"""
CALENDARIO - integracion con Google Calendar: conectar/desconectar la
cuenta y elegir que calendarios de Google se sincronizan (cada uno se
convierte en una categoria del calendario de la app).

La sincronizacion de verdad (subir y bajar eventos) la hace un job en
segundo plano configurado en app/__init__.py, mas los "push_*" que se
llaman al momento desde calendario_routes.py al guardar algo. Estas
rutas solo gestionan la conexion y la seleccion de calendarios.
"""

from flask import flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_SYNC_INTERVALO_MINUTOS
from .google_calendar_helpers import (
    construir_flow,
    guardar_credenciales,
    cuenta_conectada,
    desconectar,
    listar_calendarios_google,
    guardar_seleccion_calendarios,
    obtener_calendarios_vinculados,
)


@app.route("/calendario/google")
@login_requerido
def calendario_google():
    usuario_id = session["usuario_id"]
    return render_template(
        "calendario/google.html",
        google_configurado=bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        conectado=cuenta_conectada(usuario_id),
        calendarios=obtener_calendarios_vinculados(usuario_id),
        intervalo_minutos=GOOGLE_SYNC_INTERVALO_MINUTOS,
    )


@app.route("/calendario/google/conectar")
@login_requerido
def calendario_google_conectar():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        flash(
            "Falta configurar GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET a l'.env abans de poder "
            "connectar amb Google Calendar (mira el README per als passos)."
        )
        return redirect(url_for("calendario_google"))

    redirect_uri = url_for("calendario_google_callback", _external=True)
    flow = construir_flow(redirect_uri)
    # prompt="consent" fuerza a Google a devolver siempre un
    # refresh_token, incluso si el usuario ya habia dado permiso antes
    # (si no, solo lo manda la primera vez).
    url_autorizacion, estado = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    session["google_oauth_state"] = estado
    return redirect(url_autorizacion)


@app.route("/calendario/google/callback")
@login_requerido
def calendario_google_callback():
    usuario_id = session["usuario_id"]

    if request.args.get("error"):
        flash("S'ha cancel·lat la connexio amb Google Calendar.")
        return redirect(url_for("calendario_google"))

    estado = session.pop("google_oauth_state", None)
    redirect_uri = url_for("calendario_google_callback", _external=True)
    flow = construir_flow(redirect_uri, estado=estado)

    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as error:
        print(f"[google-sync] Error completando el login OAuth: {error}")
        flash("No s'ha pogut completar la connexio amb Google. Torna-ho a provar.")
        return redirect(url_for("calendario_google"))

    guardar_credenciales(usuario_id, flow.credentials)
    flash("Compte de Google connectat. Ara tria quins calendaris vols sincronitzar.")
    return redirect(url_for("calendario_google_calendarios"))


@app.route("/calendario/google/desconectar", methods=["POST"])
@login_requerido
def calendario_google_desconectar():
    usuario_id = session["usuario_id"]
    desconectar(usuario_id)
    flash(
        "S'ha desconnectat el compte de Google. Les categories i esdeveniments ja importats "
        "es queden tal com estaven, pero deixaran de sincronitzar-se."
    )
    return redirect(url_for("calendario_google"))


@app.route("/calendario/google/calendarios")
@login_requerido
def calendario_google_calendarios():
    usuario_id = session["usuario_id"]
    if not cuenta_conectada(usuario_id):
        flash("Primer connecta el teu compte de Google.")
        return redirect(url_for("calendario_google"))

    calendarios = listar_calendarios_google(usuario_id)
    if calendarios is None:
        flash("No s'ha pogut contactar amb Google ara mateix. Torna-ho a provar en un moment.")
        return redirect(url_for("calendario_google"))

    vinculados = {c["google_calendar_id"]: c for c in obtener_calendarios_vinculados(usuario_id)}
    return render_template(
        "calendario/google_calendarios.html",
        calendarios=calendarios,
        vinculados=vinculados,
    )


@app.route("/calendario/google/calendarios/guardar", methods=["POST"])
@login_requerido
def calendario_google_calendarios_guardar():
    usuario_id = session["usuario_id"]
    ids_marcados = set(request.form.getlist("sincronizar"))

    if not guardar_seleccion_calendarios(usuario_id, ids_marcados):
        flash("No s'ha pogut contactar amb Google ara mateix. Torna-ho a provar en un moment.")
        return redirect(url_for("calendario_google"))

    flash(
        "Preferencies guardades. Els calendaris marcats es sincronitzaran automaticament en "
        "segon pla (i cada vegada que crees o edites un esdeveniment)."
    )
    return redirect(url_for("calendario_google"))
