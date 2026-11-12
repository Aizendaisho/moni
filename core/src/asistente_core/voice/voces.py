"""Voces de Piper: catálogo, estilo (suave) y descarga automática.

Las voces vienen de huggingface.co/rhasspy/piper-voices (cada una tiene su MODEL_CARD con
la licencia de sus datos). Se descargan la primera vez a data/modelos/piper.
"""

import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger("moni.voces")

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Voces en español disponibles en Piper (género según su ficha).
CATALOGO = {
    "es_MX-claude-high": "femenina, México, calidad alta (la de Moni por defecto)",
    "es_AR-daniela-high": "femenina, Argentina, calidad alta",
    "es_ES-sharvard-medium": "voz de España con dos hablantes (0 masculino, 1 femenino)",
    "es_MX-ald-medium": "masculina, México",
    "es_ES-davefx-medium": "masculina, España",
}

# Estilo "suave": un poco más lenta, con menos variación y algo más baja.
ESTILOS = {
    "suave": {"length_scale": 1.12, "noise_scale": 0.5, "noise_w_scale": 0.6, "volume": 0.85},
    "normal": {"length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8, "volume": 1.0},
}


def url_de(nombre: str) -> str:
    """'es_MX-claude-high' -> .../es/es_MX/claude/high/es_MX-claude-high"""
    m = re.fullmatch(r"([a-z]{2})_([A-Z]{2})-([\w]+)-(x_low|low|medium|high)", nombre)
    if not m:
        raise ValueError(f"Nombre de voz de Piper no válido: {nombre}")
    idioma, pais, voz, calidad = m.groups()
    return f"{BASE}/{idioma}/{idioma}_{pais}/{voz}/{calidad}/{nombre}"


def asegurar(nombre: str, carpeta: Path, cliente: httpx.Client | None = None) -> Path:
    """Devuelve la ruta del .onnx de la voz, descargándola si falta."""
    carpeta = Path(carpeta)
    modelo = carpeta / f"{nombre}.onnx"
    if modelo.exists() and (carpeta / f"{nombre}.onnx.json").exists():
        return modelo
    carpeta.mkdir(parents=True, exist_ok=True)
    cliente = cliente or httpx.Client(timeout=300, follow_redirects=True)
    base = url_de(nombre)
    for ext in (".onnx.json", ".onnx"):
        destino = carpeta / f"{nombre}{ext}"
        if destino.exists():
            continue
        log.info("Descargando la voz %s%s", nombre, ext)
        tmp = destino.with_suffix(destino.suffix + ".part")
        with cliente.stream("GET", base + ext) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for bloque in r.iter_bytes(1 << 20):
                    f.write(bloque)
        tmp.replace(destino)
    return modelo
