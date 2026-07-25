"""
Panel general ("Mi cuenta"): combina en una pantalla el resumen de
finanzas, de caducidades, el estado del bot de Telegram y el total de
registros de Caca.
"""

from flask import render_template, session

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection
from .finanzas_helpers import obtener_cuentas
from .caducidades_helpers import obtener_caducidades
from .calendario_helpers import obtener_eventos


@app.route("/dashboard")
@login_requerido
def dashboard():
    usuario_id = session["usuario_id"]

    cuentas = obtener_cuentas(usuario_id)
    saldo_total = sum(c["saldo"] for c in cuentas if not c["es_ahorro"])
    saldo_ahorros = sum(c["saldo"] for c in cuentas if c["es_ahorro"])

    items_caducidad = obtener_caducidades(usuario_id)
    resumen_caducidad = {
        "caducado": sum(1 for i in items_caducidad if i["estado"] == "caducado"),
        "proximo": sum(1 for i in items_caducidad if i["estado"] == "proximo"),
        "vigente": sum(1 for i in items_caducidad if i["estado"] == "vigente"),
    }

    eventos_futuros = obtener_eventos(usuario_id, incluir_pasados=False)
    resumen_calendario = {
        "hoy": sum(1 for e in eventos_futuros if e["estado"] == "hoy"),
        "proximo": sum(1 for e in eventos_futuros if e["estado"] == "proximo"),
    }

    conn = get_db_connection()
    fila_usuario = conn.execute(
        "SELECT telegram_chat_id FROM usuarios WHERE id = ?", (usuario_id,)
    ).fetchone()
    total_caca = conn.execute(
        "SELECT COUNT(*) AS total FROM registros_caca WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()["total"]
    conn.close()

    return render_template(
        "dashboard.html",
        username=session["username"],
        saldo_total=saldo_total,
        saldo_ahorros=saldo_ahorros,
        num_cuentas=len(cuentas),
        resumen_caducidad=resumen_caducidad,
        total_caducidades=len(items_caducidad),
        # Las 5 mas urgentes: obtener_caducidades ya las devuelve ordenadas por fecha.
        proximas_caducidades=items_caducidad[:5],
        resumen_calendario=resumen_calendario,
        total_eventos_futuros=len(eventos_futuros),
        proximos_eventos=eventos_futuros[:5],
        telegram_vinculado=bool(fila_usuario["telegram_chat_id"]),
        total_caca=total_caca,
    )
