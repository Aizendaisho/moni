"""Copias de seguridad cifradas de la memoria de Moni (data/moni.db).

Cada copia:
  1. Se toma con la API de backup de SQLite: es consistente aunque Moni esté escribiendo.
  2. Se comprime (gzip) y se cifra en esta PC con AES-256-GCM. La clave sale de la frase
     secreta del usuario (scrypt). Sin la frase, la copia es ilegible para cualquiera,
     Supabase incluido. Si la frase se pierde, las copias no se pueden recuperar.
  3. Se guarda en uno o más destinos: una carpeta local y/o un bucket privado de
     Supabase Storage.

Formato del archivo: b"MONI1" + sal (16 bytes) + nonce (12 bytes) + datos cifrados.
Nombre: moni-AAAAMMDD-HHMMSS.db.gz.enc (hora local).

Retención: se conservan las 7 copias diarias más recientes (una por día) y 4 semanales
(la más nueva de cada semana anterior). El resto se borra.
"""

import gzip
import logging
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

log = logging.getLogger("moni.respaldo")

MAGIA = b"MONI1"
_NOMBRE = re.compile(r"^moni-(\d{8})-(\d{6})\.db\.gz\.enc$")


# ---------------------------------------------------------------- cifrado


def _clave(frase: str, sal: bytes) -> bytes:
    return Scrypt(salt=sal, length=32, n=2**15, r=8, p=1).derive(frase.encode("utf-8"))


def cifrar(datos: bytes, frase: str) -> bytes:
    if not frase:
        raise ValueError("Falta la frase secreta para cifrar la copia.")
    sal, nonce = os.urandom(16), os.urandom(12)
    return (
        MAGIA + sal + nonce + AESGCM(_clave(frase, sal)).encrypt(nonce, gzip.compress(datos), MAGIA)
    )


def descifrar(blob: bytes, frase: str) -> bytes:
    if not blob.startswith(MAGIA):
        raise ValueError("Ese archivo no es una copia de Moni.")
    sal, nonce, cuerpo = blob[5:21], blob[21:33], blob[33:]
    try:
        return gzip.decompress(AESGCM(_clave(frase, sal)).decrypt(nonce, cuerpo, MAGIA))
    except Exception as exc:  # InvalidTag: frase incorrecta o archivo dañado
        raise ValueError(
            "No se pudo descifrar: la frase secreta no coincide o la copia está dañada."
        ) from exc


def instantanea(ruta_db: Path) -> bytes:
    """Copia consistente de la base de datos, aunque esté en uso."""
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "copia.db"
        origen = sqlite3.connect(ruta_db)
        copia = sqlite3.connect(destino)
        try:
            origen.backup(copia)
        finally:
            copia.close()
            origen.close()
        return destino.read_bytes()


# ---------------------------------------------------------------- destinos


class Destino(Protocol):
    nombre: str

    def subir(self, nombre: str, datos: bytes) -> None: ...
    def listar(self) -> list[str]: ...
    def descargar(self, nombre: str) -> bytes: ...
    def borrar(self, nombres: list[str]) -> None: ...


@dataclass
class CarpetaLocal:
    carpeta: Path
    nombre: str = "carpeta local"

    def subir(self, nombre: str, datos: bytes) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.carpeta / (nombre + ".tmp")
        tmp.write_bytes(datos)
        tmp.replace(self.carpeta / nombre)

    def listar(self) -> list[str]:
        if not self.carpeta.exists():
            return []
        return sorted(p.name for p in self.carpeta.iterdir() if _NOMBRE.match(p.name))

    def descargar(self, nombre: str) -> bytes:
        return (self.carpeta / nombre).read_bytes()

    def borrar(self, nombres: list[str]) -> None:
        for n in nombres:
            (self.carpeta / n).unlink(missing_ok=True)


