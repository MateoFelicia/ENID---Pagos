from datetime import datetime, timedelta, timezone

from db import db
from sqlalchemy import UniqueConstraint

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Argentina no tiene horario de verano: UTC-3 todo el año.
# Las fechas de las clases se cargan y se muestran en hora de Argentina.
ZONA_ARGENTINA = timezone(timedelta(hours=-3))

# Cuánto se considera que dura una clase en vivo (para mostrar "en vivo ahora")
DURACION_CLASE = timedelta(hours=2)


def ahora_argentina():
    return datetime.now(ZONA_ARGENTINA).replace(tzinfo=None)


# Cómo llegó el acceso cuando lo da el dueño a mano
MEDIOS_ACCESO = [
    ("paypal", "PayPal"),
    ("transferencia", "Transferencia"),
    ("efectivo", "Efectivo"),
    ("beca", "Beca o regalo"),
    ("importado", "Importado de una lista"),
    ("otro", "Otro"),
]
NOMBRE_MEDIO = dict(MEDIOS_ACCESO)


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
    creado_en = db.Column(db.DateTime, default=ahora_argentina)
    ultimo_ingreso = db.Column(db.DateTime)
    # Recordatorios de clases y avisos de novedades (los mails de pagos y de cuenta siempre salen)
    avisos_email = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.true()
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
    # Legado: antes un curso tenía una sola clase. Ahora van en la tabla "clases"
    # (la migración copió estos datos). Ya no se usan; se conservan para no perder nada.
    meet_link = db.Column(db.String(300))
    fecha = db.Column(db.DateTime)
    grabacion = db.Column(db.String(300))

    inscripciones = db.relationship("Inscripcion", back_populates="curso")
    modulos = db.relationship(
        "Modulo",
        back_populates="curso",
        cascade="all, delete-orphan",
        order_by="Modulo.orden, Modulo.id"
    )
    clases = db.relationship(
        "Clase",
        back_populates="curso",
        cascade="all, delete-orphan",
        order_by="Clase.orden, Clase.id"
    )


class Clase(db.Model):
    """Una clase de un curso: en vivo (Meet + fecha) y/o grabada (link al video)."""
    __tablename__ = "clases"

    id = db.Column(db.Integer, primary_key=True)
    curso_id = db.Column(db.Integer, db.ForeignKey("cursos.id"), nullable=False)
    # Opcional: las clases sin módulo se muestran juntas al final
    modulo_id = db.Column(db.Integer, db.ForeignKey("modulos.id", ondelete="SET NULL"))
    titulo = db.Column(db.String(160), nullable=False)
    descripcion = db.Column(db.String(500))
    orden = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    fecha = db.Column(db.DateTime)
    meet_link = db.Column(db.String(300))
    grabacion = db.Column(db.String(300))
    publicada = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.true()
    )

    curso = db.relationship("Curso", back_populates="clases")
    modulo = db.relationship("Modulo", back_populates="clases")
    envios = db.relationship("EnvioAviso", cascade="all, delete-orphan")
    partes = db.relationship(
        "Parte",
        back_populates="clase",
        cascade="all, delete-orphan",
        order_by="Parte.orden, Parte.id"
    )
    progresos = db.relationship("Progreso", cascade="all, delete-orphan")

    def estado(self, ahora=None):
        """grabada | en_curso | proxima | esperando_grabacion | sin_contenido"""
        ahora = ahora or ahora_argentina()
        if self.grabacion:
            return "grabada"
        if self.meet_link:
            if self.fecha is None or ahora < self.fecha:
                return "proxima"
            if ahora <= self.fecha + DURACION_CLASE:
                return "en_curso"
            return "esperando_grabacion"
        return "sin_contenido"


class Modulo(db.Model):
    """Agrupa clases de un curso (Módulo 1: Táctica, Módulo 2: Preparación física...)."""
    __tablename__ = "modulos"

    id = db.Column(db.Integer, primary_key=True)
    curso_id = db.Column(db.Integer, db.ForeignKey("cursos.id"), nullable=False)
    titulo = db.Column(db.String(160), nullable=False)
    descripcion = db.Column(db.String(500))
    orden = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    curso = db.relationship("Curso", back_populates="modulos")
    clases = db.relationship("Clase", back_populates="modulo", order_by="Clase.orden, Clase.id")


class Parte(db.Model):
    """Un video dentro de una clase, como los capítulos de una lista de YouTube."""
    __tablename__ = "partes"

    id = db.Column(db.Integer, primary_key=True)
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id", ondelete="CASCADE"), nullable=False)
    titulo = db.Column(db.String(160), nullable=False)
    video_url = db.Column(db.String(300))
    duracion_min = db.Column(db.Integer)
    orden = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    clase = db.relationship("Clase", back_populates="partes")
    progresos = db.relationship("Progreso", cascade="all, delete-orphan")


