"""Servidor del núcleo: expone /health y un WebSocket /ws que la app (Tauri) y el avatar
(Godot) usan para hablar con Moni.

Protocolo (JSON):
  app → núcleo   {"type": "chat", "text": ...}               mensaje del usuario
                 {"type": "new_conversation"}                empezar de cero
                 {"type": "confirm_reply", "id", "ok": bool} respuesta a una confirmación
  núcleo → app   {"type": "history", "messages": [...]}      al conectar o al crear conversación
                 {"type": "token", "text": ...}               fragmento de respuesta
                 {"type": "tool", ...}                        Moni usa una herramienta
                 {"type": "memory", "count": n}               encontró n recuerdos relevantes
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
from .agent.loop import Turno, ejecutar_herramienta, responder
from .agent.prompt import mensaje_recuerdos, mensaje_sistema
from .agent.router import necesita_internet
from .config import settings
from .memory import bitacora, conocimiento
from .memory.historial import Historial

log = logging.getLogger("moni")
app = FastAPI(title="Moni · núcleo", version="0.4.0")
historial = Historial(settings.data_dir / "moni.db")
bitacora.usar(bitacora.Bitacora(settings.data_dir / "moni.db"))
conocimiento.usar(
    conocimiento.Conocimiento(
        settings.data_dir / "moni.db",
        conocimiento.embedder_ollama(settings.ollama_host, settings.embed_model),
    )
)

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


async def _recordar(texto: str) -> list[dict]:
    """Recuerdos relevantes para el mensaje (vacío si no hay o si la memoria falla)."""
    memoria = conocimiento.actual()
    if memoria is None or len(texto.strip()) < 4:
        return []
    try:
        return await asyncio.to_thread(memoria.buscar, texto, settings.memory_auto_limit)
    except Exception:
        log.exception("No se pudo consultar la memoria")
        return []


def _ultima_respuesta(mensajes: list[dict]) -> str:
    for m in reversed(mensajes[:-1]):
        if m["role"] == "assistant" and m.get("content"):
            return m["content"]
    return ""


async def _investigar_antes(ws: WebSocket, pregunta: str) -> list[dict]:
    """Ejecuta `investigar` y lo devuelve como si Moni hubiera llamado la herramienta."""
    args = {"pregunta": pregunta}
    await ws.send_json(
        {
            "type": "tool",
            "name": "investigar",
            "label": "Investigando en internet",
            "status": "start",
        }
    )
    ok, resultado = await ejecutar_herramienta("investigar", args)
    await ws.send_json(
        {
            "type": "tool",
            "name": "investigar",
            "label": "Investigando en internet",
            "status": "end",
            "ok": ok,
        }
    )
    if not ok:
        resultado = (
            f"No se pudo investigar en internet: {resultado}. Díselo al usuario con honestidad."
        )
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "investigar", "arguments": args}}],
        },
        {"role": "tool", "tool_name": "investigar", "content": resultado},
    ]


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

            texto = str(msg.get("text", ""))
            historial.agregar(conv, {"role": "user", "content": texto})
            mensajes = historial.mensajes(conv, settings.history_limit)
            recuerdos = await _recordar(texto)
            extra = mensaje_recuerdos(recuerdos)
            # Los recuerdos van justo antes del último mensaje del usuario, donde más pesan.
            contexto = [
                mensaje_sistema(),
                *mensajes[:-1],
                *([extra] if extra else []),
                mensajes[-1],
            ]
            if recuerdos:
                await ws.send_json({"type": "memory", "count": len(recuerdos)})
            elif settings.auto_research and await necesita_internet(
                texto, _ultima_respuesta(mensajes)
            ):
                # Sin recuerdos y la pregunta necesita datos: el núcleo investiga por su cuenta
                # (el modelo pequeño a veces inventa en vez de usar la herramienta).
                previos = await _investigar_antes(ws, texto)
                contexto.extend(previos)
                for m in previos:
                    historial.agregar(conv, m)
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
