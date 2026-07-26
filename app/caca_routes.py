"""
CACA - rutas: registrar (boton rapido o formulario manual), historial,
borrado, estadisticas y privacidad publico/privado del perfil.
"""

from datetime import datetime

from flask import flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection
from .caca_helpers import obtener_registros_caca, usuarios_visibles_para, puede_ver_registros_de


@app.route("/caca", methods=["GET", "POST"])
@login_requerido
def caca():
    usuario_id = session["usuario_id"]

    if request.method == "POST":
        # Esta ruta la llama el Javascript de la pagina con fetch(), no un
        # formulario clasico: por eso no redirige, solo devuelve un texto
        # y un codigo de estado. El flash se guarda igualmente, y se vera
        # la proxima vez que se cargue la pagina (el propio Javascript
        # recarga la pagina cuando la respuesta es correcta).
        fecha_texto = request.form.get("fecha_hora", "").strip()

        if not fecha_texto:
            # Boton "Registrar ahora": usamos el momento actual.
            fecha_hora = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        else:
            # Formulario manual: el input datetime-local manda
            # 'AAAA-MM-DDTHH:MM' (sin segundos).
            try:
                fecha_hora = datetime.strptime(fecha_texto, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                flash("La data no es valida.")
                return "La data no es valida.", 400

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO registros_caca (usuario_id, fecha_hora) VALUES (?, ?)",
            (usuario_id, fecha_hora),
        )
        conn.commit()
        conn.close()

        flash("Registre afegit correctament.")
        return "OK", 200

    registros = obtener_registros_caca(usuario_id)
    return render_template(
        "caca/index.html",
        registros=registros,
        ahora=datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@app.route("/caca/eliminar/<int:registro_id>", methods=["POST"])
@login_requerido
def caca_eliminar(registro_id):
    usuario_id = session["usuario_id"]
    conn = get_db_connection()
    fila = conn.execute(
        "SELECT * FROM registros_caca WHERE id = ? AND usuario_id = ?", (registro_id, usuario_id)
    ).fetchone()

    if fila is None:
        flash("Aquest registre no existeix.")
        conn.close()
        return redirect(url_for("caca"))

    conn.execute("DELETE FROM registros_caca WHERE id = ?", (registro_id,))
    conn.commit()
    conn.close()

    flash("Registre eliminat.")
    return redirect(url_for("caca"))


@app.route("/caca/estadisticas")
@login_requerido
def caca_estadisticas():
    usuario_id = session["usuario_id"]
    usuario_objetivo_id = request.args.get("usuario_id", type=int) or usuario_id

    if not puede_ver_registros_de(usuario_id, usuario_objetivo_id):
        flash("No pots veure les estadistiques d'aquest usuari.")
        usuario_objetivo_id = usuario_id

    usuarios_visibles = usuarios_visibles_para(usuario_id)
    registros = obtener_registros_caca(usuario_objetivo_id)

    conn = get_db_connection()
    fila_objetivo = conn.execute(
        "SELECT username, perfil_publico FROM usuarios WHERE id = ?", (usuario_objetivo_id,)
    ).fetchone()
    fila_propia = conn.execute(
        "SELECT perfil_publico FROM usuarios WHERE id = ?", (usuario_id,)
    ).fetchone()
    conn.close()

    return render_template(
        "caca/estadisticas.html",
        usuarios_visibles=usuarios_visibles,
        usuario_objetivo_id=usuario_objetivo_id,
        nombre_objetivo=fila_objetivo["username"],
        es_propio=(usuario_objetivo_id == usuario_id),
        perfil_publico=bool(fila_propia["perfil_publico"]),
        # sqlite3.Row no se puede convertir a JSON directamente.
        fechas_json=[fila["fecha_hora"] for fila in registros],
    )


@app.route("/caca/privacidad", methods=["POST"])
@login_requerido
def caca_privacidad():
    usuario_id = session["usuario_id"]
    nuevo_valor = 1 if request.form.get("privacidad") == "publico" else 0

    conn = get_db_connection()
    conn.execute("UPDATE usuarios SET perfil_publico = ? WHERE id = ?", (nuevo_valor, usuario_id))
    conn.commit()
    conn.close()

    flash("Privacitat actualitzada.")
    return redirect(url_for("caca_estadisticas"))
