"""Bitácora de auditoría (sprint S2): cada herramienta que Moni usa queda registrada con
fecha, argumentos, si se pidió confirmación, la respuesta del usuario y el resultado.
Vive en la misma base de datos que el historial (data/moni.db), tabla `acciones`.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS acciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    herramienta TEXT NOT NULL,
    argumentos TEXT NOT NULL,
    nivel TEXT NOT NULL,
    confirmado INTEGER,          -- NULL si no hizo falta preguntar; 1 sí, 0 no
    ok INTEGER NOT NULL,
    resultado TEXT NOT NULL
);
"""


class Bitacora:
    def __init__(self, ruta: Path | str):
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(ruta, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_ESQUEMA)

    def registrar(
        self,
        herramienta: str,
        argumentos: dict,
        nivel: str,
        confirmado: bool | None,
        ok: bool,
        resultado: str,
    ) -> None:
        self._db.execute(
            "INSERT INTO acciones (fecha, herramienta, argumentos, nivel, confirmado, ok, resultado)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                herramienta,
                json.dumps(argumentos, ensure_ascii=False),
                nivel,
                None if confirmado is None else int(confirmado),
                int(ok),
                resultado[:2000],
            ),
        )
        self._db.commit()

    def ultimas(self, limite: int = 20) -> list[dict]:
        filas = self._db.execute(
            "SELECT * FROM acciones ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        return [dict(f) for f in filas]


_actual: Bitacora | None = None


def usar(b: Bitacora) -> None:
    """El núcleo indica qué bitácora usar (una por base de datos)."""
    global _actual
    _actual = b


def actual() -> Bitacora | None:
    return _actual
