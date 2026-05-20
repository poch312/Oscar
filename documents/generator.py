"""
Professional DOCX generation from Markdown content.
Handles headings, bold, bullets, numbered lists, tables, and paragraphs.
Falls back gracefully if python-docx is not installed.
"""
import re
from pathlib import Path
from datetime import datetime

GENERADOS_DIR = Path("data/generados")

try:
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False


def _safe_filename(titulo: str, tipo: str) -> str:
    safe = re.sub(r"[^\w\s-]", "", titulo).strip().replace(" ", "_")[:60]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{tipo}_{safe}_{ts}"


def _apply_inline(para, text: str):
    """Apply bold/italic formatting within a paragraph."""
    parts = re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = para.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("*") and part.endswith("*"):
            run = para.add_run(part[1:-1])
            run.italic = True
        else:
            para.add_run(part)


def _parse_table(lines: list[str], doc) -> int:
    """Parse markdown table and add to doc. Returns number of lines consumed."""
    table_lines = []
    for line in lines:
        if "|" in line:
            table_lines.append(line)
        else:
            break

    rows = []
    for line in table_lines:
        if re.match(r"^\s*\|[-:\s|]+\|\s*$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells:
            rows.append(cells)

    if not rows:
        return 0

    max_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=max_cols)
    table.style = "Table Grid"

    for i, row_data in enumerate(rows):
        row = table.rows[i]
        for j, cell_text in enumerate(row_data):
            if j < max_cols:
                cell = row.cells[j]
                cell.text = cell_text
                if i == 0:
                    for run in cell.paragraphs[0].runs:
                        run.bold = True

    doc.add_paragraph("")
    return len(table_lines)


def markdown_to_docx(titulo: str, contenido: str, tipo: str, institucion: str = "") -> Path:
    """Convert Markdown content to a .docx file. Returns the saved file path."""
    GENERADOS_DIR.mkdir(parents=True, exist_ok=True)
    base_name = _safe_filename(titulo, tipo)
    filepath = GENERADOS_DIR / f"{base_name}.docx"

    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3)
        section.right_margin = Cm(2.5)

    # Default font
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Header
    header = doc.sections[0].header
    hp = header.paragraphs[0]
    hp.text = institucion or "OSCAR — Sistema Pedagógico Inteligente"
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in hp.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x71, 0x8E, 0xA4)

    # Document title
    title_p = doc.add_heading(titulo, 0)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Metadata line
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run(f"{tipo.upper().replace('_', ' ')} | Generado por OSCAR | {datetime.now().strftime('%d/%m/%Y')}")
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x71, 0x8E, 0xA4)

    doc.add_paragraph("")

    # Parse content line by line
    lines = contenido.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            doc.add_paragraph("")
            i += 1
            continue

        # Headings (h4 first to avoid prefix collision with h3 etc.)
        if stripped.startswith("#### "):
            p = doc.add_heading(stripped[5:], 4)
            i += 1
            continue
        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], 3)
            i += 1
            continue
        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], 2)
            i += 1
            continue
        if stripped.startswith("# "):
            doc.add_heading(stripped[2:], 1)
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}$", stripped):
            doc.add_paragraph("─" * 60)
            i += 1
            continue

        # Table
        if stripped.startswith("|"):
            consumed = _parse_table(lines[i:], doc)
            i += consumed if consumed else 1
            continue

        # Nested bullet (2+ spaces or tab before - / *)
        if re.match(r"^[ \t]{2,}[-*]\s", line):
            para = doc.add_paragraph(style="List Bullet 2")
            _apply_inline(para, re.sub(r"^[ \t]+[-*]\s+", "", line))
            i += 1
            continue

        # Top-level bullet list
        if stripped.startswith("- ") or stripped.startswith("* "):
            para = doc.add_paragraph(style="List Bullet")
            _apply_inline(para, stripped[2:])
            i += 1
            continue

        # Nested numbered list
        nested_num = re.match(r"^[ \t]{2,}(\d+)\.\s+(.+)$", line)
        if nested_num:
            para = doc.add_paragraph(style="List Number 2")
            _apply_inline(para, nested_num.group(2))
            i += 1
            continue

        # Numbered list
        num_match = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if num_match:
            para = doc.add_paragraph(style="List Number")
            _apply_inline(para, num_match.group(2))
            i += 1
            continue

        # Regular paragraph
        para = doc.add_paragraph()
        _apply_inline(para, stripped)
        i += 1

    # Footer
    footer = doc.sections[0].footer
    fp = footer.paragraphs[0]
    fp.text = f"Documento generado por OSCAR | {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in fp.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x71, 0x8E, 0xA4)

    doc.save(filepath)
    return filepath


def save_document(titulo: str, contenido: str, tipo: str, institucion: str = "") -> dict:
    """
    Save document. Returns DOCX if python-docx is available, TXT as fallback.
    """
    GENERADOS_DIR.mkdir(parents=True, exist_ok=True)
    base_name = _safe_filename(titulo, tipo)

    if DOCX_AVAILABLE:
        try:
            filepath = markdown_to_docx(titulo, contenido, tipo, institucion)
            return {
                "success": True,
                "filename": filepath.name,
                "filepath": str(filepath),
                "format": "docx",
                "message": f"Documento Word guardado: '{filepath.name}'.",
            }
        except Exception as e:
            pass  # Fall through to TXT

    # TXT fallback
    filepath = GENERADOS_DIR / f"{base_name}.txt"
    filepath.write_text(contenido, encoding="utf-8")
    return {
        "success": True,
        "filename": filepath.name,
        "filepath": str(filepath),
        "format": "txt",
        "message": f"Documento guardado: '{filepath.name}'.",
    }
