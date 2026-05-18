"""
OSCAR Agent — multi-agent orchestrator.

Architecture:
  User message
    → supervisor.detect_intent()        (keyword routing, 0 LLM calls)
    → build system prompt               (base + specialized extension + institutional context)
    → LLMProvider.complete()            (single LLM call per turn)
    → tool loop (buscar_en_base / guardar_documento)
    → response
"""
import json

from .prompts import SYSTEM_PROMPT
from .specialized_prompts import AGENT_PROMPTS
from .supervisor import detect_intent
from .providers import LLMProvider
from .tools import execute_tool
from . import memory

_TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "buscar_en_base",
            "description": (
                "Busca información en la base de conocimiento institucional. "
                "Úsala SIEMPRE que el docente pida estándares básicos, DBA, formatos "
                "institucionales, lineamientos curriculares u otros documentos de referencia. "
                "Es la fuente principal de verdad — consúltala antes de responder sobre normativa."
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
                "Llama esta herramienta SIEMPRE que generes un documento completo listo para usar: "
                "planeaciones, guías, talleres, rúbricas, evaluaciones, mallas, informes, actas, proyectos, etc."
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
    },
]


class OscarAgent:
    """Main agent. Maintains the same public interface as before."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.provider = LLMProvider()

    # ── Public interface ───────────────────────────────────────────────────────

    def chat(self, user_message: str) -> tuple[str, list[dict]]:
        memory.add_message(self.session_id, "user", user_message)
        intent = detect_intent(user_message)
        messages = self._build_messages(
            memory.get_messages(self.session_id), intent
        )
        saved_files: list[dict] = []
        text = self._run(messages, saved_files)
        memory.add_message(self.session_id, "assistant", text)
        return text, saved_files

    def process_upload(self, context_msg: str) -> tuple[str, list[dict]]:
        """Inject document context (stored as 'system', hidden in UI)."""
        memory.add_message(self.session_id, "system", context_msg)
        messages = self._build_messages(
            memory.get_messages(self.session_id), "general"
        )
        saved_files: list[dict] = []
        text = self._run(messages, saved_files)
        memory.add_message(self.session_id, "assistant", text)
        return text, saved_files

    # ── Internal ───────────────────────────────────────────────────────────────

    def _run(self, messages: list[dict], saved_files: list[dict]) -> str:
        msg = self.provider.complete(messages, tools=_TOOL_SCHEMA)
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return (msg.get("content") or "").strip()

        # Tool execution loop
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
                    "format": result.get("format", "txt"),
                })
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

        messages = messages + tool_results
        return self._run(messages, saved_files)

    def _build_messages(self, history: list[dict], intent: str) -> list[dict]:
        # Compose system prompt: base + specialized agent extension + institutional context
        ctx = memory.get_institutional_context()
        system_content = (
            SYSTEM_PROMPT
            + AGENT_PROMPTS.get(intent, "")
            + memory.build_institutional_prompt(ctx)
        )

        # Flatten history to plain text messages
        flat: list[dict] = []
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
            flat.append({"role": api_role, "content": text})

        # Trim to avoid unbounded context growth
        MAX_CHARS = getattr(__import__("config", fromlist=["Config"]).Config, "MAX_HISTORY_CHARS", 8_000)
        trimmed: list[dict] = []
        used = 0
        for msg in reversed(flat):
            used += len(msg["content"])
            if used > MAX_CHARS:
                break
            trimmed.insert(0, msg)

        # First message must be from user (OpenAI/Groq requirement)
        while trimmed and trimmed[0]["role"] != "user":
            trimmed.pop(0)

        return [{"role": "system", "content": system_content}] + trimmed
