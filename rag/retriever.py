"""
Unified retriever.
Priority: ChromaDB semantic search → SQLite FTS5 keyword search.
The rest of the app calls only this module — backend is transparent.
"""
from . import embedder, vector_store


def search(query: str, limit: int = 3) -> list[dict]:
    """Search knowledge base. Returns list of {filename, content} dicts."""
    # 1. Try semantic search
    if vector_store.is_available():
        emb = embedder.get_embedding(query)
        if emb is not None:
            results = vector_store.search(emb, limit)
            if results:
                return results

    # 2. Fall back to FTS5 keyword search
    from agent import memory
    return memory.search_kb(query, limit)


def search_mode() -> str:
    """Returns the active search mode for display purposes."""
    if vector_store.is_available() and embedder.is_available():
        return "semántico"
    return "FTS5"
