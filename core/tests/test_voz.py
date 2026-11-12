"""Pruebas de la lógica de voz (sin micrófono ni modelos)."""

import numpy as np
from fastapi.testclient import TestClient

from asistente_core.voice import texto as vt
from asistente_core.voice.vad import BLOQUE, MS_BLOQUE, Segmentador


def test_frases_salen_en_cuanto_se_cierran():
    f = vt.Frases(minimo=10)
    salida = []
    for token in ["Hola, ", "soy Moni. ", "Hoy abrí ", "el bloc de notas! ", "Y cerré", " Chrome"]:
        salida += f.agregar(token)
    assert salida == ["Hola, soy Moni.", "Hoy abrí el bloc de notas!"]
    assert f.terminar() == ["Y cerré Chrome"]
    assert f.terminar() == []
    # no corta en abreviaturas muy cortas al principio
    g = vt.Frases(minimo=25)
    assert g.agregar("Sí. Lo abro ahora mismo para ti. ") == ["Sí. Lo abro ahora mismo para ti."]


def test_limpiar_para_voz():
    t = vt.limpiar_para_voz(
        "## Resumen\n- **Don Quijote** es *genial* 🎉\nMira https://es.wikipedia.org/x y "
        "[la fuente](https://x.y). Guardado en C:\\Users\\a\\Documents\\Moni\\x.pdf"
    )
    assert t == "Resumen Don Quijote es genial Mira el enlace y la fuente. Guardado en esa carpeta"


def test_palabra_de_activacion():
    assert vt.activacion("Moni, abre el bloc de notas.") == (True, "abre el bloc de notas.")
    assert vt.activacion("Oye Money, ¿qué hora es?") == (True, "¿qué hora es?")
    assert vt.activacion("¿Moni?") == (True, "")
    assert vt.activacion("Hola Moni") == (True, "")
    assert vt.activacion("El dinero es money") == (False, "")
    assert vt.activacion("monitor nuevo") == (False, "")


def _bloques(probs):
    return [(np.full(BLOQUE, i, dtype=np.int16), p) for i, p in enumerate(probs)]


def test_segmentador_corta_frases():
    seg = Segmentador(
        umbral=0.5, silencio_ms=MS_BLOQUE * 5, minimo_ms=MS_BLOQUE * 3, previo_ms=MS_BLOQUE * 2
    )
    probs = [0.1] * 4 + [0.9] * 10 + [0.45] * 2 + [0.9] * 3 + [0.1] * 5 + [0.1] * 3
    frases = [a for b, p in _bloques(probs) if (a := seg.procesar(b, p)) is not None]
    assert len(frases) == 1
    audio = frases[0]
    # empieza 2 bloques antes del inicio (no se corta la primera sílaba) y termina tras el
    # silencio: 2 previos + 10 voz + 2 dudosos + 3 voz + 5 silencio
    assert audio[0] == 2
    assert len(audio) == (2 + 1 + 10 + 2 + 3 + 5 - 1) * BLOQUE


def test_segmentador_ignora_ruidos_cortos():
    seg = Segmentador(umbral=0.5, silencio_ms=MS_BLOQUE * 3, minimo_ms=MS_BLOQUE * 4)
    probs = [0.9, 0.9] + [0.1] * 5
    assert all(seg.procesar(b, p) is None for b, p in _bloques(probs))
    assert not seg.hablando


def test_segmentador_corta_frases_eternas():
    seg = Segmentador(maximo_ms=MS_BLOQUE * 10, minimo_ms=0)
    salidas = [a for b, p in _bloques([0.9] * 25) if (a := seg.procesar(b, p)) is not None]
    assert len(salidas) == 2


class MotorFalso:
    def __init__(self):
        self.llamadas, self.dicho, self.manos_libres = [], [], False

    def escuchar_una_vez(self):
        self.llamadas.append("listen")

    def activar_manos_libres(self, on):
        self.manos_libres = on
        self.llamadas.append(f"manos_libres={on}")

    def callar(self):
        self.llamadas.append("callar")

    def decir(self, frase):
        self.dicho.append(frase)


