import os

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, flash, url_for, abort
from forms import InscripcionForm, RegistroForm, InicioSesionForm, CursoForm

from db import db
from models import Curso, Inscripcion, Pago, Usuario

import mercadopago

from decimal import Decimal, InvalidOperation


from mercadopago.webhook import (
    WebhookSignatureValidator,
    InvalidWebhookSignatureError,
)

from flask_migrate import Migrate

from flask_login import LoginManager, current_user, login_user, logout_user, login_required

from flask_wtf.csrf import CSRFProtect

from functools import wraps

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pagos.db"
db.init_app(app)
csrf = CSRFProtect()
csrf.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "iniciar_sesion"

@login_manager.user_loader
def cargar_usuario(user_id):
    try:
        return db.session.get(Usuario, int(user_id))
    except (TypeError, ValueError):
        return None
migrate = Migrate(app, db)

def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not current_user.es_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view



@app.route("/admin/cursos")
@admin_required
def administrar_cursos():
    cursos = db.session.execute(
        db.select(Curso).order_by(Curso.nombre)
    ).scalars().all()

    return render_template("admin/cursos.html", cursos=cursos)

@app.route("/admin/inscripciones")
@admin_required
def administrar_inscripciones():
    inscripciones = db.session.execute(
        db.select(Inscripcion).order_by(Inscripcion.id.desc())
    ).scalars().all()

    return render_template(
        "admin/inscripciones.html",
        inscripciones=inscripciones
    )


@app.route("/admin/cursos/nuevo", methods=["GET", "POST"])
@admin_required
def nuevo_curso():
    form = CursoForm()

    if form.validate_on_submit():
        curso = Curso(
            nombre=form.nombre.data.strip(),
            descripcion=(form.descripcion.data or "").strip() or None,
            precio=form.precio.data,
            activo=form.activo.data
        )
        db.session.add(curso)
        db.session.commit()
        flash("Curso creado.", "success")
        return redirect(url_for("administrar_cursos"))

    return render_template(
        "admin/curso_form.html",
        form=form,
        titulo="Nuevo curso"
    )


