"""Revisión de los registros de eventos de Windows con Hayabusa (Yamato Security, AGPL-3.0;
reglas Sigma y propias bajo DRL 1.1).

Hayabusa busca en los registros de Windows señales de ataques reales (más de 4000 reglas):
PowerShell sospechoso, servicios creados por malware, borrado de registros, accesos fallidos
en masa, etc.

Dos modos:
  - Normal (sin administrador): Moni exporta con wevtutil los registros que un usuario puede
    leer (Sistema, Aplicación, PowerShell, Defender, Tareas programadas...) de los últimos días
    y Hayabusa los analiza. El registro de Seguridad queda fuera.
  - Completo: Hayabusa analiza todos los registros en vivo. Necesita administrador, así que
    Windows muestra su ventana de permiso (UAC); si el usuario dice que no, no pasa nada.

Hayabusa se descarga la primera vez (paquete "live-response" de la versión fijada, ~10 MB
comprimido, con las reglas codificadas para que el antivirus no dé falsos positivos) en
data/herramientas/hayabusa, y se comprueba su SHA-256 contra el valor fijado aquí para esa
versión (el .exe de Hayabusa no lleva firma Authenticode de Windows).
"""

import hashlib
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import httpx

log = logging.getLogger("moni.eventos")

VERSION = "4.3.1"
# SHA-256 del paquete live-response de cada versión (comprobado al fijar la versión).
HASHES = {"4.3.1": "457185c17b0ce4919b566ee9ecf4ba9f2f78f6b786c2c7367ce5fd921a39cfdf"}
URL = (
    "https://github.com/Yamato-Security/hayabusa/releases/download/"
    "v{v}/hayabusa-{v}-win-x64-live-response.zip"
)

# Registros que un usuario sin administrador puede leer y que suelen tener señales útiles.
CANALES = [
    "System",
    "Application",
    "Windows PowerShell",
    "Microsoft-Windows-PowerShell/Operational",
    "Microsoft-Windows-Windows Defender/Operational",
    "Microsoft-Windows-TaskScheduler/Operational",
    "Microsoft-Windows-Bits-Client/Operational",
    "Microsoft-Windows-Sysmon/Operational",
    "Microsoft-Windows-WMI-Activity/Operational",
]
NIVELES = {"crit": "crítico", "high": "alto", "med": "medio", "low": "bajo", "info": "info"}
_ORDEN = {"crit": 0, "high": 1, "med": 2, "low": 3, "info": 4}
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Hayabusa:
    def __init__(self, carpeta: Path, version: str = VERSION):
        self.carpeta = Path(carpeta)
        self.version = version

    @property
    def exe(self) -> Path:
        return self.carpeta / f"hayabusa-{self.version}-win-x64.exe"

    def instalado(self) -> bool:
        return self.exe.exists() and (self.carpeta / "encoded_rules.yml").exists()

    def instalar(self, cliente: httpx.Client | None = None, sha256: str | None = None) -> None:
        cliente = cliente or httpx.Client(timeout=300, follow_redirects=True)
        r = cliente.get(URL.format(v=self.version))
        r.raise_for_status()
        esperado = sha256 or HASHES.get(self.version)
        real = hashlib.sha256(r.content).hexdigest()
        if not esperado or real != esperado:
            raise ValueError(
                f"El paquete de Hayabusa no coincide con el esperado (SHA-256 {real[:16]}…): "
                "no lo voy a usar."
            )
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "hayabusa.zip"
            zip_path.write_bytes(r.content)
            with zipfile.ZipFile(zip_path) as z:
                for info in z.infolist():
                    nombre = Path(info.filename).name  # nada de rutas dentro del zip
                    if nombre and not info.is_dir():
                        (self.carpeta / nombre).write_bytes(z.read(info))
        if not self.instalado():
            shutil.rmtree(self.carpeta, ignore_errors=True)
            raise ValueError("El paquete de Hayabusa no trae lo esperado.")
        log.info("Hayabusa %s instalado en %s", self.version, self.carpeta)

    # ------------------------------------------------------------ ejecutar

    def argumentos(self, salida: Path, dias: int, origen: Path | None) -> list[str]:
        args = ["dfir-timeline"]
        args += ["-d", str(origen)] if origen else ["-l"]
        return args + [
            "-o", str(salida), "-t", "jsonl",
            "-w", "-q", "-K", "-N", "-C", "-Q",
            "-m", "medium",
            "--time-offset", f"{max(1, int(dias))}d",
        ]  # fmt: skip

    def escanear(self, dias: int = 7, completo: bool = False) -> dict:
        if sys.platform != "win32":
            raise ValueError("La revisión de eventos solo funciona en Windows.")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            salida = tmp / "alertas.jsonl"
            if completo:
                exportados, fallidos = ["todos los registros (con administrador)"], []
                _ejecutar_elevado(self.exe, self.argumentos(salida, dias, None), self.carpeta)
            else:
                origen = tmp / "registros"
                exportados, fallidos = exportar_registros(origen, dias)
                if not exportados:
                    raise ValueError("No pude leer ningún registro de eventos.")
                subprocess.run(
                    [str(self.exe), *self.argumentos(salida, dias, origen)],
                    cwd=self.carpeta,
                    capture_output=True,
                    check=False,
                    timeout=900,
                    creationflags=_SIN_VENTANA,
                )
            if not salida.exists():
                raise ValueError("Hayabusa no generó resultados (¿se canceló?).")
            lineas = salida.read_text("utf-8", errors="ignore").splitlines()
        res = resumir(lineas)
        res["dias_revisados"] = dias
        res["registros_revisados"] = exportados
        if fallidos:
            res["no_revisados"] = fallidos
        if not completo:
            res["nota_modo"] = (
                "Revisión sin administrador: el registro de Seguridad (inicios de sesión) no "
                "se revisó. Para incluirlo, pide la revisión completa (Windows pedirá permiso)."
            )
        return res


