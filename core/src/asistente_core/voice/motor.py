"""Motor de voz de Moni: escucha (micrófono + VAD + Whisper), habla (Piper) e interrupciones.

Todo corre en la PC y en CPU, para dejar la GPU al modelo de chat:
  - Silero VAD: ~1 ms por bloque de 32 ms.
  - faster-whisper "small" int8: ~1 s por frase corta en un Ryzen 5 5600H.
  - Piper es_MX-ald-medium: más rápido que tiempo real.

Modos:
  - Pulsar para hablar: la app pide `escuchar_una_vez()`; se graba una frase y se transcribe.
  - Manos libres: se escucha siempre; una frase que empieza con "Moni" activa a Moni (lo que
    venga después del nombre es la orden; si no hay nada, escucha la siguiente frase).
  - Mientras Moni habla, si el usuario habla por encima (más fuerte que el eco), se calla y
    escucha (barge-in). Con parlantes puede saltar por el propio eco: con audífonos va mejor.

Los modelos se cargan la primera vez que se usan.
"""

import logging
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .texto import activacion, limpiar_para_voz
from .vad import BLOQUE, FRECUENCIA, DetectorSilero, Segmentador

log = logging.getLogger("moni.voz")


class Transcriptor:
    def __init__(self, modelo: Path | str, idioma: str = "es"):
        from faster_whisper import WhisperModel

        self.idioma = idioma
        self._m = WhisperModel(str(modelo), device="cpu", compute_type="int8", cpu_threads=4)

    def __call__(self, audio: np.ndarray) -> str:
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        segmentos, _ = self._m.transcribe(
            audio,
            language=self.idioma,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt="Moni, asistente personal.",  # ayuda a escribir bien su nombre
        )
        return " ".join(s.text.strip() for s in segmentos).strip()


class Sintetizador:
    def __init__(self, modelo: Path | str, estilo: str = "suave", hablante: int | None = None):
        from piper import PiperVoice
        from piper.config import SynthesisConfig

        from .voces import ESTILOS

        self._voz = PiperVoice.load(str(modelo))
        self._config = SynthesisConfig(
            speaker_id=hablante, **ESTILOS.get(estilo, ESTILOS["normal"])
        )
        self.frecuencia = self._voz.config.sample_rate

    def __call__(self, frase: str) -> np.ndarray:
        trozos = [c.audio_int16_array for c in self._voz.synthesize(frase, self._config)]
        return np.concatenate(trozos) if trozos else np.zeros(0, dtype=np.int16)


