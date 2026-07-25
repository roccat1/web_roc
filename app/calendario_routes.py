"""
CALENDARIO - rutas: vista mensual (con navegacion entre meses), vista
de lista con filtros, alta, edicion y borrado de eventos, y gestion de
las categorias del calendario (crear, editar, eliminar).
"""

import calendar as calendario_std
from datetime import date

from flask import flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection, COLORES_CALENDARIO, OPCIONES_REPETICION_CALENDARIO
from .calendario_helpers import (
    obtener_eventos,
    eventos_del_mes,
    evento_del_usuario,
    validar_formulario_evento,
    obtener_categorias_calendario,
    categoria_calendario_del_usuario,
)

NOMBRES_MESES_CALENDARIO = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
NOMBRES_DIAS_SEMANA = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]


def _categoria_id_valida(categoria_id, usuario_id):
    """Comprueba que la categoria elegida en el formulario existe y es
    del usuario; si no, devuelve None (el evento se guarda sin categoria
    en vez de dar un error)."""
    if not categoria_id:
        return None
    return categoria_id if categoria_calendario_del_usuario(categoria_id, usuario_id) else None


@app.route("/calendario")
@login_requerido
def calendario():
    usuario_id = session["usuario_id"]
    hoy = date.today()

    anio = request.args.get("anio", type=int)
    if anio is None:
        anio = hoy.year
    mes = request.args.get("mes", type=int)
    if mes is None:
        mes = hoy.month
    # Si navegando entre meses nos salimos de 1-12 (de enero hacia atras,
    # o de diciembre hacia adelante), lo normalizamos en vez de fallar.
    while mes < 1:
        mes += 12
        anio -= 1
    while mes > 12:
        mes -= 12
        anio += 1

    dias_con_eventos = eventos_del_mes(usuario_id, anio, mes)

    primer_dia_semana, num_dias = calendario_std.monthrange(anio, mes)
    semanas = []
    semana_actual = [None] * primer_dia_semana
    for dia in range(1, num_dias + 1):
        semana_actual.append({
            "numero": dia,
            "es_hoy": anio == hoy.year and mes == hoy.month and dia == hoy.day,
            "eventos": dias_con_eventos.get(dia, []),
        })
        if len(semana_actual) == 7:
            semanas.append(semana_actual)
            semana_actual = []
    if semana_actual:
        semana_actual += [None] * (7 - len(semana_actual))
        semanas.append(semana_actual)

    mes_anterior_anio, mes_anterior = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    mes_siguiente_anio, mes_siguiente = (anio + 1, 1) if mes == 12 else (anio, mes + 1)

    return render_template(
        "calendario/index.html",
        anio=anio,
        mes=mes,
        nombre_mes=NOMBRES_MESES_CALENDARIO[mes - 1],
        nombres_dias=NOMBRES_DIAS_SEMANA,
        semanas=semanas,
        mes_anterior_anio=mes_anterior_anio,
        mes_anterior=mes_anterior,
        mes_siguiente_anio=mes_siguiente_anio,
        mes_siguiente=mes_siguiente,
        es_mes_actual=(anio == hoy.year and mes == hoy.month),
        proximos_eventos=obtener_eventos(usuario_id, incluir_pasados=False)[:8],
        hoy=hoy.isoformat(),
    )


@app.route("/calendario/lista")
@login_requerido
def calendario_lista():
    usuario_id = session["usuario_id"]
    incluir_pasados = request.args.get("pasados") == "1"
    categoria_filtro = request.args.get("categoria", type=int)
    estado_filtro = request.args.get("estado", "")

    items = obtener_eventos(usuario_id, incluir_pasados=incluir_pasados)
    resumen = {
        "hoy": sum(1 for i in items if i["estado"] == "hoy"),
        "proximo": sum(1 for i in items if i["estado"] == "proximo"),
        "futuro": sum(1 for i in items if i["estado"] == "futuro"),
    }

    items_filtrados = items
    if categoria_filtro:
        items_filtrados = [i for i in items_filtrados if i["categoria_id"] == categoria_filtro]
    if estado_filtro in ("pasado", "hoy", "proximo", "futuro"):
        items_filtrados = [i for i in items_filtrados if i["estado"] == estado_filtro]

    return render_template(
        "calendario/lista.html",
        items=items_filtrados,
        resumen=resumen,
        categorias=obtener_categorias_calendario(usuario_id),
        categoria_filtro=categoria_filtro,
        estado_filtro=estado_filtro,
        incluir_pasados=incluir_pasados,
        total_items=len(items),
    )


@app.route("/calendario/nuevo", methods=["GET", "POST"])
@login_requerido
def calendario_nuevo():
    usuario_id = session["usuario_id"]

    if request.method == "POST":
        datos, errores = validar_formulario_evento(request.form)
        if errores:
            for error in errores:
                flash(error)
            return redirect(url_for("calendario_nuevo"))

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO calendario_eventos
                (usuario_id, titulo, categoria_id, fecha, hora, todo_el_dia, lugar,
                 descripcion, recordatorio_dias, repetir, repetir_hasta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            usuario_id, datos["titulo"], _categoria_id_valida(datos["categoria_id"], usuario_id),
            datos["fecha"], datos["hora"], datos["todo_el_dia"], datos["lugar"],
            datos["descripcion"], datos["recordatorio_dias"], datos["repetir"], datos["repetir_hasta"],
        ))
        conn.commit()
        conn.close()

        flash(f"'{datos['titulo']}' anadido al calendario.")
        return redirect(url_for("calendario"))

    return render_template(
        "calendario/nuevo.html",
        categorias=obtener_categorias_calendario(usuario_id),
        opciones_repeticion=OPCIONES_REPETICION_CALENDARIO,
        fecha_preseleccionada=request.args.get("fecha") or date.today().isoformat(),
    )


