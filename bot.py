"""
Bot de Telegram para consultar y registrar informacion de la app: saldo de
tus cuentas, gastos, ingresos, transferencias, fechas de caducidad y
eventos del calendario.

Se ejecuta como un proceso APARTE de la web (python3 bot.py, no python3
app.py), pero usa la misma base de datos SQLite (usuarios.db). Eso quiere
decir que un gasto que registres por Telegram aparece tambien en la web, y
al reves: todo se guarda en el mismo sitio.

Ademas, mientras este arrancado, una vez al dia (a la hora configurada en
TELEGRAM_AVISO_HORA, en el .env) revisa todas las fechas de caducidad y
los eventos del calendario, y te avisa por Telegram la primera vez que
uno entra en su ventana de aviso (y, en las caducidades, tambien cuando
caduca). No vuelve a avisar de lo mismo hasta que revalides o edites el
registro (o, en un evento recurrente, hasta la siguiente ocurrencia).

------------------------------------------------------------------
COMO PONERLO EN MARCHA (resumen, ver README.md para mas detalle):
------------------------------------------------------------------
1. Instala las librerias (el [job-queue] es necesario para los avisos
   automaticos diarios):
     pip install -r requirements.txt
2. Habla con @BotFather en Telegram, crea un bot con /newbot y copia el
   "token" que te da.
3. Abre el archivo .env (en esta misma carpeta) y pega ese token en
   TELEGRAM_BOT_TOKEN.
4. Arranca el bot:  python3 bot.py
5. Desde la web, entra en "Mi cuenta" -> Telegram, genera un codigo, y
   envialo a tu bot con /vincular <codigo>.
6. Escribe /ayuda en el bot para ver todo lo que puede hacer.
"""

from datetime import date, timedelta
import random
from warnings import filterwarnings

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

# La libreria avisa de que un CallbackQueryHandler dentro de un
# ConversationHandler "no se rastrea por cada mensaje" cuando per_message
# no esta activado. Es el comportamiento que queremos (nuestras
# conversaciones mezclan botones con texto normal), asi que silenciamos
# ese aviso concreto para no ensuciar la consola. Mas info:
# https://github.com/python-telegram-bot/python-telegram-bot/wiki/Frequently-Asked-Questions
filterwarnings(action="ignore", message=r".*CallbackQueryHandler.*", category=PTBUserWarning)

# Reutilizamos toda la logica y la base de datos de la app web: asi no
# duplicamos codigo y los datos siempre estan sincronizados.
import app as webapp

# El token del bot, la zona horaria y la hora del aviso diario se
# configuran en el archivo .env, no aqui (ver config.py).
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_TIMEZONE, TELEGRAM_AVISO_HORA

TOKEN = TELEGRAM_BOT_TOKEN
ZONA_HORARIA = TELEGRAM_TIMEZONE
HORA_AVISO = TELEGRAM_AVISO_HORA

# Mensajes de los avisos automaticos. Cada vez que toca avisar de un
# registro se elige uno al azar de la lista correspondiente, asi no suena
# siempre igual. Puedes anadir, quitar o reescribir los que quieras: cada
# uno puede usar {nombre}, {categoria}, {dias} y {texto_estado}.
MENSAJES_AVISO_PROXIMO = [
    "\U0001F7E1 Aviso: '{nombre}' ({categoria}) {texto_estado}.",
    "\U0001F7E1 Recuerda que '{nombre}' ({categoria}) {texto_estado}. No lo dejes para el ultimo dia.",
    "\U0001F7E1 '{nombre}' ({categoria}) esta a punto de caducar: {texto_estado}.",
]

MENSAJES_AVISO_CADUCADO = [
    "\U0001F534 '{nombre}' ({categoria}) ha caducado. Cuando puedas, renuevalo.",
    "\U0001F534 Ojo: '{nombre}' ({categoria}) ya ha caducado.",
    "\U0001F534 '{nombre}' ({categoria}) caduco hace {dias} dias. Tocaria revisarlo.",
]

MENSAJES_AVISO_EVENTO_PROXIMO = [
    "\U0001F4C5 Recordatorio: '{titulo}' ({categoria}) {texto_estado}.",
    "\U0001F4C5 No se te olvide: '{titulo}' ({categoria}) {texto_estado}.",
    "\U0001F4C5 '{titulo}' ({categoria}) se acerca: {texto_estado}.",
]

MENSAJES_AVISO_EVENTO_HOY = [
    "\U0001F514 Hoy toca: '{titulo}' ({categoria}).",
    "\U0001F514 Recuerda que hoy es '{titulo}' ({categoria}).",
    "\U0001F514 '{titulo}' ({categoria}) es hoy. No te lo pierdas.",
]

# Comandos que apareceran en el menu de Telegram (el boton con forma de
# '/' o 'Menu' junto al campo de texto), con una descripcion corta cada
# uno. Se registran al arrancar el bot, en configurar_comandos().
COMANDOS_BOT = [
    BotCommand("saldo", "Saldo total y de cada cuenta"),
    BotCommand("movimientos", "Tus ultimas 5 operaciones"),
    BotCommand("caducidades", "Ver tus fechas de caducidad"),
    BotCommand("calendario", "Ver tus proximos eventos"),
    BotCommand("comprobaravisos", "Forzar ya la comprobacion de avisos"),
    BotCommand("gasto", "Registrar un gasto"),
    BotCommand("ingreso", "Registrar un ingreso"),
    BotCommand("transferencia", "Mover dinero entre tus cuentas"),
    BotCommand("nuevacaducidad", "Anadir una fecha de caducidad"),
    BotCommand("nuevoevento", "Anadir un evento al calendario"),
    BotCommand("revalidar", "Revalidar una fecha configurada"),
    BotCommand("vincular", "Vincular tu cuenta con un codigo"),
    BotCommand("desvincular", "Dejar de usar el bot con esta cuenta"),
    BotCommand("cancelar", "Cancelar lo que estuvieras haciendo"),
    BotCommand("ayuda", "Ver todos los comandos"),
]


