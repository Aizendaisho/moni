"""Servidor del núcleo: expone /health y un WebSocket /ws que la app (Tauri) y el avatar
(Godot) usan para hablar con el asistente.

Arranque:  uv run asistente-core
"""

import logging

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .agent.llm import stream_chat
from .config import settings

log = logging.getLogger("asistente")
app = FastAPI(title="Asistente · núcleo", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "model": settings.llm_model}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    history: list[dict] = [{"role": "system", "content": settings.system_prompt}]
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "chat":
                continue
            history.append({"role": "user", "content": str(msg.get("text", ""))})
            reply = ""
            try:
                async for token in stream_chat(history):
                    reply += token
                    await ws.send_json({"type": "token", "text": token})
                history.append({"role": "assistant", "content": reply})
                await ws.send_json({"type": "done"})
            except Exception as exc:  # Ollama apagado, modelo sin descargar, etc.
                log.exception("Error al generar respuesta")
                await ws.send_json({"type": "error", "message": f"No pude responder: {exc}"})
    except WebSocketDisconnect:
        pass


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
