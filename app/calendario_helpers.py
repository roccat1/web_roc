"""
CALENDARIO - funciones de ayuda.

Lo mas particular del calendario frente a Caducidades es que un evento
puede repetirse (diaria, semanal, mensual o anualmente). Por eso, en
vez de comparar directamente la fecha guardada en la base de datos con
hoy, primero hay que calcular en que fecha cae su proxima ocurrencia
(o las ocurrencias que caen dentro de un mes, para la vista de
calendario). Estas funciones las usan tanto las rutas web como el
dashboard y el bot de Telegram.
"""

import calendar as calendario_std
from datetime import date, timedelta

from .db import get_db_connection, COLOR_LED_POR_ESTADO_EVENTO, OPCIONES_REPETICION_CALENDARIO


def _sumar_meses(fecha, meses):
    """Suma 'meses' a una fecha, ajustando el dia si el mes de destino es
    mas corto (ej. 31 de enero + 1 mes = 28 o 29 de febrero)."""
    mes_total = fecha.month - 1 + meses
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, calendario_std.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def _avanzar(fecha, repetir):
    """Devuelve la fecha de la siguiente repeticion a partir de 'fecha'."""
    if repetir == "diaria":
        return fecha + timedelta(days=1)
    if repetir == "semanal":
        return fecha + timedelta(days=7)
    if repetir == "mensual":
        return _sumar_meses(fecha, 1)
    if repetir == "anual":
        return _sumar_meses(fecha, 12)
    return fecha


def siguiente_ocurrencia(fecha_evento, repetir, repetir_hasta, desde=None):
    """
    Devuelve la fecha de la proxima ocurrencia de un evento a partir de
    'desde' (hoy, por defecto):
    - Si el evento no se repite, devuelve 'fecha_evento' tal cual (haya
      pasado ya o no: el llamante decide que hacer con eso).
    - Si se repite, devuelve la primera ocurrencia que cae en 'desde' o
      despues. Si ya no quedan ocurrencias futuras (se supero
      'repetir_hasta'), devuelve la propia 'fecha_evento' original, para
      que se trate como un evento ya terminado.
    """
    desde = desde or date.today()

    if repetir == "ninguna" or fecha_evento >= desde:
        return fecha_evento

    limite = date.fromisoformat(repetir_hasta) if repetir_hasta else None
    fecha = fecha_evento

    while fecha < desde:
        if limite and fecha >= limite:
            return fecha_evento
        fecha = _avanzar(fecha, repetir)

    if limite and fecha > limite:
        return fecha_evento
    return fecha


def _ocurrencias_en_rango(fecha_evento, repetir, repetir_hasta, desde, hasta):
    """Genera todas las fechas en las que cae un evento (una sola vez si
    no se repite) dentro del rango [desde, hasta], ambos incluidos."""
    if repetir == "ninguna":
        if desde <= fecha_evento <= hasta:
            yield fecha_evento
        return

    limite = date.fromisoformat(repetir_hasta) if repetir_hasta else None
    fecha = fecha_evento

    while fecha < desde:
        if limite and fecha >= limite:
            return
        fecha = _avanzar(fecha, repetir)

    while fecha <= hasta:
        if limite and fecha > limite:
            return
        yield fecha
        fecha = _avanzar(fecha, repetir)


def calcular_estado_evento(fecha_ocurrencia, hora, recordatorio_dias):
    """
    Compara la fecha de la (proxima) ocurrencia de un evento con hoy y
    devuelve un diccionario con:
    - estado: 'pasado', 'hoy', 'proximo' o 'futuro'
    - dias: dias que faltan (numero negativo si ya paso)
    - texto: frase lista para mostrar, ej. "Dentro de 3 dias"
    """
    hoy = date.today()
    dias = (fecha_ocurrencia - hoy).days
    palabra = "dia" if abs(dias) == 1 else "dias"

    if dias < 0:
        return {"estado": "pasado", "dias": dias, "texto": f"Hace {abs(dias)} {palabra}"}
    if dias == 0:
        texto = f"Hoy a las {hora}" if hora else "Hoy"
        return {"estado": "hoy", "dias": dias, "texto": texto}
    if dias <= recordatorio_dias:
        return {"estado": "proximo", "dias": dias, "texto": f"Dentro de {dias} {palabra}"}
    return {"estado": "futuro", "dias": dias, "texto": f"Dentro de {dias} {palabra}"}


