"""Gestión: Mi cuenta, baja de avisos, importación de alumnos, tareas programadas y chequeos.

Todo lo que no es contenido público (sitio.py) ni compra/pagos (app.py).
"""
import hmac
import logging
import os

import click
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from avisos import enviar_recordatorios
from db import db
from emailer import (
    armar_acceso,
    enviar_varios,
    generar_token_invitacion,
    mail_configurado,
    url_externa,
    verificar_token_baja,
)
from extensions import csrf, limiter
from forms import CambiarPasswordForm, MiCuentaForm
from importador import MAX_BYTES, PLANTILLA, aplicar, csv_desde_lista, decodificar, parsear, planificar
from models import Curso, Usuario
from utils import admin_required

log = logging.getLogger(__name__)
bp = Blueprint("gestion", __name__, cli_group=None)


# ---------------------------------------------------------------------------
# Mi cuenta y baja de avisos
# ---------------------------------------------------------------------------

@bp.route("/mi-cuenta", methods=["GET", "POST"])
@login_required
def mi_cuenta():
    accion = request.form.get("accion") if request.method == "POST" else None
    cuenta = MiCuentaForm(
        prefix="cuenta", obj=current_user, formdata=request.form if accion == "cuenta" else None
    )
    clave = CambiarPasswordForm(prefix="pw", formdata=request.form if accion == "password" else None)

    if accion == "cuenta" and cuenta.validate_on_submit():
        current_user.nombre = cuenta.nombre.data.strip()
        current_user.avisos_email = cuenta.avisos_email.data
        db.session.commit()
        flash("Cambios guardados.", "success")
        return redirect(url_for("gestion.mi_cuenta"))

    if accion == "password" and clave.validate_on_submit():
        if not current_user.verificar_password(clave.actual.data):
            clave.actual.errors.append("La contraseña actual no es correcta.")
        else:
            current_user.establecer_password(clave.nueva.data)
            db.session.commit()
            flash("Contraseña actualizada.", "success")
            return redirect(url_for("gestion.mi_cuenta"))

    return render_template("gestion/mi_cuenta.html", cuenta=cuenta, clave=clave)


@bp.route("/baja-avisos/<token>", methods=["GET", "POST"])
def baja_avisos(token):
    """Darse de baja de los recordatorios y avisos de clases sin iniciar sesión."""
    usuario_id = verificar_token_baja(token)
    usuario = db.session.get(Usuario, usuario_id) if usuario_id else None
    if usuario is None:
        flash("El enlace no es válido.", "danger")
        return redirect(url_for("inicio"))

    if request.method == "POST":
        usuario.avisos_email = False
        db.session.commit()
        return render_template("gestion/baja_ok.html")
    return render_template("gestion/baja.html", usuario=usuario)


# ---------------------------------------------------------------------------
# Importación de alumnos desde CSV
# ---------------------------------------------------------------------------

@bp.route("/admin/alumnos/plantilla.csv")
@admin_required
def plantilla_csv():
    return Response(
        "\ufeff" + PLANTILLA,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantilla_alumnos.csv"},
    )


