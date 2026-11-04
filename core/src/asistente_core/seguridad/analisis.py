"""Revisión de archivos sin ejecutarlos.

Todo es lectura: nada de lo que se analiza se abre con su programa ni se ejecuta.

Capas (cada una es opcional y, si falla, se anota y se sigue):
  1. Identidad: tamaño, SHA-256, tipo real por los primeros bytes (no por la extensión),
     extensión engañosa (factura.pdf.exe, caracteres invertidos), de dónde se descargó
     (Zone.Identifier de Windows).
  2. Reglas YARA (YARA-X): las de Moni (seguridad/reglas) y las tuyas (data/reglas-yara).
  3. Por tipo: macros de Office (oletools), PDF con JavaScript o acciones automáticas,
     programas .exe (pefile: empaquetado, funciones de inyección), ZIP con ejecutables.
  4. Firma digital (Windows: Get-AuthenticodeSignature).
  5. Windows Defender (MpCmdRun, sin borrar ni mover nada).
  6. En internet, solo el hash (nunca el archivo): CIRCL hashlookup (archivos conocidos)
     y MalwareBazaar si hay clave de abuse.ch.

Veredicto: "peligroso" si hay algún hallazgo de gravedad alta, "sospechoso" si hay de gravedad
media, "sin hallazgos" en otro caso (que no es una garantía).
"""

import hashlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger("moni.seguridad")

REGLAS_MONI = Path(__file__).with_name("reglas")
MAX_LEER = 64 * 1024 * 1024  # bytes que se leen para YARA y PDF

EJECUTABLES = {
    "exe", "scr", "com", "pif", "bat", "cmd", "js", "jse", "vbs", "vbe", "wsf", "wsh", "hta",
    "ps1", "psm1", "lnk", "msi", "msix", "appx", "jar", "dll", "cpl", "reg", "iso", "img",
    "vhd", "vhdx", "chm", "url", "scf", "xll",
}  # fmt: skip
DOCUMENTOS = {"pdf", "doc", "docx", "docm", "xls", "xlsx", "xlsm", "ppt", "pptx", "pptm", "rtf",
              "txt", "jpg", "jpeg", "png", "gif", "mp3", "mp4", "zip", "rar", "7z"}  # fmt: skip

FUNCIONES_PE = {
    "CreateRemoteThread": "crear hilos dentro de otros programas (inyección)",
    "WriteProcessMemory": "escribir en la memoria de otros programas (inyección)",
    "VirtualAllocEx": "reservar memoria dentro de otros programas (inyección)",
    "NtUnmapViewOfSection": "vaciar otro programa para reemplazarlo (process hollowing)",
    "SetWindowsHookExA": "espiar el teclado o el ratón",
    "SetWindowsHookExW": "espiar el teclado o el ratón",
    "GetAsyncKeyState": "leer qué teclas se pulsan",
    "URLDownloadToFileA": "descargar archivos de internet",
    "URLDownloadToFileW": "descargar archivos de internet",
    "CryptEncrypt": "cifrar datos",
    "AdjustTokenPrivileges": "pedir más privilegios en el sistema",
}


@dataclass
class Informe:
    archivo: str
    tamano: str = ""
    tipo: str = ""
    sha256: str = ""
    hallazgos: list[dict] = field(default_factory=list)  # {"gravedad", "detalle"}
    datos: list[str] = field(default_factory=list)  # información neutral o positiva
    no_revisado: list[str] = field(default_factory=list)

    def hallar(self, gravedad: str, detalle: str) -> None:
        if not any(h["detalle"] == detalle for h in self.hallazgos):
            self.hallazgos.append({"gravedad": gravedad, "detalle": detalle})

    @property
    def veredicto(self) -> str:
        g = {h["gravedad"] for h in self.hallazgos}
        if "alta" in g:
            return "peligroso"
        if "media" in g:
            return "sospechoso"
        return "sin hallazgos"

    def como_dict(self) -> dict:
        orden = {"alta": 0, "media": 1, "baja": 2}
        d = {
            "archivo": self.archivo,
            "veredicto": self.veredicto,
            "tipo": self.tipo,
            "tamano": self.tamano,
            "sha256": self.sha256,
            "hallazgos": sorted(self.hallazgos, key=lambda h: orden.get(h["gravedad"], 3)),
            "datos": self.datos,
        }
        if self.no_revisado:
            d["no_revisado"] = self.no_revisado
        if self.veredicto == "sin hallazgos":
            d["nota"] = (
                "Sin hallazgos no es una garantía: el malware nuevo puede pasar desapercibido."
            )
        return d


