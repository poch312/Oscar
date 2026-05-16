import os
import json
import time
from dotenv import load_dotenv
import requests

from .prompts import SYSTEM_PROMPT
from .tools import execute_tool
from . import memory

load_dotenv()

GROQ_BASE = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OSCAR_MODEL", "llama-3.3-70b-versatile")

_TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "buscar_en_base",
            "description": (
                "Busca información en la base de conocimiento institucional. "
                "Úsala SIEMPRE que el docente pida estándares básicos, DBA, formatos "
                "institucionales, lineamientos curriculares u otros documentos de referencia. "
                "Es la fuente principal de verdad — consúltala antes de responder sobre normativa o formatos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": (
                            "Términos de búsqueda específicos "
                            "(ej: 'DBA matemáticas grado 9', 'estándares álgebra', 'formato plan de área')"
                        ),
                    }
                },
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
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
        },
    }
]


class OscarAgent:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no está configurada en el archivo .env")
        self.model = DEFAULT_MODEL

    def chat(self, user_message: str) -> tuple[str, list[dict]]:
        memory.add_message(self.session_id, "user", user_message)
        messages = self._build_messages(memory.get_messages(self.session_id))
        saved_files: list[dict] = []
        text = self._run(messages, saved_files)
        memory.add_message(self.session_id, "assistant", text)
        return text, saved_files

    def process_upload(self, context_msg: str) -> tuple[str, list[dict]]:
        """Send document context to Groq. Stored as 'system' role, hidden in the UI."""
        memory.add_message(self.session_id, "system", context_msg)
        messages = self._build_messages(memory.get_messages(self.session_id))
        saved_files: list[dict] = []
        text = self._run(messages, saved_files)
        memory.add_message(self.session_id, "assistant", text)
        return text, saved_files

    def _run(self, messages: list[dict], saved_files: list[dict]) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": _TOOL_SCHEMA,
            "tool_choice": "auto",
            "max_tokens": 8192,
        }
        for attempt in range(4):
            resp = requests.post(GROQ_BASE, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if not resp.ok:
                try:
                    detail = resp.json().get("error", {}).get("message", resp.text[:400])
                except Exception:
                    detail = resp.text[:400]
                raise ValueError(f"Error de Groq ({resp.status_code}): {detail}")
            break
        data = resp.json()

        if "choices" not in data or not data["choices"]:
            raise ValueError(f"Respuesta inesperada de Groq: {data}")

        choice = data["choices"][0]
        msg = choice["message"]
        tool_calls = msg.get("tool_calls") or []

        if tool_calls:
            messages = messages + [msg]
            tool_results = []
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(name, args)
                if name == "guardar_documento" and result.get("success"):
                    saved_files.append({
                        "filename": result["filename"],
                        "filepath": result["filepath"],
                    })
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
            messages = messages + tool_results
            return self._run(messages, saved_files)

        return (msg.get("content") or "").strip()

    def _build_messages(self, history: list[dict]) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in history:
            role = msg["role"]
            if role not in ("user", "assistant", "system"):
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
            # "system" role in memory = document upload context → sent as "user"
            api_role = "user" if role == "system" else role
            messages.append({"role": api_role, "content": text})
        return messages
