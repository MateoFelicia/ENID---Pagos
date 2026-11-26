"""Dar acceso a varios alumnos pegando una lista de mails."""
from conftest import ctx
from db import db
from importador import csv_desde_lista, parsear
from models import Curso, Inscripcion, Usuario


def cursos():
    with ctx():
        return db.session.execute(db.select(Curso)).scalars().all()


def test_lista_entiende_los_formatos_habituales(curso):
    with ctx():
        todos = db.session.execute(db.select(Curso)).scalars().all()
        texto = csv_desde_lista(
            "ana@mail.com\n"
            "Luis Gómez, luis@mail.com\n"
            "Marta Díaz <marta@mail.com>\n"
            "pedro@mail.com\tPedro Ruiz\n"
            "\n"
            "juan.perez_99@gmail.com\n",
            todos, "transferencia")
        filas, errores = parsear(texto, todos)
    assert errores == []
    datos = [(f.nombre, f.email) for f in filas]
    assert datos == [
        ("Ana", "ana@mail.com"), ("Luis Gómez", "luis@mail.com"), ("Marta Díaz", "marta@mail.com"),
        ("Pedro Ruiz", "pedro@mail.com"), ("Juan Perez", "juan.perez_99@gmail.com"),
    ]
    assert all(f.valida for f in filas)


def test_linea_sin_mail_aparece_como_error_en_la_vista_previa(curso):
    with ctx():
        todos = db.session.execute(db.select(Curso)).scalars().all()
        filas, _ = parsear(csv_desde_lista("Ana sin mail\nok@mail.com", todos), todos)
    assert filas[0].errores and filas[1].valida


def test_pegar_lista_vista_previa_y_confirmar(cliente_admin, curso):
    r = cliente_admin.post("/admin/alumnos/importar", data={
        "accion": "previsualizar", "lista": "ana@mail.com\nLuis Gómez, luis@mail.com",
        "curso_ids": str(curso), "medio": "transferencia"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "2 listas para importar" in html
    with ctx():
        assert db.session.query(Inscripcion).count() == 0  # la vista previa no guarda nada

    # Confirmar reenvía el CSV armado (el mismo camino que un archivo)
    import re
    contenido = re.search(r'<textarea name="contenido" hidden>(.*?)</textarea>', html, re.S)
    assert contenido, "la vista previa debe incluir el contenido a confirmar"
    from html import unescape
    r = cliente_admin.post("/admin/alumnos/importar", data={"accion": "importar", "contenido": unescape(contenido.group(1))})
    assert r.status_code == 200
    with ctx():
        luis = db.session.execute(db.select(Usuario).where(Usuario.email == "luis@mail.com")).scalar_one()
        assert luis.nombre == "Luis Gómez"
        ins = db.session.execute(db.select(Inscripcion).where(Inscripcion.usuario_id == luis.id)).scalar_one()
        assert ins.tiene_acceso() and ins.medio == "transferencia" and ins.curso_id == curso


def test_pegar_lista_sin_cursos_pide_elegir(cliente_admin, curso):
    r = cliente_admin.post("/admin/alumnos/importar", data={"accion": "previsualizar", "lista": "ana@mail.com"})
    html = r.get_data(as_text=True)
    assert "Elegí al menos un curso" in html and "ana@mail.com" in html  # no pierde lo pegado
