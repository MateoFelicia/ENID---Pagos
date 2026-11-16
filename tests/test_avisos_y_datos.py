"""Mails, avisos de clases, datos del alumno, importación CSV y chequeo de configuración."""
from datetime import timedelta

import pytest

from conftest import crear_usuario, ctx, headers_firmados, pago_mp
from db import db
from models import Clase, Curso, EnvioAviso, Inscripcion, Usuario, ahora_argentina
from test_flujo import contar, enviar_webhook


def dar_acceso(curso_id, email="ana@correo.com", nombre="Ana Alumna", avisos=True):
    """Crea un alumno con acceso manual al curso (sin pasar por la web)."""
    with ctx():
        u = db.session.query(Usuario).filter_by(email=email).first()
        if u is None:
            u = Usuario(nombre=nombre, email=email, avisos_email=avisos)
            u.establecer_password("password123")
            db.session.add(u)
            db.session.flush()
        db.session.add(Inscripcion(curso_id=curso_id, usuario_id=u.id, alumno_nombre=nombre, monto=1000,
                                   estado="pagada", origen="manual", medio="paypal"))
        db.session.commit()
        return u.id


def poner_fecha_clase(titulo, delta, **extra):
    with ctx():
        c = db.session.query(Clase).filter_by(titulo=titulo).one()
        c.fecha = ahora_argentina() + delta
        for k, v in extra.items():
            setattr(c, k, v)
        db.session.commit()
        return c.id


def correr_recordatorios(**kw):
    from avisos import enviar_recordatorios
    with ctx():
        return [(c.titulo, t, r) for c, t, r in enviar_recordatorios(**kw)]


# ------------------------------------------------------------------ datos del alumno + mails de cuenta

def test_registro_guarda_alta_y_manda_bienvenida(cliente, correo):
    cliente.post("/registro", data={"nombre": "Ana Alumna", "email": "ana@correo.com",
                                    "password": "password123", "confirmar_password": "password123"})
    with ctx():
        u = db.session.query(Usuario).one()
        assert u.creado_en is not None and u.ultimo_ingreso is not None and u.avisos_email is True
    assert len(correo) == 1 and correo[0].recipients == ["ana@correo.com"]
    assert "Bienvenido" in correo[0].subject and "ENID" in correo[0].html
    assert correo[0].body and "Hola" not in correo[0].body[:0]  # versión de texto plano incluida


def test_login_actualiza_el_ultimo_ingreso(app):
    uid = crear_usuario("Ana", "ana@correo.com")
    with ctx():
        assert db.session.get(Usuario, uid).ultimo_ingreso is None
    app.test_client().post("/iniciar-sesion", data={"email": "ana@correo.com", "password": "password123"})
    with ctx():
        assert db.session.get(Usuario, uid).ultimo_ingreso is not None


def test_pago_aprobado_guarda_fecha_y_manda_un_solo_comprobante(cliente_alumno, curso, mp, correo):
    cliente_alumno.post(f"/comprar/{curso}")
    mp.pagos["9"] = pago_mp(9, 1, 12000)
    enviar_webhook(cliente_alumno, 9)
    enviar_webhook(cliente_alumno, 9, request_id="req-2")  # MP reintenta: no debe duplicar el mail
    comprobantes = [m for m in correo if "Pago confirmado" in m.subject]
    assert len(comprobantes) == 1 and "12.000" in comprobantes[0].html
    with ctx():
        assert db.session.get(Inscripcion, 1).pagado_en is not None


def test_dar_acceso_guarda_medio_nota_y_manda_invitacion(cliente_admin, curso, correo):
    cliente_admin.post("/admin/inscripciones/nueva", data={
        "curso_ids": curso, "alumno_nombre": "Pago PayPal", "email": "nuevo@correo.com",
        "medio": "paypal", "nota": "USD 25 del 12/10"})
    with ctx():
        i = db.session.query(Inscripcion).one()
        assert (i.origen, i.medio, i.nota, i.estado) == ("manual", "paypal", "USD 25 del 12/10", "pagada")
        assert i.pagado_en is not None and i.medio_legible == "PayPal"
    assert len(correo) == 1 and correo[0].recipients == ["nuevo@correo.com"]
    assert "/resetear-password/" in correo[0].html and "7 días" in correo[0].html


