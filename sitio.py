"""Contenido público del sitio y su panel de administración.

Fotos, testimonios, preguntas frecuentes y ajustes (todo editable por el dueño), páginas
legales, botón de arrepentimiento (Res. 424/2020), chequeo de salud y robots.txt.
"""
import logging
import re
import secrets
from io import BytesIO

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from werkzeug.utils import secure_filename

from ajustes import ajustes_sitio, contacto_email, guardar_ajustes, whatsapp_digitos
from db import db
from emailer import enviar_arrepentimiento
from extensions import limiter
from forms import ArrepentimientoForm, AjustesForm, FotoForm, PreguntaForm, TestimonioForm
from iconos import temas_portada
from imagenes import ImagenInvalida, procesar_imagen
from models import (
    Ajuste,
    Arrepentimiento,
    Foto,
    Imagen,
    PreguntaFrecuente,
    Testimonio,
    Usuario,
    ahora_argentina,
)
from utils import admin_required

log = logging.getLogger(__name__)
bp = Blueprint("sitio", __name__)

MAX_FOTOS = 40

# Se muestran en la portada mientras el dueño no cargue las suyas
PREGUNTAS_BASE = [
    ("¿Cómo me inscribo?",
     "Creás tu cuenta, elegís el curso y pagás con Mercado Pago. Cuando el pago se acredita, "
     "el curso aparece solo en «Mis inscripciones»."),
    ("¿Qué medios de pago aceptan?",
     "Los que ofrece Mercado Pago: tarjetas de crédito y débito, dinero en cuenta y otros medios disponibles "
     "en tu país. Si preferís pagar por transferencia o PayPal, escribinos y te damos el acceso a mano."),
    ("¿Las clases son en vivo o grabadas?",
     "Los cursos combinan las dos cosas: clases en vivo por Google Meet, con su horario en hora de Argentina, "
     "y clases grabadas que podés ver cuando quieras."),
    ("¿Qué pasa si no puedo asistir a una clase en vivo?",
     "Cuando una clase en vivo tiene grabación, la vas a ver en el mismo curso, junto al resto de las clases."),
    ("¿Puedo ver el curso desde el celular?",
     "Sí. La web funciona en cualquier celular, tablet o computadora: solo necesitás iniciar sesión."),
    ("¿Puedo pedir la devolución de mi compra?",
     "Sí. Tenés 10 días corridos desde la compra para arrepentirte, usando el botón de arrepentimiento "
     "que está al pie de la página."),
]


# ---------------------------------------------------------------------------
# Variables disponibles en todas las plantillas
# ---------------------------------------------------------------------------

def _usuario_instagram(valor):
    valor = (valor or "").strip().rstrip("/")
    if not valor:
        return ""
    ultimo = valor.split("/")[-1].lstrip("@")
    return ultimo if re.fullmatch(r"[A-Za-z0-9._]{1,30}", ultimo) else ""


@bp.app_context_processor
def inyectar_sitio():
    sitio = ajustes_sitio()
    wa = whatsapp_digitos(sitio.get("whatsapp"))
    ig = _usuario_instagram(sitio.get("instagram"))
    return {
        "sitio": sitio,
        "whatsapp_url": f"https://wa.me/{wa}" if wa else "",
        "instagram_url": f"https://instagram.com/{ig}" if ig else "",
        "instagram_usuario": ig,
        "contacto_email": contacto_email(),
        "anio_actual": ahora_argentina().year,
    }


def contenido_portada():
    """Testimonios, galería y preguntas visibles para la página de inicio."""
    testimonios = db.session.execute(
        db.select(Testimonio).where(Testimonio.visible.is_(True)).order_by(Testimonio.orden, Testimonio.id)
    ).scalars().all()
    fotos = db.session.execute(
        db.select(Foto).where(Foto.visible.is_(True)).order_by(Foto.orden, Foto.id)
    ).scalars().all()
    preguntas = db.session.execute(
        db.select(PreguntaFrecuente).where(PreguntaFrecuente.visible.is_(True))
        .order_by(PreguntaFrecuente.orden, PreguntaFrecuente.id)
    ).scalars().all()
    hay_propias = db.session.execute(db.select(db.func.count(PreguntaFrecuente.id))).scalar() > 0
    lista_preguntas = (
        [(p.pregunta, p.respuesta) for p in preguntas] if hay_propias else PREGUNTAS_BASE
    )
    return {"testimonios": testimonios, "fotos": fotos, "preguntas": lista_preguntas,
            "temas": temas_portada(ajustes_sitio().get("temas_portada"))}


