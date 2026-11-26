"""Membresía mensual con débito automático (suscripciones / preapproval de Mercado Pago).

Cómo funciona:
1. El alumno toca *Suscribirme*: se crea una Suscripcion local (pending) y un
   preapproval en Mercado Pago con external_reference "sus-<id>". El alumno
   carga su tarjeta en Mercado Pago, que cobra todos los meses solo.
2. Mercado Pago avisa por webhook (topic subscription_preapproval) y la web
   vuelve a consultar el preapproval a la API antes de cambiar nada: igual que
   con los pagos, la URL o el aviso solos nunca dan acceso.
3. Mientras el preapproval esté "authorized", el alumno entra a todos los cursos.
   Si cancela, conserva el acceso hasta la fecha del próximo cobro (el mes ya pagado).
"""
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

import click
import mercadopago
import requests
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from db import db
from emailer import base_url
from models import ESTADOS_SUSCRIPCION, PlanMembresia, Suscripcion, ZONA_ARGENTINA, ahora_argentina
from utils import admin_required

log = logging.getLogger(__name__)
bp = Blueprint("membresia", __name__, cli_group=None)

PREFIJO_REFERENCIA = "sus-"


def plan_vigente():
    """El plan a la venta (o None si la membresía está apagada)."""
    return db.session.execute(
        db.select(PlanMembresia).where(PlanMembresia.activo.is_(True)).order_by(PlanMembresia.id)
    ).scalars().first()


@bp.app_context_processor
def _inyectar_plan():
    # Para mostrar la tarjeta de la membresía en la portada sin tocar la vista de inicio
    def membresia_a_la_venta():
        try:
            return plan_vigente()
        except Exception:  # p. ej. falta correr `flask db upgrade`
            db.session.rollback()
            return None
    return {"membresia_a_la_venta": membresia_a_la_venta}


# ---------------------------------------------------------------- Mercado Pago

def _sdk():
    token = os.getenv("MP_ACCESS_TOKEN")
    return mercadopago.SDK(token) if token else None


def consultar_preapproval(preapproval_id):
    """El preapproval según la API de Mercado Pago (fuente de verdad), o None."""
    sdk = _sdk()
    if sdk is None or not preapproval_id:
        return None
    try:
        resultado = sdk.preapproval().get(str(preapproval_id))
    except Exception:
        log.exception("Error consultando el preapproval %s", preapproval_id)
        return None
    if resultado.get("status") != 200:
        log.warning("Mercado Pago devolvió %s para el preapproval %s", resultado.get("status"), preapproval_id)
        return None
    return resultado.get("response") or {}