def test_enlace_de_invitacion_dura_7_dias_y_el_de_recuperacion_1_hora(app, monkeypatch):
    from itsdangerous.timed import TimestampSigner
    import emailer
    with ctx():
        invitacion = emailer.generar_token_invitacion("a@b.com")
        reset = emailer.generar_token_reset("a@b.com")
        assert emailer.verificar_token_acceso(reset) == "a@b.com"  # recién generado, sirve
        real = TimestampSigner.get_timestamp
        for dias, inv_ok, reset_ok in ((0.01, True, True), (0.1, True, False), (3, True, False), (8, False, False)):
            monkeypatch.setattr(TimestampSigner, "get_timestamp",
                                lambda self, d=dias: real(self) + int(d * 86400))
            assert (emailer.verificar_token_acceso(invitacion) == "a@b.com") is inv_ok, dias
            assert (emailer.verificar_token_acceso(reset) == "a@b.com") is reset_ok, dias


def test_csv_incluye_fechas_medio_y_nota(cliente_admin, curso):
    dar_acceso(curso)
    texto = cliente_admin.get("/admin/usuarios.csv").get_data(as_text=True)
    assert "PayPal" in texto and "Fecha de pago o acceso" in texto


def test_importes_en_formato_argentino(app):
    from app import formato_ars
    assert formato_ars(5000) == "5.000" and formato_ars(12500.5) == "12.500,50" and formato_ars(0) == "0"


def test_html_a_texto_conserva_los_enlaces():
    from emailer import html_a_texto
    assert "Entrar (https://x.com/a)" in html_a_texto('<p>Hola</p><a href="https://x.com/a">Entrar</a>')


# ------------------------------------------------------------------ mi cuenta y baja de avisos

def test_mi_cuenta_cambia_nombre_y_avisos(cliente_alumno):
    cliente_alumno.post("/mi-cuenta", data={"accion": "cuenta", "cuenta-nombre": "Ana María"})
    with ctx():
        u = db.session.query(Usuario).filter_by(email="ana@correo.com").one()
        assert u.nombre == "Ana María" and u.avisos_email is False  # casilla desmarcada = baja


def test_mi_cuenta_cambia_la_contrasena(app, cliente_alumno):
    r = cliente_alumno.post("/mi-cuenta", data={"accion": "password", "pw-actual": "mala",
                                                 "pw-nueva": "nuevaclave123", "pw-confirmar": "nuevaclave123"})
    assert b"no es correcta" in r.data
    cliente_alumno.post("/mi-cuenta", data={"accion": "password", "pw-actual": "password123",
                                             "pw-nueva": "nuevaclave123", "pw-confirmar": "nuevaclave123"})
    nuevo = app.test_client()
    nuevo.post("/iniciar-sesion", data={"email": "ana@correo.com", "password": "nuevaclave123"})
    assert nuevo.get("/mi-cuenta").status_code == 200


def test_mi_cuenta_exige_sesion(cliente):
    assert cliente.get("/mi-cuenta").status_code == 302


def test_baja_de_avisos_sin_iniciar_sesion(app, cliente):
    import emailer
    uid = crear_usuario("Ana", "ana@correo.com")
    with ctx():
        token = emailer.generar_token_baja(uid)
    assert "Sí, darme de baja".encode() in cliente.get(f"/baja-avisos/{token}").data
    with ctx():
        assert db.session.get(Usuario, uid).avisos_email is True  # un GET solo no da de baja (los antivirus abren enlaces)
    cliente.post(f"/baja-avisos/{token}")
    with ctx():
        assert db.session.get(Usuario, uid).avisos_email is False
    assert cliente.get("/baja-avisos/token-roto").status_code == 302


# ------------------------------------------------------------------ recordatorios de clases

