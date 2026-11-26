"""Aula: módulos, partes de video, marcar como visto y porcentajes de progreso."""
from conftest import crear_usuario, ctx
from db import db
from models import Clase, Modulo, Parte, Progreso
from progreso import video_embed


# ---------------------------------------------------------------- helpers

def dar_acceso(cliente_admin, curso_id, email="ana@correo.com"):
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_ids": curso_id, "alumno_nombre": "Ana Alumna", "email": email})


def armar_curso_con_modulos(curso_id):
    """Módulo 1 con la clase 1 (3 partes) y la clase 2 sin partes; la clase en vivo del fixture queda sin módulo."""
    with ctx():
        m1 = Modulo(curso_id=curso_id, titulo="Módulo 1 · Táctica", orden=1)
        db.session.add(m1)
        db.session.flush()
        c1 = db.session.get(Clase, 1)
        c1.modulo_id = m1.id
        for i in range(1, 4):
            db.session.add(Parte(clase_id=c1.id, titulo=f"Parte {i}", orden=i,
                                 video_url=f"https://youtu.be/abcdefghij{i}"))
        nueva = Clase(curso_id=curso_id, modulo_id=m1.id, orden=3, titulo="Clase 3 corta",
                      grabacion="https://vimeo.com/123456")
        db.session.add(nueva)
        db.session.commit()
        return m1.id, nueva.id


def marcar(cliente, curso_id, clase_id, parte_id=None, visto="1"):
    data = {"visto": visto}
    if parte_id:
        data["parte_id"] = parte_id
    return cliente.post(f"/curso/{curso_id}/clase/{clase_id}/visto", data=data)


# ---------------------------------------------------------------- videos