class Progreso(db.Model):
    """Lo que un alumno marcó como visto: una parte, o la clase entera si no tiene partes."""
    __tablename__ = "progresos"
    __table_args__ = (UniqueConstraint("usuario_id", "clase_id", "parte_id", name="uq_progreso"),)

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id", ondelete="CASCADE"), nullable=False)
    parte_id = db.Column(db.Integer, db.ForeignKey("partes.id", ondelete="CASCADE"))
    completado_en = db.Column(db.DateTime, default=ahora_argentina)


class Inscripcion(db.Model):
    __tablename__ = "inscripciones"

    id = db.Column(db.Integer, primary_key=True)
    curso_id = db.Column(db.Integer, db.ForeignKey("cursos.id"), nullable=False)
    alumno_nombre = db.Column(db.String(120), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    estado = db.Column(db.String(20), default="pendiente", nullable=False)
    origen = db.Column(
        db.String(20),
        default="web",
        server_default="web",
        nullable=False
    )
    creado_en = db.Column(db.DateTime, default=ahora_argentina)
    pagado_en = db.Column(db.DateTime)
    # Solo para accesos dados a mano: medio de pago (ver MEDIOS_ACCESO) y una nota libre
    medio = db.Column(db.String(30))
    nota = db.Column(db.String(200))

    curso = db.relationship("Curso", back_populates="inscripciones")
    usuario = db.relationship("Usuario", back_populates="inscripciones")
    
    pagos = db.relationship(
        "Pago",
        back_populates="inscripcion",
        cascade="all, delete-orphan"
    )
    
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

    @property
    def medio_legible(self):
        if self.origen == "web":
            return "Mercado Pago"
        return NOMBRE_MEDIO.get(self.medio, "A mano")
    
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


# ---------------------------------------------------------------------------
# Contenido del sitio (editable desde el panel del dueño)
# ---------------------------------------------------------------------------

class Imagen(db.Model):
    """Foto subida desde el panel. Se guarda en la base para que viaje con los backups
    y no dependa del disco del hosting."""
    __tablename__ = "imagenes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(160))
    mimetype = db.Column(db.String(40), nullable=False)
    datos = db.Column(db.LargeBinary, nullable=False)
    ancho = db.Column(db.Integer)
    alto = db.Column(db.Integer)
    creado_en = db.Column(db.DateTime, default=ahora_argentina)


class Foto(db.Model):
    """Una foto de la galería de la portada."""
    __tablename__ = "fotos"

    id = db.Column(db.Integer, primary_key=True)
    imagen_id = db.Column(db.Integer, db.ForeignKey("imagenes.id"), nullable=False)
    pie = db.Column(db.String(160))
    orden = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    visible = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())

    imagen = db.relationship("Imagen")


class Testimonio(db.Model):
    __tablename__ = "testimonios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    detalle = db.Column(db.String(160))
    texto = db.Column(db.String(800), nullable=False)
    imagen_id = db.Column(db.Integer, db.ForeignKey("imagenes.id"), nullable=True)
    orden = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    visible = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())

    imagen = db.relationship("Imagen")


class PreguntaFrecuente(db.Model):
    __tablename__ = "preguntas"

    id = db.Column(db.Integer, primary_key=True)
    pregunta = db.Column(db.String(200), nullable=False)
    respuesta = db.Column(db.String(1200), nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    visible = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())


class Ajuste(db.Model):
    """Textos y datos sueltos del sitio (nombre del entrenador, WhatsApp, datos legales...)."""
    __tablename__ = "ajustes"

    clave = db.Column(db.String(60), primary_key=True)
    valor = db.Column(db.Text)


# ---------------------------------------------------------------------------
# Avisos por mail y botón de arrepentimiento
# ---------------------------------------------------------------------------

class EnvioAviso(db.Model):
    """Registro de avisos de clases ya enviados: evita mandar dos veces lo mismo."""
    __tablename__ = "envios_aviso"
    __table_args__ = (UniqueConstraint("clase_id", "usuario_id", "tipo", name="uq_envio_aviso"),)

    id = db.Column(db.Integer, primary_key=True)
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 24h | 1h | nueva | grabacion
    enviado_en = db.Column(db.DateTime, default=ahora_argentina)


class Arrepentimiento(db.Model):
    """Solicitud hecha con el botón de arrepentimiento (Res. 424/2020)."""
    __tablename__ = "arrepentimientos"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(12), unique=True, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    referencia = db.Column(db.String(200))
    motivo = db.Column(db.String(1000))
    estado = db.Column(db.String(20), nullable=False, default="recibida", server_default="recibida")
    creado_en = db.Column(db.DateTime, default=ahora_argentina)
