"""Crear y leer documentos (PDF, Word y texto).

Moni escribe en un Markdown sencillo y aquí se convierte:
  # Título, ## Sección, ### Subsección
  - viñeta  /  * viñeta  /  1. lista numerada
  **negrita** y *cursiva*
  párrafos separados por una línea en blanco

PDF con reportlab (BSD) y Word con python-docx (MIT). Leer: pypdf (BSD), python-docx y texto.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Bloque:
    tipo: str  # "h1" | "h2" | "h3" | "p" | "vineta" | "numero"
    texto: str


def bloques(markdown: str) -> list[Bloque]:
    salida: list[Bloque] = []
    parrafo: list[str] = []

    def cerrar() -> None:
        if parrafo:
            salida.append(Bloque("p", " ".join(parrafo)))
            parrafo.clear()

    for linea in markdown.replace("\r\n", "\n").split("\n"):
        s = linea.strip()
        if not s:
            cerrar()
            continue
        if m := re.match(r"^(#{1,3})\s+(.*)$", s):
            cerrar()
            salida.append(Bloque(f"h{len(m[1])}", m[2].strip()))
        elif m := re.match(r"^[-*•]\s+(.*)$", s):
            cerrar()
            salida.append(Bloque("vineta", m[1]))
        elif m := re.match(r"^\d+[.)]\s+(.*)$", s):
            cerrar()
            salida.append(Bloque("numero", m[1]))
        else:
            parrafo.append(s)
    cerrar()
    return salida


def _trozos_en_linea(texto: str) -> list[tuple[str, bool, bool]]:
    """'hola **mundo** *x*' -> [(texto, negrita, cursiva), ...]"""
    partes = re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)", texto)
    salida = []
    for p in partes:
        if not p:
            continue
        if p.startswith("**") and p.endswith("**") and len(p) > 4:
            salida.append((p[2:-2], True, False))
        elif p.startswith("*") and p.endswith("*") and len(p) > 2:
            salida.append((p[1:-1], False, True))
        else:
            salida.append((p, False, False))
    return salida


def nombre_archivo(titulo: str, extension: str, carpeta: Path) -> Path:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", titulo).strip().rstrip(".") or "Documento"
    base = base[:80]
    ruta = carpeta / f"{base}.{extension}"
    n = 2
    while ruta.exists():  # nunca se sobrescribe
        ruta = carpeta / f"{base} ({n}).{extension}"
        n += 1
    return ruta


# ---------------------------------------------------------------- PDF


def crear_pdf(ruta: Path, titulo: str, markdown: str, autor: str = "Moni") -> None:
    from xml.sax.saxutils import escape

    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    estilos = getSampleStyleSheet()
    cuerpo = ParagraphStyle(
        "cuerpo", parent=estilos["BodyText"], fontSize=11, leading=15, alignment=TA_JUSTIFY
    )
    estilo = {
        "h1": ParagraphStyle("h1", parent=estilos["Heading1"], spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=estilos["Heading2"], spaceBefore=10),
        "h3": ParagraphStyle("h3", parent=estilos["Heading3"]),
        "p": cuerpo,
    }

    def marcado(texto: str) -> str:
        salida = []
        for t, negrita, cursiva in _trozos_en_linea(texto):
            t = escape(t)
            if negrita:
                t = f"<b>{t}</b>"
            if cursiva:
                t = f"<i>{t}</i>"
            salida.append(t)
        return "".join(salida)

    historia: list = []
    bs = bloques(markdown)
    if not bs or bs[0].tipo != "h1":
        historia.append(Paragraph(marcado(titulo), estilo["h1"]))
    lista: list = []
    lista_tipo = None

    def cerrar_lista() -> None:
        nonlocal lista, lista_tipo
        if lista:
            historia.append(
                ListFlowable(
                    lista,
                    bulletType="1" if lista_tipo == "numero" else "bullet",
                    start=None if lista_tipo == "numero" else "•",
                    bulletFormat="%s." if lista_tipo == "numero" else None,
                    leftIndent=14,
                )
            )
            historia.append(Spacer(1, 4))
        lista, lista_tipo = [], None

    for b in bs:
        if b.tipo in ("vineta", "numero"):
            if lista_tipo not in (None, b.tipo):
                cerrar_lista()
            lista_tipo = b.tipo
            lista.append(ListItem(Paragraph(marcado(b.texto), cuerpo)))
            continue
        cerrar_lista()
        historia.append(Paragraph(marcado(b.texto), estilo[b.tipo]))
        if b.tipo == "p":
            historia.append(Spacer(1, 4))
    cerrar_lista()

    def pie(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(2 * cm, 1.2 * cm, f"{titulo} · {datetime.now():%d/%m/%Y}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(ruta),
        pagesize=A4,
        title=titulo,
        author=autor,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    doc.build(historia, onFirstPage=pie, onLaterPages=pie)


# ---------------------------------------------------------------- Word


def crear_docx(ruta: Path, titulo: str, markdown: str, autor: str = "Moni") -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.core_properties.title = titulo
    doc.core_properties.author = autor
    doc.styles["Normal"].font.size = Pt(11)
    bs = bloques(markdown)
    if not bs or bs[0].tipo != "h1":
        doc.add_heading(titulo, level=0)

    def escribir(parrafo, texto: str) -> None:
        for t, negrita, cursiva in _trozos_en_linea(texto):
            run = parrafo.add_run(t)
            run.bold = negrita or None
            run.italic = cursiva or None

    for b in bs:
        if b.tipo == "h1":
            escribir(doc.add_heading(level=0 if b is bs[0] else 1), b.texto)
        elif b.tipo in ("h2", "h3"):
            escribir(doc.add_heading(level=int(b.tipo[1])), b.texto)
        elif b.tipo == "vineta":
            escribir(doc.add_paragraph(style="List Bullet"), b.texto)
        elif b.tipo == "numero":
            escribir(doc.add_paragraph(style="List Number"), b.texto)
        else:
            escribir(doc.add_paragraph(), b.texto)
    doc.save(str(ruta))


def crear_txt(ruta: Path, titulo: str, markdown: str) -> None:
    contenido = markdown if markdown.lstrip().startswith("#") else f"# {titulo}\n\n{markdown}"
    ruta.write_text(contenido.strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------- leer


LEIBLES = {".pdf", ".docx", ".txt", ".md", ".csv", ".html", ".htm", ".rtf", ".json"}


def leer_texto(ruta: Path, max_caracteres: int = 5_000_000) -> str:
    ruta = Path(ruta)
    ext = ruta.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        lector = PdfReader(str(ruta))
        if lector.is_encrypted:
            try:
                lector.decrypt("")
            except Exception as exc:
                raise ValueError("El PDF está protegido con contraseña.") from exc
        partes: list[str] = []
        total = 0
        for pagina in lector.pages:
            t = pagina.extract_text() or ""
            partes.append(t)
            total += len(t)
            if total > max_caracteres:
                break
        texto = "\n".join(partes)
        if len(texto.strip()) < 50:
            raise ValueError(
                "El PDF casi no tiene texto (puede ser un escaneo de imágenes): no lo puedo leer."
            )
        return texto[:max_caracteres]
    if ext == ".docx":
        from docx import Document

        doc = Document(str(ruta))
        return "\n".join(p.text for p in doc.paragraphs)[:max_caracteres]
    if ext in (".html", ".htm"):
        import trafilatura

        return (trafilatura.extract(ruta.read_text(errors="ignore")) or "")[:max_caracteres]
    if ext in LEIBLES or ext == "":
        crudo = ruta.read_bytes()[: max_caracteres * 4]
        for codificacion in ("utf-8", "cp1252", "latin-1"):
            try:
                return crudo.decode(codificacion)[:max_caracteres]
            except UnicodeDecodeError:
                continue
    raise ValueError(f"No sé leer archivos {ext or 'sin extensión'} (sí: PDF, Word, texto).")