def _tamano(n: int) -> str:
    for unidad in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unidad == "GB":
            return f"{n:.0f} {unidad}" if unidad == "bytes" else f"{n:.1f} {unidad}"
        n /= 1024
    return str(n)


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def entropia(datos: bytes) -> float:
    if not datos:
        return 0.0
    total = len(datos)
    return -sum(c / total * math.log2(c / total) for c in Counter(datos).values())


# ---------------------------------------------------------------- tipo real


def tipo_real(cabecera: bytes, ruta: Path) -> tuple[str, str]:
    """(clave, descripción) según los primeros bytes."""
    if cabecera[:2] == b"MZ":
        return "pe", "programa de Windows (.exe/.dll)"
    if b"%PDF" in cabecera[:1024]:
        return "pdf", "documento PDF"
    if cabecera[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(ruta) as z:
                nombres = z.namelist()
        except (zipfile.BadZipFile, OSError):
            return "zip", "archivo comprimido ZIP (dañado o raro)"
        if any(n.startswith("word/") for n in nombres):
            return "ooxml", "documento de Word"
        if any(n.startswith("xl/") for n in nombres):
            return "ooxml", "hoja de Excel"
        if any(n.startswith("ppt/") for n in nombres):
            return "ooxml", "presentación de PowerPoint"
        if "AndroidManifest.xml" in nombres:
            return "zip", "aplicación de Android (APK)"
        if "META-INF/MANIFEST.MF" in nombres:
            return "zip", "programa Java (JAR)"
        return "zip", "archivo comprimido ZIP"
    if cabecera[:4] == b"\xd0\xcf\x11\xe0":
        return "ole", "documento de Office antiguo (.doc/.xls/.ppt) o instalador .msi"
    if cabecera[:4] == b"{\\rt":
        return "rtf", "documento RTF"
    if cabecera[:4] == b"\x7fELF":
        return "elf", "programa de Linux"
    if cabecera[:4] == b"Rar!":
        return "rar", "archivo comprimido RAR"
    if cabecera[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z", "archivo comprimido 7z"
    if cabecera[:4] == b"L\x00\x00\x00":
        return "lnk", "acceso directo de Windows (.lnk)"
    if cabecera[32769:32774] == b"CD001" or cabecera[:5] == b"CD001":
        return "iso", "imagen de disco ISO"
    if cabecera[:3] == b"\xff\xd8\xff":
        return "img", "imagen JPEG"
    if cabecera[:8] == b"\x89PNG\r\n\x1a\n":
        return "img", "imagen PNG"
    if cabecera[:4] in (b"GIF8",):
        return "img", "imagen GIF"
    muestra = cabecera[:4096]
    if muestra and sum(32 <= b < 127 or b in (9, 10, 13) for b in muestra) / len(muestra) > 0.9:
        return "texto", "archivo de texto o script"
    return "otro", "archivo de datos"


def revisar_nombre(ruta: Path, clave: str, inf: Informe) -> None:
    nombre = ruta.name
    if any(c in nombre for c in "\u202e\u202d\u200e\u200f"):
        inf.hallar(
            "alta",
            "El nombre tiene caracteres invisibles que invierten el texto para disfrazar la "
            "extensión real",
        )
    partes = nombre.lower().split(".")
    ext = partes[-1] if len(partes) > 1 else ""
    if len(partes) >= 3 and partes[-2] in DOCUMENTOS and ext in EJECUTABLES:
        inf.hallar(
            "alta",
            f"Doble extensión: parece .{partes[-2]} pero en realidad es .{ext} (se ejecuta)",
        )
    if re.search(r"\s{5,}\.\w+$", nombre):
        inf.hallar("media", "El nombre tiene muchos espacios para esconder la extensión real")
    if clave == "pe" and ext in DOCUMENTOS:
        inf.hallar("alta", f"Dice ser .{ext} pero en realidad es un programa de Windows")
    elif ext in EJECUTABLES:
        inf.datos.append(f"Es un tipo de archivo que se ejecuta al abrirlo (.{ext})")


def origen_descarga(ruta: Path) -> str | None:
    """De dónde se descargó (Windows guarda la URL en el flujo Zone.Identifier)."""
    if sys.platform != "win32":
        return None
    try:
        texto = Path(str(ruta) + ":Zone.Identifier").read_text(errors="ignore")
    except OSError:
        return None
    m = re.search(r"^HostUrl=(.+)$", texto, re.MULTILINE) or re.search(
        r"^ReferrerUrl=(.+)$", texto, re.MULTILINE
    )
    if m:
        return m[1].strip()
    return "internet (sin URL guardada)" if "ZoneId=3" in texto else None


# ---------------------------------------------------------------- YARA


class Reglas:
    """Reglas YARA compiladas; se recompilan si cambia algún archivo."""

    def __init__(self, carpetas: list[Path]):
        self.carpetas = carpetas
        self._firma: tuple = ()
        self._reglas = None
        self.errores: list[str] = []

    def _archivos(self) -> list[Path]:
        archivos: list[Path] = []
        for c in self.carpetas:
            if c.is_dir():
                archivos += sorted(p for p in c.rglob("*") if p.suffix.lower() in (".yar", ".yara"))
        return archivos

    def compiladas(self):
        import yara_x

        archivos = self._archivos()
        firma = tuple((str(p), p.stat().st_mtime) for p in archivos)
        if firma == self._firma and self._reglas is not None:
            return self._reglas
        self.errores = []
        compilador = yara_x.Compiler()
        for i, p in enumerate(archivos):
            # cada archivo en su espacio de nombres: así reglas con el mismo nombre no chocan
            compilador.new_namespace(f"r{i}")
            try:
                compilador.add_source(p.read_text(encoding="utf-8", errors="ignore"))
            except yara_x.CompileError as exc:
                self.errores.append(f"{p.name}: {str(exc).splitlines()[0]}")
                log.warning("Regla YARA con error, se omite: %s: %s", p, exc)
        self._reglas = compilador.build()
        self._firma = firma
        return self._reglas

    def escanear(self, datos: bytes) -> list[dict]:
        import yara_x

        scanner = yara_x.Scanner(self.compiladas())
        scanner.set_timeout(20)
        res = scanner.scan(datos)
        aciertos = []
        for r in res.matching_rules:
            meta = dict(r.metadata)
            aciertos.append(
                {
                    "regla": r.identifier,
                    "gravedad": str(meta.get("gravedad") or meta.get("severity") or "media"),
                    "detalle": str(
                        meta.get("descripcion") or meta.get("description") or r.identifier
                    ),
                }
            )
        return aciertos


def _gravedad_externa(g: str) -> str:
    g = g.lower()
    if g in ("alta", "high", "critical", "critica", "crítica"):
        return "alta"
    if g in ("baja", "low", "info", "informational"):
        return "baja"
    return "media"


# ---------------------------------------------------------------- por tipo


def revisar_office(ruta: Path, inf: Informe) -> None:
    from oletools.olevba import VBA_Parser

    vp = VBA_Parser(str(ruta))
    try:
        if not (vp.detect_vba_macros() or vp.detect_xlm_macros()):
            inf.datos.append("No tiene macros")
            return
        tipos: dict[str, list[str]] = {}
        for tipo, palabra, _desc in vp.analyze_macros():
            tipos.setdefault(tipo, []).append(palabra)
    finally:
        vp.close()
    auto = tipos.get("AutoExec", [])
    sosp = tipos.get("Suspicious", [])
    iocs = tipos.get("IOC", [])
    peligrosas = {
        "shell", "wscript.shell", "run", "createobject", "powershell", "urldownloadtofile",
        "xmlhttp", "adodb.stream", "savetofile", "exec", "callbyname", "environ", "kill",
        "createprocess",
    }  # fmt: skip
    graves = [s for s in sosp if s.lower() in peligrosas]
    if auto and graves:
        inf.hallar(
            "alta",
            "Tiene macros que se ejecutan solas al abrir el documento y que pueden lanzar "
            f"programas o descargar cosas ({', '.join(sorted(set(graves))[:5])})",
        )
    elif auto and sosp:
        inf.hallar(
            "media",
            "Tiene macros que se ejecutan solas al abrir y usan funciones sospechosas "
            f"({', '.join(sorted(set(sosp))[:5])})",
        )
    elif auto:
        inf.hallar("media", "Tiene macros que se ejecutan solas al abrir el documento")
    else:
        inf.hallar("baja", "Tiene macros (no se ejecutan solas al abrir)")
    if iocs:
        inf.hallar("media", f"Las macros contienen direcciones o rutas: {', '.join(iocs[:3])}")


def revisar_plantilla_remota(ruta: Path, inf: Informe) -> None:
    """Documentos de Office que cargan una plantilla o un objeto desde internet al abrirse."""
    try:
        with zipfile.ZipFile(ruta) as z:
            for n in z.namelist():
                if not n.endswith(".rels"):
                    continue
                xml = z.read(n).decode("utf-8", errors="ignore")
                for m in re.finditer(r'Target="(https?://[^"]+)"[^>]*TargetMode="External"', xml):
                    destino = m[1]
                    if "attachedTemplate" in xml or "oleObject" in xml or "frame" in n:
                        inf.hallar(
                            "alta",
                            f"Al abrirse descarga una plantilla u objeto de internet ({destino})",
                        )
                    else:
                        inf.datos.append(f"Tiene enlaces externos: {destino}")
    except (zipfile.BadZipFile, OSError, KeyError):
        pass


_PDF_CLAVES = [
    "JavaScript", "JS", "OpenAction", "AA", "Launch", "EmbeddedFile", "RichMedia", "XFA",
    "AcroForm", "URI", "SubmitForm", "ObjStm", "Encrypt",
]  # fmt: skip


def contar_pdf(datos: bytes) -> dict[str, int]:
    """Como pdfid: cuenta palabras clave del PDF, deshaciendo nombres ofuscados (/J#61vaScript)."""

    def normal(nombre: bytes) -> str:
        return re.sub(rb"#([0-9A-Fa-f]{2})", lambda h: bytes([int(h[1], 16)]), nombre).decode(
            "latin-1"
        )[1:]

    vistos = Counter(normal(n) for n in re.findall(rb"/[A-Za-z0-9#]+", datos))
    return {k: vistos.get(k, 0) for k in _PDF_CLAVES}


def revisar_pdf(datos: bytes, inf: Informe) -> None:
    c = contar_pdf(datos)
    js = c["JavaScript"] + c["JS"]
    auto = c["OpenAction"] + c["AA"]
    if c["Launch"]:
        inf.hallar("alta", "El PDF intenta abrir un programa o un archivo (acción /Launch)")
    if js and auto:
        inf.hallar("alta", "El PDF tiene JavaScript que se ejecuta solo al abrirlo")
    elif js:
        inf.hallar("media", "El PDF tiene JavaScript")
    elif auto:
        inf.datos.append("El PDF tiene acciones automáticas al abrirse (sin JavaScript)")
    if c["EmbeddedFile"]:
        inf.hallar("media", "El PDF trae archivos adjuntos dentro")
    if c["RichMedia"] or c["XFA"]:
        inf.hallar("baja", "El PDF tiene contenido interactivo (Flash o formularios XFA)")
    if c["SubmitForm"]:
        inf.datos.append("El PDF tiene un formulario que envía datos a internet")
    if c["URI"]:
        inf.datos.append(f"El PDF tiene {c['URI']} enlace(s)")
    if c["ObjStm"] and not js and not c["Launch"]:
        inf.datos.append("Tiene partes comprimidas que no se pudieron inspeccionar a fondo")
    if c["Encrypt"]:
        inf.no_revisado.append("El PDF está cifrado: parte del contenido no se pudo revisar")


def revisar_pe(ruta: Path, inf: Informe) -> None:
    import pefile

    pe = pefile.PE(str(ruta), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_SECURITY"],
            ]
        )
        es_dll = pe.is_dll()
        bits = 64 if pe.OPTIONAL_HEADER.Magic == 0x20B else 32
        inf.tipo = f"{'biblioteca .dll' if es_dll else 'programa .exe'} de Windows ({bits} bits)"
        secciones = []
        for s in pe.sections:
            nombre = s.Name.rstrip(b"\x00").decode("latin-1", errors="ignore")
            secciones.append(nombre)
            # Solo el código cuenta: los recursos (.rsrc) y los datos de los instaladores
            # legítimos suelen ir comprimidos.
            ejecutable = bool(s.Characteristics & 0x20000000)  # IMAGE_SCN_MEM_EXECUTE
            if ejecutable and s.SizeOfRawData > 4096 and s.get_entropy() > 7.2:
                inf.hallar(
                    "baja",
                    f"El código ({nombre or 'sección sin nombre'}) está comprimido o cifrado: "
                    "puede estar empaquetado para esconder lo que hace",
                )
        if any(n.upper().startswith("UPX") for n in secciones):
            inf.hallar("baja", "Está comprimido con UPX (común en malware, pero también legítimo)")
        importadas = []
        for entrada in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            for imp in entrada.imports:
                if imp.name:
                    importadas.append(imp.name.decode("latin-1", errors="ignore"))
        usos = sorted({FUNCIONES_PE[f] for f in importadas if f in FUNCIONES_PE})
        inyeccion = {"CreateRemoteThread", "WriteProcessMemory", "VirtualAllocEx"} <= set(
            importadas
        )
        if inyeccion:
            inf.hallar("media", "Tiene todo lo necesario para inyectar código en otros programas")
        if usos:
            inf.datos.append("Puede: " + "; ".join(usos))
        if 0 < len(importadas) < 8:
            inf.hallar("baja", "Importa muy pocas funciones: suele indicar que está empaquetado")
        seg = pe.OPTIONAL_HEADER.DATA_DIRECTORY[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_SECURITY"]
        ]
        if not seg.Size:
            inf.datos.append("No tiene firma digital")
    finally:
        pe.close()


def revisar_zip(ruta: Path, inf: Informe) -> None:
    try:
        with zipfile.ZipFile(ruta) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError):
        inf.no_revisado.append("No se pudo abrir el ZIP")
        return
    cifrados = [i for i in infos if i.flag_bits & 0x1]
    ejecutables = [
        i.filename for i in infos if i.filename.lower().rsplit(".", 1)[-1] in EJECUTABLES
    ]
    if cifrados:
        inf.hallar(
            "media" if ejecutables else "baja",
            "El ZIP tiene contraseña: los antivirus no pueden revisar lo que hay dentro",
        )
    if ejecutables:
        inf.hallar(
            "media",
            f"El ZIP trae archivos que se ejecutan: {', '.join(ejecutables[:5])}",
        )
    inf.datos.append(f"Contiene {len(infos)} archivo(s)")