def test_recordatorio_24h_llega_una_sola_vez(curso, correo):
    dar_acceso(curso)
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20))
    primera = correr_recordatorios()
    assert [(t, tipo, r["enviados"]) for t, tipo, r in primera] == [("Clase 2 en vivo", "24h", 1)]
    assert "mañana" in correo[0].subject and "/baja-avisos/" in correo[0].html
    assert correr_recordatorios()[0][2]["enviados"] == 0  # segunda corrida: ya avisado
    assert len(correo) == 1 and contar(EnvioAviso) == 1


def test_recordatorio_1h_se_suma_al_de_24h(curso, correo):
    dar_acceso(curso)
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20))
    correr_recordatorios()
    poner_fecha_clase("Clase 2 en vivo", timedelta(minutes=40))
    resultado = correr_recordatorios()
    assert [(tipo, r["enviados"]) for _, tipo, r in resultado] == [("1h", 1)]
    assert "en una hora" in correo[-1].subject


@pytest.mark.parametrize("delta", [timedelta(hours=30), timedelta(hours=6), timedelta(hours=-2)])
def test_no_hay_recordatorio_fuera_de_las_ventanas(curso, correo, delta):
    dar_acceso(curso)
    poner_fecha_clase("Clase 2 en vivo", delta)
    assert correr_recordatorios() == [] and correo == []


def test_recordatorios_respetan_baja_borradores_y_grabadas(curso, correo):
    dar_acceso(curso, avisos=False)  # se dio de baja
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20))
    assert correr_recordatorios()[0][2]["enviados"] == 0
    dar_acceso(curso, email="otro@correo.com", nombre="Otro")
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20), publicada=False)
    assert correr_recordatorios() == []
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20), publicada=True, grabacion="https://x.com/v")
    assert correr_recordatorios() == []
    assert correo == []


def test_solo_reciben_recordatorio_quienes_tienen_acceso(curso, correo):
    crear_usuario("Sin acceso", "sin@correo.com")
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20))
    assert correr_recordatorios()[0][2]["enviados"] == 0 and correo == []


def test_dry_run_no_envia_ni_registra(curso, correo):
    dar_acceso(curso)
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20))
    r = correr_recordatorios(dry_run=True)
    assert r[0][2]["pendientes"] == 1 and r[0][2]["enviados"] == 0
    assert correo == [] and contar(EnvioAviso) == 0


def test_comando_enviar_recordatorios(app, curso, correo):
    dar_acceso(curso)
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20))
    resultado = app.test_cli_runner().invoke(args=["enviar-recordatorios"])
    assert resultado.exit_code == 0 and "1 enviados" in resultado.output and len(correo) == 1


def test_tarea_http_de_recordatorios_pide_token(app, cliente, curso, correo, monkeypatch):
    dar_acceso(curso)
    poner_fecha_clase("Clase 2 en vivo", timedelta(hours=20))
    monkeypatch.delenv("CRON_TOKEN", raising=False)
    assert cliente.post("/tareas/recordatorios").status_code == 404  # desactivada sin token
    monkeypatch.setenv("CRON_TOKEN", "secreto-cron")
    assert cliente.post("/tareas/recordatorios").status_code == 403
    assert cliente.post("/tareas/recordatorios", headers={"Authorization": "Bearer otro"}).status_code == 403
    r = cliente.post("/tareas/recordatorios", headers={"Authorization": "Bearer secreto-cron"})
    assert r.status_code == 200 and r.get_json()["avisos"][0]["enviados"] == 1
    assert cliente.get("/tareas/recordatorios?token=secreto-cron").status_code == 200


# ------------------------------------------------------------------ aviso al guardar una clase

def test_avisar_clase_nueva_por_mail_una_sola_vez(cliente_admin, curso, correo):
    dar_acceso(curso)
    datos = {"titulo": "Clase 3 · Pressing", "publicada": "y", "avisar": "y", "grabacion": "https://youtu.be/x"}
    r = cliente_admin.post(f"/admin/cursos/{curso}/clases/nueva", data=datos, follow_redirects=True)
    assert b"Avisamos por mail a 1 alumno" in r.data
    assert "Nueva clase" in correo[0].subject and "Pressing" in correo[0].html
    with ctx():
        cid = db.session.query(Clase).filter_by(titulo="Clase 3 · Pressing").one().id
    r = cliente_admin.post(f"/admin/clases/{cid}/editar", data={**datos, "orden": "3"}, follow_redirects=True)
    assert "ya habían recibido".encode() in r.data and len(correo) == 1


