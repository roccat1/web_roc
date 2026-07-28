"""
CALENDARIO - sincronizacion con Google Calendar.

Idea general: cada calendario de Google que el usuario decide
sincronizar se corresponde con una categoria del calendario de la app
(se crea sola, con el mismo nombre, la primera vez que se marca). A
partir de ahi:

- "Bajar" (Google -> app): se leen los eventos de cada calendario de
  Google vinculado y se guardan/actualizan como eventos locales con esa
  categoria. Los eventos recurrentes usan el mismo sistema de
  repeticion + excepciones que ya tiene la app (ver calendario_helpers.py).
- "Subir" (app -> Google): cuando se crea, edita o elimina un evento
  cuya categoria esta vinculada a un calendario de Google, se refleja
  alla (crear/actualizar/eliminar el evento correspondiente).

Todo esto se hace en segundo plano, cada GOOGLE_SYNC_INTERVALO_MINUTOS
(ver app/__init__.py), ademas de intentarse al momento cuando se guarda
algo desde la web (ver los "push_*" que llama calendario_routes.py).
Los fallos (sin conexion, token caducado...) nunca rompen la web: se
marcan como pendientes y se reintentan en el siguiente ciclo.

Tambien se sincroniza "restaurar" una ocurrencia (deshacer una
cancelacion o edicion puntual, ver eliminar_excepcion en
calendario_helpers.py): se intenta devolver esa instancia en Google al
estado normal de la serie. Esto es lo unico algo menos fiable al 100%,
porque depende de que Google acepte "revivir" una instancia que el
mismo habia marcado como cancelada; si no lo acepta, se registra el
aviso en la consola y la ocurrencia se queda restaurada solo en la app
(nada se rompe, simplemente no queda reflejado en Google).
"""

from datetime import date, datetime, timedelta, timezone

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, TELEGRAM_TIMEZONE_NOMBRE
from .db import get_db_connection, COLORES_CALENDARIO
from .calendario_helpers import (
    excepcion_de_ocurrencia,
    guardar_excepcion_cancelada,
    guardar_excepcion_editada,
)

# Con este permiso se puede leer y escribir en todos los calendarios a
# los que el usuario nos de acceso (no solo en el suyo principal).
SCOPES = ["https://www.googleapis.com/auth/calendar"]

_FREQ_A_REPETIR = {"DAILY": "diaria", "WEEKLY": "semanal", "MONTHLY": "mensual", "YEARLY": "anual"}
_REPETIR_A_FREQ = {valor: clave for clave, valor in _FREQ_A_REPETIR.items()}

# Roles de acceso de Google Calendar que solo permiten leer: si un
# calendario tiene uno de estos, no se intenta escribir en el (fallaria).
_ROLES_SOLO_LECTURA = ("reader", "freeBusyReader")


def _servicio_calendar(credenciales):
    return build("calendar", "v3", credentials=credenciales, cache_discovery=False)


# =================================================================
# OAuth: conectar, refrescar y desconectar la cuenta
# =================================================================

def construir_flow(redirect_uri, estado=None):
    """Crea el objeto Flow de google-auth-oauthlib con las credenciales
    del proyecto (del .env) y la URL de vuelta que se use en cada caso
    (se calcula a partir de la request para no depender de una URL fija,
    ya que puede cambiar si usas ngrok sin dominio fijo)."""
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=SCOPES,
        state=estado,
        redirect_uri=redirect_uri,
    )


