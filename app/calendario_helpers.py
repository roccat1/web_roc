"""
CALENDARIO - funciones de ayuda.

Lo mas particular del calendario frente a Caducidades es que un evento
puede repetirse (diaria, semanal, mensual o anualmente). Por eso, en
vez de comparar directamente la fecha guardada en la base de datos con
hoy, primero hay que calcular en que fecha cae su proxima ocurrencia
(o las ocurrencias que caen dentro de un rango, para las vistas de
calendario, semana o dia). Estas funciones las usan tanto las rutas
web como el dashboard y el bot de Telegram.

Ademas de la recurrencia basica, un evento puede tener:
- Varios avisos (calendario_recordatorios): p.ej. "avisa 7 dies abans
  i tambe el mateix dia", en vez de un unico numero.
- Excepcions puntuals (calendario_excepciones): cancel·lar o editar
  nomes una ocurrencia concreta d'una serie recurrent, sense afectar
  a la resta.
- Categories addicionals (calendario_evento_categorias): a mes de la
  categoria principal (la que decideix el color del punt al mes).
"""

import calendar as calendario_std
from datetime import date, datetime, timedelta, timezone

from .db import get_db_connection, COLOR_LED_POR_ESTADO_EVENTO, OPCIONES_REPETICION_CALENDARIO

# Umbrales de aviso que se ofrecen ya preparados en el formulario (el
# usuario tambien puede anadir uno "a medida" ademas de estos).
UMBRALES_RECORDATORIO_SUGERIDOS = (0, 1, 3, 7, 14, 30)


# =================================================================
# Recurrencia: calculo de fechas de ocurrencia
# =================================================================

def _sumar_meses(fecha, meses):
    """Suma 'meses' a una fecha, ajustando el dia si el mes de destino es
    mas corto (ej. 31 de enero + 1 mes = 28 o 29 de febrero)."""
    mes_total = fecha.month - 1 + meses
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, calendario_std.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def _ocurrencia_n(fecha_evento, repetir, n):
    """
    Devuelve la fecha de la ocurrencia numero 'n' (n=0 es la propia
    'fecha_evento'), calculada SIEMPRE a partir de 'fecha_evento' y no
    encadenando sumas desde la ocurrencia anterior. Esto es importante
    para 'mensual' y 'anual': si se encadenara (sumar 1 mes al
    resultado anterior, una y otra vez), un evento el dia 31 que cae
    en un mes de 30 dias se quedaria en el dia 30 para siempre, sin
    volver nunca al 31 aunque el mes si tenga 31 dias. Calculando cada
    ocurrencia por separado desde el origen, ese problema desaparece.
    """
    if repetir == "diaria":
        return fecha_evento + timedelta(days=n)
    if repetir == "semanal":
        return fecha_evento + timedelta(weeks=n)
    if repetir == "mensual":
        return _sumar_meses(fecha_evento, n)
    if repetir == "anual":
        return _sumar_meses(fecha_evento, 12 * n)
    return fecha_evento


def siguiente_ocurrencia(fecha_evento, repetir, repetir_hasta, desde=None, fechas_canceladas=None):
    """
    Devuelve la fecha de la proxima ocurrencia de un evento a partir de
    'desde' (hoy, por defecto), saltandose las ocurrencias presentes en
    'fechas_canceladas' (un set de fechas ISO, de excepciones marcadas
    como cancelades):
    - Si el evento no se repite, devuelve 'fecha_evento' tal cual (haya
      pasado ya o no: el llamante decide que hacer con eso).
    - Si se repite, devuelve la primera ocurrencia (no cancelada) que
      cae en 'desde' o despues. Si ya no quedan ocurrencias futuras (se
      supero 'repetir_hasta'), devuelve la propia 'fecha_evento'
      original, para que se trate como un evento ya terminado.
    """
    desde = desde or date.today()
    fechas_canceladas = fechas_canceladas or set()

    if repetir == "ninguna":
        return fecha_evento

    limite = date.fromisoformat(repetir_hasta) if repetir_hasta else None
    n = 0
    fecha = fecha_evento
    while fecha < desde or fecha.isoformat() in fechas_canceladas:
        if limite and fecha >= limite:
            return fecha_evento
        n += 1
        fecha = _ocurrencia_n(fecha_evento, repetir, n)
    return fecha


def _ocurrencias_en_rango(fecha_evento, repetir, repetir_hasta, desde, hasta, fechas_canceladas=None):
    """Genera todas las fechas (no canceladas) en las que cae un evento
    (una sola vez si no se repite) dentro del rango [desde, hasta],
    ambos incluidos."""
    fechas_canceladas = fechas_canceladas or set()

    if repetir == "ninguna":
        if desde <= fecha_evento <= hasta and fecha_evento.isoformat() not in fechas_canceladas:
            yield fecha_evento
        return

    limite = date.fromisoformat(repetir_hasta) if repetir_hasta else None
    n = 0
    fecha = fecha_evento
    while fecha < desde:
        if limite and fecha >= limite:
            return
        n += 1
        fecha = _ocurrencia_n(fecha_evento, repetir, n)

    while fecha <= hasta:
        if limite and fecha > limite:
            return
        if fecha.isoformat() not in fechas_canceladas:
            yield fecha
        n += 1
        fecha = _ocurrencia_n(fecha_evento, repetir, n)


