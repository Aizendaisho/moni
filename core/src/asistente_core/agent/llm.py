"""Cliente del LLM local (Ollama). En S1 se añade aquí el bucle de herramientas (tool calling)."""

from collections.abc import AsyncIterator

from ollama import AsyncClient

from ..config import settings

_client = AsyncClient(host=settings.ollama_host)


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Envía la conversación al modelo y devuelve la respuesta por fragmentos."""
    stream = await _client.chat(
        model=settings.llm_model,
        messages=messages,
        stream=True,
        think=settings.llm_think,
    )
    async for part in stream:
        text = part["message"]["content"]
        if text:
            yield text