# ---------------------------------------------------------------------------
# Imágenes
# ---------------------------------------------------------------------------

@bp.route("/media/<int:imagen_id>")
def media(imagen_id):
    imagen = db.session.get(Imagen, imagen_id)
    if imagen is None:
        abort(404)
    return send_file(
        BytesIO(imagen.datos),
        mimetype=imagen.mimetype,
        max_age=60 * 60 * 24 * 30,  # el id cambia cuando se reemplaza la foto
        etag=f"img-{imagen.id}-{len(imagen.datos)}",
        conditional=True,
    )


def _guardar_imagen(archivo, max_lado=1600):
    """Procesa y guarda una subida. Lanza ImagenInvalida si no sirve."""
    datos, mimetype, ancho, alto = procesar_imagen(archivo, max_lado=max_lado)
    imagen = Imagen(
        nombre=(secure_filename(archivo.filename or "") or "foto")[:160],
        mimetype=mimetype, datos=datos, ancho=ancho, alto=alto,
    )
    db.session.add(imagen)
    db.session.flush()
    return imagen


def _borrar_si_huerfana(imagen_id):
    """Elimina la imagen si ya nada la usa (para no acumular fotos viejas en la base)."""
    if not imagen_id:
        return
    imagen_id = int(imagen_id)
    usos = (
        db.session.query(Foto).filter_by(imagen_id=imagen_id).count()
        + db.session.query(Testimonio).filter_by(imagen_id=imagen_id).count()
        + db.session.query(Ajuste).filter(
            Ajuste.clave.in_(["entrenador_imagen_id", "portada_imagen_id"]),
            Ajuste.valor == str(imagen_id),
        ).count()
        + db.session.query(Usuario).filter_by(foto_id=imagen_id).count()
    )
    if usos == 0:
        imagen = db.session.get(Imagen, imagen_id)
        if imagen is not None:
            db.session.delete(imagen)


def _hay_archivo(campo):
    return bool(campo.data and getattr(campo.data, "filename", ""))


def _siguiente_orden(modelo):
    maximo = db.session.execute(db.select(db.func.max(modelo.orden))).scalar()
    return (maximo or 0) + 1


# ---------------------------------------------------------------------------
# Administración: ajustes del sitio
# ---------------------------------------------------------------------------

@bp.route("/admin/sitio", methods=["GET", "POST"])
@admin_required
def admin_sitio():
    actuales = ajustes_sitio()
    form = AjustesForm(data=actuales if request.method == "GET" else None)

    if form.validate_on_submit():
        nuevos = {
            clave: getattr(form, clave).data
            for clave in ("entrenador_nombre", "entrenador_titulo", "entrenador_bio", "whatsapp",
                          "instagram", "email_contacto", "legal_titular", "legal_cuit", "legal_domicilio",
                          "temas_portada")
        }
        try:
            for campo_archivo, campo_quitar, clave in (
                (form.foto_entrenador, form.quitar_foto_entrenador, "entrenador_imagen_id"),
                (form.imagen_portada, form.quitar_portada, "portada_imagen_id"),
            ):
                anterior = actuales.get(clave)
                if _hay_archivo(campo_archivo):
                    imagen = _guardar_imagen(campo_archivo.data, max_lado=2000 if clave == "portada_imagen_id" else 1200)
                    nuevos[clave] = str(imagen.id)
                elif campo_quitar.data:
                    nuevos[clave] = ""
                else:
                    continue
                guardar_ajustes({clave: nuevos[clave]})
                if anterior and anterior != nuevos[clave]:
                    _borrar_si_huerfana(anterior)
        except ImagenInvalida as error:
            db.session.rollback()
            flash(str(error), "danger")
            return render_template("admin/sitio_ajustes.html", form=form, seccion="ajustes")

        guardar_ajustes(nuevos)
        db.session.commit()
        flash("Ajustes guardados.", "success")
        return redirect(url_for("sitio.admin_sitio"))

    return render_template("admin/sitio_ajustes.html", form=form, seccion="ajustes")


