"""Importación de alumnos desde un CSV (Excel / Google Sheets → "Guardar como CSV").

Columnas (en cualquier orden, con o sin acentos): nombre, email, cursos, medio, nota.
  - cursos: nombres separados por "|" (o ";", "+"), o la palabra "todos".
  - medio:  paypal, transferencia, efectivo, beca, otro (opcional; por defecto "importado").
  - nota:   texto libre (opcional).
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email

from db import db
from models import Curso, Inscripcion, Usuario, ahora_argentina
from utils import inscripcion_con_acceso

MAX_BYTES = 512 * 1024
MAX_FILAS = 1000

COLUMNAS = {
    "nombre": {"nombre", "alumno", "name", "nombre completo", "nombre y apellido", "apellido y nombre"},
    "email": {"email", "e-mail", "mail", "correo", "correo electronico"},
    "cursos": {"cursos", "curso", "course", "courses"},
    "medio": {"medio", "medio de pago", "forma de pago", "pago"},
    "nota": {"nota", "notas", "observaciones", "comentario", "comentarios"},
}
MEDIOS = {
    "paypal": "paypal",
    "transferencia": "transferencia", "transfer": "transferencia",
    "efectivo": "efectivo", "cash": "efectivo",
    "beca": "beca", "regalo": "beca", "beca o regalo": "beca",
    "otro": "otro",
}
PLANTILLA = "nombre,email,cursos,medio,nota\nAna Pérez,ana@ejemplo.com,Curso Básico,transferencia,Pagó el 12/10\nLuis Gómez,luis@ejemplo.com,todos,beca,Hijo de un amigo\n"


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def decodificar(datos):
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1")


@dataclass
class Fila:
    linea: int
    nombre: str = ""
    email: str = ""
    cursos: list = field(default_factory=list)
    medio: str = "importado"
    nota: str = ""
    errores: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    repetida_de: int = 0  # línea de la fila con el mismo email, a la que se unieron los cursos
    # Se completan al planificar contra la base de datos
    cuenta_existe: bool = False
    cursos_nuevos: list = field(default_factory=list)
    cursos_ya_tenia: list = field(default_factory=list)

    @property
    def valida(self):
        return not self.errores and not self.repetida_de


def _delimitador(texto):
    primera = texto.splitlines()[0] if texto.strip() else ""
    return max((";", ",", "\t"), key=primera.count)


def _cursos_de_celda(celda, por_nombre, activos):
    """Devuelve (cursos, desconocidos)."""
    valor = normalizar(celda)
    if valor in {"todos", "todo", "all", "*"}:
        return list(activos), []
    if valor in por_nombre:
        return [por_nombre[valor]], []
    encontrados, desconocidos = [], []
    for parte in re.split(r"[|;+,]", celda or ""):
        clave = normalizar(parte)
        if not clave:
            continue
        if clave in por_nombre:
            if por_nombre[clave] not in encontrados:
                encontrados.append(por_nombre[clave])
        else:
            desconocidos.append(parte.strip())
    return encontrados, desconocidos


def parsear(texto, cursos):
    """Lee el CSV. Devuelve (filas, errores_generales). No toca la base de datos."""
    activos = [c for c in cursos if c.activo]
    por_nombre = {normalizar(c.nombre): c for c in cursos}
    texto = (texto or "").lstrip("\ufeff")
    if not texto.strip():
        return [], ["El archivo está vacío."]

    lector = csv.reader(io.StringIO(texto), delimiter=_delimitador(texto))
    filas_crudas = [fila for fila in lector if any(celda.strip() for celda in fila)]
    if not filas_crudas:
        return [], ["El archivo está vacío."]

    columnas = {}
    for indice, titulo in enumerate(filas_crudas[0]):
        clave = normalizar(titulo)
        for nombre, sinonimos in COLUMNAS.items():
            if clave in sinonimos and nombre not in columnas:
                columnas[nombre] = indice
    faltan = [n for n in ("nombre", "email", "cursos") if n not in columnas]
    if faltan:
        return [], [f"Faltan columnas en la primera fila: {', '.join(faltan)}. Descargá la plantilla de ejemplo."]

    datos = filas_crudas[1:]
    if len(datos) > MAX_FILAS:
        return [], [f"El archivo tiene {len(datos)} filas; el máximo por importación es {MAX_FILAS}."]

    def celda(fila, nombre):
        indice = columnas.get(nombre)
        return fila[indice].strip() if indice is not None and indice < len(fila) else ""

    filas, por_email = [], {}
    for numero, cruda in enumerate(datos, start=2):
        fila = Fila(linea=numero, nombre=celda(cruda, "nombre"), nota=celda(cruda, "nota"))

        if not fila.nombre:
            fila.errores.append("falta el nombre")
        elif len(fila.nombre) > 120:
            fila.errores.append("el nombre es demasiado largo")
        if len(fila.nota) > 200:
            fila.nota = fila.nota[:200]
            fila.avisos.append("la nota se recortó a 200 caracteres")

        try:
            fila.email = validate_email(celda(cruda, "email"), check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            fila.errores.append("el email no es válido")

        cursos_fila, desconocidos = _cursos_de_celda(celda(cruda, "cursos"), por_nombre, activos)
        if desconocidos:
            fila.errores.append("curso que no existe: " + ", ".join(desconocidos))
        if not cursos_fila and not desconocidos:
            fila.errores.append("falta el curso")
        fila.cursos = cursos_fila

        medio = normalizar(celda(cruda, "medio"))
        if medio:
            if medio in MEDIOS:
                fila.medio = MEDIOS[medio]
            else:
                fila.medio = "otro"
                fila.avisos.append(f"medio “{celda(cruda, 'medio')}” desconocido: se usó “otro”")

        # Mismo email en dos filas: se unifican los cursos en la primera
        if fila.valida and fila.email in por_email:
            primera = por_email[fila.email]
            for curso in fila.cursos:
                if curso not in primera.cursos:
                    primera.cursos.append(curso)
            primera.avisos.append(f"el email también está en la línea {fila.linea}: se unieron los cursos")
            fila.repetida_de = primera.linea
        elif fila.valida:
            por_email[fila.email] = fila
        filas.append(fila)
    return filas, []


def planificar(filas):
    """Marca, para cada fila válida, qué se va a crear y qué ya existía."""
    for fila in filas:
        if not fila.valida:
            continue
        usuario = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == fila.email)
        ).scalar_one_or_none()
        fila.cuenta_existe = usuario is not None
        fila.cursos_nuevos, fila.cursos_ya_tenia = [], []
        for curso in fila.cursos:
            if usuario is not None and inscripcion_con_acceso(usuario, curso):
                fila.cursos_ya_tenia.append(curso)
            else:
                fila.cursos_nuevos.append(curso)
    return filas


def aplicar(filas):
    """Crea las cuentas y los accesos de las filas válidas. Devuelve un resumen.

    El envío de mails y los enlaces de invitación los resuelve quien llama, con el resumen.
    """
    import secrets

    resumen = {"cuentas_nuevas": [], "accesos": 0, "ya_tenian": 0, "filas_ok": 0, "usuarios": []}
    for fila in filas:
        if not fila.valida:
            continue
        usuario = db.session.execute(
            db.select(Usuario).where(db.func.lower(Usuario.email) == fila.email)
        ).scalar_one_or_none()
        es_nueva = usuario is None
        if es_nueva:
            usuario = Usuario(nombre=fila.nombre, email=fila.email)
            usuario.establecer_password(secrets.token_urlsafe(32))
            db.session.add(usuario)
            db.session.flush()
            resumen["cuentas_nuevas"].append(usuario)

        concedidos = []
        for curso in fila.cursos:
            if not es_nueva and inscripcion_con_acceso(usuario, curso):
                resumen["ya_tenian"] += 1
                continue
            db.session.add(Inscripcion(
                curso_id=curso.id, alumno_nombre=fila.nombre, monto=curso.precio,
                estado="pagada", origen="manual", medio=fila.medio, nota=fila.nota or None,
                pagado_en=ahora_argentina(), usuario=usuario,
            ))
            concedidos.append(curso)
        db.session.flush()
        resumen["accesos"] += len(concedidos)
        resumen["filas_ok"] += 1
        if concedidos:
            resumen["usuarios"].append((usuario, concedidos, es_nueva))
    db.session.commit()
    return resumen