@app.route("/admin/cursos/<int:curso_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_curso(curso_id):
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        abort(404)

    form = CursoForm(obj=curso)

    if form.validate_on_submit():
        curso.nombre = form.nombre.data.strip()
        curso.descripcion = (form.descripcion.data or "").strip() or None
        curso.precio = form.precio.data
        curso.activo = form.activo.data

        db.session.commit()
        flash("Curso actualizado.", "success")
        return redirect(url_for("administrar_cursos"))

    return render_template(
        "admin/curso_form.html",
        form=form,
        titulo="Editar curso"
    )


@app.route("/admin/cursos/<int:curso_id>/desactivar", methods=["POST"])
@admin_required
def desactivar_curso(curso_id):
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        abort(404)

    curso.activo = False
    db.session.commit()
    flash("Curso desactivado.", "success")
    return redirect(url_for("administrar_cursos"))

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    form = RegistroForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        usuario_existente = db.session.execute(
            db.select(Usuario).where(
                db.func.lower(Usuario.email) == email
            )
        ).scalar_one_or_none()

        if usuario_existente:
            form.email.errors.append(
                "Ya existe una cuenta con ese correo."
            )
        else:
            usuario = Usuario(
                nombre=form.nombre.data.strip(),
                email=email
            )
            usuario.establecer_password(form.password.data)

            db.session.add(usuario)
            db.session.commit()

            login_user(usuario)
            return redirect(url_for("inicio"))

    return render_template("registro.html", form=form)


@app.route("/iniciar-sesion", methods=["GET", "POST"])
def iniciar_sesion():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    form = InicioSesionForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        usuario = db.session.execute(
            db.select(Usuario).where(
                db.func.lower(Usuario.email) == email
            )
        ).scalar_one_or_none()

        if usuario and usuario.verificar_password(form.password.data):
            login_user(usuario)
            return redirect(url_for("inicio"))

        form.email.errors.append("Correo o contraseña incorrectos.")

    return render_template("iniciar_sesion.html", form=form)


@app.route("/cerrar-sesion", methods=["POST"])
@login_required
def cerrar_sesion():
    logout_user()
    return redirect(url_for("inicio"))


@app.route("/mis-inscripciones")
@login_required
def mis_inscripciones():
    inscripciones = db.session.execute(
        db.select(Inscripcion)
        .where(Inscripcion.usuario_id == current_user.id)
        .order_by(Inscripcion.id.desc())
    ).scalars().all()

    return render_template(
        "mis_inscripciones.html",
        inscripciones=inscripciones
    )


@app.route("/", methods=["GET", "POST"])

def inicio():
    cursos = db.session.execute(
        db.select(Curso).where(Curso.activo.is_(True))
    ).scalars().all()

    form = InscripcionForm()
    form.curso_id.choices = [
        (curso.id, curso.nombre) for curso in cursos
    ]

    mensaje = None

    if form.validate_on_submit():
        curso = db.session.get(Curso, form.curso_id.data)

        if curso is None or not curso.activo:
            mensaje = "Ese curso ya no está disponible."
        else:
            inscripcion = Inscripcion()
            inscripcion.curso = curso
            inscripcion.alumno_nombre = (form.nombre.data or "").strip()
            inscripcion.monto = curso.precio
            inscripcion.estado = "pendiente"
            inscripcion.usuario = (
                current_user if current_user.is_authenticated else None
            )

            pago = Pago()
            pago.inscripcion = inscripcion
            pago.monto = curso.precio
            pago.moneda = "ARS"
            pago.estado = "pendiente"

            db.session.add_all([inscripcion, pago])
            db.session.commit()

            sdk = mercadopago.SDK(os.getenv("MP_ACCESS_TOKEN"))

            preference_data = {
                "items": [
                    {
                        "id": str(curso.id),
                        "title": curso.nombre,
                        "quantity": 1,
                        "currency_id": "ARS",
                        "unit_price": float(curso.precio)
                    }
                ],
                "external_reference": str(inscripcion.id)
            }

            resultado = sdk.preference().create(preference_data)
            preferencia = resultado["response"]

            pago.preferencia_id = preferencia["id"]
            db.session.commit()

            return redirect(preferencia["init_point"])

    return render_template(
        "index.html",
        form=form,
        mensaje=mensaje,
        cursos=cursos
    )

@app.route("/webhooks/mercadopago", methods=["POST"])
@csrf.exempt
def webhook_mercado_pago():
    firma = request.headers.get("x-signature")
    request_id = request.headers.get("x-request-id")
    evento = request.get_json(silent=True) or {}
    data_id = evento.get("data", {}).get("id")
    secreto = os.getenv("MP_WEBHOOK_SECRET")

    if not secreto:
        return "", 503

    if not firma or not request_id or not data_id:
        return "", 400

    try:
        WebhookSignatureValidator.validate(
            firma,
            request_id,
            data_id,
            secreto
        )
    except InvalidWebhookSignatureError:
        return "", 401

    if evento.get("type") != "payment":
        return "", 200

    sdk = mercadopago.SDK(os.getenv("MP_ACCESS_TOKEN"))
    resultado = sdk.payment().get(data_id)

    if resultado.get("status") != 200:
        return "", 500

    datos_pago = resultado.get("response", {})
    referencia = datos_pago.get("external_reference")

    try:
        inscripcion_id = int(referencia)
        monto_mercado_pago = Decimal(
            str(datos_pago.get("transaction_amount"))
        )
    except (TypeError, ValueError, InvalidOperation):
        return "", 200

    inscripcion = db.session.get(Inscripcion, inscripcion_id)
    if inscripcion is None:
        return "", 200

    pago = db.session.execute(
        db.select(Pago).where(Pago.inscripcion_id == inscripcion.id)
    ).scalars().first()

    if pago is None:
        return "", 200

    if (
        monto_mercado_pago != pago.monto
        or datos_pago.get("currency_id") != pago.moneda
    ):
        return "", 200

    pago.pago_externo_id = str(datos_pago.get("id", data_id))
    pago.estado = datos_pago.get("status", "desconocido")

    if pago.estado == "approved":
        inscripcion.estado = "pagada"
    elif pago.estado in {"refunded", "charged_back"}:
        inscripcion.estado = "reembolsada"

    db.session.commit()
    return "", 200

if __name__ == "__main__":
    app.run(debug=True)