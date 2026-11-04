"""Conocimiento de seguridad de Moni: MITRE ATT&CK y LOLBAS, consultables sin internet.

- MITRE ATT&CK (Enterprise): técnicas que usan los atacantes, con su táctica, cómo mitigarlas
  y cómo detectarlas, más el malware y herramientas conocidas (Emotet, Mimikatz...).
  Fuente: github.com/mitre-attack/attack-stix-data. © The MITRE Corporation; uso libre con
  atribución según sus términos de uso.
- LOLBAS: programas legítimos de Windows que los atacantes abusan (mshta, certutil...).
  Fuente: lolbas-project.github.io (GPL-3.0). Moni lo descarga en tu PC; no se incluye en el
  repositorio.

Se descargan una vez (unos 55 MB), se compactan a data/seguridad/*.json (~2 MB) y se
actualizan solos cada 30 días. Moni solo guarda lo que sirve para explicar y defender: de
LOLBAS no se guardan los comandos de abuso, solo qué permite hacer cada programa.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx

log = logging.getLogger("moni.saber")

URL_ATTACK = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    "enterprise-attack/enterprise-attack.json"
)
URL_LOLBAS = "https://lolbas-project.github.io/api/lolbas.json"
VIGENCIA = timedelta(days=30)

TACTICAS = {
    "reconnaissance": "reconocimiento",
    "resource-development": "preparación de recursos",
    "initial-access": "acceso inicial",
    "execution": "ejecución",
    "persistence": "persistencia",
    "privilege-escalation": "escalada de privilegios",
    "defense-evasion": "evasión de defensas",
    "stealth": "sigilo",
    "credential-access": "robo de credenciales",
    "discovery": "descubrimiento",
    "lateral-movement": "movimiento lateral",
    "collection": "recolección de datos",
    "command-and-control": "comando y control",
    "exfiltration": "exfiltración",
    "impact": "impacto",
}

# Términos frecuentes en español -> inglés (ATT&CK está en inglés).
SINONIMOS = {
    "contraseña": "credential password",
    "contraseñas": "credential password",
    "credenciales": "credential",
    "suplantación": "phishing spoofing",
    "correo": "phishing email",
    "secuestro": "ransomware encrypted impact",
    "cifrado": "encrypted encryption",
    "cifra": "encrypted",
    "rescate": "ransom encrypted impact",
    "teclado": "keylogging input capture",
    "teclas": "keylogging input capture",
    "captura": "capture screen",
    "pantalla": "screen capture",
    "inicio": "startup autostart boot logon",
    "arranque": "boot autostart logon",
    "registro": "registry",
    "tareas": "scheduled task",
    "programada": "scheduled task",
    "macro": "macro office",
    "macros": "macro office",
    "descarga": "download ingress transfer",
    "remoto": "remote",
    "escritorio": "desktop",
    "navegador": "browser",
    "cookies": "cookies session",
    "minería": "resource hijacking mining",
    "criptomonedas": "cryptocurrency mining",
    "puerta": "backdoor",
    "trasera": "backdoor",
    "inyección": "injection",
    "proceso": "process",
    "procesos": "process",
    "ocultar": "hide obfuscated masquerading",
    "disfrazar": "masquerading",
    "antivirus": "impair defenses disable security tools",
    "desactivar": "disable impair",
    "usb": "removable media replication",
    "memoria": "memory",
    "red": "network",
}

# Conceptos que la gente pregunta con su nombre común -> técnica de ATT&CK que lo explica.
CONCEPTOS = {
    "ransomware": "T1486",
    "secuestro de archivos": "T1486",
    "keylogger": "T1056.001",
    "registrador de teclas": "T1056.001",
    "phishing": "T1566",
    "suplantación": "T1566",
    "macro": "T1204.002",
    "macros": "T1204.002",
    "troyano": "T1204.002",
    "minería": "T1496",
    "criptominería": "T1496",
    "cryptojacking": "T1496",
    "stealer": "T1555.003",
    "infostealer": "T1555.003",
    "robo de contraseñas": "T1555",
    "puerta trasera": "T1543",
    "backdoor": "T1543",
    "rootkit": "T1014",
    "gusano": "T1091",
    "usb": "T1091",
    "fuerza bruta": "T1110",
    "escritorio remoto": "T1021.001",
    "inyección": "T1055",
}


def _limpiar(texto: str, maximo: int = 700) -> str:
    texto = re.sub(r"\(Citation:[^)]*\)", "", texto or "")
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)  # [Emotet](url) -> Emotet
    texto = re.sub(r"<code>|</code>", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > maximo:
        corte = texto.rfind(". ", 0, maximo)
        texto = texto[: corte + 1 if corte > maximo // 2 else maximo] + " …"
    return texto


def _id_externo(o: dict) -> str:
    for r in o.get("external_references", []):
        if r.get("source_name") == "mitre-attack":
            return r.get("external_id", "")
    return ""


def compactar_attack(stix: dict) -> dict:
    objs = [o for o in stix["objects"] if not o.get("revoked") and not o.get("x_mitre_deprecated")]
    por_id = {o["id"]: o for o in objs}
    mitiga: dict[str, list[str]] = {}
    detecta: dict[str, list[str]] = {}
    usa: dict[str, list[str]] = {}
    for r in objs:
        if r["type"] != "relationship":
            continue
        origen, destino = por_id.get(r["source_ref"]), por_id.get(r["target_ref"])
        if not origen or not destino:
            continue
        if r["relationship_type"] == "mitigates" and origen["type"] == "course-of-action":
            mitiga.setdefault(destino["id"], []).append(origen["name"])
        elif r["relationship_type"] == "detects":
            detecta.setdefault(destino["id"], []).append(origen["name"])
        elif (
            r["relationship_type"] == "uses"
            and origen["type"] in ("malware", "tool")
            and destino["type"] == "attack-pattern"
        ):
            usa.setdefault(origen["id"], []).append(_id_externo(destino))

    tecnicas = []
    for o in objs:
        if o["type"] != "attack-pattern":
            continue
        plataformas = o.get("x_mitre_platforms", [])
        if plataformas and "Windows" not in plataformas:
            continue  # Moni cuida una PC con Windows
        tecnicas.append(
            {
                "id": _id_externo(o),
                "nombre": o["name"],
                "tacticas": [
                    TACTICAS.get(k["phase_name"], k["phase_name"])
                    for k in o.get("kill_chain_phases", [])
                ],
                "descripcion": _limpiar(o.get("description", "")),
                "mitigaciones": sorted(set(mitiga.get(o["id"], [])))[:6],
                "deteccion": sorted(set(detecta.get(o["id"], [])))[:3],
            }
        )
    software = []
    for o in objs:
        if o["type"] not in ("malware", "tool"):
            continue
        plataformas = o.get("x_mitre_platforms", [])
        if plataformas and "Windows" not in plataformas:
            continue
        software.append(
            {
                "id": _id_externo(o),
                "nombre": o["name"],
                "tipo": "malware" if o["type"] == "malware" else "herramienta",
                "alias": [a for a in o.get("x_mitre_aliases", []) if a != o["name"]],
                "descripcion": _limpiar(o.get("description", ""), 600),
                "tecnicas": sorted({t for t in usa.get(o["id"], []) if t})[:15],
            }
        )
    version = next(
        (o.get("x_mitre_version") for o in objs if o["type"] == "x-mitre-collection"), ""
    )
    return {"version": version, "tecnicas": tecnicas, "software": software}


def compactar_lolbas(datos: list[dict]) -> list[dict]:
    salida = []
    for e in datos:
        comandos = e.get("Commands") or []
        salida.append(
            {
                "nombre": e.get("Name", ""),
                "descripcion": e.get("Description", ""),
                "rutas": [p.get("Path") for p in e.get("Full_Path") or [] if p.get("Path")],
                # Solo qué permite hacer, nunca el comando concreto.
                "abusos": sorted({c.get("Usecase", "") for c in comandos if c.get("Usecase")}),
                "categorias": sorted(
                    {c.get("Category", "") for c in comandos if c.get("Category")}
                ),
                "tecnicas": sorted({c.get("MitreID", "") for c in comandos if c.get("MitreID")}),
                "privilegios": sorted(
                    {c.get("Privileges", "") for c in comandos if c.get("Privileges")}
                ),
            }
        )
    return salida


class Saber:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self._attack: dict | None = None
        self._lolbas: list | None = None
        self._mtimes: tuple = ()

    @property
    def ruta_attack(self) -> Path:
        return self.carpeta / "attack.json"

    @property
    def ruta_lolbas(self) -> Path:
        return self.carpeta / "lolbas.json"

    def necesita_actualizar(self) -> bool:
        for p in (self.ruta_attack, self.ruta_lolbas):
            if not p.exists():
                return True
            if datetime.now() - datetime.fromtimestamp(p.stat().st_mtime) > VIGENCIA:
                return True
        return False

    def actualizar(self, cliente: httpx.Client | None = None) -> dict:
        cliente = cliente or httpx.Client(timeout=180, follow_redirects=True)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        resumen = {}
        r = cliente.get(URL_ATTACK)
        r.raise_for_status()
        attack = compactar_attack(r.json())
        _escribir(self.ruta_attack, attack)
        resumen["attack"] = (
            f"{len(attack['tecnicas'])} técnicas, {len(attack['software'])} programas"
        )
        r = cliente.get(URL_LOLBAS)
        r.raise_for_status()
        lolbas = compactar_lolbas(r.json())
        _escribir(self.ruta_lolbas, lolbas)
        resumen["lolbas"] = f"{len(lolbas)} programas de Windows"
        self._attack = self._lolbas = None
        log.info("Conocimiento de seguridad actualizado: %s", resumen)
        return resumen

    def _cargar(self) -> None:
        mtimes = tuple(
            p.stat().st_mtime if p.exists() else 0 for p in (self.ruta_attack, self.ruta_lolbas)
        )
        if self._attack is not None and mtimes == self._mtimes:
            return
        if not self.ruta_attack.exists():
            raise ValueError(
                "Todavía no tengo descargado el conocimiento de seguridad. Pide "
                "actualizar_conocimiento_de_seguridad (necesita internet una vez)."
            )
        self._attack = json.loads(self.ruta_attack.read_text("utf-8"))
        self._lolbas = (
            json.loads(self.ruta_lolbas.read_text("utf-8")) if self.ruta_lolbas.exists() else []
        )
        self._mtimes = mtimes

    # ------------------------------------------------------------ consultas

    def buscar_attack(self, consulta: str, limite: int = 3) -> list[dict]:
        self._cargar()
        assert self._attack is not None
        q = consulta.strip()
        ident = re.fullmatch(r"([TtSs])(\d{4})(\.\d{3})?", q)
        todos = self._attack["tecnicas"] + self._attack["software"]
        if ident:
            q = q.upper()
            return [x for x in todos if x["id"] == q][:1]
        primero = [
            x
            for concepto, tid in CONCEPTOS.items()
            if re.search(rf"\b{re.escape(concepto)}\b", q.lower())
            for x in todos
            if x["id"] == tid
        ]
        palabras = _palabras(q)
        if not palabras:
            return primero[:limite]
        puntos = []
        for x in todos:
            nombre = " ".join([x["nombre"], *x.get("alias", [])]).lower()
            texto = x["descripcion"].lower()
            p = 0.0
            if q.lower() == x["nombre"].lower() or q.lower() in [
                a.lower() for a in x.get("alias", [])
            ]:
                p += 20
            for w in palabras:
                if re.search(rf"\b{re.escape(w)}", nombre):
                    p += 4
                elif re.search(rf"\b{re.escape(w)}", texto):
                    p += 1
            if p:
                # a igualdad, mejor la técnica general que la sub-técnica
                puntos.append((p - 0.1 * x["id"].count("."), x))
        puntos.sort(key=lambda t: t[0], reverse=True)
        unicos = {x["id"]: x for x in primero}
        for _, x in puntos:
            unicos.setdefault(x["id"], x)
        return list(unicos.values())[:limite]

    def buscar_lolbas(self, programa: str) -> dict | None:
        self._cargar()
        nombre = re.split(r"[\\/]", programa.strip().strip('"'))[-1].lower()
        if not nombre:
            return None
        candidatos = {nombre, nombre + ".exe"} if "." not in nombre else {nombre}
        for e in self._lolbas or []:
            if e["nombre"].lower() in candidatos:
                return e
        return None


_VACIAS = {
    "que", "qué", "es", "un", "una", "el", "la", "los", "las", "de", "del", "y", "o", "en",
    "para", "por", "con", "como", "cómo", "sobre", "the", "a", "an", "of", "to", "and", "what",
    "is", "hacen", "hace", "usan", "atacantes", "hackers", "técnica", "tecnica", "ataque",
}  # fmt: skip


def _palabras(texto: str) -> list[str]:
    salida: list[str] = []
    for w in re.findall(r"[\wáéíóúñ.-]+", texto.lower()):
        if w in _VACIAS or len(w) < 3:
            continue
        salida.append(w)
        salida += SINONIMOS.get(w, "").split()
    return list(dict.fromkeys(salida))


def _escribir(ruta: Path, datos) -> None:
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False), "utf-8")
    tmp.replace(ruta)
