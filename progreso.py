"""Progreso de los alumnos y armado del aula (módulos → clases → partes).

La unidad de progreso es lo que el alumno marca como visto:
- cada parte de una clase, si la clase tiene partes;
- la clase entera, si no tiene partes.

Así, el porcentaje de una clase es partes vistas / partes totales, y el de un
módulo o un curso suma las unidades de todas sus clases publicadas. Una clase
de 6 partes pesa más que una de 1, que es lo que el alumno siente al cursar.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from db import db
from models import Progreso


# ---------------------------------------------------------------- videos

_ID_YOUTUBE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_embed(url):
    """URL para un <iframe> si el video es de YouTube, Vimeo o Google Drive; si no, None."""
    if not url:
        return None
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    partes_ruta = [p for p in u.path.split("/") if p]

    video_id = None
    if host == "youtu.be" and partes_ruta:
        video_id = partes_ruta[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            video_id = (parse_qs(u.query).get("v") or [None])[0]
        elif len(partes_ruta) >= 2 and partes_ruta[0] in ("embed", "shorts", "live"):
            video_id = partes_ruta[1]
    if video_id:
        # youtube-nocookie: no deja cookies de seguimiento hasta que el alumno da play
        return f"https://www.youtube-nocookie.com/embed/{video_id}" if _ID_YOUTUBE.match(video_id) else None

    if host == "vimeo.com" and partes_ruta and partes_ruta[0].isdigit():
        return f"https://player.vimeo.com/video/{partes_ruta[0]}"
    if host == "player.vimeo.com":
        return url

    if host == "drive.google.com" and len(partes_ruta) >= 3 and partes_ruta[:2] == ["file", "d"]:
        return f"https://drive.google.com/file/d/{partes_ruta[2]}/preview"
    return None


# ---------------------------------------------------------------- progreso

def unidades(clase):
    """Claves (clase_id, parte_id) de lo que hay que ver para completar la clase."""
    if clase.partes:
        return [(clase.id, p.id) for p in clase.partes]
    return [(clase.id, None)]


def vistos(usuario, curso):
    """Conjunto de (clase_id, parte_id) que el usuario marcó como vistos en el curso."""
    ids_clases = [c.id for c in curso.clases]
    if not ids_clases:
        return set()
    filas = db.session.execute(
        db.select(Progreso.clase_id, Progreso.parte_id).where(
            Progreso.usuario_id == usuario.id,
            Progreso.clase_id.in_(ids_clases),
        )
    ).all()
    return {(f.clase_id, f.parte_id) for f in filas}


def _porcentaje(hechas, total):
    return round(100 * hechas / total) if total else 0


@dataclass
class Avance:
    hechas: int = 0
    total: int = 0

    @property
    def porcentaje(self):
        return _porcentaje(self.hechas, self.total)

    @property
    def completo(self):
        return self.total > 0 and self.hechas >= self.total

    def sumar(self, otro):
        self.hechas += otro.hechas
        self.total += otro.total


def avance_clase(clase, hechos):
    claves = unidades(clase)
    return Avance(sum(1 for k in claves if k in hechos), len(claves))


@dataclass
class GrupoModulo:
    """Un módulo (o el grupo de clases sin módulo, con modulo=None) listo para mostrar."""
    modulo: object
    clases: list = field(default_factory=list)
    avance: Avance = field(default_factory=Avance)

    @property
    def titulo(self):
        return self.modulo.titulo if self.modulo else "Otras clases"


def armar_aula(curso, clases, hechos):
    """Agrupa las clases visibles por módulo y calcula el avance de cada nivel.

    Devuelve (grupos, avance_por_clase, avance_curso).
    """
    por_clase = {c.id: avance_clase(c, hechos) for c in clases}
    grupos = []
    for modulo in curso.modulos:
        grupo = GrupoModulo(modulo, [c for c in clases if c.modulo_id == modulo.id])
        if grupo.clases:
            grupos.append(grupo)
    sueltas = [c for c in clases if c.modulo_id is None or c.modulo_id not in {m.id for m in curso.modulos}]
    if sueltas:
        grupos.append(GrupoModulo(None, sueltas))

    total = Avance()
    for grupo in grupos:
        for c in grupo.clases:
            grupo.avance.sumar(por_clase[c.id])
        total.sumar(grupo.avance)
    return grupos, por_clase, total


def marcar(usuario, clase, parte=None, visto=True):
    """Marca (o desmarca) como vista una parte, o la clase si no tiene partes."""
    parte_id = parte.id if parte else None
    fila = db.session.execute(
        db.select(Progreso).where(
            Progreso.usuario_id == usuario.id,
            Progreso.clase_id == clase.id,
            Progreso.parte_id.is_(None) if parte_id is None else Progreso.parte_id == parte_id,
        )
    ).scalars().first()
    if visto and fila is None:
        db.session.add(Progreso(usuario_id=usuario.id, clase_id=clase.id, parte_id=parte_id))
    elif not visto and fila is not None:
        db.session.delete(fila)
    db.session.commit()


# ---------------------------------------------------------------- ficha del curso

@dataclass
class ResumenCurso:
    """Lo que la tarjeta del catálogo cuenta del curso con íconos."""
    modulos: int = 0
    clases: int = 0
    videos: int = 0
    minutos: int = 0
    en_vivo: bool = False

    @property
    def duracion(self):
        """«45 min», «3 h», «3 h 20 min»; vacío si nadie cargó duraciones."""
        if not self.minutos:
            return ""
        horas, minutos = divmod(self.minutos, 60)
        if not horas:
            return f"{minutos} min"
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"


def resumen_curso(curso):
    """Cuenta solo lo publicado: es lo que el alumno va a encontrar al entrar."""
    clases = [c for c in curso.clases if c.publicada]
    ids_modulos = {m.id for m in curso.modulos}
    partes = [p for c in clases for p in c.partes]
    return ResumenCurso(
        modulos=len({c.modulo_id for c in clases if c.modulo_id in ids_modulos}),
        clases=len(clases),
        videos=len(partes),
        minutos=sum(p.duracion_min or 0 for p in partes),
        en_vivo=any(c.meet_link for c in clases),
    )
