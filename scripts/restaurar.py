"""Restaura la memoria de Moni desde una copia de seguridad.

Uso: doble clic en scripts\\restaurar.bat (cierra antes la ventana "Moni - nucleo").

- Muestra las copias disponibles en la carpeta local y en Supabase.
- Pide la frase secreta (la de ASISTENTE_BACKUP_PASSPHRASE; si está en core/.env la usa).
- Antes de reemplazar, guarda la memoria actual como data/moni.db.antes-de-restaurar-<fecha>.
"""

import getpass
import socket
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from asistente_core.config import settings
from asistente_core.memory import respaldo


def nucleo_encendido() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((settings.host, settings.port)) == 0


def destinos() -> list:
    lista: list = []
    if settings.backup_local_dir:
        lista.append(respaldo.CarpetaLocal(Path(settings.backup_local_dir)))
    if settings.supabase_url and settings.supabase_service_key:
        lista.append(
            respaldo.SupabaseStorage(
                settings.supabase_url, settings.supabase_service_key, settings.supabase_bucket
            )
        )
    return lista


def main() -> int:
    print("=== Restaurar la memoria de Moni ===\n")
    if nucleo_encendido():
        print("El núcleo de Moni está encendido. Cierra la ventana 'Moni - nucleo' y vuelve a intentarlo.")
        return 1

    opciones: list[tuple[str, object, str]] = []  # (nombre, destino, etiqueta)
    for d in destinos():
        try:
            for n in reversed(d.listar()):
                opciones.append((n, d, d.nombre))
        except Exception as exc:  # noqa: BLE001
            print(f"  (No se pudo leer {d.nombre}: {exc})")
    if not opciones:
        print("No encontré copias. Revisa la configuración en core/.env.")
        return 1

    for i, (n, _, origen) in enumerate(opciones, 1):
        f = respaldo.fecha_de(n)
        print(f"  {i:>2}. {f:%d/%m/%Y %I:%M %p}  ({origen})")
    eleccion = input("\nNúmero de la copia a restaurar (Enter para cancelar): ").strip()
    if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(opciones):
        print("Cancelado. No se cambió nada.")
        return 0
    nombre, destino, _ = opciones[int(eleccion) - 1]

    frase = settings.backup_passphrase or getpass.getpass("Frase secreta: ")
    try:
        datos = respaldo.descifrar(destino.descargar(nombre), frase)
    except ValueError as exc:
        print(f"\n{exc}")
        return 1

    nueva = settings.data_dir / "moni.db.restaurando"
    nueva.write_bytes(datos)
    try:
        conn = sqlite3.connect(nueva)
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
    except sqlite3.DatabaseError as exc:
        resultado = str(exc)
    if resultado != "ok":
        nueva.unlink(missing_ok=True)
        print(f"\nLa copia está dañada ({resultado}). No se cambió nada.")
        return 1

    actual = settings.data_dir / "moni.db"
    if actual.exists():
        resguardo = actual.with_name(f"moni.db.antes-de-restaurar-{datetime.now():%Y%m%d-%H%M%S}")
        actual.replace(resguardo)
        print(f"\nLa memoria anterior quedó guardada como {resguardo.name}")
    nueva.replace(actual)
    print("Memoria restaurada. Ya puedes abrir Moni.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
