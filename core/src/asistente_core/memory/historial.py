"""Historial de conversaciones en SQLite (data/moni.db).

Guarda todos los mensajes: los del usuario, las respuestas de Moni y los resultados de
herramientas (así el modelo recuerda qué consultó). La interfaz solo muestra los dos primeros.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS conversaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversacion_id INTEGER NOT NULL REFERENCES conversaciones(id) ON DELETE CASCADE,
    rol TEXT NOT NULL,              -- user | assistant | tool
    contenido TEXT NOT NULL,
    herramienta TEXT,               -- nombre, si rol = tool
    llamadas TEXT,                  -- JSON de tool_calls, si el asistente pidió herramientas
    creado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mensajes_conv ON mensajes(conversacion_id, id);
"""


class Historial:
    def __init__(self, ruta: Path | str):
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(ruta, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("PRAGMA foreign_keys = ON;" + _ESQUEMA)

    def nueva(self) -> int:
        cur = self._db.execute(
            "INSERT INTO conversaciones (creada) VALUES (?)", (datetime.now().isoformat(),)
        )
        self._db.commit()
        return int(cur.lastrowid)

    def ultima(self) -> int:
        """La conversación más reciente, o una nueva si no hay ninguna."""
        fila = self._db.execute("SELECT id FROM conversaciones ORDER BY id DESC LIMIT 1").fetchone()
        return int(fila["id"]) if fila else self.nueva()

    def agregar(self, conversacion_id: int, mensaje: dict) -> None:
        llamadas = mensaje.get("tool_calls")
        self._db.execute(
            "INSERT INTO mensajes (conversacion_id, rol, contenido, herramienta, llamadas, creado)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversacion_id,
                mensaje["role"],
                mensaje.get("content") or "",
                mensaje.get("tool_name"),
                json.dumps(llamadas, ensure_ascii=False) if llamadas else None,
                datetime.now().isoformat(),
            ),
        )
        self._db.commit()

    def mensajes(self, conversacion_id: int, limite: int | None = None) -> list[dict]:
        """Mensajes en orden cronológico, listos para enviar al modelo.
        Con `limite`, solo los últimos N, empezando siempre en un mensaje del usuario."""
        filas = self._db.execute(
            "SELECT rol, contenido, herramienta, llamadas FROM mensajes"
            " WHERE conversacion_id = ? ORDER BY id",
            (conversacion_id,),
        ).fetchall()
        if limite is not None and len(filas) > limite:
            filas = filas[-limite:]
            while filas and filas[0]["rol"] != "user":
                filas = filas[1:]
        salida = []
        for f in filas:
            m: dict = {"role": f["rol"], "content": f["contenido"]}
            if f["herramienta"]:
                m["tool_name"] = f["herramienta"]
            if f["llamadas"]:
                m["tool_calls"] = json.loads(f["llamadas"])
            salida.append(m)
        return salida

    def visibles(self, conversacion_id: int) -> list[dict]:
        """Solo lo que ve la persona: sus mensajes y las respuestas con texto de Moni."""
        return [
            {"role": m["role"], "text": m["content"]}
            for m in self.mensajes(conversacion_id)
            if m["role"] == "user" or (m["role"] == "assistant" and m["content"].strip())
        ]
