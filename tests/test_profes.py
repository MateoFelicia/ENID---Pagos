"""Rol de profesor: alta desde el panel, permisos por curso, perfil y página pública."""
import io

from conftest import crear_usuario, ctx
from db import db
from models import Clase, Curso, Modulo, Usuario


def hacer_profe(cliente_admin, nombre="Pablo Profe", email="pablo@enid.com"):
    return cliente_admin.post("/admin/profesores", data={"nombre": nombre, "email": email})


def asignar(cliente_admin, profe_id, curso_ids, **perfil):
    data = {"nombre": perfil.get("nombre", "Pablo Profe"), "curso_ids": [str(i) for i in curso_ids]}
    data.update(perfil)
    return cliente_admin.post(f"/admin/profesores/{profe_id}/editar", data=data)


def id_de(email):
    with ctx():
        return db.session.execute(db.select(Usuario).where(Usuario.email == email)).scalar_one().id


def login(app, email, password="password123"):
    c = app.test_client()
    c.post("/iniciar-sesion", data={"email": email, "password": password})
    return c


def otro_curso():
    with ctx():
        c = Curso(nombre="Curso ajeno", precio=5000, activo=True)
        db.session.add(c)
        db.session.flush()
        db.session.add(Clase(curso_id=c.id, orden=1, titulo="Clase ajena", grabacion="https://youtu.be/ajenoajeno1"))
        db.session.commit()
        return c.id


# ---------------------------------------------------------------- alta

def test_dueno_crea_profe_nuevo_con_invitacion(cliente_admin):
    r = hacer_profe(cliente_admin)
    assert r.status_code == 302 and "/admin/profesores/" in r.headers["Location"]
    html = cliente_admin.get(r.headers["Location"]).get_data(as_text=True)
    assert "/resetear-password/" in html  # enlace para que elija su contraseña
    with ctx():
        assert db.session.get(Usuario, id_de("pablo@enid.com")).es_profesor


def test_un_alumno_existente_puede_pasar_a_ser_profe(cliente_admin, cliente_alumno):
    hacer_profe(cliente_admin, "Ana Alumna", "ana@correo.com")
    with ctx():
        ana = db.session.get(Usuario, id_de("ana@correo.com"))
        assert ana.es_profesor and ana.verificar_password("password123")  # no le cambia la clave


def test_quitar_rol_conserva_la_cuenta(cliente_admin, curso):
    hacer_profe(cliente_admin)
    pid = id_de("pablo@enid.com")
    asignar(cliente_admin, pid, [curso])
    cliente_admin.post(f"/admin/profesores/{pid}/quitar")
    with ctx():
        u = db.session.get(Usuario, pid)
        assert u is not None and not u.es_profesor and u.cursos_dictados == []


# ---------------------------------------------------------------- permisos

def test_profe_gestiona_solo_sus_cursos(app, cliente_admin, curso):
    ajeno = otro_curso()
    crear_usuario("Pablo Profe", "pablo@enid.com")
    hacer_profe(cliente_admin)
    asignar(cliente_admin, id_de("pablo@enid.com"), [curso])
    profe = login(app, "pablo@enid.com")

    # Su curso: entra sin pagar, ve el panel de clases y puede crear módulo, clase y parte
    assert profe.get(f"/curso/{curso}").status_code == 200
    assert profe.get(f"/admin/cursos/{curso}/clases").status_code == 200
    assert profe.post(f"/admin/cursos/{curso}/modulos/nuevo", data={"titulo": "Módulo del profe"}).status_code == 302
    assert profe.post(f"/admin/cursos/{curso}/clases/nueva", data={"titulo": "Clase del profe", "publicada": "y"}).status_code == 302
    assert profe.post("/admin/clases/1/partes/nueva", data={"titulo": "Parte del profe"}).status_code == 302

    # Curso ajeno: nada
    with ctx():
        clase_ajena = db.session.execute(db.select(Clase).where(Clase.curso_id == ajeno)).scalar_one().id
    assert profe.get(f"/curso/{ajeno}").status_code == 302
    assert profe.get(f"/admin/cursos/{ajeno}/clases").status_code == 403
    assert profe.post(f"/admin/cursos/{ajeno}/clases/nueva", data={"titulo": "Intruso"}).status_code == 403
    assert profe.post(f"/admin/clases/{clase_ajena}/eliminar").status_code == 403
    assert profe.post(f"/admin/clases/{clase_ajena}/partes/nueva", data={"titulo": "Intrusa"}).status_code == 403
    with ctx():
        assert db.session.get(Clase, clase_ajena) is not None


def test_profe_no_ve_el_resto_del_panel(app, cliente_admin, curso):
    crear_usuario("Pablo Profe", "pablo@enid.com")
    hacer_profe(cliente_admin)
    profe = login(app, "pablo@enid.com")
    for ruta in ["/admin/usuarios", "/admin/inscripciones", "/admin/cursos", "/admin/sitio",
                 "/admin/profesores", f"/admin/cursos/{curso}/editar"]:
        assert profe.get(ruta).status_code == 403, ruta


def test_modulo_ajeno_no_se_edita_ni_borra(app, cliente_admin, curso):
    ajeno = otro_curso()
    with ctx():
        m = Modulo(curso_id=ajeno, titulo="Módulo ajeno")
        db.session.add(m)
        db.session.commit()
        mid = m.id
    crear_usuario("Pablo Profe", "pablo@enid.com")
    hacer_profe(cliente_admin)
    asignar(cliente_admin, id_de("pablo@enid.com"), [curso])
    profe = login(app, "pablo@enid.com")
    assert profe.get(f"/admin/modulos/{mid}/editar").status_code == 403
    assert profe.post(f"/admin/modulos/{mid}/eliminar").status_code == 403


def test_alumno_no_entra_al_panel_del_profe(cliente_alumno):
    assert cliente_alumno.get("/profe").status_code == 403
    assert cliente_alumno.get("/profe/perfil").status_code == 403


# ---------------------------------------------------------------- perfil y página pública

def test_profe_edita_su_perfil_y_aparece_en_la_pagina_publica(app, cliente_admin, curso):
    crear_usuario("Pablo Profe", "pablo@enid.com")
    hacer_profe(cliente_admin)
    asignar(cliente_admin, id_de("pablo@enid.com"), [curso])
    profe = login(app, "pablo@enid.com")
    assert b"Curso Pro" in profe.get("/profe").data

    r = profe.post("/profe/perfil", data={
        "nombre": "Pablo Pérez", "titulo_profesional": "Director Técnico Nacional",
        "bio": "Ex entrenador de inferiores."})
    assert r.status_code == 302

    html = app.test_client().get("/profesores").get_data(as_text=True)
    assert "Pablo Pérez" in html and "Director Técnico Nacional" in html and "Curso Pro" in html
    # También en la ficha del curso
    assert "Dictado por:" in profe.get(f"/curso/{curso}").get_data(as_text=True)


def test_foto_invalida_no_rompe_el_perfil(app, cliente_admin):
    crear_usuario("Pablo Profe", "pablo@enid.com")
    hacer_profe(cliente_admin)
    profe = login(app, "pablo@enid.com")
    r = profe.post("/profe/perfil", data={
        "nombre": "Pablo", "foto": (io.BytesIO(b"no soy una imagen"), "foto.jpg")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    with ctx():
        assert db.session.get(Usuario, id_de("pablo@enid.com")).foto_id is None
