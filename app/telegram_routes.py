"""
TELEGRAM - rutas web para vincular y desvincular la cuenta desde el
navegador (generan/consumen el codigo de un solo uso).
"""

from flask import flash, redirect, render_template, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection
from .telegram_helpers import (
    generar_codigo_vinculacion,
    codigo_vinculacion_activo,
    desvincular_telegram,
)


@app.route("/telegram")
@login_requerido
def telegram():
    usuario_id = session["usuario_id"]
    conn = get_db_connection()
    usuario = conn.execute(
        "SELECT telegram_chat_id FROM usuarios WHERE id = ?", (usuario_id,)
    ).fetchone()
    conn.close()

    return render_template(
        "telegram.html",
        vinculado=bool(usuario["telegram_chat_id"]),
        codigo=codigo_vinculacion_activo(usuario_id),
    )


@app.route("/telegram/generar", methods=["POST"])
@login_requerido
def telegram_generar():
    generar_codigo_vinculacion(session["usuario_id"])
    return redirect(url_for("telegram"))


@app.route("/telegram/desvincular", methods=["POST"])
@login_requerido
def telegram_desvincular():
    desvincular_telegram(session["usuario_id"])
    flash("Compte de Telegram desvinculat.")
    return redirect(url_for("telegram"))
