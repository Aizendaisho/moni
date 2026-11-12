"""Texto <-> voz: cortar la respuesta en frases mientras llega y limpiarla para leerla en voz alta,
y reconocer la palabra de activación en una transcripción."""

import re
import unicodedata

_FIN_FRASE = re.compile(r"(?<=[.!?…:;])\s+|\n+")


class Frases:
    """Recibe fragmentos de texto (tokens) y devuelve frases completas en cuanto se cierran,
    para empezar a hablar sin esperar a que termine la respuesta."""

    def __init__(self, minimo: int = 25):
        self.buffer = ""
        self.minimo = minimo  # no cortar frases muy cortas ("Sí.") para que suene natural

    def agregar(self, fragmento: str) -> list[str]:
        self.buffer += fragmento
        salida: list[str] = []
        while True:
            m = None
            for cand in _FIN_FRASE.finditer(self.buffer):
                if cand.start() >= self.minimo or "\n" in cand.group():
                    m = cand
                    break
            if m is None:
                break
            frase, self.buffer = self.buffer[: m.start()], self.buffer[m.end() :]
            if frase.strip():
                salida.append(frase.strip())
        return salida

    def terminar(self) -> list[str]:
        resto, self.buffer = self.buffer.strip(), ""
        return [resto] if resto else []


def limpiar_para_voz(texto: str) -> str:
    """Quita lo que no se debe leer en voz alta: Markdown, enlaces, emojis, rutas largas."""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)  # [texto](url) -> texto
    t = re.sub(r"https?://\S+", "el enlace", t)
    t = re.sub(r"[A-Za-z]:\\\S+", "esa carpeta", t)  # C:\Users\...
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"^\s*#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.MULTILINE)
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("So", "Cs") and c != "\ufe0f")
    return re.sub(r"\s+", " ", t).strip()


# Cómo transcribe Whisper "Moni" a veces.
_ACTIVACION = r"(?:moni|mony|monni|monik|moonie|money|mon[ií]a?|m[oó]ni)"


def activacion(transcripcion: str) -> tuple[bool, str]:
    """¿La frase empieza llamando a Moni ("Moni", "Oye Moni", "Hola Moni, ...")? Devuelve
    (sí/no, lo que dijo después del nombre)."""
    t = transcripcion.strip().lower()
    t = re.sub(r"^[¿¡\s,.]+", "", t)
    m = re.match(
        rf"^(?:(?:oye|hey|hola|ey|eh|ok|okay|okey)[\s,]+)?{_ACTIVACION}\b[\s,.!?:]*(.*)$", t
    )
    if not m:
        return False, ""
    # devolvemos el resto con las mayúsculas originales
    resto = transcripcion.strip()[len(transcripcion.strip()) - len(m[1]) :] if m[1] else ""
    return True, resto.strip()
