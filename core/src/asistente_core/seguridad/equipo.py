"""Chequeo de seguridad de la PC (solo lectura, sin permisos de administrador).

`recoger()` junta los datos de Windows (PowerShell, registro y psutil) y `evaluar()` decide
qué está bien y qué merece atención. Están separados para poder probar la evaluación sin
Windows.

Revisa:
  - Windows Defender: activo, protección en tiempo real, antigüedad de las firmas.
  - Firewall: activado en cada perfil.
  - Actualizaciones: fecha de la última instalada.
  - Control de cuentas (UAC) activado.
  - Programas que arrancan solos (claves Run del registro y carpetas de Inicio).
  - Tareas programadas que no son de Microsoft.
  - Puertos abiertos a la red.
  - Programas abiertos que corren desde carpetas raras (Temp, Descargas, Public).
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psutil

log = logging.getLogger("moni.equipo")

# Carpetas donde un programa legítimo casi nunca vive (pero el malware sí).
_RARAS = [
    r"\\appdata\\local\\temp\\",
    r"\\windows\\temp\\",
    r"\\downloads\\",
    r"\\users\\public\\",
    r"\\\$recycle\.bin\\",
    r"\\programdata\\[^\\]+\.exe$",  # .exe suelto en ProgramData
    r"\\appdata\\roaming\\[^\\]+\.exe$",  # .exe suelto en Roaming
]
_COMANDOS_RAROS = [
    (r"powershell[^\n]*\s-(e|en|enc|encodedcommand)\s", "PowerShell con comando codificado"),
    (r"powershell[^\n]*-w(indowstyle)?\s+h(idden)?", "PowerShell oculto"),
    (r"mshta(\.exe)?\s", "mshta (ejecuta código HTML/script)"),
    (r"wscript(\.exe)?\s|cscript(\.exe)?\s", "un script de Windows (.vbs/.js)"),
    (r"regsvr32[^\n]*/i:", "regsvr32 cargando código remoto"),
    (r"rundll32[^\n]*javascript", "rundll32 con JavaScript"),
    (r"certutil[^\n]*-urlcache", "certutil descargando archivos"),
    (r"https?://", "una dirección de internet"),
]
_PUERTOS = {
    21: "FTP",
    23: "Telnet (sin cifrar)",
    3389: "Escritorio remoto",
    5900: "VNC (control remoto)",
    5938: "TeamViewer",
    7070: "AnyDesk",
    22: "SSH",
    445: "compartir archivos (SMB)",
}


def es_ruta_rara(ruta: str) -> bool:
    r = ruta.lower()
    return any(re.search(p, r) for p in _RARAS)


def comando_raro(comando: str) -> str | None:
    c = comando.lower()
    for patron, nombre in _COMANDOS_RAROS:
        if re.search(patron, c):
            return nombre
    if es_ruta_rara(c):
        return "un programa en una carpeta temporal o de descargas"
    return None


# ---------------------------------------------------------------- recoger (Windows)

_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$r = @{}
$mp = Get-MpComputerStatus
if ($mp) {
  $r.defender = @{
    activo = [bool]$mp.AntivirusEnabled
    tiempo_real = [bool]$mp.RealTimeProtectionEnabled
    dias_firmas = [int]$mp.AntivirusSignatureAge
    dias_escaneo = [int]$mp.QuickScanAge
  }
}
$r.firewall = @(Get-NetFirewallProfile | ForEach-Object { @{ perfil = $_.Name; activo = [bool]$_.Enabled } })
$hf = Get-HotFix | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending | Select-Object -First 1
if ($hf) { $r.ultima_actualizacion = $hf.InstalledOn.ToString('yyyy-MM-dd') }
$uac = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
$r.uac = [int]$uac.EnableLUA
$r.tareas = @(Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' -and $_.TaskPath -notlike '\Microsoft\*' } | ForEach-Object {
  $t = $_
  @{
    nombre = $t.TaskName
    carpeta = $t.TaskPath
    autor = [string]$t.Author
    accion = (($t.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)".Trim() }) -join ' ; ')
  }
})
$r | ConvertTo-Json -Depth 4 -Compress
"""


def _powershell() -> dict:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
        capture_output=True,
        check=False,
        text=True,
        timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return json.loads(r.stdout or "{}")


def _inicio_registro() -> list[dict]:
    import winreg

    claves = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "usuario"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "todos"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
            "todos",
        ),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "usuario"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "todos"),
    ]
    salida = []
    for raiz, ruta, quien in claves:
        try:
            with winreg.OpenKey(raiz, ruta) as k:
                i = 0
                while True:
                    try:
                        nombre, valor, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    salida.append({"nombre": nombre, "comando": str(valor), "para": quien})
                    i += 1
        except OSError:
            continue
    return salida


def _inicio_carpetas() -> list[dict]:
    carpetas = [
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        / r"Microsoft\Windows\Start Menu\Programs\StartUp",
    ]
    salida = []
    for c in carpetas:
        if c.is_dir():
            for p in c.iterdir():
                if p.name.lower() != "desktop.ini":
                    salida.append({"nombre": p.name, "comando": str(p), "para": "carpeta Inicio"})
    return salida


