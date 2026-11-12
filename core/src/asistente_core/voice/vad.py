"""Detección de voz: decide dónde empieza y termina una frase a partir de la probabilidad de voz
de cada bloque de audio (Silero VAD da una por cada 32 ms a 16 kHz).

La lógica (Segmentador) no depende del micrófono, así se puede probar con números.
"""

from collections import deque
from dataclasses import dataclass, field

import numpy as np

FRECUENCIA = 16_000
BLOQUE = 512  # muestras por bloque que acepta Silero a 16 kHz (32 ms)
MS_BLOQUE = BLOQUE * 1000 // FRECUENCIA


@dataclass
class Segmentador:
    umbral: float = 0.5
    silencio_ms: int = 700  # silencio para dar la frase por terminada
    minimo_ms: int = 250  # menos que esto es un ruido, no una frase
    maximo_ms: int = 20_000
    previo_ms: int = 300  # audio que se guarda antes del inicio (para no cortar la primera sílaba)
    _previo: deque = field(default_factory=deque, init=False)
    _actual: list = field(default_factory=list, init=False)
    _hablando: bool = field(default=False, init=False)
    _silencio: int = field(default=0, init=False)
    _voz: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # +1: el bloque que dispara el inicio también entra
        self._previo = deque(maxlen=max(1, self.previo_ms // MS_BLOQUE) + 1)

    @property
    def hablando(self) -> bool:
        return self._hablando

    def reiniciar(self) -> None:
        self._previo.clear()
        self._actual, self._hablando, self._silencio, self._voz = [], False, 0, 0

    def procesar(self, bloque: np.ndarray, prob: float) -> np.ndarray | None:
        """Agrega un bloque con su probabilidad de voz. Devuelve el audio de la frase cuando
        termina, o None."""
        if not self._hablando:
            self._previo.append(bloque)
            if prob >= self.umbral:
                self._hablando = True
                self._actual = list(self._previo)
                self._silencio, self._voz = 0, MS_BLOQUE
            return None
        self._actual.append(bloque)
        if prob >= self.umbral - 0.15:  # histéresis: no cortar por una caída breve
            self._silencio = 0
            self._voz += MS_BLOQUE
        else:
            self._silencio += MS_BLOQUE
        duracion = len(self._actual) * MS_BLOQUE
        if self._silencio >= self.silencio_ms or duracion >= self.maximo_ms:
            audio, voz = np.concatenate(self._actual), self._voz
            self.reiniciar()
            return audio if voz >= self.minimo_ms else None
        return None


class DetectorSilero:
    """Probabilidad de voz por bloque con Silero VAD (MIT)."""

    def __init__(self) -> None:
        import torch
        from silero_vad import load_silero_vad

        torch.set_num_threads(1)
        self._torch = torch
        self._modelo = load_silero_vad(onnx=True)

    def __call__(self, bloque: np.ndarray) -> float:
        audio = bloque.astype(np.float32)
        if bloque.dtype == np.int16:
            audio /= 32768.0
        return float(self._modelo(self._torch.from_numpy(audio), FRECUENCIA).item())

    def reiniciar(self) -> None:
        self._modelo.reset_states()
