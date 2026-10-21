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

from flask_mail import Mail, Message

from functools import wraps

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pagos.db"
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True") == "True"
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER", "ENID <noreply@enid.com>")
db.init_app(app)
csrf = CSRFProtect()
csrf.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "iniciar_sesion"
mail = Mail(app)

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


def tiene_acceso_curso(usuario, curso):
    if usuario.es_admin:
        return True
    inscripcion = db.session.execute(
        db.select(Inscripcion).where(
            Inscripcion.usuario_id == usuario.id,
            Inscripcion.curso_id == curso.id
        )
    ).scalar_one_or_none()
    if inscripcion and inscripcion.tiene_acceso():
        return True
    return False


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


@app.route("/admin/inscripciones/nueva", methods=["GET", "POST"])
@admin_required
def nueva_inscripcion_manual():
    cursos = db.session.execute(
        db.select(Curso).where(Curso.activo.is_(True)).order_by(Curso.nombre)
    ).scalars().all()

    if request.method == "POST":
        curso_id = request.form.get("curso_id", type=int)
        alumno_nombre = request.form.get("alumno_nombre", "").strip()
        email = request.form.get("email", "").strip().lower()

        if not curso_id or not alumno_nombre:
            flash("Curso y nombre del alumno son obligatorios.", "danger")
            return redirect(url_for("nueva_inscripcion_manual"))

        curso = db.session.get(Curso, curso_id)
        if not curso:
            flash("Curso no encontrado.", "danger")
            return redirect(url_for("nueva_inscripcion_manual"))

        usuario = None
        if email:
            usuario = db.session.execute(
                db.select(Usuario).where(db.func.lower(Usuario.email) == email)
            ).scalar_one_or_none()
            if not usuario:
                usuario = Usuario(nombre=alumno_nombre, email=email)
                usuario.establecer_password("changeme123")
                db.session.add(usuario)
                db.session.flush()

        inscripcion = Inscripcion(
            curso_id=curso.id,
            alumno_nombre=alumno_nombre,
            monto=curso.precio,
            estado="pagada",
            origen="manual",
            usuario=usuario
        )
        db.session.add(inscripcion)
        db.session.commit()
        flash("Inscripción manual creada con acceso concedido.", "success")
        return redirect(url_for("administrar_inscripciones"))

    return render_template(
        "admin/inscripcion_manual.html",
        cursos=cursos
    )


