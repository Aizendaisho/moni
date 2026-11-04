"""Herramientas de seguridad: revisar archivos y carpetas sin ejecutarlos (ver seguridad/analisis.py)."""

import difflib
import os
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..permissions.policy import Nivel
from ..seguridad import analisis
from .registry import herramienta

_reglas = analisis.Reglas([analisis.REGLAS_MONI, settings.data_dir / "reglas-yara"])

_HOME = Path(os.path.expanduser("~"))
# Nombre que usa la gente -> carpetas reales posibles (Windows en español muestra nombres
# traducidos, pero en disco se llaman en inglés; OneDrive puede mover Escritorio y Documentos).
CARPETAS = {
    "descargas": ["Downloads", "Descargas"],
    "escritorio": ["Desktop", "OneDrive/Desktop", "OneDrive/Escritorio", "Escritorio"],
    "documentos": ["Documents", "OneDrive/Documents", "OneDrive/Documentos", "Documentos"],
    "imagenes": ["Pictures", "OneDrive/Pictures", "Imágenes"],
    "musica": ["Music"],
    "videos": ["Videos"],
}
_SINONIMOS = {
    "downloads": "descargas", "download": "descargas", "descarga": "descargas",
    "desktop": "escritorio", "documents": "documentos", "mis documentos": "documentos",
    "imágenes": "imagenes", "fotos": "imagenes", "pictures": "imagenes", "música": "musica",
}  # fmt: skip


def carpeta_conocida(nombre: str, home: Path = _HOME) -> Path | None:
    clave = nombre.strip().lower().strip("/\\")
    clave = _SINONIMOS.get(clave, clave)
    for sub in CARPETAS.get(clave, []):
        p = home / sub
        if p.is_dir():
            return p
    return None


def resolver(ruta: str, home: Path = _HOME, buscar_en: list[Path] | None = None) -> Path:
    """Convierte lo que dice el usuario en una ruta real.

    Acepta rutas completas, "descargas/factura.pdf", "~/Desktop/x.exe" o solo un nombre
    ("factura.pdf"), que se busca en Descargas, Escritorio y Documentos. Lanza ValueError con
    un mensaje útil si no lo encuentra o si hay varios candidatos.
    """
    texto = os.path.expandvars(ruta.strip().strip('"').strip("'"))
    if texto.startswith("~"):
        texto = str(home) + texto[1:]
    p = Path(texto)
    if p.is_absolute():
        if p.exists():
            return p
        raise ValueError(f"No existe {p}")
    partes = Path(texto).parts
    if partes:
        base = carpeta_conocida(partes[0], home)
        if base is not None:
            q = base.joinpath(*partes[1:])
            if q.exists():
                return q
            texto = str(Path(*partes[1:])) if len(partes) > 1 else ""
            buscar_en = [base]
            if not texto:
                return base
    if buscar_en is None:
        buscar_en = [c for k in ("descargas", "escritorio", "documentos")
                     if (c := carpeta_conocida(k, home))]  # fmt: skip
    nombre = Path(texto).name.lower()
    candidatos: list[Path] = []
    for base in buscar_en:
        for q in _recorrer(base, profundidad=2):
            if q.name.lower() == nombre:
                candidatos.append(q)
    if len(candidatos) == 1:
        return candidatos[0]
    if len(candidatos) > 1:
        lista = "; ".join(str(c) for c in candidatos[:5])
        raise ValueError(f"Hay varios archivos llamados así: {lista}. ¿Cuál?")
    todos = [q for base in buscar_en for q in _recorrer(base, profundidad=2)]
    parecidos = difflib.get_close_matches(nombre, [q.name.lower() for q in todos], n=3, cutoff=0.6)
    if parecidos:
        sugerencias = [str(q) for q in todos if q.name.lower() in parecidos][:3]
        raise ValueError(f"No encontré '{ruta}'. ¿Quizás: {'; '.join(sugerencias)}?")
    donde = ", ".join(str(b) for b in buscar_en) or "las carpetas habituales"
    raise ValueError(f"No encontré '{ruta}' en {donde}. Pide la ruta completa.")


def _recorrer(base: Path, profundidad: int):
    try:
        for q in base.iterdir():
            if q.is_file():
                yield q
            elif q.is_dir() and profundidad > 0 and not q.name.startswith("."):
                yield from _recorrer(q, profundidad - 1)
    except OSError:
        return


@herramienta(Nivel.LIBRE, etiqueta="Revisando el archivo")
def revisar_archivo(ruta: str, consultar_internet: bool = True) -> dict:
    """Revisa si un archivo es peligroso SIN abrirlo ni ejecutarlo: tipo real, extensión engañosa,
    reglas de malware (YARA), macros de Office, PDF con JavaScript, programas sin firma,
    Windows Defender y, en internet, solo el hash del archivo. Úsala cuando pregunten si un
    archivo, documento o descarga es seguro o tiene virus.

    Args:
      ruta: Ruta completa, o solo el nombre del archivo (se busca en Descargas, Escritorio y Documentos), o "descargas/nombre.pdf".
      consultar_internet: Si se consulta el hash en bases de malware públicas. El archivo nunca se sube.
    """
    p = resolver(ruta)
    if p.is_dir():
        raise ValueError(f"{p} es una carpeta: usa revisar_carpeta")
    inf = analisis.analizar(
        p,
        _reglas,
        consultar_internet=consultar_internet and settings.security_hash_lookup,
        clave_abusech=settings.abusech_auth_key,
    )
    return inf.como_dict()


@herramienta(Nivel.LIBRE, etiqueta="Revisando la carpeta")
def revisar_carpeta(carpeta: str = "descargas", limite: int = 15) -> dict:
    """Revisión rápida de los archivos más recientes de una carpeta, sin abrirlos ni ejecutarlos.
    Úsala para "revisa mis descargas" o "lo último que descargué". Para el detalle de un archivo
    concreto, usa después revisar_archivo.

    Args:
      carpeta: "descargas", "escritorio", "documentos" o una ruta completa.
      limite: Cuántos archivos revisar, los más recientes primero (máximo 50).
    """
    base = carpeta_conocida(carpeta) or resolver(carpeta)
    if not base.is_dir():
        raise ValueError(f"{base} no es una carpeta")
    archivos = sorted(
        (q for q in base.iterdir() if q.is_file()),
        key=lambda q: q.stat().st_mtime,
        reverse=True,
    )[: max(1, min(int(limite), 50))]
    resumen = {"peligroso": 0, "sospechoso": 0, "sin hallazgos": 0}
    filas = []
    for q in archivos:
        try:
            inf = analisis.analizar(q, _reglas, usar_defender=False, consultar_internet=False)
        except OSError as exc:
            filas.append({"archivo": q.name, "error": str(exc)})
            continue
        resumen[inf.veredicto] += 1
        fila = {
            "archivo": q.name,
            "fecha": datetime.fromtimestamp(q.stat().st_mtime).strftime("%d/%m/%Y"),
            "veredicto": inf.veredicto,
        }
        if inf.hallazgos:
            fila["motivo"] = inf.como_dict()["hallazgos"][0]["detalle"]
        filas.append(fila)
    # primero lo preocupante
    orden = {"peligroso": 0, "sospechoso": 1, "sin hallazgos": 2}
    filas.sort(key=lambda f: orden.get(f.get("veredicto", ""), 3))
    return {
        "carpeta": str(base),
        "revisados": len(archivos),
        "resumen": resumen,
        "archivos": filas,
        "nota": "Revisión rápida sin Windows Defender ni consulta en internet.",
    }
