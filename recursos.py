"""Recursos gratis: podcasts (episodios con reproductor) y biblioteca de libros con link a Mercado Libre."""
from urllib.parse import urlparse

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db import db
from forms import EpisodioForm, LibroForm
from imagenes import ImagenInvalida
from models import Episodio, Libro
from progreso import video_embed
from sitio import _borrar_si_huerfana, _guardar_imagen, _hay_archivo, _siguiente_orden
from utils import admin_required

bp = Blueprint("recursos", __name__)


# ---------------------------------------------------------------- links

def _host(url):
    try:
        return (urlparse((url or "").strip()).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def reproductor(url):
    """URL para un <iframe> si el episodio es de YouTube o Spotify; si no, None (se abre aparte)."""
    embed = video_embed(url)
    if embed:
        return embed
    if _host(url) == "open.spotify.com":
        partes = [p for p in urlparse(url).path.split("/") if p]
        # /episode/<id>, /show/<id> y también /intl-es/episode/<id>
        partes = [p for p in partes if not p.startswith("intl-")]
        if len(partes) >= 2 and partes[0] in ("episode", "show") and partes[1].isalnum():
            return f"https://open.spotify.com/embed/{partes[0]}/{partes[1]}"
    return None


PLATAFORMAS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube", "m.youtube.com": "YouTube",
    "open.spotify.com": "Spotify", "ivoox.com": "iVoox", "podcasts.apple.com": "Apple Podcasts",
    "soundcloud.com": "SoundCloud",
}


def plataforma(url):
    return PLATAFORMAS.get(_host(url), "la web del podcast")


def es_mercado_libre(url):
    host = _host(url)
    return host == "meli.la" or any(
        host == d or host.endswith("." + d) for d in ("mercadolibre.com.ar", "mercadolibre.com")
    )


@bp.app_context_processor
def ayudantes():
    return {"reproductor_podcast": reproductor, "plataforma_podcast": plataforma, "es_mercado_libre": es_mercado_libre}


# ---------------------------------------------------------------- consultas

def episodios_visibles():
    return db.session.execute(
        db.select(Episodio).where(Episodio.visible.is_(True))
        .order_by(Episodio.fecha.is_(None), Episodio.fecha.desc(), Episodio.id.desc())
    ).scalars().all()


def libros_visibles():
    return db.session.execute(
        db.select(Libro).where(Libro.visible.is_(True)).order_by(Libro.orden, Libro.id)
    ).scalars().all()


def ultimo_episodio():
    """El episodio visible más reciente, para destacarlo en la portada (o None)."""
    return db.session.execute(
        db.select(Episodio).where(Episodio.visible.is_(True))
        .order_by(Episodio.fecha.is_(None), Episodio.fecha.desc(), Episodio.id.desc()).limit(1)
    ).scalar_one_or_none()


def cantidades():
    """Para la portada: qué recursos mostrar."""
    contar = lambda modelo: db.session.execute(  # noqa: E731
        db.select(db.func.count(modelo.id)).where(modelo.visible.is_(True))).scalar()
    return {"podcasts": contar(Episodio), "libros": contar(Libro)}


# ---------------------------------------------------------------- páginas públicas

@bp.route("/podcasts")
def podcasts():
    return render_template("recursos/podcasts.html", episodios=episodios_visibles())


@bp.route("/biblioteca")
def biblioteca():
    libros = libros_visibles()
    temas = sorted({libro.tema for libro in libros if libro.tema}, key=str.lower)
    tema = request.args.get("tema")
    if tema:
        libros = [libro for libro in libros if (libro.tema or "").lower() == tema.lower()]
    return render_template("recursos/biblioteca.html", libros=libros, temas=temas, tema=tema)


# ---------------------------------------------------------------- panel: podcasts

def _obtener(modelo, objeto_id):
    objeto = db.session.get(modelo, objeto_id)
    if objeto is None:
        abort(404)
    return objeto


@bp.route("/admin/podcasts")
@admin_required
def admin_podcasts():
    episodios = db.session.execute(
        db.select(Episodio).order_by(Episodio.fecha.is_(None), Episodio.fecha.desc(), Episodio.id.desc())
    ).scalars().all()
    return render_template("admin/podcasts.html", episodios=episodios)


