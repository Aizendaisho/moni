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


# ---------------------------------------------------------------- internet y memoria


def _embed_falso(textos, tipo):
    """Vectores de bolsa de palabras: textos con palabras en común se parecen."""
    import zlib

    import numpy as np

    vs = []
    for t in textos:
        v = np.zeros(256, dtype=np.float32)
        for w in t.lower().split():
            v[zlib.crc32(w.strip(".,¿?").encode()) % 256] += 1
        vs.append(v.tolist())
    return vs


def test_fragmentar_respeta_tamano():
    from asistente_core.memory.conocimiento import fragmentar

    texto = "\n\n".join(f"Párrafo {i}. " + "palabra " * 60 for i in range(20))
    trozos = fragmentar(texto, tam=1200)
    assert len(trozos) > 3 and all(len(t) <= 1400 for t in trozos)
    assert fragmentar("") == []


def test_conocimiento_guarda_y_recuerda():
    from asistente_core.memory.conocimiento import Conocimiento

    c = Conocimiento(":memory:", _embed_falso)
    c.guardar(
        "Don Quijote",
        "Don Quijote de la Mancha fue escrito por Miguel de Cervantes.",
        url="https://a.org/q",
    )
    c.guardar("Volcanes", "Los volcanes expulsan lava y ceniza.", url="https://b.org/v")
    r = c.buscar("¿quién escribió Don Quijote?", umbral=0.1)
    assert r[0]["titulo"] == "Don Quijote" and r[0]["url"] == "https://a.org/q"
    # Volver a leer la misma URL la actualiza en vez de duplicarla
    c.guardar(
        "Don Quijote (2)", "Cervantes publicó la primera parte en 1605.", url="https://a.org/q"
    )
    assert [f["titulo"] for f in c.fuentes()] == ["Don Quijote (2)", "Volcanes"]


def test_no_abre_direcciones_locales():
    import pytest

    from asistente_core.tools.web import validar_url

    for url in [
        "http://127.0.0.1:11434/api/tags",
        "http://localhost:8765",
        "http://192.168.1.1",
        "file:///C:/Windows",
        "ftp://x.org",
    ]:
        with pytest.raises(ValueError):
            validar_url(url)


def test_extraer_texto_de_html():
    from asistente_core.tools.web import extraer

    html = (
        "<html><head><title>Receta de mangú</title></head><body><nav>Inicio | Menú</nav>"
        "<article><h1>Mangú dominicano</h1>"
        + "".join(
            f"<p>Paso {i}: hierve los plátanos verdes y májalos con mantequilla.</p>"
            for i in range(8)
        )
        + "</article><footer>© 2026</footer></body></html>"
    )
    titulo, texto = extraer(html, "https://ejemplo.com/mangu")
    assert "mangú" in titulo.lower()
    assert "plátanos" in texto and "Inicio | Menú" not in texto


def test_leer_pagina_guarda_en_memoria(monkeypatch):
    from asistente_core.memory import conocimiento as cmod
    from asistente_core.tools import web

    monkeypatch.setattr(cmod, "UMBRAL", 0.1)  # el embedder falso da similitudes más bajas
    c = cmod.Conocimiento(":memory:", _embed_falso)
    cmod.usar(c)
    html = (
        "<html><head><title>Cervantes</title></head><body><article>"
        + "".join(
            f"<p>Miguel de Cervantes escribió Don Quijote. Dato número {i} sobre su vida y obra.</p>"
            for i in range(15)
        )
        + "</article></body></html>"
    )
    monkeypatch.setattr(web, "_descargar", lambda url: (html, url))
    try:
        salida = web.leer_pagina("https://ejemplo.org/cervantes")
        assert "CONTENIDO DE LA PÁGINA" in salida and "Cervantes" in salida
        assert c.fuentes()[0]["url"] == "https://ejemplo.org/cervantes"
        assert web.recordar("Cervantes Don Quijote")[0]["titulo"] == "Cervantes"
    finally:
        cmod.usar(None)


def test_historial_recorta_resultados_viejos():
    h = Historial(":memory:")
    c = h.nueva()
    h.agregar(c, {"role": "user", "content": "lee algo"})
    h.agregar(c, {"role": "tool", "tool_name": "leer_pagina", "content": "x" * 5000})
    h.agregar(c, {"role": "assistant", "content": "listo"})
    h.agregar(c, {"role": "user", "content": "otra cosa"})
    h.agregar(c, {"role": "tool", "tool_name": "leer_pagina", "content": "y" * 5000})
    msgs = h.mensajes(c)
    assert len(msgs[1]["content"]) < 500  # turno anterior: recortado
    assert len(msgs[4]["content"]) == 5000  # turno actual: completo


