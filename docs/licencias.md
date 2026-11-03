# Licencias de dependencias y modelos

Antes de añadir algo al proyecto, se registra aquí. Si la licencia no es open source (o es de "pesos abiertos" con restricciones), se marca y se busca alternativa.

## Programas y librerías

| Componente | Uso | Licencia |
|---|---|---|
| Tauri | app de escritorio | MIT / Apache-2.0 |
| React | interfaz | MIT |
| Vite | build del frontend | MIT |
| Tailwind CSS | estilos | MIT |
| Godot 4 | avatar | MIT |
| Ollama | servidor de modelos | MIT |
| FastAPI / Uvicorn | servidor del núcleo | MIT / BSD-3 |
| psutil | procesos | BSD-3 |
| pywinauto | automatizar apps de Windows | BSD-3 |
| openWakeWord | palabra de activación | Apache-2.0 (código) |
| Silero VAD | detección de voz | MIT |
| faster-whisper | voz a texto | MIT |
| Piper | texto a voz | revisar: versiones recientes (piper1-gpl) usan **GPL-3.0** |
| OpenCV | cámara | Apache-2.0 |
| MediaPipe | rostro y gestos | Apache-2.0 |
| sqlite-vec | memoria vectorial | MIT / Apache-2.0 |
| MCP SDK | integraciones | MIT |
| Playwright | navegador | Apache-2.0 |

## Modelos

| Modelo | Uso | Licencia |
|---|---|---|
| Qwen3 4B | LLM | Apache-2.0 |
| Moondream 2 | visión | Apache-2.0 |
| nomic-embed-text | embeddings | Apache-2.0 |
| Whisper small (faster-whisper) | voz a texto | MIT |
| Voz Piper es_MX-ald-medium | voz | revisar en su MODEL_CARD |
| Modelos base de openWakeWord | palabra de activación | CC BY-NC-SA 4.0 (no comercial) |

## Pendientes

- **Piper:** si el proyecto usa MIT, una dependencia GPL-3.0 obliga a publicar el instalador también bajo GPL. Alternativa: Kokoro (Apache-2.0).
- **openWakeWord:** los modelos preentrenados son no comerciales. Para uso personal está bien; para distribuir, entrenar una palabra propia.
