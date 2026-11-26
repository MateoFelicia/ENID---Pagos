"""Noticias y newsletter: publicación, suscripción con doble opt-in, envío y baja."""
import re

from conftest import ctx
from db import db
from models import Noticia, Suscriptor


def crear_noticia(cliente_admin, titulo="Arranca el curso de DT", publicada=True, cuerpo="Primer párrafo.\n\nSegundo párrafo."):
    data = {"titulo": titulo, "resumen": "Inscripciones abiertas", "cuerpo": cuerpo}
    if publicada:
        data["publicada"] = "y"
    cliente_admin.post("/admin/noticias/nueva", data=data)
    with ctx():
        return db.session.execute(db.select(Noticia).where(Noticia.titulo == titulo)).scalar_one().id


def suscribir(cliente, email="hincha@correo.com", **extra):
    return cliente.post("/newsletter", data={"email": email, "volver": "/noticias", **extra}, follow_redirects=True)


def enlace(mensaje, ruta):
    return re.search(rf"https?://[^\"\s)]+{ruta}/[^\"\s)]+", mensaje.html).group(0).split("localhost", 1)[1]


def suscriptor(email="hincha@correo.com"):
    with ctx():
        return db.session.execute(db.select(Suscriptor).where(Suscriptor.email == email)).scalar_one_or_none()


def confirmar(cliente, correo, email="hincha@correo.com"):
    suscribir(cliente, email)
    cliente.get(enlace(correo[-1], "/newsletter/confirmar"))


# ---------------------------------------------------------------- noticias

def test_noticia_publicada_se_ve_con_url_legible(cliente_admin, cliente):
    nid = crear_noticia(cliente_admin)
    r = cliente.get(f"/noticias/{nid}")
    assert r.status_code == 301 and r.headers["Location"].endswith(f"/noticias/{nid}-arranca-el-curso-de-dt")
    html = cliente.get(f"/noticias/{nid}-arranca-el-curso-de-dt").get_data(as_text=True)
    assert "<p>Primer párrafo.</p>" in html and "<p>Segundo párrafo.</p>" in html
    assert "Arranca el curso de DT" in cliente.get("/noticias").get_data(as_text=True)
    assert "Arranca el curso de DT" in cliente.get("/").get_data(as_text=True)  # últimas en la portada


def test_borrador_solo_lo_ve_el_dueno(cliente_admin, cliente):
    nid = crear_noticia(cliente_admin, "Borrador secreto", publicada=False)
    assert cliente.get(f"/noticias/{nid}").status_code == 404
    assert "Borrador secreto" not in cliente.get("/noticias").get_data(as_text=True)
    assert "solo lo ves vos" in cliente_admin.get(f"/noticias/{nid}").get_data(as_text=True)


def test_el_cuerpo_no_admite_html(cliente_admin, cliente):
    nid = crear_noticia(cliente_admin, "Ojo", cuerpo="<script>alert(1)</script>")
    html = cliente.get(f"/noticias/{nid}-ojo").get_data(as_text=True)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_alumno_no_administra_noticias(cliente_alumno):
    for ruta in ("/admin/noticias", "/admin/noticias/nueva", "/admin/suscriptores"):
        assert cliente_alumno.get(ruta).status_code == 403, ruta
    assert cliente_alumno.post("/admin/noticias/1/enviar").status_code == 403


# ---------------------------------------------------------------- suscripción

def test_suscribirse_pide_confirmacion_y_recien_ahi_queda_activo(cliente, correo):
    r = suscribir(cliente)
    assert "Te mandamos un mail para confirmar" in r.get_data(as_text=True)
    assert len(correo) == 1 and correo[0].recipients == ["hincha@correo.com"]
    assert not suscriptor().activo

    cliente.get(enlace(correo[0], "/newsletter/confirmar"))
    assert suscriptor().activo


def test_mail_invalido_o_robot_no_anota(cliente, correo):
    assert "no parece válido" in suscribir(cliente, "no-es-un-mail").get_data(as_text=True)
    suscribir(cliente, "robot@spam.com", sitio_web="http://spam")
    assert correo == [] and suscriptor("robot@spam.com") is None


def test_anotarse_dos_veces_no_duplica_ni_revela_nada(cliente, correo):
    confirmar(cliente, correo)
    r = suscribir(cliente)  # ya activo: no manda otro mail, pero responde igual
    assert "Te mandamos un mail para confirmar" in r.get_data(as_text=True)
    assert len(correo) == 1
    with ctx():
        assert db.session.query(Suscriptor).count() == 1


def test_enlace_de_confirmacion_trucho_no_hace_nada(cliente):
    r = cliente.get("/newsletter/confirmar/cualquiera", follow_redirects=True)
    assert "venció o no es válido" in r.get_data(as_text=True)


def test_volver_no_redirige_a_otro_sitio(cliente):
    r = cliente.post("/newsletter", data={"email": "a@b.com", "volver": "//malo.com/x"})
    assert r.headers["Location"].endswith("/noticias")


# ---------------------------------------------------------------- envío y baja

def test_mandar_noticia_solo_a_confirmados_y_una_sola_vez(cliente_admin, cliente, correo):
    confirmar(cliente, correo, "activa@correo.com")
    suscribir(cliente, "pendiente@correo.com")  # no confirma
    nid = crear_noticia(cliente_admin)
    correo.clear()

    r = cliente_admin.post(f"/admin/noticias/{nid}/enviar", follow_redirects=True)
    assert "enviada a 1 suscriptor" in r.get_data(as_text=True)
    assert [m.recipients for m in correo] == [["activa@correo.com"]]
    assert correo[0].subject == "Arranca el curso de DT" and "Darme de baja" in correo[0].html

    cliente_admin.post(f"/admin/noticias/{nid}/enviar")
    assert len(correo) == 1  # no se repite


def test_borrador_no_se_manda(cliente_admin, cliente, correo):
    confirmar(cliente, correo)
    nid = crear_noticia(cliente_admin, "Borrador", publicada=False)
    correo.clear()
    r = cliente_admin.post(f"/admin/noticias/{nid}/enviar", follow_redirects=True)
    assert "Publicá la noticia" in r.get_data(as_text=True) and correo == []


def test_darse_de_baja_desde_el_mail(cliente_admin, cliente, correo):
    confirmar(cliente, correo)
    nid = crear_noticia(cliente_admin)
    cliente_admin.post(f"/admin/noticias/{nid}/enviar")
    url_baja = enlace(correo[-1], "/newsletter/baja")

    assert "¿Dejar de recibir novedades?" in cliente.get(url_baja).get_data(as_text=True)
    assert suscriptor().activo  # abrir el enlace no alcanza (los antivirus los abren solos)
    assert "te diste de baja" in cliente.post(url_baja).get_data(as_text=True)
    assert not suscriptor().activo

    # Si se vuelve a anotar, tiene que confirmar de nuevo
    suscribir(cliente)
    assert not suscriptor().activo and len(correo) == 3


def test_panel_lista_y_exporta_suscriptores(cliente_admin, cliente, correo):
    confirmar(cliente, correo)
    html = cliente_admin.get("/admin/suscriptores").get_data(as_text=True)
    assert "hincha@correo.com" in html and "Activo" in html
    csv = cliente_admin.get("/admin/suscriptores?formato=csv").get_data(as_text=True)
    assert "hincha@correo.com,activo" in csv
