# App Flask basica con login (SQLite) + Finanzas + Caducidades + Caca + Bot de Telegram

Web hecha con Flask que tiene:
- Pagina de inicio
- Registro de usuarios
- Login / logout
- Un **dashboard** ("Mi cuenta") con un resumen general: saldo de finanzas,
  estado de las fechas de caducidad, si tienes el bot de Telegram
  vinculado, y tus registros de "Caca"
- Una seccion de **Finanzas personales**: cuentas, categorias, subcategorias,
  gastos, ingresos, transferencias entre cuentas, y un apartado de analisis
  con graficos (por anio y por mes)
- Una seccion de **Fechas de caducidad**: para llevar el control de
  documentacion, mantenimiento del coche, seguros o lo que el usuario
  quiera anadir, con avisos y un boton de revalidacion rapida
- Una seccion de **Caca**: registro rapido de una actividad con hora
  exacta, historial, y una pagina de estadisticas con graficos (por dias,
  meses, anios, y por hora del dia) y un sistema de perfil publico/privado
  para comparar con otros usuarios de la app
- Un **bot de Telegram** para consultar y registrar todo lo anterior desde
  el movil, sin abrir el navegador, con avisos automaticos de caducidades
- Base de datos local en SQLite (un archivo `usuarios.db`, no hace falta instalar ningun servidor de base de datos)

Cada usuario tiene sus propias cuentas, categorias, operaciones, fechas
de caducidad y registros de Caca: son completamente independientes entre
usuarios distintos (salvo que marques tu perfil de Caca como publico).

## Estructura de archivos

```
flask_login_app/
├── run.py                        <- arranca la web (`python3 run.py`)
├── bot.py                        <- el bot de Telegram (se ejecuta aparte)
├── config.py                     <- lee el .env y expone la configuracion a run.py y bot.py
├── app/                          <- la app Flask, dividida por temas
│   ├── __init__.py                 <- crea la app Flask y registra todas las rutas
│   ├── db.py                       <- conexion a SQLite, init_db() y constantes compartidas
│   ├── auth_utils.py                <- decorador @login_requerido y filtro "euros"
│   ├── routes_auth.py               <- inicio, registro, login, logout
│   ├── routes_dashboard.py          <- panel general ("Mi cuenta")
│   ├── finanzas_helpers.py          <- funciones de ayuda de Finanzas
│   ├── finanzas_operaciones.py      <- resumen, historial y alta de operaciones
│   ├── finanzas_categorias.py       <- categorias y subcategorias
│   ├── finanzas_cuentas.py          <- cuentas y cuentas predefinidas
│   ├── finanzas_analisis.py         <- pagina de analisis con graficos
│   ├── caducidades_helpers.py       <- calculo de estado y validacion del formulario
│   ├── caducidades_routes.py        <- listado, alta, edicion, borrado, revalidar
│   ├── caca_helpers.py              <- lectura de registros y perfiles visibles
│   ├── caca_routes.py               <- registrar, historial, estadisticas, privacidad
│   ├── telegram_helpers.py          <- vincular/desvincular (las usa tambien bot.py)
│   └── telegram_routes.py           <- vincular la cuenta desde el navegador
├── .env                          <- AQUI se cambia la configuracion (claves, token, etc.)
├── .gitignore                    <- excluye .env y usuarios.db si usas git
├── requirements.txt              <- dependencias necesarias
├── static/
│   └── style.css                  <- estilos (tema "placa de circuitos")
└── templates/
    ├── base.html                  <- plantilla comun (menu, mensajes)
    ├── index.html                 <- pagina de inicio
    ├── login.html                 <- formulario de login
    ├── registro.html               <- formulario de registro
    ├── dashboard.html              <- panel general (finanzas + caducidades + telegram + caca)
    ├── telegram.html               <- vincular / desvincular el bot
    ├── finanzas/
    │   ├── index.html               <- resumen: saldo total, cuentas, ultimos movimientos
    │   ├── operaciones.html         <- historial completo (con boton de eliminar)
    │   ├── nueva_operacion.html     <- formulario de gasto / ingreso / transferencia (o paso a paso)
    │   ├── categorias.html          <- listado y creacion de categorias y subcategorias
    │   ├── editar_categoria.html
    │   ├── editar_subcategoria.html
    │   ├── cuentas.html             <- listado, creacion y cuentas predefinidas
    │   ├── editar_cuenta.html
    │   └── analisis.html            <- graficos y desgloses (ver seccion de abajo)
    ├── caducidades/
    │   ├── index.html                <- listado, filtros y resumen de caducidades
    │   ├── nueva.html                <- formulario para anadir una fecha
    │   └── editar.html                <- formulario para editar / renovar una fecha
    └── caca/
        ├── index.html                <- registrar ahora, formulario manual, historial
        └── estadisticas.html          <- KPIs, grafico y privacidad publico/privado
```

