"""
Unified hybrid retriever.
Combines ChromaDB semantic results with FTS5 keyword results for best coverage.
Deduplicates by content prefix so the model sees diverse, non-redundant chunks.
"""
from . import embedder, vector_store


def search(query: str, limit: int = 5) -> list[dict]:
    """
    Hybrid search: semantic results first, FTS5 fills remaining slots.
    Returns up to `limit` deduplicated {filename, content} dicts.
    """
    results: list[dict] = []
    seen: set[str] = set()

    def _add(r: dict) -> bool:
        key = r["content"][:120]
        if key not in seen:
            seen.add(key)
            results.append(r)
            return True
        return False

    # 1. Semantic search (best for meaning-based queries)
    if vector_store.is_available():
        emb = embedder.get_embedding(query)
        if emb is not None:
            for r in vector_store.search(emb, limit):
                _add(r)

    # 2. FTS5 keyword search fills remaining slots (good for exact terms like "DBA", "Artículo 3")
    if len(results) < limit:
        from agent import memory
        for r in memory.search_kb(query, limit):
            _add(r)
            if len(results) >= limit:
                break

    return results[:limit]


def search_mode() -> str:
    if vector_store.is_available() and embedder.is_available():
        return "semántico + FTS5"
    return "FTS5"
