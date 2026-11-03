"""Herramientas de información del sistema (solo lectura, nivel LIBRE).

Las que cambian algo (cerrar procesos, abrir apps) llegan en el sprint S2,
junto con el diálogo de confirmación.
"""

import platform
from datetime import datetime

import psutil

from ..permissions.policy import Nivel
from .registry import herramienta

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


def _gb(n: float) -> float:
    return round(n / 1_073_741_824, 1)


@herramienta(Nivel.LIBRE, etiqueta="Revisando procesos")
def listar_procesos(limite: int = 10) -> list[dict]:
    """Lista los programas y procesos abiertos que más memoria RAM usan en la computadora.

    Args:
      limite: Cuántos procesos devolver, de mayor a menor uso de memoria.
    """
    limite = max(1, min(int(limite), 50))
    agrupados: dict[str, float] = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        mem = p.info.get("memory_info")
        if not mem:
            continue
        nombre = (p.info.get("name") or "?").removesuffix(".exe")
        agrupados[nombre] = agrupados.get(nombre, 0) + mem.rss
    orden = sorted(agrupados.items(), key=lambda x: x[1], reverse=True)[:limite]
    return [{"nombre": n, "memoria_mb": round(b / 1_048_576)} for n, b in orden]


@herramienta(Nivel.LIBRE, etiqueta="Revisando el sistema")
def estado_sistema() -> dict:
    """Muestra el estado actual de la computadora: uso de CPU, memoria RAM, disco y batería."""
    ram = psutil.virtual_memory()
    disco = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
    estado = {
        "cpu_porcentaje": psutil.cpu_percent(interval=0.5),
        "ram_usada_gb": _gb(ram.used),
        "ram_total_gb": _gb(ram.total),
        "ram_porcentaje": ram.percent,
        "disco_libre_gb": _gb(disco.free),
        "disco_total_gb": _gb(disco.total),
    }
    bateria = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if bateria:
        estado["bateria_porcentaje"] = round(bateria.percent)
        estado["cargando"] = bool(bateria.power_plugged)
    return estado


@herramienta(Nivel.LIBRE, etiqueta="Mirando la hora")
def fecha_hora() -> str:
    """Devuelve la fecha y la hora actuales de la computadora."""
    ahora = datetime.now()
    return (
        f"{_DIAS[ahora.weekday()]} {ahora.day} de {_MESES[ahora.month - 1]} de {ahora.year}, "
        f"{ahora.strftime('%I:%M %p').lstrip('0')}"
    )