@app.route("/admin/cursos/nuevo", methods=["GET", "POST"])
@admin_required
def nuevo_curso():
    form = CursoForm()

    if form.validate_on_submit():
        fecha = None
        if form.fecha.data:
            try:
                from datetime import datetime
                fecha = datetime.strptime(form.fecha.data, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass
        curso = Curso(
            nombre=form.nombre.data.strip(),
            descripcion=(form.descripcion.data or "").strip() or None,
            precio=form.precio.data,
            activo=form.activo.data,
            meet_link=(form.meet_link.data or "").strip() or None,
            fecha=fecha,
            grabacion=(form.grabacion.data or "").strip() or None,
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
        fecha = None
        if form.fecha.data:
            try:
                from datetime import datetime
                fecha = datetime.strptime(form.fecha.data, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass
        curso.nombre = form.nombre.data.strip()
        curso.descripcion = (form.descripcion.data or "").strip() or None
        curso.precio = form.precio.data
        curso.activo = form.activo.data
        curso.meet_link = (form.meet_link.data or "").strip() or None
        curso.fecha = fecha
        curso.grabacion = (form.grabacion.data or "").strip() or None

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

            token = generar_token_reset(email)
            confirm_url = url_for("confirmar_email", token=token, _external=True)
            html = f"""
            <p>Hola {usuario.nombre},</p>
            <p>Gracias por registrarte en ENID. Confirmá tu email haciendo click en el siguiente enlace:</p>
            <p><a href="{confirm_url}">{confirm_url}</a></p>
            <p>El enlace expira en 1 hora.</p>
            """
            enviar_email(email, "Confirmá tu email - ENID", html)

            flash("Cuenta creada. Te enviamos un email para confirmar tu dirección.", "success")
            return redirect(url_for("iniciar_sesion"))

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


@app.route("/curso/<int:curso_id>")
@login_required
def ver_curso(curso_id):
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        abort(404)

    if not tiene_acceso_curso(current_user, curso):
        flash("No tenés acceso a este curso.", "warning")
        return redirect(url_for("mis_inscripciones"))

    return render_template("curso_detalle.html", curso=curso)


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

            # Usar URL de ngrok para back_urls (MP requiere HTTPS)
            ngrok_url = os.getenv("NGROK_URL", "").rstrip('/')
            base_url = ngrok_url if ngrok_url else request.url_root.rstrip('/')
            
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
                "external_reference": str(inscripcion.id),
                "back_urls": {
                    "success": f"{base_url}{url_for('pago_exitoso')}",
                    "pending": f"{base_url}{url_for('pago_pendiente')}",
                    "failure": f"{base_url}{url_for('pago_fallido')}"
                },
                "auto_return": "approved"
            }

            resultado = sdk.preference().create(preference_data)
            print("MP Preference response:", resultado)
            
            if resultado.get("status") != 201:
                flash("Error al crear la preferencia de pago. Intente nuevamente.", "danger")
                return redirect(url_for("inicio"))

            preferencia = resultado["response"]

            pago.preferencia_id = preferencia.get("id") or preferencia.get("preference_id")
            db.session.commit()

            init_point = preferencia.get("init_point") or preferencia.get("sandbox_init_point")
            if not init_point:
                flash("Error al obtener URL de pago. Intente nuevamente.", "danger")
                return redirect(url_for("inicio"))

            return redirect(init_point)

    return render_template(
        "index.html",
        form=form,
        mensaje=mensaje,
        cursos=cursos
    )

@app.route("/webhooks/mercadopago", methods=["POST"])
@csrf.exempt
def webhook_mercado_pago():
    import sys
    log = lambda msg: print(msg, flush=True, file=sys.stderr)
    
    log("\n[WEBHOOK] POST recibido")
    log(f"  ALL Headers: {dict(request.headers)}")
    log(f"  x-signature: {request.headers.get('x-signature')}")
    log(f"  x-request-id: {request.headers.get('x-request-id')}")
    log(f"  Content-Type: {request.headers.get('Content-Type')}")
    
    firma = request.headers.get("x-signature")
    request_id = request.headers.get("x-request-id")
    evento = request.get_json(silent=True) or {}
    data_id = evento.get("data", {}).get("id")
    secreto = os.getenv("MP_WEBHOOK_SECRET")

    log(f"  Evento: {evento.get('type')}, data_id: {data_id}")
    log(f"  Secreto configurado: {'SI' if secreto else 'NO'}")
    log(f"  Firma recibida: {firma}")
    log(f"  Request ID: {request_id}")
    log(f"  Data ID: {data_id}")

    if not secreto:
        print("  ERROR: MP_WEBHOOK_SECRET no configurado")
        return "", 503

    if not firma or not request_id or not data_id:
        print("  ERROR: Headers faltantes")
        return "", 400

    try:
        WebhookSignatureValidator.validate(
            firma,
            request_id,
            data_id,
            secreto
        )
        print("  Firma VALIDA")
    except InvalidWebhookSignatureError as e:
        print(f"  ERROR: Firma INVALIDA - {e}")
        return "", 401

    if evento.get("type") != "payment":
        print("  No es evento payment, ignorando")
        return "", 200

    sdk = mercadopago.SDK(os.getenv("MP_ACCESS_TOKEN"))
    resultado = sdk.payment().get(data_id)

    print(f"  MP payment.get status: {resultado.get('status')}")

    if resultado.get("status") != 200:
        print(f"  ERROR: MP devolvio status {resultado.get('status')}")
        return "", 500

    datos_pago = resultado.get("response", {})
    referencia = datos_pago.get("external_reference")

    print(f"  external_reference: {referencia}")
    print(f"  transaction_amount: {datos_pago.get('transaction_amount')}")
    print(f"  currency_id: {datos_pago.get('currency_id')}")
    print(f"  status: {datos_pago.get('status')}")

    try:
        inscripcion_id = int(referencia)
        monto_mercado_pago = Decimal(
            str(datos_pago.get("transaction_amount"))
        )
    except (TypeError, ValueError, InvalidOperation) as e:
        print(f"  ERROR parseando datos: {e}")
        return "", 200

    inscripcion = db.session.get(Inscripcion, inscripcion_id)
    if inscripcion is None:
        print(f"  ERROR: Inscripcion {inscripcion_id} no existe")
        return "", 200

    pago = db.session.execute(
        db.select(Pago).where(Pago.inscripcion_id == inscripcion.id)
    ).scalars().first()

    if pago is None:
        print(f"  ERROR: Pago para inscripcion {inscripcion_id} no existe")
        return "", 200

    print(f"  Pago local: id={pago.id}, monto={pago.monto}, moneda={pago.moneda}")

    if (
        monto_mercado_pago != pago.monto
        or datos_pago.get("currency_id") != pago.moneda
    ):
        print(f"  ERROR: Monto/moneda no coinciden. MP: {monto_mercado_pago} {datos_pago.get('currency_id')}, Local: {pago.monto} {pago.moneda}")
        return "", 200

    pago.pago_externo_id = str(datos_pago.get("id", data_id))
    pago.estado = datos_pago.get("status", "desconocido")

    if pago.estado == "approved":
        inscripcion.estado = "pagada"
    elif pago.estado in {"refunded", "charged_back"}:
        inscripcion.estado = "reembolsada"

    db.session.commit()
    print(f"  OK: Inscripcion {inscripcion_id} -> {inscripcion.estado}")
    return "", 200


@app.route("/pago/exitoso")
def pago_exitoso():
    flash("¡Pago aprobado! Tu inscripción está confirmada.", "success")
    return redirect(url_for("mis_inscripciones"))


@app.route("/pago/pendiente")
def pago_pendiente():
    flash("El pago está pendiente. Te notificaremos cuando se confirme.", "warning")
    return redirect(url_for("mis_inscripciones"))


@app.route("/pago/fallido")
def pago_fallido():
    flash("El pago no pudo procesarse. Podés reintentar cuando quieras.", "danger")
    return redirect(url_for("inicio"))


def generar_token_reset(email):
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    return s.dumps(email, salt="password-reset")


def verificar_token_reset(token, max_age=3600):
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    try:
        email = s.loads(token, salt="password-reset", max_age=max_age)
        return email
    except (SignatureExpired, BadSignature):
        return None


def enviar_email(destinatario, asunto, cuerpo_html):
    # Modo local: siempre simula e imprime en consola
    print(f"\n{'='*60}")
    print(f"[EMAIL LOCAL] Para: {destinatario}")
    print(f"Asunto: {asunto}")
    print(f"{'='*60}")
    print(cuerpo_html)
    print(f"{'='*60}\n")
    return True
    
    # Para producción, descomentá lo de abajo y borrá lo de arriba:
    # if not app.config.get("MAIL_USERNAME"):
    #     print(f"[EMAIL SIMULADO] Para: {destinatario} | Asunto: {asunto}")
    #     print(cuerpo_html)
    #     return True
    # try:
    #     msg = Message(asunto, recipients=[destinatario], html=cuerpo_html)
    #     mail.send(msg)
    #     return True
    # except Exception as e:
    #     print(f"Error enviando email: {e}")
    #     return False


@app.route("/recuperar-password", methods=["GET", "POST"])
def recuperar_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        usuario = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == email)
        ).scalar_one_or_none()
        
        if usuario:
            token = generar_token_reset(email)
            reset_url = url_for("resetear_password", token=token, _external=True)
            html = f"""
            <p>Hola {usuario.nombre},</p>
            <p>Solicitaste restablecer tu contraseña. Hacé click en el siguiente enlace:</p>
            <p><a href="{reset_url}">{reset_url}</a></p>
            <p>El enlace expira en 1 hora.</p>
            <p>Si no solicitaste esto, ignorá este mail.</p>
            """
            enviar_email(email, "Restablecer contraseña - ENID", html)
        
        flash("Si el email existe, recibirás instrucciones para restablecer tu contraseña.", "info")
        return redirect(url_for("iniciar_sesion"))
    
    return render_template("recuperar_password.html")


