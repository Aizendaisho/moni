"""Herramientas de seguridad: revisar archivos y carpetas sin ejecutarlos (ver seguridad/analisis.py)."""

import difflib
import os
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..permissions.policy import Nivel
from ..seguridad import analisis, cuarentena, equipo, saber
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
def revisar_archivo(ruta: str) -> dict:
    """Revisa si un archivo es peligroso SIN abrirlo ni ejecutarlo: tipo real, extensión engañosa,
    reglas de malware (YARA), macros de Office, PDF con JavaScript, programas sin firma,
    Windows Defender y, en internet, solo el hash del archivo. Úsala cuando pregunten si un
    archivo, documento o descarga es seguro o tiene virus.

    Args:
      ruta: Ruta completa, o solo el nombre del archivo (se busca en Descargas, Escritorio y Documentos), o "descargas/nombre.pdf".
    """
    p = resolver(ruta)
    if p.is_dir():
        raise ValueError(f"{p} es una carpeta: usa revisar_carpeta")
    inf = analisis.analizar(
        p,
        _reglas,
        consultar_internet=settings.security_hash_lookup,
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
        if inf.veredicto != "sin hallazgos":
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


# ---------------------------------------------------------------- cuarentena

_cuarentena = cuarentena.Cuarentena(settings.data_dir / "cuarentena")


def _pregunta_poner(ruta: str, motivo: str = "") -> str:
    p = resolver(ruta)
    if not p.is_file():
        raise ValueError(f"{p} no es un archivo")
    return f"¿Muevo {p.name} a la cuarentena? Se aparta de {p.parent} y se puede devolver luego."


@herramienta(Nivel.CONFIRMAR, etiqueta="Moviendo a la cuarentena", resumen=_pregunta_poner)
def poner_en_cuarentena(ruta: str, motivo: str = "") -> dict:
    """Aparta un archivo peligroso o sospechoso: lo mueve a la cuarentena de Moni, desactivado para que no se pueda abrir por accidente. No lo borra; se puede devolver con sacar_de_cuarentena. Muestra al usuario una ventana de Sí/No.

    Args:
      ruta: Ruta completa o nombre del archivo (como en revisar_archivo).
      motivo: Por qué se aparta, en pocas palabras (por ejemplo "PDF con JavaScript").
    """
    ficha = _cuarentena.poner(resolver(ruta), motivo)
    return {
        "hecho": f"{ficha['nombre']} quedó en cuarentena",
        "id": ficha["id"],
        "estaba_en": ficha["ruta_original"],
    }


@herramienta(Nivel.LIBRE, etiqueta="Revisando la cuarentena")
def ver_cuarentena() -> list[dict]:
    """Lista los archivos que Moni tiene en cuarentena, con su ruta original, fecha y motivo."""
    return [
        {
            "id": f["id"],
            "archivo": f["nombre"],
            "estaba_en": f["ruta_original"],
            "fecha": f["fecha"].replace("T", " "),
            "motivo": f.get("motivo", ""),
        }
        for f in _cuarentena.listar()
    ]


def _pregunta_sacar(archivo: str) -> str:
    f = _cuarentena.buscar(archivo)
    motivo = f" Se apartó por: {f['motivo']}." if f.get("motivo") else ""
    return f"¿Devuelvo {f['nombre']} a {Path(f['ruta_original']).parent}?{motivo}"


@herramienta(Nivel.CONFIRMAR, etiqueta="Sacando de la cuarentena", resumen=_pregunta_sacar)
def sacar_de_cuarentena(archivo: str) -> dict:
    """Devuelve un archivo de la cuarentena a su carpeta original, tal como estaba. Úsalo solo si el usuario lo pide. Muestra una ventana de Sí/No.

    Args:
      archivo: Nombre del archivo o id que aparece en ver_cuarentena.
    """
    f = _cuarentena.restaurar(archivo)
    return {"hecho": f"{f['nombre']} volvió a su sitio", "ruta": f["restaurado_en"]}


# ---------------------------------------------------------------- chequeo de la PC


@herramienta(Nivel.LIBRE, etiqueta="Revisando la seguridad de la PC")
def chequeo_de_seguridad() -> dict:
    """Revisa la seguridad de esta PC sin cambiar nada: antivirus (Windows Defender), firewall, actualizaciones de Windows, control de cuentas (UAC), programas que arrancan solos, tareas programadas, puertos abiertos a la red y programas que corren desde carpetas raras. Devuelve lo que es riesgo, lo que merece atención y lo que está bien."""
    return equipo.evaluar(equipo.recoger())


# ---------------------------------------------------------------- conocimiento (ATT&CK, LOLBAS)

conocimiento_seguridad = saber.Saber(settings.data_dir / "seguridad")


def _ficha_attack(x: dict) -> dict:
    ficha = {"id": x["id"], "nombre": x["nombre"], "descripcion": x["descripcion"]}
    if "tacticas" in x:
        ficha["tactica"] = ", ".join(x["tacticas"])
        if x.get("mitigaciones"):
            ficha["como_protegerse"] = x["mitigaciones"]
        if x.get("deteccion"):
            ficha["como_detectarlo"] = x["deteccion"]
    else:
        ficha["tipo"] = x["tipo"]
        if x.get("alias"):
            ficha["tambien_llamado"] = x["alias"]
        if x.get("tecnicas"):
            ficha["tecnicas_que_usa"] = x["tecnicas"][:8]
    ficha["fuente"] = f"MITRE ATT&CK {x['id']}"
    return ficha


@herramienta(Nivel.LIBRE, etiqueta="Consultando MITRE ATT&CK")
def consultar_attack(consulta: str) -> list[dict]:
    """Busca en MITRE ATT&CK (base de conocimiento de ataques reales, sin internet): técnicas que usan los atacantes (cómo funcionan, cómo protegerse, cómo detectarlas) y malware o herramientas conocidas (Emotet, Mimikatz...). Úsala para explicar amenazas con datos verificados.

    Args:
      consulta: Un id (T1566, T1218.005, S0367), el nombre de un malware, o palabras clave; mejor en inglés (por ejemplo "phishing", "keylogging", "ransomware", "scheduled task").
    """
    resultados = conocimiento_seguridad.buscar_attack(consulta)
    if not resultados:
        return [
            {"nota": f"No encontré '{consulta}' en ATT&CK. Prueba con otras palabras en inglés."}
        ]
    return [_ficha_attack(x) for x in resultados]


@herramienta(Nivel.LIBRE, etiqueta="Consultando LOLBAS")
def consultar_programa_windows(programa: str) -> dict:
    """Dice si un programa de Windows (mshta.exe, certutil.exe, rundll32.exe...) aparece en LOLBAS, la lista de programas legítimos de Microsoft que los atacantes abusan, y para qué lo abusan. Úsala cuando un programa del sistema aparece en algo sospechoso.

    Args:
      programa: Nombre del programa o ruta completa, por ejemplo "certutil.exe".
    """
    e = conocimiento_seguridad.buscar_lolbas(programa)
    if e is None:
        return {
            "programa": programa,
            "en_lolbas": False,
            "nota": "No está en LOLBAS. Eso no dice si es seguro o no: solo que no es un "
            "programa de Microsoft conocido por ser abusado.",
        }
    tecnicas = []
    for t in e["tecnicas"]:
        encontrado = conocimiento_seguridad.buscar_attack(t)
        tecnicas.append(f"{t} {encontrado[0]['nombre']}" if encontrado else t)
    return {
        "programa": e["nombre"],
        "en_lolbas": True,
        "uso_normal": e["descripcion"],
        "donde_esta": e["rutas"][:2],
        "los_atacantes_lo_usan_para": e["abusos"],
        "tecnicas_attack": tecnicas,
        "nota": "Es un programa legítimo de Windows: que exista en tu PC es normal. Lo "
        "sospechoso es verlo lanzado por un documento, un script o desde una carpeta rara.",
        "fuente": "LOLBAS Project",
    }


@herramienta(Nivel.LIBRE, etiqueta="Actualizando el conocimiento de seguridad")
def actualizar_conocimiento_de_seguridad() -> dict:
    """Descarga de nuevo MITRE ATT&CK y LOLBAS (unos 55 MB) para tener la información de ataques al día. Se hace sola cada 30 días."""
    return conocimiento_seguridad.actualizar()
