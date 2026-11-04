"""Configuración del núcleo. Se puede sobrescribir con variables de entorno ASISTENTE_*
o con un archivo core/.env (ver .env.example).

La personalidad de Moni no está aquí: está en agent/personalidad.md.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[3]  # carpeta asistente-pc/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASISTENTE_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"  # solo local: nunca exponer a la red
    port: int = 8765

    user_name: str = "Araldi"

    ollama_host: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:4b-instruct"  # responde directo, sin fase de razonamiento
    llm_think: bool = False  # True solo con modelos que razonan (p. ej. qwen3:4b)
    llm_num_ctx: int = 6144  # tokens de contexto; más contexto = más VRAM
    history_limit: int = 30  # mensajes del historial que se envían al modelo
    auto_research: bool = True  # el núcleo decide si investigar antes de responder
    memory_auto_limit: int = 4  # recuerdos que se añaden solos a cada mensaje
    web_region: str = "es-es"  # región para los resultados de búsqueda
    vision_model: str = "moondream"
    embed_model: str = "nomic-embed-text"

    whisper_model: str = "small"
    piper_voice: str = "es_MX-ald-medium"

    data_dir: Path = RAIZ / "data"  # historial, memoria y bitácora (ignorado por git)


settings = Settings()