class MotorVoz:
    def __init__(
        self,
        modelo_whisper: Path,
        modelo_piper: Path,
        al_transcribir: Callable[[str], None],
        al_cambiar_estado: Callable[[str], None] = lambda e: None,
        interrumpir_con_voz: bool = True,
        estilo: str = "suave",
        hablante: int | None = None,
    ):
        self.estilo, self.hablante = estilo, hablante
        self.modelo_whisper, self.modelo_piper = modelo_whisper, modelo_piper
        self.al_transcribir = al_transcribir
        self.al_cambiar_estado = al_cambiar_estado
        self.interrumpir_con_voz = interrumpir_con_voz
        self._stt: Transcriptor | None = None
        self._tts: Sintetizador | None = None
        self._vad: DetectorSilero | None = None
        self._carga = threading.Lock()
        self._hablar_cola: queue.Queue[str | None] = queue.Queue()
        self._callar = threading.Event()
        self.hablando = threading.Event()
        self._escuchando = threading.Event()  # hilo de micrófono activo
        self.manos_libres = False
        self._una_vez = False
        self._esperando_orden = False
        self._hilo_hablar = threading.Thread(
            target=self._bucle_hablar, daemon=True, name="voz-hablar"
        )
        self._hilo_hablar.start()
        self._hilo_oir: threading.Thread | None = None

    # ------------------------------------------------------------ modelos

    def cargar(self) -> None:
        with self._carga:
            if self._vad is None:
                self._vad = DetectorSilero()
            if self._stt is None:
                if not Path(self.modelo_whisper).exists():
                    raise ValueError(f"Falta el modelo de Whisper en {self.modelo_whisper}")
                self._stt = Transcriptor(self.modelo_whisper)
            if self._tts is None:
                from .voces import asegurar

                modelo = asegurar(Path(self.modelo_piper).stem, Path(self.modelo_piper).parent)
                self._tts = Sintetizador(modelo, self.estilo, self.hablante)

    # ------------------------------------------------------------ hablar

    def decir(self, frase: str) -> None:
        texto = limpiar_para_voz(frase)
        if texto:
            self._hablar_cola.put(texto)

    def callar(self) -> None:
        """Corta lo que está diciendo y descarta lo pendiente."""
        self._callar.set()
        while not self._hablar_cola.empty():
            try:
                self._hablar_cola.get_nowait()
            except queue.Empty:
                break

    def _bucle_hablar(self) -> None:
        import sounddevice as sd

        while True:
            frase = self._hablar_cola.get()
            if frase is None:
                return
            self._callar.clear()
            try:
                self.cargar()
                audio = self._tts(frase)
                self.hablando.set()
                self.al_cambiar_estado("hablando")
                sd.play(audio, self._tts.frecuencia)
                duracion = len(audio) / self._tts.frecuencia
                inicio = time.monotonic()
                while time.monotonic() - inicio < duracion + 0.05:
                    if self._callar.is_set():
                        sd.stop()
                        break
                    time.sleep(0.02)
            except Exception:
                log.exception("No se pudo hablar")
            finally:
                if self._hablar_cola.empty():
                    self.hablando.clear()
                    self.al_cambiar_estado("escuchando" if self.manos_libres else "inactivo")

    # ------------------------------------------------------------ escuchar

    def escuchar_una_vez(self) -> None:
        """Graba una sola frase (botón de micrófono)."""
        self.callar()
        self._una_vez = True
        self._arrancar_microfono()

    def activar_manos_libres(self, activo: bool) -> None:
        self.manos_libres = activo
        if activo:
            self._arrancar_microfono()
        self.al_cambiar_estado("escuchando" if activo else "inactivo")

    def _arrancar_microfono(self) -> None:
        if self._hilo_oir and self._hilo_oir.is_alive():
            return
        self._hilo_oir = threading.Thread(target=self._bucle_oir, daemon=True, name="voz-oir")
        self._hilo_oir.start()

    def _bucle_oir(self) -> None:
        import sounddevice as sd

        try:
            self.cargar()
        except Exception as exc:
            log.exception("No se pudo cargar la voz")
            self.al_cambiar_estado(f"error: {exc}")
            self._una_vez = self.manos_libres = False
            return
        seg = Segmentador()
        # mientras Moni habla, hace falta más seguridad para interrumpir (por el eco)
        seg_interrumpir = Segmentador(umbral=0.85, silencio_ms=400, minimo_ms=400)
        bloques: queue.Queue[np.ndarray] = queue.Queue()

        def recibir(indata, frames, tiempo, estado) -> None:  # hilo de audio: solo encolar
            bloques.put(indata[:, 0].copy())

        self.al_cambiar_estado("escuchando")
        with sd.InputStream(
            samplerate=FRECUENCIA, channels=1, dtype="int16", blocksize=BLOQUE, callback=recibir
        ):
            while self._una_vez or self.manos_libres:
                try:
                    bloque = bloques.get(timeout=0.5)
                except queue.Empty:
                    continue
                prob = self._vad(bloque)
                if self.hablando.is_set():
                    if (
                        self.interrumpir_con_voz
                        and seg_interrumpir.procesar(bloque, prob) is not None
                    ):
                        log.info("Interrupción por voz")
                        self.callar()
                        self._esperando_orden = True
                    continue
                frase = seg.procesar(bloque, prob)
                if frase is None:
                    continue
                self._procesar_frase(frase)
        self._vad.reiniciar()

    def _procesar_frase(self, audio: np.ndarray) -> None:
        self.al_cambiar_estado("transcribiendo")
        t = time.perf_counter()
        texto = self._stt(audio)
        log.info("Transcrito en %.1f s: %r", time.perf_counter() - t, texto)
        if self._una_vez:
            self._una_vez = False
            self.al_cambiar_estado("escuchando" if self.manos_libres else "inactivo")
            if texto:
                self.al_transcribir(texto)
            return
        # manos libres: hace falta decir "Moni" (salvo justo después de llamarla)
        llamada, resto = activacion(texto)
        if self._esperando_orden and texto:
            self._esperando_orden = False
            self.al_transcribir(resto if llamada and resto else texto)
        elif llamada and resto:
            self.al_transcribir(resto)
        elif llamada:
            self._esperando_orden = True
            self.al_cambiar_estado("te escucho")
            return
        self.al_cambiar_estado("escuchando")

    def cambiar_voz(self, modelo_piper: Path, estilo: str, hablante: int | None) -> None:
        """Cambia la voz; se carga (y descarga si hace falta) en la próxima frase."""
        with self._carga:
            self.modelo_piper, self.estilo, self.hablante = Path(modelo_piper), estilo, hablante
            self._tts = None

    def detener(self) -> None:
        self.manos_libres = self._una_vez = False
        self.callar()
        self._hablar_cola.put(None)