def guardar_credenciales(usuario_id, credenciales):
    """Guarda (o actualiza) el token de un usuario tras conectar su
    cuenta. Si Google no devuelve un refresh_token nuevo (pasa si el
    usuario ya habia dado permiso antes), se conserva el que ya
    teniamos guardado."""
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO calendario_google_cuentas (usuario_id, refresh_token, access_token, token_expira, conectado_en)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (usuario_id) DO UPDATE SET
            refresh_token = COALESCE(excluded.refresh_token, calendario_google_cuentas.refresh_token),
            access_token = excluded.access_token,
            token_expira = excluded.token_expira
    """, (
        usuario_id, credenciales.refresh_token, credenciales.token,
        credenciales.expiry.isoformat() if credenciales.expiry else None,
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def _actualizar_access_token(usuario_id, credenciales):
    conn = get_db_connection()
    conn.execute(
        "UPDATE calendario_google_cuentas SET access_token = ?, token_expira = ? WHERE usuario_id = ?",
        (credenciales.token, credenciales.expiry.isoformat() if credenciales.expiry else None, usuario_id),
    )
    conn.commit()
    conn.close()


def obtener_credenciales(usuario_id):
    """Devuelve unas credenciales validas para llamar a la API en
    nombre de este usuario (refrescando el access_token si hace falta),
    o None si no tiene cuenta conectada o el token ya no sirve (por
    ejemplo, si revoco el acceso desde su cuenta de Google)."""
    conn = get_db_connection()
    fila = conn.execute("SELECT * FROM calendario_google_cuentas WHERE usuario_id = ?", (usuario_id,)).fetchone()
    conn.close()
    if fila is None:
        return None

    credenciales = Credentials(
        token=fila["access_token"],
        refresh_token=fila["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    if not credenciales.valid:
        try:
            credenciales.refresh(GoogleAuthRequest())
            _actualizar_access_token(usuario_id, credenciales)
        except Exception as error:
            print(f"[google-sync] No se pudo refrescar el token del usuario {usuario_id}: {error}")
            return None
    return credenciales


def cuenta_conectada(usuario_id):
    conn = get_db_connection()
    fila = conn.execute(
        "SELECT usuario_id FROM calendario_google_cuentas WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()
    conn.close()
    return fila is not None


def desconectar(usuario_id):
    """Revoca el token (best effort) y olvida la cuenta y los
    calendarios vinculados. Los eventos ya importados NO se borran:
    simplemente dejan de estar enlazados con Google (se quedan como
    eventos locales normales, con la categoria que ya tenian)."""
    credenciales = obtener_credenciales(usuario_id)
    if credenciales is not None and credenciales.token:
        try:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": credenciales.token},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=5,
            )
        except Exception as error:
            print(f"[google-sync] No se pudo revocar el token del usuario {usuario_id}: {error}")

    conn = get_db_connection()
    filas_calendarios = conn.execute(
        "SELECT id FROM calendario_google_calendarios WHERE usuario_id = ?", (usuario_id,)
    ).fetchall()
    ids_calendarios = [f["id"] for f in filas_calendarios]
    if ids_calendarios:
        marcadores = ",".join("?" * len(ids_calendarios))
        conn.execute(
            f"UPDATE calendario_eventos SET google_calendario_id = NULL, google_event_id = NULL, "
            f"google_actualizado = NULL, pendiente_subir = 0 WHERE google_calendario_id IN ({marcadores})",
            ids_calendarios,
        )
    conn.execute("DELETE FROM calendario_google_calendarios WHERE usuario_id = ?", (usuario_id,))
    conn.execute("DELETE FROM calendario_google_cuentas WHERE usuario_id = ?", (usuario_id,))
    conn.execute("DELETE FROM calendario_google_eliminaciones_pendientes WHERE usuario_id = ?", (usuario_id,))
    conn.commit()
    conn.close()


# =================================================================
# Elegir que calendarios de Google sincronizar
# =================================================================

def listar_calendarios_google(usuario_id):
    """Devuelve la lista de calendarios de Google del usuario (los
    suyos y los que le hayan compartido), o None si no se ha podido
    contactar con la API (sin conexion, cuenta no conectada...)."""
    credenciales = obtener_credenciales(usuario_id)
    if credenciales is None:
        return None

    try:
        servicio = _servicio_calendar(credenciales)
        calendarios = []
        pagina = None
        while True:
            respuesta = servicio.calendarList().list(pageToken=pagina).execute()
            for item in respuesta.get("items", []):
                calendarios.append({
                    "id": item["id"],
                    "nombre": item.get("summaryOverride") or item.get("summary") or item["id"],
                    "primario": item.get("primary", False),
                    "acceso": item.get("accessRole"),
                })
            pagina = respuesta.get("nextPageToken")
            if not pagina:
                break
        return calendarios
    except HttpError as error:
        print(f"[google-sync] No se pudieron listar los calendarios del usuario {usuario_id}: {error}")
        return None
    except Exception as error:
        print(f"[google-sync] No se pudieron listar los calendarios del usuario {usuario_id}: {error}")
        return None


def obtener_calendarios_vinculados(usuario_id):
    """Los calendarios de Google que el usuario ya ha elegido (esten
    activos o en pausa), con el nombre y color de la categoria que
    tienen asociada, para pintarlos en las plantillas."""
    conn = get_db_connection()
    filas = conn.execute("""
        SELECT calendario_google_calendarios.*, calendario_categorias.nombre AS categoria_nombre,
               calendario_categorias.color AS categoria_color
        FROM calendario_google_calendarios
        LEFT JOIN calendario_categorias ON calendario_categorias.id = calendario_google_calendarios.categoria_id
        WHERE calendario_google_calendarios.usuario_id = ?
        ORDER BY calendario_google_calendarios.nombre COLLATE NOCASE
    """, (usuario_id,)).fetchall()
    conn.close()
    return filas


def guardar_seleccion_calendarios(usuario_id, ids_marcados):
    """Aplica lo que el usuario ha marcado en la pagina de seleccion:
    - Un calendario marcado por primera vez crea una categoria nueva
      (con su mismo nombre) y queda vinculado y activo.
    - Un calendario ya vinculado que se vuelve a marcar, sigue igual.
    - Un calendario ya vinculado que se desmarca se pone en pausa
      (sync_activo = 0): no se borra ni el ni sus eventos ya importados,
      simplemente deja de sincronizarse hasta que se vuelva a marcar.
    Devuelve False si no se ha podido contactar con Google (y por tanto
    no se ha guardado nada), True si ha ido bien."""
    calendarios_google = listar_calendarios_google(usuario_id)
    if calendarios_google is None:
        return False

    conn = get_db_connection()
    vinculados = {
        f["google_calendar_id"]: f
        for f in conn.execute(
            "SELECT * FROM calendario_google_calendarios WHERE usuario_id = ?", (usuario_id,)
        ).fetchall()
    }

    for indice, calendario in enumerate(calendarios_google):
        marcado = calendario["id"] in ids_marcados
        existente = vinculados.get(calendario["id"])

        if existente is not None:
            conn.execute(
                "UPDATE calendario_google_calendarios SET sync_activo = ?, nombre = ?, rol_acceso = ? WHERE id = ?",
                (1 if marcado else 0, calendario["nombre"], calendario["acceso"], existente["id"]),
            )
            continue

        if not marcado:
            continue

        color = COLORES_CALENDARIO[indice % len(COLORES_CALENDARIO)]
        cursor = conn.execute(
            "INSERT INTO calendario_categorias (usuario_id, nombre, color) VALUES (?, ?, ?)",
            (usuario_id, calendario["nombre"], color),
        )
        categoria_id = cursor.lastrowid
        conn.execute("""
            INSERT INTO calendario_google_calendarios
                (usuario_id, google_calendar_id, nombre, categoria_id, sync_activo, rol_acceso)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (usuario_id, calendario["id"], calendario["nombre"], categoria_id, calendario["acceso"]))

    conn.commit()
    conn.close()
    return True


