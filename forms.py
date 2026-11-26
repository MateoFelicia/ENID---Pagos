from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    BooleanField,
    DecimalField,
    EmailField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, ValidationError, Optional


class RegistroForm(FlaskForm):
    nombre = StringField(
        "Tu nombre",
        validators=[DataRequired(), Length(min=2, max=120)]
    )
    email = EmailField(
        "Correo electrónico",
        validators=[DataRequired(), Email(), Length(max=120)]
    )
    password = PasswordField(
        "Contraseña",
        validators=[DataRequired(), Length(min=8, max=128)]
    )
    confirmar_password = PasswordField(
        "Confirmá tu contraseña",
        validators=[
            DataRequired(),
            EqualTo("password", message="Las contraseñas no coinciden.")
        ]
    )
    enviar = SubmitField("Crear cuenta")


class InicioSesionForm(FlaskForm):
    email = EmailField(
        "Correo electrónico",
        validators=[DataRequired(), Email(), Length(max=120)]
    )
    password = PasswordField(
        "Contraseña",
        validators=[DataRequired()]
    )
    enviar = SubmitField("Iniciar sesión")
    

class CursoForm(FlaskForm):
    nombre = StringField(
        "Nombre del curso",
        validators=[DataRequired(), Length(min=2, max=120)]
    )
    descripcion = TextAreaField(
        "Descripción",
        validators=[Optional(), Length(max=300)]
    )
    precio = DecimalField(
        "Precio en ARS",
        places=2,
        validators=[DataRequired(), NumberRange(min=0.01)]
    )
    activo = BooleanField("Curso disponible", default=True)
    enviar = SubmitField("Guardar curso")


def url_http(form, field):
    """Solo enlaces web: evita guardar cosas como javascript:... en un href."""
    valor = (field.data or "").strip().lower()
    if valor and not valor.startswith(("http://", "https://")):
        raise ValidationError("El enlace tiene que empezar con http:// o https://")


class ClaseForm(FlaskForm):
    titulo = StringField(
        "Título de la clase",
        validators=[DataRequired(), Length(min=2, max=160)]
    )
    descripcion = TextAreaField(
        "Descripción (opcional)",
        validators=[Optional(), Length(max=500)]
    )
    orden = IntegerField(
        "Orden en el curso",
        validators=[Optional(), NumberRange(min=0, max=9999)]
    )
    # Las opciones las carga la vista con los módulos del curso; 0 = sin módulo
    modulo_id = SelectField("Módulo", coerce=int, default=0, validate_choice=False)
    fecha = StringField(
        "Fecha y hora en vivo (hora de Argentina)",
        validators=[Optional(), Length(max=16)]
    )
    meet_link = StringField(
        "Link de Meet/Zoom (clases en vivo)",
        validators=[Optional(), Length(max=300), url_http]
    )
    grabacion = StringField(
        "Link de la grabación",
        validators=[Optional(), Length(max=300), url_http]
    )
    publicada = BooleanField("Visible para los alumnos", default=True)
    avisar = BooleanField("Avisar por mail a los alumnos del curso al guardar")
    enviar = SubmitField("Guardar clase")


class ModuloForm(FlaskForm):
    titulo = StringField(
        "Nombre del módulo",
        validators=[DataRequired(), Length(min=2, max=160)],
        description="Por ejemplo: «Módulo 1 · Fundamentos tácticos»."
    )
    descripcion = TextAreaField("Descripción (opcional)", validators=[Optional(), Length(max=500)])
    orden = IntegerField("Orden en el curso", validators=[Optional(), NumberRange(min=0, max=9999)])
    enviar = SubmitField("Guardar módulo")


class ParteForm(FlaskForm):
    titulo = StringField(
        "Título de la parte",
        validators=[DataRequired(), Length(min=2, max=160)],
        description="Por ejemplo: «Parte 1 · Presión tras pérdida»."
    )
    video_url = StringField(
        "Link del video",
        validators=[Optional(), Length(max=300), url_http],
        description="YouTube, Vimeo o Google Drive se ven dentro de la web; otros links se abren aparte."
    )
    duracion_min = IntegerField("Duración en minutos (opcional)", validators=[Optional(), NumberRange(min=1, max=999)])
    orden = IntegerField("Orden en la clase", validators=[Optional(), NumberRange(min=0, max=9999)])
    enviar = SubmitField("Guardar parte")


