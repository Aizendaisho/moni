"""Memoria de lo aprendido: todo lo que Moni lee en internet (y las notas que decide guardar)
se divide en fragmentos, se convierte en vectores con un modelo de embeddings local
(nomic-embed-text en Ollama) y se guarda en data/moni.db. Antes de buscar en internet,
Moni consulta aquí; así recuerda lo que ya investigó y lo puede citar con fecha y fuente.

La búsqueda es por similitud de significado (no por palabras exactas), con NumPy sobre
los vectores guardados: sobra para decenas de miles de fragmentos. Si algún día crece
mucho, se cambia a sqlite-vec sin tocar el resto.
"""

import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS fuentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,                 -- NULL para notas de Moni
    titulo TEXT NOT NULL,
    tipo TEXT NOT NULL,       -- pagina | nota
    consulta TEXT,            -- qué se estaba investigando cuando se guardó
    fecha TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fuentes_url ON fuentes(url) WHERE url IS NOT NULL;
CREATE TABLE IF NOT EXISTS fragmentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fuente_id INTEGER NOT NULL REFERENCES fuentes(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    texto TEXT NOT NULL,
    vector BLOB NOT NULL      -- float32
);
CREATE INDEX IF NOT EXISTS idx_fragmentos_fuente ON fragmentos(fuente_id);
"""

# Recibe textos y devuelve un vector por texto. `tipo` es "documento" o "consulta".
Embedder = Callable[[list[str], str], list[list[float]]]

UMBRAL = 0.55  # similitud mínima para considerar que un recuerdo es relevante


def fragmentar(texto: str, tam: int = 1200, solape: int = 150) -> list[str]:
    """Divide un texto en trozos de ~tam caracteres, respetando párrafos cuando se puede."""
    parrafos = [p.strip() for p in re.split(r"\n\s*\n|\n", texto) if p.strip()]
    trozos: list[str] = []
    actual = ""
    for p in parrafos:
        while len(p) > tam:  # párrafo gigante: se corta por frases o a la fuerza
            corte = p.rfind(". ", 0, tam)
            corte = corte + 1 if corte > tam // 2 else tam
            p_ini, p = p[:corte].strip(), p[corte:].strip()
            if actual:
                trozos.append(actual)
                actual = ""
            trozos.append(p_ini)
        if len(actual) + len(p) + 1 > tam and actual:
            trozos.append(actual)
            actual = actual[-solape:] + " " + p if solape else p
        else:
            actual = f"{actual}\n{p}" if actual else p
    if actual.strip():
        trozos.append(actual.strip())
    return trozos


def embedder_ollama(host: str, modelo: str) -> Embedder:
    from ollama import Client

    cliente = Client(host=host)
    prefijo = {"documento": "search_document: ", "consulta": "search_query: "}

    def embed(textos: list[str], tipo: str) -> list[list[float]]:
        vectores: list[list[float]] = []
        for i in range(0, len(textos), 32):
            lote = [prefijo[tipo] + t for t in textos[i : i + 32]]
            vectores.extend(cliente.embed(model=modelo, input=lote).embeddings)
        return vectores

    return embed


class Conocimiento:
    def __init__(self, ruta: Path | str, embed: Embedder):
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(ruta, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("PRAGMA foreign_keys = ON;" + _ESQUEMA)
        self._embed = embed

    # ------------------------------------------------------------ guardar

    def guardar(
        self,
        titulo: str,
        texto: str,
        url: str | None = None,
        tipo: str = "pagina",
        consulta: str | None = None,
    ) -> int:
        """Guarda (o actualiza, si la URL ya existía) un texto. Devuelve el id de la fuente."""
        trozos = fragmentar(texto)
        if not trozos:
            raise ValueError("No hay texto que guardar.")
        vectores = self._embed(trozos, "documento")
        with self._db:
            if url:
                self._db.execute("DELETE FROM fuentes WHERE url = ?", (url,))
            cur = self._db.execute(
                "INSERT INTO fuentes (url, titulo, tipo, consulta, fecha) VALUES (?, ?, ?, ?, ?)",
                (url, titulo, tipo, consulta, datetime.now().isoformat(timespec="seconds")),
            )
            fid = int(cur.lastrowid)
            self._db.executemany(
                "INSERT INTO fragmentos (fuente_id, orden, texto, vector) VALUES (?, ?, ?, ?)",
                [
                    (fid, i, t, np.asarray(v, dtype=np.float32).tobytes())
                    for i, (t, v) in enumerate(zip(trozos, vectores, strict=True))
                ],
            )
        return fid

    # ------------------------------------------------------------ buscar

    def buscar(
        self,
        pregunta: str,
        limite: int = 5,
        fuente_id: int | None = None,
        umbral: float | None = None,
    ) -> list[dict]:
        """Fragmentos más parecidos en significado a la pregunta, del más al menos relevante."""
        umbral = UMBRAL if umbral is None else umbral
        sql = (
            "SELECT f.id, f.texto, f.vector, s.id AS fuente, s.titulo, s.url, s.tipo, s.fecha"
            " FROM fragmentos f JOIN fuentes s ON s.id = f.fuente_id"
        )
        filas = self._db.execute(
            sql + (" WHERE s.id = ?" if fuente_id else ""), (fuente_id,) if fuente_id else ()
        ).fetchall()
        if not filas:
            return []
        q = np.asarray(self._embed([pregunta], "consulta")[0], dtype=np.float32)
        m = np.stack([np.frombuffer(f["vector"], dtype=np.float32) for f in filas])
        sims = (m @ q) / (np.linalg.norm(m, axis=1) * np.linalg.norm(q) + 1e-9)
        orden = np.argsort(-sims)[:limite]
        return [
            {
                "titulo": filas[i]["titulo"],
                "url": filas[i]["url"],
                "tipo": filas[i]["tipo"],
                "fecha": filas[i]["fecha"][:10],
                "relevancia": round(float(sims[i]), 2),
                "texto": filas[i]["texto"],
            }
            for i in orden
            if sims[i] >= umbral
        ]

    def fuentes(self, limite: int = 20) -> list[dict]:
        filas = self._db.execute(
            "SELECT titulo, url, tipo, consulta, fecha FROM fuentes ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [dict(f) for f in filas]


_actual: Conocimiento | None = None


def usar(c: Conocimiento | None) -> None:
    global _actual
    _actual = c


def actual() -> Conocimiento | None:
    return _actual
