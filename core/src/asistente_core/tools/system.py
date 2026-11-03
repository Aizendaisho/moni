"""Herramientas de control del sistema (sprint S2). Por ahora solo lectura."""

import psutil

from ..permissions.policy import Nivel

NIVELES = {
    "listar_procesos": Nivel.LIBRE,
    "cerrar_proceso": Nivel.CONFIRMAR,  # pendiente de implementar en S2
}


def listar_procesos(limite: int = 15) -> list[dict]:
    """Procesos que más memoria usan."""
    procesos = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        info = p.info
        mem = info.get("memory_info")
        procesos.append(
            {
                "pid": info["pid"],
                "nombre": info.get("name") or "?",
                "memoria_mb": round(mem.rss / 1_048_576, 1) if mem else 0.0,
            }
        )
    procesos.sort(key=lambda x: x["memoria_mb"], reverse=True)
    return procesos[:limite]