# =================================================================
# Convertir entre el formato de un evento de la app y el de Google
# =================================================================

def _fecha_hora_desde_google(punto_temporal):
    """'punto_temporal' es el dict 'start'/'end'/'originalStartTime' de
    un evento de Google. Devuelve (fecha_iso, hora_texto_o_None)."""
    if "date" in punto_temporal:
        return punto_temporal["date"], None
    valor = punto_temporal["dateTime"]
    fecha_parte, hora_parte = valor.split("T", 1)
    return fecha_parte, hora_parte[0:5]


def _analizar_recurrencia(lineas_recurrence):
    """A partir de las lineas 'recurrence' de un evento de Google,
    intenta sacar (repetir, repetir_hasta) en el formato de la app. Si
    la regla es mas compleja de lo que soportamos (INTERVAL, COUNT,
    BYDAY...), se devuelve ('ninguna', None) y se importa como un
    evento unico en su fecha de inicio (igual que hace ya el
    importador de ficheros .ics de calendario_helpers.py)."""
    for linea in lineas_recurrence or []:
        if not linea.startswith("RRULE:"):
            continue
        partes = dict(p.split("=", 1) for p in linea[len("RRULE:"):].split(";") if "=" in p)
        freq = partes.get("FREQ")
        if freq not in _FREQ_A_REPETIR or "INTERVAL" in partes or "COUNT" in partes or "BYDAY" in partes:
            return "ninguna", None
        repetir_hasta = None
        if "UNTIL" in partes:
            valor = partes["UNTIL"]
            repetir_hasta = f"{valor[0:4]}-{valor[4:6]}-{valor[6:8]}"
        return _FREQ_A_REPETIR[freq], repetir_hasta
    return "ninguna", None


