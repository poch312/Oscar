import re
from pathlib import Path
from datetime import datetime

GENERADOS_DIR = Path("data/generados")

TOOL_DEFINITIONS = [
    {
        "name": "guardar_documento",
        "description": (
            "Guarda un documento generado en el sistema de archivos para que el docente pueda descargarlo. "
            "Llama esta herramienta siempre que generes un documento completo listo para usar: "
            "planeaciones, guías, talleres, rúbricas, evaluaciones, mallas curriculares, informes, actas, proyectos, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {
                    "type": "string",
                    "description": "Título descriptivo del documento (ej: 'Planeación_Matemáticas_Grado7_Periodo2').",
                },
                "contenido": {
                    "type": "string",
                    "description": "Contenido completo del documento en texto plano con formato Markdown.",
                },
                "tipo_documento": {
                    "type": "string",
                    "enum": [
                        "planeacion",
                        "guia",
                        "taller",
                        "rubrica",
                        "evaluacion",
                        "malla_curricular",
                        "informe",
                        "acta",
                        "proyecto",
                        "secuencia_didactica",
                        "otro",
                    ],
                    "description": "Tipo de documento educativo.",
                },
            },
            "required": ["titulo", "contenido", "tipo_documento"],
        },
    }
]


def guardar_documento(titulo: str, contenido: str, tipo_documento: str) -> dict:
    """Save a generated document to disk and return its path."""
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
        "message": f"Documento guardado exitosamente como '{filename}'.",
    }


def execute_tool(name: str, tool_input: dict) -> dict:
    if name == "guardar_documento":
        return guardar_documento(
            titulo=tool_input["titulo"],
            contenido=tool_input["contenido"],
            tipo_documento=tool_input["tipo_documento"],
        )
    return {"success": False, "message": f"Herramienta '{name}' no reconocida."}
