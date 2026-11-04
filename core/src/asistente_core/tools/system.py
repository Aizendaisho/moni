"""Herramientas de información del sistema (solo lectura, nivel LIBRE).

Las que cambian algo (cerrar procesos, abrir apps) llegan en el sprint S2,
junto con el diálogo de confirmación.
"""

import platform
import time
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
def listar_procesos(limite: int = 10, ordenar_por: str = "memoria") -> list[dict]:
    """Lista los programas abiertos con su uso de memoria RAM y de CPU, agrupando los procesos del mismo programa.

    Args:
      limite: Cuántos programas devolver.
      ordenar_por: "memoria" o "cpu": qué uso decide el orden, de mayor a menor.
    """
    limite = max(1, min(int(limite), 50))
    procesos = list(psutil.process_iter(["name", "memory_info"]))
    for p in procesos:  # primera lectura de CPU; la segunda, tras una pausa, da el uso real
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(1)
    nucleos = psutil.cpu_count() or 1
    agrupados: dict[str, dict] = {}
    for p in procesos:
        try:
            cpu = p.cpu_percent(None) / nucleos  # % del total de la PC, no de un núcleo
        except psutil.Error:
            continue
        mem = p.info.get("memory_info")
        nombre = (p.info.get("name") or "?").removesuffix(".exe")
        if nombre.lower() in {"system idle process", "idle"}:
            continue
        g = agrupados.setdefault(
            nombre, {"programa": nombre, "memoria_mb": 0.0, "cpu_porcentaje": 0.0}
        )
        g["memoria_mb"] += mem.rss / 1_048_576 if mem else 0
        g["cpu_porcentaje"] += cpu
    clave = "cpu_porcentaje" if str(ordenar_por).lower().startswith("cpu") else "memoria_mb"
    orden = sorted(agrupados.values(), key=lambda g: g[clave], reverse=True)[:limite]
    return [
        {**g, "memoria_mb": round(g["memoria_mb"]), "cpu_porcentaje": round(g["cpu_porcentaje"], 1)}
        for g in orden
    ]


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
