"""Íconos de trazo simple para la portada (SVG en línea, sin librerías ni pedidos externos).

Uso en plantillas:  {{ icono("pizarra") }}  o  {{ icono("pizarra", 40, "text-danger") }}
Heredan el color del texto (currentColor), así que se pintan con CSS.
Los temas de la portada («Qué vas a aprender») se escriben en el panel con estos nombres.
"""
from markupsafe import Markup, escape

# Cada valor es el contenido de un <svg viewBox="0 0 24 24"> dibujado solo con trazo.
TRAZOS = {
    # Modalidades: cómo se cursa
    "envivo": '<circle cx="12" cy="12" r="2.5"/><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4'
              'M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/>',
    "grabada": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M10 9.2v5.6l4.8-2.8z"/>',
    "ritmo": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "acceso": '<path d="M12 12c-2-2.7-3.6-4-5.5-4a4 4 0 0 0 0 8c1.9 0 3.5-1.3 5.5-4z'
              'm0 0c2 2.7 3.6 4 5.5 4a4 4 0 0 0 0-8c-1.9 0-3.5 1.3-5.5 4z"/>',
    "progreso": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "celular": '<rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M10.5 18.5h3"/>',
    "profe": '<circle cx="12" cy="7" r="3.5"/><path d="M5 21c0-3.9 3.1-7 7-7s7 3.1 7 7"/>',
    # Temas: qué se enseña
    "pizarra": '<rect x="3" y="4" width="18" height="13" rx="1.5"/><path d="M8 21l2-4M16 21l-2-4"/>'
               '<circle cx="8" cy="9" r="1.3"/><path d="M11 12l4-4M13 8h2v2"/>',
    "pelota": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5l3.6 2.6-1.4 4.2H9.8L8.4 10.1z"/>'
              '<path d="M12 3v4.5M20.5 9.5l-4.9.6M17.4 19.5l-3.2-5.2M6.6 19.5l3.2-5.2M3.5 9.5l4.9.6"/>',
    "silbato": '<path d="M3 13a5 5 0 1 0 10 0h8v-4H9.5"/><circle cx="8" cy="13" r="1.3"/><path d="M9.5 9V6"/>',
    "fisico": '<path d="M6.5 6.5v11M17.5 6.5v11M3 9.5v5M21 9.5v5M6.5 12h11"/>',
    "mente": '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5.2A3 3 0 0 0 7 17a3 3 0 0 0 5 2V5a3 3 0 0 0-3-1z"/>'
             '<path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5.2A3 3 0 0 1 17 17a3 3 0 0 1-5 2"/>',
    "video": '<rect x="2" y="6" width="14" height="12" rx="2"/><path d="M16 10.5l6-3.5v10l-6-3.5"/>',
    "equipo": '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.4"/>'
              '<path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M15 14.3c.6-.2 1.3-.3 2-.3 2.8 0 5 2.2 5 5"/>',
    "cancha": '<rect x="2" y="5" width="20" height="14" rx="1"/><path d="M12 5v14"/><circle cx="12" cy="12" r="2.6"/>'
              '<path d="M2 9h3v6H2M22 9h-3v6h3"/>',
    "juveniles": '<circle cx="8" cy="6" r="2.5"/><circle cx="16.5" cy="9" r="2"/>'
                 '<path d="M4 21v-3a4 4 0 0 1 8 0v3M13.5 21v-2.5a3 3 0 0 1 6 0V21"/>',
    "arco": '<path d="M3 20V6h18v14"/><path d="M3 10h18M7 6v14M11 6v14M15 6v14M19 6v14" opacity=".45"/>',
    "estrategia": '<circle cx="6" cy="6" r="2"/><path d="M15 4l4 4M19 4l-4 4"/><circle cx="18" cy="18" r="2"/>'
                  '<path d="M6 8c0 6 4 10 10 10"/><path d="M13.5 15.5L16 18l-2.5 2.5"/>',
    "estrella": '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    # Contenido y fichas de curso
    "libro": '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7"/>',
    "podcast": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/>',
    "noticias": '<path d="M4 5h13v14H6a2 2 0 0 1-2-2z"/><path d="M17 9h3v8a2 2 0 0 1-2 2M7 9h7M7 12.5h7M7 16h4"/>',
    "modulos": '<path d="M12 3l9 4.5-9 4.5-9-4.5z"/><path d="M3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>',
    "clases": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4v5"/>',
    "duracion": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5M9.5 2.5h5"/>',
}

# Los que tiene sentido elegir para un tema de la portada (en el orden en que se muestran en el panel)
ICONOS_TEMAS = ("pizarra", "estrategia", "pelota", "arco", "cancha", "silbato", "fisico", "mente",
                "video", "equipo", "juveniles", "profe", "libro", "estrella")

ICONO_POR_DEFECTO = "pelota"


def icono(nombre, tam=28, clase=""):
    """<svg> del ícono pedido; si el nombre no existe, la pelota (nunca rompe la página)."""
    trazo = TRAZOS.get((nombre or "").strip().lower(), TRAZOS[ICONO_POR_DEFECTO])
    return Markup(
        f'<svg class="icono {escape(clase)}" width="{int(tam)}" height="{int(tam)}" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{trazo}</svg>'
    )


# ---------------------------------------------------------------- temas de la portada

TEMAS_POR_DEFECTO = """\
pizarra | Táctica y estrategia | Sistemas de juego, fases del partido y cómo plantear cada rival.
fisico | Preparación física | Planificación de cargas, prevención de lesiones y puesta a punto.
equipo | Conducción de grupos | Liderazgo, comunicación y manejo del plantel.
mente | Psicología del deporte | Motivación, presión y toma de decisiones dentro de la cancha.
video | Análisis de video | Mirar partidos con ojo de entrenador y corregir con imágenes.
juveniles | Formación de juveniles | Qué y cómo entrenar en cada etapa de crecimiento."""

MAX_TEMAS = 12


def leer_temas(texto):
    """Una línea por tema: «ícono | Título | Descripción» (la descripción es opcional).

    Devuelve [(número_de_línea, ícono, título, descripción, error)], donde error es None
    si la línea está bien. Las líneas vacías se ignoran.
    """
    filas = []
    for numero, linea in enumerate((texto or "").splitlines(), start=1):
        if not linea.strip():
            continue
        partes = [p.strip() for p in linea.split("|", 2)]
        partes += [""] * (3 - len(partes))
        nombre, titulo, descripcion = partes[0].lower(), partes[1], partes[2]
        error = None
        if not titulo:
            error = "falta el título (formato: ícono | Título | Descripción)"
        elif nombre not in TRAZOS:
            error = f"el ícono «{partes[0]}» no existe"
        filas.append((numero, nombre, titulo, descripcion, error))
    return filas


def temas_portada(texto):
    """Los temas válidos, listos para la plantilla (las líneas con error se saltean)."""
    return [
        {"icono": nombre, "titulo": titulo, "descripcion": descripcion}
        for _, nombre, titulo, descripcion, error in leer_temas(texto)
        if error is None
    ][:MAX_TEMAS]
