"""
FINANZAS - gestion de cuentas: crear, editar, eliminar y elegir las
cuentas predefinidas para cada tipo de operacion.
"""

from flask import flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection, TIPOS_OPERACION
from .finanzas_helpers import obtener_cuentas, obtener_cuentas_predefinidas, cuenta_del_usuario


@app.route("/finanzas/cuentas")
@login_requerido
def finanzas_cuentas():
    usuario_id = session["usuario_id"]
    cuentas = obtener_cuentas(usuario_id)
    predefinidas = obtener_cuentas_predefinidas(usuario_id)
    return render_template(
        "finanzas/cuentas.html",
        cuentas=cuentas,
        predefinidas=predefinidas,
    )


@app.route("/finanzas/cuentas/nueva", methods=["POST"])
@login_requerido
def finanzas_nueva_cuenta():
    usuario_id = session["usuario_id"]
    nombre = request.form.get("nombre", "").strip()
    saldo_inicial = request.form.get("saldo_inicial", type=float) or 0
    es_ahorro = 1 if request.form.get("es_ahorro") else 0

    if not nombre:
        flash("Escriu un nom per al compte.")
        return redirect(url_for("finanzas_cuentas"))

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO cuentas (usuario_id, nombre, saldo, es_ahorro) VALUES (?, ?, ?, ?)",
        (usuario_id, nombre, saldo_inicial, es_ahorro),
    )
    conn.commit()
    conn.close()

    flash(f"Compte '{nombre}' creat.")
    return redirect(url_for("finanzas_cuentas"))


@app.route("/finanzas/cuentas/<int:cuenta_id>/editar", methods=["GET", "POST"])
@login_requerido
def finanzas_editar_cuenta(cuenta_id):
    usuario_id = session["usuario_id"]
    cuenta = cuenta_del_usuario(cuenta_id, usuario_id)
    if cuenta is None:
        flash("Aquest compte no existeix.")
        return redirect(url_for("finanzas_cuentas"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        saldo = request.form.get("saldo", type=float)
        es_ahorro = 1 if request.form.get("es_ahorro") else 0

        if not nombre or saldo is None:
            flash("Escriu un nom i un saldo valids.")
            return redirect(url_for("finanzas_editar_cuenta", cuenta_id=cuenta_id))

        conn = get_db_connection()
        conn.execute(
            "UPDATE cuentas SET nombre = ?, saldo = ?, es_ahorro = ? WHERE id = ?",
            (nombre, saldo, es_ahorro, cuenta_id),
        )
        conn.commit()
        conn.close()

        flash("Compte actualitzat.")
        return redirect(url_for("finanzas_cuentas"))

    return render_template("finanzas/editar_cuenta.html", cuenta=cuenta)


@app.route("/finanzas/cuentas/<int:cuenta_id>/eliminar", methods=["POST"])
@login_requerido
def finanzas_eliminar_cuenta(cuenta_id):
    usuario_id = session["usuario_id"]
    cuenta = cuenta_del_usuario(cuenta_id, usuario_id)
    if cuenta is None:
        flash("Aquest compte no existeix.")
        return redirect(url_for("finanzas_cuentas"))

    conn = get_db_connection()
    en_uso = conn.execute(
        "SELECT COUNT(*) AS total FROM operaciones WHERE cuenta_id = ? OR cuenta_destino_id = ?",
        (cuenta_id, cuenta_id),
    ).fetchone()["total"]

    if en_uso > 0:
        flash("No es pot eliminar: hi ha operacions associades a aquest compte.")
        conn.close()
        return redirect(url_for("finanzas_cuentas"))

    conn.execute("DELETE FROM cuentas_predefinidas WHERE cuenta_id = ?", (cuenta_id,))
    conn.execute("DELETE FROM cuentas WHERE id = ?", (cuenta_id,))
    conn.commit()
    conn.close()

    flash("Compte eliminat.")
    return redirect(url_for("finanzas_cuentas"))


@app.route("/finanzas/cuentas/predefinidas", methods=["POST"])
@login_requerido
def finanzas_guardar_predefinidas():
    usuario_id = session["usuario_id"]
    conn = get_db_connection()

    for tipo in TIPOS_OPERACION:
        cuenta_id = request.form.get(f"predefinida_{tipo}", type=int)
        conn.execute(
            "DELETE FROM cuentas_predefinidas WHERE usuario_id = ? AND tipo_operacion = ?",
            (usuario_id, tipo),
        )
        if cuenta_id:
            conn.execute(
                "INSERT INTO cuentas_predefinidas (usuario_id, tipo_operacion, cuenta_id) VALUES (?, ?, ?)",
                (usuario_id, tipo, cuenta_id),
            )

    conn.commit()
    conn.close()

    flash("Comptes predefinits desats.")
    return redirect(url_for("finanzas_cuentas"))
