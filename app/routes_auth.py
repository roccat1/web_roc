"""
Rutas de autenticacion: pagina de inicio, registro, login y logout.
"""

import sqlite3

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import app
from .db import get_db_connection


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not username or not password:
            flash("Omple usuari i contrasenya.")
            return redirect(url_for("registro"))

        # Nunca guardamos la contrasena tal cual, se guarda "hasheada".
        password_hash = generate_password_hash(password)

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO usuarios (username, password) VALUES (?, ?)",
                (username, password_hash),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("Aquest nom d'usuari ja existeix, prova amb un altre.")
            conn.close()
            return redirect(url_for("registro"))
        conn.close()

        flash("Compte creat correctament. Ja pots iniciar sessio.")
        return redirect(url_for("login"))

    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db_connection()
        usuario = conn.execute(
            "SELECT * FROM usuarios WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if usuario is None or not check_password_hash(usuario["password"], password):
            flash("Usuari o contrasenya incorrectes.")
            return redirect(url_for("login"))

        session.permanent = True
        session["usuario_id"] = usuario["id"]
        session["username"] = usuario["username"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Sessio tancada correctament.")
    return redirect(url_for("index"))

