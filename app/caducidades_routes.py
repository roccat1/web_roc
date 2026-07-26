"""
CADUCIDADES - rutas: listado con filtros, alta, edicion, borrado y
revalidacion rapida de una fecha de caducidad.
"""

from datetime import date, timedelta

from flask import flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection, CATEGORIAS_CADUCIDAD_SUGERIDAS
from .caducidades_helpers import (
    obtener_caducidades,
    caducidad_del_usuario,
    validar_formulario_caducidad,
)


@app.route("/caducidades")
@login_requerido
def caducidades():
    usuario_id = session["usuario_id"]
    items = obtener_caducidades(usuario_id)

    categoria_filtro = request.args.get("categoria", "")
    estado_filtro = request.args.get("estado", "")

    categorias_usadas = sorted({item["categoria"] for item in items})

    items_filtrados = items
    if categoria_filtro:
        items_filtrados = [i for i in items_filtrados if i["categoria"] == categoria_filtro]
    if estado_filtro in ("caducado", "proximo", "vigente"):
        items_filtrados = [i for i in items_filtrados if i["estado"] == estado_filtro]

    resumen = {
        "caducado": sum(1 for i in items if i["estado"] == "caducado"),
        "proximo": sum(1 for i in items if i["estado"] == "proximo"),
        "vigente": sum(1 for i in items if i["estado"] == "vigente"),
    }

    return render_template(
        "caducidades/index.html",
        items=items_filtrados,
        resumen=resumen,
        categorias_usadas=categorias_usadas,
        categoria_filtro=categoria_filtro,
        estado_filtro=estado_filtro,
        total_items=len(items),
    )


@app.route("/caducidades/nueva", methods=["GET", "POST"])
@login_requerido
def caducidades_nueva():
    usuario_id = session["usuario_id"]

    if request.method == "POST":
        datos, errores = validar_formulario_caducidad(request.form)

        if errores:
            for error in errores:
                flash(error)
            return redirect(url_for("caducidades_nueva"))

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO caducidades (usuario_id, nombre, categoria, fecha_caducidad, aviso_dias, dias_revalidacion, notas)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            usuario_id, datos["nombre"], datos["categoria"],
            datos["fecha_caducidad"], datos["aviso_dias"], datos["dias_revalidacion"], datos["notas"],
        ))
        conn.commit()
        conn.close()

        flash(f"'{datos['nombre']}' afegit correctament.")
        return redirect(url_for("caducidades"))

    return render_template(
        "caducidades/nueva.html",
        categorias_sugeridas=CATEGORIAS_CADUCIDAD_SUGERIDAS,
        hoy=date.today().isoformat(),
    )


@app.route("/caducidades/<int:caducidad_id>/editar", methods=["GET", "POST"])
@login_requerido
def caducidades_editar(caducidad_id):
    usuario_id = session["usuario_id"]
    item = caducidad_del_usuario(caducidad_id, usuario_id)
    if item is None:
        flash("Aquest registre no existeix.")
        return redirect(url_for("caducidades"))

    if request.method == "POST":
        datos, errores = validar_formulario_caducidad(request.form)

        if errores:
            for error in errores:
                flash(error)
            return redirect(url_for("caducidades_editar", caducidad_id=caducidad_id))

        conn = get_db_connection()
        conn.execute("""
            UPDATE caducidades
            SET nombre = ?, categoria = ?, fecha_caducidad = ?, aviso_dias = ?, dias_revalidacion = ?, notas = ?,
                aviso_proximo_enviado = 0, aviso_caducado_enviado = 0
            WHERE id = ?
        """, (
            datos["nombre"], datos["categoria"], datos["fecha_caducidad"],
            datos["aviso_dias"], datos["dias_revalidacion"], datos["notas"], caducidad_id,
        ))
        conn.commit()
        conn.close()

        flash("Registre actualitzat.")
        return redirect(url_for("caducidades"))

    return render_template(
        "caducidades/editar.html",
        item=item,
        categorias_sugeridas=CATEGORIAS_CADUCIDAD_SUGERIDAS,
    )


@app.route("/caducidades/<int:caducidad_id>/eliminar", methods=["POST"])
@login_requerido
def caducidades_eliminar(caducidad_id):
    usuario_id = session["usuario_id"]
    item = caducidad_del_usuario(caducidad_id, usuario_id)
    if item is None:
        flash("Aquest registre no existeix.")
        return redirect(url_for("caducidades"))

    conn = get_db_connection()
    conn.execute("DELETE FROM caducidades WHERE id = ?", (caducidad_id,))
    conn.commit()
    conn.close()

    flash(f"'{item['nombre']}' eliminat.")
    return redirect(url_for("caducidades"))


@app.route("/caducidades/<int:caducidad_id>/revalidar", methods=["POST"])
@login_requerido
def caducidades_revalidar(caducidad_id):
    """Pone la fecha de caducidad en 'hoy + dias_revalidacion', usando el
    numero de dias que se configuro al crear (o editar) el registro."""
    usuario_id = session["usuario_id"]
    item = caducidad_del_usuario(caducidad_id, usuario_id)
    if item is None:
        flash("Aquest registre no existeix.")
        return redirect(url_for("caducidades"))

    dias = item["dias_revalidacion"]
    if not dias:
        flash("Aquest registre no te un temps de revalidacio configurat. Edita'l per afegir-lo.")
        return redirect(url_for("caducidades"))

    nueva_fecha = date.today() + timedelta(days=dias)

    conn = get_db_connection()
    conn.execute(
        "UPDATE caducidades SET fecha_caducidad = ?, aviso_proximo_enviado = 0, aviso_caducado_enviado = 0 WHERE id = ?",
        (nueva_fecha.isoformat(), caducidad_id),
    )
    conn.commit()
    conn.close()

    flash(f"'{item['nombre']}' revalidat. Nova data de caducitat: {nueva_fecha.isoformat()}.")
    return redirect(url_for("caducidades"))
