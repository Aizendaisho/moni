"""Cuarentena: apartar un archivo sospechoso sin borrarlo.

El archivo se mueve a data/cuarentena/ y se guarda "desactivado": su contenido se transforma
con XOR (como hacen los antivirus), así no se puede abrir por accidente con doble clic ni lo
vuelve a detectar el antivirus en esa carpeta. Junto a él se guarda una ficha .json con la
ruta original, el hash, la fecha y el motivo. Restaurar lo devuelve tal cual, comprobando el
hash. Moni nunca borra: si quieres eliminarlo del todo, lo haces tú desde esa carpeta.
"""

import hashlib
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

CLAVE = 0xA5
_BLOQUE = 1024 * 1024


def _xor_copiar(origen: Path, destino: Path) -> str:
    """Copia origen en destino aplicando XOR y devuelve el SHA-256 del contenido ORIGINAL."""
    tabla = bytes(b ^ CLAVE for b in range(256))
    h = hashlib.sha256()
    with origen.open("rb") as fin, destino.open("wb") as fout:
        while bloque := fin.read(_BLOQUE):
            fout.write(bloque.translate(tabla))
            h.update(bloque)
    return h.hexdigest()


def _sin_xor_copiar(origen: Path, destino: Path) -> str:
    """Inverso de _xor_copiar; devuelve el SHA-256 del contenido restaurado."""
    tabla = bytes(b ^ CLAVE for b in range(256))
    h = hashlib.sha256()
    with origen.open("rb") as fin, destino.open("wb") as fout:
        while bloque := fin.read(_BLOQUE):
            claro = bloque.translate(tabla)
            fout.write(claro)
            h.update(claro)
    return h.hexdigest()


class Cuarentena:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)

    def _ficha(self, ident: str) -> Path:
        return self.carpeta / f"{ident}.json"

    def poner(self, ruta: Path, motivo: str = "") -> dict:
        ruta = Path(ruta).resolve()
        if not ruta.is_file():
            raise ValueError(f"No existe el archivo {ruta}")
        if self.carpeta.resolve() in ruta.parents:
            raise ValueError("Ese archivo ya está en la cuarentena")
        self.carpeta.mkdir(parents=True, exist_ok=True)
        ident = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        guardado = self.carpeta / f"{ident}.moni"
        try:
            sha = _xor_copiar(ruta, guardado)
            ruta.unlink()  # solo después de copiarlo entero
        except OSError as exc:
            guardado.unlink(missing_ok=True)
            raise ValueError(
                f"No pude moverlo ({exc}). Puede que esté abierto en otro programa."
            ) from exc
        ficha = {
            "id": ident,
            "nombre": ruta.name,
            "ruta_original": str(ruta),
            "sha256": sha,
            "tamano": guardado.stat().st_size,
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "motivo": motivo,
        }
        self._ficha(ident).write_text(json.dumps(ficha, ensure_ascii=False, indent=1), "utf-8")
        return ficha

    def listar(self) -> list[dict]:
        if not self.carpeta.is_dir():
            return []
        fichas = []
        for p in sorted(self.carpeta.glob("*.json")):
            try:
                f = json.loads(p.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if (self.carpeta / f"{f['id']}.moni").exists():
                fichas.append(f)
        return fichas

    def buscar(self, id_o_nombre: str) -> dict:
        texto = id_o_nombre.strip().lower()
        fichas = self.listar()
        exactas = [f for f in fichas if texto in (f["id"].lower(), f["nombre"].lower())]
        candidatas = exactas or [f for f in fichas if texto and texto in f["nombre"].lower()]
        if not candidatas:
            raise ValueError(f"No hay nada en la cuarentena que se llame '{id_o_nombre}'")
        if len(candidatas) > 1:
            lista = "; ".join(f"{f['nombre']} (id {f['id']})" for f in candidatas[:5])
            raise ValueError(f"Hay varios: {lista}. ¿Cuál? Usa el id.")
        return candidatas[0]

    def restaurar(self, id_o_nombre: str) -> dict:
        f = self.buscar(id_o_nombre)
        destino = Path(f["ruta_original"])
        if destino.exists():  # no pisar un archivo que apareció después
            destino = destino.with_name(f"{destino.stem} (restaurado){destino.suffix}")
        destino.parent.mkdir(parents=True, exist_ok=True)
        guardado = self.carpeta / f"{f['id']}.moni"
        tmp = destino.with_name(destino.name + ".restaurando")
        sha = _sin_xor_copiar(guardado, tmp)
        if sha != f["sha256"]:
            tmp.unlink(missing_ok=True)
            raise ValueError(
                "La copia en cuarentena está dañada: no coincide el hash. No toqué nada."
            )
        shutil.move(tmp, destino)
        guardado.unlink()
        self._ficha(f["id"]).unlink(missing_ok=True)
        return {**f, "restaurado_en": str(destino)}
