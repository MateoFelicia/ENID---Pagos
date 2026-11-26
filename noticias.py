"""Noticias del sitio y newsletter por mail.

- /noticias y /noticias/<id>-<slug>: lo publicado, para cualquiera.
- Suscripción con doble opt-in: el mail queda pendiente hasta que la persona toca el
  enlace de confirmación. Así nadie anota mails ajenos y se cumple la Ley 25.326.
- El dueño escribe noticias en el panel y elige cuáles mandar por mail (una sola vez cada una).
"""
import csv
import io

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from db import db
from emailer import _renderizar, enviar_email, enviar_varios, url_externa
from extensions import limiter
from forms import NoticiaForm
from imagenes import ImagenInvalida
from models import Noticia, Suscriptor, ahora_argentina
from sitio import _borrar_si_huerfana, _guardar_imagen, _hay_archivo
from utils import admin_required


bp = Blueprint("noticias", __name__)

POR_PAGINA = 9
SIETE_DIAS = 7 * 24 * 3600


# ---------------------------------------------------------------- tokens

def _firmador():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def token_confirmacion(email):
    return _firmador().dumps(email, salt="newsletter-confirmar")


def token_baja(email):
    return _firmador().dumps(email, salt="newsletter-baja")


def _leer(token, salt, max_age=None):
    try:
        return _firmador().loads(token, salt=salt, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def _suscriptor(email):
    return db.session.execute(db.select(Suscriptor).where(Suscriptor.email == email)).scalar_one_or_none()


# ---------------------------------------------------------------- consultas

def publicadas():
    return db.select(Noticia).where(Noticia.publicada.is_(True)).order_by(
        Noticia.publicada_en.desc(), Noticia.id.desc())


def ultimas(cantidad=3):
    return db.session.execute(publicadas().limit(cantidad)).scalars().all()


# ---------------------------------------------------------------- páginas públicas

@bp.route("/noticias")
def listado():
    pagina = db.paginate(publicadas(), page=request.args.get("pagina", 1, type=int),
                         per_page=POR_PAGINA, error_out=False)
    return render_template("noticias/listado.html", pagina=pagina)


@bp.route("/noticias/<int:noticia_id>")
@bp.route("/noticias/<int:noticia_id>-<slug>")
def ver(noticia_id, slug=None):
    noticia = db.session.get(Noticia, noticia_id)
    es_admin = current_user.is_authenticated and current_user.es_admin
    if noticia is None or (not noticia.publicada and not es_admin):
        abort(404)
    if noticia.publicada and slug != noticia.slug:
        return redirect(url_for("noticias.ver", noticia_id=noticia.id, slug=noticia.slug), 301)
    otras = db.session.execute(publicadas().where(Noticia.id != noticia.id).limit(3)).scalars().all()
    return render_template("noticias/ver.html", noticia=noticia, otras=otras)


# ---------------------------------------------------------------- newsletter

@bp.route("/newsletter", methods=["POST"])
@limiter.limit("8 per hour")
def suscribirse():
    volver = request.form.get("volver") or url_for("noticias.listado")
    if not volver.startswith("/") or volver.startswith("//"):
        volver = url_for("noticias.listado")

    # Campo trampa: las personas no lo ven; los robots lo completan
    if request.form.get("sitio_web"):
        return redirect(volver)

    try:
        email = validate_email(request.form.get("email", ""), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        flash("Revisá el mail: no parece válido.", "warning")
        return redirect(volver)

    suscriptor = _suscriptor(email)
    if suscriptor is None:
        suscriptor = Suscriptor(email=email)
        db.session.add(suscriptor)
    if not suscriptor.activo:
        suscriptor.confirmado = False
        suscriptor.baja_en = None
        db.session.commit()
        html = _renderizar("newsletter_confirmar",
                           url_confirmar=url_externa("noticias.confirmar", token=token_confirmacion(email)))
        enviar_email(email, "Confirmá tu suscripción a las novedades de ENID", html)

    # Mismo mensaje siempre: no revela si el mail ya estaba anotado
    flash("¡Listo! Te mandamos un mail para confirmar la suscripción. Si no lo ves, revisá spam.", "success")
    return redirect(volver)


@bp.route("/newsletter/confirmar/<token>")
def confirmar(token):
    email = _leer(token, "newsletter-confirmar", max_age=SIETE_DIAS)
    suscriptor = _suscriptor(email) if email else None
    if suscriptor is None:
        flash("El enlace venció o no es válido. Anotate de nuevo y te mandamos otro.", "warning")
        return redirect(url_for("noticias.listado"))
    if not suscriptor.activo:
        suscriptor.confirmado = True
        suscriptor.confirmado_en = ahora_argentina()
        suscriptor.baja_en = None
        db.session.commit()
    flash("Suscripción confirmada. Te vamos a avisar de las novedades de ENID.", "success")
    return redirect(url_for("noticias.listado"))


@bp.route("/newsletter/baja/<token>", methods=["GET", "POST"])
def baja(token):
    """GET muestra un botón; POST da de baja. (Algunos antivirus abren los enlaces de los
    mails solos: si la baja fuera con GET, darían de baja a la gente sin querer.)"""
    email = _leer(token, "newsletter-baja")
    suscriptor = _suscriptor(email) if email else None
    if suscriptor is None:
        abort(404)
    if request.method == "POST":
        if suscriptor.baja_en is None:
            suscriptor.baja_en = ahora_argentina()
            db.session.commit()
        return render_template("noticias/baja.html", email=email, hecha=True)
    return render_template("noticias/baja.html", email=email, hecha=suscriptor.baja_en is not None)


# ---------------------------------------------------------------- panel: noticias

@bp.route("/admin/noticias")
@admin_required
def administrar():
    noticias = db.session.execute(
        db.select(Noticia).order_by(Noticia.creada_en.desc(), Noticia.id.desc())
    ).scalars().all()
    activos = db.session.execute(
        db.select(db.func.count(Suscriptor.id)).where(Suscriptor.confirmado.is_(True), Suscriptor.baja_en.is_(None))
    ).scalar()
    return render_template("admin/noticias.html", noticias=noticias, activos=activos)


def _guardar_noticia(noticia, form):
    noticia.titulo = form.titulo.data.strip()
    noticia.resumen = (form.resumen.data or "").strip() or None
    noticia.cuerpo = form.cuerpo.data.strip()
    if form.publicada.data and not noticia.publicada:
        noticia.publicada_en = ahora_argentina()
    noticia.publicada = form.publicada.data
    anterior = noticia.imagen_id
    if _hay_archivo(form.foto):
        noticia.imagen_id = _guardar_imagen(form.foto.data, max_lado=1600).id
    elif form.quitar_foto.data:
        noticia.imagen_id = None
    if anterior and anterior != noticia.imagen_id:
        db.session.flush()
        _borrar_si_huerfana(anterior)


def _formulario(form, titulo, noticia=None):
    return render_template("admin/noticia_form.html", form=form, titulo=titulo, noticia=noticia)


@bp.route("/admin/noticias/nueva", methods=["GET", "POST"])
@admin_required
def nueva():
    form = NoticiaForm()
    if form.validate_on_submit():
        noticia = Noticia(titulo="", cuerpo="")
        db.session.add(noticia)
        try:
            _guardar_noticia(noticia, form)
        except ImagenInvalida as error:
            db.session.rollback()
            flash(str(error), "danger")
            return _formulario(form, "Nueva noticia")
        db.session.commit()
        flash("Noticia guardada.", "success")
        return redirect(url_for("noticias.administrar"))
    return _formulario(form, "Nueva noticia")


def _noticia_o_404(noticia_id):
    noticia = db.session.get(Noticia, noticia_id)
    if noticia is None:
        abort(404)
    return noticia


@bp.route("/admin/noticias/<int:noticia_id>/editar", methods=["GET", "POST"])
@admin_required
def editar(noticia_id):
    noticia = _noticia_o_404(noticia_id)
    form = NoticiaForm(obj=noticia)
    if form.validate_on_submit():
        try:
            _guardar_noticia(noticia, form)
        except ImagenInvalida as error:
            db.session.rollback()
            flash(str(error), "danger")
            return _formulario(form, "Editar noticia", noticia)
        db.session.commit()
        flash("Noticia actualizada.", "success")
        return redirect(url_for("noticias.administrar"))
    return _formulario(form, "Editar noticia", noticia)


@bp.route("/admin/noticias/<int:noticia_id>/eliminar", methods=["POST"])
@admin_required
def eliminar(noticia_id):
    noticia = _noticia_o_404(noticia_id)
    imagen_id = noticia.imagen_id
    db.session.delete(noticia)
    db.session.flush()
    _borrar_si_huerfana(imagen_id)
    db.session.commit()
    flash("Noticia eliminada.", "success")
    return redirect(url_for("noticias.administrar"))


def armar_mail_noticia(noticia, email):
    html = _renderizar(
        "noticia", noticia=noticia,
        url_noticia=url_externa("noticias.ver", noticia_id=noticia.id, slug=noticia.slug),
        url_imagen=url_externa("sitio.media", imagen_id=noticia.imagen_id) if noticia.imagen_id else None,
        baja_url=url_externa("noticias.baja", token=token_baja(email)),
        texto_baja="Recibís este mail porque te suscribiste a las novedades de ENID.",
        texto_link_baja="Darme de baja",
    )
    return (email, noticia.titulo, html)


@bp.route("/admin/noticias/<int:noticia_id>/enviar", methods=["POST"])
@admin_required
def enviar(noticia_id):
    noticia = _noticia_o_404(noticia_id)
    if not noticia.publicada:
        flash("Publicá la noticia antes de mandarla por mail.", "warning")
        return redirect(url_for("noticias.administrar"))
    if noticia.enviada_en is not None:
        flash("Esa noticia ya se mandó por mail.", "warning")
        return redirect(url_for("noticias.administrar"))

    emails = db.session.execute(
        db.select(Suscriptor.email).where(Suscriptor.confirmado.is_(True), Suscriptor.baja_en.is_(None))
    ).scalars().all()
    if not emails:
        flash("Todavía no hay suscriptores confirmados.", "warning")
        return redirect(url_for("noticias.administrar"))

    # Se marca antes de enviar: si alguien hace doble clic, no sale dos veces
    noticia.enviada_en = ahora_argentina()
    noticia.enviada_a = len(emails)
    db.session.commit()
    enviados = enviar_varios([armar_mail_noticia(noticia, e) for e in emails])
    flash(f"Noticia enviada a {enviados} suscriptor{'' if enviados == 1 else 'es'}.", "success")
    return redirect(url_for("noticias.administrar"))


# ---------------------------------------------------------------- panel: suscriptores

@bp.route("/admin/suscriptores")
@admin_required
def suscriptores():
    lista = db.session.execute(db.select(Suscriptor).order_by(Suscriptor.creado_en.desc())).scalars().all()
    if request.args.get("formato") == "csv":
        salida = io.StringIO()
        escritor = csv.writer(salida)
        escritor.writerow(["email", "estado", "anotado", "confirmado"])
        for s in lista:
            estado = "activo" if s.activo else ("baja" if s.baja_en else "sin confirmar")
            escritor.writerow([s.email, estado, s.creado_en or "", s.confirmado_en or ""])
        return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=suscriptores.csv"})
    return render_template("admin/suscriptores.html", suscriptores=lista)


@bp.route("/admin/suscriptores/<int:suscriptor_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_suscriptor(suscriptor_id):
    suscriptor = db.session.get(Suscriptor, suscriptor_id)
    if suscriptor is None:
        abort(404)
    db.session.delete(suscriptor)
    db.session.commit()
    flash("Suscriptor eliminado.", "success")
    return redirect(url_for("noticias.suscriptores"))
