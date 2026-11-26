"""Preparación para producción: página «¿Lista para abrir?», sitemap y robots."""


def test_dueno_ve_que_falta_para_abrir(cliente_admin):
    html = cliente_admin.get("/admin/lanzamiento").get_data(as_text=True)
    assert "¿Está lista la web para abrir?" in html
    assert "Falta PUBLIC_URL" in html and "Falta el número de WhatsApp" in html
    assert "abogado" in html and "contador" in html  # lo que se revisa a mano


def test_con_whatsapp_cargado_desaparece_el_aviso(cliente_admin):
    cliente_admin.post("/admin/sitio", data={"whatsapp": "5493515523929"})
    html = cliente_admin.get("/admin/lanzamiento").get_data(as_text=True)
    assert "WhatsApp cargado" in html and "Falta el número de WhatsApp" not in html
    assert "wa.me/5493515523929" in cliente_admin.get("/").get_data(as_text=True)  # botón flotante


def test_alumno_no_ve_el_lanzamiento(cliente_alumno):
    assert cliente_alumno.get("/admin/lanzamiento").status_code == 403


def test_sitemap_lista_las_paginas_publicas_y_noticias(cliente_admin, cliente):
    cliente_admin.post("/admin/noticias/nueva", data={"titulo": "Abrimos", "cuerpo": "Hola", "publicada": "y"})
    cliente_admin.post("/admin/noticias/nueva", data={"titulo": "Borrador", "cuerpo": "Hola"})
    r = cliente.get("/sitemap.xml")
    xml = r.get_data(as_text=True)
    assert r.mimetype == "application/xml"
    for ruta in ("/noticias</loc>", "/podcasts</loc>", "/biblioteca</loc>", "/profesores</loc>", "/noticias/1-abrimos</loc>"):
        assert ruta in xml, ruta
    assert "borrador" not in xml.lower() and "/admin" not in xml
    assert "Sitemap: http://localhost/sitemap.xml" in cliente.get("/robots.txt").get_data(as_text=True)