@bp.route("/admin/alumnos/importar", methods=["GET", "POST"])
@admin_required
def importar_alumnos():
    cursos = db.session.execute(db.select(Curso).order_by(Curso.nombre)).scalars().all()

    if request.method == "GET":
        return render_template("admin/importar.html", cursos=cursos, fase="subir")

    accion = request.form.get("accion")
    if accion == "previsualizar" and "lista" in request.form:
        # Lista de mails pegada: se arma el mismo CSV y sigue el camino de siempre (vista previa → confirmar)
        elegidos = {int(i) for i in request.form.getlist("curso_ids") if i.isdigit()}
        cursos_lista = [c for c in cursos if c.id in elegidos]
        if not cursos_lista:
            flash("Elegí al menos un curso para dar acceso.", "warning")
            return render_template("admin/importar.html", cursos=cursos, fase="subir",
                                   lista=request.form.get("lista", ""))
        texto = csv_desde_lista(request.form.get("lista", ""), cursos_lista, request.form.get("medio", ""))
        if len(texto.encode("utf-8")) > MAX_BYTES:
            abort(413)
    elif accion == "previsualizar":
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename:
            flash("Elegí un archivo CSV.", "warning")
            return redirect(url_for("gestion.importar_alumnos"))
        datos = archivo.read(MAX_BYTES + 1)
        if len(datos) > MAX_BYTES:
            flash("El archivo pesa más de 512 KB. Dividilo en partes.", "danger")
            return redirect(url_for("gestion.importar_alumnos"))
        texto = decodificar(datos)
    elif accion == "importar":
        texto = request.form.get("contenido", "")
        if len(texto.encode("utf-8")) > MAX_BYTES:
            abort(413)
    else:
        abort(400)

    # En los dos pasos se vuelve a leer y validar todo: no se confía en lo que mostró la vista previa
    filas, errores = parsear(texto, cursos)
    if errores:
        for error in errores:
            flash(error, "danger")
        return render_template("admin/importar.html", cursos=cursos, fase="subir")
    planificar(filas)

    if accion == "previsualizar":
        return render_template(
            "admin/importar.html", cursos=cursos, fase="vista_previa", filas=filas, contenido=texto,
            validas=sum(1 for f in filas if f.valida), con_errores=sum(1 for f in filas if f.errores),
            mail_ok=mail_configurado(),
        )

    resumen = aplicar(filas)
    invitar = request.form.get("invitar") == "1"
    enlaces, correos = [], []
    for usuario, concedidos, es_nueva in resumen["usuarios"]:
        enlace = None
        if es_nueva:
            enlace = url_externa("resetear_password", token=generar_token_invitacion(usuario.email))
            enlaces.append((usuario.nombre, usuario.email, enlace))
        if invitar and mail_configurado():
            correos.append(armar_acceso(usuario, concedidos, enlace))
    mails_enviados = enviar_varios(correos) if correos else 0
    if invitar and not mail_configurado():
        flash("Los mails todavía no están configurados: compartí los enlaces de abajo a mano.", "warning")
    return render_template(
        "admin/importar.html", cursos=cursos, fase="resultado", resumen=resumen,
        enlaces=enlaces, mails_enviados=mails_enviados,
    )


# ---------------------------------------------------------------------------
# Tarea programada por HTTP (para hostings sin cron propio)
# ---------------------------------------------------------------------------

def _token_cron_valido():
    esperado = os.getenv("CRON_TOKEN", "")
    if not esperado:
        return None  # función desactivada
    recibido = request.headers.get("Authorization", "").removeprefix("Bearer ").strip() or request.args.get("token", "")
    return hmac.compare_digest(recibido.encode(), esperado.encode())


