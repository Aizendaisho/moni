import os

# En las pruebas no se cargan los modelos de voz reales al arrancar el núcleo.
os.environ.setdefault("ASISTENTE_VOICE_PRELOAD", "false")
