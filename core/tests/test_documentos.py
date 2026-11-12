"""Pruebas de documentos, resúmenes por partes y avisos en segundo plano."""

import time
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from asistente_core import avisos, documentos, resumen
from asistente_core.tools import docs

MD = """Intro con **negrita** y *cursiva* & <símbolos>.

## Personajes
- Don Quijote
- Sancho Panza

## Aventuras
1. Molinos
2. La venta
"""


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(docs.settings, "documents_dir", str(tmp_path / "Moni"))
    return tmp_path / "Moni"


def test_markdown_a_bloques():
    b = documentos.bloques(MD)
    assert [x.tipo for x in b] == ["p", "h2", "vineta", "vineta", "h2", "numero", "numero"]
    assert documentos._trozos_en_linea("a **b** *c*") == [
        ("a ", False, False), ("b", True, False), (" ", False, False), ("c", False, True)
    ]  # fmt: skip


def test_crear_pdf_word_y_txt_sin_sobrescribir(carpeta):
    r1 = docs.crear_documento("Resumen: Quijote?", MD, "pdf")
    r2 = docs.crear_documento("Resumen: Quijote?", MD, "pdf")
    r3 = docs.crear_documento("Resumen: Quijote?", MD, "word")
    r4 = docs.crear_documento("Notas", MD, "txt")
    assert Path(r1["ruta"]).name == "Resumen Quijote.pdf"  # sin caracteres prohibidos
    assert Path(r2["ruta"]).name == "Resumen Quijote (2).pdf"
    assert Path(r3["ruta"]).suffix == ".docx" and Path(r4["ruta"]).suffix == ".txt"
    assert Path(r1["ruta"]).read_bytes()[:4] == b"%PDF"
    assert zipfile.is_zipfile(r3["ruta"])
    pdf = documentos.leer_texto(Path(r1["ruta"]))
    assert "Sancho Panza" in pdf and "negrita" in pdf and "<símbolos>" in pdf
    assert "Molinos" in documentos.leer_texto(Path(r3["ruta"]))
    with pytest.raises(ValueError, match="Formato"):
        docs.crear_documento("x", MD, "odt")
    with pytest.raises(ValueError, match="vacío"):
        docs.crear_documento("x", "hola", "pdf")


def test_abrir_solo_documentos_de_moni(carpeta, tmp_path):
    docs.crear_documento("Mi resumen", MD, "pdf")
    assert docs._ruta_creada("Mi resumen.pdf").name == "Mi resumen.pdf"
    assert docs._ruta_creada("resumen").name == "Mi resumen.pdf"  # por parecido
    afuera = tmp_path / "otro.pdf"
    afuera.write_bytes(b"%PDF")
    with pytest.raises(ValueError, match="Solo puedo abrir"):
        docs._ruta_creada(str(afuera))
    with pytest.raises(ValueError, match="Solo puedo abrir"):
        docs._ruta_creada("../otro.pdf")


def test_partir_respeta_parrafos_y_tamano():
    texto = "\n\n".join(f"Párrafo {i}. " + "palabra " * 150 for i in range(40))
    partes = resumen.partir(texto, tam=3000)
    assert all(len(p) <= 3000 for p in partes)
    assert "".join(partes).count("Párrafo") == 40
    gigante = "Frase larga. " * 2000
    assert all(len(p) <= 3000 for p in resumen.partir(gigante, tam=3000))


def test_resumir_por_niveles(monkeypatch):
    llamadas = []

    def llm(instr, texto):
        llamadas.append(instr[:30])
        return "- resumen " + ("x" * 2000 if instr.startswith("Estás") else "y" * 50)

    monkeypatch.setattr(resumen, "TAM_PARTE", 3000)
    texto = "\n\n".join("palabra " * 300 for _ in range(30))
    r = resumen.resumir(texto, llm, titulo="Libro")
    n = len(resumen.partir(texto, 3000))
    parciales = [c for c in llamadas if c.startswith("Estás resumiendo")]
    assert len(parciales) == n
    assert any(c.startswith("Estos son resúmenes") for c in llamadas)  # combinación por grupos
    assert llamadas[-1].startswith("Escribe en español el resumen")
    assert r.startswith("- resumen")

    # si el modelo nunca acorta, se corta en el nivel 4 en vez de girar sin fin
    terco = resumen.resumir(texto, lambda i, t: "z" * 5000)
    assert terco == "z" * 5000


def test_resumir_corto_al_momento(carpeta, tmp_path, monkeypatch):
    monkeypatch.setattr(
        docs, "_llm_sync", lambda i, t: "## Resumen\n- Es un texto corto de prueba."
    )
    f = tmp_path / "Downloads" / "nota.txt"
    f.parent.mkdir()
    f.write_text("Un texto corto sobre molinos y gigantes. " * 20)
    monkeypatch.setattr(docs, "resolver", lambda r: f)
    r = docs.resumir_documento("nota.txt", guardar_como="pdf")
    assert "texto corto" in r["resumen"] and r["ruta"].endswith("Resumen de nota.pdf")


