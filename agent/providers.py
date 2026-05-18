"""
LLM provider abstraction — supports Groq (cloud) and Ollama (local).
Both expose OpenAI-compatible endpoints, so the implementation is shared.
"""
import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config


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
        """Single chat completion. Returns the message dict from the response."""
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

        for attempt in range(4):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=90)
            except requests.exceptions.Timeout:
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
