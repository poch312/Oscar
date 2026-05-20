"""
LLM provider abstraction — supports Groq (cloud) and Ollama (local).
Both expose OpenAI-compatible endpoints so the implementation is shared.
Auto-trims payload to stay within provider byte limits.
"""
import sys
import json
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config

# Safe payload ceiling in bytes. Groq's free tier rejects requests above ~32KB.
_MAX_PAYLOAD_BYTES = 24_000


class LLMProvider:
    def __init__(self):
        if Config.PROVIDER == "ollama":
            self.base_url = Config.OLLAMA_BASE_URL
            self.model = Config.OLLAMA_MODEL
            self.api_key = "ollama"
            self.provider_name = f"Ollama ({self.model})"
        else:
            if not Config.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY no está configurada en .env")
            self.base_url = Config.GROQ_BASE_URL
            self.model = Config.GROQ_MODEL
            self.api_key = Config.GROQ_API_KEY
            self.provider_name = f"Groq ({self.model})"

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Single chat completion. Auto-trims history if payload exceeds size limit."""
        messages = self._fit_payload(messages, tools)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": Config.MAX_TOKENS,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"

        # Ollama on CPU can take several minutes for long responses
        timeout = 600 if Config.PROVIDER == "ollama" else 90

        for attempt in range(4):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            except requests.exceptions.Timeout:
                if Config.PROVIDER == "ollama":
                    raise ValueError("El modelo local tardó demasiado. Intenta con una pregunta más corta o usa qwen2.5:3b.")
                raise ValueError("Tiempo de espera agotado. La red es lenta — intenta de nuevo.")

            if resp.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if not resp.ok:
                try:
                    detail = resp.json().get("error", {}).get("message", resp.text[:500])
                except Exception:
                    detail = resp.text[:500]
                raise ValueError(f"Error del proveedor LLM ({resp.status_code}): {detail}")
            break

        data = resp.json()
        if "choices" not in data or not data["choices"]:
            raise ValueError(f"Respuesta inesperada del proveedor: {data}")

        return data["choices"][0]["message"]

    def _fit_payload(self, messages: list[dict], tools: list[dict] | None) -> list[dict]:
        """Remove oldest non-system messages until payload fits within byte limit."""
        while True:
            payload = {"model": self.model, "messages": messages, "max_tokens": Config.MAX_TOKENS}
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            if size <= _MAX_PAYLOAD_BYTES:
                break

            # Find oldest removable message (not system, not the last user message)
            removable = [i for i, m in enumerate(messages) if m["role"] != "system"]
            if len(removable) > 1:
                messages = [m for i, m in enumerate(messages) if i != removable[0]]
            else:
                # Can't trim further — truncate system prompt as last resort
                sys_msg = messages[0]["content"]
                messages[0] = {**messages[0], "content": sys_msg[: len(sys_msg) // 2]}
                break

        return messages
