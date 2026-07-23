"""
Acceso a la base de datos SQLite y constantes compartidas por el resto
de la app (web y bot de Telegram).

Todos los demas modulos importan get_db_connection() de aqui para leer
y escribir en la base de datos.
"""

import sqlite3

from config import DATABASE_PATH

# Donde se guarda la base de datos. Se configura en .env (variable
# DATABASE_PATH); por defecto, junto a config.py.
DB_PATH = DATABASE_PATH

# Los tres tipos de operacion que existen en la seccion de finanzas.
TIPOS_OPERACION = ("gasto", "ingreso", "transferencia")

# Nombres de los meses en espanol, para el apartado de analisis.
NOMBRES_MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Categorias que se sugieren (pero no obligan) al crear una fecha de caducidad.
CATEGORIAS_CADUCIDAD_SUGERIDAS = [
    "Documentacion", "Vehiculo", "Hogar", "Salud", "Seguros", "Suscripciones", "Otros",
]

# Color del LED segun lo urgente que sea una fecha de caducidad.
COLOR_LED_POR_ESTADO = {"caducado": "rojo", "proximo": "amarillo", "vigente": "verde"}


def get_db_connection():
    """Abre una conexion a la base de datos SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Permite usar columnas por nombre, ej: usuario["username"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Crea todas las tablas si todavia no existen."""
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            telegram_chat_id INTEGER
        )
    """)

    # Migracion sencilla para bases de datos creadas antes de que existiera
    # la integracion con Telegram (mismo truco que con dias_revalidacion).
    try:
        conn.execute("ALTER TABLE usuarios ADD COLUMN telegram_chat_id INTEGER")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS codigos_telegram (
            codigo TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            expira TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cuentas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            saldo REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    # Migracion sencilla: cuentas de ahorro, que se muestran aparte y no
    # cuentan en el saldo total (mismo truco que con las demas columnas
    # nuevas: si ya existe, SQLite lanza un error que ignoramos).
    try:
        conn.execute("ALTER TABLE cuentas ADD COLUMN es_ahorro INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('gasto', 'ingreso')),
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS subcategorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            FOREIGN KEY (categoria_id) REFERENCES categorias (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS operaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('gasto', 'ingreso', 'transferencia')),
            cuenta_id INTEGER NOT NULL,
            cuenta_destino_id INTEGER,
            categoria_id INTEGER,
            subcategoria_id INTEGER,
            monto REAL NOT NULL,
            descripcion TEXT,
            fecha TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY (cuenta_id) REFERENCES cuentas (id),
            FOREIGN KEY (cuenta_destino_id) REFERENCES cuentas (id),
            FOREIGN KEY (categoria_id) REFERENCES categorias (id),
            FOREIGN KEY (subcategoria_id) REFERENCES subcategorias (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cuentas_predefinidas (
            usuario_id INTEGER NOT NULL,
            tipo_operacion TEXT NOT NULL CHECK (tipo_operacion IN ('gasto', 'ingreso', 'transferencia')),
            cuenta_id INTEGER NOT NULL,
            PRIMARY KEY (usuario_id, tipo_operacion),
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY (cuenta_id) REFERENCES cuentas (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS caducidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            categoria TEXT NOT NULL DEFAULT 'Otros',
            fecha_caducidad TEXT NOT NULL,
            aviso_dias INTEGER NOT NULL DEFAULT 30,
            dias_revalidacion INTEGER,
            notas TEXT,
            aviso_proximo_enviado INTEGER NOT NULL DEFAULT 0,
            aviso_caducado_enviado INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    # Migracion sencilla para bases de datos creadas antes de que existieran
    # los avisos por Telegram (mismo truco que con las demas columnas nuevas).
    for columna in ("aviso_proximo_enviado", "aviso_caducado_enviado"):
        try:
            conn.execute(f"ALTER TABLE caducidades ADD COLUMN {columna} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass

    # Migracion sencilla: si la base de datos ya existia de una version
    # anterior sin la columna "dias_revalidacion", se anade ahora sin
    # borrar ningun dato. Si la columna ya existe (bases de datos nuevas),
    # SQLite lanza un error que simplemente ignoramos.
    try:
        conn.execute("ALTER TABLE caducidades ADD COLUMN dias_revalidacion INTEGER")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS registros_caca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            fecha_hora TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    # Si el usuario marca su perfil como publico, otros usuarios registrados
    # pueden ver sus estadisticas (pero no al reves si el suyo es privado).
    try:
        conn.execute("ALTER TABLE usuarios ADD COLUMN perfil_publico INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()
