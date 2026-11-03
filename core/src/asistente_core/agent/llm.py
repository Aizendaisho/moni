"""Cliente del LLM local (Ollama).

Modelo por defecto: qwen3:4b-instruct (Qwen3-4B-Instruct-2507), que responde directo y
sabe usar herramientas. La etiqueta qwen3:4b apunta a la variante "Thinking", que siempre
razona antes de contestar (~700 tokens extra, unos 35 s en una RTX 3050 Ti).
"""

from collections.abc import AsyncIterator
from typing import Any

from ollama import AsyncClient

from ..config import settings

_client = AsyncClient(host=settings.ollama_host)


async def chat_stream(messages: list[dict], tools: list[dict]) -> AsyncIterator[Any]:
    """Envía la conversación al modelo y devuelve los fragmentos tal como llegan.
    Cada fragmento tiene .message.content (texto) y/o .message.tool_calls."""
    extra: dict[str, Any] = {"think": True} if settings.llm_think else {}
    if tools:
        extra["tools"] = tools
    stream = await _client.chat(
        model=settings.llm_model,
        messages=messages,
        stream=True,
        options={"num_ctx": settings.llm_num_ctx},
        **extra,
    )
    async for part in stream:
        yield part