def _construir_cuerpo_evento_google(fila_evento):
    """A partir de una fila (o dict con las mismas claves) de
    calendario_eventos, construye el cuerpo JSON que espera la Google
    Calendar API para crear/actualizar un evento."""
    cuerpo = {
        "summary": fila_evento["titulo"],
        "location": fila_evento["lugar"] or None,
        "description": fila_evento["descripcion"] or None,
    }

    fecha = fila_evento["fecha"]
    if fila_evento["todo_el_dia"] or not fila_evento["hora"]:
        dia_siguiente = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()
        cuerpo["start"] = {"date": fecha}
        cuerpo["end"] = {"date": dia_siguiente}
    else:
        # Si por lo que sea no hay hora de fin guardada (eventos creados
        # antes de que existiera este campo), se asume 1 hora de
        # duracion como ultimo recurso.
        inicio_dt = datetime.fromisoformat(f"{fecha}T{fila_evento['hora']}:00")
        if fila_evento["hora_fin"]:
            fin_dt = datetime.fromisoformat(f"{fecha}T{fila_evento['hora_fin']}:00")
        else:
            fin_dt = inicio_dt + timedelta(hours=1)
        cuerpo["start"] = {"dateTime": inicio_dt.isoformat(), "timeZone": TELEGRAM_TIMEZONE_NOMBRE}
        cuerpo["end"] = {"dateTime": fin_dt.isoformat(), "timeZone": TELEGRAM_TIMEZONE_NOMBRE}

    if fila_evento["repetir"] != "ninguna":
        rrule = f"RRULE:FREQ={_REPETIR_A_FREQ[fila_evento['repetir']]}"
        if fila_evento["repetir_hasta"]:
            rrule += f";UNTIL={fila_evento['repetir_hasta'].replace('-', '')}T235959Z"
        cuerpo["recurrence"] = [rrule]

    return cuerpo


# =================================================================
# Bajar cambios: Google -> app
# =================================================================

def _borrar_evento_local(conn, evento_id):
    conn.execute("DELETE FROM calendario_evento_categorias WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_recordatorios WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_avisos_enviados WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_excepciones WHERE evento_id = ?", (evento_id,))
    conn.execute("DELETE FROM calendario_eventos WHERE id = ?", (evento_id,))


def _aplicar_evento_google(conn, usuario_id, calendario_row, evento_google):
    google_event_id = evento_google["id"]
    recurring_event_id = evento_google.get("recurringEventId")

    if recurring_event_id:
        # Es una ocurrencia concreta (cancelada o editada solo para
        # ella) de una serie recurrente, no un evento independiente.
        maestro = conn.execute(
            "SELECT id FROM calendario_eventos WHERE usuario_id = ? AND google_event_id = ?",
            (usuario_id, recurring_event_id),
        ).fetchone()
        if maestro is None:
            return  # aun no hemos importado la serie principal; se resolvera en el siguiente ciclo

        fecha_ocurrencia, _ = _fecha_hora_desde_google(evento_google["originalStartTime"])
        if evento_google.get("status") == "cancelled":
            guardar_excepcion_cancelada(maestro["id"], fecha_ocurrencia)
        else:
            fecha, hora = _fecha_hora_desde_google(evento_google["start"])
            _, hora_fin = _fecha_hora_desde_google(evento_google["end"]) if "end" in evento_google else (None, None)
            todo_el_dia = 1 if hora is None else 0
            guardar_excepcion_editada(
                maestro["id"], fecha_ocurrencia, evento_google.get("summary", "Sense titol"),
                hora, hora_fin, todo_el_dia, evento_google.get("location"), evento_google.get("description"),
            )
        return

    evento_local = conn.execute(
        "SELECT id, pendiente_subir FROM calendario_eventos WHERE usuario_id = ? AND google_event_id = ?",
        (usuario_id, google_event_id),
    ).fetchone()

    if evento_google.get("status") == "cancelled":
        if evento_local is not None:
            _borrar_evento_local(conn, evento_local["id"])
        return

    if evento_local is not None and evento_local["pendiente_subir"]:
        # Hay un cambio local que aun no se ha podido subir: no lo
        # pisamos con lo que venga de Google, se resolvera cuando se
        # suba (en el siguiente ciclo, o en el que toque despues).
        return

    fecha, hora = _fecha_hora_desde_google(evento_google["start"])
    _, hora_fin = _fecha_hora_desde_google(evento_google["end"]) if "end" in evento_google else (None, None)
    todo_el_dia = 1 if hora is None else 0
    titulo = evento_google.get("summary") or "Sense titol"
    lugar = evento_google.get("location")
    descripcion = evento_google.get("description")
    repetir, repetir_hasta = _analizar_recurrencia(evento_google.get("recurrence"))
    actualizado = evento_google.get("updated")

    if evento_local is None:
        conn.execute("""
            INSERT INTO calendario_eventos
                (usuario_id, titulo, categoria_id, fecha, hora, hora_fin, todo_el_dia, lugar, descripcion,
                 recordatorio_dias, repetir, repetir_hasta, google_calendario_id, google_event_id,
                 google_actualizado, pendiente_subir)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 0)
        """, (
            usuario_id, titulo, calendario_row["categoria_id"], fecha, hora, hora_fin, todo_el_dia,
            lugar, descripcion, repetir, repetir_hasta, calendario_row["id"], google_event_id, actualizado,
        ))
    else:
        conn.execute("""
            UPDATE calendario_eventos
            SET titulo = ?, fecha = ?, hora = ?, hora_fin = ?, todo_el_dia = ?, lugar = ?, descripcion = ?,
                repetir = ?, repetir_hasta = ?, google_actualizado = ?
            WHERE id = ?
        """, (
            titulo, fecha, hora, hora_fin, todo_el_dia, lugar, descripcion,
            repetir, repetir_hasta, actualizado, evento_local["id"],
        ))