def preapproval_de_cobro(authorized_payment_id):
    """Cada cobro mensual llega como authorized_payment: devuelve el id de su preapproval."""
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token:
        return None
    try:
        r = requests.get(
            f"https://api.mercadopago.com/authorized_payments/{int(authorized_payment_id)}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except (requests.RequestException, ValueError):
        log.exception("Error consultando el cobro %s", authorized_payment_id)
        return None
    if r.status_code != 200:
        return None
    return (r.json() or {}).get("preapproval_id")


def _fecha_mp(texto):
    """'2026-12-26T10:00:00.000-04:00' → datetime en hora de Argentina (sin tz)."""
    if not texto:
        return None
    try:
        fecha = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(ZONA_ARGENTINA).replace(tzinfo=None)
    return fecha


def aplicar_preapproval(datos):
    """Actualiza la Suscripcion local según un preapproval de Mercado Pago. Idempotente.

    Devuelve la suscripción o None si el preapproval no corresponde a nada válido.
    """
    referencia = str(datos.get("external_reference") or "")
    if not referencia.startswith(PREFIJO_REFERENCIA):
        return None
    try:
        suscripcion_id = int(referencia[len(PREFIJO_REFERENCIA):])
    except ValueError:
        return None
    suscripcion = db.session.get(Suscripcion, suscripcion_id)
    if suscripcion is None:
        log.warning("Preapproval %s apunta a una suscripción inexistente", datos.get("id"))
        return None

    preapproval_id = str(datos.get("id") or "")
    if suscripcion.mp_preapproval_id and preapproval_id and suscripcion.mp_preapproval_id != preapproval_id:
        log.error("Preapproval %s no coincide con el guardado (%s)", preapproval_id, suscripcion.mp_preapproval_id)
        return None

    cobro = datos.get("auto_recurring") or {}
    try:
        monto = Decimal(str(cobro.get("transaction_amount")))
    except (InvalidOperation, ValueError):
        monto = None
    if monto != suscripcion.monto or cobro.get("currency_id") != "ARS":
        log.error("Monto/moneda del preapproval %s no coinciden con la suscripción %s", preapproval_id, suscripcion.id)
        return None

    estado = datos.get("status")
    if estado not in ESTADOS_SUSCRIPCION:
        return suscripcion

    estaba_activa = suscripcion.estado == "authorized"
    suscripcion.mp_preapproval_id = suscripcion.mp_preapproval_id or preapproval_id or None
    proximo = _fecha_mp(datos.get("next_payment_date"))
    if proximo:
        suscripcion.proximo_cobro = proximo
    if estado == "cancelled" and estaba_activa and suscripcion.acceso_hasta is None:
        # Conserva lo que ya pagó: acceso hasta la fecha en que se habría cobrado el mes siguiente
        if suscripcion.proximo_cobro and suscripcion.proximo_cobro > ahora_argentina():
            suscripcion.acceso_hasta = suscripcion.proximo_cobro
    if estado == "authorized":
        suscripcion.acceso_hasta = None
    suscripcion.estado = estado
    db.session.commit()
    return suscripcion


def sincronizar(preapproval_id):
    datos = consultar_preapproval(preapproval_id)
    return aplicar_preapproval(datos) if datos is not None else None


# ---------------------------------------------------------------- alumno

@bp.route("/membresia")
def ver():
    plan = plan_vigente()
    suscripcion = None
    if current_user.is_authenticated:
        suscripcion = current_user.membresia_activa or next(iter(current_user.suscripciones), None)
    if plan is None and suscripcion is None:
        abort(404)
    return render_template("membresia.html", plan=plan, suscripcion=suscripcion)


@bp.route("/membresia/suscribirme", methods=["POST"])
@login_required
def suscribirme():
    plan = plan_vigente()
    if plan is None:
        flash("La membresía no está disponible en este momento.", "warning")
        return redirect(url_for("inicio"))
    if current_user.membresia_activa is not None:
        flash("Ya tenés la membresía activa.", "info")
        return redirect(url_for("membresia.ver"))
    sdk = _sdk()
    if sdk is None:
        flash("Los pagos todavía no están configurados (falta MP_ACCESS_TOKEN).", "warning")
        return redirect(url_for("membresia.ver"))

    # Reutiliza una suscripción que quedó sin terminar en vez de duplicar filas
    suscripcion = next(
        (s for s in current_user.suscripciones if s.estado == "pending" and s.plan_id == plan.id),
        None,
    )
    if suscripcion is None:
        suscripcion = Suscripcion(usuario=current_user, plan=plan, estado="pending")
        db.session.add(suscripcion)
    suscripcion.monto = plan.precio
    suscripcion.mp_preapproval_id = None
    db.session.commit()

    base = base_url() or request.url_root.rstrip("/")
    datos = {
        "reason": plan.nombre,
        "external_reference": f"{PREFIJO_REFERENCIA}{suscripcion.id}",
        "payer_email": current_user.email,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(plan.precio),
            "currency_id": "ARS",
        },
        "back_url": f"{base}{url_for('membresia.vuelta')}",
        "status": "pending",
    }
    try:
        resultado = sdk.preapproval().create(datos)
    except Exception:
        log.exception("No se pudo crear el preapproval")
        flash("No se pudo conectar con Mercado Pago. Intentá nuevamente.", "danger")
        return redirect(url_for("membresia.ver"))
    if resultado.get("status") not in (200, 201):
        log.error("Mercado Pago rechazó el preapproval: %s", resultado)
        flash("Mercado Pago no pudo crear la suscripción. Intentá nuevamente.", "danger")
        return redirect(url_for("membresia.ver"))

    respuesta = resultado.get("response") or {}
    init_point = respuesta.get("init_point")
    if not init_point:
        flash("Error al obtener la página de pago. Intentá nuevamente.", "danger")
        return redirect(url_for("membresia.ver"))
    suscripcion.mp_preapproval_id = str(respuesta.get("id") or "") or None
    db.session.commit()
    return redirect(init_point)


@bp.route("/membresia/vuelta")
@login_required
def vuelta():
    """Al volver de Mercado Pago confirma contra su API (no se confía en la URL)."""
    preapproval_id = request.args.get("preapproval_id")
    propia = next((s for s in current_user.suscripciones if s.mp_preapproval_id == preapproval_id), None)
    suscripcion = sincronizar(preapproval_id) if propia else None
    if suscripcion is not None and suscripcion.estado == "authorized":
        flash("¡Listo! Tu membresía está activa: ya podés entrar a todos los cursos.", "success")
        return redirect(url_for("mis_inscripciones"))
    flash("Estamos esperando la confirmación de Mercado Pago. En unos minutos se activa sola.", "info")
    return redirect(url_for("membresia.ver"))


