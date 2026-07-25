"""
FINANZAS - resumen, historial y alta/baja de operaciones (gastos,
ingresos y transferencias).
"""

from datetime import date

from flask import flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection, TIPOS_OPERACION
from .finanzas_helpers import (
    obtener_cuentas,
    obtener_categorias_con_subcategorias,
    obtener_cuentas_predefinidas,
    cuenta_del_usuario,
    categoria_del_usuario,
    subcategoria_de_categoria,
)


@app.route("/finanzas")
@login_requerido
def finanzas():
    usuario_id = session["usuario_id"]
    cuentas = obtener_cuentas(usuario_id)
    # Las cuentas de ahorro se muestran aparte y no cuentan en el saldo total.
    cuentas_normales = [c for c in cuentas if not c["es_ahorro"]]
    cuentas_ahorro = [c for c in cuentas if c["es_ahorro"]]
    saldo_total = sum(c["saldo"] for c in cuentas_normales)
    saldo_ahorros = sum(c["saldo"] for c in cuentas_ahorro)

    conn = get_db_connection()
    operaciones = conn.execute("""
        SELECT operaciones.*,
               cuentas.nombre AS cuenta_nombre,
               destino.nombre AS cuenta_destino_nombre,
               categorias.nombre AS categoria_nombre,
               subcategorias.nombre AS subcategoria_nombre
        FROM operaciones
        LEFT JOIN cuentas ON cuentas.id = operaciones.cuenta_id
        LEFT JOIN cuentas AS destino ON destino.id = operaciones.cuenta_destino_id
        LEFT JOIN categorias ON categorias.id = operaciones.categoria_id
        LEFT JOIN subcategorias ON subcategorias.id = operaciones.subcategoria_id
        WHERE operaciones.usuario_id = ?
        ORDER BY operaciones.fecha DESC, operaciones.id DESC
        LIMIT 8
    """, (usuario_id,)).fetchall()
    conn.close()

    return render_template(
        "finanzas/index.html",
        cuentas=cuentas_normales,
        cuentas_ahorro=cuentas_ahorro,
        saldo_total=saldo_total,
        saldo_ahorros=saldo_ahorros,
        operaciones=operaciones,
    )


@app.route("/finanzas/operaciones")
@login_requerido
def finanzas_operaciones():
    usuario_id = session["usuario_id"]
    conn = get_db_connection()
    operaciones = conn.execute("""
        SELECT operaciones.*,
               cuentas.nombre AS cuenta_nombre,
               destino.nombre AS cuenta_destino_nombre,
               categorias.nombre AS categoria_nombre,
               subcategorias.nombre AS subcategoria_nombre
        FROM operaciones
        LEFT JOIN cuentas ON cuentas.id = operaciones.cuenta_id
        LEFT JOIN cuentas AS destino ON destino.id = operaciones.cuenta_destino_id
        LEFT JOIN categorias ON categorias.id = operaciones.categoria_id
        LEFT JOIN subcategorias ON subcategorias.id = operaciones.subcategoria_id
        WHERE operaciones.usuario_id = ?
        ORDER BY operaciones.fecha DESC, operaciones.id DESC
    """, (usuario_id,)).fetchall()
    conn.close()
    return render_template("finanzas/operaciones.html", operaciones=operaciones)