def _guardar_sync_token(calendario_row_id, sync_token):
    conn = get_db_connection()
    conn.execute(
        "UPDATE calendario_google_calendarios SET sync_token = ?, ultima_sincronizacion = ? WHERE id = ?",
        (sync_token, datetime.now(timezone.utc).isoformat(), calendario_row_id),
    )
    conn.commit()
    conn.close()


def sincronizar_calendario(usuario_id, calendario_row):
    """Trae los cambios de un calendario de Google concreto y los
    aplica localmente. Usa un 'sync token' para traer solo lo que ha
    cambiado desde la ultima vez; si ese token ya ha caducado (Google
    devuelve un error 410), se olvida y se hace un rastreo completo
    (acotado a +/- un par de anios) la proxima vez."""
    credenciales = obtener_credenciales(usuario_id)
    if credenciales is None:
        return

    servicio = _servicio_calendar(credenciales)
    google_calendar_id = calendario_row["google_calendar_id"]
    sync_token = calendario_row["sync_token"]

    parametros = {"calendarId": google_calendar_id, "singleEvents": False, "showDeleted": True}
    if sync_token:
        parametros["syncToken"] = sync_token
    else:
        ahora = datetime.now(timezone.utc)
        parametros["timeMin"] = (ahora - timedelta(days=90)).isoformat()
        parametros["timeMax"] = (ahora + timedelta(days=730)).isoformat()

    eventos_google = []
    pagina = None
    nuevo_sync_token = sync_token
    try:
        while True:
            if pagina:
                parametros["pageToken"] = pagina
            respuesta = servicio.events().list(**parametros).execute()
            eventos_google.extend(respuesta.get("items", []))
            pagina = respuesta.get("nextPageToken")
            if not pagina:
                nuevo_sync_token = respuesta.get("nextSyncToken", nuevo_sync_token)
                break
    except HttpError as error:
        if error.resp.status == 410:
            _guardar_sync_token(calendario_row["id"], None)
            return
        print(f"[google-sync] Error listando eventos de '{calendario_row['nombre']}': {error}")
        return
    except Exception as error:
        print(f"[google-sync] Error listando eventos de '{calendario_row['nombre']}': {error}")
        return

    conn = get_db_connection()
    for evento_google in eventos_google:
        _aplicar_evento_google(conn, usuario_id, calendario_row, evento_google)
    conn.commit()
    conn.close()

    _guardar_sync_token(calendario_row["id"], nuevo_sync_token)


# =================================================================
# Subir cambios: app -> Google
# =================================================================

def eliminar_evento_remoto(usuario_id, calendario_row_id, google_event_id):
    """Borra en Google el evento correspondiente a uno local. Si no se
    puede ahora mismo (sin conexion, token caducado...), lo apunta como
    pendiente para reintentarlo en el siguiente ciclo."""
    if not calendario_row_id or not google_event_id:
        return

    conn = get_db_connection()
    fila_calendario = conn.execute(
        "SELECT google_calendar_id FROM calendario_google_calendarios WHERE id = ?", (calendario_row_id,)
    ).fetchone()
    conn.close()
    if fila_calendario is None:
        return

    credenciales = obtener_credenciales(usuario_id)
    if credenciales is None:
        _registrar_eliminacion_pendiente(usuario_id, fila_calendario["google_calendar_id"], google_event_id)
        return

    try:
        servicio = _servicio_calendar(credenciales)
        servicio.events().delete(
            calendarId=fila_calendario["google_calendar_id"], eventId=google_event_id
        ).execute()
    except HttpError as error:
        if error.resp.status not in (404, 410):
            _registrar_eliminacion_pendiente(usuario_id, fila_calendario["google_calendar_id"], google_event_id)
        # 404/410: ya no existia en Google, no hace falta reintentar nada.
    except Exception as error:
        print(f"[google-sync] No se pudo eliminar el evento {google_event_id} en Google: {error}")
        _registrar_eliminacion_pendiente(usuario_id, fila_calendario["google_calendar_id"], google_event_id)


