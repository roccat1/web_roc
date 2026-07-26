"""
CADUCIDADES - funciones de ayuda.

Calculo del estado (caducado / proximo / vigente) de cada registro,
lectura y validacion del formulario. Las usan tanto las rutas web como
el dashboard y el bot de Telegram.
"""

from datetime import date

from .db import get_db_connection, COLOR_LED_POR_ESTADO


def calcular_estado_caducidad(fecha_caducidad, aviso_dias):
    """
    Compara una fecha de caducidad con el dia de hoy y devuelve un
    diccionario con:
    - estado: 'caducado', 'proximo' o 'vigente'
    - dias: dias que faltan (numero negativo si ya caduco)
    - texto: frase lista para mostrar, ej. "Caduca en 12 dias"
    """
    hoy = date.today()
    dias = (fecha_caducidad - hoy).days
    palabra = "dia" if abs(dias) == 1 else "dies"

    if dias < 0:
        return {"estado": "caducado", "dias": dias, "texto": f"Va caducar fa {abs(dias)} {palabra}"}
    if dias == 0:
        return {"estado": "proximo", "dias": dias, "texto": "Caduca avui"}
    if dias <= aviso_dias:
        return {"estado": "proximo", "dias": dias, "texto": f"Caduca d'aqui a {dias} {palabra}"}
    return {"estado": "vigente", "dias": dias, "texto": f"Caduca d'aqui a {dias} {palabra}"}


def obtener_caducidades(usuario_id):
    """Devuelve todas las fechas de caducidad del usuario, ordenadas de la
    mas urgente a la menos urgente, cada una con su estado ya calculado."""
    conn = get_db_connection()
    filas = conn.execute(
        "SELECT * FROM caducidades WHERE usuario_id = ? ORDER BY fecha_caducidad ASC",
        (usuario_id,),
    ).fetchall()
    conn.close()

    resultado = []
    for fila in filas:
        fecha = date.fromisoformat(fila["fecha_caducidad"])
        info = calcular_estado_caducidad(fecha, fila["aviso_dias"])
        resultado.append({
            "id": fila["id"],
            "nombre": fila["nombre"],
            "categoria": fila["categoria"],
            "fecha_caducidad": fila["fecha_caducidad"],
            "aviso_dias": fila["aviso_dias"],
            "dias_revalidacion": fila["dias_revalidacion"],
            "notas": fila["notas"],
            "estado": info["estado"],
            "dias": info["dias"],
            "texto_estado": info["texto"],
            "led": COLOR_LED_POR_ESTADO[info["estado"]],
            "aviso_proximo_enviado": bool(fila["aviso_proximo_enviado"]),
            "aviso_caducado_enviado": bool(fila["aviso_caducado_enviado"]),
        })
    return resultado


def caducidad_del_usuario(caducidad_id, usuario_id):
    """Comprueba que un registro existe y pertenece al usuario. Devuelve la fila o None."""
    conn = get_db_connection()
    caducidad = conn.execute(
        "SELECT * FROM caducidades WHERE id = ? AND usuario_id = ?", (caducidad_id, usuario_id)
    ).fetchone()
    conn.close()
    return caducidad


def marcar_aviso_enviado(caducidad_id, tipo_aviso):
    """
    Marca que ya se envio por Telegram el aviso de tipo 'proximo' o
    'caducado' para un registro, para no volver a avisar de lo mismo
    hasta que se revalide o se edite la fecha.
    """
    columna = "aviso_proximo_enviado" if tipo_aviso == "proximo" else "aviso_caducado_enviado"
    conn = get_db_connection()
    conn.execute(f"UPDATE caducidades SET {columna} = 1 WHERE id = ?", (caducidad_id,))
    conn.commit()
    conn.close()


def validar_formulario_caducidad(form):
    """Valida y devuelve los datos del formulario de crear/editar una
    caducidad. Devuelve (datos, errores)."""
    nombre = form.get("nombre", "").strip()
    categoria = form.get("categoria", "").strip() or "Altres"
    fecha_texto = form.get("fecha_caducidad", "").strip()
    aviso_dias = form.get("aviso_dias", type=int)
    dias_revalidacion = form.get("dias_revalidacion", type=int)
    notas = form.get("notas", "").strip()

    errores = []
    if not nombre:
        errores.append("Escriu un nom.")

    if not fecha_texto:
        errores.append("Tria una data de caducitat.")
    else:
        try:
            date.fromisoformat(fecha_texto)
        except ValueError:
            errores.append("La data no es valida.")

    if aviso_dias is None or aviso_dias < 0:
        aviso_dias = 30

    # 0 o un numero negativo equivale a "no configurado" (no debe aparecer
    # el boton de revalidar para ese registro).
    if dias_revalidacion is not None and dias_revalidacion <= 0:
        dias_revalidacion = None

    datos = {
        "nombre": nombre,
        "categoria": categoria,
        "fecha_caducidad": fecha_texto,
        "aviso_dias": aviso_dias,
        "dias_revalidacion": dias_revalidacion,
        "notas": notas,
    }
    return datos, errores
