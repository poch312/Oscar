import sqlite3
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/oscar.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    conn = _connect()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS kb_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            chunks INTEGER DEFAULT 0,
            uploaded_at TEXT DEFAULT (datetime('now'))
        );
    """)
    try:
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
                filename UNINDEXED,
                content,
                tokenize="unicode61"
            )
        """)
    except Exception:
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
                filename UNINDEXED,
                content
            )
        """)
    conn.commit()
    conn.close()


# ── Session helpers ────────────────────────────────────────────────────────────

def create_session(name: str = "Nueva conversación") -> str:
    session_id = str(uuid.uuid4())
    conn = _connect()
    conn.execute(
        "INSERT INTO sessions (id, name, created_at) VALUES (?, ?, ?)",
        (session_id, name, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return session_id


def get_sessions() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id, name, created_at FROM sessions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]


def update_session_name(session_id: str, name: str) -> None:
    conn = _connect()
    conn.execute("UPDATE sessions SET name = ? WHERE id = ?", (name, session_id))
    conn.commit()
    conn.close()


def delete_session(session_id: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


# ── Message helpers ────────────────────────────────────────────────────────────

def add_message(session_id: str, role: str, content) -> None:
    content_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, content_str, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_messages(session_id: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    messages = []
    for role, content_str in rows:
        try:
            content = json.loads(content_str)
        except (json.JSONDecodeError, TypeError):
            content = content_str
        messages.append({"role": role, "content": content})
    return messages


# ── Session document helpers ───────────────────────────────────────────────────

def add_document(session_id: str, filename: str, content: str) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO documents (session_id, filename, content, uploaded_at) VALUES (?, ?, ?, ?)",
        (session_id, filename, content, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_documents(session_id: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id, filename, uploaded_at FROM documents WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "filename": r[1], "uploaded_at": r[2]} for r in rows]


def document_exists(session_id: str, filename: str) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT id FROM documents WHERE session_id = ? AND filename = ?",
        (session_id, filename),
    ).fetchone()
    conn.close()
    return row is not None


# ── Knowledge base helpers ─────────────────────────────────────────────────────

def _chunk_text(text: str, size: int = 800) -> list[str]:
    """Split text into chunks on paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= size:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) > size:
                for i in range(0, len(para), size):
                    chunks.append(para[i : i + size])
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks or [text[:size]]


def _fts_query(query: str) -> str:
    """Sanitize query for FTS5: extract word tokens."""
    terms = re.findall(r"[\wÀ-ɏ]+", query)
    return " ".join(f'"{t}"' for t in terms) if terms else '""'


def add_kb_document(filename: str, text: str) -> int:
    """Chunk text and index in the knowledge base. Returns chunk count."""
    chunks = _chunk_text(text)
    conn = _connect()
    conn.execute("DELETE FROM kb_fts WHERE filename = ?", (filename,))
    conn.execute("DELETE FROM kb_documents WHERE filename = ?", (filename,))
    for chunk in chunks:
        conn.execute(
            "INSERT INTO kb_fts (filename, content) VALUES (?, ?)",
            (filename, chunk),
        )
    conn.execute(
        "INSERT OR REPLACE INTO kb_documents (filename, chunks, uploaded_at) VALUES (?, ?, ?)",
        (filename, len(chunks), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return len(chunks)


def search_kb(query: str, limit: int = 5) -> list[dict]:
    """Full-text search over the knowledge base."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT filename, content FROM kb_fts WHERE content MATCH ? ORDER BY rank LIMIT ?",
            (_fts_query(query), limit),
        ).fetchall()
    except Exception:
        rows = []
    conn.close()
    return [{"filename": r[0], "content": r[1]} for r in rows]


def list_kb_documents() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT filename, chunks, uploaded_at FROM kb_documents ORDER BY uploaded_at DESC"
    ).fetchall()
    conn.close()
    return [{"filename": r[0], "chunks": r[1], "uploaded_at": r[2]} for r in rows]


def delete_kb_document(filename: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM kb_fts WHERE filename = ?", (filename,))
    conn.execute("DELETE FROM kb_documents WHERE filename = ?", (filename,))
    conn.commit()
    conn.close()


def kb_document_exists(filename: str) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT id FROM kb_documents WHERE filename = ?", (filename,)
    ).fetchone()
    conn.close()
    return row is not None
