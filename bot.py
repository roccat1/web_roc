"""
Bot de Telegram (en catala) para consultar i registrar informacio de
l'app: saldo dels teus comptes, despeses, ingressos, transferencies,
dates de caducitat i esdeveniments del calendari.

Es executa com un proces A PART de la web (python3 bot.py, no python3
app.py), pero fa servir la mateixa base de dades SQLite (usuarios.db).
Aixo vol dir que una despesa que registris per Telegram apareix tambe
a la web, i al reves: tot es guarda al mateix lloc.

A mes, mentre estigui arrencat, un cop al dia (a l'hora configurada a
TELEGRAM_AVISO_HORA, al .env) revisa totes les dates de caducitat i
els esdeveniments del calendari, i t'avisa per Telegram la primera
vegada que un entra a la seva finestra d'avis (i, en les caducitats,
tambe quan caduca). No torna a avisar del mateix fins que revalidis o
editis el registre (o, en un esdeveniment recurrent, fins a la
seguent ocurrencia).

------------------------------------------------------------------
COM POSAR-LO EN MARXA (resum, veure README.md per a mes detall):
------------------------------------------------------------------
1. Instal·la les llibreries (el [job-queue] es necessari per als avisos
   automatics diaris):
     pip install -r requirements.txt
2. Parla amb @BotFather a Telegram, crea un bot amb /newbot i copia el
   "token" que et dona.
3. Obre l'arxiu .env (en aquesta mateixa carpeta) i enganxa aquest token a
   TELEGRAM_BOT_TOKEN.
4. Arrenca el bot:  python3 bot.py
5. Des de la web, entra a "El meu compte" -> Telegram, genera un codi, i
   envia'l al teu bot amb /vincular <codi>.
6. Escriu /ayuda al bot per veure tot el que pot fer.
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
    "\U0001F7E1 Avis: '{nombre}' ({categoria}) {texto_estado}.",
    "\U0001F7E1 Recorda que '{nombre}' ({categoria}) {texto_estado}. No ho deixis per a l'ultim dia.",
    "\U0001F7E1 '{nombre}' ({categoria}) esta a punt de caducar: {texto_estado}.",
]

MENSAJES_AVISO_CADUCADO = [
    "\U0001F534 '{nombre}' ({categoria}) ha caducat. Quan puguis, renova'l.",
    "\U0001F534 Compte: '{nombre}' ({categoria}) ja ha caducat.",
    "\U0001F534 '{nombre}' ({categoria}) va caducar fa {dias} dies. Tocaria revisar-ho.",
]

MENSAJES_AVISO_EVENTO_PROXIMO = [
    "\U0001F4C5 Recordatori: '{titulo}' ({categoria}) {texto_estado}.",
    "\U0001F4C5 No se t'oblidi: '{titulo}' ({categoria}) {texto_estado}.",
    "\U0001F4C5 '{titulo}' ({categoria}) s'acosta: {texto_estado}.",
]

MENSAJES_AVISO_EVENTO_HOY = [
    "\U0001F514 Avui toca: '{titulo}' ({categoria}).",
    "\U0001F514 Recorda que avui es '{titulo}' ({categoria}).",
    "\U0001F514 '{titulo}' ({categoria}) es avui. No te'l perdis.",
]

# Comandos que apareceran en el menu de Telegram (el boton con forma de
# '/' o 'Menu' junto al campo de texto), con una descripcion corta cada
# uno. Se registran al arrancar el bot, en configurar_comandos().
COMANDOS_BOT = [
    BotCommand("saldo", "Saldo total i de cada compte"),
    BotCommand("movimientos", "Les teves ultimes 5 operacions"),
    BotCommand("caducidades", "Veure les teves dates de caducitat"),
    BotCommand("calendario", "Veure els teus propers esdeveniments"),
    BotCommand("comprobaravisos", "Forcar ja la comprovacio d'avisos"),
    BotCommand("gasto", "Registrar una despesa"),
    BotCommand("ingreso", "Registrar un ingres"),
    BotCommand("transferencia", "Moure diners entre els teus comptes"),
    BotCommand("nuevacaducidad", "Afegir una data de caducitat"),
    BotCommand("nuevoevento", "Afegir un esdeveniment al calendari"),
    BotCommand("revalidar", "Revalidar una data configurada"),
    BotCommand("vincular", "Vincular el teu compte amb un codi"),
    BotCommand("desvincular", "Deixar d'usar el bot amb aquest compte"),
    BotCommand("cancelar", "Cancel·lar el que estiguessis fent"),
    BotCommand("ayuda", "Veure totes les ordres"),
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
            "El teu xat de Telegram encara no esta vinculat a cap compte.\n\n"
            "Entra a la web, ves a 'El meu compte' -> Telegram, prem 'Generar codi "
            "de vinculacio' i envia'l aqui amb /vincular <codi>."
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
            f"Hola de nou, {usuario['username']}! Escriu /ayuda per veure que puc fer."
        )
    else:
        await update.message.reply_text(
            "Hola! Soc el bot de la teva app de finances i caducitats.\n\n"
            "Per comencar, vincula el teu compte: entra a la web, ves a 'El meu compte' "
            "-> Telegram, genera un codi, i envia'l aqui amb:\n"
            "/vincular <codi>"
        )


async def comando_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "*Consultar*\n"
        "/saldo - saldo total i de cada compte\n"
        "/movimientos - les teves ultimes 5 operacions\n"
        "/caducidades - les teves dates de caducitat\n"
        "/calendario - els teus propers esdeveniments\n"
        "/comprobaravisos - forcar ja la comprovacio d'avisos\n\n"
        "*Registrar*\n"
        "/gasto - registrar una despesa\n"
        "/ingreso - registrar un ingres\n"
        "/transferencia - moure diners entre els teus comptes\n"
        "/nuevacaducidad - afegir una data de caducitat\n"
        "/nuevoevento - afegir un esdeveniment al calendari\n"
        "/revalidar - revalidar una que ja tingui dies configurats\n\n"
        "*Compte*\n"
        "/vincular <codi> - vincular el teu compte (el codi es genera a la web)\n"
        "/desvincular - deixar d'usar el bot amb aquest compte\n"
        "/cancelar - cancel·lar el que estiguessis fent"
    )
    await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN)


async def comando_vincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Us: /vincular <codi>\n\n"
            "Genera el codi des de la web, a 'El meu compte' -> Telegram."
        )
        return

    codigo = context.args[0].strip()
    usuario, error = webapp.vincular_chat_con_codigo(codigo, update.effective_chat.id)

    if error:
        await update.message.reply_text(f"No s'ha pogut vincular: {error}")
        return

    await update.message.reply_text(
        f"Compte vinculat correctament. Hola, {usuario['username']}!\n"
        "Escriu /ayuda per veure que puc fer."
    )


async def comando_desvincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return
    webapp.desvincular_telegram(usuario["id"])
    await update.message.reply_text("Llest, aquest xat ja no esta vinculat a cap compte.")


async def comando_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    cuentas = webapp.obtener_cuentas(usuario["id"])
    if not cuentas:
        await update.message.reply_text(
            "Encara no tens cap compte. Crea'n un des de la web a Finances -> Comptes."
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
        await update.message.reply_text("Encara no tens cap operacio registrada.")
        return

    emoji_por_tipo = {"gasto": "\U0001F534", "ingreso": "\U0001F7E2", "transferencia": "\U0001F501"}
    lineas = ["*Ultims moviments:*", ""]
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
        await update.message.reply_text("Encara no tens cap data de caducitat guardada.")
        return

    emoji_por_estado = {"caducado": "\U0001F534", "proximo": "\U0001F7E1", "vigente": "\U0001F7E2"}
    lineas = ["*Dates de caducitat:*", ""]
    for item in items[:15]:
        lineas.append(
            f"{emoji_por_estado[item['estado']]} {item['nombre']} ({item['categoria']}) - {item['texto_estado']}"
        )
    if len(items) > 15:
        lineas.append(f"\n... i {len(items) - 15} mes. Mira el llistat complet a la web.")

    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)


async def comando_calendario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return

    items = webapp.obtener_eventos(usuario["id"], incluir_pasados=False)
    if not items:
        await update.message.reply_text(
            "No tens cap esdeveniment proper. Afegeix-ne un amb /nuevoevento, o des de la web."
        )
        return

    emoji_por_estado = {"hoy": "\U0001F534", "proximo": "\U0001F7E1", "futuro": "\U0001F7E2"}
    lineas = ["*Propers esdeveniments:*", ""]
    for item in items[:15]:
        hora = f" {item['hora']}" if item["hora"] else ""
        repeticion = " \U0001F501" if item["repetir"] != "ninguna" else ""
        lineas.append(
            f"{emoji_por_estado[item['estado']]} {item['fecha_ocurrencia']}{hora} - "
            f"{item['titulo']} ({item['categoria_nombre']}) - {item['texto_estado']}{repeticion}"
        )
    if len(items) > 15:
        lineas.append(f"\n... i {len(items) - 15} mes. Mira el calendari complet a la web.")

    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)


async def comando_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Val, ho he cancel·lat.")
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

    tipo_texto = "una despesa" if tipo == "gasto" else "un ingres"
    await update.message.reply_text(
        f"Val, anem a registrar {tipo_texto}. Quant? (nomes el numero, ex: 12.50)"
    )
    return OPERACION_IMPORTE


async def operacion_importe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    importe = parsear_importe(update.message.text)
    if importe is None:
        await update.message.reply_text("Aquest import no es valid. Escriu nomes un numero mes gran que 0, ex: 12.50")
        return OPERACION_IMPORTE

    datos = context.user_data["operacion"]
    datos["monto"] = importe

    categorias = [c for c in webapp.obtener_categorias_con_subcategorias(datos["usuario_id"]) if c["tipo"] == datos["tipo"]]
    if not categorias:
        tipo_texto = "despesa" if datos["tipo"] == "gasto" else "ingres"
        await update.message.reply_text(
            f"Encara no tens cap categoria de {tipo_texto}. Crea'n una des de la web "
            "a Finances -> Categories i torna-ho a provar."
        )
        context.user_data.pop("operacion", None)
        return ConversationHandler.END

    datos["categorias"] = categorias
    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"cat:{c['id']}")] for c in categorias]
    await update.message.reply_text("Tria una categoria:", reply_markup=InlineKeyboardMarkup(botones))
    return OPERACION_CATEGORIA


async def operacion_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria_id = int(query.data.split(":")[1])

    datos = context.user_data["operacion"]
    categoria = next((c for c in datos["categorias"] if c["id"] == categoria_id), None)
    if categoria is None:
        await query.edit_message_text("Aquesta categoria ja no es valida. Torna-ho a provar amb /gasto o /ingreso.")
        return ConversationHandler.END

    datos["categoria_id"] = categoria_id
    datos["categoria_nombre"] = categoria["nombre"]

    if not categoria["subcategorias"]:
        await query.edit_message_text(
            f"La categoria '{categoria['nombre']}' encara no te cap subcategoria. "
            "Crea'n una des de la web a Finances -> Categories."
        )
        context.user_data.pop("operacion", None)
        return ConversationHandler.END

    botones = [[InlineKeyboardButton(s["nombre"], callback_data=f"sub:{s['id']}")] for s in categoria["subcategorias"]]
    await query.edit_message_text(
        f"Categoria: {categoria['nombre']}\n\nAra tria la subcategoria:",
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
        await query.edit_message_text("Aquesta subcategoria ja no es valida. Torna-ho a provar.")
        return ConversationHandler.END

    datos["subcategoria_id"] = subcategoria_id
    datos["subcategoria_nombre"] = subcategoria["nombre"]

    cuentas = webapp.obtener_cuentas(datos["usuario_id"])
    datos["cuentas"] = cuentas
    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"cta:{c['id']}")] for c in cuentas]
    await query.edit_message_text(
        f"Subcategoria: {subcategoria['nombre']}\n\nDe quin compte?",
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
        await query.edit_message_text("Aquest compte ja no es valid. Torna-ho a provar.")
        return ConversationHandler.END

    datos["cuenta_id"] = cuenta_id
    datos["cuenta_nombre"] = cuenta["nombre"]

    await query.edit_message_text(
        f"Compte: {cuenta['nombre']}\n\nAlguna descripcio? Escriu-la, o envia - per deixar-la buida."
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
    tipo_texto = "Despesa" if datos["tipo"] == "gasto" else "Ingres"
    await update.message.reply_text(
        f"{emoji} {tipo_texto} desada: {webapp.formatear_euros(datos['monto'])}\n"
        f"{datos['categoria_nombre']} > {datos['subcategoria_nombre']}\n"
        f"Compte: {datos['cuenta_nombre']}"
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
            "Necessites almenys 2 comptes per fer una transferencia. "
            "Crea'n un altre des de la web a Finances -> Comptes."
        )
        return ConversationHandler.END

    context.user_data["transferencia"] = {"usuario_id": usuario["id"], "cuentas": cuentas}
    await update.message.reply_text("Anem a registrar una transferencia. Quant? (nomes el numero, ex: 100)")
    return TRANSFERENCIA_IMPORTE


async def transferencia_importe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    importe = parsear_importe(update.message.text)
    if importe is None:
        await update.message.reply_text("Aquest import no es valid. Escriu nomes un numero mes gran que 0.")
        return TRANSFERENCIA_IMPORTE

    datos = context.user_data["transferencia"]
    datos["monto"] = importe

    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"origen:{c['id']}")] for c in datos["cuentas"]]
    await update.message.reply_text("De quin compte surt el diner?", reply_markup=InlineKeyboardMarkup(botones))
    return TRANSFERENCIA_ORIGEN


async def transferencia_origen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    origen_id = int(query.data.split(":")[1])

    datos = context.user_data["transferencia"]
    origen = next((c for c in datos["cuentas"] if c["id"] == origen_id), None)
    if origen is None:
        await query.edit_message_text("Aquest compte ja no es valid. Torna-ho a provar.")
        return ConversationHandler.END

    datos["origen_id"] = origen_id
    datos["origen_nombre"] = origen["nombre"]

    destinos = [c for c in datos["cuentas"] if c["id"] != origen_id]
    botones = [[InlineKeyboardButton(c["nombre"], callback_data=f"destino:{c['id']}")] for c in destinos]
    await query.edit_message_text(
        f"Origen: {origen['nombre']}\n\nA quin compte arriba el diner?",
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
        await query.edit_message_text("Aquest compte ja no es valid. Torna-ho a provar.")
        return ConversationHandler.END

    datos["destino_id"] = destino_id
    datos["destino_nombre"] = destino["nombre"]

    await query.edit_message_text(
        f"Desti: {destino['nombre']}\n\nAlguna descripcio? Escriu-la, o envia - per deixar-la buida."
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
        f"\U0001F501 Transferencia desada: {webapp.formatear_euros(datos['monto'])}\n"
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
    await update.message.reply_text("Anem a afegir una data de caducitat. Com es diu? (ex: ITV del cotxe)")
    return CADUCIDAD_NOMBRE


async def caducidad_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.message.text.strip()
    if not nombre:
        await update.message.reply_text("Escriu un nom valid.")
        return CADUCIDAD_NOMBRE

    context.user_data["caducidad"]["nombre"] = nombre

    botones = [[InlineKeyboardButton(cat, callback_data=f"catcad:{cat}")] for cat in webapp.CATEGORIAS_CADUCIDAD_SUGERIDAS]
    await update.message.reply_text("Quina categoria es?", reply_markup=InlineKeyboardMarkup(botones))
    return CADUCIDAD_CATEGORIA


async def caducidad_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria = query.data.split(":", 1)[1]
    context.user_data["caducidad"]["categoria"] = categoria

    await query.edit_message_text(
        f"Categoria: {categoria}\n\nQuina data de caducitat? (format AAAA-MM-DD, ex: 2027-03-15)"
    )
    return CADUCIDAD_FECHA


async def caducidad_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        date.fromisoformat(texto)
    except ValueError:
        await update.message.reply_text("Aquesta data no es valida. Fes servir el format AAAA-MM-DD, ex: 2027-03-15")
        return CADUCIDAD_FECHA

    context.user_data["caducidad"]["fecha_caducidad"] = texto

    botones = [
        [InlineKeyboardButton("7 dies", callback_data="aviso:7"), InlineKeyboardButton("15 dies", callback_data="aviso:15")],
        [InlineKeyboardButton("30 dies", callback_data="aviso:30"), InlineKeyboardButton("60 dies", callback_data="aviso:60")],
    ]
    await update.message.reply_text(
        "Amb quants dies d'antelacio vols l'avis?", reply_markup=InlineKeyboardMarkup(botones)
    )
    return CADUCIDAD_AVISO


async def caducidad_aviso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dias = int(query.data.split(":")[1])
    context.user_data["caducidad"]["aviso_dias"] = dias

    botones = [
        [InlineKeyboardButton("Sense revalidacio", callback_data="reval:0")],
        [InlineKeyboardButton("Cada 30 dies", callback_data="reval:30"), InlineKeyboardButton("Cada 90 dies", callback_data="reval:90")],
        [InlineKeyboardButton("Cada 365 dies", callback_data="reval:365")],
    ]
    await query.edit_message_text(
        f"Avis: {dias} dies abans\n\nCada quants dies es revalida? (tria 'Sense revalidacio' si no es repeteix)",
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

    await query.edit_message_text(f"\u2705 '{datos['nombre']}' desat. Caduca el {datos['fecha_caducidad']}.")
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
        [InlineKeyboardButton("El mateix dia", callback_data="recordevento:0")],
        [
            InlineKeyboardButton("1 dia abans", callback_data="recordevento:1"),
            InlineKeyboardButton("3 dies abans", callback_data="recordevento:3"),
        ],
        [InlineKeyboardButton("7 dies abans", callback_data="recordevento:7")],
    ]


async def iniciar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = await obtener_usuario_o_avisar(update)
    if usuario is None:
        return ConversationHandler.END

    context.user_data["evento"] = {"usuario_id": usuario["id"]}
    await update.message.reply_text(
        "Anem a afegir un esdeveniment al calendari. Quin titol li poses? (ex: Sopar amb la Marta)"
    )
    return EVENTO_TITULO


async def evento_titulo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    titulo = update.message.text.strip()
    if not titulo:
        await update.message.reply_text("Escriu un titol valid.")
        return EVENTO_TITULO

    context.user_data["evento"]["titulo"] = titulo
    usuario_id = context.user_data["evento"]["usuario_id"]

    categorias = webapp.obtener_categorias_calendario(usuario_id)
    botones = [[InlineKeyboardButton(cat["nombre"], callback_data=f"catevento:{cat['id']}")] for cat in categorias]
    botones.append([InlineKeyboardButton("Sense categoria", callback_data="catevento:0")])

    await update.message.reply_text(
        "Quina categoria es? (pots triar 'Sense categoria')", reply_markup=InlineKeyboardMarkup(botones)
    )
    return EVENTO_CATEGORIA


async def evento_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria_id = int(query.data.split(":")[1])
    context.user_data["evento"]["categoria_id"] = categoria_id or None

    await query.edit_message_text("Quina data? (format AAAA-MM-DD, ex: 2026-08-15)")
    return EVENTO_FECHA


async def evento_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        date.fromisoformat(texto)
    except ValueError:
        await update.message.reply_text("Aquesta data no es valida. Fes servir el format AAAA-MM-DD, ex: 2026-08-15")
        return EVENTO_FECHA

    context.user_data["evento"]["fecha"] = texto

    botones = [[
        InlineKeyboardButton("Tot el dia", callback_data="horaevento:todoeldia"),
        InlineKeyboardButton("A una hora", callback_data="horaevento:hora"),
    ]]
    await update.message.reply_text("Tot el dia, o a una hora concreta?", reply_markup=InlineKeyboardMarkup(botones))
    return EVENTO_TIPO_HORA


async def evento_tipo_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    eleccion = query.data.split(":")[1]

    if eleccion == "hora":
        context.user_data["evento"]["todo_el_dia"] = False
        await query.edit_message_text("A quina hora? (format HH:MM, ex: 19:30)")
        return EVENTO_HORA

    context.user_data["evento"]["todo_el_dia"] = True
    context.user_data["evento"]["hora"] = None
    await query.edit_message_text(
        "Val, tot el dia.\n\nAmb quants dies d'antelacio vols l'avis?",
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
        await update.message.reply_text("Aquesta hora no es valida. Fes servir el format HH:MM, ex: 19:30")
        return EVENTO_HORA

    context.user_data["evento"]["hora"] = texto
    await update.message.reply_text(
        "Amb quants dies d'antelacio vols l'avis?",
        reply_markup=InlineKeyboardMarkup(_botones_recordatorio_evento()),
    )
    return EVENTO_RECORDATORIO


async def evento_recordatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dias = int(query.data.split(":")[1])
    context.user_data["evento"]["recordatorio_dias"] = dias

    botones = [
        [InlineKeyboardButton("No es repeteix", callback_data="repetirevento:ninguna")],
        [
            InlineKeyboardButton("Cada dia", callback_data="repetirevento:diaria"),
            InlineKeyboardButton("Cada setmana", callback_data="repetirevento:semanal"),
        ],
        [
            InlineKeyboardButton("Cada mes", callback_data="repetirevento:mensual"),
            InlineKeyboardButton("Cada any", callback_data="repetirevento:anual"),
        ],
    ]
    await query.edit_message_text("Es repeteix?", reply_markup=InlineKeyboardMarkup(botones))
    return EVENTO_REPETIR


async def evento_repetir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    repetir = query.data.split(":")[1]

    datos = context.user_data["evento"]
    datos["repetir"] = repetir

    # Els botons de categoria nomes ofereixen les del propi usuari (o
    # "Sense categoria"), pero comprovem igualment abans de desar, per si
    # el callback arriba manipulat.
    categoria_id = datos.get("categoria_id")
    if categoria_id and not webapp.categoria_calendario_del_usuario(categoria_id, datos["usuario_id"]):
        categoria_id = None

    conn = webapp.get_db_connection()
    cursor = conn.execute("""
        INSERT INTO calendario_eventos
            (usuario_id, titulo, categoria_id, fecha, hora, todo_el_dia, recordatorio_dias, repetir)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datos["usuario_id"], datos["titulo"], categoria_id, datos["fecha"],
        datos.get("hora"), 1 if datos["todo_el_dia"] else 0, datos["recordatorio_dias"], repetir,
    ))
    conn.commit()
    conn.close()

    # Ademas de la columna antigua (compatibilidad), lo dejamos tambien
    # registrado como su unico "umbral" en la tabla nueva, que es la que
    # de verdad consultan las vistas web y la revision de avisos. Si el
    # usuario quiere varios avisos para el mismo evento (ej. "7 dies
    # abans i tambe el mateix dia"), de momento nomes es pot afegir des
    # de la web (editar l'esdeveniment).
    webapp.guardar_umbrales_recordatorio(cursor.lastrowid, [datos["recordatorio_dias"]])

    resumen_hora = f" a les {datos['hora']}" if datos.get("hora") else " (tot el dia)"
    await query.edit_message_text(f"\u2705 '{datos['titulo']}' afegit el {datos['fecha']}{resumen_hora}.")
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
            "No tens cap registre amb dies de revalidacio configurats.\n"
            "Pots afegir-ho editant el registre des de la web, o en crear-lo amb /nuevacaducidad."
        )
        return

    botones = [
        [InlineKeyboardButton(f"{i['nombre']} ({i['dias_revalidacion']} dies)", callback_data=f"revalidar:{i['id']}")]
        for i in items
    ]
    await update.message.reply_text("Que vols revalidar?", reply_markup=InlineKeyboardMarkup(botones))


