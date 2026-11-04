import asyncio
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from asistente_core.agent.loop import Turno, ejecutar_herramienta, responder
from asistente_core.agent.prompt import mensaje_sistema
from asistente_core.memory.historial import Historial
from asistente_core.permissions.policy import Nivel, esta_permitido, requiere_confirmacion
from asistente_core.tools.registry import REGISTRO, esquemas, herramienta
from asistente_core.tools.system import estado_sistema, fecha_hora, listar_procesos


def test_health():
    from asistente_core.main import app

    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_niveles_de_permiso():
    assert not requiere_confirmacion(Nivel.LIBRE)
    assert requiere_confirmacion(Nivel.CONFIRMAR)
    assert not esta_permitido(Nivel.PROHIBIDO)


def test_herramientas_del_sistema():
    procesos = listar_procesos(limite=3)
    assert 0 < len(procesos) <= 3
    assert {"programa", "memoria_mb", "cpu_porcentaje"} <= procesos[0].keys()
    assert listar_procesos(limite=2, ordenar_por="cpu")
    assert 0 < estado_sistema()["ram_total_gb"]
    assert " de " in fecha_hora()


def test_esquemas_parametros_opcionales():
    esq = {e["function"]["name"]: e for e in esquemas()}
    assert {"listar_procesos", "estado_sistema", "fecha_hora"} <= esq.keys()
    params = esq["listar_procesos"]["function"]["parameters"]
    assert "limite" in params["properties"]
    assert params["required"] == []  # tiene valor por defecto


def test_herramienta_que_requiere_confirmacion_no_se_ejecuta():
    llamado = []

    @herramienta(Nivel.CONFIRMAR, etiqueta="Prueba")
    def _borrar_algo() -> str:
        """Borra algo."""
        llamado.append(True)
        return "borrado"

    try:
        ok, texto = asyncio.run(ejecutar_herramienta("_borrar_algo", {}))
        assert not ok and "confirmación" in texto and not llamado
    finally:
        REGISTRO.pop("_borrar_algo")


def _parte(content="", tool_calls=None):
    return NS(message=NS(content=content, tool_calls=tool_calls))


def test_bucle_usa_herramienta_y_responde():
    rondas = iter(
        [
            [_parte(tool_calls=[NS(function=NS(name="fecha_hora", arguments={}))])],
            [_parte("Hoy es "), _parte("martes.")],
        ]
    )

    async def falso_stream(mensajes, tools):
        for p in next(rondas):
            yield p

    async def correr():
        turno = Turno()
        eventos = [
            e
            async for e in responder(
                [{"role": "user", "content": "¿qué día es?"}], turno, falso_stream
            )
        ]
        return eventos, turno

    eventos, turno = asyncio.run(correr())
    tipos = [e["type"] for e in eventos]
    assert tipos == ["tool", "tool", "token", "token"]
    assert eventos[1]["ok"] is True
    roles = [m["role"] for m in turno.nuevos]
    assert roles == ["assistant", "tool", "assistant"]
    assert turno.nuevos[-1]["content"] == "Hoy es martes."


def test_historial_guarda_y_recorta():
    h = Historial(":memory:")
    c = h.nueva()
    h.agregar(c, {"role": "user", "content": "hola"})
    h.agregar(
        c,
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "fecha_hora", "arguments": {}}}],
        },
    )
    h.agregar(c, {"role": "tool", "tool_name": "fecha_hora", "content": "martes"})
    h.agregar(c, {"role": "assistant", "content": "Es martes."})
    h.agregar(c, {"role": "user", "content": "gracias"})
    assert [m["role"] for m in h.mensajes(c)] == ["user", "assistant", "tool", "assistant", "user"]
    assert h.mensajes(c)[1]["tool_calls"][0]["function"]["name"] == "fecha_hora"
    assert h.mensajes(c, limite=3) == [{"role": "user", "content": "gracias"}]  # empieza en user
    assert h.visibles(c) == [
        {"role": "user", "text": "hola"},
        {"role": "assistant", "text": "Es martes."},
        {"role": "user", "text": "gracias"},
    ]
    assert h.ultima() == c


