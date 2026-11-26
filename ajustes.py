"""Ajustes editables del sitio (tabla `ajustes`) con valores por defecto."""
import logging
import os
import re

from flask import current_app, g

from db import db
from iconos import TEMAS_POR_DEFECTO
from models import Ajuste

log = logging.getLogger(__name__)

DEFAULTS = {
    "entrenador_nombre": "",
    "entrenador_titulo": "",
    "entrenador_bio": "",
    "entrenador_imagen_id": "",
    "portada_imagen_id": "",
    "whatsapp": "",
    "instagram": "",
    "email_contacto": "",
    "legal_titular": "",
    "legal_cuit": "",
    "legal_domicilio": "",
    # «Qué vas a aprender» en la portada: una línea por tema (ver iconos.leer_temas)
    "temas_portada": TEMAS_POR_DEFECTO,
}


def ajustes_sitio():
    """Dict con todos los ajustes (cacheado durante la request). Nunca rompe la página."""
    if "ajustes_sitio" in g:
        return g.ajustes_sitio
    valores = dict(DEFAULTS)
    try:
        for fila in db.session.execute(db.select(Ajuste)).scalars():
            if fila.clave in DEFAULTS:
                valores[fila.clave] = fila.valor or ""
    except Exception:  # p. ej. todavía no se corrió `flask db upgrade`
        db.session.rollback()
        log.warning("No se pudieron leer los ajustes del sitio", exc_info=True)
    g.ajustes_sitio = valores
    return valores


def guardar_ajustes(nuevos):
    for clave, valor in nuevos.items():
        if clave not in DEFAULTS:
            continue
        fila = db.session.get(Ajuste, clave)
        if fila is None:
            fila = Ajuste(clave=clave)
            db.session.add(fila)
        fila.valor = (valor or "").strip()
    db.session.commit()
    g.pop("ajustes_sitio", None)


def whatsapp_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def contacto_email():
    """Mail al que escriben los alumnos y al que llegan los avisos para el dueño."""
    return (
        ajustes_sitio().get("email_contacto")
        or os.getenv("CONTACT_EMAIL")
        or current_app.config.get("MAIL_USERNAME")
        or ""
    )