def _registrar_eliminacion_pendiente(usuario_id, google_calendar_id, google_event_id):
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO calendario_google_eliminaciones_pendientes
            (usuario_id, google_calendar_id, google_event_id, creado)
        VALUES (?, ?, ?, ?)
    """, (usuario_id, google_calendar_id, google_event_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def _reintentar_eliminaciones_pendientes(usuario_id):
    conn = get_db_connection()
    pendientes = conn.execute(
        "SELECT * FROM calendario_google_eliminaciones_pendientes WHERE usuario_id = ?", (usuario_id,)
    ).fetchall()
    conn.close()
    if not pendientes:
        return

    credenciales = obtener_credenciales(usuario_id)
    if credenciales is None:
        return
    servicio = _servicio_calendar(credenciales)

    for pendiente in pendientes:
        try:
            servicio.events().delete(
                calendarId=pendiente["google_calendar_id"], eventId=pendiente["google_event_id"]
            ).execute()
        except HttpError as error:
            if error.resp.status not in (404, 410):
                continue  # sigue sin poderse borrar: se reintenta en el siguiente ciclo
        except Exception as error:
            print(f"[google-sync] No se pudo eliminar el evento {pendiente['google_event_id']} en Google: {error}")
            continue
        conn = get_db_connection()
        conn.execute("DELETE FROM calendario_google_eliminaciones_pendientes WHERE id = ?", (pendiente["id"],))
        conn.commit()
        conn.close()


def push_evento(evento_id):
    """Refleja en Google el estado actual de un evento local: lo crea
    si es nuevo, lo actualiza si ya existia, lo mueve de calendario si
    ha cambiado de categoria, o lo elimina de Google si su categoria ya
    no esta vinculada a ningun calendario. Nunca lanza una excepcion
    hacia quien la llama: si algo falla, deja el evento marcado como
    'pendiente_subir' para que el ciclo periodico lo reintente."""
    conn = get_db_connection()
    fila = conn.execute("SELECT * FROM calendario_eventos WHERE id = ?", (evento_id,)).fetchone()
    if fila is None:
        conn.close()
        return

    calendario_vinculado = None
    if fila["categoria_id"] is not None:
        calendario_vinculado = conn.execute(
            "SELECT * FROM calendario_google_calendarios "
            "WHERE usuario_id = ? AND categoria_id = ? AND sync_activo = 1",
            (fila["usuario_id"], fila["categoria_id"]),
        ).fetchone()

    if calendario_vinculado is None:
        # La categoria de este evento ya no esta vinculada a Google (o
        # nunca lo estuvo). Si antes si lo estaba, se elimina de alla.
        if fila["google_event_id"]:
            usuario_id, calendario_id_anterior, google_event_id = (
                fila["usuario_id"], fila["google_calendario_id"], fila["google_event_id"]
            )
            conn.execute(
                "UPDATE calendario_eventos SET google_calendario_id = NULL, google_event_id = NULL, "
                "google_actualizado = NULL, pendiente_subir = 0 WHERE id = ?",
                (evento_id,),
            )
            conn.commit()
            conn.close()
            eliminar_evento_remoto(usuario_id, calendario_id_anterior, google_event_id)
            return
        conn.close()
        return

    if calendario_vinculado["rol_acceso"] in _ROLES_SOLO_LECTURA:
        conn.close()
        return  # calendario de solo lectura: no se puede escribir en Google

    credenciales = obtener_credenciales(fila["usuario_id"])
    if credenciales is None:
        conn.execute("UPDATE calendario_eventos SET pendiente_subir = 1 WHERE id = ?", (evento_id,))
        conn.commit()
        conn.close()
        return

    cuerpo = _construir_cuerpo_evento_google(fila)
    cambia_de_calendario = fila["google_event_id"] and fila["google_calendario_id"] != calendario_vinculado["id"]

    try:
        servicio = _servicio_calendar(credenciales)
        if fila["google_event_id"] and not cambia_de_calendario:
            respuesta = servicio.events().update(
                calendarId=calendario_vinculado["google_calendar_id"], eventId=fila["google_event_id"], body=cuerpo
            ).execute()
        else:
            if cambia_de_calendario:
                eliminar_evento_remoto(fila["usuario_id"], fila["google_calendario_id"], fila["google_event_id"])
            respuesta = servicio.events().insert(
                calendarId=calendario_vinculado["google_calendar_id"], body=cuerpo
            ).execute()

        conn.execute("""
            UPDATE calendario_eventos
            SET google_calendario_id = ?, google_event_id = ?, google_actualizado = ?, pendiente_subir = 0
            WHERE id = ?
        """, (calendario_vinculado["id"], respuesta["id"], respuesta.get("updated"), evento_id))
        conn.commit()
    except HttpError as error:
        print(f"[google-sync] No se pudo subir el evento {evento_id} a Google: {error}")
        conn.execute("UPDATE calendario_eventos SET pendiente_subir = 1 WHERE id = ?", (evento_id,))
        conn.commit()
    except Exception as error:
        print(f"[google-sync] No se pudo subir el evento {evento_id} a Google: {error}")
        conn.execute("UPDATE calendario_eventos SET pendiente_subir = 1 WHERE id = ?", (evento_id,))
        conn.commit()
    finally:
        conn.close()


def _buscar_instancia_google(servicio, google_calendar_id, google_event_id, fecha_ocurrencia):
    """De entre las instancias de un evento recurrente en Google, busca
    la que corresponde a 'fecha_ocurrencia' (ISO YYYY-MM-DD) y devuelve
    su propio ID (distinto del ID de la serie), o None si no la
    encuentra (por ejemplo, si esa ocurrencia no cae dentro del rango
    que devuelve Google). Incluye tambien instancias ya canceladas
    (showDeleted=True), porque para restaurar una hace falta encontrar
    su ID igualmente."""
    pagina = None
    while True:
        respuesta = servicio.events().instances(
            calendarId=google_calendar_id, eventId=google_event_id, pageToken=pagina, showDeleted=True,
        ).execute()
        for instancia in respuesta.get("items", []):
            punto_temporal = instancia.get("originalStartTime") or instancia.get("start")
            fecha_instancia, _ = _fecha_hora_desde_google(punto_temporal)
            if fecha_instancia == fecha_ocurrencia:
                return instancia["id"]
        pagina = respuesta.get("nextPageToken")
        if not pagina:
            return None


def push_excepcion(evento_id, fecha_ocurrencia):
    """Refleja en Google la cancelacion o edicion de una sola ocurrencia
    de un evento recurrente. Best effort: si el evento todavia no esta
    sincronizado con Google, o falla la llamada, no hace nada mas (no
    interrumpe el flujo normal de la web, que ya ha guardado el cambio
    localmente antes de llamar a esta funcion)."""
    conn = get_db_connection()
    fila = conn.execute("SELECT * FROM calendario_eventos WHERE id = ?", (evento_id,)).fetchone()
    conn.close()
    if fila is None or not fila["google_event_id"] or not fila["google_calendario_id"]:
        return

    conn = get_db_connection()
    calendario_row = conn.execute(
        "SELECT * FROM calendario_google_calendarios WHERE id = ?", (fila["google_calendario_id"],)
    ).fetchone()
    conn.close()
    if calendario_row is None or calendario_row["rol_acceso"] in _ROLES_SOLO_LECTURA:
        return

    credenciales = obtener_credenciales(fila["usuario_id"])
    if credenciales is None:
        return

    try:
        servicio = _servicio_calendar(credenciales)
        instancia_id = _buscar_instancia_google(
            servicio, calendario_row["google_calendar_id"], fila["google_event_id"], fecha_ocurrencia
        )
        if instancia_id is None:
            return

        excepcion = excepcion_de_ocurrencia(evento_id, fecha_ocurrencia)
        if excepcion is not None and excepcion["cancelada"]:
            servicio.events().delete(
                calendarId=calendario_row["google_calendar_id"], eventId=instancia_id
            ).execute()
            return

        datos_ocurrencia = dict(fila)
        if excepcion is not None:
            datos_ocurrencia["titulo"] = excepcion["titulo"] or fila["titulo"]
            datos_ocurrencia["hora"] = excepcion["hora"] if excepcion["hora"] is not None else fila["hora"]
            datos_ocurrencia["hora_fin"] = (
                excepcion["hora_fin"] if excepcion["hora_fin"] is not None else fila["hora_fin"]
            )
            datos_ocurrencia["todo_el_dia"] = (
                excepcion["todo_el_dia"] if excepcion["todo_el_dia"] is not None else fila["todo_el_dia"]
            )
            datos_ocurrencia["lugar"] = excepcion["lugar"] if excepcion["lugar"] is not None else fila["lugar"]
            datos_ocurrencia["descripcion"] = (
                excepcion["descripcion"] if excepcion["descripcion"] is not None else fila["descripcion"]
            )
        datos_ocurrencia["fecha"] = fecha_ocurrencia
        datos_ocurrencia["repetir"] = "ninguna"
        datos_ocurrencia["repetir_hasta"] = None

        cuerpo = _construir_cuerpo_evento_google(datos_ocurrencia)
        servicio.events().patch(
            calendarId=calendario_row["google_calendar_id"], eventId=instancia_id, body=cuerpo
        ).execute()
    except HttpError as error:
        print(f"[google-sync] No se pudo sincronizar la ocurrencia del {fecha_ocurrencia} (evento {evento_id}): {error}")
    except Exception as error:
        print(f"[google-sync] No se pudo sincronizar la ocurrencia del {fecha_ocurrencia} (evento {evento_id}): {error}")


def push_restauracion(evento_id, fecha_ocurrencia):
    """Refleja en Google que una ocurrencia concreta ha vuelto a ser
    igual que el resto de la serie, tras 'Ocurrencia -> Restaurar' en
    la app (deshace una cancelacion o una edicion puntual). Se intenta
    dejar esa instancia en Google con los mismos datos que tendria por
    defecto segun el evento principal.

    Es la unica de las sincronizaciones que no es 100% fiable: si la
    ocurrencia estaba cancelada en Google, "revivirla" depende de que
    Google acepte volver a poner esa instancia como 'confirmed' (no
    todas las cuentas se comportan igual). Si no lo acepta, se registra
    el aviso y la ocurrencia se queda restaurada solo en la app: no
    rompe nada, simplemente no queda reflejado en Google."""
    conn = get_db_connection()
    fila = conn.execute("SELECT * FROM calendario_eventos WHERE id = ?", (evento_id,)).fetchone()
    conn.close()
    if fila is None or not fila["google_event_id"] or not fila["google_calendario_id"]:
        return

    conn = get_db_connection()
    calendario_row = conn.execute(
        "SELECT * FROM calendario_google_calendarios WHERE id = ?", (fila["google_calendario_id"],)
    ).fetchone()
    conn.close()
    if calendario_row is None or calendario_row["rol_acceso"] in _ROLES_SOLO_LECTURA:
        return

    credenciales = obtener_credenciales(fila["usuario_id"])
    if credenciales is None:
        return

    # Los datos "por defecto" de esta ocurrencia son los del evento
    # principal, aplicados a la fecha concreta (sin recurrencia: se
    # esta editando solo esta instancia, no toda la serie).
    datos_ocurrencia = dict(fila)
    datos_ocurrencia["fecha"] = fecha_ocurrencia
    datos_ocurrencia["repetir"] = "ninguna"
    datos_ocurrencia["repetir_hasta"] = None
    cuerpo = _construir_cuerpo_evento_google(datos_ocurrencia)
    cuerpo["status"] = "confirmed"

    try:
        servicio = _servicio_calendar(credenciales)
        instancia_id = _buscar_instancia_google(
            servicio, calendario_row["google_calendar_id"], fila["google_event_id"], fecha_ocurrencia
        )
        if instancia_id is None:
            return

        try:
            servicio.events().patch(
                calendarId=calendario_row["google_calendar_id"], eventId=instancia_id, body=cuerpo
            ).execute()
        except HttpError as error_patch:
            # Si la instancia estaba cancelada, algunas cuentas no
            # dejan reactivarla con un patch parcial; se reintenta una
            # vez con un update completo antes de darse por vencido.
            print(f"[google-sync] El patch para restaurar ha fallado, se reintenta con update: {error_patch}")
            servicio.events().update(
                calendarId=calendario_row["google_calendar_id"], eventId=instancia_id, body=cuerpo
            ).execute()
    except Exception as error:
        print(
            f"[google-sync] No se pudo restaurar en Google la ocurrencia del {fecha_ocurrencia} "
            f"(evento {evento_id}): {error}"
        )


# =================================================================
# Ciclo periodico completo (lo llama el scheduler de app/__init__.py)
# =================================================================

def _sincronizar_usuario(usuario_id):
    conn = get_db_connection()
    pendientes = conn.execute(
        "SELECT id FROM calendario_eventos WHERE usuario_id = ? AND pendiente_subir = 1", (usuario_id,)
    ).fetchall()
    calendarios = conn.execute(
        "SELECT * FROM calendario_google_calendarios WHERE usuario_id = ? AND sync_activo = 1", (usuario_id,)
    ).fetchall()
    conn.close()

    for fila in pendientes:
        push_evento(fila["id"])

    _reintentar_eliminaciones_pendientes(usuario_id)

    for calendario_row in calendarios:
        sincronizar_calendario(usuario_id, calendario_row)

    print(
        f"[google-sync] Usuario {usuario_id}: {len(pendientes)} evento(s) subido(s), "
        f"{len(calendarios)} calendario(s) revisado(s)."
    )


def sincronizar_todos_los_usuarios():
    """Punto de entrada que llama el job en segundo plano (y que se
    podria llamar tambien a mano si en el futuro se anade un boton de
    'sincronizar ahora'). Recorre todos los usuarios con una cuenta de
    Google conectada; un fallo con uno no afecta a los demas."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return

    conn = get_db_connection()
    usuarios = [f["usuario_id"] for f in conn.execute("SELECT usuario_id FROM calendario_google_cuentas").fetchall()]
    conn.close()

    for usuario_id in usuarios:
        try:
            _sincronizar_usuario(usuario_id)
        except Exception as error:
            print(f"[google-sync] Error inesperado sincronizando el usuario {usuario_id}: {error}")