def _puertos() -> list[dict]:
    vistos: dict[tuple, dict] = {}
    for c in psutil.net_connections(kind="inet"):
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        ip = c.laddr.ip
        if ip.startswith("127.") or ip == "::1":
            continue  # solo esta PC: no es accesible desde la red
        try:
            nombre = psutil.Process(c.pid).name() if c.pid else "?"
        except psutil.Error:
            nombre = "?"
        vistos[(c.laddr.port, nombre)] = {"puerto": c.laddr.port, "programa": nombre}
    return sorted(vistos.values(), key=lambda x: x["puerto"])


def _procesos_raros() -> list[dict]:
    salida = []
    for p in psutil.process_iter(["name", "exe"]):
        exe = p.info.get("exe") or ""
        if exe and es_ruta_rara(exe):
            salida.append({"programa": p.info.get("name") or "?", "ruta": exe})
    return salida


def recoger() -> dict:
    if sys.platform != "win32":
        raise ValueError("El chequeo de seguridad solo funciona en Windows.")
    datos: dict = {"errores": []}
    pasos = {
        "windows": _powershell,
        "inicio_registro": _inicio_registro,
        "inicio_carpetas": _inicio_carpetas,
        "puertos": _puertos,
        "procesos_raros": _procesos_raros,
    }
    for nombre, fn in pasos.items():
        try:
            datos[nombre] = fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("Chequeo: falló %s: %s", nombre, exc)
            datos["errores"].append(f"{nombre}: {exc}")
    return datos


# ---------------------------------------------------------------- evaluar (puro)


def evaluar(datos: dict, hoy: datetime | None = None) -> dict:
    """Convierte los datos en puntos: riesgo / atencion / bien."""
    hoy = hoy or datetime.now()
    riesgo: list[str] = []
    atencion: list[str] = []
    bien: list[str] = []
    w = datos.get("windows") or {}

    d = w.get("defender")
    if d is None:
        atencion.append(
            "No pude leer el estado de Windows Defender (puede que uses otro antivirus)."
        )
    elif not d.get("activo"):
        riesgo.append("Windows Defender está desactivado y no veo otro antivirus.")
    elif not d.get("tiempo_real"):
        riesgo.append("La protección en tiempo real de Windows Defender está apagada.")
    else:
        bien.append("Windows Defender está activo con protección en tiempo real.")
        if d.get("dias_firmas", 0) > 7:
            atencion.append(
                f"Las firmas de Defender tienen {d['dias_firmas']} días: conviene actualizarlas."
            )

    perfiles = w.get("firewall") or []
    if isinstance(perfiles, dict):
        perfiles = [perfiles]
    apagados = [p["perfil"] for p in perfiles if not p.get("activo")]
    if apagados:
        riesgo.append(f"El firewall está apagado en: {', '.join(apagados)}.")
    elif perfiles:
        bien.append("El firewall está activado.")

    fecha = w.get("ultima_actualizacion")
    if fecha:
        dias = (hoy - datetime.strptime(fecha, "%Y-%m-%d")).days
        if dias > 60:
            riesgo.append(f"La última actualización de Windows fue hace {dias} días.")
        elif dias > 35:
            atencion.append(f"La última actualización de Windows fue hace {dias} días.")
        else:
            bien.append(f"Windows se actualizó hace {dias} días.")

    if w.get("uac") == 0:
        riesgo.append("El Control de cuentas de usuario (UAC) está desactivado.")
    elif w.get("uac") == 1:
        bien.append("El Control de cuentas de usuario (UAC) está activado.")

    inicio = (datos.get("inicio_registro") or []) + (datos.get("inicio_carpetas") or [])
    raros_inicio = []
    for e in inicio:
        motivo = comando_raro(e["comando"])
        if motivo:
            raros_inicio.append(f"{e['nombre']} (usa {motivo})")
    if raros_inicio:
        atencion.append("Arrancan solos y se ven raros: " + "; ".join(raros_inicio[:6]))
    nombres_inicio = sorted({e["nombre"] for e in inicio})

    tareas = w.get("tareas") or []
    if isinstance(tareas, dict):
        tareas = [tareas]
    raras_tareas = []
    for t in tareas:
        motivo = comando_raro(t.get("accion", ""))
        if motivo:
            raras_tareas.append(f"{t['nombre']} (usa {motivo})")
    if raras_tareas:
        atencion.append("Tareas programadas que se ven raras: " + "; ".join(raras_tareas[:6]))

    expuestos = [
        f"{p['puerto']} {_PUERTOS[p['puerto']]} ({p['programa']})"
        for p in datos.get("puertos") or []
        if p["puerto"] in _PUERTOS and p["puerto"] != 445
    ]
    if expuestos:
        atencion.append("Hay accesos remotos abiertos a la red: " + "; ".join(expuestos))

    procs = datos.get("procesos_raros") or []
    if procs:
        lista = "; ".join(f"{p['programa']} desde {p['ruta']}" for p in procs[:5])
        atencion.append(f"Programas abiertos desde carpetas poco habituales: {lista}")

    return {
        "riesgo": riesgo,
        "atencion": atencion,
        "bien": bien,
        "arrancan_solos": nombres_inicio,
        "tareas_programadas_no_microsoft": len(tareas),
        "puertos_abiertos_a_la_red": len(datos.get("puertos") or []),
        "no_revisado": datos.get("errores") or [],
        "nota": "Revisión de solo lectura: no se cambió nada.",
    }
