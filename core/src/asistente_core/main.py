"""Servidor del núcleo: expone /health y un WebSocket /ws que la app (Tauri) y el avatar
(Godot) usan para hablar con Moni.

Protocolo (JSON):
  app → núcleo   {"type": "chat", "text": ...}         mensaje del usuario
                 {"type": "new_conversation"}          empezar de cero
  núcleo → app   {"type": "history", "messages": [...]} al conectar o al crear conversación
                 {"type": "token", "text": ...}         fragmento de respuesta
                 {"type": "tool", ...}                  Moni usa una herramienta
                 {"type": "done"} / {"type": "error", "message": ...}

Arranque:  uv run asistente-core
"""

import logging

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import tools  # noqa: F401 - registra las herramientas
from .agent.loop import Turno, responder
from .agent.prompt import mensaje_sistema
from .config import settings
from .memory.historial import Historial

log = logging.getLogger("moni")
app = FastAPI(title="Moni · núcleo", version="0.2.0")
historial = Historial(settings.data_dir / "moni.db")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "model": settings.llm_model}


async def _enviar_historial(ws: WebSocket, conv: int) -> None:
    await ws.send_json(
        {"type": "history", "conversation_id": conv, "messages": historial.visibles(conv)}
    )


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conv = historial.ultima()
    await _enviar_historial(ws, conv)
    try:
        while True:
            msg = await ws.receive_json()
            tipo = msg.get("type")
            if tipo == "new_conversation":
                conv = historial.nueva()
                await _enviar_historial(ws, conv)
                continue
            if tipo != "chat":
                continue

            usuario = {"role": "user", "content": str(msg.get("text", ""))}
            historial.agregar(conv, usuario)
            contexto = [mensaje_sistema(), *historial.mensajes(conv, settings.history_limit)]
            turno = Turno()
            try:
                async for evento in responder(contexto, turno):
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
        log.info("Ventana desconectada")


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
