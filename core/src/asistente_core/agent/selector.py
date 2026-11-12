"""Qué herramientas se le ofrecen al modelo en cada mensaje.

Con más de 30 herramientas, sus descripciones ocupan ~4600 tokens: no caben junto con la
conversación en el contexto de 6144 tokens del modelo pequeño (y además lo confunden).
Por eso en cada mensaje se ofrecen solo:
  1. BASE: las de uso general, siempre.
  2. Las que nombra la skill activa en sus pasos.
  3. Si no hay skill: las MAS_PARECIDAS herramientas cuya descripción más se parece al mensaje
     (embeddings, calculados una vez).
  4. Las que ya se usaron en la conversación reciente (para seguir lo que se estaba haciendo).
"""

import logging
import re

import numpy as np

from ..memory.conocimiento import Embedder
from ..permissions.policy import Nivel
from ..tools.registry import REGISTRO

log = logging.getLogger("moni.selector")

BASE = (
    "fecha_hora",
    "estado_sistema",
    "listar_procesos",
    "abrir_programa",
    "cerrar_programa",
    "investigar",
    "recordar",
    "mis_skills",
)
MAS_PARECIDAS = 6


class Selector:
    def __init__(self, embedder: Embedder | None):
        self.embedder = embedder
        self._nombres: list[str] = []
        self._vectores: np.ndarray | None = None

    def _indice(self) -> None:
        nombres = sorted(n for n, h in REGISTRO.items() if h.nivel is not Nivel.PROHIBIDO)
        if nombres == self._nombres and self._vectores is not None:
            return
        textos = [
            f"{n.replace('_', ' ')}: {REGISTRO[n].esquema['function'].get('description', '')}"
            for n in nombres
        ]
        m = np.asarray(self.embedder(textos, "documento"), dtype=np.float32)
        self._vectores = m / np.linalg.norm(m, axis=1, keepdims=True)
        self._nombres = nombres

    def parecidas(self, mensaje: str, n: int = MAS_PARECIDAS) -> list[str]:
        if self.embedder is None or not mensaje.strip():
            return []
        try:
            self._indice()
            q = np.asarray(self.embedder([mensaje], "consulta")[0], dtype=np.float32)
            sims = self._vectores @ (q / np.linalg.norm(q))
        except Exception:
            log.exception("No se pudieron comparar las herramientas")
            return []
        orden = np.argsort(-sims)
        return [self._nombres[i] for i in orden[: n + len(BASE)] if self._nombres[i] not in BASE][
            :n
        ]

    def elegir(
        self, mensaje: str, pasos_skill: str | None = None, usadas: list[str] | None = None
    ) -> list[str]:
        disponibles = {n for n, h in REGISTRO.items() if h.nivel is not Nivel.PROHIBIDO}
        elegidas: list[str] = [n for n in BASE if n in disponibles]
        if pasos_skill:
            elegidas += [n for n in sorted(disponibles) if re.search(rf"\b{n}\b", pasos_skill)]
        else:
            elegidas += self.parecidas(mensaje)
        elegidas += [n for n in usadas or [] if n in disponibles]
        return list(dict.fromkeys(elegidas))


def esquemas_de(nombres: list[str]) -> list[dict]:
    return [REGISTRO[n].esquema for n in nombres if n in REGISTRO]


def usadas_en(mensajes: list[dict], ultimos: int = 6) -> list[str]:
    """Herramientas llamadas en los últimos mensajes de la conversación."""
    nombres: list[str] = []
    for m in mensajes[-ultimos:]:
        for c in m.get("tool_calls") or []:
            nombre = (c.get("function") or {}).get("name")
            if nombre:
                nombres.append(nombre)
    return nombres