async def configurar_comandos(aplicacion):
    """
    Registra la lista de comandos en Telegram para que salgan sugeridos en
    el menu (el boton junto al campo de texto). Se ejecuta una vez, justo
    despues de arrancar el bot (ver 'post_init' en main()). Sin esto, los
    comandos funcionan igual escribiendolos a mano, pero no aparecen ahi.
    """
    await aplicacion.bot.set_my_commands(COMANDOS_BOT)


# =================================================================
# Estados de las conversaciones (gasto/ingreso, transferencia, nueva
# caducidad). Cada numero identifica "en que paso" esta el usuario.
# =================================================================
(
    OPERACION_IMPORTE, OPERACION_CATEGORIA, OPERACION_SUBCATEGORIA,
    OPERACION_CUENTA, OPERACION_DESCRIPCION,
) = range(5)

(
    TRANSFERENCIA_IMPORTE, TRANSFERENCIA_ORIGEN,
    TRANSFERENCIA_DESTINO, TRANSFERENCIA_DESCRIPCION,
) = range(5, 9)

(
    CADUCIDAD_NOMBRE, CADUCIDAD_CATEGORIA, CADUCIDAD_FECHA,
    CADUCIDAD_AVISO, CADUCIDAD_REVALIDACION,
) = range(9, 14)

(
    EVENTO_TITULO, EVENTO_CATEGORIA, EVENTO_FECHA, EVENTO_TIPO_HORA,
    EVENTO_HORA, EVENTO_RECORDATORIO, EVENTO_REPETIR,
) = range(14, 21)


async def obtener_usuario_o_avisar(update: Update):
    """
    Comprueba que el chat que escribe ya esta vinculado a una cuenta de la
    app. Si no lo esta, envia un aviso explicando como vincularlo y
    devuelve None (para que el comando que llamo a esta funcion pare ahi).
    """
    chat_id = update.effective_chat.id
    usuario = webapp.usuario_por_chat_id(chat_id)
    if usuario is None:
        await update.message.reply_text(
            "Tu chat de Telegram todavia no esta vinculado a ninguna cuenta.\n\n"
            "Entra en la web, ve a 'Mi cuenta' -> Telegram, pulsa 'Generar codigo "
            "de vinculacion' y envialo aqui con /vincular <codigo>."
        )
    return usuario


def parsear_importe(texto):
    """Convierte un texto en un numero positivo, o devuelve None si no es valido."""
    try:
        importe = float(texto.strip().replace(",", "."))
    except ValueError:
        return None
    return importe if importe > 0 else None


# =================================================================
# Comandos sueltos (no son conversaciones con varios pasos)
# =================================================================

async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = webapp.usuario_por_chat_id(update.effective_chat.id)
    if usuario:
        await update.message.reply_text(
            f"Hola de nuevo, {usuario['username']}! Escribe /ayuda para ver que puedo hacer."
        )
    else:
        await update.message.reply_text(
            "Hola! Soy el bot de tu app de finanzas y caducidades.\n\n"
            "Para empezar, vincula tu cuenta: entra en la web, ve a 'Mi cuenta' "
            "-> Telegram, genera un codigo, y envialo aqui con:\n"
            "/vincular <codigo>"
        )


async def comando_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "*Consultar*\n"
        "/saldo - saldo total y de cada cuenta\n"
        "/movimientos - tus ultimas 5 operaciones\n"
        "/caducidades - tus fechas de caducidad\n"
        "/calendario - tus proximos eventos\n"
        "/comprobaravisos - forzar ya la comprobacion de avisos\n\n"
        "*Registrar*\n"
        "/gasto - registrar un gasto\n"
        "/ingreso - registrar un ingreso\n"
        "/transferencia - mover dinero entre tus cuentas\n"
        "/nuevacaducidad - anadir una fecha de caducidad\n"
        "/nuevoevento - anadir un evento al calendario\n"
        "/revalidar - revalidar una que ya tenga dias configurados\n\n"
        "*Cuenta*\n"
        "/vincular <codigo> - vincular tu cuenta (el codigo se genera en la web)\n"
        "/desvincular - dejar de usar el bot con esta cuenta\n"
        "/cancelar - cancelar lo que estuvieras haciendo"
    )
    await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN)


async def comando_vincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Uso: /vincular <codigo>\n\n"
            "Genera el codigo desde la web, en 'Mi cuenta' -> Telegram."
        )
        return

    codigo = context.args[0].strip()
    usuario, error = webapp.vincular_chat_con_codigo(codigo, update.effective_chat.id)

    if error:
        await update.message.reply_text(f"No se pudo vincular: {error}")
        return

    await update.message.reply_text(
        f"Cuenta vinculada correctamente. Hola, {usuario['username']}!\n"
        "Escribe /ayuda para ver que puedo hacer."
    )


async def comando_desvincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return
    webapp.desvincular_telegram(usuario["id"])
    await update.message.reply_text("Listo, este chat ya no esta vinculado a ninguna cuenta.")


async def comando_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    cuentas = webapp.obtener_cuentas(usuario["id"])
    if not cuentas:
        await update.message.reply_text(
            "Todavia no tienes ninguna cuenta. Crea una desde la web en Finanzas -> Cuentas."
        )
        return

    saldo_total = sum(c["saldo"] for c in cuentas)
    lineas = [f"*Saldo total: {webapp.formatear_euros(saldo_total)}*", ""]
    for cuenta in cuentas:
        lineas.append(f"- {cuenta['nombre']}: {webapp.formatear_euros(cuenta['saldo'])}")

    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)