def _fila_a_evento(fila, ocurrencia=None):
    """Convierte una fila de calendario_eventos (con el JOIN de
    categoria) en un diccionario listo para las plantillas, calculando
    su estado a partir de la ocurrencia indicada (o de la proxima, si no
    se indica ninguna)."""
    fecha_evento = date.fromisoformat(fila["fecha"])
    if ocurrencia is None:
        ocurrencia = siguiente_ocurrencia(fecha_evento, fila["repetir"], fila["repetir_hasta"])
    info = calcular_estado_evento(ocurrencia, fila["hora"], fila["recordatorio_dias"])

    return {
        "id": fila["id"],
        "titulo": fila["titulo"],
        "categoria_id": fila["categoria_id"],
        "categoria_nombre": fila["categoria_nombre"] or "Sin categoria",
        "categoria_color": fila["categoria_color"] or "azul",
        "fecha": fila["fecha"],
        "fecha_ocurrencia": ocurrencia.isoformat(),
        "hora": fila["hora"],
        "todo_el_dia": bool(fila["todo_el_dia"]),
        "lugar": fila["lugar"],
        "descripcion": fila["descripcion"],
        "recordatorio_dias": fila["recordatorio_dias"],
        "repetir": fila["repetir"],
        "repetir_hasta": fila["repetir_hasta"],
        "aviso_enviado_fecha": fila["aviso_enviado_fecha"],
        "estado": info["estado"],
        "dias": info["dias"],
        "texto_estado": info["texto"],
        "led": COLOR_LED_POR_ESTADO_EVENTO[info["estado"]],
    }


def _eventos_con_categoria(usuario_id):
    conn = get_db_connection()
    filas = conn.execute("""
        SELECT calendario_eventos.*, calendario_categorias.nombre AS categoria_nombre,
               calendario_categorias.color AS categoria_color
        FROM calendario_eventos
        LEFT JOIN calendario_categorias ON calendario_categorias.id = calendario_eventos.categoria_id
        WHERE calendario_eventos.usuario_id = ?
    """, (usuario_id,)).fetchall()
    conn.close()
    return filas


def obtener_eventos(usuario_id, incluir_pasados=True):
    """Devuelve los eventos del usuario (con la fecha de su proxima
    ocurrencia ya calculada, tambien para los recurrentes) ordenados de
    mas cercano a mas lejano."""
    eventos = [_fila_a_evento(fila) for fila in _eventos_con_categoria(usuario_id)]
    if not incluir_pasados:
        eventos = [e for e in eventos if e["estado"] != "pasado"]
    eventos.sort(key=lambda e: (e["fecha_ocurrencia"], e["hora"] or "99:99"))
    return eventos


def eventos_del_mes(usuario_id, anio, mes):
    """Devuelve un diccionario {dia (int): [eventos ese dia]} con todas
    las ocurrencias (incluidas las de eventos recurrentes) que caen
    dentro del mes indicado, para pintar la vista de calendario."""
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendario_std.monthrange(anio, mes)[1])

    dias = {}
    for fila in _eventos_con_categoria(usuario_id):
        fecha_evento = date.fromisoformat(fila["fecha"])
        for ocurrencia in _ocurrencias_en_rango(
            fecha_evento, fila["repetir"], fila["repetir_hasta"], primer_dia, ultimo_dia
        ):
            dias.setdefault(ocurrencia.day, []).append(_fila_a_evento(fila, ocurrencia))

    for lista in dias.values():
        lista.sort(key=lambda e: e["hora"] or "00:00")
    return dias


