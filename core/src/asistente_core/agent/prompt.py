"""Construye el mensaje de sistema de Moni a partir de personalidad.md.

Edita core/src/asistente_core/agent/personalidad.md para cambiar cómo habla Moni:
se vuelve a leer en cada mensaje, así que no hace falta reiniciar el núcleo.
"""

from pathlib import Path

from ..config import settings
from ..tools.system import fecha_hora

_ARCHIVO = Path(__file__).with_name("personalidad.md")


def mensaje_sistema() -> dict:
    texto = _ARCHIVO.read_text(encoding="utf-8").replace("{usuario}", settings.user_name)
    texto += f"\n\nAhora es {fecha_hora()}."
    return {"role": "system", "content": texto}