@bp.route("/tareas/recordatorios", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit("60 per hour")
def tarea_recordatorios():
    """Dispara los recordatorios de clases. Pensado para un servicio de cron externo cada 10 minutos."""
    valido = _token_cron_valido()
    if valido is None:
        abort(404)
    if not valido:
        abort(403)
    resultado = enviar_recordatorios()
    return jsonify(
        ok=True,
        avisos=[{"clase": c.titulo, "tipo": t, **r} for c, t, r in resultado],
    )


# ---------------------------------------------------------------------------
# Comandos de consola
# ---------------------------------------------------------------------------

@bp.cli.command("enviar-recordatorios")
@click.option("--dry-run", is_flag=True, help="Muestra a quién le llegaría, sin enviar nada.")
def cmd_enviar_recordatorios(dry_run):
    """Envía los recordatorios de clases en vivo (24 h y 1 h antes). Programalo cada 10 minutos."""
    current_app.config["EMAIL_ASYNC"] = False  # el proceso termina enseguida: tiene que enviar antes
    resultado = enviar_recordatorios(dry_run=dry_run)
    if not resultado:
        click.echo("No hay recordatorios para enviar ahora.")
        return
    for clase, tipo, resumen in resultado:
        click.echo(
            f"{clase.titulo} [{tipo}]: {resumen['enviados']} enviados, "
            f"{resumen['pendientes']} pendientes, {resumen['ya_avisados']} ya avisados"
        )


@bp.cli.command("probar-mail")
@click.argument("destinatario")
def cmd_probar_mail(destinatario):
    """Envía un mail de prueba y muestra el error exacto si algo falla (clave, puerto, remitente...)."""
    from flask_mail import Message

    from extensions import mail

    if not mail_configurado():
        click.echo("✘ MAIL_USERNAME está vacío: configurá los datos SMTP en el .env (ver docs/MAILS.md).")
        raise SystemExit(1)
    app = current_app
    click.echo(f"Servidor: {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']} · usuario: {app.config['MAIL_USERNAME']}")
    click.echo(f"Remitente: {app.config['MAIL_DEFAULT_SENDER']}")
    try:
        with mail.connect() as conexion:
            conexion.send(Message(
                "Prueba de mails de ENID", recipients=[destinatario],
                body="Si estás leyendo esto, los mails de ENID funcionan.",
                html="<p>Si estás leyendo esto, los mails de <strong>ENID</strong> funcionan. ✅</p>",
            ))
    except Exception as error:
        click.echo(f"✘ No se pudo enviar: {error}")
        raise SystemExit(1)
    click.echo(f"✔ Mail de prueba enviado a {destinatario}. Revisá también la carpeta de spam.")


def _estado_migraciones():
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    config = current_app.extensions["migrate"].migrate.get_config()
    cabeza = ScriptDirectory.from_config(config).get_current_head()
    with db.engine.connect() as conexion:
        actual = MigrationContext.configure(conexion).get_current_revision()
    return actual, cabeza


def revisar_configuracion():
    """Lista de (nivel, texto) con lo que falta para recibir pagos reales. nivel: ok | aviso | error.

    La usan `flask verificar-config` y la página Administración → Lanzamiento."""
    from ajustes import ajustes_sitio, contacto_email

    app = current_app
    resultados = []  # (nivel, texto)  nivel: ok | aviso | error

    def agregar(nivel, texto):
        resultados.append((nivel, texto))

    secreto = app.config.get("SECRET_KEY") or ""
    if len(secreto) < 16 or secreto.lower() in {"x", "clave", "changeme", "secret", "dev"}:
        agregar("error", "SECRET_KEY es corta o de ejemplo. Generá una: python -c \"import secrets; print(secrets.token_hex(32))\"")
    elif len(secreto) < 32:
        agregar("aviso", "SECRET_KEY tiene menos de 32 caracteres; conviene una más larga.")
    else:
        agregar("ok", "SECRET_KEY larga y definida.")

    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    try:
        db.session.execute(db.text("SELECT 1"))
        if uri.startswith("sqlite"):
            agregar("aviso", "Base SQLite: sirve para empezar, pero con un hosting de disco efímero se pierde. En producción usá PostgreSQL.")
        else:
            agregar("ok", "Base de datos PostgreSQL conectada.")
        actual, cabeza = _estado_migraciones()
        if actual == cabeza:
            agregar("ok", "Migraciones al día.")
        else:
            agregar("error", f"Faltan migraciones (base en {actual}, última {cabeza}). Corré: flask db upgrade")
        admins = db.session.query(Usuario).filter_by(es_admin=True).count()
        agregar("ok" if admins else "error", f"Administradores: {admins}." + ("" if admins else " Creá uno con: flask crear-admin"))
        activos = db.session.query(Curso).filter_by(activo=True).count()
        agregar("ok" if activos else "aviso", f"Cursos activos: {activos}.")
    except Exception as error:
        agregar("error", f"No se pudo usar la base de datos: {error}")

    token = os.getenv("MP_ACCESS_TOKEN", "")
    if not token:
        agregar("error", "Falta MP_ACCESS_TOKEN.")
    elif token.startswith("TEST-"):
        agregar("error", "MP_ACCESS_TOKEN es de prueba (empieza con TEST-). Para cobrar de verdad usá las credenciales productivas.")
    else:
        agregar("aviso", "MP_ACCESS_TOKEN está cargado: confirmá que sea el de PRODUCCIÓN (Credenciales productivas), no el de prueba.")
    agregar("ok" if os.getenv("MP_WEBHOOK_SECRET") else "error",
            "MP_WEBHOOK_SECRET cargado." if os.getenv("MP_WEBHOOK_SECRET") else "Falta MP_WEBHOOK_SECRET (clave secreta del webhook).")

    publica = (os.getenv("PUBLIC_URL") or os.getenv("NGROK_URL") or "").strip()
    if not publica:
        agregar("error", "Falta PUBLIC_URL (la dirección https de tu web).")
    elif not publica.startswith("https://"):
        agregar("error", f"PUBLIC_URL ({publica}) no es https: Mercado Pago exige SSL en producción.")
    elif any(x in publica for x in ("localhost", "127.0.0.1", "ngrok")):
        agregar("aviso", f"PUBLIC_URL ({publica}) parece de pruebas. En producción usá tu dominio.")
    else:
        agregar("ok", f"PUBLIC_URL: {publica}")
    agregar("ok" if app.config.get("SESSION_COOKIE_SECURE") else "aviso",
            "Cookies de sesión marcadas como seguras." if app.config.get("SESSION_COOKIE_SECURE")
            else "Las cookies de sesión no son 'secure' (se activan con PUBLIC_URL https).")

    if not mail_configurado():
        agregar("aviso", "Mails sin configurar (MAIL_USERNAME vacío): se imprimen en consola y no llegan a nadie.")
    else:
        remitente = str(app.config.get("MAIL_DEFAULT_SENDER") or "")
        if "noreply@enid.com" in remitente:
            agregar("aviso", "MAIL_DEFAULT_SENDER sigue con el valor de ejemplo.")
        else:
            agregar("ok", f"Mails configurados ({app.config.get('MAIL_SERVER')}).")
    agregar("ok" if os.getenv("CRON_TOKEN") else "aviso",
            "CRON_TOKEN definido: podés disparar los recordatorios por HTTP." if os.getenv("CRON_TOKEN")
            else "Sin CRON_TOKEN: programá `flask enviar-recordatorios` cada 10 min (cron/servicio del hosting).")

    try:
        sitio = ajustes_sitio()
        faltan = [n for n in ("legal_titular", "legal_cuit", "legal_domicilio") if not sitio.get(n)]
        agregar("ok" if not faltan else "aviso",
                "Datos legales completos." if not faltan else "Faltan datos legales en Administración → Contenido del sitio (titular, CUIT, domicilio).")
        agregar("ok" if contacto_email() else "aviso",
                "Email de contacto definido." if contacto_email() else "Falta el email de contacto (Administración → Contenido del sitio).")
    except Exception:
        pass

    agregar("ok" if os.getenv("FLASK_DEBUG") != "1" else "error",
            "Modo debug apagado." if os.getenv("FLASK_DEBUG") != "1" else "FLASK_DEBUG=1: apagalo en producción.")

    try:
        from models import PlanMembresia
        sitio = ajustes_sitio()
        agregar("ok" if sitio.get("whatsapp") else "aviso",
                "WhatsApp cargado: se ve el botón flotante." if sitio.get("whatsapp")
                else "Falta el número de WhatsApp (Contenido del sitio → Contacto): sin él no aparece el botón flotante.")
        servidor = str(app.config.get("MAIL_SERVER") or "")
        if mail_configurado() and "gmail" in servidor:
            agregar("aviso", "Los mails salen por Gmail: sirve para empezar, pero tiene un límite diario y el newsletter "
                             "puede caer en spam. Con muchos suscriptores usá un servicio con tu dominio (docs/MAILS.md).")
        plan = db.session.execute(db.select(PlanMembresia).where(PlanMembresia.activo.is_(True))).first()
        if plan:
            agregar("aviso", "Membresía a la venta: en Mercado Pago → Webhooks tiene que estar marcado también "
                             "«Planes y suscripciones».")
    except Exception:
        db.session.rollback()

    return resultados


@bp.route("/admin/lanzamiento")
@admin_required
def lanzamiento():
    """Lo mismo que `flask verificar-config`, en el panel, más lo que se revisa a mano."""
    resultados = revisar_configuracion()
    return render_template("admin/lanzamiento.html", resultados=resultados,
                           errores=sum(1 for n, _ in resultados if n == "error"),
                           avisos=sum(1 for n, _ in resultados if n == "aviso"))


@bp.cli.command("verificar-config")
def cmd_verificar_config():
    """Revisa que la configuración esté lista para recibir pagos reales."""
    resultados = revisar_configuracion()
    iconos = {"ok": "✔", "aviso": "!", "error": "✘"}
    for nivel, texto in resultados:
        click.echo(f" {iconos[nivel]}  {texto}")
    errores = sum(1 for n, _ in resultados if n == "error")
    avisos = sum(1 for n, _ in resultados if n == "aviso")
    click.echo(f"\n{errores} error(es), {avisos} aviso(s).")
    if errores:
        raise SystemExit(1)
