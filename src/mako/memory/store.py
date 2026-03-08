"""SQLite-backed conversation history."""

import json
import sqlite3
import time
import uuid
from pathlib import Path

from mako.providers.base import Message, ToolCall


class ConversationStore:
    """Persistent conversation history stored in SQLite.

    Each conversation is identified by a session_id. Messages are stored
    in order with role, content, and any tool calls.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                title TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tool_calls TEXT DEFAULT '[]',
                tool_call_id TEXT DEFAULT '',
                name TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at);
        """)
        self._conn.commit()

    def create_session(self, title: str = "") -> str:
        """Create a new conversation session. Returns the session ID."""
        session_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            "INSERT INTO sessions (id, created_at, updated_at, title) VALUES (?, ?, ?, ?)",
            (session_id, now, now, title),
        )
        self._conn.commit()
        return session_id

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str = "",
        tool_calls: list[ToolCall] | None = None,
        tool_call_id: str = "",
        name: str = "",
    ) -> None:
        """Save a message to the conversation history."""
        tc_json = json.dumps(
            [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in (tool_calls or [])]
        )
        now = time.time()
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, tc_json, tool_call_id, name, now),
        )
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        self._conn.commit()

    def get_history(self, session_id: str, limit: int = 50) -> list[Message]:
        """Retrieve conversation history for a session.

        Returns the most recent `limit` messages in chronological order.
        """
        rows = self._conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, name FROM messages "
            "WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()

        messages: list[Message] = []
        for row in reversed(rows):  # Reverse to get chronological order
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in json.loads(row["tool_calls"])
            ]
            messages.append(Message(
                role=row["role"],
                content=row["content"],
                tool_calls=tool_calls,
                tool_call_id=row["tool_call_id"],
                name=row["name"],
            ))

        return messages

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """List recent conversation sessions."""
        rows = self._conn.execute(
            "SELECT s.id, s.title, s.created_at, s.updated_at, "
            "  (SELECT COUNT(*) FROM messages WHERE session_id = s.id) as message_count "
            "FROM sessions s ORDER BY s.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()