async def comando_movimientos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    conn = webapp.get_db_connection()
    operaciones = conn.execute("""
        SELECT operaciones.*, cuentas.nombre AS cuenta_nombre,
               destino.nombre AS cuenta_destino_nombre,
               categorias.nombre AS categoria_nombre
        FROM operaciones
        LEFT JOIN cuentas ON cuentas.id = operaciones.cuenta_id
        LEFT JOIN cuentas AS destino ON destino.id = operaciones.cuenta_destino_id
        LEFT JOIN categorias ON categorias.id = operaciones.categoria_id
        WHERE operaciones.usuario_id = ?
        ORDER BY operaciones.fecha DESC, operaciones.id DESC
        LIMIT 5
    """, (usuario["id"],)).fetchall()
    conn.close()

    if not operaciones:
        await update.message.reply_text("Todavia no tienes ninguna operacion registrada.")
        return

    emoji_por_tipo = {"gasto": "\U0001F534", "ingreso": "\U0001F7E2", "transferencia": "\U0001F501"}
    lineas = ["*Ultimos movimientos:*", ""]
    for op in operaciones:
        signo = "-" if op["tipo"] == "gasto" else ("+" if op["tipo"] == "ingreso" else "")
        detalle = op["categoria_nombre"] or f"{op['cuenta_nombre']} -> {op['cuenta_destino_nombre']}"
        lineas.append(
            f"{emoji_por_tipo[op['tipo']]} {op['fecha']}: {signo}{webapp.formatear_euros(op['monto'])} ({detalle})"
        )

    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)


async def comando_caducidades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    items = webapp.obtener_caducidades(usuario["id"])
    if not items:
        await update.message.reply_text("Todavia no tienes ninguna fecha de caducidad guardada.")
        return

    emoji_por_estado = {"caducado": "\U0001F534", "proximo": "\U0001F7E1", "vigente": "\U0001F7E2"}
    lineas = ["*Fechas de caducidad:*", ""]
    for item in items[:15]:
        lineas.append(
            f"{emoji_por_estado[item['estado']]} {item['nombre']} ({item['categoria']}) - {item['texto_estado']}"
        )
    if len(items) > 15:
        lineas.append(f"\n... y {len(items) - 15} mas. Mira el listado completo en la web.")

    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)


async def comando_calendario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    items = webapp.obtener_eventos(usuario["id"], incluir_pasados=False)
    if not items:
        await update.message.reply_text(
            "No tienes ningun evento proximo. Anade uno con /nuevoevento, o desde la web."
        )
        return

    emoji_por_estado = {"hoy": "\U0001F534", "proximo": "\U0001F7E1", "futuro": "\U0001F7E2"}
    lineas = ["*Proximos eventos:*", ""]
    for item in items[:15]:
        hora = f" {item['hora']}" if item["hora"] else ""
        repeticion = " \U0001F501" if item["repetir"] != "ninguna" else ""
        lineas.append(
            f"{emoji_por_estado[item['estado']]} {item['fecha_ocurrencia']}{hora} - "
            f"{item['titulo']} ({item['categoria_nombre']}) - {item['texto_estado']}{repeticion}"
        )
    if len(items) > 15:
        lineas.append(f"\n... y {len(items) - 15} mas. Mira el calendario completo en la web.")

    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)


async def comando_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Vale, lo he cancelado.")
    return ConversationHandler.END


# =================================================================
# Conversacion: /gasto e /ingreso (comparten los mismos pasos, solo
# cambia el "tipo" que se guarda en context.user_data)
# =================================================================

async def iniciar_operacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return ConversationHandler.END

    tipo = "gasto" if update.message.text.startswith("/gasto") else "ingreso"
    context.user_data["operacion"] = {"tipo": tipo, "usuario_id": usuario["id"]}

    await update.message.reply_text(
        f"Vale, vamos a registrar un {tipo}. ¿Cuanto? (solo el numero, ej: 12.50)"
    )
    return OPERACION_IMPORTE


async def operacion_importe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    importe = parsear_importe(update.message.text)
    if importe is None:
        await update.message.reply_text("Ese importe no es valido. Escribe solo un numero mayor que 0, ej: 12.50")
        return OPERACION_IMPORTE

    datos = context.user_data["operacion"]
    datos["monto"] = importe

    categorias = [c for c in webapp.obtener_categorias_con_subcategorias(datos["usuario_id"]) if c["tipo"] == datos["tipo"]]
    if not categorias:
        await update.message.reply_text(
            f"Todavia no tienes ninguna categoria de {datos['tipo']}. Crea una desde la web "
            "en Finanzas -> Categorias y vuelve a intentarlo."
        )
        context.user_data.pop("operacion", None)
        return ConversationHandler.END

    datos["categorias"] = categorias
    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"cat:{c['id']}")] for c in categorias]
    await update.message.reply_text("Elige una categoria:", reply_markup=InlineKeyboardMarkup(botones))
    return OPERACION_CATEGORIA


async def operacion_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria_id = int(query.data.split(":")[1])

    datos = context.user_data["operacion"]
    categoria = next((c for c in datos["categorias"] if c["id"] == categoria_id), None)
    if categoria is None:
        await query.edit_message_text("Esa categoria ya no es valida. Prueba de nuevo con /gasto o /ingreso.")
        return ConversationHandler.END

    datos["categoria_id"] = categoria_id
    datos["categoria_nombre"] = categoria["nombre"]

    if not categoria["subcategorias"]:
        await query.edit_message_text(
            f"La categoria '{categoria['nombre']}' todavia no tiene ninguna subcategoria. "
            "Crea una desde la web en Finanzas -> Categorias."
        )
        context.user_data.pop("operacion", None)
        return ConversationHandler.END

    botones = [[InlineKeyboardButton(s["nombre"], callback_data=f"sub:{s['id']}")] for s in categoria["subcategorias"]]
    await query.edit_message_text(
        f"Categoria: {categoria['nombre']}\n\nAhora elige la subcategoria:",
        reply_markup=InlineKeyboardMarkup(botones),
    )
    return OPERACION_SUBCATEGORIA


async def operacion_subcategoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subcategoria_id = int(query.data.split(":")[1])

    datos = context.user_data["operacion"]
    categoria = next(c for c in datos["categorias"] if c["id"] == datos["categoria_id"])
    subcategoria = next((s for s in categoria["subcategorias"] if s["id"] == subcategoria_id), None)
    if subcategoria is None:
        await query.edit_message_text("Esa subcategoria ya no es valida. Prueba de nuevo.")
        return ConversationHandler.END

    datos["subcategoria_id"] = subcategoria_id
    datos["subcategoria_nombre"] = subcategoria["nombre"]

    cuentas = webapp.obtener_cuentas(datos["usuario_id"])
    datos["cuentas"] = cuentas
    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"cta:{c['id']}")] for c in cuentas]
    await query.edit_message_text(
        f"Subcategoria: {subcategoria['nombre']}\n\n¿De que cuenta?",
        reply_markup=InlineKeyboardMarkup(botones),
    )
    return OPERACION_CUENTA


