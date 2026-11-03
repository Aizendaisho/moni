"""Registro de herramientas que Moni puede usar.

Cada herramienta es una función de Python normal con un docstring estilo Google
(descripción + sección Args). El decorador @herramienta la registra con su nivel de
permiso y genera el esquema JSON que entiende el LLM.

    @herramienta(Nivel.LIBRE, etiqueta="Revisando procesos")
    def listar_procesos(limite: int = 10) -> list[dict]:
        '''Lista los procesos que más memoria usan.

        Args:
          limite: Cuántos procesos devolver.
        '''
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ollama._utils import convert_function_to_tool

from ..permissions.policy import Nivel


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    funcion: Callable[..., Any]
    nivel: Nivel
    etiqueta: str  # texto corto que ve el usuario mientras se ejecuta
    esquema: dict


REGISTRO: dict[str, Herramienta] = {}


def _esquema(fn: Callable[..., Any]) -> dict:
    esquema = convert_function_to_tool(fn).model_dump(exclude_none=True)
    # Los parámetros con valor por defecto son opcionales para el modelo.
    opcionales = {
        n for n, p in inspect.signature(fn).parameters.items() if p.default is not p.empty
    }
    params = esquema["function"]["parameters"]
    params["required"] = [r for r in params.get("required", []) if r not in opcionales]
    return esquema


def herramienta(nivel: Nivel, etiqueta: str) -> Callable[[Callable], Callable]:
    def registrar(fn: Callable) -> Callable:
        REGISTRO[fn.__name__] = Herramienta(fn.__name__, fn, nivel, etiqueta, _esquema(fn))
        return fn

    return registrar


def esquemas() -> list[dict]:
    """Esquemas de todas las herramientas disponibles (se omiten las prohibidas)."""
    return [h.esquema for h in REGISTRO.values() if h.nivel is not Nivel.PROHIBIDO]
