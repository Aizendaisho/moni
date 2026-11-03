# Asistente PC

Asistente personal de escritorio, 100 % local y open source: controla la computadora con permisos por niveles, conversa por voz, tiene un avatar 2D y puede ver por la cámara.

> Estado: **S0 · Fundaciones**. El seguimiento de sprints está en el [Roadmap del Asistente](https://claude.ai/artifact/LvaxDFJoLqLg2sWaXYnGbC).

## Estructura

```
asistente-pc/
├── app/        App de escritorio: Tauri 2 + React + TypeScript + Tailwind
├── core/       Núcleo en Python: LLM, herramientas, permisos, voz, visión, memoria, MCP
├── avatar/     Avatar 2D en Godot 4
├── scripts/    setup (instala todo), dev (arranca en modo desarrollo), descarga de modelos
├── docs/       Arquitectura y licencias
└── data/       Modelos, historial y memoria locales (no se sube a git)
```

## Instalación (Windows)

1. Clona el repo o descomprímelo en una carpeta sin espacios raros, por ejemplo `C:\dev\asistente-pc`.
2. Doble clic en `scripts\setup.bat`. Instala programas con winget, dependencias de Python y Node, y descarga los modelos (unos 15 GB en total; tarda).
3. Abre una terminal nueva y ejecuta `scripts\dev.bat`.

`scripts\setup.bat -SinModelos` instala todo menos los modelos de IA.

## Hardware de referencia

Ryzen 5 5600H · 16 GB RAM · RTX 3050 Ti Laptop (4 GB VRAM). Con 4 GB de VRAM, el LLM (Qwen3 4B) vive en la GPU, la voz y MediaPipe en la CPU, y el modelo de visión se carga solo cuando hace falta. Detalles en [docs/arquitectura.md](docs/arquitectura.md).

## Licencia

[MIT](LICENSE). Las licencias de cada dependencia y modelo están en [docs/licencias.md](docs/licencias.md).
