@echo off
REM Arranca Moni en modo desarrollo: el nucleo (si no esta corriendo ya) y la app de escritorio.
REM Deja abierta esta ventana: si la cierras, la app pierde su servidor de desarrollo.
set "RAIZ=%~dp0.."
title Moni - app (no cerrar)
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if errorlevel 1 start "Moni - nucleo" /D "%RAIZ%\core" cmd /k uv run asistente-core
cd /d "%RAIZ%\app"
npm run tauri dev