def test_resumir_largo_en_segundo_plano_y_avisa(carpeta, tmp_path, monkeypatch):
    publicados = []
    monkeypatch.setattr(avisos, "publicar", lambda texto, **d: publicados.append(texto))
    monkeypatch.setattr(docs, "_llm_sync", lambda i, t: "- idea")
    f = tmp_path / "libro.txt"
    f.write_text("\n\n".join("Capítulo con muchas palabras. " * 100 for _ in range(30)))
    monkeypatch.setattr(docs, "resolver", lambda r: f)
    r = docs.resumir_documento("libro.txt")
    assert r["estado"] == "en segundo plano" and r["partes"] > resumen.PARTES_DIRECTO
    for _ in range(100):
        if any(p.startswith("Terminé") for p in publicados):
            break
        time.sleep(0.05)
    assert any(p.startswith("Terminé el resumen de libro") for p in publicados)
    assert any("mitad" in p for p in publicados)


def test_aviso_llega_a_la_ventana(monkeypatch):
    import asistente_core.main as m
    from asistente_core.memory.historial import Historial

    monkeypatch.setattr(m, "historial", Historial(":memory:"))
    with TestClient(m.app) as cliente, cliente.websocket_connect("/ws") as ws:
        ws.receive_json()  # historial
        avisos.publicar("Terminé el resumen de prueba.", ruta="x.pdf")
        msg = ws.receive_json()
        assert msg == {"type": "notice", "text": "Terminé el resumen de prueba.", "ruta": "x.pdf"}
    conv = m.historial.ultima()
    assert m.historial.visibles(conv)[-1]["text"] == "Terminé el resumen de prueba."


def test_memoria_aguanta_escrituras_en_paralelo():
    from concurrent.futures import ThreadPoolExecutor

    from asistente_core.memory.conocimiento import Conocimiento

    from .test_core import _embed_falso

    c = Conocimiento(":memory:", _embed_falso)
    with ThreadPoolExecutor(8) as pool:
        ids = list(
            pool.map(
                lambda i: c.guardar(f"T{i}", f"texto número {i} " * 200, url=f"https://x/{i}"),
                range(24),
            )
        )
    assert len(set(ids)) == 24 and len(c.fuentes(50)) == 24


def test_leer_texto_plano_sin_guardar(monkeypatch):
    from asistente_core.tools import web

    libro = (
        "El ingenioso hidalgo don Quijote de la Mancha\n\n" + "En un lugar de la Mancha... " * 50
    )
    monkeypatch.setattr(web, "_descargar", lambda url: (libro, url))
    guardados = []
    monkeypatch.setattr(
        web, "_memoria", lambda: NS(guardar=lambda *a, **k: guardados.append(a) or 7)
    )
    fid, titulo, _, texto = web._leer("https://gutenberg.org/x.txt", guardar=False)
    assert (
        fid == 0 and titulo.startswith("El ingenioso hidalgo") and texto.startswith("El ingenioso")
    )
    assert guardados == []
    assert web._leer("https://gutenberg.org/x.txt")[0] == 7


def test_selector_ofrece_pocas_herramientas():
    import json

    from asistente_core.agent import selector
    from asistente_core.tools.registry import esquemas

    from .test_core import _embed_falso

    s = selector.Selector(_embed_falso)
    con_skill = s.elegir(
        "x", pasos_skill="1. Llama a revisar_archivo y luego a poner_en_cuarentena."
    )
    assert con_skill[: len(selector.BASE)] == list(selector.BASE)
    assert {"revisar_archivo", "poner_en_cuarentena"} <= set(con_skill)
    assert len(con_skill) == len(selector.BASE) + 2

    sin_skill = s.elegir("crear documento pdf con un resumen")
    assert (
        "crear_documento" in sin_skill
        and len(sin_skill) <= len(selector.BASE) + selector.MAS_PARECIDAS
    )
    # lo que se usó hace poco sigue disponible
    usadas = selector.usadas_en(
        [{"role": "assistant", "tool_calls": [{"function": {"name": "ver_cuarentena"}}]}]
    )
    assert "ver_cuarentena" in s.elegir("y el otro?", usadas=usadas)
    # sin embeddings, solo las básicas
    assert selector.Selector(None).elegir("hola") == list(selector.BASE)
    # cabe de sobra: menos de la mitad que todas
    todas = len(json.dumps(esquemas(), ensure_ascii=False))
    ofrecidas = len(json.dumps(selector.esquemas_de(sin_skill), ensure_ascii=False))
    assert ofrecidas < todas / 2
