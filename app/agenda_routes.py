"""
AGENDA - vista combinada dels propers esdeveniments del calendari i les
properes caducitats en una sola linia de temps, agrupada per data
relativa (Avui, Dema, Aquesta setmana...). Nomes mira cap endavant
(inclou el que ja ha vençut/passat pero no s'ha resolt) fins a un
horitzo de 60 dies, perque no es converteixi en una llista interminable
amb caducitats a anys vista.
"""

from datetime import date

from flask import render_template, session

from . import app
from .auth_utils import login_requerido
from .calendario_helpers import obtener_eventos
from .caducidades_helpers import obtener_caducidades

HORIZONTE_DIAS = 60

_GRUPOS_ORDEN = ("pasado", "hoy", "manana", "semana", "mes")
_GRUPOS_ETIQUETA = {
    "pasado": "Pendent (ja hauria de ser fet)",
    "hoy": "Avui",
    "manana": "Dema",
    "semana": "Aquesta setmana",
    "mes": "Aquest mes",
}


def _grupo_de(dias):
    if dias < 0:
        return "pasado"
    if dias == 0:
        return "hoy"
    if dias == 1:
        return "manana"
    if dias <= 7:
        return "semana"
    return "mes"


def _agrupar_por_fecha_relativa(items):
    grupos = {clave: [] for clave in _GRUPOS_ORDEN}
    for item in items:
        grupos[_grupo_de(item["dias"])].append(item)
    return [
        {"clave": clave, "etiqueta": _GRUPOS_ETIQUETA[clave], "items": grupos[clave]}
        for clave in _GRUPOS_ORDEN if grupos[clave]
    ]


@app.route("/agenda")
@login_requerido
def agenda():
    usuario_id = session["usuario_id"]

    items = []
    for evento in obtener_eventos(usuario_id, incluir_pasados=True):
        if evento["dias"] > HORIZONTE_DIAS:
            continue
        items.append({
            "tipo": "evento",
            "id": evento["id"],
            "titulo": evento["titulo"],
            "subtitulo": evento["categoria_nombre"],
            "fecha": evento["fecha_ocurrencia"],
            "hora": evento["hora"],
            "hora_fin": evento["hora_fin"],
            "dias": evento["dias"],
            "texto_estado": evento["texto_estado"],
            "led": evento["led"],
        })

    for caducidad in obtener_caducidades(usuario_id):
        if caducidad["dias"] > HORIZONTE_DIAS:
            continue
        items.append({
            "tipo": "caducitat",
            "id": caducidad["id"],
            "titulo": caducidad["nombre"],
            "subtitulo": caducidad["categoria"],
            "fecha": caducidad["fecha_caducidad"],
            "hora": None,
            "hora_fin": None,
            "dias": caducidad["dias"],
            "texto_estado": caducidad["texto_estado"],
            "led": caducidad["led"],
        })

    items.sort(key=lambda i: (i["fecha"], i["hora"] or "00:00"))

    return render_template(
        "agenda.html",
        grupos=_agrupar_por_fecha_relativa(items),
        horizonte_dias=HORIZONTE_DIAS,
        hoy=date.today().isoformat(),
    )
