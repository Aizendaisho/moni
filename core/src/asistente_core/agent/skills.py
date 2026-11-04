"""Skills de Moni: instrucciones paso a paso para tareas concretas.

Cada skill es una carpeta con un SKILL.md:

    ---
    name: revisar-archivo
    title: Revisar un archivo
    description: Cuándo usarla, en una frase.
    examples:
      - ¿este archivo tiene virus?
      - revisa el pdf que me llegó
    ---
    Pasos que Moni debe seguir (texto libre).

Hay dos lugares:
  - core/src/asistente_core/skills/  las que vienen con Moni
  - data/skills/                     las tuyas (si tienen el mismo `name`, ganan las tuyas)

Antes de cada mensaje se elige la skill en dos pasos:
  1. Embeddings (rápido): el mensaje se compara con los ejemplos de cada skill y quedan como
     candidatas las que pasan UMBRAL (máximo 3).
  2. Si hay candidatas, el modelo confirma con una pregunta cerrada (agent/router.py) cuál
     corresponde o "ninguna". Solo con embeddings, "¿qué es un virus?" se parece más a
     "revisar archivo" que algunos pedidos reales; el modelo sí distingue preguntar de pedir.
Medido en la PC con nomic-embed-text + qwen3:4b-instruct: 23 de 25 mensajes bien, ~1 s extra
solo cuando hay candidatas.

La skill elegida se le pasa al modelo con sus pasos: así el modelo pequeño no tiene que
adivinar qué herramientas usar ni en qué orden. Los archivos se releen si cambian: no hace
falta reiniciar el núcleo.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..memory.conocimiento import Embedder

log = logging.getLogger("moni.skills")

INCLUIDAS = Path(__file__).resolve().parents[1] / "skills"

# Similitud mínima (con el ejemplo más parecido) para que una skill sea candidata. Con
# nomic-embed-text los pedidos reales dan 0.65-0.86; por debajo de 0.62 casi nunca acierta.
UMBRAL = 0.62
MAX_CANDIDATAS = 3


@dataclass
class Skill:
    nombre: str
    titulo: str
    descripcion: str
    ejemplos: list[str]
    pasos: str
    ruta: Path
    vectores: np.ndarray | None = field(default=None, repr=False)


def _frontmatter(texto: str) -> tuple[dict, str]:
    """Lee el bloque --- ... --- del inicio. Formato sencillo: `clave: valor` y listas `- x`."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", texto, re.DOTALL)
    if not m:
        return {}, texto
    datos: dict = {}
    clave = None
    for linea in m[1].splitlines():
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", linea)
        if item and clave:
            datos.setdefault(clave, [])
            if isinstance(datos[clave], list):
                datos[clave].append(item[1].strip())
            continue
        par = re.match(r"^([\w-]+):\s*(.*)$", linea)
        if par:
            clave = par[1]
            datos[clave] = par[2].strip() if par[2].strip() else []
    return datos, m[2].strip()


def leer(ruta: Path) -> Skill | None:
    try:
        datos, cuerpo = _frontmatter(ruta.read_text(encoding="utf-8"))
    except OSError:
        return None
    nombre = str(datos.get("name") or ruta.parent.name)
    ejemplos = [e for e in datos.get("examples", []) if isinstance(e, str)] or []
    descripcion = str(datos.get("description", ""))
    if not cuerpo or not (ejemplos or descripcion):
        log.warning("Skill %s sin pasos o sin ejemplos: se ignora", ruta)
        return None
    return Skill(
        nombre=nombre,
        titulo=str(datos.get("title") or nombre),
        descripcion=descripcion,
        ejemplos=ejemplos,
        pasos=cuerpo,
        ruta=ruta,
    )


def _normalizar(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(n == 0, 1, n)


class Skills:
    def __init__(self, carpetas: list[Path], embedder: Embedder):
        self.carpetas = [Path(c) for c in carpetas]
        self.embedder = embedder
        self._cache: dict[Path, tuple[float, Skill]] = {}

    def todas(self) -> list[Skill]:
        """Las skills de todas las carpetas; las de carpetas posteriores pisan a las anteriores."""
        por_nombre: dict[str, Skill] = {}
        vistas: set[Path] = set()
        for carpeta in self.carpetas:
            if not carpeta.is_dir():
                continue
            for archivo in sorted(carpeta.glob("*/SKILL.md")):
                vistas.add(archivo)
                mtime = archivo.stat().st_mtime
                guardada = self._cache.get(archivo)
                if guardada and guardada[0] == mtime:
                    skill = guardada[1]
                else:
                    skill = leer(archivo)
                    if skill is None:
                        continue
                    self._cache[archivo] = (mtime, skill)
                por_nombre[skill.nombre] = skill
        for viejo in set(self._cache) - vistas:
            del self._cache[viejo]
        return list(por_nombre.values())

    def _vectores(self, skill: Skill) -> np.ndarray:
        if skill.vectores is None:
            textos = skill.ejemplos + ([skill.descripcion] if skill.descripcion else [])
            skill.vectores = _normalizar(
                np.asarray(self.embedder(textos, "consulta"), dtype=np.float32)
            )
        return skill.vectores

    def puntuar(self, mensaje: str) -> list[tuple[float, Skill]]:
        """Similitud del mensaje con cada skill (la del ejemplo más parecido), de mayor a menor."""
        skills = self.todas()
        if not skills or len(mensaje.strip()) < 4:
            return []
        q = _normalizar(np.asarray(self.embedder([mensaje], "consulta")[0], dtype=np.float32))
        puntos = [(float(np.max(self._vectores(s) @ q)), s) for s in skills]
        return sorted(puntos, key=lambda p: p[0], reverse=True)

    def candidatas(self, mensaje: str) -> list[Skill]:
        puntos = self.puntuar(mensaje)
        if puntos:
            log.info(
                "Skills para %r: %s",
                mensaje[:60],
                ", ".join(f"{s.nombre}={p:.2f}" for p, s in puntos[:3]),
            )
        return [s for p, s in puntos if p >= UMBRAL][:MAX_CANDIDATAS]


def mensaje_skill(skill: Skill | None) -> dict | None:
    if skill is None:
        return None
    return {
        "role": "system",
        "content": (
            f'Para el próximo mensaje aplica tu skill "{skill.titulo}". Sigue estos pasos '
            "en orden, usando tus herramientas; si el mensaje en realidad pide otra cosa, "
            f"ignora la skill.\n\n{skill.pasos}"
        ),
    }


_actual: Skills | None = None


def usar(s: Skills | None) -> None:
    global _actual
    _actual = s


def actual() -> Skills | None:
    return _actual
