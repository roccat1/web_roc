"""
FINANZAS - funciones de ayuda.

Funciones compartidas por las rutas de finanzas (y por el dashboard y
el bot de Telegram) para leer cuentas, categorias, subcategorias y las
cuentas predefinidas de un usuario.
"""

from .db import get_db_connection


def obtener_cuentas(usuario_id):
    conn = get_db_connection()
    cuentas = conn.execute(
        "SELECT * FROM cuentas WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
    ).fetchall()
    conn.close()
    return cuentas


def obtener_categorias_con_subcategorias(usuario_id):
    """Devuelve una lista de categorias, cada una con su lista de subcategorias.
    Se usa tanto para mostrar la pagina de categorias como para mandar los
    datos a Javascript en el formulario de nueva operacion."""
    conn = get_db_connection()
    categorias = conn.execute(
        "SELECT * FROM categorias WHERE usuario_id = ? ORDER BY tipo, nombre",
        (usuario_id,),
    ).fetchall()

    resultado = []
    for cat in categorias:
        subs = conn.execute(
            "SELECT * FROM subcategorias WHERE categoria_id = ? ORDER BY nombre",
            (cat["id"],),
        ).fetchall()
        resultado.append({
            "id": cat["id"],
            "nombre": cat["nombre"],
            "tipo": cat["tipo"],
            "subcategorias": [{"id": s["id"], "nombre": s["nombre"]} for s in subs],
        })
    conn.close()
    return resultado


def obtener_cuentas_predefinidas(usuario_id):
    """Devuelve un diccionario {tipo_operacion: cuenta_id} con las cuentas
    predefinidas del usuario."""
    conn = get_db_connection()
    filas = conn.execute(
        "SELECT tipo_operacion, cuenta_id FROM cuentas_predefinidas WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    conn.close()
    return {fila["tipo_operacion"]: fila["cuenta_id"] for fila in filas}


def cuenta_del_usuario(cuenta_id, usuario_id):
    """Comprueba que una cuenta existe y pertenece al usuario. Devuelve la fila o None."""
    conn = get_db_connection()
    cuenta = conn.execute(
        "SELECT * FROM cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id)
    ).fetchone()
    conn.close()
    return cuenta


def categoria_del_usuario(categoria_id, usuario_id):
    conn = get_db_connection()
    categoria = conn.execute(
        "SELECT * FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
    ).fetchone()
    conn.close()
    return categoria


def subcategoria_de_categoria(subcategoria_id, categoria_id):
    conn = get_db_connection()
    subcategoria = conn.execute(
        "SELECT * FROM subcategorias WHERE id = ? AND categoria_id = ?",
        (subcategoria_id, categoria_id),
    ).fetchone()
    conn.close()
    return subcategoria