def calcular_estado_evento(fecha_ocurrencia, hora, umbrales_recordatorio):
    """
    Compara la fecha de la (proxima) ocurrencia de un evento con hoy y
    devuelve un diccionario con:
    - estado: 'pasado', 'hoy', 'proximo' o 'futuro'
    - dias: dias que faltan (numero negativo si ya paso)
    - texto: frase lista para mostrar, ej. "Dentro de 3 dias"

    'umbrales_recordatorio' es una lista de "dias de antelacion" (puede
    haber varios, ej. [7, 3, 0]); el evento se considera 'proximo' en
    cuanto entra en la ventana del mayor de ellos.
    """
    hoy = date.today()
    dias = (fecha_ocurrencia - hoy).days
    palabra = "dia" if abs(dias) == 1 else "dies"
    umbral_maximo = max(umbrales_recordatorio) if umbrales_recordatorio else 0

    if dias < 0:
        return {"estado": "pasado", "dias": dias, "texto": f"Fa {abs(dias)} {palabra}"}
    if dias == 0:
        texto = f"Avui a les {hora}" if hora else "Avui"
        return {"estado": "hoy", "dias": dias, "texto": texto}
    if dias <= umbral_maximo:
        return {"estado": "proximo", "dias": dias, "texto": f"Dins de {dias} {palabra}"}
    return {"estado": "futuro", "dias": dias, "texto": f"Dins de {dias} {palabra}"}


# =================================================================
# Recordatorios (uno o varios umbrales por evento)
# =================================================================

def obtener_umbrales_recordatorio(evento_id):
    """Devuelve la lista de "dias de antelacion" configurados para un
    evento. Si no tiene ninguno en la tabla nueva (eventos creados
    antes de que existiera esta funcionalidad), recurre a la columna
    antigua calendario_eventos.recordatorio_dias como unico umbral."""
    conn = get_db_connection()
    filas = conn.execute(
        "SELECT dias_antes FROM calendario_recordatorios WHERE evento_id = ? ORDER BY dias_antes DESC",
        (evento_id,),
    ).fetchall()
    if filas:
        conn.close()
        return [f["dias_antes"] for f in filas]

    fila = conn.execute(
        "SELECT recordatorio_dias FROM calendario_eventos WHERE id = ?", (evento_id,)
    ).fetchone()
    conn.close()
    return [fila["recordatorio_dias"]] if fila else [0]


def guardar_umbrales_recordatorio(evento_id, umbrales):
    """Sustituye los umbrales de aviso de un evento por 'umbrales' (una
    lista de enteros >= 0). Tambien actualiza la columna antigua
    recordatorio_dias (al mayor umbral) por compatibilidad."""
    umbrales = sorted({u for u in umbrales if u >= 0}) or [0]

    conn = get_db_connection()
    conn.execute("DELETE FROM calendario_recordatorios WHERE evento_id = ?", (evento_id,))
    for dias in umbrales:
        conn.execute(
            "INSERT INTO calendario_recordatorios (evento_id, dias_antes) VALUES (?, ?)",
            (evento_id, dias),
        )
    conn.execute(
        "UPDATE calendario_eventos SET recordatorio_dias = ? WHERE id = ?",
        (max(umbrales), evento_id),
    )
    conn.commit()
    conn.close()


def _umbrales_por_evento(usuario_id):
    """Trae de una vez los umbrales de todos los eventos del usuario,
    para no hacer una consulta por evento al pintar una lista entera."""
    conn = get_db_connection()
    filas = conn.execute("""
        SELECT calendario_recordatorios.evento_id, calendario_recordatorios.dias_antes
        FROM calendario_recordatorios
        JOIN calendario_eventos ON calendario_eventos.id = calendario_recordatorios.evento_id
        WHERE calendario_eventos.usuario_id = ?
    """, (usuario_id,)).fetchall()
    conn.close()
    resultado = {}
    for fila in filas:
        resultado.setdefault(fila["evento_id"], []).append(fila["dias_antes"])
    return resultado


# =================================================================
# Excepciones puntuales de una ocurrencia
# =================================================================