async def operacion_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cuenta_id = int(query.data.split(":")[1])

    datos = context.user_data["operacion"]
    cuenta = next((c for c in datos["cuentas"] if c["id"] == cuenta_id), None)
    if cuenta is None:
        await query.edit_message_text("Esa cuenta ya no es valida. Prueba de nuevo.")
        return ConversationHandler.END

    datos["cuenta_id"] = cuenta_id
    datos["cuenta_nombre"] = cuenta["nombre"]

    await query.edit_message_text(
        f"Cuenta: {cuenta['nombre']}\n\n¿Alguna descripcion? Escribela, o envia - para dejarla vacia."
    )
    return OPERACION_DESCRIPCION


async def operacion_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    descripcion = "" if texto == "-" else texto

    datos = context.user_data["operacion"]
    hoy = date.today().isoformat()

    conn = webapp.get_db_connection()
    columna_saldo = "saldo - ?" if datos["tipo"] == "gasto" else "saldo + ?"
    conn.execute(f"UPDATE cuentas SET saldo = {columna_saldo} WHERE id = ?", (datos["monto"], datos["cuenta_id"]))
    conn.execute("""
        INSERT INTO operaciones (usuario_id, tipo, cuenta_id, categoria_id, subcategoria_id, monto, descripcion, fecha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datos["usuario_id"], datos["tipo"], datos["cuenta_id"],
        datos["categoria_id"], datos["subcategoria_id"], datos["monto"], descripcion, hoy,
    ))
    conn.commit()
    conn.close()

    emoji = "\U0001F534" if datos["tipo"] == "gasto" else "\U0001F7E2"
    await update.message.reply_text(
        f"{emoji} {datos['tipo'].capitalize()} guardado: {webapp.formatear_euros(datos['monto'])}\n"
        f"{datos['categoria_nombre']} > {datos['subcategoria_nombre']}\n"
        f"Cuenta: {datos['cuenta_nombre']}"
    )
    context.user_data.pop("operacion", None)
    return ConversationHandler.END


conversacion_operacion = ConversationHandler(
    entry_points=[CommandHandler("gasto", iniciar_operacion), CommandHandler("ingreso", iniciar_operacion)],
    states={
        OPERACION_IMPORTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, operacion_importe)],
        OPERACION_CATEGORIA: [CallbackQueryHandler(operacion_categoria, pattern=r"^cat:")],
        OPERACION_SUBCATEGORIA: [CallbackQueryHandler(operacion_subcategoria, pattern=r"^sub:")],
        OPERACION_CUENTA: [CallbackQueryHandler(operacion_cuenta, pattern=r"^cta:")],
        OPERACION_DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, operacion_descripcion)],
    },
    fallbacks=[CommandHandler("cancelar", comando_cancelar)],
)


# =================================================================
# Conversacion: /transferencia
# =================================================================

async def iniciar_transferencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return ConversationHandler.END

    cuentas = webapp.obtener_cuentas(usuario["id"])
    if len(cuentas) < 2:
        await update.message.reply_text(
            "Necesitas al menos 2 cuentas para hacer una transferencia. "
            "Crea otra desde la web en Finanzas -> Cuentas."
        )
        return ConversationHandler.END

    context.user_data["transferencia"] = {"usuario_id": usuario["id"], "cuentas": cuentas}
    await update.message.reply_text("Vamos a registrar una transferencia. ¿Cuanto? (solo el numero, ej: 100)")
    return TRANSFERENCIA_IMPORTE


async def transferencia_importe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    importe = parsear_importe(update.message.text)
    if importe is None:
        await update.message.reply_text("Ese importe no es valido. Escribe solo un numero mayor que 0.")
        return TRANSFERENCIA_IMPORTE

    datos = context.user_data["transferencia"]
    datos["monto"] = importe

    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"origen:{c['id']}")] for c in datos["cuentas"]]
    await update.message.reply_text("¿Desde que cuenta sale el dinero?", reply_markup=InlineKeyboardMarkup(botones))
    return TRANSFERENCIA_ORIGEN


async def transferencia_origen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    origen_id = int(query.data.split(":")[1])

    datos = context.user_data["transferencia"]
    origen = next((c for c in datos["cuentas"] if c["id"] == origen_id), None)
    if origen is None:
        await query.edit_message_text("Esa cuenta ya no es valida. Prueba de nuevo.")
        return ConversationHandler.END

    datos["origen_id"] = origen_id
    datos["origen_nombre"] = origen["nombre"]

    destinos = [c for c in datos["cuentas"] if c["id"] != origen_id]
    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"destino:{c['id']}")] for c in destinos]
    await query.edit_message_text(
        f"Origen: {origen['nombre']}\n\n¿A que cuenta llega el dinero?",
        reply_markup=InlineKeyboardMarkup(botones),
    )
    return TRANSFERENCIA_DESTINO


async def transferencia_destino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    destino_id = int(query.data.split(":")[1])

    datos = context.user_data["transferencia"]
    destino = next((c for c in datos["cuentas"] if c["id"] == destino_id), None)
    if destino is None:
        await query.edit_message_text("Esa cuenta ya no es valida. Prueba de nuevo.")
        return ConversationHandler.END

    datos["destino_id"] = destino_id
    datos["destino_nombre"] = destino["nombre"]

    await query.edit_message_text(
        f"Destino: {destino['nombre']}\n\n¿Alguna descripcion? Escribela, o envia - para dejarla vacia."
    )
    return TRANSFERENCIA_DESCRIPCION


async def transferencia_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    descripcion = "" if texto == "-" else texto

    datos = context.user_data["transferencia"]
    hoy = date.today().isoformat()

    conn = webapp.get_db_connection()
    conn.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?", (datos["monto"], datos["origen_id"]))
    conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (datos["monto"], datos["destino_id"]))
    conn.execute("""
        INSERT INTO operaciones (usuario_id, tipo, cuenta_id, cuenta_destino_id, monto, descripcion, fecha)
        VALUES (?, 'transferencia', ?, ?, ?, ?, ?)
    """, (datos["usuario_id"], datos["origen_id"], datos["destino_id"], datos["monto"], descripcion, hoy))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"\U0001F501 Transferencia guardada: {webapp.formatear_euros(datos['monto'])}\n"
        f"{datos['origen_nombre']} -> {datos['destino_nombre']}"
    )
    context.user_data.pop("transferencia", None)
    return ConversationHandler.END


conversacion_transferencia = ConversationHandler(
    entry_points=[CommandHandler("transferencia", iniciar_transferencia)],
    states={
        TRANSFERENCIA_IMPORTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, transferencia_importe)],
        TRANSFERENCIA_ORIGEN: [CallbackQueryHandler(transferencia_origen, pattern=r"^origen:")],
        TRANSFERENCIA_DESTINO: [CallbackQueryHandler(transferencia_destino, pattern=r"^destino:")],
        TRANSFERENCIA_DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, transferencia_descripcion)],
    },
    fallbacks=[CommandHandler("cancelar", comando_cancelar)],
)


# =================================================================
# Conversacion: /nuevacaducidad
# =================================================================

async def iniciar_caducidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return ConversationHandler.END

    context.user_data["caducidad"] = {"usuario_id": usuario["id"]}
    await update.message.reply_text("Vamos a anadir una fecha de caducidad. ¿Como se llama? (ej: ITV del coche)")
    return CADUCIDAD_NOMBRE


async def caducidad_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.message.text.strip()
    if not nombre:
        await update.message.reply_text("Escribe un nombre valido.")
        return CADUCIDAD_NOMBRE

    context.user_data["caducidad"]["nombre"] = nombre

    botones = [[InlineKeyboardButton(cat, callback_data=f"catcad:{cat}")] for cat in webapp.CATEGORIAS_CADUCIDAD_SUGERIDAS]
    await update.message.reply_text("¿Que categoria es?", reply_markup=InlineKeyboardMarkup(botones))
    return CADUCIDAD_CATEGORIA


async def caducidad_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria = query.data.split(":", 1)[1]
    context.user_data["caducidad"]["categoria"] = categoria

    await query.edit_message_text(
        f"Categoria: {categoria}\n\n¿Que fecha de caducidad? (formato AAAA-MM-DD, ej: 2027-03-15)"
    )
    return CADUCIDAD_FECHA


async def caducidad_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        date.fromisoformat(texto)
    except ValueError:
        await update.message.reply_text("Esa fecha no es valida. Usa el formato AAAA-MM-DD, ej: 2027-03-15")
        return CADUCIDAD_FECHA

    context.user_data["caducidad"]["fecha_caducidad"] = texto

    botones = [
        [InlineKeyboardButton("7 dias", callback_data="aviso:7"), InlineKeyboardButton("15 dias", callback_data="aviso:15")],
        [InlineKeyboardButton("30 dias", callback_data="aviso:30"), InlineKeyboardButton("60 dias", callback_data="aviso:60")],
    ]
    await update.message.reply_text(
        "¿Con cuantos dias de antelacion quieres el aviso?", reply_markup=InlineKeyboardMarkup(botones)
    )
    return CADUCIDAD_AVISO


async def caducidad_aviso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dias = int(query.data.split(":")[1])
    context.user_data["caducidad"]["aviso_dias"] = dias

    botones = [
        [InlineKeyboardButton("Sin revalidacion", callback_data="reval:0")],
        [InlineKeyboardButton("Cada 30 dias", callback_data="reval:30"), InlineKeyboardButton("Cada 90 dias", callback_data="reval:90")],
        [InlineKeyboardButton("Cada 365 dias", callback_data="reval:365")],
    ]
    await query.edit_message_text(
        f"Aviso: {dias} dias antes\n\n¿Cada cuantos dias se revalida? (elige 'Sin revalidacion' si no se repite)",
        reply_markup=InlineKeyboardMarkup(botones),
    )
    return CADUCIDAD_REVALIDACION


async def caducidad_revalidacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dias = int(query.data.split(":")[1])

    datos = context.user_data["caducidad"]
    datos["dias_revalidacion"] = dias if dias > 0 else None

    conn = webapp.get_db_connection()
    conn.execute("""
        INSERT INTO caducidades (usuario_id, nombre, categoria, fecha_caducidad, aviso_dias, dias_revalidacion, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datos["usuario_id"], datos["nombre"], datos["categoria"],
        datos["fecha_caducidad"], datos["aviso_dias"], datos["dias_revalidacion"], "",
    ))
    conn.commit()
    conn.close()

    await query.edit_message_text(f"\u2705 '{datos['nombre']}' guardado. Caduca el {datos['fecha_caducidad']}.")
    context.user_data.pop("caducidad", None)
    return ConversationHandler.END


