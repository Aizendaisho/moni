"""Diagnóstico de la voz de Moni: Piper -> Silero -> Whisper, sin micrófono.

Uso: doble clic en scripts\\probar_voz.bat. Escribe el resultado en data\\prueba_voz.json y
reproduce la frase por los parlantes.
"""

import json
import sys
import time
import traceback

import numpy as np

from asistente_core.config import settings

FRASE = "Hola, soy Moni. Moni, abre el bloc de notas, por favor."
res: dict = {"frase": FRASE}


def paso(nombre, fn):
    t = time.perf_counter()
    try:
        valor = fn()
        res[nombre] = {"ok": True, "segundos": round(time.perf_counter() - t, 2), "valor": valor}
        return valor
    except Exception as exc:  # noqa: BLE001
        res[nombre] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traza": traceback.format_exc()[-1500:],
        }
        return None


def dispositivos():
    import sounddevice as sd

    entrada, salida = sd.default.device
    lista = sd.query_devices()
    return {
        "entrada": lista[entrada]["name"] if entrada is not None and entrada >= 0 else None,
        "salida": lista[salida]["name"] if salida is not None and salida >= 0 else None,
        "microfonos": sorted({d["name"] for d in lista if d["max_input_channels"] > 0})[:8],
    }


paso("dispositivos", dispositivos)

modelos = settings.data_dir / "modelos"
from asistente_core.voice.motor import Sintetizador, Transcriptor
from asistente_core.voice.texto import activacion
from asistente_core.voice.vad import BLOQUE, FRECUENCIA, DetectorSilero, Segmentador

sint = paso(
    "cargar_piper", lambda: Sintetizador(modelos / "piper" / f"{settings.piper_voice}.onnx")
)
audio = paso("sintetizar", lambda: sint(FRASE)) if sint else None
if audio is not None:
    res["sintetizar"]["valor"] = (
        f"{len(audio) / sint.frecuencia:.1f} s de audio a {sint.frecuencia} Hz"
    )


def reproducir():
    import sounddevice as sd

    sd.play(audio, sint.frecuencia)
    sd.wait()
    return "reproducido"


if audio is not None:
    paso("reproducir", reproducir)

frases = []


def vad():
    det = DetectorSilero()
    x = np.interp(
        np.linspace(0, len(audio), int(len(audio) * FRECUENCIA / sint.frecuencia), endpoint=False),
        np.arange(len(audio)),
        audio.astype(np.float32),
    ).astype(np.int16)
    x = np.concatenate([np.zeros(FRECUENCIA // 2, np.int16), x, np.zeros(FRECUENCIA, np.int16)])
    seg = Segmentador()
    for i in range(0, len(x) - BLOQUE + 1, BLOQUE):
        b = x[i : i + BLOQUE]
        f = seg.procesar(b, det(b))
        if f is not None:
            frases.append(f)
    return f"{len(frases)} frase(s) detectada(s)"


if audio is not None:
    paso("silero_vad", vad)

stt = paso("cargar_whisper", lambda: Transcriptor(modelos / "whisper" / settings.whisper_model))
if stt and frases:
    texto = paso("transcribir", lambda: " ".join(stt(f) for f in frases))
    if texto:
        res["activacion"] = activacion(texto.split(".")[-2] if texto.count(".") > 1 else texto)

destino = settings.data_dir / "prueba_voz.json"
destino.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(
    json.dumps(
        {k: (v.get("ok") if isinstance(v, dict) else v) for k, v in res.items()},
        ensure_ascii=False,
        indent=1,
    )
)
print(f"\nResultado completo en {destino}")
sys.exit(0)
