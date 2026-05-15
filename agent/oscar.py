import os
import json
from pathlib import Path
from dotenv import load_dotenv
import anthropic

from .prompts import SYSTEM_PROMPT
from .tools import TOOL_DEFINITIONS, execute_tool
from . import memory

load_dotenv()

DEFAULT_MODEL = os.getenv("OSCAR_MODEL", "claude-opus-4-7")
MAX_TOKENS = 8192


class OscarAgent:
    """Main agent class. One instance per session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY no está configurada en el archivo .env")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = DEFAULT_MODEL

    def chat(self, user_message: str) -> tuple[str, list[dict]]:
        """
        Send a user message and return (assistant_text, saved_files).
        saved_files is a list of {"filename": ..., "filepath": ...} dicts.
        """
        memory.add_message(self.session_id, "user", user_message)
        messages = memory.get_messages(self.session_id)
        saved_files = []
        assistant_text = self._run_turn(messages, saved_files)
        return assistant_text, saved_files

    def _run_turn(self, messages: list[dict], saved_files: list[dict]) -> str:
        """Execute one turn, handling tool_use loops."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        assistant_content = response.content
        text_parts: list[str] = []
        tool_uses: list = []

        for block in assistant_content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        serializable_content = []
        for block in assistant_content:
            if block.type == "text":
                serializable_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                serializable_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        memory.add_message(self.session_id, "assistant", serializable_content)

        if response.stop_reason == "tool_use" and tool_uses:
            tool_results = []
            for tool_use in tool_uses:
                result = execute_tool(tool_use.name, tool_use.input)
                if tool_use.name == "guardar_documento" and result.get("success"):
                    saved_files.append({
                        "filename": result["filename"],
                        "filepath": result["filepath"],
                    })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            tool_result_message = {"role": "user", "content": tool_results}
            memory.add_message(self.session_id, "user", tool_results)

            updated_messages = memory.get_messages(self.session_id)
            return self._run_turn(updated_messages, saved_files)

        return "\n".join(text_parts).strip()
