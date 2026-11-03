"""Niveles de permiso de las herramientas (sprint S2).

Toda herramienta declara su nivel. El núcleo ejecuta directamente las de nivel LIBRE y
pide confirmación al usuario (por voz o con un clic) antes de las de nivel CONFIRMAR.
"""

from enum import Enum


class Nivel(str, Enum):
    LIBRE = "libre"  # leer información: listar procesos, ver hora, describir pantalla
    CONFIRMAR = "confirmar"  # cerrar procesos, borrar archivos, ejecutar código, enviar mensajes
    PROHIBIDO = "prohibido"  # nunca se ejecuta (p. ej. cambiar configuración de seguridad)


def requiere_confirmacion(nivel: Nivel) -> bool:
    return nivel is Nivel.CONFIRMAR


def esta_permitido(nivel: Nivel) -> bool:
    return nivel is not Nivel.PROHIBIDO
