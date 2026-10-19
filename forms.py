from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField, SelectField, StringField, SubmitField, BooleanField, DecimalField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, ValidationError, Optional


class InscripcionForm(FlaskForm):
    curso_id = SelectField(
    "Elegí tu curso",
    coerce=int,
    validators=[DataRequired()]
    )
    
    nombre = StringField(
        "Tu nombre",
        validators=[DataRequired(), Length(min=2, max=80)]
    )
    enviar = SubmitField("Continuar")

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