def test_websocket_voz(monkeypatch):
    """Lo transcrito entra como mensaje, se muestra y la respuesta se dice por frases."""
    import asistente_core.main as m
    from asistente_core.memory.historial import Historial

    from .test_core import _parte

    motor = MotorFalso()
    monkeypatch.setattr(m, "_voz", motor)
    monkeypatch.setattr(m, "historial", Historial(":memory:"))

    async def falso_stream(mensajes, tools):
        for t in ["Son las tres ", "de la tarde. ", "¿Algo **más**?"]:
            yield _parte(t)

    async def nada(*a, **k):
        return None

    real = m.responder
    monkeypatch.setattr(
        m,
        "responder",
        lambda ctx, turno, confirmar, **kw: real(ctx, turno, falso_stream, confirmar, **kw),
    )
    monkeypatch.setattr(m, "elegir_skill", nada)

    async def no(*a, **k):
        return False

    monkeypatch.setattr(m, "necesita_internet", no)
    with TestClient(m.app).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "listen"})
        ws.send_json({"type": "voice_mode", "on": True})
        ws.send_json({"type": "chat", "text": "¿qué hora es?", "voz": True})
        assert ws.receive_json() == {"type": "transcript", "text": "¿qué hora es?"}
        tipos = []
        while (ev := ws.receive_json())["type"] != "done":
            tipos.append(ev["type"])
        assert "token" in tipos
        ws.send_json({"type": "stop_speaking"})
        ws.send_json(
            {"type": "chat", "text": "gracias"}
        )  # por teclado, en manos libres también habla
        while ws.receive_json()["type"] != "done":
            pass
    assert motor.llamadas[:3] == ["listen", "manos_libres=True", "callar"]
    assert motor.dicho[:2] == ["Son las tres de la tarde.", "¿Algo **más**?"]
    assert motor.manos_libres is False  # al cerrar la ventana se apaga


def test_voces_url_y_descarga(tmp_path):
    import httpx
    import pytest

    from asistente_core.voice import voces

    assert voces.url_de("es_MX-claude-high").endswith("/es/es_MX/claude/high/es_MX-claude-high")
    assert voces.url_de("es_AR-daniela-high").endswith("/es/es_AR/daniela/high/es_AR-daniela-high")
    with pytest.raises(ValueError):
        voces.url_de("claude")
    pedidas = []

    def api(req):
        pedidas.append(str(req.url))
        return httpx.Response(200, content=b"datos")

    ruta = voces.asegurar(
        "es_MX-claude-high", tmp_path, httpx.Client(transport=httpx.MockTransport(api))
    )
    assert ruta.read_bytes() == b"datos" and (tmp_path / "es_MX-claude-high.onnx.json").exists()
    voces.asegurar("es_MX-claude-high", tmp_path, httpx.Client(transport=httpx.MockTransport(api)))
    assert len(pedidas) == 2  # la segunda vez no descarga nada
    assert voces.ESTILOS["suave"]["length_scale"] > 1  # más lenta que la normal


def test_cambiar_voz(tmp_path, monkeypatch):
    from asistente_core.tools import voz as tvoz
    from asistente_core.voice import estado, voces

    class M:
        def cambiar_voz(self, modelo, estilo, hablante):
            self.args = (modelo.name, estilo, hablante)

    m = M()
    monkeypatch.setattr(estado, "motor", m)
    monkeypatch.setattr(tvoz.settings, "data_dir", tmp_path)
    lista = tvoz.cambiar_voz()
    assert "es_MX-claude-high" in lista["disponibles"] and lista["estilo_actual"] == "suave"
    r = tvoz.cambiar_voz("la voz argentina")
    assert "es_AR-daniela-high" in r["hecho"] and m.args == (
        "es_AR-daniela-high.onnx",
        "suave",
        None,
    )
    tvoz.cambiar_voz("española", "normal")
    assert m.args == ("es_ES-sharvard-medium.onnx", "normal", 1)
    assert voces.leer_preferencia(tmp_path / "voz.json")["voz"] == "es_ES-sharvard-medium"
    tvoz.cambiar_voz(estilo="suave")  # solo el estilo: la voz se mantiene
    assert m.args == ("es_ES-sharvard-medium.onnx", "suave", 1)
    import pytest

    with pytest.raises(ValueError, match="No conozco"):
        tvoz.cambiar_voz("klingon")
