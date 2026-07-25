"""
FINANZAS - pagina de analisis: graficos y desgloses por anio, mes,
categoria y cuenta.
"""

from flask import render_template, request, session

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection, NOMBRES_MESES


@app.route("/finanzas/analisis")
@login_requerido
def finanzas_analisis():
    usuario_id = session["usuario_id"]
    conn = get_db_connection()

    # Anios de los que hay operaciones, para rellenar el selector.
    filas_anios = conn.execute("""
        SELECT DISTINCT strftime('%Y', fecha) AS anio
        FROM operaciones
        WHERE usuario_id = ? AND tipo IN ('gasto', 'ingreso')
        ORDER BY anio DESC
    """, (usuario_id,)).fetchall()
    anios_disponibles = [fila["anio"] for fila in filas_anios]

    if not anios_disponibles:
        conn.close()
        return render_template("finanzas/analisis.html", hay_datos=False)

    # El usuario puede elegir un anio concreto o "todos" para ver el total historico.
    anio_seleccionado = request.args.get("anio")
    if anio_seleccionado not in anios_disponibles and anio_seleccionado != "todos":
        anio_seleccionado = anios_disponibles[0]

    if anio_seleccionado == "todos":
        condicion_anio = ""
        parametros_anio = []
        # Con "todos los anios" seleccionado no tiene sentido filtrar por
        # un mes concreto (mezclaria meses de anios distintos), asi que
        # el selector de mes solo aparece cuando hay un anio elegido.
        meses_disponibles = []
        mes_seleccionado = "todos"
    else:
        condicion_anio = "AND strftime('%Y', operaciones.fecha) = ?"
        parametros_anio = [anio_seleccionado]

        filas_meses_disp = conn.execute(f"""
            SELECT DISTINCT strftime('%m', fecha) AS mes
            FROM operaciones
            WHERE usuario_id = ? {condicion_anio} AND tipo IN ('gasto', 'ingreso')
            ORDER BY mes
        """, [usuario_id] + parametros_anio).fetchall()
        meses_disponibles = [fila["mes"] for fila in filas_meses_disp]

        mes_seleccionado = request.args.get("mes", "todos")
        if mes_seleccionado != "todos" and mes_seleccionado not in meses_disponibles:
            mes_seleccionado = "todos"

    # condicion_periodo/parametros_periodo = anio + mes (si se eligio uno).
    # Se usan para los totales y los desgloses. El grafico mes a mes usa
    # solo condicion_anio, para poder ver siempre los 12 meses del anio
    # aunque haya un mes concreto seleccionado.
    condicion_periodo = condicion_anio
    parametros_periodo = list(parametros_anio)
    if mes_seleccionado != "todos":
        condicion_periodo += " AND strftime('%m', operaciones.fecha) = ?"
        parametros_periodo.append(mes_seleccionado)

    if anio_seleccionado == "todos":
        etiqueta_periodo = "Todos los anios"
    elif mes_seleccionado == "todos":
        etiqueta_periodo = f"Anio {anio_seleccionado}"
    else:
        etiqueta_periodo = f"{NOMBRES_MESES[int(mes_seleccionado) - 1]} {anio_seleccionado}"

    # --- Totales del periodo elegido (anio, o anio + mes) ---
    filas_totales = conn.execute(f"""
        SELECT tipo, SUM(monto) AS total
        FROM operaciones
        WHERE usuario_id = ? {condicion_periodo} AND tipo IN ('gasto', 'ingreso')
        GROUP BY tipo
    """, [usuario_id] + parametros_periodo).fetchall()

    total_gastos = 0.0
    total_ingresos = 0.0
    for fila in filas_totales:
        if fila["tipo"] == "gasto":
            total_gastos = fila["total"]
        elif fila["tipo"] == "ingreso":
            total_ingresos = fila["total"]

    balance = total_ingresos - total_gastos
    ahorro_pct = (balance / total_ingresos * 100) if total_ingresos else 0

    # --- Desglose mes a mes del anio elegido (no se ve afectado por el
    #     filtro de mes, para poder comparar siempre los 12 meses) ---
    filas_meses = conn.execute(f"""
        SELECT strftime('%m', fecha) AS mes, tipo, SUM(monto) AS total
        FROM operaciones
        WHERE usuario_id = ? {condicion_anio} AND tipo IN ('gasto', 'ingreso')
        GROUP BY mes, tipo
    """, [usuario_id] + parametros_anio).fetchall()

    meses = []
    for numero in range(1, 13):
        clave = str(numero).zfill(2)
        meses.append({"numero": clave, "nombre": NOMBRES_MESES[numero - 1], "ingreso": 0.0, "gasto": 0.0})
    indice_meses = {mes["numero"]: mes for mes in meses}
    for fila in filas_meses:
        if fila["mes"] in indice_meses:
            indice_meses[fila["mes"]][fila["tipo"]] = fila["total"]

    meses_con_datos = sum(1 for mes in meses if mes["ingreso"] or mes["gasto"])
    gasto_medio_mensual = (total_gastos / meses_con_datos) if meses_con_datos else 0

    # --- Desglose por categoria, con sus subcategorias dentro ---
    def desglose_por_categoria(tipo):
        total_tipo = total_gastos if tipo == "gasto" else total_ingresos

        filas = conn.execute(f"""
            SELECT categorias.id AS categoria_id, categorias.nombre AS categoria, SUM(operaciones.monto) AS total
            FROM operaciones
            JOIN categorias ON categorias.id = operaciones.categoria_id
            WHERE operaciones.usuario_id = ? {condicion_periodo} AND operaciones.tipo = ?
            GROUP BY categorias.id
            ORDER BY total DESC
        """, [usuario_id] + parametros_periodo + [tipo]).fetchall()

        resultado = []
        for fila in filas:
            porcentaje = (fila["total"] / total_tipo * 100) if total_tipo else 0

            subfilas = conn.execute(f"""
                SELECT subcategorias.nombre AS subcategoria, SUM(operaciones.monto) AS total
                FROM operaciones
                JOIN subcategorias ON subcategorias.id = operaciones.subcategoria_id
                WHERE operaciones.usuario_id = ? {condicion_periodo}
                      AND operaciones.tipo = ? AND operaciones.categoria_id = ?
                GROUP BY subcategorias.id
                ORDER BY total DESC
            """, [usuario_id] + parametros_periodo + [tipo, fila["categoria_id"]]).fetchall()

            subcategorias = [
                {
                    "nombre": s["subcategoria"],
                    "total": s["total"],
                    "porcentaje": (s["total"] / total_tipo * 100) if total_tipo else 0,
                }
                for s in subfilas
            ]

            resultado.append({
                "nombre": fila["categoria"],
                "total": fila["total"],
                "porcentaje": porcentaje,
                "subcategorias": subcategorias,
            })
        return resultado

    categorias_gasto = desglose_por_categoria("gasto")
    categorias_ingreso = desglose_por_categoria("ingreso")

    # --- Gasto por cuenta ---
    filas_cuentas = conn.execute(f"""
        SELECT cuentas.nombre AS cuenta, SUM(operaciones.monto) AS total
        FROM operaciones
        JOIN cuentas ON cuentas.id = operaciones.cuenta_id
        WHERE operaciones.usuario_id = ? {condicion_periodo} AND operaciones.tipo = 'gasto'
        GROUP BY cuentas.id
        ORDER BY total DESC
    """, [usuario_id] + parametros_periodo).fetchall()

    gasto_por_cuenta = [
        {
            "nombre": f["cuenta"],
            "total": f["total"],
            "porcentaje": (f["total"] / total_gastos * 100) if total_gastos else 0,
        }
        for f in filas_cuentas
    ]

    conn.close()

    return render_template(
        "finanzas/analisis.html",
        hay_datos=True,
        anios_disponibles=anios_disponibles,
        anio_seleccionado=anio_seleccionado,
        meses_disponibles=meses_disponibles,
        mes_seleccionado=mes_seleccionado,
        nombres_meses=NOMBRES_MESES,
        etiqueta_periodo=etiqueta_periodo,
        total_gastos=total_gastos,
        total_ingresos=total_ingresos,
        balance=balance,
        ahorro_pct=ahorro_pct,
        gasto_medio_mensual=gasto_medio_mensual,
        meses=meses,
        categorias_gasto=categorias_gasto,
        categorias_ingreso=categorias_ingreso,
        gasto_por_cuenta=gasto_por_cuenta,
    )
