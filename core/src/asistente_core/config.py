"""Configuración del núcleo. Se puede sobrescribir con variables de entorno ASISTENTE_*
o con un archivo core/.env (ver .env.example)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASISTENTE_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"  # solo local: nunca exponer a la red
    port: int = 8765

    ollama_host: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:4b-instruct"  # responde directo, sin fase de razonamiento
    llm_think: bool = False  # True solo con modelos que razonan (p. ej. qwen3:4b)
    vision_model: str = "moondream"
    embed_model: str = "nomic-embed-text"

    whisper_model: str = "small"
    piper_voice: str = "es_MX-ald-medium"

    data_dir: str = "../data"  # historial, memoria y bitácora (ignorado por git)

    system_prompt: str = (
        "Te llamas Moni. Eres la asistente personal que vive en la computadora del usuario. "
        "Respondes en español, de forma breve y clara. "
        "Antes de cualquier acción que cierre, borre o ejecute algo, pides confirmación."
    )


settings = Settings()
