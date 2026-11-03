from fastapi.testclient import TestClient

from asistente_core.main import app
from asistente_core.permissions.policy import Nivel, esta_permitido, requiere_confirmacion
from asistente_core.tools.system import listar_procesos


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_niveles_de_permiso():
    assert not requiere_confirmacion(Nivel.LIBRE)
    assert requiere_confirmacion(Nivel.CONFIRMAR)
    assert not esta_permitido(Nivel.PROHIBIDO)


def test_listar_procesos():
    procesos = listar_procesos(limite=3)
    assert 0 < len(procesos) <= 3
    assert {"pid", "nombre", "memoria_mb"} <= procesos[0].keys()
