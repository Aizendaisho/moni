"""Consultar la bitácora: qué ha hecho Moni últimamente (sprint S2)."""

import json

from ..memory import bitacora
from ..permissions.policy import Nivel
from .registry import herramienta


@herramienta(Nivel.LIBRE, etiqueta="Revisando la bitácora")
def ver_actividad(limite: int = 10) -> list[dict]:
    """Muestra las últimas acciones que Moni ha hecho en la computadora (programas abiertos o cerrados, consultas, confirmaciones), de la más reciente a la más antigua.

    Args:
      limite: Cuántas acciones mostrar.
    """
    b = bitacora.actual()
    if b is None:
        return []
    salida = []
    for a in b.ultimas(max(1, min(int(limite), 50))):
        if a["herramienta"] == "ver_actividad":
            continue
        salida.append(
            {
                "fecha": a["fecha"],
                "accion": a["herramienta"],
                "argumentos": json.loads(a["argumentos"]),
                "confirmacion": {None: "no hacía falta", 1: "aceptada", 0: "rechazada"}[
                    a["confirmado"]
                ],
                "salio_bien": bool(a["ok"]),
                "resultado": a["resultado"][:200],
            }
        )
    return salida
