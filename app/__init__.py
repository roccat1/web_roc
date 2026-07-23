"""
Paquete de la app Flask.

Aqui se crea el objeto `app` de Flask y se registran, uno a uno, todos
los modulos que definen rutas (cada uno usa el decorador @app.route
al importarse). Dividir la app en estos modulos es solo una forma de
organizar el codigo: para Flask sigue siendo una unica aplicacion.

`bot.py` hace `import app as webapp` y usa cosas como
`webapp.get_db_connection` o `webapp.obtener_cuentas`: por eso, al
final de este archivo, se vuelven a importar esas funciones y
constantes aqui, para que sigan estando disponibles como
`webapp.lo_que_sea` sin tener que tocar bot.py.
"""

import os
from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (
    SECRET_KEY,
    SESSION_LIFETIME_DIAS,
    SESSION_COOKIE_SECURE,
    DETRAS_DE_PROXY,
)

# Carpeta raiz del proyecto (un nivel por encima de esta carpeta "app"),
# que es donde viven "templates/" y "static/". Se indica de forma
# explicita porque, al crear la app Flask desde dentro del paquete
# "app", Flask buscaria esas carpetas junto a este archivo por defecto.
_CARPETA_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(_CARPETA_RAIZ, "templates"),
    static_folder=os.path.join(_CARPETA_RAIZ, "static"),
)

# Esta clave se usa para proteger las sesiones (cookies). Se configura en
# el archivo .env (variable SECRET_KEY), no aqui.
app.secret_key = SECRET_KEY

# Si la web esta detras de un proxy que termina el HTTPS (ngrok, Nginx,
# Cloudflare Tunnel...), esto hace que Flask entienda que la conexion
# original era HTTPS aunque a el le llegue por HTTP desde el proxy.
# Se activa con DETRAS_DE_PROXY=True en el .env.
if DETRAS_DE_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Mantener la sesion iniciada durante varios dias en vez de que se
# cierre sola al cerrar el navegador (se activa marcando
# session.permanent = True al hacer login, en routes_auth.py).
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=SESSION_LIFETIME_DIAS)
app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

from .auth_utils import formatear_euros

app.template_filter("euros")(formatear_euros)

# Cada uno de estos modulos registra sus propias rutas en `app` al ser
# importado (por eso no hace falta usar lo que devuelven). El orden
# solo importa cuando un modulo usa funciones de otro (por ejemplo, el
# dashboard usa funciones de finanzas y de caducidades).
from . import routes_auth
from . import finanzas_helpers
from . import routes_dashboard
from . import finanzas_operaciones
from . import finanzas_categorias
from . import finanzas_cuentas
from . import finanzas_analisis
from . import caducidades_helpers
from . import caducidades_routes
from . import caca_helpers
from . import caca_routes
from . import telegram_helpers
from . import telegram_routes

# Re-exportamos aqui lo que bot.py necesita de "webapp.*".
from .db import get_db_connection, init_db, CATEGORIAS_CADUCIDAD_SUGERIDAS
from .finanzas_helpers import obtener_cuentas, obtener_categorias_con_subcategorias
from .caducidades_helpers import obtener_caducidades, caducidad_del_usuario, marcar_aviso_enviado
from .telegram_helpers import (
    usuario_por_chat_id,
    vincular_chat_con_codigo,
    desvincular_telegram,
)
