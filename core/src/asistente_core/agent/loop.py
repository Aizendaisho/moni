"""Bucle del agente: el modelo responde o pide usar herramientas; el núcleo las ejecuta
(respetando los permisos) y le devuelve el resultado hasta que haya una respuesta final.

Produce eventos para la interfaz:
  {"type": "token", "text": ...}                     fragmento de la respuesta
  {"type": "tool", "name", "label", "status": "start"|"end", "ok": bool}
y al final devuelve, vía `turno.nuevos`, los mensajes que hay que guardar en el historial.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from ..permissions.policy import Nivel
from ..tools.registry import REGISTRO, esquemas
from .llm import chat_stream

log = logging.getLogger("moni.agente")

MAX_PASOS = 5  # rondas de herramientas por mensaje, para que nunca entre en bucle infinito


@dataclass
class Turno:
    """Resultado de un turno: los mensajes nuevos (asistente y herramientas) en orden."""

    nuevos: list[dict] = field(default_factory=list)


def _arg_dict(arguments: Any) -> dict:
    if isinstance(arguments, dict):
        return arguments
    try:
        return json.loads(arguments or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


async def ejecutar_herramienta(nombre: str, argumentos: dict) -> tuple[bool, str]:
    """Ejecuta una herramienta registrada y devuelve (ok, resultado en texto)."""
    h = REGISTRO.get(nombre)
    if h is None:
        return False, f"La herramienta '{nombre}' no existe."
    if h.nivel is Nivel.PROHIBIDO:
        return False, "Esta acción no está permitida."
    if h.nivel is Nivel.CONFIRMAR:
        # El diálogo de confirmación llega en S2; hasta entonces no se ejecuta.
        return False, "Esta acción necesita confirmación del usuario y aún no está disponible."
    try:
        resultado = await asyncio.to_thread(h.funcion, **argumentos)
    except TypeError as exc:
        return False, f"Argumentos inválidos: {exc}"
    except Exception as exc:
        log.exception("Falló la herramienta %s", nombre)
        return False, f"Error al ejecutar: {exc}"
    texto = resultado if isinstance(resultado, str) else json.dumps(resultado, ensure_ascii=False)
    return True, texto


async def responder(
    mensajes: list[dict],
    turno: Turno,
    stream: Callable[[list[dict], list[dict]], AsyncIterator[Any]] = chat_stream,
) -> AsyncIterator[dict]:
    """Corre el bucle para el último mensaje del usuario en `mensajes`."""
    contexto = list(mensajes)
    for _ in range(MAX_PASOS):
        texto, llamadas, empezo = "", [], False
        async for part in stream(contexto, esquemas()):
            msg = part.message
            if msg.tool_calls:
                llamadas.extend(msg.tool_calls)
            fragmento = msg.content or ""
            if not empezo:
                fragmento = fragmento.lstrip()
            if fragmento:
                empezo = True
                texto += fragmento
                yield {"type": "token", "text": fragmento}

        asistente: dict = {"role": "assistant", "content": texto}
        if llamadas:
            asistente["tool_calls"] = [
                {
                    "function": {
                        "name": c.function.name,
                        "arguments": _arg_dict(c.function.arguments),
                    }
                }
                for c in llamadas
            ]
        contexto.append(asistente)
        turno.nuevos.append(asistente)
        if not llamadas:
            return

        for c in llamadas:
            nombre, args = c.function.name, _arg_dict(c.function.arguments)
            etiqueta = REGISTRO[nombre].etiqueta if nombre in REGISTRO else nombre
            yield {"type": "tool", "name": nombre, "label": etiqueta, "status": "start"}
            ok, resultado = await ejecutar_herramienta(nombre, args)
            log.info("Herramienta %s(%s) -> %s", nombre, args, "ok" if ok else resultado)
            yield {"type": "tool", "name": nombre, "label": etiqueta, "status": "end", "ok": ok}
            resp = {"role": "tool", "tool_name": nombre, "content": resultado}
            contexto.append(resp)
            turno.nuevos.append(resp)

    aviso = "Me enredé usando herramientas y no pude terminar. ¿Me lo pides de otra forma?"
    turno.nuevos.append({"role": "assistant", "content": aviso})
    yield {"type": "token", "text": aviso}
