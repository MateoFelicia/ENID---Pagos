import hashlib
import hmac
import os
import sys
import time

# La config se lee al importar app.py, así que se fija antes
os.environ["SECRET_KEY"] = "clave-de-test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ["MP_ACCESS_TOKEN"] = "APP_USR-test-token"
os.environ["MP_WEBHOOK_SECRET"] = "secreto-webhook-test"
os.environ["EMAIL_ASYNC"] = "0"
os.environ["MAIL_SUPPRESS_SEND"] = "1"
os.environ.pop("MAIL_USERNAME", None)
os.environ.pop("PUBLIC_URL", None)
os.environ.pop("NGROK_URL", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import app as app_module  # noqa: E402
from db import db  # noqa: E402
from models import Clase, Curso, Usuario, ahora_argentina  # noqa: E402
from datetime import timedelta  # noqa: E402


class FakeMercadoPago:
    """Reemplaza al SDK: guarda los pagos 'que existen' en Mercado Pago."""

    pagos = {}
    preferencias = []

    def __init__(self, token):
        self.token = token

    def preference(self):
        outer = self

        class _Pref:
            def create(self, data):
                FakeMercadoPago.preferencias.append(data)
                n = len(FakeMercadoPago.preferencias)
                return {
                    "status": 201,
                    "response": {"id": f"pref-{n}", "init_point": f"https://mp.test/checkout/pref-{n}"},
                }

        return _Pref()

    def payment(self):
        class _Pay:
            def get(self, payment_id):
                pago = FakeMercadoPago.pagos.get(str(payment_id))
                if pago is None:
                    return {"status": 404, "response": {}}
                return {"status": 200, "response": pago}

        return _Pay()


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    FakeMercadoPago.pagos = {}
    FakeMercadoPago.preferencias = []
    monkeypatch.setattr(app_module.mercadopago, "SDK", FakeMercadoPago)
    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    from extensions import limiter
    limiter.enabled = False  # los tests de límites lo encienden explícitamente
    # Sin contexto abierto durante los tests: cada request tiene el suyo, como en producción
    with app_module.app.app_context():
        db.create_all()
    yield
    with app_module.app.app_context():
        db.session.remove()
        db.drop_all()
        db.session.execute(db.text("DROP TABLE IF EXISTS alembic_version"))  # lo crean los tests que usan stamp()
        db.session.commit()


@pytest.fixture
def app():
    return app_module.app


@pytest.fixture
def correo(monkeypatch):
    """Activa el envío de mails (sin SMTP real) y devuelve la lista de mensajes enviados."""
    from extensions import mail
    monkeypatch.setitem(app_module.app.config, "MAIL_USERNAME", "enid@test.com")
    monkeypatch.setitem(app_module.app.config, "MAIL_DEFAULT_SENDER", "ENID <enid@test.com>")
    with mail.record_messages() as enviados:
        yield enviados


@pytest.fixture
def mp():
    return FakeMercadoPago


def ctx():
    return app_module.app.app_context()


@pytest.fixture
def curso():
    with ctx():
        c = Curso(nombre="Curso Pro", descripcion="Táctica avanzada", precio=12000, activo=True)
        db.session.add(c)
        db.session.flush()
        db.session.add_all([
            Clase(curso_id=c.id, orden=1, titulo="Clase 1 grabada",
                  grabacion="https://drive.google.com/grabacion"),
            Clase(curso_id=c.id, orden=2, titulo="Clase 2 en vivo",
                  fecha=ahora_argentina() + timedelta(days=2),
                  meet_link="https://meet.google.com/abc-defg-hij"),
        ])
        db.session.commit()
        return c.id


def crear_usuario(nombre, email, password="password123", admin=False):
    with ctx():
        u = Usuario(nombre=nombre, email=email, es_admin=admin)
        u.establecer_password(password)
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def cliente(app):
    return app.test_client()


@pytest.fixture
def cliente_admin(app):
    crear_usuario("Dueño", "dueno@enid.com", admin=True)
    c = app.test_client()
    c.post("/iniciar-sesion", data={"email": "dueno@enid.com", "password": "password123"})
    return c


@pytest.fixture
def cliente_alumno(app):
    c = app.test_client()
    c.post("/registro", data={
        "nombre": "Ana Alumna", "email": "ana@correo.com",
        "password": "password123", "confirmar_password": "password123",
    })
    return c


def headers_firmados(data_id, request_id="req-1", secreto=None, ts=None):
    secreto = secreto or os.environ["MP_WEBHOOK_SECRET"]
    ts = ts or str(int(time.time() * 1000))
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    firma = hmac.new(secreto.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={firma}", "x-request-id": request_id}


def pago_mp(payment_id, inscripcion_id, monto, status="approved", moneda="ARS"):
    return {
        "id": int(payment_id), "status": status, "transaction_amount": float(monto),
        "currency_id": moneda, "external_reference": str(inscripcion_id),
    }