def test_video_embed_reconoce_youtube_vimeo_y_drive():
    assert video_embed("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    assert video_embed("https://youtu.be/dQw4w9WgXcQ?t=10") == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    assert video_embed("https://youtube.com/shorts/dQw4w9WgXcQ") == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    assert video_embed("https://vimeo.com/123456") == "https://player.vimeo.com/video/123456"
    assert video_embed("https://drive.google.com/file/d/ABC123/view?usp=sharing") == "https://drive.google.com/file/d/ABC123/preview"
    # Lo que no se reconoce se abre aparte
    assert video_embed("https://drive.google.com/grabacion") is None
    assert video_embed("https://youtube.com/watch?v=<script>") is None
    assert video_embed("") is None and video_embed(None) is None


# ---------------------------------------------------------------- acceso

def test_la_clase_exige_acceso(cliente_alumno, curso):
    r = cliente_alumno.get(f"/curso/{curso}/clase/1")
    assert r.status_code == 302 and "/mis-inscripciones" in r.headers["Location"]
    assert marcar(cliente_alumno, curso, 1).status_code == 403


def test_clase_de_otro_curso_da_404(cliente_admin, cliente_alumno, curso):
    from models import Curso
    with ctx():
        otro = Curso(nombre="Otro", precio=100, activo=True)
        db.session.add(otro)
        db.session.commit()
        otro_id = otro.id
    dar_acceso(cliente_admin, otro_id)
    assert cliente_alumno.get(f"/curso/{otro_id}/clase/1").status_code == 404


def test_borrador_no_se_ve_en_la_pagina_de_clase(cliente_admin, cliente_alumno, curso):
    with ctx():
        db.session.get(Clase, 1).publicada = False
        db.session.commit()
    dar_acceso(cliente_admin, curso)
    assert cliente_alumno.get(f"/curso/{curso}/clase/1").status_code == 404
    assert cliente_admin.get(f"/curso/{curso}/clase/1").status_code == 200


# ---------------------------------------------------------------- partes y progreso

def test_la_clase_muestra_las_partes_y_el_reproductor(cliente_admin, cliente_alumno, curso):
    armar_curso_con_modulos(curso)
    dar_acceso(cliente_admin, curso)
    html = cliente_alumno.get(f"/curso/{curso}/clase/1").get_data(as_text=True)
    assert "Partes de esta clase" in html and "Parte 3" in html
    assert "youtube-nocookie.com/embed/abcdefghij1" in html  # arranca por la primera parte
    with ctx():
        p2 = db.session.execute(db.select(Parte).where(Parte.titulo == "Parte 2")).scalar_one().id
    html = cliente_alumno.get(f"/curso/{curso}/clase/1?parte={p2}").get_data(as_text=True)
    assert "youtube-nocookie.com/embed/abcdefghij2" in html


def test_porcentajes_por_clase_modulo_y_curso(cliente_admin, cliente_alumno, curso):
    _, clase3 = armar_curso_con_modulos(curso)
    dar_acceso(cliente_admin, curso)
    with ctx():
        partes = [p.id for p in db.session.get(Clase, 1).partes]

    # Unidades: clase 1 = 3 partes, clase 3 = 1, clase 2 (sin módulo) = 1 → total 5
    r = marcar(cliente_alumno, curso, 1, partes[0])
    assert r.status_code == 302 and f"parte={partes[1]}" in r.headers["Location"]  # pasa a la siguiente parte
    html = cliente_alumno.get(f"/curso/{curso}").get_data(as_text=True)
    assert "1/3" in html                 # clase 1
    assert "25% completado" in html      # módulo 1: 1 de 4
    assert 'aria-valuenow="20"' in html  # curso: 1 de 5

    marcar(cliente_alumno, curso, 1, partes[1])
    marcar(cliente_alumno, curso, 1, partes[2])
    marcar(cliente_alumno, curso, clase3)
    html = cliente_alumno.get(f"/curso/{curso}").get_data(as_text=True)
    assert "100% completado" in html     # módulo 1 entero
    assert 'aria-valuenow="80"' in html  # curso: 4 de 5
    assert "Seguir viendo: Clase 2 en vivo" in html

    marcar(cliente_alumno, curso, 2)
    html = cliente_alumno.get(f"/curso/{curso}").get_data(as_text=True)
    assert "¡Completaste el curso!" in html


def test_desmarcar_y_marcar_dos_veces_no_duplica(cliente_admin, cliente_alumno, curso):
    dar_acceso(cliente_admin, curso)
    marcar(cliente_alumno, curso, 1)
    marcar(cliente_alumno, curso, 1)
    with ctx():
        assert db.session.query(Progreso).count() == 1
    marcar(cliente_alumno, curso, 1, visto="0")
    with ctx():
        assert db.session.query(Progreso).count() == 0


def test_no_se_puede_marcar_una_parte_de_otra_clase(cliente_admin, cliente_alumno, curso):
    armar_curso_con_modulos(curso)
    dar_acceso(cliente_admin, curso)
    with ctx():
        parte = db.session.get(Clase, 1).partes[0].id
    assert marcar(cliente_alumno, curso, 2, parte).status_code == 404


def test_el_progreso_es_de_cada_alumno(app, cliente_admin, cliente_alumno, curso):
    dar_acceso(cliente_admin, curso)
    marcar(cliente_alumno, curso, 1)
    crear_usuario("Beto", "beto@correo.com")
    dar_acceso(cliente_admin, curso, "beto@correo.com")
    beto = app.test_client()
    beto.post("/iniciar-sesion", data={"email": "beto@correo.com", "password": "password123"})
    html = beto.get(f"/curso/{curso}").get_data(as_text=True)
    assert 'aria-valuenow="0"' in html


# ---------------------------------------------------------------- admin

def test_admin_crea_modulo_clase_y_partes(cliente_admin, curso):
    r = cliente_admin.post(f"/admin/cursos/{curso}/modulos/nuevo", data={"titulo": "Módulo 1 · Fundamentos", "orden": 1})
    assert r.status_code == 302
    with ctx():
        modulo_id = db.session.execute(db.select(Modulo)).scalar_one().id

    assert b"Agregar clase ac" in cliente_admin.get(f"/admin/cursos/{curso}/clases").data
    cliente_admin.post(f"/admin/cursos/{curso}/clases/nueva", data={
        "titulo": "Clase con partes", "modulo_id": modulo_id, "publicada": "y"})
    with ctx():
        clase = db.session.execute(db.select(Clase).where(Clase.titulo == "Clase con partes")).scalar_one()
        assert clase.modulo_id == modulo_id
        clase_id = clase.id

    r = cliente_admin.post(f"/admin/clases/{clase_id}/partes/nueva", data={
        "titulo": "Parte 1", "video_url": "https://youtu.be/dQw4w9WgXcQ", "duracion_min": 12, "otra": "1"})
    assert r.headers["Location"].endswith(f"/admin/clases/{clase_id}/partes/nueva")
    cliente_admin.post(f"/admin/clases/{clase_id}/partes/nueva", data={"titulo": "Parte 2"})
    html = cliente_admin.get(f"/admin/clases/{clase_id}/partes").get_data(as_text=True)
    assert "Parte 1" in html and "Parte 2" in html and "Se ve en la web" in html and "Sin video" in html

    # Mover la clase fuera del módulo desde su edición
    cliente_admin.post(f"/admin/clases/{clase_id}/editar", data={"titulo": "Clase con partes", "modulo_id": 0, "publicada": "y"})
    with ctx():
        assert db.session.get(Clase, clase_id).modulo_id is None


def test_modulo_de_otro_curso_no_se_asigna(cliente_admin, curso):
    from models import Curso
    with ctx():
        otro = Curso(nombre="Otro", precio=100, activo=True)
        db.session.add(otro)
        db.session.flush()
        ajeno = Modulo(curso_id=otro.id, titulo="Ajeno")
        db.session.add(ajeno)
        db.session.commit()
        ajeno_id = ajeno.id
    cliente_admin.post("/admin/clases/1/editar", data={"titulo": "Clase 1 grabada", "modulo_id": ajeno_id, "publicada": "y"})
    with ctx():
        assert db.session.get(Clase, 1).modulo_id is None


def test_eliminar_modulo_conserva_las_clases_y_eliminar_parte_borra_su_progreso(cliente_admin, cliente_alumno, curso):
    modulo_id, _ = armar_curso_con_modulos(curso)
    dar_acceso(cliente_admin, curso)
    with ctx():
        parte = db.session.get(Clase, 1).partes[0].id
    marcar(cliente_alumno, curso, 1, parte)

    cliente_admin.post(f"/admin/modulos/{modulo_id}/eliminar")
    with ctx():
        assert db.session.get(Modulo, modulo_id) is None
        assert db.session.get(Clase, 1).modulo_id is None

    cliente_admin.post(f"/admin/partes/{parte}/eliminar")
    with ctx():
        assert db.session.query(Progreso).count() == 0


def test_eliminar_clase_borra_partes_y_progreso(cliente_admin, cliente_alumno, curso):
    armar_curso_con_modulos(curso)
    dar_acceso(cliente_admin, curso)
    with ctx():
        parte = db.session.get(Clase, 1).partes[0].id
    marcar(cliente_alumno, curso, 1, parte)
    cliente_admin.post("/admin/clases/1/eliminar")
    with ctx():
        assert db.session.query(Parte).count() == 0
        assert db.session.query(Progreso).count() == 0


def test_alumno_no_entra_a_la_administracion_del_aula(cliente_alumno, curso):
    assert cliente_alumno.get(f"/admin/cursos/{curso}/modulos/nuevo").status_code == 403
    assert cliente_alumno.get("/admin/clases/1/partes").status_code == 403