def test_investigar_busca_lee_y_responde_con_fuentes(monkeypatch):
    from asistente_core.memory import conocimiento as cmod
    from asistente_core.tools import web

    cmod.usar(cmod.Conocimiento(":memory:", _embed_falso))
    paginas = {
        "https://a.org/quijote": "<html><head><title>Quijote</title></head><body><article>"
        + "".join(
            f"<p>Dato {i}: la primera parte del Quijote se publicó en 1605 en Madrid,"
            " impresa por Juan de la Cuesta.</p>"
            for i in range(10)
        )
        + "</article></body></html>",
        "https://b.org/roto": None,  # esta falla y se salta
        "https://c.org/otro": "<html><head><title>Otro</title></head><body><article>"
        + "".join(f"<p>Párrafo {i} sobre volcanes y montañas lejanas.</p>" for i in range(20))
        + "</article></body></html>",
    }

    def descargar(url):
        if paginas[url] is None:
            raise ValueError("caída")
        return paginas[url], url

    monkeypatch.setattr(web, "_descargar", descargar)
    monkeypatch.setattr(
        web,
        "buscar_en_internet",
        lambda consulta, cantidad=5: [{"titulo": u, "url": u, "extracto": "..."} for u in paginas],
    )
    try:
        r = web.investigar("¿cuándo se publicó la primera parte del Quijote?", paginas=2)
        assert [p["url"] for p in r["paginas_leidas"]] == [
            "https://a.org/quijote",
            "https://c.org/otro",
        ]
        assert r["fragmentos"][0]["url"] == "https://a.org/quijote"
        assert "1605" in r["fragmentos"][0]["texto"]
    finally:
        cmod.usar(None)


def test_recuerdos_se_inyectan_antes_del_mensaje(monkeypatch):
    """El núcleo consulta la memoria solo y pasa los recuerdos al modelo."""
    import asistente_core.main as m
    from asistente_core.memory import conocimiento as cmod

    c = cmod.Conocimiento(":memory:", _embed_falso)
    c.guardar(
        "Juan de la Cuesta",
        "La imprenta de Juan de la Cuesta estaba en la calle de Atocha, en Madrid.",
        url="https://es.wikipedia.org/wiki/Juan_de_la_Cuesta",
    )
    cmod.usar(c)
    monkeypatch.setattr(cmod, "UMBRAL", 0.1)
    vistos = []

    async def falso_stream(mensajes, tools):
        vistos.append(list(mensajes))
        yield _parte("En la calle de Atocha.")

    real = m.responder
    monkeypatch.setattr(
        m, "responder", lambda ctx, turno, confirmar: real(ctx, turno, falso_stream, confirmar)
    )
    monkeypatch.setattr(m, "historial", Historial(":memory:"))
    try:
        with TestClient(m.app).websocket_connect("/ws") as ws:
            ws.receive_json()  # history
            ws.send_json({"type": "chat", "text": "¿En qué calle estaba la imprenta del Quijote?"})
            assert ws.receive_json() == {"type": "memory", "count": 1}
            assert ws.receive_json()["type"] == "token"
            assert ws.receive_json()["type"] == "done"
        ctx = vistos[0]
        assert ctx[-1]["role"] == "user"
        assert ctx[-2]["role"] == "system" and "Atocha" in ctx[-2]["content"]
    finally:
        cmod.usar(None)


def test_nucleo_investiga_si_hace_falta(monkeypatch):
    """Sin recuerdos y con una pregunta de datos, el núcleo investiga antes de que responda Moni."""
    import asistente_core.main as m

    vistos = []

    async def falso_stream(mensajes, tools):
        vistos.append(list(mensajes))
        yield _parte("Es la 4.5.")

    async def siempre_si(texto, anterior=""):
        return True

    async def falso_ejecutar(nombre, args, confirmar=None):
        return True, '{"fragmentos": [{"fuente": "Godot", "texto": "Godot 4.5 salió..."}]}'

    real = m.responder
    monkeypatch.setattr(
        m, "responder", lambda ctx, turno, confirmar: real(ctx, turno, falso_stream, confirmar)
    )
    monkeypatch.setattr(m, "necesita_internet", siempre_si)
    monkeypatch.setattr(m, "ejecutar_herramienta", falso_ejecutar)
    monkeypatch.setattr(m, "historial", Historial(":memory:"))
    with TestClient(m.app).websocket_connect("/ws") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "chat", "text": "¿Cuál es la última versión de Godot?"})
        assert ws.receive_json()["status"] == "start"
        assert ws.receive_json()["status"] == "end"
        assert ws.receive_json()["type"] == "token"
        assert ws.receive_json()["type"] == "done"
    ctx = vistos[0]
    assert [x["role"] for x in ctx[-3:]] == ["user", "assistant", "tool"]
    assert "Godot 4.5" in ctx[-1]["content"]


