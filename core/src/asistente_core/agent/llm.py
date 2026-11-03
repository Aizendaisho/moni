"""Cliente del LLM local (Ollama). En S1 se añade aquí el bucle de herramientas (tool calling)."""

import re
from collections.abc import AsyncIterator

from ollama import AsyncClient

from ..config import settings

_client = AsyncClient(host=settings.ollama_host)
_THINK_TAGS = re.compile(r"</?think>")


def _preparar(messages: list[dict]) -> list[dict]:
    """Con llm_think apagado se usa el interruptor "/no_think" de Qwen3: el modelo se salta
    el razonamiento y responde directo. (Pasar think=False a Ollama hace que algunos modelos
    escriban el razonamiento dentro de la respuesta, por eso no se usa)."""
    if settings.llm_think or not messages or messages[-1].get("role") != "user":
        return messages
    ultimo = {**messages[-1], "content": f"{messages[-1]['content']} /no_think"}
    return [*messages[:-1], ultimo]


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Envía la conversación al modelo y devuelve solo la respuesta final, por fragmentos.
    El razonamiento (si lo hay) llega aparte en message.thinking y no se muestra."""
    stream = await _client.chat(
        model=settings.llm_model,
        messages=_preparar(messages),
        stream=True,
        think=True,
    )
    empezo = False
    async for part in stream:
        text = _THINK_TAGS.sub("", part["message"]["content"] or "")
        if not empezo:
            text = text.lstrip()  # quita saltos de línea iniciales
        if text:
            empezo = True
            yield text
