"""
CALENDARIO - rutas: vista mensual (con navegacion entre meses), vista
setmanal, vista d'un sol dia, vista de lista amb filtres i cerca, alta,
edicio i esborrat d'esdeveniments (sencers o nomes una ocurrencia),
exportacio/importacio ICS, i gestio de les categories del calendari.
"""

import calendar as calendario_std
from datetime import date, timedelta

from flask import Response, flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection, COLORES_CALENDARIO, OPCIONES_REPETICION_CALENDARIO
from .calendario_helpers import (
    obtener_eventos,
    eventos_del_mes,
    eventos_de_dia,
    eventos_de_semana,
    evento_del_usuario,
    validar_formulario_evento,
    validar_formulario_excepcion,
    obtener_categorias_calendario,
    categoria_calendario_del_usuario,
    contar_eventos_por_categoria,
    obtener_umbrales_recordatorio,
    guardar_umbrales_recordatorio,
    categorias_extra_evento,
    guardar_categorias_extra,
    excepcion_de_ocurrencia,
    guardar_excepcion_cancelada,
    guardar_excepcion_editada,
    eliminar_excepcion,
    generar_ics,
    importar_ics,
    UMBRALES_RECORDATORIO_SUGERIDOS,
)
from .google_calendar_helpers import push_evento, push_excepcion, eliminar_evento_remoto, obtener_calendarios_vinculados

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


def _formatear_fecha_larga(fecha_dt):
    return f"{fecha_dt.day} de {NOMBRES_MESES_CALENDARIO[fecha_dt.month - 1].lower()} de {fecha_dt.year}"


def _formatear_rango_semana(lunes, domingo):
    if lunes.month == domingo.month:
        return f"{lunes.day} - {domingo.day} de {NOMBRES_MESES_CALENDARIO[lunes.month - 1].lower()} de {lunes.year}"
    return (
        f"{lunes.day} de {NOMBRES_MESES_CALENDARIO[lunes.month - 1].lower()} - "
        f"{domingo.day} de {NOMBRES_MESES_CALENDARIO[domingo.month - 1].lower()} de {domingo.year}"
    )


def _guardar_recordatorios_y_categorias(evento_id, datos, usuario_id):
    guardar_umbrales_recordatorio(evento_id, datos["recordatorios_dias"])
    guardar_categorias_extra(evento_id, datos["categorias_extra"], usuario_id)


def _sincronizar_con_google(evento_id):
    """Intenta reflejar el evento en Google Calendar al momento (si su
    categoria esta vinculada a un calendario sincronizado). Si falla
    (sin conexion, token caducado...) no interrumpe la web: el evento
    se guarda igual, y el ciclo periodico en segundo plano lo reintenta
    mas tarde."""
    try:
        push_evento(evento_id)
    except Exception as error:
        print(f"[google-sync] No s'ha pogut sincronitzar l'esdeveniment {evento_id} amb Google: {error}")


def _sincronizar_ocurrencia_con_google(evento_id, fecha):
    try:
        push_excepcion(evento_id, fecha)
    except Exception as error:
        print(f"[google-sync] No s'ha pogut sincronitzar l'ocurrencia del {fecha} (evento {evento_id}) amb Google: {error}")


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
            "fecha": date(anio, mes, dia).isoformat(),
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


@app.route("/calendario/semana")
@login_requerido
def calendario_semana():
    usuario_id = session["usuario_id"]
    hoy = date.today()

    lunes_texto = request.args.get("lunes")
    try:
        base = date.fromisoformat(lunes_texto) if lunes_texto else hoy
    except ValueError:
        base = hoy
    lunes = base - timedelta(days=base.weekday())
    domingo = lunes + timedelta(days=6)

    dias = eventos_de_semana(usuario_id, lunes)
    for indice, dia in enumerate(dias):
        fecha_dt = lunes + timedelta(days=indice)
        dia["numero"] = fecha_dt.day
        dia["nombre_dia"] = NOMBRES_DIAS_SEMANA[indice]
        dia["es_hoy"] = fecha_dt == hoy

    return render_template(
        "calendario/semana.html",
        dias=dias,
        lunes=lunes.isoformat(),
        semana_anterior=(lunes - timedelta(days=7)).isoformat(),
        semana_siguiente=(lunes + timedelta(days=7)).isoformat(),
        rango_texto=_formatear_rango_semana(lunes, domingo),
        es_semana_actual=(lunes <= hoy <= domingo),
    )


