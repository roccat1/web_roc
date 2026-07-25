"""
FINANZAS - gestion de categorias y subcategorias (crear, editar, eliminar).
"""

from flask import flash, redirect, render_template, request, session, url_for

from . import app
from .auth_utils import login_requerido
from .db import get_db_connection
from .finanzas_helpers import obtener_categorias_con_subcategorias, categoria_del_usuario


@app.route("/finanzas/categorias")
@login_requerido
def finanzas_categorias():
    usuario_id = session["usuario_id"]
    categorias = obtener_categorias_con_subcategorias(usuario_id)
    gastos = [c for c in categorias if c["tipo"] == "gasto"]
    ingresos = [c for c in categorias if c["tipo"] == "ingreso"]
    return render_template("finanzas/categorias.html", gastos=gastos, ingresos=ingresos)


@app.route("/finanzas/categorias/nueva", methods=["POST"])
@login_requerido
def finanzas_nueva_categoria():
    usuario_id = session["usuario_id"]
    nombre = request.form.get("nombre", "").strip()
    tipo = request.form.get("tipo")

    if not nombre or tipo not in ("gasto", "ingreso"):
        flash("Escribe un nombre y elige si es de gasto o de ingreso.")
        return redirect(url_for("finanzas_categorias"))

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO categorias (usuario_id, nombre, tipo) VALUES (?, ?, ?)",
        (usuario_id, nombre, tipo),
    )
    conn.commit()
    conn.close()

    flash(f"Categoria '{nombre}' creada.")
    return redirect(url_for("finanzas_categorias"))


@app.route("/finanzas/categorias/<int:categoria_id>/editar", methods=["GET", "POST"])
@login_requerido
def finanzas_editar_categoria(categoria_id):
    usuario_id = session["usuario_id"]
    categoria = categoria_del_usuario(categoria_id, usuario_id)
    if categoria is None:
        flash("Esa categoria no existe.")
        return redirect(url_for("finanzas_categorias"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        tipo = request.form.get("tipo")

        if not nombre or tipo not in ("gasto", "ingreso"):
            flash("Escribe un nombre y elige si es de gasto o de ingreso.")
            return redirect(url_for("finanzas_editar_categoria", categoria_id=categoria_id))

        conn = get_db_connection()
        conn.execute(
            "UPDATE categorias SET nombre = ?, tipo = ? WHERE id = ?",
            (nombre, tipo, categoria_id),
        )
        conn.commit()
        conn.close()

        flash("Categoria actualizada.")
        return redirect(url_for("finanzas_categorias"))

    return render_template("finanzas/editar_categoria.html", categoria=categoria)


@app.route("/finanzas/categorias/<int:categoria_id>/eliminar", methods=["POST"])
@login_requerido
def finanzas_eliminar_categoria(categoria_id):
    usuario_id = session["usuario_id"]
    categoria = categoria_del_usuario(categoria_id, usuario_id)
    if categoria is None:
        flash("Esa categoria no existe.")
        return redirect(url_for("finanzas_categorias"))

    conn = get_db_connection()
    en_uso = conn.execute(
        "SELECT COUNT(*) AS total FROM operaciones WHERE categoria_id = ?", (categoria_id,)
    ).fetchone()["total"]

    if en_uso > 0:
        flash("No se puede eliminar: hay operaciones que usan esta categoria.")
        conn.close()
        return redirect(url_for("finanzas_categorias"))

    conn.execute("DELETE FROM subcategorias WHERE categoria_id = ?", (categoria_id,))
    conn.execute("DELETE FROM categorias WHERE id = ?", (categoria_id,))
    conn.commit()
    conn.close()

    flash("Categoria eliminada.")
    return redirect(url_for("finanzas_categorias"))


@app.route("/finanzas/subcategorias/nueva", methods=["POST"])
@login_requerido
def finanzas_nueva_subcategoria():
    usuario_id = session["usuario_id"]
    categoria_id = request.form.get("categoria_id", type=int)
    nombre = request.form.get("nombre", "").strip()

    categoria = categoria_del_usuario(categoria_id, usuario_id) if categoria_id else None
    if categoria is None or not nombre:
        flash("Elige una categoria y escribe un nombre para la subcategoria.")
        return redirect(url_for("finanzas_categorias"))

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO subcategorias (categoria_id, nombre) VALUES (?, ?)",
        (categoria_id, nombre),
    )
    conn.commit()
    conn.close()

    flash(f"Subcategoria '{nombre}' creada.")
    return redirect(url_for("finanzas_categorias"))


@app.route("/finanzas/subcategorias/<int:subcategoria_id>/editar", methods=["GET", "POST"])
@login_requerido
def finanzas_editar_subcategoria(subcategoria_id):
    usuario_id = session["usuario_id"]
    conn = get_db_connection()
    subcategoria = conn.execute("""
        SELECT subcategorias.*, categorias.usuario_id AS propietario
        FROM subcategorias
        JOIN categorias ON categorias.id = subcategorias.categoria_id
        WHERE subcategorias.id = ?
    """, (subcategoria_id,)).fetchone()
    conn.close()

    if subcategoria is None or subcategoria["propietario"] != usuario_id:
        flash("Esa subcategoria no existe.")
        return redirect(url_for("finanzas_categorias"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            flash("Escribe un nombre para la subcategoria.")
            return redirect(url_for("finanzas_editar_subcategoria", subcategoria_id=subcategoria_id))

        conn = get_db_connection()
        conn.execute("UPDATE subcategorias SET nombre = ? WHERE id = ?", (nombre, subcategoria_id))
        conn.commit()
        conn.close()

        flash("Subcategoria actualizada.")
        return redirect(url_for("finanzas_categorias"))

    return render_template("finanzas/editar_subcategoria.html", subcategoria=subcategoria)


@app.route("/finanzas/subcategorias/<int:subcategoria_id>/eliminar", methods=["POST"])
@login_requerido
def finanzas_eliminar_subcategoria(subcategoria_id):
    usuario_id = session["usuario_id"]
    conn = get_db_connection()
    subcategoria = conn.execute("""
        SELECT subcategorias.*, categorias.usuario_id AS propietario
        FROM subcategorias
        JOIN categorias ON categorias.id = subcategorias.categoria_id
        WHERE subcategorias.id = ?
    """, (subcategoria_id,)).fetchone()

    if subcategoria is None or subcategoria["propietario"] != usuario_id:
        flash("Esa subcategoria no existe.")
        conn.close()
        return redirect(url_for("finanzas_categorias"))

    en_uso = conn.execute(
        "SELECT COUNT(*) AS total FROM operaciones WHERE subcategoria_id = ?", (subcategoria_id,)
    ).fetchone()["total"]

    if en_uso > 0:
        flash("No se puede eliminar: hay operaciones que usan esta subcategoria.")
        conn.close()
        return redirect(url_for("finanzas_categorias"))

    conn.execute("DELETE FROM subcategorias WHERE id = ?", (subcategoria_id,))
    conn.commit()
    conn.close()

    flash("Subcategoria eliminada.")
    return redirect(url_for("finanzas_categorias"))