def _excepciones_por_evento(usuario_id):
    """Trae de una vez las excepciones de todos los eventos del
    usuario, indexadas por (evento_id -> fecha_ocurrencia -> fila)."""
    conn = get_db_connection()
    filas = conn.execute("""
        SELECT calendario_excepciones.*
        FROM calendario_excepciones
        JOIN calendario_eventos ON calendario_eventos.id = calendario_excepciones.evento_id
        WHERE calendario_eventos.usuario_id = ?
    """, (usuario_id,)).fetchall()
    conn.close()
    resultado = {}
    for fila in filas:
        resultado.setdefault(fila["evento_id"], {})[fila["fecha_ocurrencia"]] = fila
    return resultado


def excepcion_de_ocurrencia(evento_id, fecha_ocurrencia):
    """Devuelve la excepcion guardada para esa ocurrencia concreta (o
    None si esa ocurrencia no se ha tocado nunca)."""
    conn = get_db_connection()
    fila = conn.execute(
        "SELECT * FROM calendario_excepciones WHERE evento_id = ? AND fecha_ocurrencia = ?",
        (evento_id, fecha_ocurrencia),
    ).fetchone()
    conn.close()
    return fila


def guardar_excepcion_cancelada(evento_id, fecha_ocurrencia):
    """Marca una ocurrencia concreta como cancelada (no tornara a
    apareixer al calendari), sense tocar la resta de la serie."""
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO calendario_excepciones (evento_id, fecha_ocurrencia, cancelada)
        VALUES (?, ?, 1)
        ON CONFLICT (evento_id, fecha_ocurrencia) DO UPDATE SET
            cancelada = 1, titulo = NULL, hora = NULL, todo_el_dia = NULL,
            lugar = NULL, descripcion = NULL
    """, (evento_id, fecha_ocurrencia))
    conn.commit()
    conn.close()


def guardar_excepcion_editada(evento_id, fecha_ocurrencia, titulo, hora, todo_el_dia, lugar, descripcion):
    """Guarda un canvi (titol/hora/lloc/descripcio) que nomes s'aplica
    a aquesta ocurrencia concreta, sense afectar a la resta de la
    serie. (No permet canviar-la de dia: per aixo cal cancel·lar-la i
    crear un esdeveniment nou aquell altre dia.)"""
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO calendario_excepciones
            (evento_id, fecha_ocurrencia, cancelada, titulo, hora, todo_el_dia, lugar, descripcion)
        VALUES (?, ?, 0, ?, ?, ?, ?, ?)
        ON CONFLICT (evento_id, fecha_ocurrencia) DO UPDATE SET
            cancelada = 0, titulo = excluded.titulo, hora = excluded.hora,
            todo_el_dia = excluded.todo_el_dia, lugar = excluded.lugar,
            descripcion = excluded.descripcion
    """, (evento_id, fecha_ocurrencia, titulo or None, hora or None, todo_el_dia, lugar or None, descripcion or None))
    conn.commit()
    conn.close()


def eliminar_excepcion(evento_id, fecha_ocurrencia):
    """Elimina la excepcio d'una ocurrencia (torna a mostrar-se tal com
    surt de la serie, sense cap canvi ni cancel·lacio)."""
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM calendario_excepciones WHERE evento_id = ? AND fecha_ocurrencia = ?",
        (evento_id, fecha_ocurrencia),
    )
    conn.commit()
    conn.close()


# =================================================================
# Lectura de eventos (con categoria, ocurrencia, excepciones...)
# =================================================================

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


def _fila_a_evento(fila, ocurrencia=None, excepcion=None, umbrales=None, categorias_extra=None):
    """Convierte una fila de calendario_eventos (con el JOIN de
    categoria) en un diccionario listo para las plantillas, calculando
    su estado a partir de la ocurrencia indicada (o de la proxima, si
    no se indica ninguna), y aplicando la excepcion de esa ocurrencia
    concreta si la hay (titulo/hora/lloc/descripcio diferentes solo
    para ese dia, o marcada como cancelada)."""
    fecha_evento = date.fromisoformat(fila["fecha"])
    if ocurrencia is None:
        ocurrencia = siguiente_ocurrencia(fecha_evento, fila["repetir"], fila["repetir_hasta"])
    if umbrales is None:
        umbrales = obtener_umbrales_recordatorio(fila["id"])

    titulo = fila["titulo"]
    hora = fila["hora"]
    todo_el_dia = fila["todo_el_dia"]
    lugar = fila["lugar"]
    descripcion = fila["descripcion"]
    if excepcion is not None:
        titulo = excepcion["titulo"] or titulo
        hora = excepcion["hora"] if excepcion["hora"] is not None else hora
        todo_el_dia = excepcion["todo_el_dia"] if excepcion["todo_el_dia"] is not None else todo_el_dia
        lugar = excepcion["lugar"] if excepcion["lugar"] is not None else lugar
        descripcion = excepcion["descripcion"] if excepcion["descripcion"] is not None else descripcion

    info = calcular_estado_evento(ocurrencia, hora, umbrales)

    return {
        "id": fila["id"],
        "titulo": titulo,
        "categoria_id": fila["categoria_id"],
        "categoria_nombre": fila["categoria_nombre"] or "Sense categoria",
        "categoria_color": fila["categoria_color"] or "azul",
        "categorias_extra": categorias_extra or [],
        "fecha": fila["fecha"],
        "fecha_ocurrencia": ocurrencia.isoformat(),
        "hora": hora,
        "todo_el_dia": bool(todo_el_dia),
        "lugar": lugar,
        "descripcion": descripcion,
        "umbrales_recordatorio": umbrales,
        "repetir": fila["repetir"],
        "repetir_hasta": fila["repetir_hasta"],
        "es_recurrent": fila["repetir"] != "ninguna",
        "es_excepcio": excepcion is not None,
        "estado": info["estado"],
        "dias": info["dias"],
        "texto_estado": info["texto"],
        "led": COLOR_LED_POR_ESTADO_EVENTO[info["estado"]],
    }


