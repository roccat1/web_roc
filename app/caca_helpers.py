"""
CACA - funciones de ayuda: lectura de registros y calculo de que
usuarios puede ver cada uno (perfil publico/privado).
"""

from .db import get_db_connection


def obtener_registros_caca(usuario_id):
    """Devuelve todos los registros de un usuario, del mas reciente al mas antiguo."""
    conn = get_db_connection()
    filas = conn.execute(
        "SELECT * FROM registros_caca WHERE usuario_id = ? ORDER BY fecha_hora DESC",
        (usuario_id,),
    ).fetchall()
    conn.close()
    return filas


def usuarios_visibles_para(usuario_id):
    """
    Devuelve los usuarios cuyas estadisticas puede ver este usuario: el
    propio, mas cualquiera que tenga el perfil marcado como publico.
    """
    conn = get_db_connection()
    filas = conn.execute(
        "SELECT id, username FROM usuarios WHERE perfil_publico = 1 OR id = ? ORDER BY username",
        (usuario_id,),
    ).fetchall()
    conn.close()
    return filas


def puede_ver_registros_de(usuario_id_viendo, usuario_id_objetivo):
    """Un usuario siempre puede ver los suyos propios; los de otro usuario
    solo si ese otro tiene el perfil publico."""
    if usuario_id_viendo == usuario_id_objetivo:
        return True
    conn = get_db_connection()
    fila = conn.execute("SELECT perfil_publico FROM usuarios WHERE id = ?", (usuario_id_objetivo,)).fetchone()
    conn.close()
    return bool(fila and fila["perfil_publico"])