# ---------------------------------------------------------------- Windows


def _powershell(script: str, env: dict[str, str], timeout: int = 30) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
        env={**os.environ, **env},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return r.stdout.strip()


def firma(ruta: Path) -> dict | None:
    """Estado de la firma digital (Valid, NotSigned, HashMismatch...) y quién firmó."""
    if sys.platform != "win32":
        return None
    # La ruta va por variable de entorno, nunca pegada en el comando.
    salida = _powershell(
        "$s = Get-AuthenticodeSignature -LiteralPath $env:MONI_RUTA; "
        "[pscustomobject]@{estado=$s.Status.ToString(); "
        "firmante=$(if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '' })} "
        "| ConvertTo-Json -Compress",
        {"MONI_RUTA": str(ruta)},
    )
    return json.loads(salida) if salida else None


def anotar_firma(f: dict, inf: Informe) -> None:
    estado = f.get("estado", "")
    quien = re.search(r"CN=([^,]+)", f.get("firmante", ""))
    quien = quien[1].strip('"') if quien else ""
    if estado == "Valid":
        inf.datos.append(f"Firma digital válida de {quien or 'un firmante desconocido'}")
        inf.datos[:] = [d for d in inf.datos if d != "No tiene firma digital"]
    elif estado == "HashMismatch":
        inf.hallar(
            "alta", "La firma digital no coincide: el archivo fue modificado después de firmarse"
        )
    elif estado in ("NotTrusted", "UnknownError"):
        inf.hallar("media", f"La firma digital no es de confianza ({quien or estado})")


