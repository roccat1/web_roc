"""
Configuracion centralizada de toda la app (la web en app.py y el bot en
bot.py). Todo lo que se pueda querer cambiar sin tocar codigo vive en el
archivo .env, en esta misma carpeta.

Este archivo lee ese .env y expone valores por defecto sensatos, para
que la app funcione nada mas descomprimirla, incluso si no tocas nada.
Si el .env no existe o le falta alguna variable, se usa el valor por
defecto de aqui.

Para personalizar algo: abre el archivo .env (no este archivo) y cambia
lo que necesites.
"""

import os
from datetime import time

from dotenv import load_dotenv

# Buscamos el .env siempre en la misma carpeta que este archivo, para que
# funcione igual sin importar desde donde se arranque la app (systemd,
# doble clic, terminal en otra carpeta...).
_CARPETA_BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_CARPETA_BASE, ".env"))


def _texto(nombre, por_defecto=""):
    valor = os.getenv(nombre)
    return valor if valor not in (None, "") else por_defecto


def _entero(nombre, por_defecto):
    valor = os.getenv(nombre)
    if valor in (None, ""):
        return por_defecto
    try:
        return int(valor)
    except ValueError:
        return por_defecto


def _booleano(nombre, por_defecto):
    valor = os.getenv(nombre)
    if valor in (None, ""):
        return por_defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


# =================================================================
# Flask (la web, app.py)
# =================================================================

SECRET_KEY = _texto("SECRET_KEY", "cambia-esta-clave-por-una-tuya")

# Si DATABASE_PATH es una ruta relativa (o esta vacia), se guarda junto a
# este archivo; si es una ruta absoluta (ej. /home/pi/datos/usuarios.db),
# se usa tal cual.
_database_path = _texto("DATABASE_PATH", "usuarios.db")
if os.path.isabs(_database_path):
    DATABASE_PATH = _database_path
else:
    DATABASE_PATH = os.path.join(_CARPETA_BASE, _database_path)

FLASK_HOST = _texto("FLASK_HOST", "0.0.0.0")
FLASK_PORT = _entero("FLASK_PORT", 5000)
FLASK_DEBUG = _booleano("FLASK_DEBUG", True)

# Cuantos dias se mantiene la sesion iniciada sin tener que volver a
# meter usuario y contrasena.
SESSION_LIFETIME_DIAS = _entero("SESSION_LIFETIME_DIAS", 30)

# Si SOLO entras a la web por HTTPS (por ejemplo a traves de ngrok, o de
# un dominio con certificado), pon esto en True para que la cookie de
# sesion vaya marcada como seguras. OJO: si tambien entras por HTTP en tu
# red local (ej. http://192.168.1.50:5000 desde el movil), dejalo en
# False, o el navegador se negara a guardar esa cookie por HTTP y no
# podras iniciar sesion.
SESSION_COOKIE_SECURE = _booleano("SESSION_COOKIE_SECURE", False)

# Si la web esta detras de un proxy que hace de intermediario y termina
# el HTTPS (ngrok, Nginx, Cloudflare Tunnel...), activa esto para que
# Flask sepa que la conexion original del navegador era HTTPS aunque a
# el le llegue por HTTP desde el proxy. Necesario para que
# SESSION_COOKIE_SECURE funcione bien detras de ngrok.
DETRAS_DE_PROXY = _booleano("DETRAS_DE_PROXY", False)

# =================================================================
# Bot de Telegram (bot.py)
# =================================================================

TELEGRAM_BOT_TOKEN = _texto("TELEGRAM_BOT_TOKEN", "")

# Zona horaria para el aviso diario de caducidades. Lista de nombres
# validos: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
TELEGRAM_TIMEZONE_NOMBRE = _texto("TELEGRAM_TIMEZONE", "Europe/Madrid")

try:
    from zoneinfo import ZoneInfo
    TELEGRAM_TIMEZONE = ZoneInfo(TELEGRAM_TIMEZONE_NOMBRE)
except Exception:
    TELEGRAM_TIMEZONE = None
    print(
        f'Aviso: no se pudo cargar la zona horaria "{TELEGRAM_TIMEZONE_NOMBRE}" (en Windows '
        "puede hacer falta instalar el paquete tzdata: pip install tzdata). Los avisos "
        "automaticos se programaran en UTC en vez de en tu hora local."
    )

# A que hora del dia se revisan las caducidades, formato "HH:MM".
_aviso_hora_texto = _texto("TELEGRAM_AVISO_HORA", "09:00")
try:
    _horas, _minutos = _aviso_hora_texto.split(":")
    TELEGRAM_AVISO_HORA = time(hour=int(_horas), minute=int(_minutos), tzinfo=TELEGRAM_TIMEZONE)
except (ValueError, AttributeError):
    print(f'Aviso: TELEGRAM_AVISO_HORA="{_aviso_hora_texto}" no es valido, usando 09:00 en su lugar.')
    TELEGRAM_AVISO_HORA = time(hour=9, minute=0, tzinfo=TELEGRAM_TIMEZONE)
