@echo off
title Moni - prueba de voz
cd /d "%~dp0..\core"
uv run --extra todo python ..\scripts\probar_voz.py
echo.
echo Puedes cerrar esta ventana.
pause >nul