# ---------------------------------------------------------------------------
# Administración: galería de fotos
# ---------------------------------------------------------------------------

@bp.route("/admin/sitio/fotos", methods=["GET", "POST"])
@admin_required
def admin_fotos():
    if request.method == "POST":
        archivos = [a for a in request.files.getlist("fotos") if a and a.filename]
        if not archivos:
            flash("Elegí al menos una foto.", "warning")
            return redirect(url_for("sitio.admin_fotos"))
        total = db.session.query(Foto).count()
        subidas = 0
        orden = _siguiente_orden(Foto)
        for archivo in archivos:
            if total + subidas >= MAX_FOTOS:
                flash(f"La galería admite hasta {MAX_FOTOS} fotos.", "warning")
                break
            try:
                imagen = _guardar_imagen(archivo)
            except ImagenInvalida as error:
                flash(f"{archivo.filename}: {error}", "danger")
                continue
            db.session.add(Foto(imagen_id=imagen.id, orden=orden + subidas))
            subidas += 1
        db.session.commit()
        if subidas:
            flash(f"{subidas} foto{'s' if subidas != 1 else ''} subida{'s' if subidas != 1 else ''}.", "success")
        return redirect(url_for("sitio.admin_fotos"))

    fotos = db.session.execute(db.select(Foto).order_by(Foto.orden, Foto.id)).scalars().all()
    return render_template("admin/sitio_fotos.html", fotos=fotos, seccion="fotos", maximo=MAX_FOTOS)