@app.route("/calendario/<int:evento_id>/editar", methods=["GET", "POST"])
@login_requerido
def calendario_editar(evento_id):
    usuario_id = session["usuario_id"]
    evento = evento_del_usuario(evento_id, usuario_id)
    if evento is None:
        flash("Ese evento no existe.")
        return redirect(url_for("calendario"))

    if request.method == "POST":
        datos, errores = validar_formulario_evento(request.form)
        if errores:
            for error in errores:
                flash(error)
            return redirect(url_for("calendario_editar", evento_id=evento_id))

        conn = get_db_connection()
        conn.execute("""
            UPDATE calendario_eventos
            SET titulo = ?, categoria_id = ?, fecha = ?, hora = ?, todo_el_dia = ?, lugar = ?,
                descripcion = ?, recordatorio_dias = ?, repetir = ?, repetir_hasta = ?,
                aviso_enviado_fecha = NULL
            WHERE id = ?
        """, (
            datos["titulo"], _categoria_id_valida(datos["categoria_id"], usuario_id),
            datos["fecha"], datos["hora"], datos["todo_el_dia"], datos["lugar"],
            datos["descripcion"], datos["recordatorio_dias"], datos["repetir"], datos["repetir_hasta"],
            evento_id,
        ))
        conn.commit()
        conn.close()

        flash("Evento actualizado.")
        return redirect(url_for("calendario"))

    return render_template(
        "calendario/editar.html",
        evento=evento,
        categorias=obtener_categorias_calendario(usuario_id),
        opciones_repeticion=OPCIONES_REPETICION_CALENDARIO,
    )


@app.route("/calendario/<int:evento_id>/eliminar", methods=["POST"])
@login_requerido
def calendario_eliminar(evento_id):
    usuario_id = session["usuario_id"]
    evento = evento_del_usuario(evento_id, usuario_id)
    if evento is None:
        flash("Ese evento no existe.")
        return redirect(url_for("calendario"))

    conn = get_db_connection()
    conn.execute("DELETE FROM calendario_eventos WHERE id = ?", (evento_id,))
    conn.commit()
    conn.close()

    flash(f"'{evento['titulo']}' eliminado.")
    return redirect(url_for("calendario"))


# =================================================================
# Categorias
# =================================================================

@app.route("/calendario/categorias")
@login_requerido
def calendario_categorias():
    usuario_id = session["usuario_id"]
    return render_template(
        "calendario/categorias.html",
        categorias=obtener_categorias_calendario(usuario_id),
        colores=COLORES_CALENDARIO,
    )


@app.route("/calendario/categorias/nueva", methods=["POST"])
@login_requerido
def calendario_nueva_categoria():
    usuario_id = session["usuario_id"]
    nombre = request.form.get("nombre", "").strip()
    color = request.form.get("color", "azul")
    if color not in COLORES_CALENDARIO:
        color = "azul"

    if not nombre:
        flash("Escribe un nombre para la categoria.")
        return redirect(url_for("calendario_categorias"))

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO calendario_categorias (usuario_id, nombre, color) VALUES (?, ?, ?)",
        (usuario_id, nombre, color),
    )
    conn.commit()
    conn.close()

    flash(f"Categoria '{nombre}' creada.")
    return redirect(url_for("calendario_categorias"))


@app.route("/calendario/categorias/<int:categoria_id>/editar", methods=["GET", "POST"])
@login_requerido
def calendario_editar_categoria(categoria_id):
    usuario_id = session["usuario_id"]
    categoria = categoria_calendario_del_usuario(categoria_id, usuario_id)
    if categoria is None:
        flash("Esa categoria no existe.")
        return redirect(url_for("calendario_categorias"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        color = request.form.get("color", "azul")
        if color not in COLORES_CALENDARIO:
            color = "azul"

        if not nombre:
            flash("Escribe un nombre para la categoria.")
            return redirect(url_for("calendario_editar_categoria", categoria_id=categoria_id))

        conn = get_db_connection()
        conn.execute(
            "UPDATE calendario_categorias SET nombre = ?, color = ? WHERE id = ?",
            (nombre, color, categoria_id),
        )
        conn.commit()
        conn.close()

        flash("Categoria actualizada.")
        return redirect(url_for("calendario_categorias"))

    return render_template(
        "calendario/editar_categoria.html", categoria=categoria, colores=COLORES_CALENDARIO
    )


@app.route("/calendario/categorias/<int:categoria_id>/eliminar", methods=["POST"])
@login_requerido
def calendario_eliminar_categoria(categoria_id):
    usuario_id = session["usuario_id"]
    categoria = categoria_calendario_del_usuario(categoria_id, usuario_id)
    if categoria is None:
        flash("Esa categoria no existe.")
        return redirect(url_for("calendario_categorias"))

    conn = get_db_connection()
    # Los eventos que la usaban se quedan sin categoria (no se borran):
    # la categoria es solo una etiqueta visual, no un dato imprescindible.
    conn.execute("UPDATE calendario_eventos SET categoria_id = NULL WHERE categoria_id = ?", (categoria_id,))
    conn.execute("DELETE FROM calendario_categorias WHERE id = ?", (categoria_id,))
    conn.commit()
    conn.close()

    flash(f"Categoria '{categoria['nombre']}' eliminada.")
    return redirect(url_for("calendario_categorias"))