def obtener_eventos(usuario_id, incluir_pasados=True):
    """Devuelve los eventos del usuario (con la fecha de su proxima
    ocurrencia ya calculada, tambien para los recurrentes, y saltando
    las ocurrencias canceladas por una excepcion) ordenados de mas
    cercano a mas lejano."""
    excepciones = _excepciones_por_evento(usuario_id)
    umbrales_todos = _umbrales_por_evento(usuario_id)
    categorias_extra_todas = categorias_extra_por_evento(usuario_id)

    eventos = []
    for fila in _eventos_con_categoria(usuario_id):
        fecha_evento = date.fromisoformat(fila["fecha"])
        excepciones_evento = excepciones.get(fila["id"], {})
        canceladas = {f for f, exc in excepciones_evento.items() if exc["cancelada"]}
        umbrales = umbrales_todos.get(fila["id"]) or [fila["recordatorio_dias"]]

        ocurrencia = siguiente_ocurrencia(
            fecha_evento, fila["repetir"], fila["repetir_hasta"], fechas_canceladas=canceladas
        )
        excepcion = excepciones_evento.get(ocurrencia.isoformat())
        eventos.append(_fila_a_evento(
            fila, ocurrencia, excepcion=excepcion, umbrales=umbrales,
            categorias_extra=categorias_extra_todas.get(fila["id"], []),
        ))

    if not incluir_pasados:
        eventos = [e for e in eventos if e["estado"] != "pasado"]
    eventos.sort(key=lambda e: (e["fecha_ocurrencia"], e["hora"] or "99:99"))
    return eventos


def eventos_en_rango(usuario_id, desde, hasta):
    """Devuelve un diccionario {fecha ISO: [eventos ese dia]} con todas
    las ocurrencias (incluidas las de eventos recurrentes, y ya sin
    las canceladas) que caen entre 'desde' y 'hasta', ambos incluidos.
    Es la base compartida de la vista de mes, de semana y de dia."""
    excepciones = _excepciones_por_evento(usuario_id)
    umbrales_todos = _umbrales_por_evento(usuario_id)
    categorias_extra_todas = categorias_extra_por_evento(usuario_id)

    dias = {}
    for fila in _eventos_con_categoria(usuario_id):
        fecha_evento = date.fromisoformat(fila["fecha"])
        excepciones_evento = excepciones.get(fila["id"], {})
        canceladas = {f for f, exc in excepciones_evento.items() if exc["cancelada"]}
        umbrales = umbrales_todos.get(fila["id"]) or [fila["recordatorio_dias"]]

        for ocurrencia in _ocurrencias_en_rango(
            fecha_evento, fila["repetir"], fila["repetir_hasta"], desde, hasta, fechas_canceladas=canceladas
        ):
            excepcion = excepciones_evento.get(ocurrencia.isoformat())
            evento = _fila_a_evento(
                fila, ocurrencia, excepcion=excepcion, umbrales=umbrales,
                categorias_extra=categorias_extra_todas.get(fila["id"], []),
            )
            dias.setdefault(ocurrencia.isoformat(), []).append(evento)

    for lista in dias.values():
        lista.sort(key=lambda e: e["hora"] or "00:00")
    return dias


def eventos_del_mes(usuario_id, anio, mes):
    """Devuelve un diccionario {dia (int): [eventos ese dia]} con todas
    las ocurrencias que caen dentro del mes indicado, para pintar la
    vista de calendario."""
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendario_std.monthrange(anio, mes)[1])
    por_fecha_iso = eventos_en_rango(usuario_id, primer_dia, ultimo_dia)
    return {date.fromisoformat(f).day: eventos for f, eventos in por_fecha_iso.items()}


def eventos_de_dia(usuario_id, fecha):
    """Devuelve la lista de eventos (con su ocurrencia) que caen en un
    dia concreto, ordenados por hora."""
    return eventos_en_rango(usuario_id, fecha, fecha).get(fecha.isoformat(), [])


