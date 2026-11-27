"""Recursos gratis: podcasts con reproductor y biblioteca con links a Mercado Libre."""
import io

from conftest import ctx
from db import db
from models import Episodio, Imagen, Libro
from recursos import es_mercado_libre, plataforma, reproductor

ML = "https://articulo.mercadolibre.com.ar/MLA-123456-la-pizarra-del-dt-_JM"


def nuevo_episodio(cliente_admin, **datos):
    data = {"titulo": "Episodio 1 · La presión", "url": "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk",
            "fecha": "2026-11-20", "duracion_min": "35", "visible": "y"}
    data.update(datos)
    return cliente_admin.post("/admin/podcasts/nuevo", data=data, follow_redirects=True)


def nuevo_libro(cliente_admin, **datos):
    data = {"titulo": "La pizarra del DT", "autor": "Autor de prueba", "tema": "Táctica", "url": ML, "visible": "y"}
    data.update(datos)
    return cliente_admin.post("/admin/biblioteca/nuevo", data=data, content_type="multipart/form-data",
                              follow_redirects=True)


# ---------------------------------------------------------------- links

def test_reproductores_y_plataformas():
    assert reproductor("https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk?si=x") == \
        "https://open.spotify.com/embed/episode/4rOoJ6Egrf8K2IrywzwOMk"
    assert reproductor("https://open.spotify.com/intl-es/show/abc123") == "https://open.spotify.com/embed/show/abc123"
    assert reproductor("https://youtu.be/dQw4w9WgXcQ") == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    assert reproductor("https://www.ivoox.com/episodio_rf_1.html") is None
    assert plataforma("https://www.ivoox.com/x") == "iVoox"


def test_reconoce_links_de_mercado_libre():
    assert es_mercado_libre(ML) and es_mercado_libre("https://meli.la/2abc")
    assert es_mercado_libre("https://listado.mercadolibre.com.ar/libro-futbol")
    assert not es_mercado_libre("https://mercadolibre.com.ar.estafa.com/x")
    assert not es_mercado_libre("https://www.amazon.com/x")


# ---------------------------------------------------------------- podcasts

def test_episodio_de_spotify_se_escucha_en_la_web(cliente_admin, cliente):
    assert "Episodio guardado." in nuevo_episodio(cliente_admin).get_data(as_text=True)
    html = cliente.get("/podcasts").get_data(as_text=True)
    assert "Episodio 1 · La presión" in html and "open.spotify.com/embed/episode/" in html and "35 min" in html


def test_episodio_de_otra_plataforma_se_abre_aparte(cliente_admin, cliente):
    r = nuevo_episodio(cliente_admin, url="https://www.ivoox.com/episodio_rf_1.html")
    assert "se va a abrir aparte" in r.get_data(as_text=True)
    assert "Escuchar en iVoox" in cliente.get("/podcasts").get_data(as_text=True)


def test_episodio_oculto_o_link_peligroso(cliente_admin, cliente):
    r = nuevo_episodio(cliente_admin, url="javascript:alert(1)")
    assert "tiene que empezar con http" in r.get_data(as_text=True)
    nuevo_episodio(cliente_admin, titulo="Oculto", visible="")
    assert "Oculto" not in cliente.get("/podcasts").get_data(as_text=True)


def test_portada_destaca_el_ultimo_episodio(cliente_admin, cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert 'id="podcast"' not in html and 'id="recursos"' not in html and "ESCUCHAR PODCASTS" not in html
    assert 'href="/podcasts">Podcasts</a>' in html  # el menú siempre lleva a los podcasts

    nuevo_episodio(cliente_admin, titulo="Viejo", fecha="2026-10-01")
    nuevo_episodio(cliente_admin)
    nuevo_episodio(cliente_admin, titulo="Borrador", fecha="2026-12-31", visible="")
    html = cliente.get("/").get_data(as_text=True)
    seccion = html.split('id="podcast"')[1].split("</section>")[0]
    assert "Episodio 1 · La presión" in seccion and "open.spotify.com/embed/episode/" in seccion
    assert 'href="#podcast"' in html  # botón en la portada
    assert "Viejo" not in seccion and "Borrador" not in seccion and "Ver todos los episodios (2)" in seccion
    assert 'id="recursos"' not in html  # sin libros no hay sección de biblioteca

    nuevo_libro(cliente_admin)
    assert "Biblioteca</strong>" in cliente.get("/").get_data(as_text=True)


# ---------------------------------------------------------------- biblioteca

def test_libro_con_link_a_mercado_libre_y_filtro_por_tema(cliente_admin, cliente):
    nuevo_libro(cliente_admin)
    nuevo_libro(cliente_admin, titulo="Cabeza fría", tema="Psicología")
    html = cliente.get("/biblioteca").get_data(as_text=True)
    assert "Comprar en Mercado Libre" in html and 'rel="noopener noreferrer nofollow"' in html
    assert "La pizarra del DT" in html and "Cabeza fría" in html
    filtrado = cliente.get("/biblioteca?tema=psicología").get_data(as_text=True)
    assert "Cabeza fría" in filtrado and "La pizarra del DT" not in filtrado


def test_link_que_no_es_de_mercado_libre_avisa(cliente_admin, cliente):
    r = nuevo_libro(cliente_admin, url="https://www.amazon.com/libro")
    assert "no es de Mercado Libre" in r.get_data(as_text=True)
    assert "Ver dónde comprarlo" in cliente.get("/biblioteca").get_data(as_text=True)


def test_tapa_se_guarda_y_se_borra_con_el_libro(cliente_admin):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (300, 450), (10, 20, 30)).save(buf, "PNG")
    nuevo_libro(cliente_admin, foto=(io.BytesIO(buf.getvalue()), "tapa.png"))
    with ctx():
        libro = db.session.query(Libro).one()
        assert libro.imagen_id is not None and db.session.query(Imagen).count() == 1
        lid = libro.id
    cliente_admin.post(f"/admin/biblioteca/{lid}/eliminar")
    with ctx():
        assert db.session.query(Libro).count() == 0 and db.session.query(Imagen).count() == 0


def test_alumno_no_administra_recursos(cliente_alumno):
    for ruta in ("/admin/podcasts", "/admin/podcasts/nuevo", "/admin/biblioteca", "/admin/biblioteca/nuevo"):
        assert cliente_alumno.get(ruta).status_code == 403, ruta
    with ctx():
        assert db.session.query(Episodio).count() == 0
