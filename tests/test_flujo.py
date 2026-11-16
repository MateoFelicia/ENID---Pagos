from conftest import crear_usuario, ctx, headers_firmados, pago_mp
from db import db
from models import Inscripcion, Pago, Usuario


def enviar_webhook(cliente, payment_id, **kw):
    return cliente.post(
        f"/webhooks/mercadopago?data.id={payment_id}&type=payment",
        json={"type": "payment", "data": {"id": str(payment_id)}},
        headers=headers_firmados(payment_id, **kw),
    )


def estado_inscripcion(inscripcion_id=1):
    with ctx():
        return db.session.get(Inscripcion, inscripcion_id).estado


def contar(modelo):
    with ctx():
        return db.session.query(modelo).count()


# ---------------------------------------------------------------- compra + acceso

def test_flujo_completo_registro_pago_y_acceso(cliente_alumno, curso, mp):
    r = cliente_alumno.post(f"/comprar/{curso}")
    assert r.status_code == 302 and r.headers["Location"] == "https://mp.test/checkout/pref-1"

    pref = mp.preferencias[0]
    assert pref["items"][0]["unit_price"] == 12000.0 and pref["external_reference"] == "1"
    assert estado_inscripcion() == "pendiente"

    # Antes de pagar: sin acceso al contenido
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302

    # Mercado Pago avisa por webhook
    mp.pagos["555"] = pago_mp(555, 1, 12000)
    assert enviar_webhook(cliente_alumno, 555).status_code == 200
    assert estado_inscripcion() == "pagada"

    r = cliente_alumno.get(f"/curso/{curso}")
    assert r.status_code == 200
    assert b"meet.google.com/abc-defg-hij" in r.data and b"drive.google.com/grabacion" in r.data
    assert b"hora de Argentina" in r.data
    assert b"Entrar al curso" in cliente_alumno.get("/mis-inscripciones").data


