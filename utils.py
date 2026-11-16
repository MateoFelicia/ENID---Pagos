"""Utilidades de rutas compartidas por app.py y los blueprints."""
from functools import wraps

from flask import abort, request, url_for
from flask_login import current_user, login_required

from db import db
from models import Inscripcion


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not current_user.es_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def destino_seguro(por_defecto="inicio"):
    """Devuelve el parámetro ?next= solo si es una ruta interna (evita open redirect)."""
    destino = request.args.get("next") or request.form.get("next") or ""
    if destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return url_for(por_defecto)


def inscripcion_con_acceso(usuario, curso):
    """Primera inscripción del usuario a ese curso que da acceso (o None)."""
    inscripciones = db.session.execute(
        db.select(Inscripcion).where(
            Inscripcion.usuario_id == usuario.id,
            Inscripcion.curso_id == curso.id,
        )
    ).scalars().all()
    return next((i for i in inscripciones if i.tiene_acceso()), None)


def tiene_acceso_curso(usuario, curso):
    if usuario.es_admin:
        return True
    return inscripcion_con_acceso(usuario, curso) is not None