@bp.route("/membresia/cancelar", methods=["POST"])
@login_required
def cancelar():
    suscripcion = next((s for s in current_user.suscripciones if s.estado in ("authorized", "paused")), None)
    if suscripcion is None or not suscripcion.mp_preapproval_id:
        flash("No tenés una membresía activa para cancelar.", "info")
        return redirect(url_for("membresia.ver"))
    sdk = _sdk()
    try:
        resultado = sdk.preapproval().update(suscripcion.mp_preapproval_id, {"status": "cancelled"}) if sdk else {}
    except Exception:
        log.exception("No se pudo cancelar el preapproval %s", suscripcion.mp_preapproval_id)
        resultado = {}
    if resultado.get("status") != 200:
        flash("No pudimos cancelar en Mercado Pago. Probá de nuevo o escribinos.", "danger")
        return redirect(url_for("membresia.ver"))

    # Se vuelve a consultar para registrar el estado real (y la fecha hasta la que tiene acceso)
    if sincronizar(suscripcion.mp_preapproval_id) is None:
        suscripcion.estado = "cancelled"
        if suscripcion.proximo_cobro and suscripcion.proximo_cobro > ahora_argentina():
            suscripcion.acceso_hasta = suscripcion.proximo_cobro
        db.session.commit()
    if suscripcion.acceso_hasta:
        flash(f"Membresía cancelada. No se te cobra más y seguís teniendo acceso hasta el "
              f"{suscripcion.acceso_hasta:%d/%m/%Y}.", "success")
    else:
        flash("Membresía cancelada. No se te va a cobrar más.", "success")
    return redirect(url_for("membresia.ver"))


# ---------------------------------------------------------------- panel del dueño

class PlanForm(FlaskForm):
    nombre = StringField("Nombre", validators=[DataRequired(), Length(max=120)], default="Membresía ENID")
    descripcion = TextAreaField(
        "Qué incluye (opcional)",
        validators=[Optional(), Length(max=500)],
        description="Se muestra en la portada y en la página de la membresía.",
    )
    precio = DecimalField("Precio por mes en ARS", places=2, validators=[DataRequired(), NumberRange(min=1)])
    activo = BooleanField("A la venta")
    enviar = SubmitField("Guardar")


@bp.route("/admin/membresia", methods=["GET", "POST"])
@admin_required
def administrar():
    plan = db.session.execute(db.select(PlanMembresia).order_by(PlanMembresia.id)).scalars().first()
    form = PlanForm(obj=plan)
    if form.validate_on_submit():
        if plan is None:
            plan = PlanMembresia()
            db.session.add(plan)
        cambio_precio = plan.precio is not None and Decimal(plan.precio) != form.precio.data
        plan.nombre = form.nombre.data.strip()
        plan.descripcion = (form.descripcion.data or "").strip() or None
        plan.precio = form.precio.data
        plan.activo = form.activo.data
        db.session.commit()
        flash("Membresía guardada.", "success")
        if cambio_precio:
            flash("El precio nuevo se aplica a las suscripciones nuevas. Las que ya existen siguen con su precio.", "info")
        return redirect(url_for("membresia.administrar"))

    suscripciones = db.session.execute(
        db.select(Suscripcion).order_by(Suscripcion.id.desc())
    ).scalars().all()
    activas = sum(1 for s in suscripciones if s.da_acceso())
    return render_template(
        "admin/membresia.html", form=form, plan=plan, suscripciones=suscripciones, activas=activas,
        estados=ESTADOS_SUSCRIPCION,
    )


@bp.cli.command("sincronizar-membresias")
def cmd_sincronizar():
    """Vuelve a consultar en Mercado Pago las suscripciones vigentes (respaldo de los webhooks). Correrlo a diario."""
    pendientes = db.session.execute(
        db.select(Suscripcion).where(
            Suscripcion.mp_preapproval_id.is_not(None),
            Suscripcion.estado.in_(["pending", "authorized", "paused"]),
        )
    ).scalars().all()
    cambios = 0
    for suscripcion in pendientes:
        antes = suscripcion.estado
        if sincronizar(suscripcion.mp_preapproval_id) and suscripcion.estado != antes:
            cambios += 1
    click.echo(f"Revisadas {len(pendientes)} suscripciones; {cambios} cambiaron de estado.")