def test_avisar_que_ya_esta_la_grabacion(cliente_admin, curso, correo):
    dar_acceso(curso)
    with ctx():
        cid = db.session.query(Clase).filter_by(titulo="Clase 2 en vivo").one().id
    cliente_admin.post(f"/admin/clases/{cid}/editar", data={
        "titulo": "Clase 2 en vivo", "orden": "2", "publicada": "y", "avisar": "y",
        "meet_link": "https://meet.google.com/abc", "grabacion": "https://youtu.be/lista"})
    assert "Ya está la grabación" in correo[0].subject


def test_no_se_avisa_si_es_borrador_ni_sin_casilla(cliente_admin, curso, correo):
    dar_acceso(curso)
    cliente_admin.post(f"/admin/cursos/{curso}/clases/nueva", data={"titulo": "Borrador", "avisar": "y"})
    cliente_admin.post(f"/admin/cursos/{curso}/clases/nueva", data={"titulo": "Sin aviso", "publicada": "y"})
    assert correo == []


# ------------------------------------------------------------------ importación CSV (lógica)

CSV_OK = "nombre,email,cursos,medio,nota\nAna Pérez,ana@x.com,Curso Pro,transferencia,Pagó el 12/10\nLuis,LUIS@X.COM,todos,beca,\n"


def parsear(texto):
    from importador import parsear as p
    with ctx():
        cursos = db.session.query(Curso).all()
        filas, errores = p(texto, cursos)
        return [(f.linea, f.nombre, f.email, [c.nombre for c in f.cursos], f.medio, f.nota,
                 list(f.errores), f.repetida_de, list(f.avisos)) for f in filas], errores


def test_importador_lee_filas_validas(curso):
    filas, errores = parsear(CSV_OK)
    assert errores == []
    assert filas[0][:6] == (2, "Ana Pérez", "ana@x.com", ["Curso Pro"], "transferencia", "Pagó el 12/10")
    assert filas[1][2:5] == ("luis@x.com", ["Curso Pro"], "beca")  # "todos" = todos los activos


def test_importador_acepta_punto_y_coma_bom_y_encabezados_con_acentos(curso):
    texto = "\ufeffAlumno;Correo electrónico;Curso\nAna;ana@x.com;curso PRO\n"
    filas, errores = parsear(texto)
    assert errores == [] and filas[0][3] == ["Curso Pro"]  # sin importar mayúsculas


def test_importador_reporta_errores_por_fila(curso):
    texto = "nombre,email,cursos\n,ana@x.com,Curso Pro\nLuis,no-es-mail,Curso Pro\nMaría,m@x.com,Curso Fantasma\nPedro,p@x.com,\n"
    filas, _ = parsear(texto)
    errores = [f[6] for f in filas]
    assert "falta el nombre" in errores[0]
    assert "el email no es válido" in errores[1]
    assert errores[2] == ["curso que no existe: Curso Fantasma"]
    assert errores[3] == ["falta el curso"]


def test_importador_une_emails_repetidos(curso):
    with ctx():
        db.session.add(Curso(nombre="Curso Básico", precio=100, activo=True)); db.session.commit()
    texto = "nombre,email,cursos\nAna,ana@x.com,Curso Pro\nAna,ana@x.com,Curso Básico\n"
    filas, _ = parsear(texto)
    assert filas[0][3] == ["Curso Pro", "Curso Básico"] and filas[1][7] == 2


def test_importador_columnas_faltantes_y_archivo_vacio(curso):
    assert "Faltan columnas" in parsear("nombre,email\nAna,a@x.com\n")[1][0]
    assert parsear("   \n")[1] == ["El archivo está vacío."]


def test_importador_medio_desconocido_avisa(curso):
    filas, _ = parsear("nombre,email,cursos,medio\nAna,a@x.com,Curso Pro,bitcoin\n")
    assert filas[0][4] == "otro" and "desconocido" in filas[0][8][0]


