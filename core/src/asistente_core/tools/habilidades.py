"""Herramienta para que Moni cuente qué skills tiene."""

from ..agent import skills
from ..permissions.policy import Nivel
from .registry import herramienta


@herramienta(Nivel.LIBRE, etiqueta="Revisando mis skills")
def mis_skills() -> list[dict]:
    """Lista las skills de Moni: tareas que sabe hacer paso a paso (revisar archivos, PC lenta...)."""
    s = skills.actual()
    if s is None:
        return []
    return [{"skill": k.titulo, "para": k.descripcion} for k in s.todas()]
