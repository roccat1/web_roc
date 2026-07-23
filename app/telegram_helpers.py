"""
TELEGRAM - funciones de ayuda.

Estas funciones las usan tanto la web (para generar el codigo de
vinculacion y mostrar el estado) como bot.py (para saber que cuenta
corresponde a cada chat de Telegram y para vincular/desvincular).
"""

import random
from datetime import datetime, timedelta

from .db import get_db_connection


def generar_codigo_vinculacion(usuario_id):
    """
    Crea un codigo de 6 digitos, valido durante 10 minutos, para vincular
    la cuenta con un chat de Telegram. Borra antes cualquier codigo
    anterior de ese mismo usuario que no se haya usado.
    """
    conn = get_db_connection()
    conn.execute("DELETE FROM codigos_telegram WHERE usuario_id = ?", (usuario_id,))

    codigo = f"{random.randint(0, 999999):06d}"
    expira = (datetime.now() + timedelta(minutes=10)).isoformat()
    conn.execute(
        "INSERT INTO codigos_telegram (codigo, usuario_id, expira) VALUES (?, ?, ?)",
        (codigo, usuario_id, expira),
    )
    conn.commit()
    conn.close()
    return codigo


def codigo_vinculacion_activo(usuario_id):
    """Devuelve el codigo pendiente de un usuario si todavia no ha caducado, o None."""
    conn = get_db_connection()
    fila = conn.execute(
        "SELECT * FROM codigos_telegram WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()
    conn.close()

    if fila is None:
        return None
    if datetime.fromisoformat(fila["expira"]) < datetime.now():
        return None
    return fila["codigo"]


def vincular_chat_con_codigo(codigo, chat_id):
    """
    Intenta vincular un chat de Telegram usando un codigo generado desde la
    web. Devuelve (usuario, error): si el codigo es valido, 'usuario' es la
    fila de la tabla usuarios y 'error' es None; si no, 'usuario' es None y
    'error' explica el motivo.
    """
    conn = get_db_connection()
    fila = conn.execute("SELECT * FROM codigos_telegram WHERE codigo = ?", (codigo,)).fetchone()

    if fila is None:
        conn.close()
        return None, "Ese codigo no existe o ya se uso. Genera uno nuevo desde la web."

    if datetime.fromisoformat(fila["expira"]) < datetime.now():
        conn.execute("DELETE FROM codigos_telegram WHERE codigo = ?", (codigo,))
        conn.commit()
        conn.close()
        return None, "Ese codigo ha caducado. Genera uno nuevo desde la web."

    usuario_id = fila["usuario_id"]

    # Un mismo chat de Telegram solo puede estar vinculado a una cuenta, asi
    # que si ya estaba vinculado a otra distinta, se lo quitamos primero.
    conn.execute("UPDATE usuarios SET telegram_chat_id = NULL WHERE telegram_chat_id = ?", (chat_id,))
    conn.execute("UPDATE usuarios SET telegram_chat_id = ? WHERE id = ?", (chat_id, usuario_id))
    conn.execute("DELETE FROM codigos_telegram WHERE usuario_id = ?", (usuario_id,))
    conn.commit()

    usuario = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    conn.close()
    return usuario, None


def desvincular_telegram(usuario_id):
    conn = get_db_connection()
    conn.execute("UPDATE usuarios SET telegram_chat_id = NULL WHERE id = ?", (usuario_id,))
    conn.commit()
    conn.close()


def usuario_por_chat_id(chat_id):
    """Devuelve la fila de 'usuarios' vinculada a un chat de Telegram, o None
    si ese chat todavia no esta vinculado a ninguna cuenta."""
    conn = get_db_connection()
    usuario = conn.execute(
        "SELECT * FROM usuarios WHERE telegram_chat_id = ?", (chat_id,)
    ).fetchone()
    conn.close()
    return usuario
