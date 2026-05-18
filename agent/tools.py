import re
from pathlib import Path
from datetime import datetime

from . import memory

GENERADOS_DIR = Path("data/generados")


def guardar_documento(titulo: str, contenido: str, tipo_documento: str) -> dict:
    """Save document — DOCX if python-docx is available, TXT otherwise."""
    try:
        from documents.generator import save_document
        ctx = memory.get_institutional_context()
        institucion = ctx.get("nombre_institucion", "")
        return save_document(titulo, contenido, tipo_documento, institucion)
    except Exception:
        pass

    # Pure TXT fallback (no dependencies)
    GENERADOS_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\s-]", "", titulo).strip().replace(" ", "_")[:60]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{tipo_documento}_{safe_title}_{timestamp}.txt"
    filepath = GENERADOS_DIR / filename
    filepath.write_text(contenido, encoding="utf-8")
    return {
        "success": True,
        "filename": filename,
        "filepath": str(filepath),
        "format": "txt",
        "message": f"Documento guardado: '{filename}'.",
    }


def buscar_en_base(consulta: str) -> dict:
    results = memory.search_kb(consulta, limit=3)
    if not results:
        return {
            "found": False,
            "message": "No se encontró información relevante en la base de conocimiento para esa consulta.",
        }
    context = "\n\n---\n\n".join(
        f"[Fuente: {r['filename']}]\n{r['content']}" for r in results
    )
    sources = list(dict.fromkeys(r["filename"] for r in results))
    return {"found": True, "context": context, "fuentes": sources}


def execute_tool(name: str, tool_input: dict) -> dict:
    if name == "guardar_documento":
        return guardar_documento(
            titulo=tool_input["titulo"],
            contenido=tool_input["contenido"],
            tipo_documento=tool_input["tipo_documento"],
        )
    if name == "buscar_en_base":
        return buscar_en_base(consulta=tool_input["consulta"])
    return {"success": False, "message": f"Herramienta '{name}' no reconocida."}