conversacion_caducidad = ConversationHandler(
    entry_points=[CommandHandler("nuevacaducidad", iniciar_caducidad)],
    states={
        CADUCIDAD_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, caducidad_nombre)],
        CADUCIDAD_CATEGORIA: [CallbackQueryHandler(caducidad_categoria, pattern=r"^catcad:")],
        CADUCIDAD_FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, caducidad_fecha)],
        CADUCIDAD_AVISO: [CallbackQueryHandler(caducidad_aviso, pattern=r"^aviso:")],
        CADUCIDAD_REVALIDACION: [CallbackQueryHandler(caducidad_revalidacion, pattern=r"^reval:")],
    },
    fallbacks=[CommandHandler("cancelar", comando_cancelar)],
)


# =================================================================
# Conversacion: /nuevoevento
# =================================================================

def _botones_recordatorio_evento():
    return [
        [InlineKeyboardButton("El mismo dia", callback_data="recordevento:0")],
        [
            InlineKeyboardButton("1 dia antes", callback_data="recordevento:1"),
            InlineKeyboardButton("3 dias antes", callback_data="recordevento:3"),
        ],
        [InlineKeyboardButton("7 dias antes", callback_data="recordevento:7")],
    ]


async def iniciar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return ConversationHandler.END

    context.user_data["evento"] = {"usuario_id": usuario["id"]}
    await update.message.reply_text(
        "Vamos a anadir un evento al calendario. ¿Que titulo le pones? (ej: Cena con Marta)"
    )
    return EVENTO_TITULO


