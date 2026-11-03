# core — núcleo del asistente

Servicio local en Python (FastAPI + WebSocket) que conecta el LLM, las herramientas, la voz, la visión y la memoria.

```powershell
uv sync --extra todo     # instala todo (lo hace scripts\setup.ps1)
uv run asistente-core    # arranca en ws://127.0.0.1:8765/ws
uv run pytest            # pruebas
```

Los extras se agrupan por sprint: `voz` (S3), `vision` (S5), `memoria` (S6), `integraciones` (S7) y `todo`.
