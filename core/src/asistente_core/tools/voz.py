"""Herramienta para que Moni cambie su propia voz."""

from ..config import settings
from ..permissions.policy import Nivel
from ..voice import estado, voces
from .registry import herramienta


@herramienta(Nivel.LIBRE, etiqueta="Cambiando mi voz")
def cambiar_voz(voz: str = "", estilo: str = "") -> dict:
    """Cambia TU voz (la que usas al hablar en voz alta) o tu forma de hablar. Sin argumentos, lista las voces disponibles. La elección se guarda para la próxima vez.

    Args:
      voz: Cuál: "claude" (femenina, México), "daniela" (femenina, Argentina), "española" (femenina, España), "masculina"... Vacío = no cambiarla.
      estilo: "suave" (más lenta y calmada) o "normal". Vacío = no cambiarlo.
    """
    m = estado.motor
    pref = voces.leer_preferencia(settings.data_dir / "voz.json") or {}
    actual = pref.get("voz") or settings.piper_voice
    estilo_actual = pref.get("estilo") or settings.voice_style
    if not voz and not estilo:
        return {
            "voz_actual": f"{actual} ({voces.CATALOGO.get(actual, '')})",
            "estilo_actual": estilo_actual,
            "disponibles": voces.CATALOGO,
            "estilos": list(voces.ESTILOS),
        }
    nombre, hablante = voces.resolver(voz) if voz else (actual, pref.get("hablante"))
    estilo = (estilo or estilo_actual).lower()
    if estilo not in voces.ESTILOS:
        raise ValueError("Estilo no válido: usa suave o normal.")
    voces.guardar_preferencia(settings.data_dir / "voz.json", nombre, estilo, hablante)
    if m is not None:
        m.cambiar_voz(settings.data_dir / "modelos" / "piper" / f"{nombre}.onnx", estilo, hablante)
    return {
        "hecho": f"Ahora uso la voz {nombre} ({voces.CATALOGO.get(nombre, '')}), estilo {estilo}.",
        "nota": "Si es la primera vez, se descarga (unos 60-110 MB) antes de la próxima frase.",
    }
