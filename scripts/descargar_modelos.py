"""Descarga los modelos de voz a data/modelos para que el asistente funcione sin internet.

Se ejecuta desde scripts/setup.ps1:  uv run python ../scripts/descargar_modelos.py
"""

import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = RAIZ / "data" / "modelos"

WHISPER = "small"
PIPER_VOZ = (
    "es_MX-ald-medium"  # cambia aquí la voz; lista en https://rhasspy.github.io/piper-samples/
)
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_MX/ald/medium"


def paso(texto: str) -> None:
    print(f"    -> {texto}", flush=True)


def whisper() -> None:
    from faster_whisper import download_model

    destino = MODELOS / "whisper" / WHISPER
    paso(f"faster-whisper '{WHISPER}'")
    download_model(WHISPER, output_dir=str(destino))


def piper() -> None:
    destino = MODELOS / "piper"
    destino.mkdir(parents=True, exist_ok=True)
    for ext in (".onnx", ".onnx.json"):
        archivo = destino / f"{PIPER_VOZ}{ext}"
        if archivo.exists():
            continue
        paso(f"Piper {archivo.name}")
        urllib.request.urlretrieve(f"{PIPER_BASE}/{PIPER_VOZ}{ext}", archivo)


def wakeword() -> None:
    import openwakeword.utils

    paso("openWakeWord (modelos base)")
    openwakeword.utils.download_models()


def silero() -> None:
    from silero_vad import load_silero_vad

    paso("Silero VAD")
    load_silero_vad()  # viene dentro del paquete; esto solo comprueba que carga


def main() -> int:
    fallos = []
    for nombre, fn in (
        ("Whisper", whisper),
        ("Piper", piper),
        ("openWakeWord", wakeword),
        ("Silero", silero),
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - se informa y se sigue con los demás
            print(f"    !! {nombre}: {exc}", flush=True)
            fallos.append(nombre)
    if fallos:
        print(f"    Fallaron: {', '.join(fallos)}")
        return 1
    print(f"    Modelos de voz listos en {MODELOS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
