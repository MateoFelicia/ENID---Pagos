import csv
import io
import logging
import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import click
import mercadopago
from dotenv import load_dotenv
from email_validator import EmailNotValidError, validate_email
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFError
from mercadopago.webhook import (
    InvalidWebhookSignatureError,
    WebhookSignatureValidator,
)
from sqlalchemy.orm import selectinload
from werkzeug.middleware.proxy_fix import ProxyFix

import gestion
import sitio
from avisos import avisar
from db import db
from emailer import (
    base_url,
    enviar_acceso,
    enviar_bienvenida,
    enviar_comprobante,
    enviar_reset,
    generar_token_invitacion,
    generar_token_reset,
    mail_configurado,
    url_externa,
    verificar_token_acceso,
    verificar_token_reset,
)
from extensions import csrf, limiter, mail
from forms import ClaseForm, CursoForm, InicioSesionForm, RegistroForm
from models import (
    MEDIOS_ACCESO,
    Clase,
    Curso,
    Inscripcion,
    Pago,
    Usuario,
    ahora_argentina,
)
from utils import (
    admin_required,
    destino_seguro,
    inscripcion_con_acceso,
    tiene_acceso_curso,
)

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("enid")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Falta SECRET_KEY en el archivo .env")

def normalizar_url_base_de_datos(url):
    """Los hostings viejos entregan postgres://, pero SQLAlchemy solo acepta postgresql://."""
    return "postgresql://" + url[len("postgres://"):] if url.startswith("postgres://") else url


app.config["SQLALCHEMY_DATABASE_URI"] = normalizar_url_base_de_datos(
    os.getenv("DATABASE_URL", "sqlite:///pagos.db")
)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

