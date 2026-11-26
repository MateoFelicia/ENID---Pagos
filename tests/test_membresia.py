"""Membresía mensual: suscripción con Mercado Pago (preapproval), acceso a todos los cursos y cancelación."""
from datetime import timedelta

from conftest import ctx, headers_firmados
from db import db
from models import PlanMembresia, Suscripcion, ahora_argentina


def activar_plan(precio=9000, activo=True):
    with ctx():
        db.session.add(PlanMembresia(nombre="Membresía ENID", precio=precio, activo=activo))
        db.session.commit()


def webhook(cliente, data_id, tipo="subscription_preapproval"):
    return cliente.post(
        f"/webhooks/mercadopago?data.id={data_id}&type={tipo}",
        json={"type": tipo, "data": {"id": str(data_id)}},
        headers=headers_firmados(data_id),
    )


def mp_aprueba(mp, pid="pre-1", dias=30):
    proximo = (ahora_argentina() + timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.000-03:00")
    mp.preapprovals[pid].update(status="authorized", next_payment_date=proximo)


def suscripcion():
    with ctx():
        return db.session.execute(db.select(Suscripcion)).scalar_one()


# ---------------------------------------------------------------- alta

def test_sin_plan_a_la_venta_no_hay_membresia(cliente_alumno):
    assert cliente_alumno.get("/membresia").status_code == 404
    assert cliente_alumno.post("/membresia/suscribirme").status_code == 302
    with ctx():
        assert db.session.query(Suscripcion).count() == 0


def test_suscribirse_manda_a_mercado_pago_con_el_precio_del_plan(cliente_alumno, mp):
    activar_plan(9000)
    assert b"9.000" in cliente_alumno.get("/").data  # tarjeta en la portada
    r = cliente_alumno.post("/membresia/suscribirme")
    assert r.status_code == 302 and r.headers["Location"] == "https://mp.test/suscripcion/pre-1"
    enviado = mp.creados[0]
    assert enviado["payer_email"] == "ana@correo.com"
    assert enviado["auto_recurring"] == {"frequency": 1, "frequency_type": "months",
                                          "transaction_amount": 9000.0, "currency_id": "ARS"}
    s = suscripcion()
    assert enviado["external_reference"] == f"sus-{s.id}" and s.estado == "pending" and s.mp_preapproval_id == "pre-1"


def test_reintentar_no_duplica_suscripciones(cliente_alumno, mp):
    activar_plan()
    cliente_alumno.post("/membresia/suscribirme")
    cliente_alumno.post("/membresia/suscribirme")
    with ctx():
        assert db.session.query(Suscripcion).count() == 1


# ---------------------------------------------------------------- acceso

def test_webhook_activa_y_da_acceso_a_todos_los_cursos(cliente_alumno, curso, mp):
    activar_plan()
    cliente_alumno.post("/membresia/suscribirme")
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302  # todavía no

    # Un aviso de "pending" no da acceso
    assert webhook(cliente_alumno, "pre-1").status_code == 200
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302

    mp_aprueba(mp)
    assert webhook(cliente_alumno, "pre-1").status_code == 200
    assert suscripcion().estado == "authorized"
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 200
    assert cliente_alumno.get(f"/curso/{curso}/clase/1").status_code == 200
    html = cliente_alumno.get("/mis-inscripciones").get_data(as_text=True)
    assert "Tenés acceso a todos los cursos" in html


def test_volver_de_mercado_pago_confirma_contra_la_api(cliente_alumno, curso, mp):
    activar_plan()
    cliente_alumno.post("/membresia/suscribirme")
    # La URL sola no alcanza
    cliente_alumno.get("/membresia/vuelta?preapproval_id=pre-1")
    assert suscripcion().estado == "pending"
    mp_aprueba(mp)
    r = cliente_alumno.get("/membresia/vuelta?preapproval_id=pre-1")
    assert r.status_code == 302 and "/mis-inscripciones" in r.headers["Location"]
    assert suscripcion().estado == "authorized"


def test_vuelta_con_preapproval_ajeno_no_hace_nada(app, cliente_alumno, mp):
    activar_plan()
    cliente_alumno.post("/membresia/suscribirme")
    mp_aprueba(mp)
    otro = app.test_client()
    otro.post("/registro", data={"nombre": "Beto", "email": "beto@correo.com",
                                 "password": "password123", "confirmar_password": "password123"})
    otro.get("/membresia/vuelta?preapproval_id=pre-1")
    assert suscripcion().estado == "pending"  # solo el webhook o su dueña la sincronizan


def test_monto_distinto_no_activa(cliente_alumno, mp):
    activar_plan(9000)
    cliente_alumno.post("/membresia/suscribirme")
    mp_aprueba(mp)
    mp.preapprovals["pre-1"]["auto_recurring"]["transaction_amount"] = 10.0
    webhook(cliente_alumno, "pre-1")
    assert suscripcion().estado == "pending"


def test_webhook_de_preapproval_desconocido_pide_reintento(cliente):
    assert webhook(cliente, "no-existe").status_code == 500


def test_webhook_sin_firma_valida_se_rechaza(cliente_alumno, mp):
    activar_plan()
    cliente_alumno.post("/membresia/suscribirme")
    mp_aprueba(mp)
    r = cliente_alumno.post(
        "/webhooks/mercadopago?data.id=pre-1&type=subscription_preapproval",
        json={"type": "subscription_preapproval", "data": {"id": "pre-1"}},
        headers=headers_firmados("pre-1", secreto="otro-secreto"),
    )
    assert r.status_code == 401 and suscripcion().estado == "pending"


# ---------------------------------------------------------------- baja

def test_cancelar_mantiene_el_acceso_hasta_el_mes_pagado(cliente_alumno, curso, mp):
    activar_plan()
    cliente_alumno.post("/membresia/suscribirme")
    mp_aprueba(mp, dias=12)
    webhook(cliente_alumno, "pre-1")

    r = cliente_alumno.post("/membresia/cancelar", follow_redirects=True)
    assert "seguís teniendo acceso hasta" in r.get_data(as_text=True)
    s = suscripcion()
    assert s.estado == "cancelled" and s.acceso_hasta is not None
    assert mp.preapprovals["pre-1"]["status"] == "cancelled"  # dejó de cobrarse en Mercado Pago
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 200  # todavía tiene acceso

    # Pasado ese día, pierde el acceso
    with ctx():
        db.session.get(Suscripcion, s.id).acceso_hasta = ahora_argentina() - timedelta(minutes=1)
        db.session.commit()
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302


def test_si_mercado_pago_la_cancela_por_falta_de_pago_se_corta_al_vencer(cliente_alumno, curso, mp):
    activar_plan()
    cliente_alumno.post("/membresia/suscribirme")
    mp_aprueba(mp, dias=-1)  # el cobro que vencía ayer no pasó
    webhook(cliente_alumno, "pre-1")
    mp.preapprovals["pre-1"]["status"] = "cancelled"
    webhook(cliente_alumno, "pre-1")
    assert suscripcion().estado == "cancelled"
    assert cliente_alumno.get(f"/curso/{curso}").status_code == 302


# ---------------------------------------------------------------- panel

def test_dueno_configura_el_plan_y_ve_las_suscripciones(cliente_admin, cliente_alumno, mp):
    r = cliente_admin.post("/admin/membresia", data={"nombre": "Membresía Pro", "precio": "15000", "activo": "y"})
    assert r.status_code == 302
    cliente_alumno.post("/membresia/suscribirme")
    assert mp.creados[0]["auto_recurring"]["transaction_amount"] == 15000.0
    html = cliente_admin.get("/admin/membresia").get_data(as_text=True)
    assert "Ana Alumna" in html and "Sin confirmar" in html


def test_alumno_no_entra_a_la_configuracion(cliente_alumno):
    assert cliente_alumno.get("/admin/membresia").status_code == 403
