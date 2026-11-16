"""Avisos de clases por mail: recordatorios automáticos y avisos de clase nueva.

Cada aviso queda registrado en `envios_aviso` (clase + alumno + tipo), así que se puede
ejecutar `flask enviar-recordatorios` cada pocos minutos sin mandar nada dos veces.
"""
import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from db import db
from emailer import armar_aviso_clase, armar_recordatorio, enviar_varios
from models import Clase, EnvioAviso, Inscripcion, ahora_argentina

log = logging.getLogger(__name__)

# (tipo, mínimo, máximo) de tiempo que falta para la clase.
# "24h" sale entre 24 y 12 horas antes; "1h", dentro de la última hora.
VENTANAS = (
    ("24h", timedelta(hours=12), timedelta(hours=24)),
    ("1h", timedelta(0), timedelta(hours=1)),
)


def alumnos_con_acceso(curso, solo_con_avisos=True):
    """Usuarios con acceso al curso (y, por defecto, que no se dieron de baja de los avisos)."""
    inscripciones = db.session.execute(
        db.select(Inscripcion).where(
            Inscripcion.curso_id == curso.id,
            Inscripcion.usuario_id.is_not(None),
        )
    ).scalars().all()
    alumnos = {}
    for inscripcion in inscripciones:
        usuario = inscripcion.usuario
        if not inscripcion.tiene_acceso() or not usuario or not usuario.email:
            continue
        if solo_con_avisos and not usuario.avisos_email:
            continue
        alumnos[usuario.id] = usuario
    return list(alumnos.values())


def avisar(clase, tipo, dry_run=False):
    """Manda el aviso `tipo` de la clase a quienes todavía no lo recibieron.

    tipo: '24h' | '1h' (recordatorios) | 'nueva' | 'grabacion'.
    Devuelve {'enviados', 'pendientes', 'ya_avisados'}.
    """
    ya_enviados = set(db.session.execute(
        db.select(EnvioAviso.usuario_id).where(
            EnvioAviso.clase_id == clase.id, EnvioAviso.tipo == tipo
        )
    ).scalars())
    destinatarios = alumnos_con_acceso(clase.curso)
    pendientes = [u for u in destinatarios if u.id not in ya_enviados]
    resumen = {"enviados": 0, "pendientes": len(pendientes), "ya_avisados": len(destinatarios) - len(pendientes)}
    if dry_run or not pendientes:
        return resumen

    # Se reserva cada envío antes de mandar: si dos ejecuciones se pisan, la segunda se saltea
    reservados = []
    for usuario in pendientes:
        db.session.add(EnvioAviso(clase_id=clase.id, usuario_id=usuario.id, tipo=tipo))
        try:
            db.session.commit()
            reservados.append(usuario)
        except IntegrityError:
            db.session.rollback()

    correos = [
        armar_recordatorio(u, clase, tipo) if tipo in ("24h", "1h") else armar_aviso_clase(u, clase, tipo)
        for u in reservados
    ]
    resumen["enviados"] = enviar_varios(correos)
    log.info("Aviso %s de la clase %s: %s enviados", tipo, clase.id, resumen["enviados"])
    return resumen


def enviar_recordatorios(dry_run=False, ahora=None):
    """Recordatorios de las clases en vivo de las próximas 24 horas.

    Devuelve una lista de (clase, tipo, resumen).
    """
    ahora = ahora or ahora_argentina()
    clases = db.session.execute(
        db.select(Clase).where(
            Clase.publicada.is_(True),
            Clase.fecha.is_not(None),
            Clase.fecha > ahora,
            Clase.fecha <= ahora + timedelta(hours=24),
            Clase.meet_link.is_not(None),
        )
    ).scalars().all()

    resultado = []
    for clase in clases:
        if clase.grabacion or not clase.meet_link:
            continue
        faltan = clase.fecha - ahora
        for tipo, minimo, maximo in VENTANAS:
            if minimo < faltan <= maximo:
                resultado.append((clase, tipo, avisar(clase, tipo, dry_run=dry_run)))
    return resultado
