"""Servidor del núcleo: expone /health y un WebSocket /ws que la app (Tauri) y el avatar
(Godot) usan para hablar con Moni.

Protocolo (JSON):
  app → núcleo   {"type": "chat", "text": ...}               mensaje del usuario
                 {"type": "new_conversation"}                empezar de cero
                 {"type": "confirm_reply", "id", "ok": bool} respuesta a una confirmación
  núcleo → app   {"type": "history", "messages": [...]}      al conectar o al crear conversación
                 {"type": "token", "text": ...}               fragmento de respuesta
                 {"type": "tool", ...}                        Moni usa una herramienta
                 {"type": "confirm", "id", "question"}        pedir Sí/No antes de una acción
                 {"type": "confirm_closed", "id"}             la pregunta caducó (sin respuesta)
                 {"type": "done"} / {"type": "error", "message": ...}

Arranque:  uv run asistente-core
"""

import asyncio
import logging
import uuid

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import tools  # noqa: F401 - registra las herramientas
from .agent.loop import Turno, responder
from .agent.prompt import mensaje_sistema
from .config import settings
from .memory import bitacora
from .memory.historial import Historial

log = logging.getLogger("moni")
app = FastAPI(title="Moni · núcleo", version="0.3.0")
historial = Historial(settings.data_dir / "moni.db")
bitacora.usar(bitacora.Bitacora(settings.data_dir / "moni.db"))

ESPERA_CONFIRMACION = 60  # segundos; sin respuesta cuenta como "no"


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "model": settings.llm_model}


class Sesion:
    """Una ventana conectada. Lee mensajes en segundo plano para poder recibir la respuesta
    a una confirmación mientras Moni está a mitad de un turno."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.cola: asyncio.Queue[dict | None] = asyncio.Queue()
        self.pendientes: dict[str, asyncio.Future[bool]] = {}

    async def leer(self) -> None:
        try:
            while True:
                msg = await self.ws.receive_json()
                if msg.get("type") == "confirm_reply":
                    fut = self.pendientes.get(str(msg.get("id")))
                    if fut and not fut.done():
                        fut.set_result(bool(msg.get("ok")))
                else:
                    await self.cola.put(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            for fut in self.pendientes.values():
                if not fut.done():
                    fut.set_result(False)
            await self.cola.put(None)

    async def confirmar(self, pregunta: str) -> bool:
        cid = uuid.uuid4().hex[:8]
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.pendientes[cid] = fut
        await self.ws.send_json({"type": "confirm", "id": cid, "question": pregunta})
        try:
            return await asyncio.wait_for(fut, ESPERA_CONFIRMACION)
        except TimeoutError:
            await self.ws.send_json({"type": "confirm_closed", "id": cid})
            return False
        finally:
            self.pendientes.pop(cid, None)

    async def enviar_historial(self, conv: int) -> None:
        await self.ws.send_json(
            {"type": "history", "conversation_id": conv, "messages": historial.visibles(conv)}
        )


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    sesion = Sesion(ws)
    lector = asyncio.create_task(sesion.leer())
    conv = historial.ultima()
    try:
        await sesion.enviar_historial(conv)
        while (msg := await sesion.cola.get()) is not None:
            tipo = msg.get("type")
            if tipo == "new_conversation":
                conv = historial.nueva()
                await sesion.enviar_historial(conv)
                continue
            if tipo != "chat":
                continue

            historial.agregar(conv, {"role": "user", "content": str(msg.get("text", ""))})
            contexto = [mensaje_sistema(), *historial.mensajes(conv, settings.history_limit)]
            turno = Turno()
            try:
                async for evento in responder(contexto, turno, confirmar=sesion.confirmar):
                    await ws.send_json(evento)
                await ws.send_json({"type": "done"})
            except (WebSocketDisconnect, RuntimeError):
                raise  # la ventana se cerró a mitad de respuesta: no hay a quién avisar
            except Exception as exc:  # Ollama apagado, modelo sin descargar, etc.
                log.exception("Error al generar respuesta")
                await ws.send_json({"type": "error", "message": f"No pude responder: {exc}"})
            finally:
                for m in turno.nuevos:  # se guarda lo que alcanzó a generar
                    historial.agregar(conv, m)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        lector.cancel()
        log.info("Ventana desconectada")


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