def defender(ruta: Path) -> dict | None:
    """Analiza con Windows Defender sin que borre ni mueva nada (-DisableRemediation)."""
    if sys.platform != "win32":
        return None
    exe = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Windows Defender"
        / "MpCmdRun.exe"
    )
    if not exe.exists():
        return {"error": "Windows Defender no está disponible"}
    r = subprocess.run(
        [str(exe), "-Scan", "-ScanType", "3", "-File", str(ruta), "-DisableRemediation"],
        capture_output=True,
        check=False,
        text=True,
        timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    amenazas = re.findall(r"Threat\s*:\s*(.+)", r.stdout)
    if r.returncode == 2 or amenazas:
        return {"amenazas": amenazas or ["(sin nombre)"]}
    if r.returncode == 0:
        return {"amenazas": []}
    return {"error": (r.stdout or r.stderr).strip().splitlines()[-1:] or [f"código {r.returncode}"]}


# ---------------------------------------------------------------- internet (solo el hash)


def consultar_hash(h: str, clave_abusech: str = "", cliente: httpx.Client | None = None) -> dict:
    cliente = cliente or httpx.Client(timeout=10)
    res: dict = {}
    try:
        r = cliente.get(f"https://hashlookup.circl.lu/lookup/sha256/{h}")
        if r.status_code == 200:
            datos = r.json()
            res["conocido"] = datos.get("FileName") or datos.get("ProductCode", {}).get(
                "ProductName", "sí"
            )
        elif r.status_code == 404:
            res["conocido"] = None
    except Exception as exc:  # noqa: BLE001
        res["error_circl"] = str(exc)
    if clave_abusech:
        try:
            r = cliente.post(
                "https://mb-api.abuse.ch/api/v1/",
                data={"query": "get_info", "hash": h},
                headers={"Auth-Key": clave_abusech},
            )
            datos = r.json()
            if datos.get("query_status") == "ok":
                info = (datos.get("data") or [{}])[0]
                res["malware"] = info.get("signature") or "malware conocido"
            else:
                res["malware"] = None
        except Exception as exc:  # noqa: BLE001
            res["error_malwarebazaar"] = str(exc)
    return res


# ---------------------------------------------------------------- orquestación


def analizar(
    ruta: Path,
    reglas: Reglas,
    *,
    usar_defender: bool = True,
    consultar_internet: bool = True,
    clave_abusech: str = "",
    cliente: httpx.Client | None = None,
) -> Informe:
    ruta = Path(ruta)
    inf = Informe(archivo=str(ruta))
    total = ruta.stat().st_size
    inf.tamano = _tamano(total)
    with ruta.open("rb") as f:
        datos = f.read(MAX_LEER)
    if total > MAX_LEER:
        inf.no_revisado.append(f"Solo se revisaron los primeros {_tamano(MAX_LEER)} con YARA")
    inf.sha256 = sha256(ruta)
    clave, inf.tipo = tipo_real(datos[:40000], ruta)
    revisar_nombre(ruta, clave, inf)
    if origen := origen_descarga(ruta):
        inf.datos.append(f"Descargado de: {origen}")

    def paso(nombre: str, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falló %s en %s: %s", nombre, ruta, exc)
            inf.no_revisado.append(f"{nombre}: {exc}")

    def yara() -> None:
        for a in reglas.escanear(datos):
            if a["regla"] == "Moni_Prueba_EICAR":
                inf.hallar("alta", a["detalle"])
            else:
                inf.hallar(_gravedad_externa(a["gravedad"]), a["detalle"])

    paso("reglas YARA", yara)
    if clave in ("ole", "ooxml"):
        paso("macros de Office", revisar_office, ruta, inf)
    if clave == "ooxml":
        paso("enlaces externos", revisar_plantilla_remota, ruta, inf)
    if clave == "pdf":
        paso("PDF", revisar_pdf, datos, inf)
    if clave == "pe":
        paso("programa", revisar_pe, ruta, inf)
    if clave == "zip":
        paso("ZIP", revisar_zip, ruta, inf)
    if clave in ("rar", "7z", "iso"):
        inf.no_revisado.append("No se revisó por dentro (solo ZIP por ahora)")

    if clave == "pe" or ruta.suffix.lower() in (".msi", ".ps1", ".dll", ".sys", ".cab"):

        def revisar_firma() -> None:
            f = firma(ruta)
            if f:
                anotar_firma(f, inf)

        paso("firma digital", revisar_firma)

    if usar_defender:

        def con_defender() -> None:
            d = defender(ruta)
            if d is None:
                return
            if d.get("amenazas"):
                inf.hallar("alta", f"Windows Defender lo detecta como: {', '.join(d['amenazas'])}")
            elif "amenazas" in d:
                inf.datos.append("Windows Defender no encontró amenazas")
            else:
                inf.no_revisado.append(f"Windows Defender: {d.get('error')}")

        paso("Windows Defender", con_defender)

    if consultar_internet:

        def en_internet() -> None:
            r = consultar_hash(inf.sha256, clave_abusech, cliente)
            if r.get("malware"):
                inf.hallar(
                    "alta", f"MalwareBazaar lo tiene registrado como malware: {r['malware']}"
                )
            elif "malware" in r:
                inf.datos.append("No aparece en MalwareBazaar")
            if r.get("conocido"):
                inf.datos.append(
                    "Aparece en la base de archivos conocidos de CIRCL/NSRL "
                    f"({r['conocido']}): suele ser software legítimo"
                )

        paso("consulta del hash en internet", en_internet)
    return inf