async def evento_titulo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    titulo = update.message.text.strip()
    if not titulo:
        await update.message.reply_text("Escribe un titulo valido.")
        return EVENTO_TITULO

    context.user_data["evento"]["titulo"] = titulo
    usuario_id = context.user_data["evento"]["usuario_id"]

    categorias = webapp.obtener_categorias_calendario(usuario_id)
    botones = [[InlineKeyboardButton(cat["nombre"], callback_data=f"catevento:{cat['id']}")] for cat in categorias]
    botones.append([InlineKeyboardButton("Sin categoria", callback_data="catevento:0")])

    await update.message.reply_text(
        "¿Que categoria es? (puedes elegir 'Sin categoria')", reply_markup=InlineKeyboardMarkup(botones)
    )
    return EVENTO_CATEGORIA


async def evento_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria_id = int(query.data.split(":")[1])
    context.user_data["evento"]["categoria_id"] = categoria_id or None

    await query.edit_message_text("¿Que fecha? (formato AAAA-MM-DD, ej: 2026-08-15)")
    return EVENTO_FECHA


async def evento_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        date.fromisoformat(texto)
    except ValueError:
        await update.message.reply_text("Esa fecha no es valida. Usa el formato AAAA-MM-DD, ej: 2026-08-15")
        return EVENTO_FECHA

    context.user_data["evento"]["fecha"] = texto

    botones = [[
        InlineKeyboardButton("Todo el dia", callback_data="horaevento:todoeldia"),
        InlineKeyboardButton("A una hora", callback_data="horaevento:hora"),
    ]]
    await update.message.reply_text("¿Todo el dia, o a una hora concreta?", reply_markup=InlineKeyboardMarkup(botones))
    return EVENTO_TIPO_HORA


async def evento_tipo_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    eleccion = query.data.split(":")[1]

    if eleccion == "hora":
        context.user_data["evento"]["todo_el_dia"] = False
        await query.edit_message_text("¿A que hora? (formato HH:MM, ej: 19:30)")
        return EVENTO_HORA

    context.user_data["evento"]["todo_el_dia"] = True
    context.user_data["evento"]["hora"] = None
    await query.edit_message_text(
        "Vale, todo el dia.\n\n¿Con cuantos dias de antelacion quieres el aviso?",
        reply_markup=InlineKeyboardMarkup(_botones_recordatorio_evento()),
    )
    return EVENTO_RECORDATORIO


