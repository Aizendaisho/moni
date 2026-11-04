"""REA (Reverse Engineer Anything, github.com/morluto/rea, MIT) como integración MCP.

Moni usa REA para explicar qué PUEDE hacer un programa sin ejecutarlo: con qué partes de
Windows trabaja (red, teclado, pantalla, registro, otros procesos...), si está firmado, si
es .NET, Go o Rust y con qué librerías. Solo se permiten herramientas estáticas de REA que
leen el archivo; nunca las que ejecutan, depuran o inyectan código (Frida, GDB, escenarios).

REA necesita Node.js 22 o más nuevo. Se instala la primera vez, con la versión fijada, en
data/herramientas/rea (npm install --prefix), sin tocar la configuración global.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from .mcp_cliente import ServidorMCP

VERSION = "6.8.0"
PERMITIDAS = frozenset(
    {
        "inspect_pe_imports",
        "inspect_pe_certificates",
        "inspect_pe_load_config",
        "inspect_managed_artifact",
        "inspect_go_binary",
        "inspect_desktop_application",
    }
)

# Funciones de Windows -> capacidad, en palabras sencillas.
CAPACIDADES = [
    (r"^(InternetOpen|InternetConnect|HttpSendRequest|WinHttp|URLDownload|WSAStartup|connect|send|recv|getaddrinfo|gethostbyname)", "conectarse a internet o a la red"),
    (r"^(GetAsyncKeyState|GetKeyState|SetWindowsHookEx|RegisterRawInputDevices|GetRawInputData)", "leer el teclado o el ratón"),
    (r"^(BitBlt|GetDC|GetWindowDC|PrintWindow|CreateCompatibleBitmap)", "capturar la pantalla"),
    (r"^(OpenClipboard|GetClipboardData|SetClipboardData)", "leer o cambiar el portapapeles"),
    (r"^(RegSetValue|RegCreateKey|RegDeleteKey|RegDeleteValue)", "modificar el registro de Windows"),
    (r"^(CreateProcess|ShellExecute|WinExec)", "abrir otros programas"),
    (r"^(OpenProcess|WriteProcessMemory|VirtualAllocEx|CreateRemoteThread|NtUnmapViewOfSection|QueueUserAPC)", "meterse en la memoria de otros programas"),
    (r"^(CreateService|StartService|ChangeServiceConfig|OpenSCManager)", "crear o controlar servicios de Windows"),
    (r"^(CryptEncrypt|CryptDecrypt|BCryptEncrypt|BCryptDecrypt|CryptAcquireContext|BCryptGenRandom)", "cifrar o descifrar datos"),
    (r"^(DeleteFile|MoveFile|CopyFile|CreateFile|WriteFile|FindFirstFile)", "leer, crear o borrar archivos"),
    (r"^(AdjustTokenPrivileges|LookupPrivilegeValue|OpenProcessToken)", "pedir más privilegios en el sistema"),
    # IsDebuggerPresent, LoadLibrary o GetProcAddress no cuentan: los usa casi cualquier
    # programa compilado con Visual C++.
    (r"^(CheckRemoteDebuggerPresent|NtSetInformationThread)$", "detectar si lo están analizando (antidepuración)"),
    (r"^(CreateToolhelp32Snapshot|Process32First|EnumProcesses)", "listar los programas abiertos"),
]  # fmt: skip
_SENSIBLES = {
    "leer el teclado o el ratón",
    "capturar la pantalla",
    "meterse en la memoria de otros programas",
    "detectar si lo están analizando (antidepuración)",
}


def node_valido(node: str | None) -> str | None:
    """Ruta de node si es 22 o más nuevo; None si no."""
    if not node:
        return None
    try:
        r = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None
    m = re.match(r"v(\d+)\.", r.stdout.strip())
    return node if m and int(m[1]) >= 22 else None


class REA:
    def __init__(self, carpeta: Path, version: str = VERSION):
        self.carpeta = Path(carpeta)
        self.version = version

    @property
    def script(self) -> Path:
        return self.carpeta / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"

    def instalado(self) -> bool:
        return self.script.exists()

    def instalar(self) -> None:
        if node_valido(shutil.which("node")) is None:
            raise ValueError(
                "Para analizar programas por dentro necesito Node.js 22 o más nuevo "
                "(nodejs.org). No lo encontré o es una versión anterior."
            )
        npm = shutil.which("npm")
        if npm is None:
            raise ValueError("No encontré npm (viene con Node.js).")
        self.carpeta.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [npm, "install", "--prefix", str(self.carpeta), f"rea-agents@{self.version}",
             "--no-audit", "--no-fund", "--omit=dev"],
            capture_output=True, text=True, check=False, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )  # fmt: skip
        if r.returncode != 0 or not self.instalado():
            raise ValueError(f"No se pudo instalar REA: {(r.stderr or r.stdout)[-300:]}")

    def servidor(self) -> ServidorMCP:
        node = node_valido(shutil.which("node"))
        if node is None:
            raise ValueError("Necesito Node.js 22 o más nuevo para usar REA.")
        return ServidorMCP(
            nombre="REA",
            comando=node,
            argumentos=[str(self.script), "mcp"],
            permitidas=PERMITIDAS,
            entorno={**os.environ, "REA_MCP_OUTPUT_SCHEMA_PROFILE": "off"},
        )

    async def explicar(self, ruta: Path) -> dict:
        ruta = Path(ruta).resolve()
        servidor = self.servidor()
        if ruta.is_dir():
            [r] = await servidor.llamar_varias(
                [("inspect_desktop_application", {"path": str(ruta), "detail": "summary"})]
            )
            return {"carpeta": str(ruta), "aplicacion": _recortar(r)}
        p = str(ruta)
        r_imp, r_cert, r_tls, r_net, r_go = await servidor.llamar_varias(
            [
                ("inspect_pe_imports", {"path": p}),
                ("inspect_pe_certificates", {"path": p}),
                ("inspect_pe_load_config", {"path": p}),
                ("inspect_managed_artifact", {"path": p, "detail": "summary"}),
                ("inspect_go_binary", {"path": p, "detail": "summary"}),
            ]
        )
        if not r_imp["ok"]:
            raise ValueError(
                f"REA no pudo leer ese archivo como programa de Windows: {r_imp['error']}"
            )
        return resumir(r_imp["datos"], r_cert, r_tls, r_net, r_go, nombre=ruta.name)


def _norm(datos: dict) -> dict:
    return (datos or {}).get("normalized_result") or {}


def capacidades(funciones: list[str]) -> list[str]:
    salida: list[str] = []
    for patron, capacidad in CAPACIDADES:
        if capacidad not in salida and any(re.match(patron, f) for f in funciones):
            salida.append(capacidad)
    return salida


def resumir(imp: dict, cert: dict, tls: dict, net: dict, go: dict, nombre: str = "") -> dict:
    n = _norm(imp)
    dlls = [d.get("name", "?") for d in n.get("imports") or []]
    dlls += [d.get("name", "?") for d in (n.get("delay_imports") or [])]
    funciones = [
        f.get("name") or ""
        for d in (n.get("imports") or []) + (n.get("delay_imports") or [])
        for f in d.get("functions") or []
    ]
    puede = capacidades(funciones)
    res: dict = {
        "programa": nombre,
        "formato": f"{n.get('format', '?')} de {n.get('bits', '?')} bits",
        "usa_librerias": sorted(set(dlls))[:15],
        "funciones_importadas": len(funciones),
        "puede": puede or ["nada destacable según sus importaciones"],
    }
    sensibles = [c for c in puede if c in _SENSIBLES]
    if sensibles:
        res["a_vigilar"] = sensibles
    if 0 < len(funciones) < 10:
        res["nota_importaciones"] = (
            "Importa muy pocas funciones: puede cargar el resto al vuelo o venir empaquetado, "
            "así que sus capacidades reales pueden ser más."
        )
    c = _norm(cert.get("datos")) if cert.get("ok") else {}
    if c:
        res["tiene_certificado_incrustado"] = bool(c.get("entries"))
    t = _norm(tls.get("datos")) if tls.get("ok") else {}
    if t and t.get("examined_callbacks"):
        res["callbacks_tls"] = t["examined_callbacks"]
        res["nota_tls"] = "Tiene código que corre antes del inicio normal (TLS callbacks)."
    m = (_norm(net.get("datos")) if net.get("ok") else {}).get("summary") or {}
    clase = m.get("classification") or {}
    if clase.get("status") == "managed":
        res["tecnologia"] = (
            f".NET ({clase.get('runtime_family', '?')}, {clase.get('implementation', '?')})"
        )
        res["puede"] = [
            "no se puede saber por sus importaciones: en .NET las capacidades están en el "
            "código administrado y este análisis no lo descompila"
        ]
        res.pop("nota_importaciones", None)
    g = (_norm(go.get("datos")) if go.get("ok") else {}).get("summary") or {}
    if g.get("go_version") or g.get("main_module"):
        res["tecnologia"] = f"Go {g.get('go_version', '')}".strip()
    res["nota"] = (
        "Esto dice lo que el programa PUEDE hacer según su estructura, no lo que hace de verdad "
        "ni si es malicioso. Muchos programas normales usan internet, archivos o el registro."
    )
    res["fuente"] = f"REA {VERSION} (análisis estático, sin ejecutar)"
    return res


def _recortar(r: dict) -> dict:
    if not r.get("ok"):
        return {"error": r.get("error")}
    s = _norm(r.get("datos")).get("summary") or _norm(r.get("datos"))
    texto = str(s)
    return s if len(texto) < 3000 else {"resumen": texto[:3000] + " …"}