def eventos_de_semana(usuario_id, lunes):
    """Devuelve una lista de 7 diccionarios {fecha, eventos}, uno por
    cada dia de la semana que empieza en 'lunes' (lunes a domingo)."""
    domingo = lunes + timedelta(days=6)
    por_fecha_iso = eventos_en_rango(usuario_id, lunes, domingo)
    return [
        {
            "fecha": (lunes + timedelta(days=i)).isoformat(),
            "eventos": por_fecha_iso.get((lunes + timedelta(days=i)).isoformat(), []),
        }
        for i in range(7)
    ]


def evento_del_usuario(evento_id, usuario_id):
    """Comprueba que un evento existe y pertenece al usuario. Devuelve la fila o None."""
    conn = get_db_connection()
    evento = conn.execute(
        "SELECT * FROM calendario_eventos WHERE id = ? AND usuario_id = ?", (evento_id, usuario_id)
    ).fetchone()
    conn.close()
    return evento


def marcar_aviso_evento_enviado(evento_id, fecha_ocurrencia, dias_antes=0):
    """
    Registra que ya se ha enviado el aviso de este evento, para esta
    ocurrencia concreta y con este umbral ("avisar con X dias de
    antelacion") concreto, para no repetir el mismo aviso. En un evento
    recurrente, la proxima vez que le toque avisar sera de una
    ocurrencia con otra fecha, asi que basta con la pareja
    (fecha_ocurrencia, dias_antes) sin necesitar una tabla por
    ocurrencia real.
    """
    conn = get_db_connection()
    conn.execute("""
        INSERT OR IGNORE INTO calendario_avisos_enviados (evento_id, fecha_ocurrencia, dias_antes)
        VALUES (?, ?, ?)
    """, (evento_id, fecha_ocurrencia, dias_antes))
    # Se mantiene tambien la columna antigua, por si algo externo la lee.
    conn.execute(
        "UPDATE calendario_eventos SET aviso_enviado_fecha = ? WHERE id = ?",
        (fecha_ocurrencia, evento_id),
    )
    conn.commit()
    conn.close()


def avisos_ya_enviados(evento_id, fecha_ocurrencia):
    """Devuelve el conjunto de umbrales ("dias antes") para los que ya
    se ha enviado el aviso de esta ocurrencia concreta."""
    conn = get_db_connection()
    filas = conn.execute(
        "SELECT dias_antes FROM calendario_avisos_enviados WHERE evento_id = ? AND fecha_ocurrencia = ?",
        (evento_id, fecha_ocurrencia),
    ).fetchall()
    conn.close()
    return {f["dias_antes"] for f in filas}


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


def contar_eventos_por_categoria(usuario_id):
    """Cuantos esdeveniments fan servir cada categoria (com a principal
    o com a etiqueta addicional), per mostrar-ho abans d'esborrar-la."""
    conn = get_db_connection()
    filas = conn.execute("""
        SELECT categoria_id AS id, COUNT(*) AS total FROM (
            SELECT categoria_id FROM calendario_eventos
            WHERE usuario_id = ? AND categoria_id IS NOT NULL
            UNION ALL
            SELECT calendario_evento_categorias.categoria_id
            FROM calendario_evento_categorias
            JOIN calendario_eventos ON calendario_eventos.id = calendario_evento_categorias.evento_id
            WHERE calendario_eventos.usuario_id = ?
        )
        GROUP BY categoria_id
    """, (usuario_id, usuario_id)).fetchall()
    conn.close()
    return {f["id"]: f["total"] for f in filas}


def categorias_extra_evento(evento_id):
    """Categories addicionals (a mes de la principal) d'un sol
    esdeveniment, ordenades pel nom."""
    conn = get_db_connection()
    filas = conn.execute("""
        SELECT calendario_categorias.* FROM calendario_evento_categorias
        JOIN calendario_categorias ON calendario_categorias.id = calendario_evento_categorias.categoria_id
        WHERE calendario_evento_categorias.evento_id = ?
        ORDER BY calendario_categorias.nombre COLLATE NOCASE
    """, (evento_id,)).fetchall()
    conn.close()
    return filas


def categorias_extra_por_evento(usuario_id):
    """Igual que categorias_extra_evento, pero para todos los eventos
    del usuario de una vez (evita N consultas al pintar una lista)."""
    conn = get_db_connection()
    filas = conn.execute("""
        SELECT calendario_evento_categorias.evento_id, calendario_categorias.id,
               calendario_categorias.nombre, calendario_categorias.color
        FROM calendario_evento_categorias
        JOIN calendario_categorias ON calendario_categorias.id = calendario_evento_categorias.categoria_id
        JOIN calendario_eventos ON calendario_eventos.id = calendario_evento_categorias.evento_id
        WHERE calendario_eventos.usuario_id = ?
        ORDER BY calendario_categorias.nombre COLLATE NOCASE
    """, (usuario_id,)).fetchall()
    conn.close()
    resultado = {}
    for fila in filas:
        resultado.setdefault(fila["evento_id"], []).append(
            {"id": fila["id"], "nombre": fila["nombre"], "color": fila["color"]}
        )
    return resultado


