@echo off
REM Doble clic para instalar todo lo que necesita el proyecto.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
pause
