"""Portada con íconos: modalidades, temas editables («Qué vas a aprender») y ficha de cada curso."""
import re

from conftest import ctx
from db import db
from iconos import ICONOS_TEMAS, TEMAS_POR_DEFECTO, TRAZOS, icono, leer_temas, temas_portada
from models import Clase, Curso, Modulo, Parte
from progreso import resumen_curso


def guardar_temas(cliente_admin, texto):
    return cliente_admin.post("/admin/sitio", data={"temas_portada": texto}, follow_redirects=True)


# ---------------------------------------------------------------- íconos

def test_todos_los_iconos_del_panel_existen():
    assert set(ICONOS_TEMAS) <= set(TRAZOS)
    for _, nombre, _, _, error in leer_temas(TEMAS_POR_DEFECTO):
        assert error is None and nombre in TRAZOS


def test_icono_desconocido_no_rompe_y_no_inyecta_html():
    svg = icono("no-existe", 20, '"><script>')
    assert svg.startswith("<svg") and TRAZOS["pelota"] in svg and "<script>" not in svg


# ---------------------------------------------------------------- modalidades y temas

def test_portada_muestra_modalidades_y_temas_por_defecto(cliente):
    html = cliente.get("/").get_data(as_text=True)
    for texto in ("CÓMO SE CURSA", "Clases en vivo", "Clases grabadas", "A tu ritmo", "Acceso permanente",
                  "QUÉ VAS A APRENDER", "TÁCTICA Y ESTRATEGIA", "PREPARACIÓN FÍSICA"):
        assert texto in html, texto
    assert html.count('class="icono') >= 12
    assert "membresía" not in html.split('id="modalidades"')[1].split("</section>")[0]  # sin plan a la venta


def test_dueno_cambia_los_temas_desde_el_panel(cliente_admin, cliente):
    r = guardar_temas(cliente_admin, "silbato | Arbitraje | Reglas del juego.\n\narco | Arqueros\n")
    assert "Ajustes guardados" in r.get_data(as_text=True)
    html = cliente.get("/").get_data(as_text=True)
    assert "ARBITRAJE" in html and "Reglas del juego." in html and "ARQUEROS" in html
    assert "TÁCTICA Y ESTRATEGIA" not in html


def test_temas_con_errores_no_se_guardan_y_se_explica_por_que(cliente_admin, cliente):
    html = guardar_temas(cliente_admin, "pizarra | Táctica\ncohete | Viajes espaciales\nvideo").get_data(as_text=True)
    assert "Línea 2: el ícono «cohete» no existe." in html and "Línea 3: falta el título" in html
    assert "TÁCTICA Y ESTRATEGIA" in cliente.get("/").get_data(as_text=True)  # quedó lo anterior


def test_sin_temas_la_seccion_no_aparece_y_el_boton_apunta_a_modalidades(cliente_admin, cliente):
    guardar_temas(cliente_admin, "")
    html = cliente.get("/").get_data(as_text=True)
    assert "QUÉ VAS A APRENDER" not in html and 'href="#modalidades"' in html


def test_temas_se_limitan_y_toleran_espacios():
    texto = "\n".join(f"  PELOTA |  Tema {i}  | Texto {i} " for i in range(20))
    temas = temas_portada(texto)
    assert len(temas) == 12 and temas[0] == {"icono": "pelota", "titulo": "Tema 0", "descripcion": "Texto 0"}


def test_el_panel_muestra_los_iconos_para_elegir(cliente_admin):
    html = cliente_admin.get("/admin/sitio").get_data(as_text=True)
    assert "Qué vas a aprender" in html and "galeria-iconos" in html
    assert all(nombre in html for nombre in ICONOS_TEMAS)


# ---------------------------------------------------------------- ficha del curso

def _curso_completo(curso_id):
    with ctx():
        m = Modulo(curso_id=curso_id, titulo="Táctica")
        db.session.add(m)
        db.session.flush()
        clases = db.session.execute(db.select(Clase).where(Clase.curso_id == curso_id)).scalars().all()
        for c in clases:
            c.modulo_id = m.id
        db.session.add_all([Parte(clase_id=clases[0].id, titulo=f"Parte {i}", duracion_min=50) for i in range(4)])
        db.session.add(Clase(curso_id=curso_id, orden=3, titulo="Borrador", publicada=False))
        db.session.commit()


def test_resumen_cuenta_solo_lo_publicado(app, curso):
    _curso_completo(curso)
    with ctx():
        r = resumen_curso(db.session.get(Curso, curso))
        assert (r.modulos, r.clases, r.videos, r.minutos, r.en_vivo) == (1, 2, 4, 200, True)
        assert r.duracion == "3 h 20 min"


def test_tarjeta_del_curso_muestra_la_ficha_con_iconos(cliente, curso):
    _curso_completo(curso)
    html = cliente.get("/").get_data(as_text=True)
    ficha = re.search(r'<ul class="ficha-curso">(.*?)</ul>', html, re.S).group(1)
    texto = re.sub(r"<[^>]+>|\s+", " ", ficha)
    for dato in ("1 módulo", "2 clases", "4 videos", "3 h 20 min", "Con clases en vivo"):
        assert dato in texto, dato
    assert ficha.count("<svg") == 5
