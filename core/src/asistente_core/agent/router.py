"""Decide si un mensaje necesita información de internet antes de responder.

Los modelos pequeños (4B) usan mal sus herramientas cuando deben decidir solos: responden
"de memoria", inventan datos y hasta copian el formato de una cita anterior. En cambio,
responden bien a una pregunta cerrada y aislada. Por eso el núcleo hace esta consulta corta
(sí/no, en JSON) antes de cada mensaje y, si hace falta, investiga por su cuenta.
"""

import json
import logging

from ollama import AsyncClient

from ..config import settings

log = logging.getLogger("moni.router")
_client = AsyncClient(host=settings.ollama_host)

_INSTRUCCIONES = """Eres un clasificador. Decide si, para responder bien el mensaje del usuario, \
hace falta buscar información en internet.

SÍ hace falta (internet = true) para: hechos, datos, fechas, nombres, lugares, personas, \
versiones de programas, noticias, precios, clima, resultados deportivos, definiciones técnicas \
precisas, o cualquier dato que pueda haber cambiado o que no se sepa con total certeza.

NO hace falta (internet = false) para: saludos y charla, agradecimientos, opiniones, preguntas \
sobre esta computadora (procesos, programas abiertos, memoria, CPU, batería, internet de la PC, \
fecha u hora), pedir abrir o cerrar programas, preguntar qué ha hecho el asistente, redactar, \
resumir o traducir un texto que el usuario da, cálculos simples.

Responde solo con JSON: {"internet": true} o {"internet": false}."""

_FORMATO = {
    "type": "object",
    "properties": {"internet": {"type": "boolean"}},
    "required": ["internet"],
}


async def necesita_internet(mensaje: str, anterior: str = "") -> bool:
    """True si conviene investigar en internet antes de responder. Ante cualquier error, False."""
    contenido = (
        mensaje
        if not anterior
        else f"(Mensaje anterior del asistente: {anterior[:300]})\n\n{mensaje}"
    )
    try:
        r = await _client.chat(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _INSTRUCCIONES},
                {"role": "user", "content": contenido},
            ],
            format=_FORMATO,
            # mismo num_ctx que el chat: si cambia, Ollama recarga el modelo (lento)
            options={"temperature": 0, "num_predict": 20, "num_ctx": settings.llm_num_ctx},
        )
        decision = bool(json.loads(r.message.content or "{}").get("internet", False))
    except Exception:
        log.exception("Falló el clasificador de internet")
        return False
    log.info("¿Necesita internet? %s -> %s", mensaje[:80], decision)
    return decision