async def evento_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        horas, minutos = texto.split(":")
        if not (0 <= int(horas) <= 23 and 0 <= int(minutos) <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Esa hora no es valida. Usa el formato HH:MM, ej: 19:30")
        return EVENTO_HORA

    context.user_data["evento"]["hora"] = texto
    await update.message.reply_text(
        "¿Con cuantos dias de antelacion quieres el aviso?",
        reply_markup=InlineKeyboardMarkup(_botones_recordatorio_evento()),
    )
    return EVENTO_RECORDATORIO


async def evento_recordatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dias = int(query.data.split(":")[1])
    context.user_data["evento"]["recordatorio_dias"] = dias

    botones = [
        [InlineKeyboardButton("No se repite", callback_data="repetirevento:ninguna")],
        [
            InlineKeyboardButton("Cada dia", callback_data="repetirevento:diaria"),
            InlineKeyboardButton("Cada semana", callback_data="repetirevento:semanal"),
        ],
        [
            InlineKeyboardButton("Cada mes", callback_data="repetirevento:mensual"),
            InlineKeyboardButton("Cada ano", callback_data="repetirevento:anual"),
        ],
    ]
    await query.edit_message_text("¿Se repite?", reply_markup=InlineKeyboardMarkup(botones))
    return EVENTO_REPETIR


async def evento_repetir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    repetir = query.data.split(":")[1]

    datos = context.user_data["evento"]
    datos["repetir"] = repetir

    # Los botones de categoria solo ofrecen las del propio usuario (o
    # "Sin categoria"), pero comprobamos igualmente antes de guardar, por
    # si el callback llega manipulado.
    categoria_id = datos.get("categoria_id")
    if categoria_id and not webapp.categoria_calendario_del_usuario(categoria_id, datos["usuario_id"]):
        categoria_id = None

    conn = webapp.get_db_connection()
    conn.execute("""
        INSERT INTO calendario_eventos
            (usuario_id, titulo, categoria_id, fecha, hora, todo_el_dia, recordatorio_dias, repetir)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datos["usuario_id"], datos["titulo"], categoria_id, datos["fecha"],
        datos.get("hora"), 1 if datos["todo_el_dia"] else 0, datos["recordatorio_dias"], repetir,
    ))
    conn.commit()
    conn.close()

    resumen_hora = f" a las {datos['hora']}" if datos.get("hora") else " (todo el dia)"
    await query.edit_message_text(f"\u2705 '{datos['titulo']}' anadido el {datos['fecha']}{resumen_hora}.")
    context.user_data.pop("evento", None)
    return ConversationHandler.END


conversacion_evento = ConversationHandler(
    entry_points=[CommandHandler("nuevoevento", iniciar_evento)],
    states={
        EVENTO_TITULO: [MessageHandler(filters.TEXT & ~filters.COMMAND, evento_titulo)],
        EVENTO_CATEGORIA: [CallbackQueryHandler(evento_categoria, pattern=r"^catevento:")],
        EVENTO_FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, evento_fecha)],
        EVENTO_TIPO_HORA: [CallbackQueryHandler(evento_tipo_hora, pattern=r"^horaevento:")],
        EVENTO_HORA: [MessageHandler(filters.TEXT & ~filters.COMMAND, evento_hora)],
        EVENTO_RECORDATORIO: [CallbackQueryHandler(evento_recordatorio, pattern=r"^recordevento:")],
        EVENTO_REPETIR: [CallbackQueryHandler(evento_repetir, pattern=r"^repetirevento:")],
    },
    fallbacks=[CommandHandler("cancelar", comando_cancelar)],
)


# =================================================================
# /revalidar (no es una conversacion: un comando + botones)
# =================================================================

async def comando_revalidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    items = [i for i in webapp.obtener_caducidades(usuario["id"]) if i["dias_revalidacion"]]
    if not items:
        await update.message.reply_text(
            "No tienes ningun registro con dias de revalidacion configurados.\n"
            "Puedes anadirlo editando el registro desde la web, o al crearlo con /nuevacaducidad."
        )
        return

    botones = [
        [InlineKeyboardButton(f"{i['nombre']} ({i['dias_revalidacion']} dias)", callback_data=f"revalidar:{i['id']}")]
        for i in items
    ]
    await update.message.reply_text("¿Que quieres revalidar?", reply_markup=InlineKeyboardMarkup(botones))


async def revalidar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    caducidad_id = int(query.data.split(":")[1])

    usuario = webapp.usuario_por_chat_id(update.effective_chat.id)
    item = webapp.caducidad_del_usuario(caducidad_id, usuario["id"]) if usuario else None
    if item is None or not item["dias_revalidacion"]:
        await query.edit_message_text("Ese registro ya no se puede revalidar.")
        return

    nueva_fecha = date.today() + timedelta(days=item["dias_revalidacion"])
    conn = webapp.get_db_connection()
    conn.execute(
        "UPDATE caducidades SET fecha_caducidad = ?, aviso_proximo_enviado = 0, aviso_caducado_enviado = 0 WHERE id = ?",
        (nueva_fecha.isoformat(), caducidad_id),
    )
    conn.commit()
    conn.close()

    await query.edit_message_text(f"\u2705 '{item['nombre']}' revalidado. Nueva fecha: {nueva_fecha.isoformat()}.")


# =================================================================
# Aviso automatico diario (y comando manual /comprobaravisos)
# =================================================================

def _texto_aviso_si_toca(item):
    """
    Si a este registro de caducidad le toca avisar ahora (esta 'proximo' o
    'caducado' y todavia no se aviso de eso), devuelve el texto ya
    formateado. Si no le toca avisar, devuelve None.
    """
    if item["estado"] == "proximo" and not item["aviso_proximo_enviado"]:
        plantilla = random.choice(MENSAJES_AVISO_PROXIMO)
    elif item["estado"] == "caducado" and not item["aviso_caducado_enviado"]:
        plantilla = random.choice(MENSAJES_AVISO_CADUCADO)
    else:
        return None

    return plantilla.format(
        nombre=item["nombre"],
        categoria=item["categoria"],
        dias=abs(item["dias"]),
        texto_estado=item["texto_estado"][0].lower() + item["texto_estado"][1:],
    )


async def revisar_caducidades(context: ContextTypes.DEFAULT_TYPE):
    """
    Tarea programada: recorre las fechas de caducidad de todos los
    usuarios que tienen Telegram vinculado, y envia un mensaje la primera
    vez que una entra en su ventana de aviso, y la primera vez que
    caduca. No repite el mismo aviso hasta que el registro se revalide o
    se edite la fecha. Se ejecuta una vez nada mas arrancar el bot, y
    luego todos los dias a la hora HORA_AVISO (ver main()).
    """
    conn = webapp.get_db_connection()
    usuarios = conn.execute(
        "SELECT id, telegram_chat_id FROM usuarios WHERE telegram_chat_id IS NOT NULL"
    ).fetchall()
    conn.close()

    print(f"[avisos] Revisando caducidades de {len(usuarios)} usuario(s) con Telegram vinculado...")
    total_enviados = 0

    for usuario in usuarios:
        for item in webapp.obtener_caducidades(usuario["id"]):
            texto = _texto_aviso_si_toca(item)
            if texto is None:
                continue

            try:
                await context.bot.send_message(chat_id=usuario["telegram_chat_id"], text=texto)
                webapp.marcar_aviso_enviado(item["id"], item["estado"])
                total_enviados += 1
            except Exception as error:
                # Por ejemplo, si el usuario bloqueo el bot. No paramos por
                # esto, seguimos revisando el resto de usuarios y registros.
                print(f"[avisos] No se pudo avisar a {usuario['telegram_chat_id']}: {error}")

    print(f"[avisos] Revision terminada: {total_enviados} aviso(s) enviado(s).")


def _texto_aviso_evento_si_toca(item):
    """
    Si a este evento le toca avisar ahora (esta 'hoy' o dentro de su
    ventana de recordatorio, y todavia no se aviso de ESTA ocurrencia
    concreta), devuelve el texto ya formateado. Si no le toca, devuelve
    None. Comparar contra 'fecha_ocurrencia' (en vez de un simple
    si/no) es lo que hace que un evento recurrente vuelva a avisar en
    cada repeticion, sin repetir el mismo aviso dos veces para la misma.
    """
    if item["aviso_enviado_fecha"] == item["fecha_ocurrencia"]:
        return None

    if item["estado"] == "hoy":
        plantilla = random.choice(MENSAJES_AVISO_EVENTO_HOY)
    elif item["estado"] == "proximo":
        plantilla = random.choice(MENSAJES_AVISO_EVENTO_PROXIMO)
    else:
        return None

    return plantilla.format(
        titulo=item["titulo"],
        categoria=item["categoria_nombre"],
        texto_estado=item["texto_estado"][0].lower() + item["texto_estado"][1:],
    )


async def revisar_eventos(context: ContextTypes.DEFAULT_TYPE):
    """
    Tarea programada: recorre los eventos del calendario de todos los
    usuarios con Telegram vinculado, y envia un mensaje la primera vez
    que uno entra en su ventana de recordatorio, y la primera vez que
    llega el mismo dia. En los recurrentes, esto se repite en cada
    ocurrencia. Se ejecuta junto con revisar_caducidades (ver main()).
    """
    conn = webapp.get_db_connection()
    usuarios = conn.execute(
        "SELECT id, telegram_chat_id FROM usuarios WHERE telegram_chat_id IS NOT NULL"
    ).fetchall()
    conn.close()

    print(f"[avisos] Revisando el calendario de {len(usuarios)} usuario(s) con Telegram vinculado...")
    total_enviados = 0

    for usuario in usuarios:
        for item in webapp.obtener_eventos(usuario["id"], incluir_pasados=False):
            texto = _texto_aviso_evento_si_toca(item)
            if texto is None:
                continue

            try:
                await context.bot.send_message(chat_id=usuario["telegram_chat_id"], text=texto)
                webapp.marcar_aviso_evento_enviado(item["id"], item["fecha_ocurrencia"])
                total_enviados += 1
            except Exception as error:
                print(f"[avisos] No se pudo avisar a {usuario['telegram_chat_id']}: {error}")

    print(f"[avisos] Revision del calendario terminada: {total_enviados} aviso(s) enviado(s).")


async def comando_comprobar_avisos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fuerza ya mismo la comprobacion de TUS caducidades y de TU calendario,
    sin esperar a la hora programada. Util para probar que los avisos
    funcionan, o para no tener que esperar a manana.
    """
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    enviados = 0
    for item in webapp.obtener_caducidades(usuario["id"]):
        texto = _texto_aviso_si_toca(item)
        if texto is None:
            continue
        await update.message.reply_text(texto)
        webapp.marcar_aviso_enviado(item["id"], item["estado"])
        enviados += 1

    for item in webapp.obtener_eventos(usuario["id"], incluir_pasados=False):
        texto = _texto_aviso_evento_si_toca(item)
        if texto is None:
            continue
        await update.message.reply_text(texto)
        webapp.marcar_aviso_evento_enviado(item["id"], item["fecha_ocurrencia"])
        enviados += 1

    if enviados == 0:
        await update.message.reply_text(
            "No hay ningun aviso pendiente ahora mismo: o no te toca todavia, o ya te "
            "avisamos de todo lo que tocaba. Usa /caducidades y /calendario para ver el estado de todo."
        )


# =================================================================
# Mensajes que no coinciden con ningun comando ni conversacion activa
# =================================================================

async def mensaje_no_entendido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("No entendi eso. Escribe /ayuda para ver los comandos disponibles.")


async def manejador_errores(update, context):
    print(f"Error en el bot: {context.error}")


def main():
    # Nos aseguramos de que la base de datos y todas sus tablas existen,
    # por si este es el primer sitio desde el que se arranca la app.
    webapp.init_db()

    if not TOKEN:
        print(
            "Falta configurar el token del bot.\n"
            "Abre el archivo .env (en esta misma carpeta) y pega tu token "
            "(el que te da @BotFather) en TELEGRAM_BOT_TOKEN."
        )
        return

    aplicacion = ApplicationBuilder().token(TOKEN).post_init(configurar_comandos).build()

    aplicacion.add_handler(CommandHandler("start", comando_start))
    aplicacion.add_handler(CommandHandler(["ayuda", "help"], comando_ayuda))
    aplicacion.add_handler(CommandHandler("vincular", comando_vincular))
    aplicacion.add_handler(CommandHandler("desvincular", comando_desvincular))
    aplicacion.add_handler(CommandHandler("saldo", comando_saldo))
    aplicacion.add_handler(CommandHandler("movimientos", comando_movimientos))
    aplicacion.add_handler(CommandHandler("caducidades", comando_caducidades))
    aplicacion.add_handler(CommandHandler("calendario", comando_calendario))
    aplicacion.add_handler(CommandHandler("revalidar", comando_revalidar))
    aplicacion.add_handler(CommandHandler("comprobaravisos", comando_comprobar_avisos))
    aplicacion.add_handler(CallbackQueryHandler(revalidar_callback, pattern=r"^revalidar:"))

    aplicacion.add_handler(conversacion_operacion)
    aplicacion.add_handler(conversacion_transferencia)
    aplicacion.add_handler(conversacion_caducidad)
    aplicacion.add_handler(conversacion_evento)

    # Este handler va el ultimo: solo se dispara si ningun otro ha
    # respondido ya al mensaje.
    aplicacion.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_no_entendido))

    aplicacion.add_error_handler(manejador_errores)

    if aplicacion.job_queue is not None:
        aplicacion.job_queue.run_daily(revisar_caducidades, time=HORA_AVISO, name="revisar_caducidades")
        aplicacion.job_queue.run_daily(revisar_eventos, time=HORA_AVISO, name="revisar_eventos")
        # Ademas de la revision diaria, hacemos una nada mas arrancar (unos
        # segundos despues de conectar), para no tener que esperar hasta la
        # hora programada para comprobar que los avisos funcionan.
        aplicacion.job_queue.run_once(revisar_caducidades, when=5, name="revisar_caducidades_al_arrancar")
        aplicacion.job_queue.run_once(revisar_eventos, when=5, name="revisar_eventos_al_arrancar")
        zona_texto = str(ZONA_HORARIA) if ZONA_HORARIA else "UTC"
        print(f"Aviso automatico programado todos los dias a las {HORA_AVISO.strftime('%H:%M')} ({zona_texto}).")
        print("Ademas, se hara una primera comprobacion en unos segundos (mira la consola).")
    else:
        print(
            "Aviso: no se han programado los avisos automaticos (caducidades ni calendario) porque "
            'falta el extra "job-queue". Instalalo con:\n'
            '  pip install "python-telegram-bot[job-queue]==22.8" --break-system-packages\n'
            "El resto del bot (comandos, /gasto, /caducidades, /calendario, etc.) funciona igual sin "
            "esto. Tambien puedes usar /comprobaravisos en cualquier momento para comprobarlo a mano."
        )

    print("Bot arrancado. Pulsa Ctrl+C para pararlo.")
    aplicacion.run_polling()


if __name__ == "__main__":
    main()