@app.route("/resetear-password/<token>", methods=["GET", "POST"])
def resetear_password(token):
    email = verificar_token_reset(token)
    if not email:
        flash("El enlace es inválido o ha expirado.", "danger")
        return redirect(url_for("recuperar_password"))
    
    usuario = db.session.execute(
        db.select(Usuario).where(db.func.lower(Usuario.email) == email)
    ).scalar_one_or_none()
    
    if not usuario:
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for("recuperar_password"))
    
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmar = request.form.get("confirmar", "")
        
        if not password or len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "danger")
        elif password != confirmar:
            flash("Las contraseñas no coinciden.", "danger")
        else:
            usuario.establecer_password(password)
            db.session.commit()
            flash("Contraseña actualizada correctamente.", "success")
            return redirect(url_for("iniciar_sesion"))
    
    return render_template("resetear_password.html", token=token)


@app.route("/confirmar-email/<token>")
def confirmar_email(token):
    email = verificar_token_reset(token)
    if not email:
        flash("El enlace es inválido o ha expirado.", "danger")
        return redirect(url_for("registro"))
    
    usuario = db.session.execute(
        db.select(Usuario).where(db.func.lower(Usuario.email) == email)
    ).scalar_one_or_none()
    
    if not usuario:
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for("registro"))
    
    flash("Email confirmado correctamente. Ya podés iniciar sesión.", "success")
    return redirect(url_for("iniciar_sesion"))


if __name__ == "__main__":
    app.run(debug=True)