def guardar_categorias_extra(evento_id, categoria_ids, usuario_id):
    """Sustituye las categorias addicionals d'un esdeveniment. Ignora
    qualsevol id que no sigui una categoria del propi usuari (i tambe
    la categoria ja triada com a principal, per no duplicar-la)."""
    conn = get_db_connection()
    categoria_principal = conn.execute(
        "SELECT categoria_id FROM calendario_eventos WHERE id = ?", (evento_id,)
    ).fetchone()["categoria_id"]

    validas = set()
    for categoria_id in categoria_ids:
        if categoria_id == categoria_principal:
            continue
        fila = conn.execute(
            "SELECT id FROM calendario_categorias WHERE id = ? AND usuario_id = ?",
            (categoria_id, usuario_id),
        ).fetchone()
        if fila:
            validas.add(categoria_id)

    conn.execute("DELETE FROM calendario_evento_categorias WHERE evento_id = ?", (evento_id,))
    for categoria_id in validas:
        conn.execute(
            "INSERT INTO calendario_evento_categorias (evento_id, categoria_id) VALUES (?, ?)",
            (evento_id, categoria_id),
        )
    conn.commit()
    conn.close()


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
    repetir = form.get("repetir", "ninguna").strip()
    repetir_hasta = form.get("repetir_hasta", "").strip()

    errores = []
    if not titulo:
        errores.append("Escriu un titol.")

    if not fecha_texto:
        errores.append("Tria una data.")
    else:
        try:
            date.fromisoformat(fecha_texto)
        except ValueError:
            errores.append("La data no es valida.")

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

    # Recordatoris: uno o varios umbrales (checkboxes con los valores
    # sugeridos, mas uno "a mida" opcional en texto libre).
    umbrales = set()
    for valor in form.getlist("recordatorios"):
        try:
            dias = int(valor)
            if dias >= 0:
                umbrales.add(dias)
        except ValueError:
            pass
    extra_texto = form.get("recordatorio_extra", "").strip()
    if extra_texto:
        try:
            dias_extra = int(extra_texto)
            if dias_extra < 0:
                raise ValueError
            umbrales.add(dias_extra)
        except ValueError:
            errores.append("El nombre de dies d'avis addicional no es valid.")
    if not umbrales:
        umbrales = {0}

    if repetir not in OPCIONES_REPETICION_CALENDARIO:
        repetir = "ninguna"

    if repetir == "ninguna" or not repetir_hasta:
        repetir_hasta = None
    else:
        try:
            date.fromisoformat(repetir_hasta)
        except ValueError:
            errores.append("La data limit de repeticio no es valida.")
            repetir_hasta = None

    categorias_extra = []
    for valor in form.getlist("categorias_extra"):
        try:
            categorias_extra.append(int(valor))
        except ValueError:
            pass

    datos = {
        "titulo": titulo,
        "categoria_id": categoria_id or None,
        "fecha": fecha_texto,
        "hora": hora_texto or None,
        "todo_el_dia": 1 if todo_el_dia else 0,
        "lugar": lugar or None,
        "descripcion": descripcion or None,
        "recordatorios_dias": sorted(umbrales),
        "repetir": repetir,
        "repetir_hasta": repetir_hasta,
        "categorias_extra": categorias_extra,
    }
    return datos, errores


def validar_formulario_excepcion(form):
    """Valida los datos del formulario para editar (no cancel·lar)
    nomes una ocurrencia concreta d'un esdeveniment recurrent."""
    titulo = form.get("titulo", "").strip()
    hora_texto = form.get("hora", "").strip()
    todo_el_dia = form.get("todo_el_dia") == "on"
    lugar = form.get("lugar", "").strip()
    descripcion = form.get("descripcion", "").strip()

    errores = []
    if not titulo:
        errores.append("Escriu un titol.")

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

    datos = {
        "titulo": titulo,
        "hora": hora_texto or None,
        "todo_el_dia": 1 if todo_el_dia else 0,
        "lugar": lugar or None,
        "descripcion": descripcion or None,
    }
    return datos, errores


# =================================================================
# Exportacion / importacion ICS (iCalendar, RFC 5545)
# =================================================================

