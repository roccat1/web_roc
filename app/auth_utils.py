"""
Utilidades pequenas que usan varios modulos de rutas: el decorador que
protege las paginas que requieren haber iniciado sesion, y el filtro de
plantilla que da formato a los importes en euros.
"""

from functools import wraps

from flask import flash, redirect, session, url_for


def login_requerido(vista):
    """
    Decorador para proteger rutas.
    Si el usuario no ha iniciado sesion, lo manda a la pagina de login.
    """
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "usuario_id" not in session:
            flash("Has d'iniciar sessio per veure aquesta pagina.")
            return redirect(url_for("login"))
        return vista(*args, **kwargs)
    return envoltura


def formatear_euros(valor):
    """Convierte un numero en texto tipo '1.234,50 €' (formato espanol)."""
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{texto} €"
