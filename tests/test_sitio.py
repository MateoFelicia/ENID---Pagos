"""Contenido del sitio (fotos, testimonios, preguntas, ajustes), páginas legales, arrepentimiento y seguridad."""
import io

import pytest
from PIL import Image

from conftest import crear_usuario, ctx
from db import db
from models import Arrepentimiento, Foto, Imagen, PreguntaFrecuente, Testimonio


def imagen(ancho=800, alto=600, formato="PNG", modo="RGB", color=(200, 30, 40)):
    buf = io.BytesIO()
    Image.new(modo, (ancho, alto), color).save(buf, formato)
    return buf.getvalue()


def archivo(datos, nombre="foto.png"):
    return (io.BytesIO(datos), nombre)


def subir_fotos(cliente, *archivos):
    return cliente.post("/admin/sitio/fotos", data={"fotos": list(archivos)},
                        content_type="multipart/form-data", follow_redirects=True)


def contar(modelo):
    with ctx():
        return db.session.query(modelo).count()


def guardar_ajustes_web(cliente, **campos):
    return cliente.post("/admin/sitio", data=campos, content_type="multipart/form-data", follow_redirects=True)


# ------------------------------------------------------------------ fotos e imágenes

def test_subir_foto_la_optimiza_y_la_sirve_con_cache(cliente_admin, cliente):
    r = subir_fotos(cliente_admin, archivo(imagen(3200, 2400, "PNG")))
    assert "1 foto subida" in r.get_data(as_text=True)
    with ctx():
        foto = db.session.query(Foto).one()
        img = db.session.get(Imagen, foto.imagen_id)
        assert (img.mimetype, max(img.ancho, img.alto)) == ("image/jpeg", 1600)  # achicada y sin transparencia
        iid = img.id
    resp = cliente.get(f"/media/{iid}")  # pública: la ven los visitantes
    assert resp.status_code == 200 and resp.mimetype == "image/jpeg"
    assert "max-age" in resp.headers["Cache-Control"] and resp.headers["ETag"]
    assert cliente.get(f"/media/{iid}", headers={"If-None-Match": resp.headers["ETag"]}).status_code == 304
    assert cliente.get("/media/99999").status_code == 404


def test_png_transparente_conserva_la_transparencia(cliente_admin):
    subir_fotos(cliente_admin, archivo(imagen(100, 100, "PNG", "RGBA", (0, 0, 0, 0))))
    with ctx():
        assert db.session.query(Imagen).one().mimetype == "image/png"


def test_foto_que_no_es_imagen_se_rechaza(cliente_admin):
    r = subir_fotos(cliente_admin, archivo(b"<script>alert(1)</script>", "foto.jpg"))
    assert "no es una imagen válida" in r.get_data(as_text=True)
    assert contar(Foto) == 0 and contar(Imagen) == 0


def test_foto_demasiado_pesada_se_rechaza(cliente_admin):
    r = subir_fotos(cliente_admin, archivo(b"\xff\xd8\xff" + b"0" * (11 * 1024 * 1024), "enorme.jpg"))
    assert "pesa más de 10 MB" in r.get_data(as_text=True) and contar(Foto) == 0


def test_se_pueden_subir_varias_fotos_y_una_mala_no_frena_a_las_otras(cliente_admin):
    r = subir_fotos(cliente_admin, archivo(imagen(), "a.png"), archivo(b"basura", "b.jpg"), archivo(imagen(), "c.png"))
    assert "2 fotos subidas" in r.get_data(as_text=True) and contar(Foto) == 2


def test_eliminar_foto_borra_tambien_la_imagen(cliente_admin):
    subir_fotos(cliente_admin, archivo(imagen()))
    with ctx():
        fid = db.session.query(Foto).one().id
    cliente_admin.post(f"/admin/sitio/fotos/{fid}/eliminar")
    assert contar(Foto) == 0 and contar(Imagen) == 0


