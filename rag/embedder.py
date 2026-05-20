"""
Embedding via Ollama local API.
Pull the model once: ollama pull nomic-embed-text
"""
import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config

_OLLAMA_HOST = Config.OLLAMA_BASE_URL.replace("/v1", "")
_MODEL = Config.EMBED_MODEL


def get_embedding(text: str) -> list[float] | None:
    """Returns embedding vector or None if Ollama/model unavailable."""
    try:
        resp = requests.post(
            f"{_OLLAMA_HOST}/api/embeddings",
            json={"model": _MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception:
        return None


def is_available() -> bool:
    return get_embedding("test") is not None
