from db import db

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    es_admin = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.false()
    )

    inscripciones = db.relationship(
        "Inscripcion",
        back_populates="usuario"
    )

    def establecer_password(self, password):
        self.password_hash = generate_password_hash(password)

    def verificar_password(self, password):
        return check_password_hash(self.password_hash, password)
    
class Curso(db.Model):
    __tablename__ = "cursos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.String(300))
    precio = db.Column(db.Numeric(10, 2), nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    meet_link = db.Column(db.String(300))
    fecha = db.Column(db.DateTime)
    grabacion = db.Column(db.String(300))

    inscripciones = db.relationship("Inscripcion", back_populates="curso")


class Inscripcion(db.Model):
    __tablename__ = "inscripciones"

    id = db.Column(db.Integer, primary_key=True)
    curso_id = db.Column(db.Integer, db.ForeignKey("cursos.id"), nullable=False)
    alumno_nombre = db.Column(db.String(120), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    estado = db.Column(db.String(20), default="pendiente", nullable=False)
    origen = db.Column(db.String(20), default="web", nullable=False)

    curso = db.relationship("Curso", back_populates="inscripciones")
    usuario = db.relationship("Usuario", back_populates="inscripciones")
    
    pagos = db.relationship("Pago", back_populates="inscripcion")
    
    usuario_id = db.Column(
    db.Integer,
    db.ForeignKey("usuarios.id"),
    nullable=True
    )

    def tiene_acceso(self):
        if self.estado == "pagada":
            return True
        if self.origen == "manual":
            return True
        return False
    
class Pago(db.Model):
    __tablename__ = "pagos"

    id = db.Column(db.Integer, primary_key=True)
    inscripcion_id = db.Column(
        db.Integer,
        db.ForeignKey("inscripciones.id"),
        nullable=False
    )
    proveedor = db.Column(
        db.String(30),
        default="mercado_pago",
        nullable=False
    )
    preferencia_id = db.Column(db.String(100))
    pago_externo_id = db.Column(db.String(100))
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    moneda = db.Column(db.String(3), default="ARS", nullable=False)
    estado = db.Column(db.String(30), default="pendiente", nullable=False)

    inscripcion = db.relationship("Inscripcion", back_populates="pagos")