@echo off
REM Arranca solo el nucleo de Moni (util para reiniciarlo sin cerrar la app).
cd /d "%~dp0..\core"
title Moni - nucleo
uv run asistente-core