def evento_del_usuario(evento_id, usuario_id):
    """Comprueba que un evento existe y pertenece al usuario. Devuelve la fila o None."""
    conn = get_db_connection()
    evento = conn.execute(
        "SELECT * FROM calendario_eventos WHERE id = ? AND usuario_id = ?", (evento_id, usuario_id)
    ).fetchone()
    conn.close()
    return evento


def marcar_aviso_evento_enviado(evento_id, fecha_ocurrencia):
    """
    Guarda la fecha (texto ISO) de la ocurrencia para la que ya se avisa,
    para no repetir el mismo aviso. En un evento recurrente, la proxima
    vez que le toque avisar sera de una ocurrencia con otra fecha, asi
    que este mismo campo sirve tambien para ellos sin necesitar una
    tabla aparte por ocurrencia.
    """
    conn = get_db_connection()
    conn.execute(
        "UPDATE calendario_eventos SET aviso_enviado_fecha = ? WHERE id = ?",
        (fecha_ocurrencia, evento_id),
    )
    conn.commit()
    conn.close()


# =================================================================
# Categorias
# =================================================================

def obtener_categorias_calendario(usuario_id):
    conn = get_db_connection()
    filas = conn.execute(
        "SELECT * FROM calendario_categorias WHERE usuario_id = ? ORDER BY nombre COLLATE NOCASE",
        (usuario_id,),
    ).fetchall()
    conn.close()
    return filas


def categoria_calendario_del_usuario(categoria_id, usuario_id):
    conn = get_db_connection()
    categoria = conn.execute(
        "SELECT * FROM calendario_categorias WHERE id = ? AND usuario_id = ?",
        (categoria_id, usuario_id),
    ).fetchone()
    conn.close()
    return categoria


# =================================================================
# Validacion de formularios
# =================================================================

def validar_formulario_evento(form):
    """Valida y devuelve los datos del formulario de crear/editar un
    evento del calendario. Devuelve (datos, errores)."""
    titulo = form.get("titulo", "").strip()
    categoria_id = form.get("categoria_id", type=int)
    fecha_texto = form.get("fecha", "").strip()
    hora_texto = form.get("hora", "").strip()
    todo_el_dia = form.get("todo_el_dia") == "on"
    lugar = form.get("lugar", "").strip()
    descripcion = form.get("descripcion", "").strip()
    recordatorio_dias = form.get("recordatorio_dias", type=int)
    repetir = form.get("repetir", "ninguna").strip()
    repetir_hasta = form.get("repetir_hasta", "").strip()

    errores = []
    if not titulo:
        errores.append("Escribe un titulo.")

    if not fecha_texto:
        errores.append("Elige una fecha.")
    else:
        try:
            date.fromisoformat(fecha_texto)
        except ValueError:
            errores.append("La fecha no es valida.")

    if todo_el_dia:
        hora_texto = ""
    elif hora_texto:
        try:
            horas, minutos = hora_texto.split(":")
            if not (0 <= int(horas) <= 23 and 0 <= int(minutos) <= 59):
                raise ValueError
        except ValueError:
            errores.append("La hora no es valida.")
            hora_texto = ""

    if recordatorio_dias is None or recordatorio_dias < 0:
        recordatorio_dias = 0

    if repetir not in OPCIONES_REPETICION_CALENDARIO:
        repetir = "ninguna"

    if repetir == "ninguna" or not repetir_hasta:
        repetir_hasta = None
    else:
        try:
            date.fromisoformat(repetir_hasta)
        except ValueError:
            errores.append("La fecha limite de repeticion no es valida.")
            repetir_hasta = None

    datos = {
        "titulo": titulo,
        "categoria_id": categoria_id or None,
        "fecha": fecha_texto,
        "hora": hora_texto or None,
        "todo_el_dia": 1 if todo_el_dia else 0,
        "lugar": lugar or None,
        "descripcion": descripcion or None,
        "recordatorio_dias": recordatorio_dias,
        "repetir": repetir,
        "repetir_hasta": repetir_hasta,
    }
    return datos, errores
