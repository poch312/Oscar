"""
ChromaDB vector store for semantic document search.
Falls back gracefully if chromadb is not installed.
"""
from pathlib import Path

_CHROMA_PATH = str(Path("data/vectordb"))
_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
        _client = chromadb.PersistentClient(path=_CHROMA_PATH)
        _collection = _client.get_or_create_collection(
            name="oscar_kb",
            metadata={"hnsw:space": "cosine"},
        )
        return _collection
    except Exception:
        return None


def is_available() -> bool:
    return _get_collection() is not None


def index_chunks(filename: str, chunks: list[str], embeddings: list[list[float]]) -> None:
    col = _get_collection()
    if col is None:
        return
    # Remove existing chunks for this file before re-indexing
    try:
        existing = col.get(where={"filename": filename})
        if existing["ids"]:
            col.delete(ids=existing["ids"])
    except Exception:
        pass
    ids = [f"{filename}::{i}" for i in range(len(chunks))]
    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=[{"filename": filename} for _ in chunks],
    )


def search(query_embedding: list[float], limit: int = 3) -> list[dict]:
    col = _get_collection()
    if col is None:
        return []
    try:
        count = col.count()
        if count == 0:
            return []
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=min(limit, count),
        )
        return [
            {
                "filename": results["metadatas"][0][i]["filename"],
                "content": results["documents"][0][i],
            }
            for i in range(len(results["documents"][0]))
        ]
    except Exception:
        return []


def delete_file(filename: str) -> None:
    col = _get_collection()
    if col is None:
        return
    try:
        existing = col.get(where={"filename": filename})
        if existing["ids"]:
            col.delete(ids=existing["ids"])
    except Exception:
        pass