def _escapar_texto_ics(texto):
    """Escapa los caracteres especiales de un valor de texto ICS."""
    return (
        (texto or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _plegar_linea_ics(linea):
    """Pliega una linea segun RFC 5545 (maximo 75 octetos por linea;
    las continuaciones empiezan con un espacio), para que los avisos
    largos no rompan el fichero en lectores estrictos."""
    codificado = linea.encode("utf-8")
    if len(codificado) <= 75:
        return linea

    partes = []
    inicio = 0
    limite = 75
    while inicio < len(codificado):
        trozo = codificado[inicio:inicio + limite]
        while trozo:
            try:
                texto_trozo = trozo.decode("utf-8")
                break
            except UnicodeDecodeError:
                trozo = trozo[:-1]
        else:
            texto_trozo = ""
        partes.append(texto_trozo)
        inicio += len(trozo)
        limite = 74
    return "\r\n ".join(partes)


def _lineas_evento_ics(evento_id, titulo, fecha, hora, todo_el_dia, lugar, descripcion,
                        repetir=None, repetir_hasta=None, recurrence_id=None):
    """Genera las lineas BEGIN:VEVENT..END:VEVENT de un evento (o de la
    excepcion de una ocurrencia, si se pasa 'recurrence_id')."""
    lineas = ["BEGIN:VEVENT", f"UID:webroc-evento-{evento_id}@web-roc"]
    if recurrence_id:
        valor = recurrence_id.replace("-", "")
        lineas.append(f"RECURRENCE-ID;VALUE=DATE:{valor}")
    lineas.append(f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")

    fecha_compacta = fecha.replace("-", "")
    if todo_el_dia or not hora:
        lineas.append(f"DTSTART;VALUE=DATE:{fecha_compacta}")
        dia_siguiente = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat().replace("-", "")
        lineas.append(f"DTEND;VALUE=DATE:{dia_siguiente}")
    else:
        hora_compacta = hora.replace(":", "") + "00"
        lineas.append(f"DTSTART:{fecha_compacta}T{hora_compacta}")

    lineas.append(f"SUMMARY:{_escapar_texto_ics(titulo)}")
    if lugar:
        lineas.append(f"LOCATION:{_escapar_texto_ics(lugar)}")
    if descripcion:
        lineas.append(f"DESCRIPTION:{_escapar_texto_ics(descripcion)}")

    if repetir and repetir != "ninguna":
        freq = {"diaria": "DAILY", "semanal": "WEEKLY", "mensual": "MONTHLY", "anual": "YEARLY"}[repetir]
        rrule = f"FREQ={freq}"
        if repetir_hasta:
            rrule += f";UNTIL={repetir_hasta.replace('-', '')}"
        lineas.append(f"RRULE:{rrule}")

    lineas.append("END:VEVENT")
    return [_plegar_linea_ics(linea) for linea in lineas]


def generar_ics(usuario_id):
    """Genera el contenido de un fichero .ics con todos los eventos del
    usuario: la serie base de cada uno (con su RRULE si se repite),
    mas un EXDATE por cada ocurrencia cancelada y un VEVENT de
    excepcion (RECURRENCE-ID) por cada ocurrencia editada solo a ella."""
    excepciones = _excepciones_por_evento(usuario_id)

    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//web-roc//Calendari//CA",
        "CALSCALE:GREGORIAN",
    ]

    for fila in _eventos_con_categoria(usuario_id):
        excepciones_evento = excepciones.get(fila["id"], {})

        lineas += _lineas_evento_ics(
            fila["id"], fila["titulo"], fila["fecha"], fila["hora"], fila["todo_el_dia"],
            fila["lugar"], fila["descripcion"], fila["repetir"], fila["repetir_hasta"],
        )

        # Las ocurrencias canceladas se excluyen de la serie con EXDATE...
        canceladas = [f for f, exc in excepciones_evento.items() if exc["cancelada"]]
        for fecha_cancelada in canceladas:
            valor = fecha_cancelada.replace("-", "")
            lineas.insert(len(lineas) - 1, _plegar_linea_ics(f"EXDATE;VALUE=DATE:{valor}"))

        # ...y las editadas solo a ellas se anaden como VEVENT aparte,
        # referenciando la ocurrencia original con RECURRENCE-ID.
        for fecha_ocurrencia, exc in excepciones_evento.items():
            if exc["cancelada"]:
                continue
            lineas += _lineas_evento_ics(
                fila["id"], exc["titulo"] or fila["titulo"], fecha_ocurrencia,
                exc["hora"] if exc["hora"] is not None else fila["hora"],
                exc["todo_el_dia"] if exc["todo_el_dia"] is not None else fila["todo_el_dia"],
                exc["lugar"] if exc["lugar"] is not None else fila["lugar"],
                exc["descripcion"] if exc["descripcion"] is not None else fila["descripcion"],
                recurrence_id=fecha_ocurrencia,
            )

    lineas.append("END:VCALENDAR")
    return "\r\n".join(lineas) + "\r\n"


_FREQ_A_REPETIR = {"DAILY": "diaria", "WEEKLY": "semanal", "MONTHLY": "mensual", "YEARLY": "anual"}


def _desplegar_lineas_ics(texto):
    """Deshace el plegado de lineas del ICS (una linea que continua en
    la siguiente empieza con un espacio o tabulador)."""
    lineas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    resultado = []
    for linea in lineas:
        if linea.startswith((" ", "\t")) and resultado:
            resultado[-1] += linea[1:]
        elif linea.strip():
            resultado.append(linea)
    return resultado


def _desescapar_texto_ics(texto):
    return (
        texto.replace("\\n", "\n").replace("\\N", "\n")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )


def _parsear_fecha_ics(valor):
    """Convierte un DTSTART de ICS (con o sin hora, con o sin 'Z' de
    UTC) en (fecha_iso, hora_texto_o_None). Ignora la zona horaria: se
    trata como hora local, que es como ya funciona el resto de la app."""
    valor = valor.strip()
    if "T" in valor:
        parte_fecha, parte_hora = valor.split("T", 1)
        parte_hora = parte_hora.rstrip("Z")
        fecha_iso = f"{parte_fecha[0:4]}-{parte_fecha[4:6]}-{parte_fecha[6:8]}"
        hora_texto = f"{parte_hora[0:2]}:{parte_hora[2:4]}" if len(parte_hora) >= 4 else None
        return fecha_iso, hora_texto
    fecha_iso = f"{valor[0:4]}-{valor[4:6]}-{valor[6:8]}"
    return fecha_iso, None


def importar_ics(usuario_id, texto_ics):
    """
    Importa los VEVENT de un fichero .ics como nuevos eventos del
    calendario (sin categoria, se pueden clasificar despues).

    Limitaciones asumidas para mantener el importador simple:
    - No lee EXDATE ni VEVENT de excepcion (RECURRENCE-ID): si el
      fichero los tiene, se ignoran (la serie base se importa igual).
    - Solo entiende RRULE de tipo FREQ=DAILY/WEEKLY/MONTHLY/YEARLY (sin
      INTERVAL, BYDAY, COUNT...); si la regla es mas compleja, el
      evento se importa como un evento unico (no recurrente) en su
      fecha de inicio, y se avisa de ello en el resumen devuelto.

    Devuelve (n_importados, avisos) donde avisos es una lista de
    textos sobre reglas de repeticion no soportadas.
    """
    lineas = _desplegar_lineas_ics(texto_ics)
    eventos_en_bruto = []
    evento_actual = None

    for linea in lineas:
        if linea.startswith("BEGIN:VEVENT"):
            evento_actual = {}
            continue
        if linea.startswith("END:VEVENT"):
            if evento_actual is not None:
                eventos_en_bruto.append(evento_actual)
            evento_actual = None
            continue
        if evento_actual is None or ":" not in linea:
            continue

        clave, _, valor = linea.partition(":")
        nombre_propiedad = clave.split(";")[0].upper()
        evento_actual[nombre_propiedad] = valor

    n_importados = 0
    avisos = []
    conn = get_db_connection()

    for datos in eventos_en_bruto:
        if "RECURRENCE-ID" in datos:
            continue  # excepcion de una ocurrencia: no soportado al importar

        dtstart = datos.get("DTSTART")
        if not dtstart:
            continue
        try:
            fecha_iso, hora_texto = _parsear_fecha_ics(dtstart)
            date.fromisoformat(fecha_iso)
        except (ValueError, IndexError):
            continue

        titulo = _desescapar_texto_ics(datos.get("SUMMARY", "Esdeveniment importat"))
        lugar = _desescapar_texto_ics(datos["LOCATION"]) if "LOCATION" in datos else None
        descripcion = _desescapar_texto_ics(datos["DESCRIPTION"]) if "DESCRIPTION" in datos else None
        todo_el_dia = 1 if hora_texto is None else 0

        repetir = "ninguna"
        repetir_hasta = None
        rrule = datos.get("RRULE")
        if rrule:
            partes = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
            freq = partes.get("FREQ")
            if freq in _FREQ_A_REPETIR:
                repetir = _FREQ_A_REPETIR[freq]
                if "UNTIL" in partes:
                    repetir_hasta, _ = _parsear_fecha_ics(partes["UNTIL"])
            else:
                avisos.append(f"«{titulo}»: la regla de repeticio no es compatible, s'ha importat com a unica.")

        conn.execute("""
            INSERT INTO calendario_eventos
                (usuario_id, titulo, fecha, hora, todo_el_dia, lugar, descripcion,
                 recordatorio_dias, repetir, repetir_hasta)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (usuario_id, titulo, fecha_iso, hora_texto, todo_el_dia, lugar, descripcion, repetir, repetir_hasta))
        n_importados += 1

    conn.commit()
    conn.close()
    return n_importados, avisos