class SupabaseStorage:
    """Bucket privado de Supabase Storage, usando su API REST."""

    nombre = "Supabase"

    def __init__(
        self, url: str, clave: str, bucket: str, transport: httpx.BaseTransport | None = None
    ):
        self._bucket = bucket
        self._http = httpx.Client(
            base_url=url.rstrip("/") + "/storage/v1",
            headers={"Authorization": f"Bearer {clave}", "apikey": clave},
            timeout=60,
            transport=transport,
        )

    def _ok(self, r: httpx.Response, accion: str) -> httpx.Response:
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase rechazó {accion} ({r.status_code}): {r.text[:200]}")
        return r

    def subir(self, nombre: str, datos: bytes) -> None:
        self._ok(
            self._http.post(
                f"/object/{self._bucket}/{nombre}",
                content=datos,
                headers={"Content-Type": "application/octet-stream", "x-upsert": "true"},
            ),
            "la subida",
        )

    def listar(self) -> list[str]:
        r = self._ok(
            self._http.post(
                f"/object/list/{self._bucket}",
                json={"prefix": "", "limit": 1000, "sortBy": {"column": "name", "order": "asc"}},
            ),
            "el listado",
        )
        return sorted(o["name"] for o in r.json() if _NOMBRE.match(o.get("name", "")))

    def descargar(self, nombre: str) -> bytes:
        return self._ok(self._http.get(f"/object/{self._bucket}/{nombre}"), "la descarga").content

    def borrar(self, nombres: list[str]) -> None:
        if nombres:
            self._ok(
                self._http.request("DELETE", f"/object/{self._bucket}", json={"prefixes": nombres}),
                "el borrado",
            )


# ---------------------------------------------------------------- retención


def fecha_de(nombre: str) -> datetime | None:
    m = _NOMBRE.match(nombre)
    return datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S") if m else None


def a_conservar(nombres: list[str], diarias: int = 7, semanales: int = 4) -> set[str]:
    """La copia más nueva de cada uno de los últimos `diarias` días con copias, y la más nueva
    de cada una de las `semanales` semanas anteriores a esos días."""
    fechadas = sorted(((fecha_de(n), n) for n in nombres if fecha_de(n)), reverse=True)
    quedan: set[str] = set()
    dias: list = []
    for f, n in fechadas:
        if f.date() not in dias and len(dias) < diarias:
            dias.append(f.date())
            quedan.add(n)
    limite = min(dias) if dias else None
    semanas: list = []
    for f, n in fechadas:
        semana = f.isocalendar()[:2]
        if limite and f.date() >= limite:
            continue
        if semana not in semanas and len(semanas) < semanales:
            semanas.append(semana)
            quedan.add(n)
    return quedan


# ---------------------------------------------------------------- orquestación


@dataclass
class Resultado:
    nombre: str
    tamano_kb: int
    destinos_ok: list[str]
    errores: list[str]
    borradas: int


class Respaldo:
    def __init__(self, ruta_db: Path, frase: str, destinos: list[Destino]):
        self.ruta_db = Path(ruta_db)
        self.frase = frase
        self.destinos = destinos

    def hacer(self, ahora: datetime | None = None) -> Resultado:
        if not self.destinos:
            raise ValueError("No hay destinos de copia configurados.")
        nombre = f"moni-{(ahora or datetime.now()).strftime('%Y%m%d-%H%M%S')}.db.gz.enc"
        blob = cifrar(instantanea(self.ruta_db), self.frase)
        ok, errores, borradas = [], [], 0
        for d in self.destinos:
            try:
                d.subir(nombre, blob)
                ok.append(d.nombre)
                lista = d.listar()
                quedan = a_conservar(lista)
                viejas = [n for n in lista if n not in quedan]
                d.borrar(viejas)
                borradas += len(viejas)
            except Exception as exc:
                log.exception("Falló la copia en %s", d.nombre)
                errores.append(f"{d.nombre}: {exc}")
        log.info("Copia %s: ok=%s errores=%s", nombre, ok, errores)
        return Resultado(nombre, len(blob) // 1024, ok, errores, borradas)

    def ultima(self) -> tuple[datetime | None, dict[str, str | None]]:
        """Fecha de la copia más reciente en cualquier destino, y la última de cada uno."""
        por_destino: dict[str, str | None] = {}
        for d in self.destinos:
            try:
                lista = d.listar()
                por_destino[d.nombre] = lista[-1] if lista else None
            except Exception as exc:  # noqa: BLE001
                por_destino[d.nombre] = f"error: {exc}"
        fechas = [fecha_de(n) for n in por_destino.values() if n and fecha_de(n)]
        return (max(fechas) if fechas else None), por_destino


_actual: Respaldo | None = None


def usar(r: Respaldo | None) -> None:
    global _actual
    _actual = r


def actual() -> Respaldo | None:
    return _actual
