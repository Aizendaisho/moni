"""Uso de internet (sprint S2).

Qué se puede medir sin permisos de administrador:
- La velocidad total de bajada y subida de la PC en este momento.
- Qué programas tienen conexiones abiertas a internet y cuántas.

Lo que NO se puede medir sin administrador es cuántos bytes exactos usa cada programa:
Windows solo lo expone mediante ETW (lo que usa el Monitor de recursos), que requiere
privilegios elevados. Ver docs/arquitectura.md, sección "Red por programa".
"""

import ipaddress
import time

import psutil

from ..permissions.policy import Nivel
from .registry import herramienta


def _es_internet(ip: str) -> bool:
    try:
        d = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return not (d.is_loopback or d.is_private or d.is_link_local or d.is_multicast)


def _velocidad(segundos: float = 2.0) -> dict:
    a = psutil.net_io_counters()
    time.sleep(segundos)
    b = psutil.net_io_counters()

    def kbs(n: int) -> float:
        return round(n / segundos / 1024, 1)

    return {
        "bajada_kb_s": kbs(b.bytes_recv - a.bytes_recv),
        "subida_kb_s": kbs(b.bytes_sent - a.bytes_sent),
        "bajado_desde_encendido_mb": round(b.bytes_recv / 1_048_576),
        "subido_desde_encendido_mb": round(b.bytes_sent / 1_048_576),
    }


def _programas_conectados(limite: int) -> list[dict]:
    conteo: dict[int, int] = {}
    try:
        conexiones = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:  # en algunos sistemas requiere administrador
        conexiones = []
    for c in conexiones:
        if c.pid and c.raddr and c.status == psutil.CONN_ESTABLISHED and _es_internet(c.raddr.ip):
            conteo[c.pid] = conteo.get(c.pid, 0) + 1
    por_programa: dict[str, int] = {}
    for pid, n in conteo.items():
        try:
            nombre = psutil.Process(pid).name().removesuffix(".exe")
        except psutil.Error:
            continue
        por_programa[nombre] = por_programa.get(nombre, 0) + n
    orden = sorted(por_programa.items(), key=lambda x: x[1], reverse=True)[:limite]
    return [{"programa": n, "conexiones_a_internet": c} for n, c in orden]


@herramienta(Nivel.LIBRE, etiqueta="Midiendo el internet")
def uso_de_internet(limite: int = 8) -> dict:
    """Mide el uso de internet: velocidad actual de bajada y subida de toda la PC, y qué programas tienen más conexiones abiertas a internet ahora mismo.

    Args:
      limite: Cuántos programas incluir en la lista.
    """
    return {
        **_velocidad(),
        "programas_con_mas_conexiones": _programas_conectados(max(1, min(int(limite), 20))),
        "nota": (
            "La velocidad es de toda la PC. Por programa solo se sabe cuántas conexiones "
            "tiene abiertas, no cuántos MB usa cada uno; más conexiones suele indicar más "
            "actividad, pero no siempre. Medirlo exacto requiere permisos de administrador."
        ),
    }
