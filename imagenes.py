"""Validación y optimización de las fotos que sube el dueño."""
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELES = 40_000_000
MAX_LADO = 1600
FORMATOS = {"JPEG", "PNG", "WEBP", "GIF"}


class ImagenInvalida(Exception):
    pass


def procesar_imagen(archivo, max_lado=MAX_LADO):
    """Recibe un FileStorage y devuelve (bytes, mimetype, ancho, alto).

    Verifica que sea una imagen de verdad, corrige la rotación del celular, borra los datos
    EXIF (ubicación, etc.), la achica a `max_lado` y la guarda como JPEG (o PNG si es transparente).
    """
    datos = archivo.read(MAX_BYTES + 1)
    if not datos:
        raise ImagenInvalida("Elegí una imagen para subir.")
    if len(datos) > MAX_BYTES:
        raise ImagenInvalida("La imagen pesa más de 10 MB. Probá con una más liviana.")

    try:
        imagen = Image.open(BytesIO(datos))
        if imagen.format not in FORMATOS:
            raise ImagenInvalida("Formato no admitido. Subí una foto JPG, PNG, WEBP o GIF.")
        if imagen.width * imagen.height > MAX_PIXELES:
            raise ImagenInvalida("La imagen es demasiado grande en píxeles.")
        imagen.load()
    except ImagenInvalida:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise ImagenInvalida("El archivo no es una imagen válida.")

    imagen = ImageOps.exif_transpose(imagen)
    imagen.thumbnail((max_lado, max_lado))
    salida = BytesIO()
    if imagen.mode in ("RGBA", "LA", "P") and ("transparency" in imagen.info or imagen.mode in ("RGBA", "LA")):
        imagen.convert("RGBA").save(salida, "PNG", optimize=True)
        mimetype = "image/png"
    else:
        imagen.convert("RGB").save(salida, "JPEG", quality=85, optimize=True, progressive=True)
        mimetype = "image/jpeg"
    return salida.getvalue(), mimetype, imagen.width, imagen.height
