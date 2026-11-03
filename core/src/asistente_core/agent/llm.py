"""Cliente del LLM local (Ollama). En S1 se añade aquí el bucle de herramientas (tool calling).

Modelo por defecto: qwen3:4b-instruct (Qwen3-4B-Instruct-2507), que responde directo.
La etiqueta qwen3:4b apunta a la variante "Thinking", que siempre razona antes de contestar
(~700 tokens extra, unos 35 s en una RTX 3050 Ti) aunque se le pida que no lo haga.
"""

from collections.abc import AsyncIterator

from ollama import AsyncClient

from ..config import settings

_client = AsyncClient(host=settings.ollama_host)


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Envía la conversación al modelo y devuelve solo la respuesta final, por fragmentos.
    Si llm_think está activo y el modelo razona, el razonamiento llega aparte
    (message.thinking) y no se muestra."""
    extra = {"think": True} if settings.llm_think else {}
    stream = await _client.chat(model=settings.llm_model, messages=messages, stream=True, **extra)
    empezo = False
    async for part in stream:
        text = part["message"]["content"] or ""
        if not empezo:
            text = text.lstrip()  # quita saltos de línea iniciales
        if text:
            empezo = True
            yield text
