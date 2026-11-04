"""Copias de seguridad desde el chat: hacer una ahora y consultar el estado."""

from ..memory import respaldo
from ..permissions.policy import Nivel
from .registry import herramienta

_SIN_CONFIGURAR = (
    "Las copias de seguridad no están activadas: falta la frase secreta "
    "(ASISTENTE_BACKUP_PASSPHRASE en core/.env)."
)


@herramienta(Nivel.LIBRE, etiqueta="Haciendo copia de seguridad")
def hacer_copia_de_seguridad() -> str:
    """Hace ahora mismo una copia de seguridad cifrada de toda la memoria de Moni (conversaciones, lo aprendido y la bitácora) en la carpeta local y en la nube."""
    r = respaldo.actual()
    if r is None:
        raise ValueError(_SIN_CONFIGURAR)
    res = r.hacer()
    texto = f"Copia {res.nombre} ({res.tamano_kb} KB) guardada en: {', '.join(res.destinos_ok) or 'ningún destino'}."
    if res.errores:
        texto += " Fallaron: " + "; ".join(res.errores)
    if res.borradas:
        texto += f" Se borraron {res.borradas} copias antiguas."
    return texto


@herramienta(Nivel.LIBRE, etiqueta="Revisando las copias")
def estado_copias() -> dict:
    """Dice cuándo fue la última copia de seguridad de la memoria de Moni y dónde está guardada."""
    r = respaldo.actual()
    if r is None:
        return {"activadas": False, "detalle": _SIN_CONFIGURAR}
    fecha, por_destino = r.ultima()
    return {
        "activadas": True,
        "ultima_copia": fecha.strftime("%d/%m/%Y %I:%M %p") if fecha else "ninguna todavía",
        "por_destino": por_destino,
    }