@app.route("/finanzas/operaciones/nueva", methods=["GET", "POST"])
@login_requerido
def finanzas_nueva_operacion():
    usuario_id = session["usuario_id"]
    cuentas = obtener_cuentas(usuario_id)

    if not cuentas:
        flash("Antes de crear una operacion necesitas al menos una cuenta.")
        return redirect(url_for("finanzas_cuentas"))

    if request.method == "POST":
        tipo = request.form.get("tipo")
        cuenta_id = request.form.get("cuenta_id", type=int)
        monto = request.form.get("monto", type=float)
        descripcion = request.form.get("descripcion", "").strip()
        fecha = request.form.get("fecha") or date.today().isoformat()

        errores = []

        if tipo not in TIPOS_OPERACION:
            errores.append("Elige un tipo de operacion valido.")

        cuenta = cuenta_del_usuario(cuenta_id, usuario_id) if cuenta_id else None
        if cuenta is None:
            errores.append("Elige una cuenta valida.")

        if not monto or monto <= 0:
            errores.append("El importe debe ser mayor que 0.")

        categoria_id = subcategoria_id = None
        cuenta_destino = None

        if tipo in ("gasto", "ingreso"):
            categoria_id = request.form.get("categoria_id", type=int)
            subcategoria_id = request.form.get("subcategoria_id", type=int)

            categoria = categoria_del_usuario(categoria_id, usuario_id) if categoria_id else None
            if categoria is None or categoria["tipo"] != tipo:
                errores.append("Elige una categoria valida para ese tipo de operacion.")

            subcategoria = (
                subcategoria_de_categoria(subcategoria_id, categoria_id)
                if categoria and subcategoria_id else None
            )
            if subcategoria is None:
                errores.append("Elige una subcategoria valida.")

        elif tipo == "transferencia":
            cuenta_destino_id = request.form.get("cuenta_destino_id", type=int)
            cuenta_destino = cuenta_del_usuario(cuenta_destino_id, usuario_id) if cuenta_destino_id else None
            if cuenta_destino is None:
                errores.append("Elige una cuenta destino valida.")
            elif cuenta and cuenta_destino_id == cuenta["id"]:
                errores.append("La cuenta origen y destino no pueden ser la misma.")

        if errores:
            for error in errores:
                flash(error)
            return redirect(url_for("finanzas_nueva_operacion"))

        conn = get_db_connection()

        if tipo == "gasto":
            conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?", (monto, cuenta_id))
        elif tipo == "ingreso":
            conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (monto, cuenta_id))
        elif tipo == "transferencia":
            conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?", (monto, cuenta_id))
            conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (monto, cuenta_destino["id"]))

        conn.execute("""
            INSERT INTO operaciones
                (usuario_id, tipo, cuenta_id, cuenta_destino_id, categoria_id, subcategoria_id, monto, descripcion, fecha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            usuario_id, tipo, cuenta_id,
            cuenta_destino["id"] if cuenta_destino else None,
            categoria_id, subcategoria_id,
            monto, descripcion, fecha,
        ))
        conn.commit()
        conn.close()

        flash("Operacion guardada correctamente.")
        return redirect(url_for("finanzas"))

    # GET: preparamos los datos que necesita el formulario
    categorias = obtener_categorias_con_subcategorias(usuario_id)
    predefinidas = obtener_cuentas_predefinidas(usuario_id)

    return render_template(
        "finanzas/nueva_operacion.html",
        cuentas=cuentas,
        # Los objetos Row de sqlite3 no se pueden convertir a JSON
        # directamente (los usa el modo guiado, en Javascript).
        cuentas_json=[{"id": c["id"], "nombre": c["nombre"]} for c in cuentas],
        categorias=categorias,
        predefinidas=predefinidas,
        hoy=date.today().isoformat(),
    )


@app.route("/finanzas/operaciones/<int:operacion_id>/editar", methods=["GET", "POST"])
@login_requerido
def finanzas_editar_operacion(operacion_id):
    usuario_id = session["usuario_id"]
    conn = get_db_connection()
    operacion = conn.execute(
        "SELECT * FROM operaciones WHERE id = ? AND usuario_id = ?",
        (operacion_id, usuario_id),
    ).fetchone()

    if operacion is None:
        conn.close()
        flash("Esa operacion no existe.")
        return redirect(url_for("finanzas_operaciones"))

    cuentas = obtener_cuentas(usuario_id)

    if request.method == "POST":
        # El campo oculto "origen" dice si se llego aqui desde el resumen
        # de Finanzas o desde el historial completo (el referrer del POST
        # seria esta misma pagina de edicion, asi que no sirve para saberlo).
        if request.form.get("origen") == "finanzas":
            destino = url_for("finanzas")
        else:
            destino = url_for("finanzas_operaciones")

        tipo = request.form.get("tipo")
        cuenta_id = request.form.get("cuenta_id", type=int)
        monto = request.form.get("monto", type=float)
        descripcion = request.form.get("descripcion", "").strip()
        fecha = request.form.get("fecha") or date.today().isoformat()

        errores = []

        if tipo not in TIPOS_OPERACION:
            errores.append("Elige un tipo de operacion valido.")

        cuenta = cuenta_del_usuario(cuenta_id, usuario_id) if cuenta_id else None
        if cuenta is None:
            errores.append("Elige una cuenta valida.")

        if not monto or monto <= 0:
            errores.append("El importe debe ser mayor que 0.")

        categoria_id = subcategoria_id = None
        cuenta_destino = None

        if tipo in ("gasto", "ingreso"):
            categoria_id = request.form.get("categoria_id", type=int)
            subcategoria_id = request.form.get("subcategoria_id", type=int)

            categoria = categoria_del_usuario(categoria_id, usuario_id) if categoria_id else None
            if categoria is None or categoria["tipo"] != tipo:
                errores.append("Elige una categoria valida para ese tipo de operacion.")

            subcategoria = (
                subcategoria_de_categoria(subcategoria_id, categoria_id)
                if categoria and subcategoria_id else None
            )
            if subcategoria is None:
                errores.append("Elige una subcategoria valida.")

        elif tipo == "transferencia":
            cuenta_destino_id = request.form.get("cuenta_destino_id", type=int)
            cuenta_destino = cuenta_del_usuario(cuenta_destino_id, usuario_id) if cuenta_destino_id else None
            if cuenta_destino is None:
                errores.append("Elige una cuenta destino valida.")
            elif cuenta and cuenta_destino_id == cuenta["id"]:
                errores.append("La cuenta origen y destino no pueden ser la misma.")

        if errores:
            for error in errores:
                flash(error)
            conn.close()
            return redirect(url_for("finanzas_editar_operacion", operacion_id=operacion_id))

        # Primero deshacemos el efecto que tenia la operacion tal como
        # estaba guardada, y despues aplicamos el efecto de los datos
        # nuevos. Asi el saldo de las cuentas queda igual de correcto
        # tanto si solo cambia el importe como si cambia de cuenta o de tipo.
        if operacion["tipo"] == "gasto":
            conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?",
                          (operacion["monto"], operacion["cuenta_id"]))
        elif operacion["tipo"] == "ingreso":
            conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?",
                          (operacion["monto"], operacion["cuenta_id"]))
        elif operacion["tipo"] == "transferencia":
            conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?",
                          (operacion["monto"], operacion["cuenta_id"]))
            conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?",
                          (operacion["monto"], operacion["cuenta_destino_id"]))

        if tipo == "gasto":
            conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?", (monto, cuenta_id))
        elif tipo == "ingreso":
            conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (monto, cuenta_id))
        elif tipo == "transferencia":
            conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?", (monto, cuenta_id))
            conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (monto, cuenta_destino["id"]))

        conn.execute("""
            UPDATE operaciones
            SET tipo = ?, cuenta_id = ?, cuenta_destino_id = ?, categoria_id = ?,
                subcategoria_id = ?, monto = ?, descripcion = ?, fecha = ?
            WHERE id = ?
        """, (
            tipo, cuenta_id,
            cuenta_destino["id"] if cuenta_destino else None,
            categoria_id, subcategoria_id,
            monto, descripcion, fecha,
            operacion_id,
        ))
        conn.commit()
        conn.close()

        flash("Operacion actualizada.")
        return redirect(destino)

    # GET: preparamos los datos que necesita el formulario
    categorias = obtener_categorias_con_subcategorias(usuario_id)
    conn.close()

    origen = "finanzas" if request.referrer and request.referrer.rstrip("/").endswith("/finanzas") else "operaciones"

    return render_template(
        "finanzas/editar_operacion.html",
        operacion=operacion,
        cuentas=cuentas,
        categorias=categorias,
        origen=origen,
    )



@app.route("/finanzas/operaciones/<int:operacion_id>/eliminar", methods=["POST"])
@login_requerido
def finanzas_eliminar_operacion(operacion_id):
    usuario_id = session["usuario_id"]
    conn = get_db_connection()
    operacion = conn.execute(
        "SELECT * FROM operaciones WHERE id = ? AND usuario_id = ?",
        (operacion_id, usuario_id),
    ).fetchone()

    # Si el borrado se hizo desde el resumen de Finanzas, volvemos ahi;
    # en cualquier otro caso (o si no hay referrer), al historial completo.
    if request.referrer and request.referrer.rstrip("/").endswith("/finanzas"):
        destino = url_for("finanzas")
    else:
        destino = url_for("finanzas_operaciones")

    if operacion is None:
        flash("Esa operacion no existe.")
        conn.close()
        return redirect(destino)

    # Deshacemos el efecto que tuvo la operacion sobre los saldos
    if operacion["tipo"] == "gasto":
        conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?",
                      (operacion["monto"], operacion["cuenta_id"]))
    elif operacion["tipo"] == "ingreso":
        conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?",
                      (operacion["monto"], operacion["cuenta_id"]))
    elif operacion["tipo"] == "transferencia":
        conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?",
                      (operacion["monto"], operacion["cuenta_id"]))
        conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?",
                      (operacion["monto"], operacion["cuenta_destino_id"]))

    conn.execute("DELETE FROM operaciones WHERE id = ?", (operacion_id,))
    conn.commit()
    conn.close()

    flash("Operacion eliminada.")
    return redirect(destino)