# ------------------------------------------------------------------ importación CSV (web)

def subir(cliente, texto, accion="previsualizar", **extra):
    import io
    if accion == "previsualizar":
        return cliente.post("/admin/alumnos/importar", data={
            "accion": accion, "archivo": (io.BytesIO(texto.encode("utf-8")), "alumnos.csv")},
            content_type="multipart/form-data")
    return cliente.post("/admin/alumnos/importar", data={"accion": accion, "contenido": texto, **extra})


def test_vista_previa_no_guarda_nada(cliente_admin, curso):
    r = subir(cliente_admin, CSV_OK)
    html = r.get_data(as_text=True)
    assert "2 listas para importar" in html and "ana@x.com" in html and "nueva" in html
    assert contar(Inscripcion) == 0 and contar(Usuario) == 1


def test_importar_crea_cuentas_y_accesos_y_es_idempotente(cliente_admin, curso, correo):
    r = subir(cliente_admin, CSV_OK, "importar", invitar="1")
    html = r.get_data(as_text=True)
    assert "Importación lista" in html and "/resetear-password/" in html
    assert len(correo) == 2  # un mail de acceso por alumno nuevo
    with ctx():
        ana = db.session.query(Usuario).filter_by(email="ana@x.com").one()
        i = ana.inscripciones[0]
        assert (i.origen, i.medio, i.nota, i.estado) == ("manual", "transferencia", "Pagó el 12/10", "pagada")
    # Importar el mismo archivo otra vez no duplica nada
    r = subir(cliente_admin, CSV_OK, "importar")
    assert "ya existían" in r.get_data(as_text=True) and contar(Inscripcion) == 2 and contar(Usuario) == 3


def test_importar_saltea_filas_con_errores(cliente_admin, curso):
    subir(cliente_admin, "nombre,email,cursos\nAna,ana@x.com,Curso Pro\nMal,mal,Curso Pro\n", "importar")
    assert contar(Usuario) == 2 and contar(Inscripcion) == 1


def test_importar_sin_mail_configurado_muestra_los_enlaces(cliente_admin, curso):
    r = subir(cliente_admin, CSV_OK, "importar", invitar="1")
    assert "Los mails todavía no están configurados" in r.get_data(as_text=True)


def test_importar_rechaza_archivos_enormes_y_a_quien_no_es_admin(cliente_admin, cliente_alumno, curso):
    grande = "nombre,email,cursos\n" + ("Ana,ana@x.com,Curso Pro\n" * 30000)
    assert b"pesa m" in cliente_admin.post("/admin/alumnos/importar", data={
        "accion": "previsualizar", "archivo": (__import__("io").BytesIO(grande.encode()), "a.csv")},
        content_type="multipart/form-data", follow_redirects=True).data
    assert subir(cliente_alumno, CSV_OK).status_code == 403
    assert cliente_admin.get("/admin/alumnos/plantilla.csv").mimetype == "text/csv"


# ------------------------------------------------------------------ chequeo de configuración

def test_verificar_config_detecta_problemas(app, curso):
    r = app.test_cli_runner().invoke(args=["verificar-config"])
    assert r.exit_code == 1 and "✘" in r.output and "error(es)" in r.output


def test_verificar_config_pasa_con_todo_en_orden(app, cliente_admin, curso, monkeypatch):
    from flask_migrate import stamp
    monkeypatch.setitem(app.config, "SECRET_KEY", "k" * 48)
    monkeypatch.setenv("PUBLIC_URL", "https://cursos.enid.com.ar")
    monkeypatch.setenv("MP_ACCESS_TOKEN", "APP_USR-123")
    monkeypatch.setenv("MP_WEBHOOK_SECRET", "s")
    with ctx():
        stamp(revision="head")
    r = app.test_cli_runner().invoke(args=["verificar-config"])
    assert r.exit_code == 0 and "0 error(es)" in r.output, r.output
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-123")
    assert app.test_cli_runner().invoke(args=["verificar-config"]).exit_code == 1
