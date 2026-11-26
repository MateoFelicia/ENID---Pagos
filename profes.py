"""Profesores: página pública, panel del profe, su perfil y la gestión desde el panel del dueño."""
import secrets

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from db import db
from emailer import generar_token_invitacion, url_externa
from forms import NuevoProfeForm, PerfilProfeForm
from imagenes import ImagenInvalida
from models import Curso, Usuario
from sitio import _borrar_si_huerfana, _guardar_imagen, _hay_archivo
from utils import admin_required

bp = Blueprint("profes", __name__)


def _profes_publicos():
    return db.session.execute(
        db.select(Usuario).where(Usuario.es_profesor.is_(True)).order_by(Usuario.nombre)
    ).scalars().all()


# ---------------------------------------------------------------- público

@bp.route("/profesores")
def listado():
    return render_template("profesores.html", profes=_profes_publicos())


# ---------------------------------------------------------------- panel del profe

@bp.route("/profe")
@login_required
def panel():
    if not current_user.es_profesor:
        if current_user.es_admin:
            return redirect(url_for("administrar_cursos"))
        abort(403)
    return render_template("profe/panel.html", cursos=current_user.cursos_dictados)


@bp.route("/profe/perfil", methods=["GET", "POST"])
@login_required
def mi_perfil():
    if not current_user.es_profesor:
        abort(403)
    form = PerfilProfeForm(obj=current_user)
    if form.validate_on_submit():
        if _guardar_perfil(current_user, form):
            flash("Perfil actualizado.", "success")
            return redirect(url_for("profes.panel"))
    return render_template("profe/perfil.html", form=form, profe=current_user, titulo="Mi perfil de profe")


def _guardar_perfil(profe, form):
    """Guarda nombre, título, bio y foto. Devuelve False si la foto no sirve."""
    anterior = profe.foto_id
    if _hay_archivo(form.foto):
        try:
            profe.foto_id = _guardar_imagen(form.foto.data, max_lado=800).id
        except ImagenInvalida as error:
            db.session.rollback()
            form.foto.errors.append(str(error))
            return False
    elif form.quitar_foto.data:
        profe.foto_id = None
    profe.nombre = form.nombre.data.strip()
    profe.titulo_profesional = (form.titulo_profesional.data or "").strip() or None
    profe.bio = (form.bio.data or "").strip() or None
    if anterior and anterior != profe.foto_id:
        db.session.flush()
        _borrar_si_huerfana(anterior)
    db.session.commit()
    return True


# ---------------------------------------------------------------- panel del dueño

@bp.route("/admin/profesores", methods=["GET", "POST"])
@admin_required
def administrar():
    form = NuevoProfeForm()
    if form.validate_on_submit():
        try:
            email = validate_email(form.email.data, check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            flash("Ese email no es válido.", "danger")
            return redirect(url_for("profes.administrar"))

        profe = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == email)
        ).scalar_one_or_none()
        nuevo = profe is None
        if nuevo:
            profe = Usuario(nombre=form.nombre.data.strip(), email=email)
            profe.establecer_password(secrets.token_urlsafe(32))
            db.session.add(profe)
        elif profe.es_profesor:
            flash(f"{profe.nombre} ya era profe.", "info")
            return redirect(url_for("profes.editar", usuario_id=profe.id))
        profe.es_profesor = True
        db.session.commit()

        flash(f"{profe.nombre} ahora es profe. Asignale sus cursos.", "success")
        if nuevo:
            invitacion = url_externa("resetear_password", token=generar_token_invitacion(email))
            flash(
                f"Le creamos la cuenta. Pasale este enlace para que elija su contraseña "
                f"(vence en 7 días): {invitacion}",
                "info",
            )
        return redirect(url_for("profes.editar", usuario_id=profe.id))

    return render_template("admin/profesores.html", profes=_profes_publicos(), form=form)


@bp.route("/admin/profesores/<int:usuario_id>/editar", methods=["GET", "POST"])
@admin_required
def editar(usuario_id):
    profe = db.session.get(Usuario, usuario_id)
    if profe is None or not profe.es_profesor:
        abort(404)
    cursos = db.session.execute(db.select(Curso).order_by(Curso.id)).scalars().all()
    form = PerfilProfeForm(obj=profe)
    if form.validate_on_submit():
        ids = {int(i) for i in request.form.getlist("curso_ids") if i.isdigit()}
        profe.cursos_dictados = [c for c in cursos if c.id in ids]
        if _guardar_perfil(profe, form):
            flash("Profe actualizado.", "success")
            return redirect(url_for("profes.administrar"))
    return render_template(
        "profe/perfil.html", form=form, profe=profe, cursos=cursos,
        titulo=f"Editar profe: {profe.nombre}",
    )


@bp.route("/admin/profesores/<int:usuario_id>/quitar", methods=["POST"])
@admin_required
def quitar(usuario_id):
    profe = db.session.get(Usuario, usuario_id)
    if profe is None or not profe.es_profesor:
        abort(404)
    profe.es_profesor = False
    profe.cursos_dictados = []
    db.session.commit()
    flash(f"{profe.nombre} ya no es profe. Su cuenta sigue activa como alumno.", "success")
    return redirect(url_for("profes.administrar"))
