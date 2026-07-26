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

# Nombres de los meses en catalan, para el apartado de analisis.
NOMBRES_MESES = [
    "Gener", "Febrer", "Marc", "Abril", "Maig", "Juny",
    "Juliol", "Agost", "Setembre", "Octubre", "Novembre", "Desembre",
]

# Categorias que se sugieren (pero no obligan) al crear una fecha de caducidad.
CATEGORIAS_CADUCIDAD_SUGERIDAS = [
    "Documentacio", "Vehicle", "Llar", "Salut", "Assegurances", "Subscripcions", "Altres",
]

# Color del LED segun lo urgente que sea una fecha de caducidad.
COLOR_LED_POR_ESTADO = {"caducado": "rojo", "proximo": "amarillo", "vigente": "verde"}

# Categorias que se sugieren (pero no obligan) al crear una categoria del calendario.
CATEGORIAS_CALENDARIO_SUGERIDAS = [
    "Personal", "Feina", "Salut", "Familia", "Oci", "Aniversaris", "Viatges", "Altres",
]

# Colores disponibles para las categorias del calendario. Se guarda solo la
# clave en la base de datos; el color real (variable CSS) lo define
# style.css con clases ".cat-<clave>", igual que se hace con los LED.
COLORES_CALENDARIO = ("rojo", "amarillo", "verde", "azul", "morado", "cian", "rosa", "gris")

# Con que frecuencia puede repetirse un evento del calendario.
OPCIONES_REPETICION_CALENDARIO = ("ninguna", "diaria", "semanal", "mensual", "anual")

# Color del LED segun lo cerca que este un evento del calendario.
COLOR_LED_POR_ESTADO_EVENTO = {"pasado": "gris", "hoy": "rojo", "proximo": "amarillo", "futuro": "verde"}


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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT 'azul',
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            categoria_id INTEGER,
            fecha TEXT NOT NULL,
            hora TEXT,
            todo_el_dia INTEGER NOT NULL DEFAULT 1,
            lugar TEXT,
            descripcion TEXT,
            recordatorio_dias INTEGER NOT NULL DEFAULT 0,
            repetir TEXT NOT NULL DEFAULT 'ninguna'
                CHECK (repetir IN ('ninguna', 'diaria', 'semanal', 'mensual', 'anual')),
            repetir_hasta TEXT,
            aviso_enviado_fecha TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY (categoria_id) REFERENCES calendario_categorias (id)
        )
    """)

    # Categories addicionals d'un esdeveniment (a mes de la principal, que
    # es la que es guarda a calendario_eventos.categoria_id i decideix el
    # color del punt al mes). Es una relacio N a N: un esdeveniment pot
    # tenir diverses etiquetes, i una categoria es pot fer servir com a
    # etiqueta addicional en molts esdeveniments.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_evento_categorias (
            evento_id INTEGER NOT NULL,
            categoria_id INTEGER NOT NULL,
            PRIMARY KEY (evento_id, categoria_id),
            FOREIGN KEY (evento_id) REFERENCES calendario_eventos (id),
            FOREIGN KEY (categoria_id) REFERENCES calendario_categorias (id)
        )
    """)

    # Uno o varios avisos por evento (ej. "avisa 7 dies abans i tambe el
    # mateix dia"). Sustituye en la practica a la columna suelta
    # calendario_eventos.recordatorio_dias, que se mantiene solo por
    # compatibilidad con bases de datos antiguas: si un evento no tiene
    # ninguna fila aqui, el codigo usa esa columna como unico aviso.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_recordatorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id INTEGER NOT NULL,
            dias_antes INTEGER NOT NULL,
            UNIQUE (evento_id, dias_antes),
            FOREIGN KEY (evento_id) REFERENCES calendario_eventos (id)
        )
    """)

    # Registro de que avisos ya se han enviado, por evento + ocurrencia +
    # umbral concreto (en vez de la unica columna aviso_enviado_fecha),
    # para poder tener varios avisos por evento sin repetirlos.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_avisos_enviados (
            evento_id INTEGER NOT NULL,
            fecha_ocurrencia TEXT NOT NULL,
            dias_antes INTEGER NOT NULL,
            PRIMARY KEY (evento_id, fecha_ocurrencia, dias_antes),
            FOREIGN KEY (evento_id) REFERENCES calendario_eventos (id)
        )
    """)

    # Excepciones puntuals d'un esdeveniment recurrent: cancel·lar nomes
    # una ocurrencia concreta, o canviar-ne el titol/hora/lloc/descripcio
    # nomes per a aquella data, sense afectar a la resta de la serie.
    # (Nomes es guarda la data original de l'ocurrencia; no permet moure
    # una ocurrencia a un dia diferent, nomes editar-la o cancelar-la.)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_excepciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id INTEGER NOT NULL,
            fecha_ocurrencia TEXT NOT NULL,
            cancelada INTEGER NOT NULL DEFAULT 0,
            titulo TEXT,
            hora TEXT,
            todo_el_dia INTEGER,
            lugar TEXT,
            descripcion TEXT,
            UNIQUE (evento_id, fecha_ocurrencia),
            FOREIGN KEY (evento_id) REFERENCES calendario_eventos (id)
        )
    """)

    # Indices: sin ellos, cada vista del calendario recorre entera la
    # tabla de eventos aunque solo haga falta un usuario o un rango de
    # fechas. Con pocos eventos no se nota, pero no cuesta nada tenerlos.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_calendario_eventos_usuario ON calendario_eventos (usuario_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_calendario_eventos_fecha ON calendario_eventos (fecha)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_calendario_excepciones_evento ON calendario_excepciones (evento_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_calendario_recordatorios_evento ON calendario_recordatorios (evento_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_caducidades_usuario ON caducidades (usuario_id)")

    conn.commit()
    conn.close()
