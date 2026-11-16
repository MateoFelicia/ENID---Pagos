"""Prueba local del flujo de pago aprobado, sin tarjeta ni llamadas reales."""
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app as app_module
from db import db
from models import Curso, Inscripcion, Pago, Usuario


class PaymentFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = app_module.app
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        )
        # Flask-SQLAlchemy construye el engine al inicializar la app. Sustituimos
        # explícitamente ese engine antes de cualquier consulta de la prueba.
        with app.app_context():
            extension = app.extensions["sqlalchemy"]
            cls.original_engine = db.engines[None]
            expected_real_path = str(Path(app.instance_path) / "pagos.db")
            if str(cls.original_engine.url.database).lower() != expected_real_path.lower():
                raise RuntimeError("No se pudo verificar la conexión original; se cancela la prueba")
            cls.test_engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            extension._app_engines[app][None] = cls.test_engine

    @classmethod
    def tearDownClass(cls):
        with app_module.app.app_context():
            db.session.remove()
            app_module.app.extensions["sqlalchemy"]._app_engines[app_module.app][None] = cls.original_engine
        cls.test_engine.dispose()

    def setUp(self):
        self.app_context = app_module.app.app_context()
        self.app_context.push()
        db.session.remove()
        db.create_all()
        self.usuario = Usuario(nombre="Alumna de prueba", email="test@example.com")
        self.usuario.establecer_password("password-local")
        curso = Curso(nombre="Curso simulado", descripcion="", precio=Decimal("12500.00"))
        db.session.add_all([self.usuario, curso])
        db.session.flush()
        self.inscripcion = Inscripcion(
            curso_id=curso.id,
            usuario_id=self.usuario.id,
            alumno_nombre=self.usuario.nombre,
            monto=Decimal("12500.00"),
            estado="pendiente",
            origen="web",
        )
        db.session.add(self.inscripcion)
        db.session.flush()
        self.pago = Pago(
            inscripcion_id=self.inscripcion.id,
            preferencia_id="pref-simulada-123",
            monto=Decimal("12500.00"),
            moneda="ARS",
            estado="pendiente",
        )
        db.session.add(self.pago)
        db.session.commit()
        self.usuario_id = self.usuario.id
        self.inscripcion_id = self.inscripcion.id
        self.client = app_module.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.usuario_id)
            session["_fresh"] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_email_confirmation_is_persisted(self):
        token = app_module.generar_token_email(self.usuario.email)
        response = self.client.get(f"/confirmar-email/{token}")
        self.assertEqual(response.status_code, 302)
        usuario = db.session.get(Usuario, self.usuario_id)
        self.assertTrue(usuario.email_confirmado)

    def test_login_is_blocked_until_email_confirmation(self):
        with self.client.session_transaction() as session:
            session.clear()
        response = self.client.post(
            "/iniciar-sesion",
            data={"email": self.usuario.email, "password": "password-local"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("confirmá tu correo".encode(), response.data)
        with self.client.session_transaction() as session:
            self.assertNotIn("_user_id", session)

    def test_registration_sends_confirmation_and_creates_unconfirmed_user(self):
        with self.client.session_transaction() as session:
            session.clear()
        with patch.object(app_module, "enviar_email", return_value=True) as send_email:
            response = self.client.post(
                "/registro",
                data={
                    "nombre": "Nueva Alumna",
                    "email": "nueva@example.com",
                    "password": "password-local",
                    "confirmar_password": "password-local",
                },
            )
        self.assertEqual(response.status_code, 302)
        send_email.assert_called_once()
        nuevo_usuario = db.session.execute(
            db.select(Usuario).where(Usuario.email == "nueva@example.com")
        ).scalar_one()
        self.assertFalse(nuevo_usuario.email_confirmado)

    def test_aprobado_se_guarda_y_aparece_en_mis_inscripciones(self):
        respuesta_mp = {
            "status": 200,
            "response": {
                "id": 987654321,
                "status": "approved",
                "external_reference": str(self.inscripcion_id),
                "transaction_amount": 12500.00,
                "currency_id": "ARS",
                "preference_id": "pref-simulada-123",
            },
        }
        with patch.dict("os.environ", {"MP_ACCESS_TOKEN": "token-simulado"}), \
             patch.object(app_module.mercadopago, "SDK") as sdk:
            sdk.return_value.payment.return_value.get.return_value = respuesta_mp
            pagina = self.client.get("/pago/exitoso?payment_id=987654321", follow_redirects=True)

        self.assertEqual(pagina.status_code, 200)
        self.assertIn("Curso simulado".encode(), pagina.data)
        self.assertIn("Pagada".encode(), pagina.data)
        pago = db.session.get(Pago, self.pago.id)
        inscripcion = db.session.get(Inscripcion, self.inscripcion_id)
        self.assertEqual(pago.estado, "approved")
        self.assertEqual(pago.pago_externo_id, "987654321")
        self.assertEqual(inscripcion.estado, "pagada")
        self.assertEqual(inscripcion.usuario_id, self.usuario_id)
        sdk.return_value.payment.return_value.get.assert_called_once_with("987654321")


if __name__ == "__main__":
    unittest.main(verbosity=2)
