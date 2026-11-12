"""Descarga los modelos de voz a data/modelos para que el asistente funcione sin internet.

Se ejecuta desde scripts/setup.ps1:  uv run python ../scripts/descargar_modelos.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = RAIZ / "data" / "modelos"

WHISPER = "small"
PIPER_VOZ = "es_MX-claude-high"  # voz femenina; otras en core/src/asistente_core/voice/voces.py


def paso(texto: str) -> None:
    print(f"    -> {texto}", flush=True)


def whisper() -> None:
    from faster_whisper import download_model

    destino = MODELOS / "whisper" / WHISPER
    paso(f"faster-whisper '{WHISPER}'")
    download_model(WHISPER, output_dir=str(destino))


def piper() -> None:
    from asistente_core.voice.voces import asegurar

    paso(f"Piper {PIPER_VOZ}")
    asegurar(PIPER_VOZ, MODELOS / "piper")


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