def exportar_registros(destino: Path, dias: int) -> tuple[list[str], list[str]]:
    """Exporta con wevtutil los últimos `dias` días de cada canal legible. Devuelve
    (exportados, fallidos)."""
    destino.mkdir(parents=True, exist_ok=True)
    ms = max(1, int(dias)) * 24 * 3600 * 1000
    consulta = f"*[System[TimeCreated[timediff(@SystemTime) <= {ms}]]]"
    ok, fallos = [], []
    for i, canal in enumerate(CANALES):
        archivo = destino / f"{i:02d}.evtx"
        r = subprocess.run(
            ["wevtutil", "epl", canal, str(archivo), f"/q:{consulta}", "/ow:true"],
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
            creationflags=_SIN_VENTANA,
        )
        if r.returncode == 0 and archivo.exists():
            ok.append(canal)
        elif "Sysmon" not in canal:  # Sysmon casi nunca está instalado: no es un fallo
            fallos.append(canal)
    return ok, fallos


def _ejecutar_elevado(exe: Path, args: list[str], cwd: Path) -> None:
    """Lanza Hayabusa como administrador: Windows muestra la ventana de UAC."""

    def q(x) -> str:  # texto entre comillas simples de PowerShell
        return "'" + str(x).replace("'", "''") + "'"

    script = (
        f"$p = Start-Process -FilePath {q(exe)} -ArgumentList {','.join(q(a) for a in args)} "
        f"-WorkingDirectory {q(cwd)} -Verb RunAs -WindowStyle Hidden -Wait -PassThru; "
        "exit $p.ExitCode"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=1800,
        creationflags=_SIN_VENTANA,
    )
    if "cancel" in r.stderr.lower():
        raise ValueError("Se canceló la ventana de permiso de Windows: no revisé nada.")


def resumir(lineas: list[str], maximo: int = 10) -> dict:
    """Agrupa las alertas de Hayabusa por regla, de la más grave a la menos."""
    grupos: dict[str, dict] = {}
    por_nivel: Counter = Counter()
    for linea in lineas:
        try:
            a = json.loads(linea)
        except ValueError:
            continue
        nivel = a.get("Level", "info")
        por_nivel[nivel] += 1
        g = grupos.setdefault(
            a.get("RuleTitle", "?"),
            {
                "alerta": a.get("RuleTitle", "?"),
                "nivel": nivel,
                "veces": 0,
                "registro": a.get("Channel", ""),
                "primera": a.get("Timestamp", ""),
                "ultima": a.get("Timestamp", ""),
                "ejemplo": _ejemplo(a.get("Details")),
            },
        )
        g["veces"] += 1
        ts = a.get("Timestamp", "")
        g["primera"], g["ultima"] = min(g["primera"], ts), max(g["ultima"], ts)
    orden = sorted(grupos.values(), key=lambda g: (_ORDEN.get(g["nivel"], 5), -g["veces"]))
    for g in orden:
        g["nivel"] = NIVELES.get(g["nivel"], g["nivel"])
        g["primera"], g["ultima"] = g["primera"][:16], g["ultima"][:16]
    total = sum(por_nivel.values())
    return {
        "total_alertas": total,
        "por_nivel": {
            NIVELES.get(k, k): v
            for k, v in sorted(por_nivel.items(), key=lambda x: _ORDEN.get(x[0], 5))
        },
        "alertas": orden[:maximo],
        "otras_alertas": max(0, len(orden) - maximo),
        "nota": (
            "Las alertas son señales para revisar, no pruebas de un ataque: muchos programas "
            "legítimos (instaladores, antivirus, herramientas de desarrollo) generan alertas medias."
            if total
            else "Sin alertas de nivel medio o superior en ese periodo."
        ),
    }


def _ejemplo(detalles) -> str:
    if isinstance(detalles, dict):
        partes = [
            f"{k}: {v}"
            for k, v in detalles.items()
            if k in ("Cmdline", "Proc", "Svc", "Path", "User", "ScriptBlock", "Msg", "Tgt", "Src")
        ]
        texto = "; ".join(partes) or "; ".join(f"{k}: {v}" for k, v in list(detalles.items())[:3])
    else:
        texto = str(detalles or "")
    return texto[:240]