@app.route("/calendario/dia/<fecha>")
@login_requerido
def calendario_dia(fecha):
    usuario_id = session["usuario_id"]
    try:
        fecha_dt = date.fromisoformat(fecha)
    except ValueError:
        flash("La data no es valida.")
        return redirect(url_for("calendario"))

    return render_template(
        "calendario/dia.html",
        fecha=fecha_dt.isoformat(),
        fecha_formateada=_formatear_fecha_larga(fecha_dt),
        es_hoy=(fecha_dt == date.today()),
        eventos=eventos_de_dia(usuario_id, fecha_dt),
    )


@app.route("/calendario/lista")
@login_requerido
def calendario_lista():
    usuario_id = session["usuario_id"]
    incluir_pasados = request.args.get("pasados") == "1"
    categoria_filtro = request.args.get("categoria", type=int)
    estado_filtro = request.args.get("estado", "")
    busqueda = request.args.get("q", "").strip()

    items = obtener_eventos(usuario_id, incluir_pasados=incluir_pasados)
    resumen = {
        "hoy": sum(1 for i in items if i["estado"] == "hoy"),
        "proximo": sum(1 for i in items if i["estado"] == "proximo"),
        "futuro": sum(1 for i in items if i["estado"] == "futuro"),
    }

    items_filtrados = items
    if categoria_filtro:
        items_filtrados = [
            i for i in items_filtrados
            if i["categoria_id"] == categoria_filtro
            or any(c["id"] == categoria_filtro for c in i["categorias_extra"])
        ]
    if estado_filtro in ("pasado", "hoy", "proximo", "futuro"):
        items_filtrados = [i for i in items_filtrados if i["estado"] == estado_filtro]
    if busqueda:
        texto = busqueda.lower()
        items_filtrados = [
            i for i in items_filtrados
            if texto in i["titulo"].lower()
            or (i["lugar"] and texto in i["lugar"].lower())
            or (i["descripcion"] and texto in i["descripcion"].lower())
        ]

    return render_template(
        "calendario/lista.html",
        items=items_filtrados,
        resumen=resumen,
        categorias=obtener_categorias_calendario(usuario_id),
        categoria_filtro=categoria_filtro,
        estado_filtro=estado_filtro,
        incluir_pasados=incluir_pasados,
        busqueda=busqueda,
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
        cursor = conn.execute("""
            INSERT INTO calendario_eventos
                (usuario_id, titulo, categoria_id, fecha, hora, todo_el_dia, lugar,
                 descripcion, recordatorio_dias, repetir, repetir_hasta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            usuario_id, datos["titulo"], _categoria_id_valida(datos["categoria_id"], usuario_id),
            datos["fecha"], datos["hora"], datos["todo_el_dia"], datos["lugar"],
            datos["descripcion"], max(datos["recordatorios_dias"]), datos["repetir"], datos["repetir_hasta"],
        ))
        evento_id = cursor.lastrowid
        conn.commit()
        conn.close()

        _guardar_recordatorios_y_categorias(evento_id, datos, usuario_id)
        _sincronizar_con_google(evento_id)

        flash(f"'{datos['titulo']}' afegit al calendari.")
        return redirect(url_for("calendario"))

    return render_template(
        "calendario/nuevo.html",
        categorias=obtener_categorias_calendario(usuario_id),
        opciones_repeticion=OPCIONES_REPETICION_CALENDARIO,
        fecha_preseleccionada=request.args.get("fecha") or date.today().isoformat(),
        umbrales_sugeridos=UMBRALES_RECORDATORIO_SUGERIDOS,
        umbrales_marcados={0},
        categorias_extra_marcadas=set(),
    )


@app.route("/calendario/<int:evento_id>/editar", methods=["GET", "POST"])
@login_requerido
def calendario_editar(evento_id):
    usuario_id = session["usuario_id"]
    evento = evento_del_usuario(evento_id, usuario_id)
    if evento is None:
        flash("Aquest esdeveniment no existeix.")
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
            datos["descripcion"], max(datos["recordatorios_dias"]), datos["repetir"], datos["repetir_hasta"],
            evento_id,
        ))
        # Al cambiar la serie, las fechas de ocurrencia pueden cambiar
        # enteras: los avisos ya enviados que quedaban registrados para
        # las fechas antiguas ya no significan nada, se limpian.
        conn.execute("DELETE FROM calendario_avisos_enviados WHERE evento_id = ?", (evento_id,))
        conn.commit()
        conn.close()

        _guardar_recordatorios_y_categorias(evento_id, datos, usuario_id)
        _sincronizar_con_google(evento_id)

        flash("Esdeveniment actualitzat.")
        return redirect(url_for("calendario"))

    categorias_extra_marcadas = {c["id"] for c in categorias_extra_evento(evento_id)}
    return render_template(
        "calendario/editar.html",
        evento=evento,
        categorias=obtener_categorias_calendario(usuario_id),
        opciones_repeticion=OPCIONES_REPETICION_CALENDARIO,
        umbrales_sugeridos=UMBRALES_RECORDATORIO_SUGERIDOS,
        umbrales_marcados=set(obtener_umbrales_recordatorio(evento_id)),
        categorias_extra_marcadas=categorias_extra_marcadas,
    )


@app.route("/calendario/<int:evento_id>/eliminar", methods=["POST"])
@login_requerido
def calendario_eliminar(evento_id):
    usuario_id = session["usuario_id"]
    evento = evento_del_usuario(evento_id, usuario_id)
    if evento is None:
        flash("Aquest esdeveniment no existeix.")
        return redirect(url_for("calendario"))

    if evento["google_event_id"]:
        try:
            eliminar_evento_remoto(usuario_id, evento["google_calendario_id"], evento["google_event_id"])
        except Exception as error:
            print(f"[google-sync] No s'ha pogut eliminar l'esdeveniment {evento_id} a Google: {error}")

    conn = get_db_connection()
    conn.execute("DELETE FROM calendario_evento_categorias WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_recordatorios WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_avisos_enviados WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_excepciones WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_eventos WHERE id = ?", (evento_id,))
    conn.commit()
    conn.close()

    flash(f"'{evento['titulo']}' eliminat.")
    return redirect(url_for("calendario"))


# =================================================================
# Una sola ocurrencia de un evento recurrente
# =================================================================

@app.route("/calendario/<int:evento_id>/ocurrencia/<fecha>/cancelar", methods=["POST"])
@login_requerido
def calendario_ocurrencia_cancelar(evento_id, fecha):
    usuario_id = session["usuario_id"]
    evento = evento_del_usuario(evento_id, usuario_id)
    if evento is None or evento["repetir"] == "ninguna":
        flash("Aquest esdeveniment no existeix o no es repeteix.")
        return redirect(url_for("calendario"))
    try:
        date.fromisoformat(fecha)
    except ValueError:
        flash("La data no es valida.")
        return redirect(url_for("calendario"))

    guardar_excepcion_cancelada(evento_id, fecha)
    _sincronizar_ocurrencia_con_google(evento_id, fecha)
    flash(f"S'ha cancel·lat nomes l'ocurrencia del {fecha} de «{evento['titulo']}».")
    return redirect(url_for("calendario_dia", fecha=fecha))


@app.route("/calendario/<int:evento_id>/ocurrencia/<fecha>/editar", methods=["GET", "POST"])
@login_requerido
def calendario_ocurrencia_editar(evento_id, fecha):
    usuario_id = session["usuario_id"]
    evento = evento_del_usuario(evento_id, usuario_id)
    if evento is None or evento["repetir"] == "ninguna":
        flash("Aquest esdeveniment no existeix o no es repeteix.")
        return redirect(url_for("calendario"))
    try:
        fecha_dt = date.fromisoformat(fecha)
    except ValueError:
        flash("La data no es valida.")
        return redirect(url_for("calendario"))

    if request.method == "POST":
        datos, errores = validar_formulario_excepcion(request.form)
        if errores:
            for error in errores:
                flash(error)
            return redirect(url_for("calendario_ocurrencia_editar", evento_id=evento_id, fecha=fecha))

        guardar_excepcion_editada(
            evento_id, fecha, datos["titulo"], datos["hora"], datos["todo_el_dia"],
            datos["lugar"], datos["descripcion"],
        )
        _sincronizar_ocurrencia_con_google(evento_id, fecha)
        flash(f"S'ha actualitzat nomes l'ocurrencia del {fecha}.")
        return redirect(url_for("calendario_dia", fecha=fecha))

    excepcion = excepcion_de_ocurrencia(evento_id, fecha)
    return render_template(
        "calendario/ocurrencia_editar.html",
        evento=evento,
        fecha=fecha,
        fecha_formateada=_formatear_fecha_larga(fecha_dt),
        excepcion=excepcion,
    )


@app.route("/calendario/<int:evento_id>/ocurrencia/<fecha>/restaurar", methods=["POST"])
@login_requerido
def calendario_ocurrencia_restaurar(evento_id, fecha):
    usuario_id = session["usuario_id"]
    evento = evento_del_usuario(evento_id, usuario_id)
    if evento is None:
        flash("Aquest esdeveniment no existeix.")
        return redirect(url_for("calendario"))

    # Nota: esto no se refleja en Google Calendar (si el evento esta
    # sincronizado). Recrear alla una ocurrencia que se habia cancelado
    # o editado requeriria logica adicional que, de momento, no esta
    # implementada; la ocurrencia se restaura solo en la app.
    eliminar_excepcion(evento_id, fecha)
    flash("S'ha restaurat aquesta ocurrencia tal com era a la serie.")
    return redirect(url_for("calendario_dia", fecha=fecha))


# =================================================================
# Exportacio / importacio ICS
# =================================================================

@app.route("/calendario/exportar.ics")
@login_requerido
def calendario_exportar_ics():
    usuario_id = session["usuario_id"]
    contenido = generar_ics(usuario_id)
    return Response(
        contenido,
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=calendari.ics"},
    )


@app.route("/calendario/importar", methods=["GET", "POST"])
@login_requerido
def calendario_importar():
    usuario_id = session["usuario_id"]

    if request.method == "POST":
        fichero = request.files.get("fichero")
        if not fichero or not fichero.filename:
            flash("Tria un fitxer .ics per importar.")
            return redirect(url_for("calendario_importar"))

        try:
            texto = fichero.read().decode("utf-8", errors="replace")
        except Exception:
            flash("No s'ha pogut llegir aquest fitxer.")
            return redirect(url_for("calendario_importar"))

        n_importados, avisos = importar_ics(usuario_id, texto)
        if n_importados:
            flash(f"S'han importat {n_importados} esdeveniments.")
        else:
            flash("No s'ha trobat cap esdeveniment per importar en aquest fitxer.")
        for aviso in avisos[:5]:
            flash(aviso)
        return redirect(url_for("calendario"))

    return render_template("calendario/importar.html")


# =================================================================
# Categorias
# =================================================================

@app.route("/calendario/categorias")
@login_requerido
def calendario_categorias():
    usuario_id = session["usuario_id"]
    categorias_google = {
        c["categoria_id"] for c in obtener_calendarios_vinculados(usuario_id) if c["categoria_id"] is not None
    }
    return render_template(
        "calendario/categorias.html",
        categorias=obtener_categorias_calendario(usuario_id),
        colores=COLORES_CALENDARIO,
        conteo_eventos=contar_eventos_por_categoria(usuario_id),
        categorias_google=categorias_google,
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
        flash("Escriu un nom per a la categoria.")
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
        flash("Aquesta categoria no existeix.")
        return redirect(url_for("calendario_categorias"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        color = request.form.get("color", "azul")
        if color not in COLORES_CALENDARIO:
            color = "azul"

        if not nombre:
            flash("Escriu un nom per a la categoria.")
            return redirect(url_for("calendario_editar_categoria", categoria_id=categoria_id))

        conn = get_db_connection()
        conn.execute(
            "UPDATE calendario_categorias SET nombre = ?, color = ? WHERE id = ?",
            (nombre, color, categoria_id),
        )
        conn.commit()
        conn.close()

        flash("Categoria actualitzada.")
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
        flash("Aquesta categoria no existeix.")
        return redirect(url_for("calendario_categorias"))

    conn = get_db_connection()
    # Los eventos que la usaban (como principal o como etiqueta extra)
    # se quedan sin ella (no se borran): la categoria es solo una
    # etiqueta visual, no un dato imprescindible.
    conn.execute("UPDATE calendario_eventos SET categoria_id = NULL WHERE categoria_id = ?", (categoria_id,))
    conn.execute("DELETE FROM calendario_evento_categorias WHERE categoria_id = ?", (categoria_id,))
    # Si esta categoria venia de un calendario de Google vinculado, ese
    # calendario se pone en pausa (deja de sincronizarse) en vez de
    # quedarse apuntando a una categoria que ya no existe.
    conn.execute(
        "UPDATE calendario_google_calendarios SET categoria_id = NULL, sync_activo = 0 WHERE categoria_id = ?",
        (categoria_id,),
    )
    conn.execute("DELETE FROM calendario_categorias WHERE id = ?", (categoria_id,))
    conn.commit()
    conn.close()

    flash(f"Categoria '{categoria['nombre']}' eliminada.")
    return redirect(url_for("calendario_categorias"))
