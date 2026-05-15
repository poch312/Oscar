import os
import json
import time
from dotenv import load_dotenv
import requests

from .prompts import SYSTEM_PROMPT
from .tools import execute_tool
from . import memory

load_dotenv()

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = os.getenv("OSCAR_MODEL", "gemini-2.0-flash")

_TOOL_SCHEMA = {
    "function_declarations": [
        {
            "name": "guardar_documento",
            "description": (
                "Guarda un documento generado para que el docente pueda descargarlo. "
                "Llama esta herramienta siempre que generes un documento completo listo para usar: "
                "planeaciones, guías, talleres, rúbricas, evaluaciones, mallas curriculares, "
                "informes, actas, proyectos, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {
                        "type": "string",
                        "description": "Título descriptivo del documento.",
                    },
                    "contenido": {
                        "type": "string",
                        "description": "Contenido completo del documento en formato Markdown.",
                    },
                    "tipo_documento": {
                        "type": "string",
                        "enum": [
                            "planeacion", "guia", "taller", "rubrica", "evaluacion",
                            "malla_curricular", "informe", "acta", "proyecto",
                            "secuencia_didactica", "otro",
                        ],
                        "description": "Tipo de documento educativo.",
                    },
                },
                "required": ["titulo", "contenido", "tipo_documento"],
            },
        }
    ]
}


class OscarAgent:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY no está configurada en el archivo .env")
        self.model = DEFAULT_MODEL

    def chat(self, user_message: str) -> tuple[str, list[dict]]:
        memory.add_message(self.session_id, "user", user_message)
        contents = self._build_contents(memory.get_messages(self.session_id))
        saved_files: list[dict] = []
        text = self._run(contents, saved_files)
        memory.add_message(self.session_id, "assistant", text)
        return text, saved_files

    def _run(self, contents: list[dict], saved_files: list[dict]) -> str:
        url = f"{GEMINI_BASE}/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "tools": [_TOOL_SCHEMA],
            "generationConfig": {"maxOutputTokens": 8192},
        }
        for attempt in range(4):
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        data = resp.json()

        if "candidates" not in data or not data["candidates"]:
            feedback = data.get("promptFeedback", {})
            block_reason = feedback.get("blockReason", "")
            if block_reason:
                raise ValueError(f"Contenido bloqueado por Gemini ({block_reason}). Intenta reformular la solicitud.")
            raise ValueError(f"Respuesta inesperada de la API: {data}")

        candidate = data["candidates"][0]
        finish = candidate.get("finishReason", "STOP")

        if finish == "SAFETY" or "content" not in candidate:
            raise ValueError("La respuesta fue bloqueada por filtros de seguridad. Intenta reformular la solicitud.")

        parts = candidate["content"]["parts"]

        fn_calls = [p["functionCall"] for p in parts if "functionCall" in p]

        if fn_calls:
            tool_results = []
            for fc in fn_calls:
                result = execute_tool(fc["name"], fc["args"])
                if fc["name"] == "guardar_documento" and result.get("success"):
                    saved_files.append({
                        "filename": result["filename"],
                        "filepath": result["filepath"],
                    })
                tool_results.append({
                    "functionResponse": {
                        "name": fc["name"],
                        "response": {"result": json.dumps(result, ensure_ascii=False)},
                    }
                })

            contents = contents + [
                {"role": "model", "parts": parts},
                {"role": "user", "parts": tool_results},
            ]
            return self._run(contents, saved_files)

        return "\n".join(p["text"] for p in parts if "text" in p).strip()

    def _build_contents(self, messages: list[dict]) -> list[dict]:
        contents: list[dict] = []
        for msg in messages:
            role = msg["role"]
            if role not in ("user", "assistant"):
                continue
            content = msg["content"]
            if isinstance(content, list):
                text = "\n".join(
                    b["text"] for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip()
            else:
                text = str(content).strip()
            if not text:
                continue
            gemini_role = "user" if role == "user" else "model"
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].append({"text": text})
            else:
                contents.append({"role": gemini_role, "parts": [{"text": text}]})
        return contents
