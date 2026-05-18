import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── LLM Provider ──────────────────────────────────────────────────────────
    # "groq" (cloud, API key required) | "ollama" (local, no API key needed)
    PROVIDER = os.getenv("LLM_PROVIDER", "groq")

    # Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_BASE_URL = "https://api.groq.com/openai/v1"

    # Ollama (fully local — install Ollama and pull a model first)
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    # ── Generation ────────────────────────────────────────────────────────────
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))
    MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "25000"))

    # ── App ───────────────────────────────────────────────────────────────────
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