def test_retorno_exitoso_confirma_aunque_el_webhook_no_llegue(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["777"] = pago_mp(777, 1, 12000)
    r = cliente_alumno.get("/pago/exitoso?payment_id=777&status=approved&external_reference=1")
    assert r.status_code == 302
    assert estado_inscripcion() == "pagada"


def test_url_de_retorno_falsa_no_da_acceso(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    # payment_id que no existe en Mercado Pago: la URL sola no alcanza
    cliente_alumno.get("/pago/exitoso?payment_id=999&status=approved&external_reference=1")
    assert estado_inscripcion() == "pendiente"
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302


def test_comprar_sin_login_redirige_al_login(cliente, curso):
    r = cliente.post(f"/comprar/{curso}")
    assert r.status_code == 302 and "/iniciar-sesion" in r.headers["Location"]


def test_reintento_reutiliza_la_inscripcion_pendiente(cliente_alumno, curso):
    cliente_alumno.post(f"/comprar/{curso}")
    cliente_alumno.post(f"/comprar/{curso}")
    assert contar(Inscripcion) == 1
    assert contar(Pago) == 1


def test_no_se_puede_comprar_dos_veces_un_curso_ya_pagado(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["1"] = pago_mp(1, 1, 12000)
    enviar_webhook(cliente_alumno, 1)
    r = cliente_alumno.post(f"/comprar/{curso}")
    assert f"/curso/{curso}" in r.headers["Location"]
    assert contar(Inscripcion) == 1


def test_pendiente_y_pagada_del_mismo_curso_no_rompen_el_acceso(cliente_alumno, curso):
    # Bug original: scalar_one_or_none() explotaba con 2 filas
    with ctx():
        uid = db.session.query(Usuario).filter_by(email="ana@correo.com").one().id
        db.session.add_all([
            Inscripcion(curso_id=curso, usuario_id=uid, alumno_nombre="Ana", monto=12000, estado="pendiente"),
            Inscripcion(curso_id=curso, usuario_id=uid, alumno_nombre="Ana", monto=12000, estado="pagada"),
        ])
        db.session.commit()
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 200


# ---------------------------------------------------------------- seguridad del webhook

def test_webhook_firma_invalida_es_rechazado(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["555"] = pago_mp(555, 1, 12000)
    r = enviar_webhook(cliente_alumno, 555, secreto="otro-secreto")
    assert r.status_code == 401
    assert estado_inscripcion() == "pendiente"


def test_webhook_sin_headers_da_400(cliente):
    assert cliente.post("/webhooks/mercadopago?data.id=1&type=payment", json={}).status_code == 400


def test_webhook_con_monto_distinto_no_acredita(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["555"] = pago_mp(555, 1, 1)  # pagó $1 en vez de $12000
    enviar_webhook(cliente_alumno, 555)
    assert estado_inscripcion() == "pendiente"


def test_pago_rechazado_no_da_acceso(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["555"] = pago_mp(555, 1, 12000, status="rejected")
    enviar_webhook(cliente_alumno, 555)
    assert estado_inscripcion() == "pendiente"


def test_reembolso_revoca_el_acceso(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["555"] = pago_mp(555, 1, 12000)
    enviar_webhook(cliente_alumno, 555)
    mp.pagos["555"] = pago_mp(555, 1, 12000, status="refunded")
    enviar_webhook(cliente_alumno, 555, request_id="req-2")
    assert estado_inscripcion() == "reembolsada"
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302


def test_intento_rechazado_posterior_no_pisa_un_pago_acreditado(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["1"] = pago_mp(1, 1, 12000)
    enviar_webhook(cliente_alumno, 1)
    mp.pagos["2"] = pago_mp(2, 1, 12000, status="rejected")
    enviar_webhook(cliente_alumno, 2, request_id="req-2")
    assert estado_inscripcion() == "pagada"


# ---------------------------------------------------------------- panel del dueño

def test_panel_de_alumnos_solo_para_admin(app, cliente, cliente_alumno, cliente_admin):
    assert cliente.get("/admin/usuarios").status_code == 302      # sin login
    assert cliente_alumno.get("/admin/usuarios").status_code == 403
    assert cliente_admin.get("/admin/usuarios").status_code == 200


def test_panel_muestra_usuarios_con_sus_cursos(cliente_alumno, cliente_admin, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["1"] = pago_mp(1, 1, 12000)
    enviar_webhook(cliente_alumno, 1)
    html = cliente_admin.get("/admin/usuarios").get_data(as_text=True)
    assert "Ana Alumna" in html and "ana@correo.com" in html and "Curso Pro" in html
    assert "pagada" in html


def test_alta_manual_crea_cuenta_con_acceso_y_enlace(cliente_admin, curso):
    r = cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_id": curso, "alumno_nombre": "Lucho Previo", "email": "Lucho@Correo.com",
    }, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Acceso concedido" in html and "/resetear-password/" in html

    with ctx():
        u = db.session.query(Usuario).filter_by(email="lucho@correo.com").one()
        assert not u.es_admin
        ins = db.session.query(Inscripcion).one()
        assert ins.origen == "manual" and ins.estado == "pagada" and ins.usuario_id == u.id


def test_alta_manual_duplicada_avisa(cliente_admin, curso):
    datos = {"curso_id": curso, "alumno_nombre": "Lucho", "email": "lucho@correo.com"}
    cliente_admin.post("/admin/inscripciones/nueva", data=datos)
    r = cliente_admin.post("/admin/inscripciones/nueva", data=datos, follow_redirects=True)
    assert "ya tenía acceso".encode() in r.data
    assert contar(Inscripcion) == 1


def test_alumno_dado_de_alta_a_mano_entra_con_el_enlace(app, cliente_admin, curso):
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_id": curso, "alumno_nombre": "Lucho", "email": "lucho@correo.com"})
    token = app_module_token("lucho@correo.com")
    c = app.test_client()
    c.post(f"/resetear-password/{token}", data={"password": "nuevaclave123", "confirmar": "nuevaclave123"})
    c.post("/iniciar-sesion", data={"email": "lucho@correo.com", "password": "nuevaclave123"})
    assert c.get(f"/curso/{curso}").status_code == 200


def app_module_token(email):
    import app as m
    with ctx():
        return m.generar_token_reset(email)


def test_csv_exporta_y_neutraliza_formulas(cliente_admin):
    crear_usuario("=HYPERLINK(\"http://malo\")", "x@correo.com")
    r = cliente_admin.get("/admin/usuarios.csv")
    texto = r.get_data(as_text=True)
    assert r.mimetype == "text/csv" and "Alumno,Email,Alta,Último ingreso,Curso" in texto
    assert "'=HYPERLINK" in texto


def test_admin_elimina_inscripcion_de_prueba(cliente_alumno, cliente_admin, curso):
    cliente_alumno.post(f"/comprar/{curso}")
    cliente_admin.post("/admin/inscripciones/1/eliminar")
    assert contar(Inscripcion) == 0 and contar(Pago) == 0


def test_next_externo_no_se_sigue(app):
    crear_usuario("Ana", "ana2@correo.com")
    c = app.test_client()
    r = c.post("/iniciar-sesion?next=//evil.com", data={"email": "ana2@correo.com", "password": "password123"})
    assert r.status_code == 302 and "evil.com" not in r.headers["Location"]


def test_paginas_publicas_renderizan(cliente, cliente_alumno, curso):
    assert cliente.get("/").status_code == 200
    assert b"INSCRIBIRME" in cliente.get("/").data
    for ruta in ["/registro", "/iniciar-sesion", "/recuperar-password"]:
        assert cliente.get(ruta).status_code == 200
    assert b"COMPLETAR PAGO" not in cliente_alumno.get("/").data


def test_todas_las_pantallas_del_panel_renderizan(cliente_admin, cliente_alumno, curso):
    for ruta in ["/admin/cursos", "/admin/cursos/nuevo", f"/admin/cursos/{curso}/editar",
                 "/admin/inscripciones", "/admin/inscripciones/nueva",
                 "/admin/inscripciones/nueva?nombre=Ana&email=ana@correo.com", "/admin/usuarios"]:
        assert cliente_admin.get(ruta).status_code == 200, ruta
    assert cliente_alumno.get("/mis-inscripciones").status_code == 200


# ---------------------------------------------------------------- clases (en vivo + grabadas)

def id_clase(titulo):
    from models import Clase
    with ctx():
        return db.session.query(Clase).filter_by(titulo=titulo).one().id


def test_estados_de_una_clase():
    from datetime import datetime, timedelta
    from models import Clase
    ahora = datetime(2026, 11, 3, 18, 0)
    assert Clase(titulo="a", grabacion="https://x.com/v").estado(ahora) == "grabada"
    assert Clase(titulo="b", meet_link="https://meet", fecha=ahora + timedelta(days=1)).estado(ahora) == "proxima"
    assert Clase(titulo="c", meet_link="https://meet", fecha=ahora - timedelta(minutes=30)).estado(ahora) == "en_curso"
    assert Clase(titulo="d", meet_link="https://meet", fecha=ahora - timedelta(hours=5)).estado(ahora) == "esperando_grabacion"
    assert Clase(titulo="e").estado(ahora) == "sin_contenido"
    # Una clase en vivo con grabación ya subida muestra la grabación
    assert Clase(titulo="f", meet_link="https://meet", grabacion="https://x.com/v",
                 fecha=ahora - timedelta(days=2)).estado(ahora) == "grabada"


def test_alumno_con_acceso_ve_las_clases_y_destaca_la_proxima(cliente_alumno, curso, mp):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["1"] = pago_mp(1, 1, 12000)
    enviar_webhook(cliente_alumno, 1)
    html = cliente_alumno.get(f"/curso/{curso}").get_data(as_text=True)
    assert "Clase 1 grabada" in html and "Clase 2 en vivo" in html
    assert "Próxima clase en vivo" in html and "Ver grabación" in html


def test_alumno_sin_acceso_no_ve_las_clases(cliente_alumno, curso):
    r = cliente_alumno.get(f"/curso/{curso}", follow_redirects=True)
    assert b"meet.google.com" not in r.data and b"drive.google.com" not in r.data


def test_borrador_se_oculta_al_alumno_pero_no_al_admin(cliente_alumno, cliente_admin, curso):
    from models import Clase
    with ctx():
        db.session.add(Clase(curso_id=curso, orden=3, titulo="Clase secreta", publicada=False,
                             grabacion="https://drive.google.com/secreta"))
        db.session.commit()
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_ids": curso, "alumno_nombre": "Ana Alumna", "email": "ana@correo.com"})
    assert b"Clase secreta" not in cliente_alumno.get(f"/curso/{curso}").data
    assert b"Clase secreta" in cliente_admin.get(f"/curso/{curso}").data


def test_admin_crea_edita_y_elimina_clases(cliente_admin, curso):
    from models import Clase
    r = cliente_admin.post(f"/admin/cursos/{curso}/clases/nueva", data={
        "titulo": "Clase 3 · Pressing", "descripcion": "Presión alta", "fecha": "2026-12-01T19:30",
        "meet_link": "https://meet.google.com/zzz", "publicada": "y"})
    assert r.status_code == 302
    cid = id_clase("Clase 3 · Pressing")
    with ctx():
        c = db.session.get(Clase, cid)
        assert c.orden == 3 and c.fecha.strftime("%Y-%m-%d %H:%M") == "2026-12-01 19:30"

    # La edición muestra la fecha en el formato del input y permite agregar la grabación
    assert 'value="2026-12-01T19:30"' in cliente_admin.get(f"/admin/clases/{cid}/editar").get_data(as_text=True)
    cliente_admin.post(f"/admin/clases/{cid}/editar", data={
        "titulo": "Clase 3 · Pressing", "fecha": "2026-12-01T19:30", "orden": "3", "publicada": "y",
        "meet_link": "https://meet.google.com/zzz", "grabacion": "https://youtu.be/abc"})
    with ctx():
        assert db.session.get(Clase, cid).estado() == "grabada"

    cliente_admin.post(f"/admin/clases/{cid}/eliminar")
    with ctx():
        assert db.session.get(Clase, cid) is None


def test_enlaces_que_no_son_http_se_rechazan(cliente_admin, curso):
    from models import Clase
    r = cliente_admin.post(f"/admin/cursos/{curso}/clases/nueva", data={
        "titulo": "Clase mala", "grabacion": "javascript:alert(1)", "publicada": "y"})
    assert r.status_code == 200 and b"http://" in r.data
    with ctx():
        assert db.session.query(Clase).filter_by(titulo="Clase mala").count() == 0


def test_solo_admin_gestiona_clases(cliente, cliente_alumno, curso):
    assert cliente.get(f"/admin/cursos/{curso}/clases").status_code == 302
    assert cliente_alumno.get(f"/admin/cursos/{curso}/clases").status_code == 403
    assert cliente_alumno.post(f"/admin/clases/{id_clase('Clase 1 grabada')}/eliminar").status_code == 403


def test_landing_muestra_cuantas_clases_tiene_cada_curso(cliente, curso):
    assert b"2 clases" in cliente.get("/").data


# ---------------------------------------------------------------- dar el privilegio de alumno

def crear_curso(nombre, precio=5000):
    from models import Curso
    with ctx():
        c = Curso(nombre=nombre, precio=precio, activo=True)
        db.session.add(c)
        db.session.commit()
        return c.id


def test_dar_acceso_a_varios_cursos_de_una(cliente_admin, curso):
    otro = crear_curso("Curso Básico")
    r = cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_ids": [curso, otro], "alumno_nombre": "Pago por PayPal", "email": "paypal@correo.com"},
        follow_redirects=True)
    assert b"Acceso concedido" in r.data
    with ctx():
        u = db.session.query(Usuario).filter_by(email="paypal@correo.com").one()
        assert sorted(i.curso_id for i in u.inscripciones) == sorted([curso, otro])
        assert all(i.origen == "manual" and i.estado == "pagada" for i in u.inscripciones)


def test_dar_acceso_a_todos_los_cursos_activos(cliente_admin, curso):
    crear_curso("Curso Básico")
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "todos_los_cursos": "1", "alumno_nombre": "Becado", "email": "beca@correo.com"})
    assert contar(Inscripcion) == 2


def test_dar_acceso_a_una_cuenta_que_ya_existe(cliente_admin, cliente_alumno, curso):
    # Ana ya se registró por su cuenta; el dueño le da acceso sin crear otra cuenta
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_ids": curso, "alumno_nombre": "Ana Alumna", "email": "ANA@correo.com"})
    assert contar(Usuario) == 2  # dueño + Ana
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 200


def test_dar_acceso_dos_veces_no_duplica(cliente_admin, curso):
    datos = {"curso_ids": curso, "alumno_nombre": "Lucho", "email": "lucho@correo.com"}
    cliente_admin.post("/admin/inscripciones/nueva", data=datos)
    r = cliente_admin.post("/admin/inscripciones/nueva", data=datos, follow_redirects=True)
    assert b"ya ten" in r.data and contar(Inscripcion) == 1


def test_dar_acceso_exige_email_valido_y_curso(cliente_admin, curso):
    r = cliente_admin.post("/admin/inscripciones/nueva", data={"curso_ids": curso, "alumno_nombre": "Sin mail", "email": ""},
                           follow_redirects=True)
    assert "email válido".encode() in r.data and contar(Inscripcion) == 0
    r = cliente_admin.post("/admin/inscripciones/nueva", data={"alumno_nombre": "Sin curso", "email": "a@b.com"},
                           follow_redirects=True)
    assert b"al menos un curso" in r.data and contar(Usuario) == 1


def test_quitar_acceso_desde_alumnos_vuelve_a_la_misma_pagina(cliente_admin, cliente_alumno, curso):
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_ids": curso, "alumno_nombre": "Ana Alumna", "email": "ana@correo.com"})
    assert b"quitar acceso" in cliente_admin.get("/admin/usuarios").data
    r = cliente_admin.post("/admin/inscripciones/1/eliminar", data={"next": "/admin/usuarios"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/usuarios")
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302  # ya no entra


def test_quitar_acceso_no_sigue_destinos_externos(cliente_admin, curso):
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_ids": curso, "alumno_nombre": "Ana", "email": "ana@correo.com"})
    r = cliente_admin.post("/admin/inscripciones/1/eliminar", data={"next": "//evil.com"})
    assert "evil.com" not in r.headers["Location"]
