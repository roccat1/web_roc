"""
Punto de entrada de la web: `python3 run.py`.

Antes de dividir el codigo en varios archivos, esto se arrancaba con
`python3 app.py`. Ahora `app` es una carpeta (un paquete de Python)
con toda la logica dividida por temas, y este archivo es lo unico que
hace falta ejecutar para levantar el servidor.
"""

from app import app, init_db
from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG

if __name__ == "__main__":
    init_db()
    # El host, puerto y modo debug se configuran en el archivo .env
    # (FLASK_HOST, FLASK_PORT, FLASK_DEBUG). Por defecto, host="0.0.0.0"
    # permite entrar desde otros dispositivos de tu red local, por
    # ejemplo desde el movil usando la IP de la Raspberry Pi.
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