IMAGENES_PERMITIDAS = ["jpg", "jpeg", "png", "webp", "gif"]
_solo_imagenes = FileAllowed(IMAGENES_PERMITIDAS, "Subí una imagen JPG, PNG, WEBP o GIF.")


class TestimonioForm(FlaskForm):
    nombre = StringField("Nombre", validators=[DataRequired(), Length(max=120)])
    detalle = StringField(
        "Detalle (opcional)",
        validators=[Optional(), Length(max=160)],
        description="Por ejemplo: «Alumno de ENID · Córdoba» o «Mamá de Tomás, 12 años»."
    )
    texto = TextAreaField("Testimonio", validators=[DataRequired(), Length(max=800)])
    foto = FileField("Foto (opcional)", validators=[Optional(), _solo_imagenes])
    quitar_foto = BooleanField("Quitar la foto actual")
    orden = IntegerField("Orden", validators=[Optional(), NumberRange(min=0, max=9999)])
    visible = BooleanField("Visible en la web", default=True)
    enviar = SubmitField("Guardar testimonio")


class PreguntaForm(FlaskForm):
    pregunta = StringField("Pregunta", validators=[DataRequired(), Length(max=200)])
    respuesta = TextAreaField("Respuesta", validators=[DataRequired(), Length(max=1200)])
    orden = IntegerField("Orden", validators=[Optional(), NumberRange(min=0, max=9999)])
    visible = BooleanField("Visible en la web", default=True)
    enviar = SubmitField("Guardar pregunta")


class FotoForm(FlaskForm):
    pie = StringField("Pie de foto (opcional)", validators=[Optional(), Length(max=160)])
    orden = IntegerField("Orden", validators=[Optional(), NumberRange(min=0, max=9999)])
    visible = BooleanField("Visible en la web", default=True)
    enviar = SubmitField("Guardar foto")


class AjustesForm(FlaskForm):
    entrenador_nombre = StringField("Nombre del entrenador", validators=[Optional(), Length(max=120)])
    entrenador_titulo = StringField(
        "Título o rol", validators=[Optional(), Length(max=160)],
        description="Por ejemplo: «Director técnico · Fundador de ENID»."
    )
    entrenador_bio = TextAreaField("Presentación", validators=[Optional(), Length(max=1500)])
    foto_entrenador = FileField("Foto del entrenador", validators=[Optional(), _solo_imagenes])
    quitar_foto_entrenador = BooleanField("Quitar la foto actual")
    imagen_portada = FileField("Imagen de portada (fondo del inicio)", validators=[Optional(), _solo_imagenes])
    quitar_portada = BooleanField("Volver a la imagen de portada original")
    whatsapp = StringField(
        "WhatsApp", validators=[Optional(), Length(max=30)],
        description="Con código de país y sin signos: 5493510000000."
    )
    instagram = StringField("Instagram", validators=[Optional(), Length(max=100)],
                            description="Tu usuario o el enlace al perfil.")
    email_contacto = StringField(
        "Email de contacto", validators=[Optional(), Email(), Length(max=120)],
        description="Recibe los avisos de arrepentimiento y es el «responder a» de los mails."
    )
    legal_titular = StringField("Titular / razón social", validators=[Optional(), Length(max=160)])
    legal_cuit = StringField("CUIT / CUIL", validators=[Optional(), Length(max=20)])
    legal_domicilio = StringField("Domicilio", validators=[Optional(), Length(max=200)])
    enviar = SubmitField("Guardar ajustes")


class ArrepentimientoForm(FlaskForm):
    nombre = StringField("Nombre y apellido", validators=[DataRequired(), Length(max=120)])
    email = EmailField("Email con el que compraste", validators=[DataRequired(), Email(), Length(max=120)])
    referencia = StringField(
        "Curso o número de inscripción", validators=[Optional(), Length(max=200)]
    )
    motivo = TextAreaField("Comentario (opcional)", validators=[Optional(), Length(max=1000)])
    enviar = SubmitField("Solicitar arrepentimiento")


class MiCuentaForm(FlaskForm):
    nombre = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=120)])
    avisos_email = BooleanField("Recibir recordatorios y avisos de clases por mail")
    enviar = SubmitField("Guardar cambios")


class CambiarPasswordForm(FlaskForm):
    actual = PasswordField("Contraseña actual", validators=[DataRequired()])
    nueva = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=8, max=128)])
    confirmar = PasswordField(
        "Repetir nueva contraseña",
        validators=[DataRequired(), EqualTo("nueva", message="Las contraseñas no coinciden.")]
    )
    enviar = SubmitField("Cambiar contraseña")