# ---------------------------------------------------------------- copias de seguridad


def _db_de_prueba(ruta):
    import sqlite3

    c = sqlite3.connect(ruta)
    c.execute("CREATE TABLE t (x TEXT)")
    c.execute("INSERT INTO t VALUES ('recuerdo importante')")
    c.commit()
    return c


def test_cifrado_ida_y_vuelta():
    import pytest

    from asistente_core.memory.respaldo import cifrar, descifrar

    blob = cifrar(b"datos de Moni", "frase correcta")
    assert b"datos de Moni" not in blob
    assert descifrar(blob, "frase correcta") == b"datos de Moni"
    with pytest.raises(ValueError):
        descifrar(blob, "frase equivocada")


def test_retencion_7_diarias_4_semanales():
    from datetime import datetime, timedelta

    from asistente_core.memory.respaldo import a_conservar

    base = datetime(2026, 11, 4, 10, 0, 0)
    nombres = [
        f"moni-{(base - timedelta(days=d)).strftime('%Y%m%d-%H%M%S')}.db.gz.enc" for d in range(60)
    ]
    nombres.append(
        f"moni-{(base - timedelta(hours=2)).strftime('%Y%m%d-%H%M%S')}.db.gz.enc"
    )  # 2 hoy
    quedan = a_conservar(nombres)
    assert len(quedan) == 11  # 7 días + 4 semanas
    assert nombres[0] in quedan  # la más nueva de hoy
    assert nombres[-1] not in quedan  # la de hoy más vieja sobra


def test_respaldo_local_completo(tmp_path):
    import sqlite3

    from asistente_core.memory.respaldo import CarpetaLocal, Respaldo, descifrar

    db = tmp_path / "moni.db"
    conn = _db_de_prueba(db)  # abierta mientras se copia, como en la vida real
    r = Respaldo(db, "frase", [CarpetaLocal(tmp_path / "respaldos")])
    res = r.hacer()
    conn.close()
    assert res.destinos_ok == ["carpeta local"] and not res.errores
    fecha, _ = r.ultima()
    assert fecha is not None
    restaurada = tmp_path / "restaurada.db"
    restaurada.write_bytes(descifrar((tmp_path / "respaldos" / res.nombre).read_bytes(), "frase"))
    assert (
        sqlite3.connect(restaurada).execute("SELECT x FROM t").fetchone()[0]
        == "recuerdo importante"
    )


def test_supabase_storage_con_api_simulada(tmp_path):
    import httpx

    from asistente_core.memory.respaldo import Respaldo, SupabaseStorage, descifrar

    guardado: dict[str, bytes] = {}

    def api(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer clave-secreta"
        ruta = req.url.path
        if req.method == "POST" and ruta.startswith("/storage/v1/object/list/moni-respaldos"):
            return httpx.Response(200, json=[{"name": n} for n in guardado])
        if req.method == "POST" and ruta.startswith("/storage/v1/object/moni-respaldos/"):
            guardado[ruta.rsplit("/", 1)[1]] = req.content
            return httpx.Response(200, json={"Key": ruta})
        if req.method == "GET":
            return httpx.Response(200, content=guardado[ruta.rsplit("/", 1)[1]])
        if req.method == "DELETE":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    nube = SupabaseStorage(
        "https://x.supabase.co",
        "clave-secreta",
        "moni-respaldos",
        transport=httpx.MockTransport(api),
    )
    db = tmp_path / "moni.db"
    _db_de_prueba(db).close()
    res = Respaldo(db, "frase", [nube]).hacer()
    assert res.destinos_ok == ["Supabase"]
    assert nube.listar() == [res.nombre]
    assert descifrar(nube.descargar(res.nombre), "frase").startswith(b"SQLite format 3")