def test_personalidad():
    s = mensaje_sistema()["content"]
    assert "Moni" in s and "{usuario}" not in s and "Ahora es" in s


# ---------------------------------------------------------------- S2


def test_buscar_programa_por_nombre():
    from asistente_core.tools.apps import _parecido

    opciones = ["Google Chrome", "Bloc de notas", "Calculadora", "Spotify", "Steam"]
    assert _parecido("chrome", opciones)[0] == "Google Chrome"
    assert _parecido("bloc de notas", opciones) == ["Bloc de notas"]
    assert _parecido("spotyfi", opciones) == ["Spotify"]  # con error de tipeo
    assert _parecido("photoshop", opciones) == []


def test_no_cierra_procesos_protegidos():
    import pytest

    from asistente_core.tools.apps import _procesos_de

    with pytest.raises(ValueError):
        _procesos_de("python")  # el propio núcleo de Moni


def test_uso_de_internet():
    from asistente_core.tools.red import uso_de_internet

    r = uso_de_internet(limite=3)
    assert r["bajada_kb_s"] >= 0 and "nota" in r
    assert isinstance(r["programas_con_mas_conexiones"], list)


def test_confirmacion_y_bitacora():
    from asistente_core.memory import bitacora as bmod

    b = bmod.Bitacora(":memory:")
    bmod.usar(b)
    hechos = []

    @herramienta(Nivel.CONFIRMAR, etiqueta="Borrando", resumen=lambda cosa: f"¿Borro {cosa}?")
    def _borrar(cosa: str) -> str:
        """Borra algo.

        Args:
          cosa: Qué borrar.
        """
        hechos.append(cosa)
        return f"Borré {cosa}."

    preguntas = []

    def responde(valor):
        async def confirmar(pregunta):
            preguntas.append(pregunta)
            return valor

        return confirmar

    try:
        ok, texto = asyncio.run(ejecutar_herramienta("_borrar", {"cosa": "x"}, responde(False)))
        assert not ok and "no" in texto and hechos == []
        ok, texto = asyncio.run(ejecutar_herramienta("_borrar", {"cosa": "y"}, responde(True)))
        assert ok and hechos == ["y"]
        assert preguntas == ["¿Borro x?", "¿Borro y?"]
        acciones = b.ultimas()
        assert [(a["confirmado"], a["ok"]) for a in acciones] == [(1, 1), (0, 0)]
    finally:
        REGISTRO.pop("_borrar")
        bmod.usar(None)


def test_websocket_pide_confirmacion(monkeypatch):
    """Flujo completo: el modelo pide una acción, la app recibe la pregunta y dice que no."""
    import asistente_core.main as m

    hechos = []

    @herramienta(Nivel.CONFIRMAR, etiqueta="Apagando", resumen=lambda: "¿Apago la luz?")
    def _apagar() -> str:
        """Apaga la luz."""
        hechos.append(1)
        return "apagada"

    rondas = iter(
        [
            [_parte(tool_calls=[NS(function=NS(name="_apagar", arguments={}))])],
            [_parte("Vale, no la apago.")],
        ]
    )

    async def falso_stream(mensajes, tools):
        for p in next(rondas):
            yield p

    real = m.responder
    monkeypatch.setattr(
        m, "responder", lambda ctx, turno, confirmar: real(ctx, turno, falso_stream, confirmar)
    )
    monkeypatch.setattr(m, "historial", Historial(":memory:"))
    try:
        with TestClient(m.app).websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "history"
            ws.send_json({"type": "chat", "text": "apaga la luz"})
            assert ws.receive_json()["status"] == "start"
            pregunta = ws.receive_json()
            assert pregunta["type"] == "confirm" and pregunta["question"] == "¿Apago la luz?"
            ws.send_json({"type": "confirm_reply", "id": pregunta["id"], "ok": False})
            fin = ws.receive_json()
            assert fin["status"] == "end" and fin["ok"] is False
            assert ws.receive_json() == {"type": "token", "text": "Vale, no la apago."}
            assert ws.receive_json()["type"] == "done"
        assert hechos == []
    finally:
        REGISTRO.pop("_apagar")