def test_editar_foto_y_ocultarla_de_la_portada(cliente_admin, cliente):
    subir_fotos(cliente_admin, archivo(imagen()))
    with ctx():
        fid = db.session.query(Foto).one().id
    cliente_admin.post(f"/admin/sitio/fotos/{fid}/editar", data={"pie": "Final del torneo", "orden": "1", "visible": "y"})
    assert "Final del torneo" in cliente.get("/").get_data(as_text=True)
    cliente_admin.post(f"/admin/sitio/fotos/{fid}/editar", data={"pie": "Final del torneo", "orden": "1"})  # sin "visible"
    assert "Final del torneo" not in cliente.get("/").get_data(as_text=True)


def test_solo_el_admin_sube_fotos(cliente, cliente_alumno):
    assert cliente.post("/admin/sitio/fotos").status_code == 302
    assert cliente_alumno.post("/admin/sitio/fotos").status_code == 403
    assert cliente_alumno.get("/admin/sitio").status_code == 403


# ------------------------------------------------------------------ testimonios

DATOS_TESTIMONIO = {"nombre": "Laura Pérez", "detalle": "Mamá de Tomás", "texto": "Mi hijo mejoró muchísimo.",
                    "orden": "1", "visible": "y"}


def test_testimonio_aparece_en_la_portada_y_se_puede_ocultar(cliente_admin, cliente):
    assert "ELLOS YA ENTRENAN" not in cliente.get("/").get_data(as_text=True)  # sin testimonios, no hay sección
    cliente_admin.post("/admin/sitio/testimonios/nuevo", data=DATOS_TESTIMONIO, content_type="multipart/form-data")
    html = cliente.get("/").get_data(as_text=True)
    assert "Mi hijo mejoró muchísimo." in html and "Mamá de Tomás" in html
    with ctx():
        tid = db.session.query(Testimonio).one().id
    datos = {k: v for k, v in DATOS_TESTIMONIO.items() if k != "visible"}
    cliente_admin.post(f"/admin/sitio/testimonios/{tid}/editar", data=datos, content_type="multipart/form-data")
    assert "Mi hijo mejoró" not in cliente.get("/").get_data(as_text=True)


def test_testimonio_con_foto_y_borrado_limpia_la_imagen(cliente_admin):
    cliente_admin.post("/admin/sitio/testimonios/nuevo", data={**DATOS_TESTIMONIO, "foto": archivo(imagen())},
                       content_type="multipart/form-data")
    with ctx():
        t = db.session.query(Testimonio).one()
        assert t.imagen_id is not None
        tid = t.id
    assert contar(Imagen) == 1
    cliente_admin.post(f"/admin/sitio/testimonios/{tid}/eliminar")
    assert contar(Testimonio) == 0 and contar(Imagen) == 0


def test_testimonio_con_html_se_muestra_escapado(cliente_admin, cliente):
    cliente_admin.post("/admin/sitio/testimonios/nuevo", content_type="multipart/form-data",
                       data={**DATOS_TESTIMONIO, "texto": "<script>alert('xss')</script>", "nombre": "<b>Hack</b>"})
    html = cliente.get("/").get_data(as_text=True)
    assert "<script>alert('xss')" not in html and "&lt;script&gt;" in html and "<b>Hack</b>" not in html


# ------------------------------------------------------------------ preguntas frecuentes

def test_preguntas_de_ejemplo_y_preguntas_propias(cliente_admin, cliente):
    assert "¿Cómo me inscribo?" in cliente.get("/").get_data(as_text=True)
    cliente_admin.post("/admin/sitio/preguntas/nueva", data={"pregunta": "¿Hay clases los feriados?",
                                                              "respuesta": "No.", "orden": "1", "visible": "y"})
    html = cliente.get("/").get_data(as_text=True)
    assert "¿Hay clases los feriados?" in html and "¿Cómo me inscribo?" not in html  # solo las propias


def test_cargar_las_preguntas_de_ejemplo_para_editarlas(cliente_admin):
    cliente_admin.post("/admin/sitio/preguntas/cargar-base")
    n = contar(PreguntaFrecuente)
    assert n >= 5
    cliente_admin.post("/admin/sitio/preguntas/cargar-base")  # segunda vez: no duplica
    assert contar(PreguntaFrecuente) == n


