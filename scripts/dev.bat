@echo off
REM Arranca el nucleo (Python) y la app de escritorio en modo desarrollo.
set "RAIZ=%~dp0.."
start "Asistente - nucleo" /D "%RAIZ%\core" cmd /k uv run asistente-core
cd /d "%RAIZ%\app"
npm run tauri dev
