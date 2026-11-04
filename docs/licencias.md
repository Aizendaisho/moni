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
| ddgs | búsqueda en internet | MIT |
| trafilatura | extraer texto de páginas | Apache-2.0 |
| httpx | descargas | BSD-3 |
| NumPy | búsqueda por similitud | BSD-3 |
| cryptography | cifrado de las copias | Apache-2.0 / BSD-3 |
| Supabase (servicio) | copia en la nube | Apache-2.0 (se puede autoalojar) |
| YARA-X | reglas de malware | BSD-3 |
| oletools | macros de Office | BSD-2 |
| pefile | revisar programas .exe | MIT |
| CIRCL hashlookup (servicio) | ¿es un archivo conocido? (solo el hash) | servicio público gratuito |
| MalwareBazaar de abuse.ch (servicio, opcional) | ¿es malware conocido? (solo el hash) | gratuito con clave |
| MITRE ATT&CK (datos, se descargan en la PC) | conocimiento de ataques | términos de uso de MITRE: uso libre con atribución |
| LOLBAS (datos, se descargan en la PC) | programas de Windows abusables | GPL-3.0 (no se incluye en el repo; sin los comandos de abuso) |
| Hayabusa 4.3.1 (se descarga en la PC) | revisar registros de eventos | AGPL-3.0; reglas DRL 1.1 |
| REA (rea-agents 6.8.0, se instala en la PC) | qué puede hacer un programa (estático) | MIT |
| Node.js 22+ (lo instala el usuario) | necesario para REA | MIT |
| Reglas YARA de la comunidad (opcional, `data/reglas-yara`) | más detecciones | según cada repo; signature-base usa DRL 1.1 |

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
