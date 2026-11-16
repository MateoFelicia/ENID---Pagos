"""Extensiones compartidas (se inicializan en app.py con init_app)."""
import smtplib

import flask_mail
from flask import current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect

mail = Mail()
csrf = CSRFProtect()

# Límite de intentos por IP. Sin límites globales: se aplican solo donde se decora.
# En producción con varios procesos de gunicorn conviene RATELIMIT_STORAGE_URI=redis://...
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def _abrir_conexion_smtp(self):
    """Igual que Flask-Mail, pero con tiempo máximo de espera (MAIL_TIMEOUT, 20 s por defecto).

    Sin esto, un servidor de mail que no responde deja colgado el envío durante minutos.
    """
    timeout = float(current_app.config.get("MAIL_TIMEOUT", 20))
    if self.mail.use_ssl:
        host = smtplib.SMTP_SSL(self.mail.server, self.mail.port, timeout=timeout)
    else:
        host = smtplib.SMTP(self.mail.server, self.mail.port, timeout=timeout)
    host.set_debuglevel(int(self.mail.debug))
    if self.mail.use_tls:
        host.starttls()
    if self.mail.username and self.mail.password:
        host.login(self.mail.username, self.mail.password)
    return host


flask_mail.Connection.configure_host = _abrir_conexion_smtp
