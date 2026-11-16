"""Envío de mails (SMTP con Flask-Mail), tokens firmados y mensajes de ENID.

Sin MAIL_USERNAME configurado no se envía nada: los mails se imprimen en la consola
(modo desarrollo). Con MAIL_USERNAME, salen por SMTP.
"""
import html as html_lib
import logging
import os
import re
import threading

from flask import current_app, has_request_context, render_template, request, url_for
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ajustes import ajustes_sitio, contacto_email, whatsapp_digitos
from extensions import mail

log = logging.getLogger(__name__)

HORA = 3600
SIETE_DIAS = 7 * 24 * HORA


# ---------------------------------------------------------------------------
# Tokens firmados
# ---------------------------------------------------------------------------

def _serializador():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generar_token_reset(email):
    """Enlace para recuperar la contraseña (vence en 1 hora)."""
    return _serializador().dumps(email, salt="password-reset")


def generar_token_invitacion(email):
    """Enlace para que un alumno nuevo elija su contraseña (vence en 7 días)."""
    return _serializador().dumps(email, salt="invitacion")


def verificar_token_reset(token, max_age=HORA):
    try:
        return _serializador().loads(token, salt="password-reset", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def verificar_token_acceso(token):
    """Email del token si es un enlace de recuperación (1 h) o de invitación (7 días)."""
    for salt, max_age in (("password-reset", HORA), ("invitacion", SIETE_DIAS)):
        try:
            return _serializador().loads(token, salt=salt, max_age=max_age)
        except (SignatureExpired, BadSignature):
            continue
    return None


def generar_token_baja(usuario_id):
    return _serializador().dumps(usuario_id, salt="baja-avisos")


def verificar_token_baja(token):
    """El enlace de baja no vence: tiene que funcionar aunque el mail sea viejo."""
    try:
        return _serializador().loads(token, salt="baja-avisos")
    except BadSignature:
        return None


# ---------------------------------------------------------------------------
# URLs absolutas (también fuera de una request, p. ej. en los recordatorios)
# ---------------------------------------------------------------------------

def base_url():
    url = (os.getenv("PUBLIC_URL") or os.getenv("NGROK_URL") or "").strip().rstrip("/")
    if url:
        return url
    if has_request_context():
        return request.url_root.rstrip("/")
    return ""


def url_externa(endpoint, **values):
    if has_request_context():
        ruta = url_for(endpoint, **values)
    else:
        with current_app.test_request_context():
            ruta = url_for(endpoint, **values)
    return base_url() + ruta


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------

def mail_configurado():
    return bool(current_app.config.get("MAIL_USERNAME"))


def html_a_texto(html):
    """Versión de texto plano de un mail HTML (para clientes que no muestran HTML)."""
    texto = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    texto = re.sub(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", texto)
    texto = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h1|h2|h3|li)>", "\n", texto)
    texto = re.sub(r"(?s)<[^>]+>", "", texto)
    texto = html_lib.unescape(texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n\n", texto).strip()


def _mostrar_en_consola(destinatario, asunto, texto):
    print(f"\n{'=' * 60}\n[EMAIL SIMULADO] Para: {destinatario}\nAsunto: {asunto}\n{'=' * 60}")
    print(texto)
    print("=" * 60 + "\n")


def _enviar_mensajes(app, mensajes):
    """Envía todos los mensajes con una sola conexión SMTP. Devuelve cuántos salieron."""
    enviados = 0
    with app.app_context():
        try:
            with mail.connect() as conexion:
                for mensaje in mensajes:
                    try:
                        conexion.send(mensaje)
                        enviados += 1
                    except Exception:
                        log.exception("No se pudo enviar el mail a %s", mensaje.recipients)
        except Exception:
            log.exception("No se pudo abrir la conexión SMTP")
    return enviados


def enviar_varios(correos):
    """correos: lista de (destinatario, asunto, html). Devuelve cuántos se enviaron (o se
    encolaron, si el envío es asíncrono)."""
    correos = [c for c in correos if c[0]]
    if not correos:
        return 0

    if not mail_configurado():
        for destinatario, asunto, html in correos:
            _mostrar_en_consola(destinatario, asunto, html_a_texto(html))
        return len(correos)

    responder_a = contacto_email() or None
    mensajes = [
        Message(asunto, recipients=[destinatario], html=html, body=html_a_texto(html), reply_to=responder_a)
        for destinatario, asunto, html in correos
    ]
    app = current_app._get_current_object()
    if app.config.get("EMAIL_ASYNC", True) and not app.testing:
        threading.Thread(target=_enviar_mensajes, args=(app, mensajes), daemon=True).start()
        return len(mensajes)
    return _enviar_mensajes(app, mensajes)


def enviar_email(destinatario, asunto, html):
    return enviar_varios([(destinatario, asunto, html)]) == 1


# ---------------------------------------------------------------------------
# Mensajes de ENID
# ---------------------------------------------------------------------------

def _renderizar(plantilla, **contexto):
    sitio = ajustes_sitio()
    contexto.setdefault("url_sitio", base_url() or "#")
    contexto.setdefault("contacto_email", contacto_email())
    contexto.setdefault("whatsapp", whatsapp_digitos(sitio.get("whatsapp")))
    contexto.setdefault("legal_titular", sitio.get("legal_titular"))
    return render_template(f"emails/{plantilla}.html", **contexto)


def url_baja(usuario):
    return url_externa("gestion.baja_avisos", token=generar_token_baja(usuario.id))


def armar_bienvenida(usuario):
    html = _renderizar("bienvenida", usuario=usuario,
                       url_cursos=url_externa("inicio") + "#precio")
    return (usuario.email, "¡Bienvenido a ENID!", html)


def armar_reset(usuario):
    enlace = url_externa("resetear_password", token=generar_token_reset(usuario.email))
    return (usuario.email, "Restablecer tu contraseña de ENID",
            _renderizar("reset", usuario=usuario, enlace=enlace))


def armar_acceso(usuario, cursos, invitacion_url=None):
    nombres = ", ".join(c.nombre for c in cursos)
    html = _renderizar(
        "acceso", usuario=usuario, cursos=cursos, invitacion_url=invitacion_url,
        url_ingresar=url_externa("iniciar_sesion"), url_mis_cursos=url_externa("mis_inscripciones"),
    )
    return (usuario.email, f"Ya tenés acceso a {nombres}", html)


def armar_comprobante(inscripcion):
    usuario = inscripcion.usuario
    html = _renderizar(
        "comprobante", usuario=usuario, inscripcion=inscripcion, curso=inscripcion.curso,
        url_curso=url_externa("ver_curso", curso_id=inscripcion.curso_id),
        url_arrepentimiento=url_externa("sitio.arrepentimiento"),
    )
    return (usuario.email, f"Pago confirmado: {inscripcion.curso.nombre}", html)


def armar_recordatorio(usuario, clase, tipo):
    cuando = "mañana" if tipo == "24h" else "en una hora"
    html = _renderizar(
        "recordatorio", usuario=usuario, clase=clase, curso=clase.curso, cuando=cuando,
        url_curso=url_externa("ver_curso", curso_id=clase.curso_id), baja_url=url_baja(usuario),
    )
    return (usuario.email, f"Clase en vivo {cuando}: {clase.titulo}", html)


def armar_aviso_clase(usuario, clase, tipo):
    """tipo: 'nueva' (clase nueva) o 'grabacion' (la grabación ya está disponible)."""
    asunto = (f"Ya está la grabación: {clase.titulo}" if tipo == "grabacion"
              else f"Nueva clase en {clase.curso.nombre}: {clase.titulo}")
    html = _renderizar(
        "clase_nueva", usuario=usuario, clase=clase, curso=clase.curso, tipo=tipo,
        url_curso=url_externa("ver_curso", curso_id=clase.curso_id), baja_url=url_baja(usuario),
    )
    return (usuario.email, asunto, html)


def armar_arrepentimiento_alumno(solicitud):
    html = _renderizar("arrepentimiento_alumno", solicitud=solicitud)
    return (solicitud.email, f"Recibimos tu solicitud de arrepentimiento ({solicitud.codigo})", html)


def armar_arrepentimiento_dueno(solicitud):
    html = _renderizar("arrepentimiento_dueno", solicitud=solicitud,
                       url_panel=url_externa("sitio.admin_arrepentimientos"))
    return (contacto_email(), f"Solicitud de arrepentimiento {solicitud.codigo}", html)


# Atajos para enviar un solo mensaje
def enviar_bienvenida(usuario):
    return enviar_varios([armar_bienvenida(usuario)])


def enviar_reset(usuario):
    return enviar_varios([armar_reset(usuario)])


def enviar_acceso(usuario, cursos, invitacion_url=None):
    return enviar_varios([armar_acceso(usuario, cursos, invitacion_url)])


def enviar_comprobante(inscripcion):
    return enviar_varios([armar_comprobante(inscripcion)])


def enviar_arrepentimiento(solicitud):
    return enviar_varios([armar_arrepentimiento_alumno(solicitud), armar_arrepentimiento_dueno(solicitud)])