# Detrás de un proxy (Caddy, Nginx, Render...) hay que confiar en sus cabeceras para saber
# la IP real y que los enlaces salgan con https. Solo se activa si lo pedís (TRUST_PROXY=1).
if os.getenv("TRUST_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _cookies_seguras():
    """Cookies 'secure' (solo viajan por https). Auto: sí si PUBLIC_URL es https y no es un túnel de pruebas."""
    explicito = os.getenv("SECURE_COOKIES")
    if explicito in ("0", "1"):
        return explicito == "1"
    publica = (os.getenv("PUBLIC_URL") or os.getenv("NGROK_URL") or "").strip().lower()
    return publica.startswith("https://") and "ngrok" not in publica


app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = _cookies_seguras()
app.config["REMEMBER_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["PREFERRED_URL_SCHEME"] = "https" if app.config["SESSION_COOKIE_SECURE"] else "http"
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # varias fotos juntas
app.config["EMAIL_ASYNC"] = os.getenv("EMAIL_ASYNC", "1") == "1"
app.config["RATELIMIT_STORAGE_URI"] = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
app.config["RATELIMIT_ENABLED"] = os.getenv("RATELIMIT_ENABLED", "1") == "1"

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True") == "True"
app.config["MAIL_USE_SSL"] = os.getenv("MAIL_USE_SSL", "False") == "True"
app.config["MAIL_TIMEOUT"] = float(os.getenv("MAIL_TIMEOUT", 20))
app.config["MAIL_SUPPRESS_SEND"] = os.getenv("MAIL_SUPPRESS_SEND") == "1"  # 1 = no enviar de verdad (pruebas)
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv(
    "MAIL_DEFAULT_SENDER", "ENID <noreply@enid.com>"
)

db.init_app(app)
csrf.init_app(app)
limiter.init_app(app)
migrate = Migrate(app, db)
mail.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "iniciar_sesion"
login_manager.login_message = "Iniciá sesión para continuar."
login_manager.login_message_category = "warning"

app.register_blueprint(sitio.bp)
app.register_blueprint(gestion.bp)

@app.template_filter("fecha_ar")
def fecha_ar(fecha):
    """18/11/2026 · 19:30 hs (hora de Argentina). Los alumnos pueden estar en otros países."""
    if not fecha:
        return ""
    return fecha.strftime("%d/%m/%Y · %H:%M") + " hs (hora de Argentina)"


@app.template_filter("ars")
def formato_ars(valor):
    """5000 -> 5.000 ; 12500.5 -> 12.500,50 (formato argentino, sin decimales si son ,00)."""
    try:
        texto = f"{float(valor):,.2f}"
    except (TypeError, ValueError):
        return ""
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return texto[:-3] if texto.endswith(",00") else texto


@app.template_filter("dia")
def dia(fecha):
    return fecha.strftime("%d/%m/%Y") if fecha else "—"


# Estados de pago de Mercado Pago que revocan el acceso
ESTADOS_REEMBOLSO = {"refunded", "charged_back"}


@login_manager.user_loader
def cargar_usuario(user_id):
    try:
        return db.session.get(Usuario, int(user_id))
    except (TypeError, ValueError):
        return None


def url_publica():
    """URL base pública (https) que Mercado Pago usa para volver a la web."""
    return base_url() or request.url_root.rstrip("/")


def parsear_fecha(texto):
    if isinstance(texto, datetime):  # el formulario devolvió el valor guardado
        return texto
    texto = (texto or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


def _intentar(funcion, *args):
    """Los mails nunca deben romper un pago ni un registro: se registra el error y se sigue."""
    try:
        return funcion(*args)
    except Exception:
        log.exception("Falló el envío de un mail (%s)", getattr(funcion, "__name__", funcion))
        return False


# ---------------------------------------------------------------------------
# Aviso claro cuando la base de datos no está actualizada
# ---------------------------------------------------------------------------

_migraciones_ok = False


@app.before_request
def verificar_migraciones():
    """Si faltan migraciones (o hay más de una cabeza), mostrar un aviso claro en lugar de un error 500.

    Se comprueba hasta que pasa una vez; después no cuesta nada. No aplica a los tests, a los archivos
    estáticos ni al chequeo de salud.
    """
    global _migraciones_ok
    if _migraciones_ok or app.testing or request.endpoint in ("static", "sitio.salud"):
        return None
    try:
        actual, cabeza = gestion._estado_migraciones()
        problema = None if actual == cabeza else f"la base está en {actual} y la última versión es {cabeza}"
    except Exception as error:  # por ejemplo: varias cabezas de migraciones
        problema = str(error)
    if problema is None:
        _migraciones_ok = True
        return None
    log.error("Base de datos desactualizada: %s. Corré: flask db upgrade", problema)
    return render_template("errores/migraciones.html"), 503


# ---------------------------------------------------------------------------
# Cabeceras de seguridad y páginas de error
# ---------------------------------------------------------------------------

@app.after_request
def cabeceras_seguridad(respuesta):
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    respuesta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    respuesta.headers.setdefault(
        "Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    )
    if request.is_secure:
        respuesta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return respuesta


def _pagina_error(codigo, titulo, mensaje):
    return render_template("errores/error.html", codigo=codigo, titulo=titulo, mensaje=mensaje), codigo


@app.errorhandler(403)
def error_403(_):
    return _pagina_error(403, "No tenés permiso", "Esta página es solo para administradores.")


@app.errorhandler(404)
def error_404(_):
    return _pagina_error(404, "No encontramos esa página", "Puede que el enlace esté mal escrito o que ya no exista.")


@app.errorhandler(413)
def error_413(_):
    return _pagina_error(413, "El archivo es demasiado grande", "Probá con uno más liviano.")


@app.errorhandler(429)
def error_429(_):
    return _pagina_error(429, "Demasiados intentos", "Esperá unos minutos y volvé a intentarlo.")


@app.errorhandler(CSRFError)
def error_csrf(_):
    return _pagina_error(400, "La página venció", "Volvé atrás, recargala e intentá de nuevo.")


@app.errorhandler(500)
def error_500(_):
    db.session.rollback()
    # Plantilla autónoma: no consulta la base, que podría ser justo lo que falló
    return render_template("errores/500.html"), 500


# ---------------------------------------------------------------------------
# Administración (solo dueño / admins)
# ---------------------------------------------------------------------------

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
    return render_template("admin/inscripciones.html", inscripciones=inscripciones)


def _usuarios_con_cursos():
    return db.session.execute(
        db.select(Usuario)
        .options(selectinload(Usuario.inscripciones).selectinload(Inscripcion.curso))
        .order_by(db.func.lower(Usuario.nombre))
    ).scalars().all()


@app.route("/admin/usuarios")
@admin_required
def administrar_usuarios():
    """Vista del dueño: todos los usuarios con sus cursos y el estado de cada uno."""
    usuarios = _usuarios_con_cursos()
    inscripciones = db.session.execute(db.select(Inscripcion)).scalars().all()

    stats = {
        "alumnos": sum(1 for u in usuarios if not u.es_admin),
        "pagadas": sum(1 for i in inscripciones if i.estado == "pagada"),
        "pendientes": sum(1 for i in inscripciones if i.estado == "pendiente"),
        "manuales": sum(1 for i in inscripciones if i.origen == "manual"),
        "ingresos": sum(
            (i.monto for i in inscripciones if i.estado == "pagada" and i.origen == "web"),
            Decimal("0"),
        ),
    }
    return render_template("admin/usuarios.html", usuarios=usuarios, stats=stats)


def _celda_segura(valor):
    """Evita inyección de fórmulas al abrir el CSV en Excel/Sheets."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


@app.route("/admin/usuarios.csv")
@admin_required
def exportar_usuarios_csv():
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow([
        "Alumno", "Email", "Alta", "Último ingreso", "Curso", "Estado", "Origen",
        "Medio", "Nota", "Fecha de pago o acceso", "Importe ARS",
    ])
    for u in _usuarios_con_cursos():
        base = [_celda_segura(u.nombre), _celda_segura(u.email), dia(u.creado_en), dia(u.ultimo_ingreso)]
        if not u.inscripciones:
            escritor.writerow(base + ["", "", "", "", "", "", ""])
        for i in u.inscripciones:
            escritor.writerow(base + [
                _celda_segura(i.curso.nombre),
                i.estado,
                i.origen,
                _celda_segura(i.medio_legible),
                _celda_segura(i.nota),
                dia(i.pagado_en),
                f"{i.monto:.2f}",
            ])
    return Response(
        "\ufeff" + salida.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=enid_alumnos.csv"},
    )


@app.route("/admin/usuarios/<int:usuario_id>/enlace-acceso", methods=["POST"])
@admin_required
def generar_enlace_acceso(usuario_id):
    """Genera un enlace para que el alumno elija (o recupere) su contraseña."""
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)
    reset_url = url_externa("resetear_password", token=generar_token_invitacion(usuario.email))
    flash(
        f"Enlace de acceso para {usuario.nombre} (vence en 7 días): {reset_url}",
        "info",
    )
    return redirect(url_for("administrar_usuarios"))


@app.route("/admin/inscripciones/<int:inscripcion_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_inscripcion(inscripcion_id):
    inscripcion = db.session.get(Inscripcion, inscripcion_id)
    if inscripcion is None:
        abort(404)

    # Los pagos asociados se borran en cascada (ver models.py)
    db.session.delete(inscripcion)
    db.session.commit()
    flash("Acceso eliminado." if inscripcion.origen == "manual" else f"Inscripción #{inscripcion_id} eliminada.", "success")
    return redirect(destino_seguro("administrar_inscripciones"))


@app.route("/admin/inscripciones/nueva", methods=["GET", "POST"])
@admin_required
def nueva_inscripcion_manual():
    """El dueño da el 'privilegio de alumno' a quien quiera, sin pasar por Mercado Pago.

    Sirve para quien pagó por PayPal/transferencia, para becas, para alumnos previos a la web.
    """
    cursos = db.session.execute(
        db.select(Curso).where(Curso.activo.is_(True)).order_by(Curso.nombre)
    ).scalars().all()

    if request.method == "POST":
        alumno_nombre = request.form.get("alumno_nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        medio = request.form.get("medio", "")
        medio = medio if medio in dict(MEDIOS_ACCESO) else "otro"
        nota = request.form.get("nota", "").strip()[:200] or None

        ids = request.form.getlist("curso_ids", type=int)
        curso_unico = request.form.get("curso_id", type=int)  # formulario viejo, por compatibilidad
        if curso_unico:
            ids.append(curso_unico)
        if request.form.get("todos_los_cursos") == "1":
            ids = [c.id for c in cursos]
        seleccionados = []
        for curso_id in dict.fromkeys(ids):
            curso = db.session.get(Curso, curso_id)
            if curso is not None:
                seleccionados.append(curso)

        if not seleccionados or not alumno_nombre:
            flash("Elegí al menos un curso y escribí el nombre del alumno.", "danger")
            return redirect(url_for("nueva_inscripcion_manual", nombre=alumno_nombre, email=email))

        try:
            email = validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            flash("Necesitamos un email válido: con él el alumno inicia sesión.", "danger")
            return redirect(url_for("nueva_inscripcion_manual", nombre=alumno_nombre))

        usuario = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == email)
        ).scalar_one_or_none()
        usuario_nuevo = usuario is None
        if usuario_nuevo:
            usuario = Usuario(nombre=alumno_nombre, email=email)
            usuario.establecer_password(secrets.token_urlsafe(32))
            db.session.add(usuario)
            db.session.flush()

        concedidos, ya_tenia = [], []
        for curso in seleccionados:
            if not usuario_nuevo and inscripcion_con_acceso(usuario, curso):
                ya_tenia.append(curso.nombre)
                continue
            db.session.add(Inscripcion(
                curso_id=curso.id,
                alumno_nombre=alumno_nombre,
                monto=curso.precio,
                estado="pagada",
                origen="manual",
                medio=medio,
                nota=nota,
                pagado_en=ahora_argentina(),
                usuario=usuario,
            ))
            concedidos.append(curso)

        if not concedidos:
            db.session.rollback()
            flash("Ese alumno ya tenía acceso a todo lo que elegiste.", "warning")
            return redirect(url_for("administrar_usuarios"))

        db.session.commit()
        flash(f"Acceso concedido a {usuario.nombre} en: {', '.join(c.nombre for c in concedidos)}.", "success")
        if ya_tenia:
            flash(f"Ya tenía acceso a: {', '.join(ya_tenia)}.", "info")

        invitacion = None
        if usuario_nuevo:
            invitacion = url_externa("resetear_password", token=generar_token_invitacion(email))
            if not mail_configurado():
                flash(
                    f"Cuenta creada para {email}. Pasale este enlace al alumno para que "
                    f"elija su contraseña (vence en 7 días): {invitacion}",
                    "info",
                )
        _intentar(enviar_acceso, usuario, concedidos, invitacion)
        return redirect(url_for("administrar_usuarios"))

    return render_template(
        "admin/inscripcion_manual.html",
        cursos=cursos,
        medios=MEDIOS_ACCESO,
        prefill_nombre=request.args.get("nombre", ""),
        prefill_email=request.args.get("email", ""),
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
            activo=form.activo.data,
        )
        db.session.add(curso)
        db.session.commit()
        flash("Curso creado. Ahora cargale las clases.", "success")
        return redirect(url_for("administrar_clases", curso_id=curso.id))

    return render_template("admin/curso_form.html", form=form, titulo="Nuevo curso")


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

    return render_template("admin/curso_form.html", form=form, titulo="Editar curso")


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


# ---------------------------------------------------------------------------
# Clases de cada curso (en vivo y grabadas)
# ---------------------------------------------------------------------------

def _guardar_clase(clase, form):
    fecha = parsear_fecha(form.fecha.data)
    if form.fecha.data and fecha is None:
        flash("La fecha no tenía un formato válido: la clase se guardó sin fecha.", "warning")
    clase.titulo = form.titulo.data.strip()
    clase.descripcion = (form.descripcion.data or "").strip() or None
    clase.fecha = fecha
    clase.meet_link = (form.meet_link.data or "").strip() or None
    clase.grabacion = (form.grabacion.data or "").strip() or None
    clase.publicada = form.publicada.data
    if form.orden.data is not None:
        clase.orden = form.orden.data


def _avisar_a_alumnos(clase, tipo):
    """Avisa por mail a los alumnos del curso (una sola vez por clase y tipo de aviso)."""
    if not clase.publicada:
        flash("La clase es un borrador: no se avisó a nadie.", "warning")
        return
    if not mail_configurado():
        flash("Los mails no están configurados: no se pudo avisar a los alumnos.", "warning")
        return
    resumen = _intentar(avisar, clase, tipo) or {"enviados": 0, "pendientes": 0, "ya_avisados": 0}
    if resumen["enviados"]:
        flash(f"Avisamos por mail a {resumen['enviados']} alumno{'s' if resumen['enviados'] != 1 else ''}.", "success")
    elif resumen["ya_avisados"]:
        flash("Los alumnos ya habían recibido este aviso.", "info")
    else:
        flash("Todavía no hay alumnos con avisos activados a quienes avisar.", "info")


@app.route("/admin/cursos/<int:curso_id>/clases")
@admin_required
def administrar_clases(curso_id):
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        abort(404)
    return render_template("admin/clases.html", curso=curso, ahora=ahora_argentina())


@app.route("/admin/cursos/<int:curso_id>/clases/nueva", methods=["GET", "POST"])
@admin_required
def nueva_clase(curso_id):
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        abort(404)

    form = ClaseForm()
    siguiente_orden = max((c.orden for c in curso.clases), default=0) + 1
    if request.method == "GET":
        form.orden.data = siguiente_orden

    if form.validate_on_submit():
        clase = Clase(curso=curso, orden=siguiente_orden)
        _guardar_clase(clase, form)
        db.session.add(clase)
        db.session.commit()
        flash("Clase creada.", "success")
        if form.avisar.data:
            _avisar_a_alumnos(clase, "nueva")
        return redirect(url_for("administrar_clases", curso_id=curso.id))

    return render_template("admin/clase_form.html", form=form, curso=curso, titulo="Nueva clase")


@app.route("/admin/clases/<int:clase_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_clase(clase_id):
    clase = db.session.get(Clase, clase_id)
    if clase is None:
        abort(404)

    form = ClaseForm(obj=clase)
    if request.method == "GET" and clase.fecha:
        # El input datetime-local solo entiende este formato
        form.fecha.data = clase.fecha.strftime("%Y-%m-%dT%H:%M")

    if form.validate_on_submit():
        tenia_grabacion = bool(clase.grabacion)
        _guardar_clase(clase, form)
        db.session.commit()
        flash("Clase actualizada.", "success")
        if form.avisar.data:
            _avisar_a_alumnos(clase, "grabacion" if clase.grabacion and not tenia_grabacion else "nueva")
        return redirect(url_for("administrar_clases", curso_id=clase.curso_id))

    return render_template("admin/clase_form.html", form=form, curso=clase.curso, titulo="Editar clase")


@app.route("/admin/clases/<int:clase_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_clase(clase_id):
    clase = db.session.get(Clase, clase_id)
    if clase is None:
        abort(404)
    curso_id = clase.curso_id
    db.session.delete(clase)
    db.session.commit()
    flash("Clase eliminada.", "success")
    return redirect(url_for("administrar_clases", curso_id=curso_id))


# ---------------------------------------------------------------------------
# Cuentas de usuario
# ---------------------------------------------------------------------------

@app.route("/registro", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    form = RegistroForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        usuario_existente = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == email)
        ).scalar_one_or_none()

        if usuario_existente:
            form.email.errors.append("Ya existe una cuenta con ese correo.")
        else:
            usuario = Usuario(nombre=form.nombre.data.strip(), email=email)
            usuario.establecer_password(form.password.data)
            db.session.add(usuario)
            db.session.commit()

            # Entra directo: así puede seguir con la compra sin más vueltas
            usuario.ultimo_ingreso = ahora_argentina()
            db.session.commit()
            login_user(usuario)
            _intentar(enviar_bienvenida, usuario)
            flash("¡Bienvenido a ENID! Tu cuenta está lista.", "success")
            return redirect(destino_seguro())

    return render_template("registro.html", form=form)


@app.route("/iniciar-sesion", methods=["GET", "POST"])
@limiter.limit("15 per minute", methods=["POST"])
def iniciar_sesion():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    form = InicioSesionForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        usuario = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == email)
        ).scalar_one_or_none()

        if usuario and usuario.verificar_password(form.password.data):
            usuario.ultimo_ingreso = ahora_argentina()
            db.session.commit()
            login_user(usuario)
            return redirect(destino_seguro())

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
    return render_template("mis_inscripciones.html", inscripciones=inscripciones)


@app.route("/curso/<int:curso_id>")
@login_required
def ver_curso(curso_id):
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        abort(404)

    if not tiene_acceso_curso(current_user, curso):
        flash("No tenés acceso a este curso.", "warning")
        return redirect(url_for("mis_inscripciones"))

    ahora = ahora_argentina()
    # Los alumnos solo ven las clases publicadas; el admin también ve los borradores
    clases = [c for c in curso.clases if c.publicada or current_user.es_admin]
    proxima = min(
        (c for c in clases if c.fecha and c.estado(ahora) in ("proxima", "en_curso")),
        key=lambda c: c.fecha,
        default=None,
    )
    return render_template(
        "curso_detalle.html", curso=curso, clases=clases, proxima=proxima, ahora=ahora
    )


# ---------------------------------------------------------------------------
# Landing + compra
# ---------------------------------------------------------------------------

@app.route("/")
def inicio():
    cursos = db.session.execute(
        db.select(Curso).where(Curso.activo.is_(True)).order_by(Curso.id)
    ).scalars().all()

    # Para que cada tarjeta muestre "Inscribirme", "Completar pago" o "Entrar al curso"
    estados = {}
    if current_user.is_authenticated:
        for inscripcion in current_user.inscripciones:
            if inscripcion.tiene_acceso():
                estados[inscripcion.curso_id] = "acceso"
            elif inscripcion.estado == "pendiente":
                estados.setdefault(inscripcion.curso_id, "pendiente")

    return render_template("index.html", cursos=cursos, estados=estados, **sitio.contenido_portada())


@app.route("/comprar/<int:curso_id>", methods=["GET", "POST"])
@login_required
def comprar_curso(curso_id):
    # Si el login nos devuelve acá por GET, volvemos a la grilla de cursos
    if request.method == "GET":
        return redirect(url_for("inicio") + "#precio")

    curso = db.session.get(Curso, curso_id)
    if curso is None or not curso.activo:
        flash("Ese curso ya no está disponible.", "warning")
        return redirect(url_for("inicio"))

    if not os.getenv("MP_ACCESS_TOKEN"):
        flash("Los pagos todavía no están configurados (falta MP_ACCESS_TOKEN).", "warning")
        return redirect(url_for("inicio"))

    if inscripcion_con_acceso(current_user, curso):
        flash("Ya tenés acceso a este curso.", "info")
        return redirect(url_for("ver_curso", curso_id=curso.id))

    # Reutiliza una inscripción pendiente (pago abandonado) en vez de duplicar filas
    inscripcion = db.session.execute(
        db.select(Inscripcion)
        .where(
            Inscripcion.usuario_id == current_user.id,
            Inscripcion.curso_id == curso.id,
            Inscripcion.estado == "pendiente",
            Inscripcion.origen == "web",
        )
        .order_by(Inscripcion.id.desc())
    ).scalars().first()

    if inscripcion is None:
        inscripcion = Inscripcion(
            curso=curso,
            usuario=current_user,
            alumno_nombre=current_user.nombre,
            monto=curso.precio,
            estado="pendiente",
            origen="web",
        )
        db.session.add(inscripcion)
    inscripcion.monto = curso.precio

    pago = inscripcion.pagos[0] if inscripcion.pagos else Pago(inscripcion=inscripcion)
    pago.monto = curso.precio
    pago.moneda = "ARS"
    pago.estado = "pendiente"
    db.session.add(pago)
    # Se confirma antes de llamar a Mercado Pago para no dejar la base bloqueada durante la llamada
    db.session.commit()

    base = url_publica()
    preference_data = {
        "items": [
            {
                "id": str(curso.id),
                "title": curso.nombre,
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": float(curso.precio),
            }
        ],
        "external_reference": str(inscripcion.id),
        "statement_descriptor": "ENID",
        "back_urls": {
            "success": f"{base}{url_for('pago_exitoso')}",
            "pending": f"{base}{url_for('pago_pendiente')}",
            "failure": f"{base}{url_for('pago_fallido')}",
        },
    }
    # Mercado Pago exige HTTPS para el retorno automático
    if base.startswith("https://"):
        preference_data["auto_return"] = "approved"

    try:
        sdk = mercadopago.SDK(os.getenv("MP_ACCESS_TOKEN"))
        resultado = sdk.preference().create(preference_data)
    except Exception:
        app.logger.exception("No se pudo crear la preferencia de Mercado Pago")
        flash("No se pudo conectar con Mercado Pago. Intentá nuevamente.", "danger")
        return redirect(url_for("inicio"))

    if resultado.get("status") != 201:
        app.logger.error("Mercado Pago rechazó la preferencia: %s", resultado)
        flash("Error al crear la preferencia de pago. Intentá nuevamente.", "danger")
        return redirect(url_for("inicio"))

    preferencia = resultado["response"]
    init_point = preferencia.get("init_point") or preferencia.get("sandbox_init_point")
    if not init_point:
        flash("Error al obtener la URL de pago. Intentá nuevamente.", "danger")
        return redirect(url_for("inicio"))

    pago.preferencia_id = preferencia.get("id") or preferencia.get("preference_id")
    db.session.commit()
    return redirect(init_point)


# ---------------------------------------------------------------------------
# Confirmación de pagos (webhook + verificación al volver de Mercado Pago)
# ---------------------------------------------------------------------------

def consultar_pago_mp(payment_id):
    """Pide el pago a Mercado Pago (fuente de verdad). None si no se pudo obtener."""
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token or not payment_id:
        return None
    try:
        resultado = mercadopago.SDK(token).payment().get(payment_id)
    except Exception:
        app.logger.exception("Error consultando el pago %s en Mercado Pago", payment_id)
        return None
    if resultado.get("status") != 200:
        app.logger.warning("Mercado Pago devolvió %s para el pago %s", resultado.get("status"), payment_id)
        return None
    return resultado.get("response") or {}


def aplicar_datos_pago(datos_pago):
    """Actualiza Pago e Inscripcion según un pago de Mercado Pago. Idempotente.

    Devuelve la inscripción afectada o None si el pago no corresponde a nada válido.
    """
    try:
        inscripcion_id = int(datos_pago.get("external_reference"))
        monto_mp = Decimal(str(datos_pago.get("transaction_amount")))
    except (TypeError, ValueError, InvalidOperation):
        app.logger.warning("Pago de MP sin external_reference/monto válidos: %s", datos_pago.get("id"))
        return None

    inscripcion = db.session.get(Inscripcion, inscripcion_id)
    if inscripcion is None:
        app.logger.warning("Inscripción %s inexistente (pago MP %s)", inscripcion_id, datos_pago.get("id"))
        return None

    pago = db.session.execute(
        db.select(Pago).where(Pago.inscripcion_id == inscripcion.id)
    ).scalars().first()
    if pago is None:
        app.logger.warning("La inscripción %s no tiene Pago local", inscripcion_id)
        return None

    if monto_mp != pago.monto or datos_pago.get("currency_id") != pago.moneda:
        app.logger.error(
            "Monto/moneda no coinciden en inscripción %s. MP: %s %s, local: %s %s",
            inscripcion_id, monto_mp, datos_pago.get("currency_id"), pago.monto, pago.moneda,
        )
        return None

    pago_externo_id = str(datos_pago.get("id"))
    estado_mp = datos_pago.get("status") or "desconocido"

    # Un intento posterior (rechazado, duplicado) no debe pisar un pago ya acreditado
    if (
        inscripcion.estado == "pagada"
        and estado_mp not in ESTADOS_REEMBOLSO
        and pago.pago_externo_id
        and pago.pago_externo_id != pago_externo_id
    ):
        app.logger.warning(
            "Inscripción %s ya pagada con %s; se ignora el pago %s (%s)",
            inscripcion_id, pago.pago_externo_id, pago_externo_id, estado_mp,
        )
        return inscripcion

    era_pagada = inscripcion.estado == "pagada"
    pago.pago_externo_id = pago_externo_id
    pago.estado = estado_mp

    if estado_mp == "approved":
        inscripcion.estado = "pagada"
        if inscripcion.pagado_en is None:
            inscripcion.pagado_en = ahora_argentina()
    elif estado_mp in ESTADOS_REEMBOLSO:
        inscripcion.estado = "reembolsada"

    db.session.commit()
    if estado_mp == "approved" and not era_pagada and inscripcion.usuario is not None:
        _intentar(enviar_comprobante, inscripcion)
    app.logger.info(
        "Inscripción %s -> %s (pago MP %s: %s)",
        inscripcion_id, inscripcion.estado, pago_externo_id, estado_mp,
    )
    return inscripcion


@app.route("/webhooks/mercadopago", methods=["POST"])
@csrf.exempt
def webhook_mercado_pago():
    secreto = os.getenv("MP_WEBHOOK_SECRET")
    if not secreto:
        app.logger.error("MP_WEBHOOK_SECRET no configurado")
        return "", 503

    evento = request.get_json(silent=True) or {}
    # Mercado Pago firma con el data.id de la query string; el body es el respaldo
    data_id = request.args.get("data.id") or (evento.get("data") or {}).get("id")
    firma = request.headers.get("x-signature")
    request_id = request.headers.get("x-request-id")

    if not firma or not data_id:
        return "", 400

    try:
        WebhookSignatureValidator.validate(firma, request_id, str(data_id), secreto)
    except InvalidWebhookSignatureError as error:
        app.logger.warning("Webhook con firma inválida: %s", error)
        return "", 401

    tipo = request.args.get("type") or evento.get("type")
    if tipo != "payment":
        return "", 200

    datos_pago = consultar_pago_mp(data_id)
    if datos_pago is None:
        return "", 500  # que Mercado Pago reintente

    aplicar_datos_pago(datos_pago)
    return "", 200


def _sincronizar_desde_retorno():
    """Al volver de Mercado Pago confirma el pago contra su API (no se confía en la URL)."""
    payment_id = request.args.get("payment_id") or request.args.get("collection_id")
    if not payment_id or payment_id == "null":
        return None
    datos_pago = consultar_pago_mp(payment_id)
    return aplicar_datos_pago(datos_pago) if datos_pago else None


@app.route("/pago/exitoso")
def pago_exitoso():
    inscripcion = _sincronizar_desde_retorno()
    if inscripcion is not None and inscripcion.estado == "pagada":
        flash("¡Pago aprobado! Ya tenés acceso a tu curso.", "success")
    else:
        flash(
            "Recibimos tu pago y lo estamos confirmando. En unos minutos aparece como "
            "pagado en “Mis inscripciones”.",
            "info",
        )
    return redirect(url_for("mis_inscripciones"))


@app.route("/pago/pendiente")
def pago_pendiente():
    _sincronizar_desde_retorno()
    flash("El pago está pendiente. Se habilita el acceso apenas se confirme.", "warning")
    return redirect(url_for("mis_inscripciones"))


@app.route("/pago/fallido")
def pago_fallido():
    flash("El pago no pudo procesarse. Podés reintentar cuando quieras.", "danger")
    return redirect(url_for("inicio") + "#precio")


# ---------------------------------------------------------------------------
# Recuperación de contraseña y email
# ---------------------------------------------------------------------------

@app.route("/recuperar-password", methods=["GET", "POST"])
@limiter.limit("6 per hour", methods=["POST"])
def recuperar_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        usuario = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == email)
        ).scalar_one_or_none()

        if usuario:
            _intentar(enviar_reset, usuario)

        # Misma respuesta exista o no el email: no se revela quién tiene cuenta
        flash("Si el email existe, recibirás instrucciones para restablecer tu contraseña.", "info")
        return redirect(url_for("iniciar_sesion"))

    return render_template("recuperar_password.html")


@app.route("/resetear-password/<token>", methods=["GET", "POST"])
def resetear_password(token):
    email = verificar_token_acceso(token)
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

    flash("Email confirmado correctamente. Ya podés iniciar sesión.", "success")
    return redirect(url_for("iniciar_sesion"))


# ---------------------------------------------------------------------------
# Comandos de consola (flask crear-admin / flask seed-cursos)
# ---------------------------------------------------------------------------

@app.cli.command("crear-admin")
@click.option("--email", prompt="Email del administrador")
@click.option("--nombre", prompt="Nombre", default="Administrador")
@click.password_option("--password", prompt="Contraseña (mínimo 8 caracteres)")
def crear_admin(email, nombre, password):
    """Crea un administrador, o promueve y actualiza la clave de un usuario existente."""
    email = email.strip().lower()
    if len(password) < 8:
        raise click.ClickException("La contraseña debe tener al menos 8 caracteres.")

    usuario = db.session.execute(
        db.select(Usuario).where(db.func.lower(Usuario.email) == email)
    ).scalar_one_or_none()
    if usuario is None:
        usuario = Usuario(nombre=nombre.strip(), email=email)
        db.session.add(usuario)
    usuario.establecer_password(password)
    usuario.es_admin = True
    db.session.commit()
    click.echo(f"Administrador listo: {email}")


@app.cli.command("seed-cursos")
def seed_cursos():
    """Carga cursos de ejemplo (editá nombres y precios desde el panel)."""
    ejemplos = [
        ("Curso Básico", 5000),
        ("Curso Avanzado", 8000),
        ("Curso Pro", 12000),
    ]
    for nombre, precio in ejemplos:
        existe = db.session.execute(
            db.select(Curso).where(Curso.nombre == nombre)
        ).scalar_one_or_none()
        if existe is None:
            db.session.add(
                Curso(nombre=nombre, descripcion=f"Descripción de {nombre}", precio=precio, activo=True)
            )
    db.session.commit()

    # Clases de ejemplo en el primer curso, solo si todavía no tiene ninguna
    primero = db.session.execute(db.select(Curso).order_by(Curso.id)).scalars().first()
    if primero is not None and not primero.clases:
        manana = ahora_argentina().replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=1)
        db.session.add_all([
            Clase(curso=primero, orden=1, titulo="Clase 1 · Introducción (grabada)",
                  descripcion="Ejemplo de clase ya grabada.",
                  grabacion="https://www.youtube.com/"),
            Clase(curso=primero, orden=2, titulo="Clase 2 · En vivo",
                  descripcion="Ejemplo de clase en vivo por Meet.",
                  fecha=manana, meet_link="https://meet.google.com/"),
        ])
        db.session.commit()

    for curso in db.session.execute(db.select(Curso).order_by(Curso.id)).scalars():
        click.echo(f"  {curso.id}: {curso.nombre} - ${curso.precio} ({len(curso.clases)} clases)")


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