def _guardar_episodio(episodio, form):
    episodio.titulo = form.titulo.data.strip()
    episodio.url = form.url.data.strip()
    episodio.descripcion = (form.descripcion.data or "").strip() or None
    episodio.duracion_min = form.duracion_min.data
    episodio.fecha = form.fecha.data
    episodio.visible = form.visible.data


@bp.route("/admin/podcasts/nuevo", methods=["GET", "POST"])
@bp.route("/admin/podcasts/<int:episodio_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_episodio(episodio_id=None):
    episodio = _obtener(Episodio, episodio_id) if episodio_id else None
    form = EpisodioForm(obj=episodio)
    if form.validate_on_submit():
        if episodio is None:
            episodio = Episodio()
            db.session.add(episodio)
        _guardar_episodio(episodio, form)
        db.session.commit()
        aviso = "" if reproductor(episodio.url) else " Ese link se va a abrir aparte (no se reproduce dentro de la web)."
        flash("Episodio guardado." + aviso, "success")
        return redirect(url_for("recursos.admin_podcasts"))
    return render_template("admin/episodio_form.html", form=form, episodio=episodio,
                           titulo="Editar episodio" if episodio else "Nuevo episodio")


@bp.route("/admin/podcasts/<int:episodio_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_episodio(episodio_id):
    db.session.delete(_obtener(Episodio, episodio_id))
    db.session.commit()
    flash("Episodio eliminado.", "success")
    return redirect(url_for("recursos.admin_podcasts"))


# ---------------------------------------------------------------- panel: biblioteca

@bp.route("/admin/biblioteca")
@admin_required
def admin_biblioteca():
    libros = db.session.execute(db.select(Libro).order_by(Libro.orden, Libro.id)).scalars().all()
    return render_template("admin/biblioteca.html", libros=libros)


def _guardar_libro(libro, form):
    libro.titulo = form.titulo.data.strip()
    libro.autor = (form.autor.data or "").strip() or None
    libro.tema = (form.tema.data or "").strip() or None
    libro.url = form.url.data.strip()
    libro.descripcion = (form.descripcion.data or "").strip() or None
    libro.visible = form.visible.data
    libro.orden = form.orden.data if form.orden.data is not None else (libro.orden or _siguiente_orden(Libro))
    anterior = libro.imagen_id
    if _hay_archivo(form.foto):
        libro.imagen_id = _guardar_imagen(form.foto.data, max_lado=800).id
    elif form.quitar_foto.data:
        libro.imagen_id = None
    if anterior and anterior != libro.imagen_id:
        db.session.flush()
        _borrar_si_huerfana(anterior)


@bp.route("/admin/biblioteca/nuevo", methods=["GET", "POST"])
@bp.route("/admin/biblioteca/<int:libro_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_libro(libro_id=None):
    libro = _obtener(Libro, libro_id) if libro_id else None
    form = LibroForm(obj=libro)
    if request.method == "GET" and libro is None:
        form.orden.data = _siguiente_orden(Libro)
    titulo = "Editar libro" if libro else "Nuevo libro"
    if form.validate_on_submit():
        nuevo = libro is None
        if nuevo:
            libro = Libro(titulo="", url="")
            db.session.add(libro)
        try:
            _guardar_libro(libro, form)
        except ImagenInvalida as error:
            db.session.rollback()
            flash(str(error), "danger")
            return render_template("admin/libro_form.html", form=form, libro=None if nuevo else libro, titulo=titulo)
        db.session.commit()
        aviso = "" if es_mercado_libre(libro.url) else " Ojo: el link no es de Mercado Libre."
        flash("Libro guardado." + aviso, "success" if not aviso else "warning")
        return redirect(url_for("recursos.admin_biblioteca"))
    return render_template("admin/libro_form.html", form=form, libro=libro, titulo=titulo)


@bp.route("/admin/biblioteca/<int:libro_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_libro(libro_id):
    libro = _obtener(Libro, libro_id)
    imagen_id = libro.imagen_id
    db.session.delete(libro)
    db.session.flush()
    _borrar_si_huerfana(imagen_id)
    db.session.commit()
    flash("Libro eliminado.", "success")
    return redirect(url_for("recursos.admin_biblioteca"))
