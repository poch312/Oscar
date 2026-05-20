"""
Document indexer — writes to both SQLite FTS5 and ChromaDB.
FTS5 is always updated (reliable fallback).
ChromaDB is updated when Ollama embeddings are available.
"""
from agent import memory
from . import embedder, vector_store


def index_document(filename: str, text: str) -> dict:
    """
    Index a document in the knowledge base.
    Returns: {chunks, semantic, keyword}
    """
    # Always index in FTS5
    chunks = memory._chunk_text(text)
    memory.add_kb_document(filename, text)
    result = {"chunks": len(chunks), "semantic": False, "keyword": True}

    # Also index in ChromaDB with embeddings when available
    if vector_store.is_available() and embedder.is_available():
        try:
            embeddings = [embedder.get_embedding(chunk) for chunk in chunks]
            valid = [(c, e) for c, e in zip(chunks, embeddings) if e is not None]
            if valid:
                good_chunks, good_embeddings = zip(*valid)
                vector_store.index_chunks(filename, list(good_chunks), list(good_embeddings))
                result["semantic"] = True
        except Exception as e:
            print(f"[RAG] Semantic indexing skipped: {e}")

    return result


def delete_document(filename: str) -> None:
    memory.delete_kb_document(filename)
    vector_store.delete_file(filename)