La logica que antes estaba toda junta en un unico `app.py` ahora vive
dividida en la carpeta `app/`, con un archivo por tema (autenticacion,
finanzas, caducidades, caca, telegram...). `app/__init__.py` es quien
crea la app Flask y va importando cada uno de esos archivos para que
registren sus rutas; el resto del comportamiento es exactamente el
mismo que antes, incluido `bot.py`, que no ha hecho falta tocar.

## Configuracion (`.env`)

Toda la configuracion de la app (claves, rutas, el token del bot, la
zona horaria...) vive en el archivo `.env`, en la raiz del proyecto.
Para cambiar algo, edita ese archivo con cualquier editor de texto y
reinicia `run.py` y/o `bot.py`: **no hace falta tocar ningun archivo
`.py`**. Si el `.env` no existe o le falta alguna variable, se usan los
valores por defecto de abajo, para que la app funcione igualmente.

| Variable | Para que sirve | Valor por defecto |
|---|---|---|
| `SECRET_KEY` | Clave secreta de las sesiones de Flask | `cambia-esta-clave-por-una-tuya` |
| `DATABASE_PATH` | Donde se guarda la base de datos SQLite | `usuarios.db` (en la raiz del proyecto) |
| `FLASK_HOST` | Direccion donde escucha la web | `0.0.0.0` (accesible desde tu red) |
| `FLASK_PORT` | Puerto donde escucha la web | `5000` |
| `FLASK_DEBUG` | Modo debug de Flask (`True`/`False`) | `True` |
| `TELEGRAM_BOT_TOKEN` | Token del bot, te lo da @BotFather | (vacio; el bot no arranca sin esto) |
| `TELEGRAM_TIMEZONE` | Zona horaria del aviso diario de caducidades | `Europe/Madrid` |
| `TELEGRAM_AVISO_HORA` | Hora del aviso diario (formato `HH:MM`) | `09:00` |