def test_editar_y_eliminar_pregunta(cliente_admin):
    cliente_admin.post("/admin/sitio/preguntas/nueva", data={"pregunta": "P", "respuesta": "R", "visible": "y"})
    with ctx():
        pid = db.session.query(PreguntaFrecuente).one().id
    cliente_admin.post(f"/admin/sitio/preguntas/{pid}/editar", data={"pregunta": "P2", "respuesta": "R2", "visible": "y"})
    with ctx():
        assert db.session.get(PreguntaFrecuente, pid).pregunta == "P2"
    cliente_admin.post(f"/admin/sitio/preguntas/{pid}/eliminar")
    assert contar(PreguntaFrecuente) == 0


# ------------------------------------------------------------------ ajustes del sitio

def test_el_entrenador_aparece_solo_cuando_se_completa(cliente_admin, cliente):
    assert "EL ENTRENADOR" not in cliente.get("/").get_data(as_text=True)
    guardar_ajustes_web(cliente_admin, entrenador_nombre="Carlos Rivas", entrenador_titulo="DT",
                        entrenador_bio="Veinte años formando jugadores.")
    html = cliente.get("/").get_data(as_text=True)
    assert "CARLOS RIVAS" in html and "Veinte años formando jugadores." in html


def test_foto_del_entrenador_y_portada_se_reemplazan_y_se_quitan(cliente_admin, cliente):
    guardar_ajustes_web(cliente_admin, entrenador_nombre="Carlos", foto_entrenador=archivo(imagen()),
                        imagen_portada=archivo(imagen(2400, 1200)))
    html = cliente.get("/").get_data(as_text=True)
    assert 'alt="Carlos"' in html and "/media/" in html and contar(Imagen) == 2
    # Reemplazar la foto del entrenador borra la anterior (no se acumulan imágenes viejas)
    guardar_ajustes_web(cliente_admin, entrenador_nombre="Carlos", foto_entrenador=archivo(imagen(500, 500, color=(1, 2, 3))))
    assert contar(Imagen) == 2
    guardar_ajustes_web(cliente_admin, entrenador_nombre="Carlos", quitar_foto_entrenador="y", quitar_portada="y")
    assert contar(Imagen) == 0 and "/media/" not in cliente.get("/").get_data(as_text=True)


def test_imagen_invalida_en_ajustes_no_guarda_nada(cliente_admin):
    r = guardar_ajustes_web(cliente_admin, entrenador_nombre="Carlos", foto_entrenador=archivo(b"no soy foto", "x.png"))
    assert "no es una imagen válida" in r.get_data(as_text=True)


def test_contacto_y_datos_legales_se_ven_en_el_pie(cliente_admin, cliente):
    guardar_ajustes_web(cliente_admin, whatsapp="+54 9 351 555-0000", instagram="https://instagram.com/enid.futbol/",
                        email_contacto="hola@enid.com.ar", legal_titular="Carlos Rivas", legal_cuit="20-1-9",
                        legal_domicilio="Córdoba")
    html = cliente.get("/").get_data(as_text=True)
    assert "https://wa.me/549351555000" in html and "boton-whatsapp" in html
    assert "instagram.com/enid.futbol" in html and "hola@enid.com.ar" in html and "CUIT 20-1-9" in html
    assert "Carlos Rivas" in cliente.get("/terminos").get_data(as_text=True)


def test_instagram_malicioso_se_descarta(cliente_admin, cliente):
    guardar_ajustes_web(cliente_admin, instagram="javascript:alert(1)")
    assert "javascript:" not in cliente.get("/").get_data(as_text=True)


def test_email_de_contacto_invalido_se_rechaza(cliente_admin):
    r = guardar_ajustes_web(cliente_admin, email_contacto="esto-no-es-un-mail")
    assert "Invalid email" in r.get_data(as_text=True) or "email" in r.get_data(as_text=True).lower()