async def revalidar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    caducidad_id = int(query.data.split(":")[1])

    usuario = webapp.usuario_por_chat_id(update.effective_chat.id)
    item = webapp.caducidad_del_usuario(caducidad_id, usuario["id"]) if usuario else None
    if item is None or not item["dias_revalidacion"]:
        await query.edit_message_text("Aquest registre ja no es pot revalidar.")
        return

    nueva_fecha = date.today() + timedelta(days=item["dias_revalidacion"])
    conn = webapp.get_db_connection()
    conn.execute(
        "UPDATE caducidades SET fecha_caducidad = ?, aviso_proximo_enviado = 0, aviso_caducado_enviado = 0 WHERE id = ?",
        (nueva_fecha.isoformat(), caducidad_id),
    )
    conn.commit()
    conn.close()

    await query.edit_message_text(f"\u2705 '{item['nombre']}' revalidat. Nova data: {nueva_fecha.isoformat()}.")


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


def _avisos_evento_pendientes(item):
    """
    Devuelve una lista de (dias_antes, texto) con un elemento por cada
    umbral de aviso de este evento (puede tener varios, ej. "7 dies
    abans i tambe el mateix dia") que toca notificar ahora mismo: su
    ventana ya se ha cruzado y todavia no se aviso de ESTA ocurrencia
    concreta con ESE umbral en concreto. Comparar por
    (fecha_ocurrencia, dias_antes) es lo que hace que un evento
    recurrente vuelva a avisar en cada repeticion, con cada uno de sus
    avisos, sin repetir ninguno dos veces para la misma ocurrencia.
    """
    ya_enviados = webapp.avisos_ya_enviados(item["id"], item["fecha_ocurrencia"])
    pendientes = []

    for dias_antes in item["umbrales_recordatorio"]:
        if dias_antes in ya_enviados:
            continue

        if dias_antes == 0:
            if item["estado"] != "hoy":
                continue
            plantilla = random.choice(MENSAJES_AVISO_EVENTO_HOY)
        else:
            # Toca en cuanto se entra en su ventana (dias <= dias_antes),
            # pero no el mismo dia (eso ya lo cubre el umbral 0 de arriba).
            if not (0 < item["dias"] <= dias_antes):
                continue
            plantilla = random.choice(MENSAJES_AVISO_EVENTO_PROXIMO)

        texto = plantilla.format(
            titulo=item["titulo"],
            categoria=item["categoria_nombre"],
            texto_estado=item["texto_estado"][0].lower() + item["texto_estado"][1:],
        )
        pendientes.append((dias_antes, texto))

    return pendientes


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
            for dias_antes, texto in _avisos_evento_pendientes(item):
                try:
                    await context.bot.send_message(chat_id=usuario["telegram_chat_id"], text=texto)
                    webapp.marcar_aviso_evento_enviado(item["id"], item["fecha_ocurrencia"], dias_antes)
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
        for dias_antes, texto in _avisos_evento_pendientes(item):
            await update.message.reply_text(texto)
            webapp.marcar_aviso_evento_enviado(item["id"], item["fecha_ocurrencia"], dias_antes)
            enviados += 1

    if enviados == 0:
        await update.message.reply_text(
            "Ara mateix no hi ha cap avis pendent: o encara no et toca, o ja t'hem "
            "avisat de tot el que tocava. Fes servir /caducidades i /calendario per veure l'estat de tot."
        )


# =================================================================
# Mensajes que no coinciden con ningun comando ni conversacion activa
# =================================================================

async def mensaje_no_entendido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("No ho he entes. Escriu /ayuda per veure les ordres disponibles.")


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
