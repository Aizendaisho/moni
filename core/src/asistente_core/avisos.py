"""Avisos de Moni que llegan sin que el usuario pregunte (por ejemplo, "terminé el resumen").

Cualquier hilo puede llamar a publicar(); el núcleo (main.py) los reparte a todas las ventanas
conectadas y los guarda en la conversación actual.
"""

import asyncio
import logging
import threading

log = logging.getLogger("moni.avisos")

_loop: asyncio.AbstractEventLoop | None = None
_cola: asyncio.Queue | None = None
_pendientes: list[dict] = []
_lock = threading.Lock()


def configurar(loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
    global _loop, _cola
    with _lock:
        _loop, _cola = loop, asyncio.Queue()
        for a in _pendientes:
            _cola.put_nowait(a)
        _pendientes.clear()
    return _cola


def publicar(texto: str, **datos) -> None:
    aviso = {"text": texto, **datos}
    with _lock:
        if _loop is None or _cola is None or _loop.is_closed():
            _pendientes.append(aviso)
            return
        _loop.call_soon_threadsafe(_cola.put_nowait, aviso)
    log.info("Aviso: %s", texto[:80])