# ------------------------------------------------------------------ páginas legales y arrepentimiento

def test_paginas_legales_son_publicas_y_el_borrador_solo_lo_ve_el_admin(cliente, cliente_admin):
    for ruta in ("/terminos", "/privacidad"):
        html = cliente.get(ruta).get_data(as_text=True)
        assert cliente.get(ruta).status_code == 200 and "Borrador solo visible" not in html
        assert "Borrador solo visible" in cliente_admin.get(ruta).get_data(as_text=True)
    assert "10 días corridos" in cliente.get("/terminos").get_data(as_text=True)
    assert "Ley 25.326" in cliente.get("/privacidad").get_data(as_text=True)


def test_el_boton_de_arrepentimiento_esta_en_todas_las_paginas(cliente, cliente_alumno):
    for ruta in ("/", "/registro", "/iniciar-sesion", "/terminos"):
        assert "Botón de arrepentimiento" in cliente.get(ruta).get_data(as_text=True), ruta
    assert "Botón de arrepentimiento" in cliente_alumno.get("/mis-inscripciones").get_data(as_text=True)


def test_arrepentimiento_sin_iniciar_sesion_registra_y_avisa(cliente, cliente_admin, correo):
    cliente_admin.post("/admin/sitio", data={"email_contacto": "duenio@enid.com"}, content_type="multipart/form-data")
    r = cliente.post("/arrepentimiento", data={"nombre": "Laura Pérez", "email": "laura@correo.com",
                                               "referencia": "Curso Pro", "motivo": "Me arrepentí"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "RECIBIMOS TU PEDIDO" in html
    with ctx():
        s = db.session.query(Arrepentimiento).one()
        assert len(s.codigo) == 8 and s.estado == "recibida" and s.codigo in html
    destinatarios = sorted(m.recipients[0] for m in correo)
    assert destinatarios == ["duenio@enid.com", "laura@correo.com"]
    assert any(s.codigo in m.html for m in correo)


def test_arrepentimiento_valida_los_datos(cliente):
    r = cliente.post("/arrepentimiento", data={"nombre": "", "email": "mal"})
    assert r.status_code == 200 and contar(Arrepentimiento) == 0


def test_el_admin_ve_y_marca_las_solicitudes(cliente, cliente_admin):
    cliente.post("/arrepentimiento", data={"nombre": "Laura", "email": "laura@correo.com"})
    assert "laura@correo.com" in cliente_admin.get("/admin/arrepentimientos").get_data(as_text=True)
    with ctx():
        sid = db.session.query(Arrepentimiento).one().id
    cliente_admin.post(f"/admin/arrepentimientos/{sid}/atender")
    with ctx():
        assert db.session.get(Arrepentimiento, sid).estado == "atendida"
    cliente_admin.post(f"/admin/arrepentimientos/{sid}/atender")
    with ctx():
        assert db.session.get(Arrepentimiento, sid).estado == "recibida"


def test_arrepentimiento_prellena_los_datos_de_quien_esta_logueado(cliente_alumno):
    html = cliente_alumno.get("/arrepentimiento").get_data(as_text=True)
    assert "Ana Alumna" in html and "ana@correo.com" in html


# ------------------------------------------------------------------ seguridad e infraestructura

def test_cabeceras_de_seguridad(cliente):
    h = cliente.get("/").headers
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Strict-Transport-Security" not in h  # solo con https


def test_hsts_solo_por_https(cliente):
    h = cliente.get("/", base_url="https://enid.test").headers
    assert "max-age" in h["Strict-Transport-Security"]


def test_salud_y_robots(cliente):
    assert cliente.get("/salud").get_json() == {"ok": True}
    robots = cliente.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /admin/" in robots and "Disallow: /curso/" in robots


def test_paginas_de_error_con_el_estilo_del_sitio(cliente, cliente_alumno):
    r = cliente.get("/esto-no-existe")
    assert r.status_code == 404 and "No encontramos esa página" in r.get_data(as_text=True)
    r = cliente_alumno.get("/admin/usuarios")
    assert r.status_code == 403 and "No tenés permiso" in r.get_data(as_text=True)


def test_error_500_no_muestra_detalles_ni_depende_de_la_base(app, cliente, monkeypatch):
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)

    def falla():
        raise RuntimeError("contraseña-secreta-de-la-base")

    monkeypatch.setitem(app.view_functions, "inicio", falla)
    r = cliente.get("/")
    assert r.status_code == 500 and "Algo salió mal" in r.get_data(as_text=True)
    assert "contraseña-secreta" not in r.get_data(as_text=True)


def test_csrf_vencido_muestra_una_pagina_amable(app, cliente):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        r = cliente.post("/iniciar-sesion", data={"email": "a@b.com", "password": "x"})
        assert r.status_code == 400 and "La página venció" in r.get_data(as_text=True)
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_limite_de_intentos_de_inicio_de_sesion(app, cliente):
    from extensions import limiter
    limiter.enabled = True
    limiter.reset()
    try:
        # 40 intentos: aunque crucen el cambio de minuto de la ventana, una de las dos pasa el límite de 15
        codigos = [cliente.post("/iniciar-sesion", data={"email": "a@b.com", "password": "mala"}).status_code
                   for _ in range(40)]
        assert 429 in codigos and codigos[0] == 200
    finally:
        limiter.enabled = False
        limiter.reset()


def test_url_de_postgres_se_normaliza():
    from app import normalizar_url_base_de_datos as n
    assert n("postgres://u:p@h/db") == "postgresql://u:p@h/db"
    assert n("postgresql://u:p@h/db") == "postgresql://u:p@h/db" and n("sqlite:///x.db") == "sqlite:///x.db"


@pytest.mark.parametrize("publica,forzado,esperado", [
    ("https://cursos.enid.com.ar", None, True),
    ("https://abc.ngrok-free.dev", None, False),   # túnel de pruebas
    ("http://127.0.0.1:5000", None, False),
    ("https://abc.ngrok-free.dev", "1", True),
    ("https://cursos.enid.com.ar", "0", False),
])
def test_cookies_seguras_segun_la_url_publica(monkeypatch, publica, forzado, esperado):
    from app import _cookies_seguras
    monkeypatch.setenv("PUBLIC_URL", publica)
    monkeypatch.delenv("SECURE_COOKIES", raising=False)
    if forzado is not None:
        monkeypatch.setenv("SECURE_COOKIES", forzado)
    assert _cookies_seguras() is esperado


def test_portada_completa_renderiza_con_todo_el_contenido(cliente_admin, cliente, curso):
    subir_fotos(cliente_admin, archivo(imagen()))
    cliente_admin.post("/admin/sitio/testimonios/nuevo", data=DATOS_TESTIMONIO, content_type="multipart/form-data")
    guardar_ajustes_web(cliente_admin, entrenador_nombre="Carlos", whatsapp="5493510000000")
    r = cliente.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    for esperado in ("EL ENTRENADOR", "ELLOS YA ENTRENAN", "MOMENTOS ENID", "PREGUNTAS FRECUENTES",
                     "EMPEZÁ EN TRES PASOS", "ARS 12.000", "2 clases"):
        assert esperado in html, esperado


def test_aviso_claro_cuando_faltan_migraciones(app, cliente, monkeypatch):
    """Antes se veía un error 500 ('no such table'); ahora una página que dice qué comando correr."""
    import app as modulo_app
    from flask_migrate import stamp
    monkeypatch.setitem(app.config, "TESTING", False)
    monkeypatch.setattr(modulo_app, "_migraciones_ok", False)
    r = cliente.get("/")
    assert r.status_code == 503 and "flask db upgrade" in r.get_data(as_text=True)
    assert cliente.get("/salud").status_code == 200  # el chequeo de salud no se bloquea
    with ctx():
        stamp(revision="head")  # la base queda al día
    assert cliente.get("/").status_code == 200
    assert modulo_app._migraciones_ok is True
