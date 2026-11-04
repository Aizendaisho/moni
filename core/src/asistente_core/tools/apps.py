"""Abrir y cerrar programas (sprint S2).

- Abrir es nivel LIBRE: usa la misma lista que el menú Inicio (Get-StartApps), así funciona
  igual con programas normales y con apps de la Tienda (Calculadora, Fotos, etc.).
- Cerrar es nivel CONFIRMAR: Moni pregunta antes. Primero pide a las ventanas que se cierren
  solas (como el botón X, así el programa puede guardar); solo fuerza si se lo piden.
- Hay procesos protegidos que Moni nunca cierra (Windows, Ollama, la propia Moni...).
"""

import difflib
import json
import platform
import re
import subprocess
import time
import unicodedata
from functools import lru_cache

import psutil

from ..permissions.policy import Nivel
from .registry import herramienta

ES_WINDOWS = platform.system() == "Windows"
_SIN_VENTANA = 0x08000000 if ES_WINDOWS else 0  # CREATE_NO_WINDOW

# Procesos que Moni nunca cierra: Windows, sus servicios y lo que hace funcionar a Moni.
PROTEGIDOS = {
    "system", "idle", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass",
    "svchost", "dwm", "explorer", "fontdrvhost", "sihost", "ctfmon", "conhost", "runtimebroker",
    "searchhost", "searchapp", "startmenuexperiencehost", "shellexperiencehost", "taskhostw",
    "securityhealthservice", "msmpeng", "audiodg", "spoolsv", "memory compression",
    "ollama", "ollama app", "llama-server", "moni", "python", "uv", "node", "cmd",
    "powershell", "msedgewebview2", "claude",
}  # fmt: skip

# Nombres en español o comunes → nombre del proceso.
ALIAS = {
    "bloc de notas": "notepad",
    "calculadora": "calculatorapp",
    "paint": "mspaint",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "visual studio code": "code",
    "vs code": "code",
    "vscode": "code",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "google chrome": "chrome",
    "administrador de tareas": "taskmgr",
}


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", texto).strip()


def _parecido(consulta: str, opciones: list[str]) -> list[str]:
    """Opciones que coinciden con la consulta: exacta, contenida o muy parecida."""
    q = _norm(consulta)
    exactas = [o for o in opciones if _norm(o) == q]
    if exactas:
        return exactas
    contenidas = [o for o in opciones if q and (q in _norm(o) or _norm(o) in q.split())]
    if contenidas:
        return sorted(contenidas, key=len)
    normal = {_norm(o): o for o in opciones}
    return [normal[n] for n in difflib.get_close_matches(q, list(normal), n=3, cutoff=0.7)]


# ---------------------------------------------------------------- abrir


@lru_cache(maxsize=1)
def _apps_inicio() -> dict[str, str]:
    """{nombre visible: AppID} de todo lo que aparece en el menú Inicio."""
    if not ES_WINDOWS:
        return {}
    salida = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            (
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                " Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
            ),
        ],
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        creationflags=_SIN_VENTANA,
    ).stdout  # fmt: skip
    datos = json.loads(salida or "[]")
    if isinstance(datos, dict):
        datos = [datos]
    return {d["Name"]: d["AppID"] for d in datos if d.get("Name") and d.get("AppID")}


@herramienta(Nivel.LIBRE, etiqueta="Abriendo programa")
def abrir_programa(nombre: str) -> str:
    """Abre un programa instalado en la computadora, buscándolo por su nombre como aparece en el menú Inicio.

    Args:
      nombre: Nombre del programa, por ejemplo "Bloc de notas", "Chrome" o "Spotify".
    """
    apps = _apps_inicio()
    candidatos = _parecido(nombre, list(apps))
    if not candidatos:
        raise ValueError(f"No encontré ningún programa llamado '{nombre}' en el menú Inicio.")
    elegido = candidatos[0]
    subprocess.Popen(  # el AppID viene del propio menú Inicio
        ["explorer.exe", f"shell:AppsFolder\\{apps[elegido]}"], creationflags=_SIN_VENTANA
    )
    otros = f" (también encontré: {', '.join(candidatos[1:3])})" if len(candidatos) > 1 else ""
    return f"Abrí {elegido}.{otros}"


# ---------------------------------------------------------------- cerrar


def _procesos_de(nombre: str) -> tuple[str, list[psutil.Process]]:
    """Encuentra los procesos de un programa. Devuelve (nombre del proceso, procesos)."""
    q = ALIAS.get(_norm(nombre), nombre)
    por_nombre: dict[str, list[psutil.Process]] = {}
    for p in psutil.process_iter(["name"]):
        n = (p.info.get("name") or "").removesuffix(".exe").removesuffix(".EXE")
        if n:
            por_nombre.setdefault(n, []).append(p)
    candidatos = _parecido(q, list(por_nombre))
    if not candidatos:
        raise ValueError(f"No veo ningún programa abierto que se llame '{nombre}'.")
    elegido = candidatos[0]
    if _norm(elegido) in PROTEGIDOS:
        raise ValueError(
            f"'{elegido}' es parte de Windows o de la propia Moni; no lo cierro por seguridad."
        )
    return elegido, por_nombre[elegido]


def _resumen_cerrar(nombre: str, forzar: bool = False) -> str:
    elegido, procs = _procesos_de(nombre)
    n = len(procs)
    detalle = f"{n} proceso{'s' if n != 1 else ''}"
    if forzar:
        return f"¿Cierro {elegido} a la fuerza ({detalle})? Se perderá lo que no esté guardado."
    return f"¿Cierro {elegido} ({detalle})? Si tiene algo sin guardar, puede que te pregunte."


@herramienta(Nivel.CONFIRMAR, etiqueta="Cerrando programa", resumen=_resumen_cerrar)
def cerrar_programa(nombre: str, forzar: bool = False) -> str:
    """Cierra un programa que está abierto. Siempre pide confirmación al usuario antes.

    Args:
      nombre: Nombre del programa a cerrar, por ejemplo "Chrome" o "Bloc de notas".
      forzar: Solo si el usuario lo pide explícitamente o si un cierre normal no funcionó.
    """
    elegido, procs = _procesos_de(nombre)
    pids = [p.pid for p in procs]
    if forzar:
        for p in procs:
            try:
                p.kill()
            except psutil.Error:
                pass
    elif ES_WINDOWS:
        for pid in pids:  # sin /F: es como pulsar la X de cada ventana
            subprocess.run(
                ["taskkill", "/PID", str(pid)],
                capture_output=True,
                check=False,
                creationflags=_SIN_VENTANA,
            )
    else:
        for p in procs:
            try:
                p.terminate()
            except psutil.Error:
                pass
    time.sleep(3)
    vivos = [pid for pid in pids if psutil.pid_exists(pid)]
    if not vivos:
        return f"Cerré {elegido}."
    if len(vivos) < len(pids):
        return (
            f"Cerré parte de {elegido}; quedan {len(vivos)} procesos abiertos. Puede estar "
            "esperando que el usuario guarde algo; si quiere, se puede forzar el cierre."
        )
    return (
        f"{elegido} no se cerró. Puede estar mostrando un aviso para guardar cambios o no "
        "tener ventanas; si el usuario quiere, se puede forzar el cierre."
    )