Tanto `run.py` como `bot.py` importan estos valores desde `config.py`,
que es quien realmente lee el `.env` (usando la libreria
[`python-dotenv`](https://pypi.org/project/python-dotenv/)). No compartas
tu `.env` con nadie ni lo subas a internet una vez tenga tu token o tu
clave secreta reales: el `.gitignore` incluido ya lo excluye si usas git.

## Como funciona la seccion de Finanzas

- **Cuentas**: se crean y editan desde `Finanzas -> Cuentas`. Cada cuenta
  tiene un nombre y un saldo, que se actualiza solo cuando registras
  operaciones (aunque tambien puedes ajustarlo a mano editando la cuenta).
- **Categorias y subcategorias**: se gestionan desde `Finanzas -> Categorias`.
  Una categoria es de tipo "gasto" o "ingreso", y cada una puede tener
  varias subcategorias (por ejemplo, categoria "Alimentacion" con
  subcategorias "Supermercado" y "Restaurantes").
- **Operaciones**: desde `Finanzas -> + Nueva operacion` eliges el tipo:
  - **Gasto**: sale dinero de una cuenta. Obliga a elegir categoria y subcategoria.
  - **Ingreso**: entra dinero en una cuenta. Tambien obliga a elegir categoria y subcategoria.
  - **Transferencia**: mueve dinero entre dos de tus cuentas (no necesita categoria).

  Esta pagina tiene dos formas de rellenarla, con un boton arriba para
  cambiar entre una y otra (los datos que hayas puesto se conservan al
  cambiar):
  - **Formulario**: todos los campos a la vista, como un formulario normal.
  - **Paso a paso, como el bot**: va preguntando de una en una las mismas
    cosas (tipo, importe, categoria, subcategoria, cuenta, descripcion)
    con botones para ir eligiendo, igual que la conversacion del bot de
    Telegram. Al final te ensena un resumen antes de guardar. Las dos
    formas mandan exactamente los mismos datos al servidor.
- **Cuentas predefinidas**: en `Finanzas -> Cuentas` puedes indicar que
  cuenta se debe seleccionar automaticamente para cada tipo de operacion
  (gasto, ingreso, transferencia). Siempre puedes cambiarla a mano al
  crear una operacion concreta.
- Si intentas eliminar una cuenta, categoria o subcategoria que ya tiene
  operaciones asociadas, la app lo impide para no dejar datos huerfanos.
- Si eliminas una operacion desde el historial, el saldo de la cuenta (o
  cuentas, en el caso de una transferencia) se ajusta automaticamente
  para deshacer su efecto.

## Analisis (`Finanzas -> Analisis`)

Pagina con graficos y desgloses para entender en que se va el dinero:

- **Filtro por anio y por mes**: eliges un anio concreto (o "Todos los
  anios") y, si quieres, tambien un mes de ese anio, para ver los
  totales, graficos de tarta y desgloses de ese mes exacto. El grafico
  de barras "Ingresos y gastos por mes" siempre muestra el anio
  completo (los 12 meses), para poder comparar, aunque hayas filtrado
  a un mes concreto.
- **Tarjetas KPI**: ingresos, gastos, ahorro (ingresos - gastos) y
  porcentaje ahorrado del periodo elegido.
- **Grafico de barras**: ingresos vs gastos mes a mes (enero-diciembre)
  dentro del anio elegido (o sumando todos los anios si eliges "Todos").
- **Graficos de tarta (donut)**: reparto de gastos y de ingresos por
  categoria.
- **Desgloses detallados**: listas con barra de porcentaje para gastos
  por categoria (con sus subcategorias dentro), ingresos por categoria
  y gasto por cuenta.
- **Gasto medio mensual** del periodo seleccionado.

Los graficos usan la libreria [Chart.js](https://www.chartjs.org/),
cargada desde un CDN (`cdn.jsdelivr.net`), asi que la Raspberry Pi
necesita conexion a internet para verlos correctamente; el resto de la
app funciona igual sin conexion porque no depende de ninguna libreria
externa.

## Fechas de caducidad (`Caducidades`)

Un registro libre para controlar cualquier cosa que caduque: DNI,
pasaporte, ITV, seguros, revisiones de la caldera, suscripciones...
El usuario decide que fechas quiere anadir, no hay una lista cerrada.

Cada registro tiene:
- **Nombre** (ej. "ITV Renault Clio")
- **Categoria**: texto libre, con sugerencias (Documentacion, Vehiculo,
  Hogar, Salud, Seguros, Suscripciones, Otros) pero puedes escribir la
  que quieras
- **Fecha de caducidad**
- **Avisar con antelacion (dias)**: cuantos dias antes de la fecha
  quieres que se marque como "proximo a caducar" (30 dias por defecto)
- **Notas** (opcional): ej. "Llevar a Talleres Perez"

Segun cuantos dias falten, cada registro se clasifica automaticamente en:
- 🔴 **Caducado** (LED rojo): la fecha ya paso
- 🟡 **Proximo** (LED ambar): faltan menos dias de los indicados en "avisar con antelacion"
- 🟢 **Vigente** (LED verde): todavia queda tiempo de sobra

La pagina principal (`Caducidades`) muestra un resumen (cuantos hay de
cada tipo) y permite filtrar por estado y por categoria. Para "renovar"
un documento (por ejemplo, despues de pasar la ITV), simplemente edita
el registro y pon la nueva fecha.

### Revalidar con un boton

Al crear (o editar) un registro puedes rellenar opcionalmente
**"Revalidar automaticamente cada (dias)"** (ej. 365 para algo anual).
Si lo rellenas, en el listado aparece un boton **Revalidar** junto a
ese registro: al pulsarlo, la fecha de caducidad se recalcula como
*hoy + esos dias*, sin tener que abrir el formulario de edicion. Si lo
dejas en blanco, el registro no tiene boton de revalidar y hay que
cambiar la fecha a mano desde "Editar" (util para fechas puntuales que
no se repiten).

## Panel general (`Mi cuenta`)

El dashboard que se ve tras iniciar sesion combina en una sola pantalla:
- El saldo total de Finanzas y el numero de cuentas, con acceso directo
- El resumen de Caducidades (cuantas caducadas / proximas) y las 5
  fechas mas urgentes, con acceso directo
- Si tienes o no el bot de Telegram vinculado, con acceso a esa pagina
- Cuantos registros de Caca tienes, con acceso directo

## Bot de Telegram

El bot es un programa **aparte** de la web: se ejecuta con `python3 bot.py`
en vez de `python3 run.py`. Usa la misma base de datos SQLite
(`usuarios.db`), asi que todo lo que hagas por Telegram aparece tambien
en la web, y al reves. Puedes tener la web y el bot arrancados a la vez
sin ningun problema.

### 1. Crear el bot en Telegram

1. Abre Telegram y busca **@BotFather**.
2. Envia `/newbot` y sigue sus instrucciones (nombre y usuario del bot).
3. BotFather te da un **token** (una cadena larga tipo `123456:ABC-...`).
   Guardalo, lo necesitas en el siguiente paso.

### 2. Configurar y arrancar el bot en tu Raspberry Pi

```bash
cd flask_login_app
source venv/bin/activate          # el mismo entorno virtual que ya tenias
pip install -r requirements.txt   # instala python-telegram-bot y python-dotenv
```

Abre el archivo `.env` (en la raiz del proyecto) y pega tu token
en esta linea:

```
TELEGRAM_BOT_TOKEN=PEGA_AQUI_TU_TOKEN_DE_BOTFATHER
```

Y arranca el bot:

```bash
python3 bot.py
```

Veras "Bot arrancado. Pulsa Ctrl+C para pararlo." Dejalo corriendo (en
otra pestana de terminal, con `tmux`/`screen`, o como servicio, ver
mas abajo) mientras quieras poder usarlo desde Telegram.

### 3. Vincular tu cuenta

El bot necesita saber que chat de Telegram corresponde a que cuenta de
la web. Se hace con un codigo de un solo uso:

1. En la web, entra en **Mi cuenta -> Telegram** y pulsa "Generar codigo
   de vinculacion". Te da un codigo de 6 digitos, valido 10 minutos.
2. Abre tu bot en Telegram y envia `/vincular 123456` (con tu codigo).
3. Listo. Escribe `/ayuda` en el bot para ver todos los comandos.

Puedes desvincular la cuenta en cualquier momento, desde la web
(Mi cuenta -> Telegram -> Desvincular) o desde el propio bot con
`/desvincular`.

### Comandos disponibles

**Consultar**
- `/saldo` - saldo total y el de cada cuenta
- `/movimientos` - tus ultimas 5 operaciones
- `/caducidades` - todas tus fechas de caducidad, con su estado
- `/comprobaravisos` - fuerza ya la comprobacion de avisos (sin esperar a la hora programada)

**Registrar** (te van preguntando paso a paso, con botones para elegir
categoria, subcategoria y cuenta de una lista, igual que en la web)
- `/gasto` - registrar un gasto
- `/ingreso` - registrar un ingreso
- `/transferencia` - mover dinero entre dos de tus cuentas
- `/nuevacaducidad` - anadir una fecha de caducidad nueva
- `/revalidar` - revalidar (con un boton) una que ya tenga dias de
  revalidacion configurados

**Cuenta**
- `/vincular <codigo>` / `/desvincular`
- `/cancelar` - cancela lo que estuvieras rellenando
- `/ayuda` - lista de comandos

### Avisos automaticos

Mientras el bot este arrancado, cada dia a las 9:00 (hora configurable en
el `.env`, variable `TELEGRAM_AVISO_HORA`) revisa las fechas de caducidad de todos
los usuarios con Telegram vinculado y te envia un mensaje:
- 🟡 la primera vez que un registro entra en su ventana de aviso (los
  "dias de antelacion" que configuraste)
- 🔴 la primera vez que un registro caduca

Cada aviso se envia **una sola vez**: no te va a escribir todos los dias
sobre lo mismo. Si revalidas el registro (boton "Revalidar" o editando
la fecha, desde la web o desde el bot), vuelve a poder avisarte en el
futuro, cuando le toque de nuevo.

Ademas de la comprobacion diaria, el bot hace **una comprobacion nada
mas arrancar** (unos segundos despues de conectar), para no tener que
esperar hasta la hora programada para ver si funciona. Tambien puedes
forzarla tu mismo en cualquier momento con el comando **`/comprobaravisos`**.

El texto de los avisos se elige al azar de unas listas de mensajes
predefinidos, para que no suene siempre igual. Estan al principio de
`bot.py`, en `MENSAJES_AVISO_PROXIMO` y `MENSAJES_AVISO_CADUCADO`, y
puedes anadir, quitar o reescribir los que quieras:

```python
MENSAJES_AVISO_PROXIMO = [
    "Aviso: '{nombre}' ({categoria}) {texto_estado}.",
    "Recuerda que '{nombre}' ({categoria}) {texto_estado}. No lo dejes para el ultimo dia.",
    ...
]
```

Dentro de cada mensaje puedes usar `{nombre}`, `{categoria}`, `{dias}`
(numero de dias, siempre positivo) y `{texto_estado}` (ej. "caduca en
5 dias").

Para que los avisos automaticos funcionen hace falta instalar la
libreria con el extra `job-queue` (ya incluido en `requirements.txt`):

```bash
pip install -r requirements.txt
```

Si en algun momento la instalas sin ese extra, el bot te avisa por
consola al arrancar, y el resto de comandos siguen funcionando igual;
simplemente no se programan los avisos automaticos (pero
`/comprobaravisos` sigue funcionando igual, porque no depende de eso).

**Zona horaria:** la hora de `TELEGRAM_AVISO_HORA` se interpreta en la
zona horaria de `TELEGRAM_TIMEZONE` (ambas en el `.env`; por defecto
`09:00` y `Europe/Madrid` — cambialas si vives en otro sitio). En
Windows hace falta el paquete `tzdata` para que esto funcione (ya esta
en `requirements.txt`); si no esta instalado, el bot sigue arrancando
pero programa la hora en UTC en vez de en tu hora local, y te avisa de
ello por consola.

**Si los avisos no te llegan**, revisa la consola donde tienes
`bot.py` corriendo: cada vez que se comprueban las caducidades (al
arrancar, cada dia a la hora programada, o al usar `/comprobaravisos`)
se imprime una linea `[avisos] ...` con cuantos usuarios y cuantos
avisos se han enviado. Las causas mas habituales de que no llegue nada:
- No tienes ningun registro en estado "proximo" o "caducado" (los
  "vigentes" no avisan nunca, es normal). Comprueba en `/caducidades`.
- Ya se aviso de ese registro antes (por eso no se repite). Prueba a
  revalidarlo o editar su fecha para reiniciar el aviso, y luego usa
  `/comprobaravisos`.
- Falta el extra `job-queue` (te lo dice la consola al arrancar). Aun
  asi, `/comprobaravisos` deberia funcionar sin este extra.

### Menu de comandos en Telegram

Al arrancar, el bot registra automaticamente la lista de comandos en
Telegram (`set_my_commands`), para que aparezcan sugeridos en el boton
"Menu" junto al campo de texto del chat, con una descripcion corta de
cada uno. Si acabas de arrancar el bot por primera vez y no los ves
todavia, sal del chat y vuelve a entrar (o reinicia la app de
Telegram); a veces tarda unos segundos en refrescarse.

### Dejarlo arrancando solo (opcional)

Igual que con la web, puedes crear un servicio de systemd para el bot,
por ejemplo `/etc/systemd/system/telegrambot.service`:

```ini
[Unit]
Description=Bot de Telegram de mi app
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/flask_login_app
ExecStart=/home/pi/flask_login_app/venv/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable telegrambot
sudo systemctl start telegrambot
```

Asi tendrias dos servicios corriendo a la vez en tu Raspberry Pi: uno
para la web (`flaskapp.service`) y otro para el bot (`telegrambot.service`),
ambos leyendo y escribiendo en el mismo `usuarios.db`.

## Caca

Seccion de seguimiento con la logica portada fielmente del proyecto
original (`poop.js` / `home.js`): un registro rapido con hora exacta,
mas una pagina de estadisticas con graficos de tendencia.

**Registrar** (`Caca`):
- Boton grande "Registrar ahora": pide confirmar la hora (calculada en
  tu propio navegador, igual que en el original) y lo manda al servidor
  con una peticion en segundo plano (sin recargar la pagina hasta que
  termina).
- Formulario manual para anadir una fecha y hora pasada, por si te
  olvidaste de registrarlo en su momento. Tambien se manda en segundo
  plano y el boton se pone en "Guardado!" al terminar.
- Historial completo con boton de eliminar por cada entrada.

**Estadisticas** (`Caca -> Ver estadisticas`):
- Tarjetas con el total, la ultima entrada (en formato "Hoy: 09:00",
  "Ayer: 22:15" o "Hace X dias a las HH:MM"), la media por dia en los
  ultimos 30 y 365 dias, la media por dia de siempre, y la hora del dia
  mas habitual en el ultimo mes.
- Un grafico de linea con dos series superpuestas, "Tendencia" (media
  movil, para suavizar el ruido dia a dia) y "Datos reales", con 5 vistas:
  - **Ultimos 30 dias**: al llegar al principio del historial reciente
    (flecha "atras"), salta a meses naturales completos (mes anterior,
    el anterior a ese...) en vez de seguir con ventanas de 30 dias sueltas.
  - **Ultimo anio**: igual, pero saltando a anios naturales completos.
  - **Media por meses**: todo el historico, un punto por cada mes en el
    que hay algun registro (no se puede navegar, se ve todo de golpe).
  - **Media por anios**: todo el historico, un punto por cada anio.
  - **Por hora del dia**: en que franjas de 15 minutos sueles registrar,
    sobre todo tu historial.
- Las vistas "Media por meses/anios" y "Por hora" muestran todo el
  historico sin paginar; solo "Ultimos 30 dias" y "Ultimo anio" tienen
  flechas de navegacion.

**Perfil publico/privado**: en la pagina de estadisticas puedes marcar tu
perfil como publico. Si lo haces, el resto de usuarios registrados en la
app pueden elegir tu nombre en un desplegable y ver tus mismas
estadisticas (nunca tu historial detallado con boton de eliminar, eso
solo lo ves tu). Por defecto los perfiles son privados.

La logica de los graficos (medias moviles, agrupacion por dia/mes/anio/
hora, navegacion entre periodos) esta escrita en Javascript dentro de
`templates/caca/estadisticas.html`, y se escribio y probo aparte con
Node.js (comparando el resultado con el comportamiento del `home.js`
original) antes de incluirla en la pagina.

## Estilo visual

El diseno esta inspirado en la propia Raspberry Pi: fondo oscuro tipo
placa de circuitos, tipografia monoespaciada para titulos y etiquetas
(como el texto serigrafiado de una placa), y los colores de marca rojo
y verde de Raspberry Pi como acentos (mas un ambar para los avisos,
como un tercer LED de estado). Todo esta definido con variables CSS en
`static/style.css` (`:root { --bg, --red, --green, --amarillo, ... }`),
asi que para mantener la coherencia visual en paginas nuevas basta con
reutilizar esas mismas variables y clases (`.card`, `.btn`, `.badge`,
`.led`, `.kpi-card`, `.pin-row`, etc.) en vez de crear estilos nuevos sueltos.

## 1. Instalar en la Raspberry Pi

Abre una terminal en la Raspberry Pi (por SSH o directamente) y ejecuta:

```bash
# 1. Copia la carpeta flask_login_app a la Raspberry Pi (por ejemplo con scp, USB o git)

# 2. Entra en la carpeta del proyecto
cd flask_login_app

# 3. Crea un entorno virtual (recomendado para no mezclar paquetes con el sistema)
python3 -m venv venv
source venv/bin/activate

# 4. Instala las dependencias
pip install -r requirements.txt
```

## 2. Ejecutar la app

```bash
python3 run.py
```

Veras un mensaje indicando que el servidor esta corriendo. La primera vez que arranca, se crea automaticamente el archivo `usuarios.db` con la tabla de usuarios.

## 3. Acceder desde el navegador

- Desde la propia Raspberry Pi: `http://localhost:5000`
- Desde otro dispositivo de la misma red (movil, PC...): `http://IP_DE_LA_RASPBERRY:5000`

Para saber la IP de la Raspberry Pi, ejecuta `hostname -I` en su terminal.

## 4. Cosas a cambiar antes de usarla "en serio"

Este proyecto es a proposito muy simple para que sea facil de entender, pero si vas a dejarla accesible de forma mas seria conviene que:

1. Cambies `SECRET_KEY` en el archivo `.env` por un valor propio y secreto (no lo compartas ni lo subas a internet).
2. Pongas `FLASK_DEBUG=False` en el `.env` (el modo debug no es seguro para produccion).
3. Uses un servidor mas robusto que el propio de Flask, por ejemplo `gunicorn` o `waitress`, en vez de `python3 run.py`.

## 5. (Opcional) Que arranque solo al encender la Raspberry Pi

Puedes crear un servicio de systemd para que la app se inicie automaticamente. Ejemplo `/etc/systemd/system/flaskapp.service`:

```ini
[Unit]
Description=Mi app Flask
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/flask_login_app
ExecStart=/home/pi/flask_login_app/venv/bin/python3 run.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Luego:

```bash
sudo systemctl enable flaskapp
sudo systemctl start flaskapp
```

## Como funciona el login (resumen rapido)

- Cuando alguien se registra, su contrasena **no** se guarda tal cual: se transforma con `generate_password_hash()` (esto es importante por seguridad).
- Al iniciar sesion, se compara la contrasena introducida con ese hash usando `check_password_hash()`.
- Si coincide, se guarda el id del usuario en `session`, que es una cookie segura que gestiona Flask.
- Las paginas protegidas usan el decorador `@login_requerido`, que revisa si hay una sesion activa antes de mostrar el contenido.