@bp.route("/admin/sitio/fotos/<int:foto_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_foto(foto_id):
    foto = db.session.get(Foto, foto_id)
    if foto is None:
        abort(404)
    form = FotoForm(obj=foto)
    if form.validate_on_submit():
        foto.pie = (form.pie.data or "").strip() or None
        foto.visible = form.visible.data
        if form.orden.data is not None:
            foto.orden = form.orden.data
        db.session.commit()
        flash("Foto actualizada.", "success")
        return redirect(url_for("sitio.admin_fotos"))
    return render_template("admin/sitio_foto_form.html", form=form, foto=foto, seccion="fotos")


@bp.route("/admin/sitio/fotos/<int:foto_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_foto(foto_id):
    foto = db.session.get(Foto, foto_id)
    if foto is None:
        abort(404)
    imagen_id = foto.imagen_id
    db.session.delete(foto)
    db.session.flush()
    _borrar_si_huerfana(imagen_id)
    db.session.commit()
    flash("Foto eliminada.", "success")
    return redirect(url_for("sitio.admin_fotos"))


# ---------------------------------------------------------------------------
# Administración: testimonios
# ---------------------------------------------------------------------------

@bp.route("/admin/sitio/testimonios")
@admin_required
def admin_testimonios():
    testimonios = db.session.execute(
        db.select(Testimonio).order_by(Testimonio.orden, Testimonio.id)
    ).scalars().all()
    return render_template("admin/sitio_testimonios.html", testimonios=testimonios, seccion="testimonios")


def _guardar_testimonio(testimonio, form):
    testimonio.nombre = form.nombre.data.strip()
    testimonio.detalle = (form.detalle.data or "").strip() or None
    testimonio.texto = form.texto.data.strip()
    testimonio.visible = form.visible.data
    testimonio.orden = form.orden.data if form.orden.data is not None else (testimonio.orden or _siguiente_orden(Testimonio))
    anterior = testimonio.imagen_id
    if _hay_archivo(form.foto):
        testimonio.imagen_id = _guardar_imagen(form.foto.data, max_lado=600).id
    elif form.quitar_foto.data:
        testimonio.imagen_id = None
    if anterior and anterior != testimonio.imagen_id:
        db.session.flush()
        _borrar_si_huerfana(anterior)


@bp.route("/admin/sitio/testimonios/nuevo", methods=["GET", "POST"])
@admin_required
def nuevo_testimonio():
    form = TestimonioForm()
    if request.method == "GET":
        form.orden.data = _siguiente_orden(Testimonio)
    if form.validate_on_submit():
        testimonio = Testimonio(nombre="", texto="")
        try:
            _guardar_testimonio(testimonio, form)
        except ImagenInvalida as error:
            db.session.rollback()
            flash(str(error), "danger")
            return render_template("admin/sitio_testimonio_form.html", form=form, titulo="Nuevo testimonio", seccion="testimonios")
        db.session.add(testimonio)
        db.session.commit()
        flash("Testimonio creado.", "success")
        return redirect(url_for("sitio.admin_testimonios"))
    return render_template("admin/sitio_testimonio_form.html", form=form, titulo="Nuevo testimonio", seccion="testimonios")


@bp.route("/admin/sitio/testimonios/<int:testimonio_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_testimonio(testimonio_id):
    testimonio = db.session.get(Testimonio, testimonio_id)
    if testimonio is None:
        abort(404)
    form = TestimonioForm(obj=testimonio)
    if form.validate_on_submit():
        try:
            _guardar_testimonio(testimonio, form)
        except ImagenInvalida as error:
            db.session.rollback()
            flash(str(error), "danger")
            return render_template("admin/sitio_testimonio_form.html", form=form, titulo="Editar testimonio",
                                   testimonio=testimonio, seccion="testimonios")
        db.session.commit()
        flash("Testimonio actualizado.", "success")
        return redirect(url_for("sitio.admin_testimonios"))
    return render_template("admin/sitio_testimonio_form.html", form=form, titulo="Editar testimonio",
                           testimonio=testimonio, seccion="testimonios")


@bp.route("/admin/sitio/testimonios/<int:testimonio_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_testimonio(testimonio_id):
    testimonio = db.session.get(Testimonio, testimonio_id)
    if testimonio is None:
        abort(404)
    imagen_id = testimonio.imagen_id
    db.session.delete(testimonio)
    db.session.flush()
    _borrar_si_huerfana(imagen_id)
    db.session.commit()
    flash("Testimonio eliminado.", "success")
    return redirect(url_for("sitio.admin_testimonios"))


# ---------------------------------------------------------------------------
# Administración: preguntas frecuentes
# ---------------------------------------------------------------------------

@bp.route("/admin/sitio/preguntas")
@admin_required
def admin_preguntas():
    preguntas = db.session.execute(
        db.select(PreguntaFrecuente).order_by(PreguntaFrecuente.orden, PreguntaFrecuente.id)
    ).scalars().all()
    return render_template("admin/sitio_preguntas.html", preguntas=preguntas, base=PREGUNTAS_BASE, seccion="preguntas")


def _guardar_pregunta(pregunta, form):
    pregunta.pregunta = form.pregunta.data.strip()
    pregunta.respuesta = form.respuesta.data.strip()
    pregunta.visible = form.visible.data
    pregunta.orden = form.orden.data if form.orden.data is not None else (pregunta.orden or _siguiente_orden(PreguntaFrecuente))


@bp.route("/admin/sitio/preguntas/nueva", methods=["GET", "POST"])
@admin_required
def nueva_pregunta():
    form = PreguntaForm()
    if request.method == "GET":
        form.orden.data = _siguiente_orden(PreguntaFrecuente)
    if form.validate_on_submit():
        pregunta = PreguntaFrecuente(pregunta="", respuesta="")
        _guardar_pregunta(pregunta, form)
        db.session.add(pregunta)
        db.session.commit()
        flash("Pregunta creada. Desde ahora la web muestra solo tus preguntas.", "success")
        return redirect(url_for("sitio.admin_preguntas"))
    return render_template("admin/sitio_pregunta_form.html", form=form, titulo="Nueva pregunta", seccion="preguntas")


@bp.route("/admin/sitio/preguntas/<int:pregunta_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_pregunta(pregunta_id):
    pregunta = db.session.get(PreguntaFrecuente, pregunta_id)
    if pregunta is None:
        abort(404)
    form = PreguntaForm(obj=pregunta)
    if form.validate_on_submit():
        _guardar_pregunta(pregunta, form)
        db.session.commit()
        flash("Pregunta actualizada.", "success")
        return redirect(url_for("sitio.admin_preguntas"))
    return render_template("admin/sitio_pregunta_form.html", form=form, titulo="Editar pregunta", seccion="preguntas")


@bp.route("/admin/sitio/preguntas/<int:pregunta_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_pregunta(pregunta_id):
    pregunta = db.session.get(PreguntaFrecuente, pregunta_id)
    if pregunta is None:
        abort(404)
    db.session.delete(pregunta)
    db.session.commit()
    flash("Pregunta eliminada.", "success")
    return redirect(url_for("sitio.admin_preguntas"))


@bp.route("/admin/sitio/preguntas/cargar-base", methods=["POST"])
@admin_required
def cargar_preguntas_base():
    """Copia las preguntas por defecto a la base para poder editarlas una por una."""
    if db.session.query(PreguntaFrecuente).count():
        flash("Ya tenés preguntas propias.", "warning")
        return redirect(url_for("sitio.admin_preguntas"))
    for numero, (pregunta, respuesta) in enumerate(PREGUNTAS_BASE, start=1):
        db.session.add(PreguntaFrecuente(pregunta=pregunta, respuesta=respuesta, orden=numero))
    db.session.commit()
    flash("Cargamos las preguntas de ejemplo: editalas a tu gusto.", "success")
    return redirect(url_for("sitio.admin_preguntas"))


# ---------------------------------------------------------------------------
# Páginas legales y botón de arrepentimiento
# ---------------------------------------------------------------------------

@bp.route("/terminos")
def terminos():
    return render_template("legal/terminos.html")


@bp.route("/privacidad")
def privacidad():
    return render_template("legal/privacidad.html")


@bp.route("/arrepentimiento", methods=["GET", "POST"])
@limiter.limit("6 per hour", methods=["POST"])
def arrepentimiento():
    """Botón de arrepentimiento: no pide cuenta ni inicio de sesión."""
    form = ArrepentimientoForm()
    if request.method == "GET" and current_user.is_authenticated:
        form.nombre.data = current_user.nombre
        form.email.data = current_user.email

    if form.validate_on_submit():
        solicitud = Arrepentimiento(
            codigo=secrets.token_hex(4).upper(),
            nombre=form.nombre.data.strip(),
            email=form.email.data.strip().lower(),
            referencia=(form.referencia.data or "").strip() or None,
            motivo=(form.motivo.data or "").strip() or None,
        )
        db.session.add(solicitud)
        db.session.commit()
        enviar_arrepentimiento(solicitud)
        return render_template("legal/arrepentimiento_ok.html", solicitud=solicitud)

    return render_template("legal/arrepentimiento.html", form=form)


@bp.route("/admin/arrepentimientos")
@admin_required
def admin_arrepentimientos():
    solicitudes = db.session.execute(
        db.select(Arrepentimiento).order_by(Arrepentimiento.id.desc())
    ).scalars().all()
    return render_template("admin/arrepentimientos.html", solicitudes=solicitudes, seccion="arrepentimientos")


@bp.route("/admin/arrepentimientos/<int:solicitud_id>/atender", methods=["POST"])
@admin_required
def atender_arrepentimiento(solicitud_id):
    solicitud = db.session.get(Arrepentimiento, solicitud_id)
    if solicitud is None:
        abort(404)
    solicitud.estado = "recibida" if solicitud.estado == "atendida" else "atendida"
    db.session.commit()
    return redirect(url_for("sitio.admin_arrepentimientos"))


# ---------------------------------------------------------------------------
# Infraestructura: salud y robots
# ---------------------------------------------------------------------------

@bp.route("/salud")
def salud():
    """Para el monitoreo del hosting: responde 200 si la app y la base andan."""
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        log.exception("Chequeo de salud: la base no responde")
        return jsonify(ok=False), 503
    return jsonify(ok=True)


@bp.route("/robots.txt")
def robots():
    texto = (
        "User-agent: *\n"
        "Disallow: /admin/\n"
        "Disallow: /curso/\n"
        "Disallow: /mis-inscripciones\n"
        "Disallow: /mi-cuenta\n"
        "Disallow: /webhooks/\n"
        "Disallow: /comprar/\n"
    )
    return Response(texto, mimetype="text/plain")
