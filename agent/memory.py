import sqlite3
import json
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
    """)
    conn.commit()
    conn.close()


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


def add_message(session_id: str, role: str, content) -> None:
    """Store a message. content can be a string or a list (for tool_use blocks)."""
    content_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, content_str, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_messages(session_id: str) -> list[dict]:
    """Return messages in Claude API format."""
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
