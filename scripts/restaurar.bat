@echo off
REM Restaura la memoria de Moni desde una copia de seguridad (cierra antes el nucleo).
cd /d "%~dp0..\core"
uv run --extra todo python ..\scripts\restaurar.py
pause
