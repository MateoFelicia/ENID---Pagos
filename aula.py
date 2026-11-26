"""Aula: página de cada clase con sus partes, progreso del alumno y
administración de módulos y partes."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from db import db
from forms import ModuloForm, ParteForm
from models import Clase, Curso, Modulo, Parte, ahora_argentina
from progreso import armar_aula, avance_clase, marcar, video_embed, vistos
from utils import admin_required, tiene_acceso_curso

bp = Blueprint("aula", __name__)


@bp.app_template_filter("video_embed")
def _filtro_video_embed(url):
    return video_embed(url)


def _clase_visible(curso_id, clase_id):
    """La clase, si existe, pertenece al curso y el usuario puede verla; si no, aborta."""
    curso = db.session.get(Curso, curso_id)
    clase = db.session.get(Clase, clase_id)
    if curso is None or clase is None or clase.curso_id != curso.id:
        abort(404)
    if not clase.publicada and not current_user.es_admin:
        abort(404)
    return curso, clase


# ---------------------------------------------------------------- alumno

@bp.route("/curso/<int:curso_id>/clase/<int:clase_id>")
@login_required
def ver_clase(curso_id, clase_id):
    curso, clase = _clase_visible(curso_id, clase_id)
    if not tiene_acceso_curso(current_user, curso):
        flash("No tenés acceso a este curso.", "warning")
        return redirect(url_for("mis_inscripciones"))

    parte = None
    if clase.partes:
        pedido = request.args.get("parte", type=int)
        parte = next((p for p in clase.partes if p.id == pedido), None) or clase.partes[0]

    hechos = vistos(current_user, curso)
    clases = [c for c in curso.clases if c.publicada or current_user.es_admin]
    grupos, por_clase, total = armar_aula(curso, clases, hechos)

    # Anterior / siguiente siguiendo el orden en que se muestra el aula
    orden = [c for g in grupos for c in g.clases]
    i = orden.index(clase) if clase in orden else -1
    anterior = orden[i - 1] if i > 0 else None
    siguiente = orden[i + 1] if 0 <= i < len(orden) - 1 else None

    video = parte.video_url if parte else clase.grabacion
    return render_template(
        "clase.html",
        curso=curso, clase=clase, parte=parte, hechos=hechos,
        grupos=grupos, por_clase=por_clase, total=total,
        avance=avance_clase(clase, hechos),
        video=video, embed=video_embed(video),
        anterior=anterior, siguiente=siguiente,
        ahora=ahora_argentina(),
    )


@bp.route("/curso/<int:curso_id>/clase/<int:clase_id>/visto", methods=["POST"])
@login_required
def marcar_visto(curso_id, clase_id):
    curso, clase = _clase_visible(curso_id, clase_id)
    if not tiene_acceso_curso(current_user, curso):
        abort(403)
    parte = None
    parte_id = request.form.get("parte_id", type=int)
    if parte_id:
        parte = db.session.get(Parte, parte_id)
        if parte is None or parte.clase_id != clase.id:
            abort(404)
    visto = request.form.get("visto", "1") == "1"
    marcar(current_user, clase, parte, visto)

    # Al marcar una parte como vista, pasa sola a la siguiente
    destino = parte.id if parte else None
    if visto and parte:
        siguientes = [p for p in clase.partes if p.orden > parte.orden or (p.orden == parte.orden and p.id > parte.id)]
        if siguientes:
            destino = siguientes[0].id
    return redirect(url_for("aula.ver_clase", curso_id=curso.id, clase_id=clase.id, parte=destino))


# ---------------------------------------------------------------- admin: módulos

def _curso_o_404(curso_id):
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        abort(404)
    return curso


@bp.route("/admin/cursos/<int:curso_id>/modulos/nuevo", methods=["GET", "POST"])
@admin_required
def nuevo_modulo(curso_id):
    curso = _curso_o_404(curso_id)
    form = ModuloForm()
    siguiente = max((m.orden for m in curso.modulos), default=0) + 1
    if request.method == "GET":
        form.orden.data = siguiente
    if form.validate_on_submit():
        modulo = Modulo(curso=curso, orden=form.orden.data if form.orden.data is not None else siguiente)
        _guardar_modulo(modulo, form)
        db.session.add(modulo)
        db.session.commit()
        flash("Módulo creado. Ahora podés asignarle clases desde cada clase.", "success")
        return redirect(url_for("administrar_clases", curso_id=curso.id))
    return render_template("admin/modulo_form.html", form=form, curso=curso, titulo="Nuevo módulo")


@bp.route("/admin/modulos/<int:modulo_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_modulo(modulo_id):
    modulo = db.session.get(Modulo, modulo_id) or abort(404)
    form = ModuloForm(obj=modulo)
    if form.validate_on_submit():
        _guardar_modulo(modulo, form)
        db.session.commit()
        flash("Módulo actualizado.", "success")
        return redirect(url_for("administrar_clases", curso_id=modulo.curso_id))
    return render_template("admin/modulo_form.html", form=form, curso=modulo.curso, titulo="Editar módulo")


@bp.route("/admin/modulos/<int:modulo_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_modulo(modulo_id):
    modulo = db.session.get(Modulo, modulo_id) or abort(404)
    curso_id = modulo.curso_id
    for clase in list(modulo.clases):
        clase.modulo_id = None  # las clases no se borran: quedan sin módulo
    db.session.delete(modulo)
    db.session.commit()
    flash("Módulo eliminado. Sus clases quedaron sin módulo.", "success")
    return redirect(url_for("administrar_clases", curso_id=curso_id))


def _guardar_modulo(modulo, form):
    modulo.titulo = form.titulo.data.strip()
    modulo.descripcion = (form.descripcion.data or "").strip() or None
    if form.orden.data is not None:
        modulo.orden = form.orden.data


# ---------------------------------------------------------------- admin: partes

@bp.route("/admin/clases/<int:clase_id>/partes")
@admin_required
def administrar_partes(clase_id):
    clase = db.session.get(Clase, clase_id) or abort(404)
    return render_template("admin/partes.html", clase=clase, curso=clase.curso)


@bp.route("/admin/clases/<int:clase_id>/partes/nueva", methods=["GET", "POST"])
@admin_required
def nueva_parte(clase_id):
    clase = db.session.get(Clase, clase_id) or abort(404)
    form = ParteForm()
    siguiente = max((p.orden for p in clase.partes), default=0) + 1
    if request.method == "GET":
        form.orden.data = siguiente
        form.titulo.data = f"Parte {len(clase.partes) + 1}"
    if form.validate_on_submit():
        parte = Parte(clase=clase, orden=siguiente)
        _guardar_parte(parte, form)
        db.session.add(parte)
        db.session.commit()
        flash("Parte agregada.", "success")
        if request.form.get("otra"):
            return redirect(url_for("aula.nueva_parte", clase_id=clase.id))
        return redirect(url_for("aula.administrar_partes", clase_id=clase.id))
    return render_template("admin/parte_form.html", form=form, clase=clase, titulo="Nueva parte")


@bp.route("/admin/partes/<int:parte_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_parte(parte_id):
    parte = db.session.get(Parte, parte_id) or abort(404)
    form = ParteForm(obj=parte)
    if form.validate_on_submit():
        _guardar_parte(parte, form)
        db.session.commit()
        flash("Parte actualizada.", "success")
        return redirect(url_for("aula.administrar_partes", clase_id=parte.clase_id))
    return render_template("admin/parte_form.html", form=form, clase=parte.clase, titulo="Editar parte")


@bp.route("/admin/partes/<int:parte_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_parte(parte_id):
    parte = db.session.get(Parte, parte_id) or abort(404)
    clase_id = parte.clase_id
    db.session.delete(parte)
    db.session.commit()
    flash("Parte eliminada.", "success")
    return redirect(url_for("aula.administrar_partes", clase_id=clase_id))


def _guardar_parte(parte, form):
    parte.titulo = form.titulo.data.strip()
    parte.video_url = (form.video_url.data or "").strip() or None
    parte.duracion_min = form.duracion_min.data
    if form.orden.data is not None:
        parte.orden = form.orden.data
