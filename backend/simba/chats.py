"""
chats.py — the chat list and run-history store: one SQLite database that remembers every chat's
title and timestamps, plus each turn's trace history ("runs"), across restarts.

Where it sits: api.py (the step-6 integration, not this file) creates one ChatStore at startup and
hands it to chats_api.py's router via `request.app.state.chats`. The graph's actual conversation
messages live separately, in the LangGraph checkpointer (AsyncSqliteSaver) — this store only holds
what the sidebar and run-history views need: chat metadata and past runs.

Library concept: aiosqlite is asyncio's SQLite driver — the same SQL as the stdlib `sqlite3` module,
but every call is `await`ed so a slow disk write never blocks the event loop the rest of the app
(FastAPI, LangGraph) shares.
"""

# Needed because ChatStore defines a `list` method: without this, a later annotation like
# `list[dict]` would resolve to that method instead of the builtin. Deferring annotation evaluation
# (they become strings, not looked up at class-body time) sidesteps the name clash.
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import aiosqlite


def _now() -> str:
    """The current time as ISO 8601 UTC, e.g. "2026-09-26T14:03:11.123456+00:00" (docs/contracts.md § 10)."""
    return datetime.now(timezone.utc).isoformat()


def title_from(message: str) -> str:
    """Build a chat's starting title from its first message (Q9 in the design book).

    Steps: (1) collapse all whitespace to single spaces and trim the ends, (2) cut to 40 characters
    with a trailing "…" if it was cut, (3) an empty result becomes "New chat" so no chat is ever
    titled "".

    Example: title_from("  plan   a trip\\nto Rome  ") -> "plan a trip to Rome"
    """
    # 1. Collapse all whitespace to single spaces and trim the ends.
    collapsed = " ".join(message.split())
    # 2. Cut to 40 characters with a trailing "…" if it was cut.
    title = collapsed[:40] + "…" if len(collapsed) > 40 else collapsed
    # 3. An empty result becomes "New chat" so no chat is ever titled "".
    return title or "New chat"


class ChatStore:
    """SQLite-backed store for chat metadata and run history (docs/contracts.md § 10).

    Two tables: `chats` (one row per chat) and `runs` (one row per finished turn, with the trace
    lines and summary JSON-encoded so a mixed-shape Python value fits one TEXT column). Always build
    one with `await ChatStore.open(db_path)`, never the constructor directly, so the tables exist
    before any query runs.
    """

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    @classmethod
    async def open(cls, db_path: str) -> "ChatStore":
        """Connect to `db_path` (file created if missing) and create the tables if they don't exist yet."""
        db = await aiosqlite.connect(db_path)
        await db.execute(
            """CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, prompt TEXT NOT NULL,
                lines TEXT NOT NULL, summary TEXT, error TEXT, created_at TEXT NOT NULL
            )"""
        )
        await db.commit()
        return cls(db)

    async def create(self, title: str, chat_id: str | None = None) -> dict:
        """Insert a new chat and return it as a dict. `chat_id` defaults to a fresh uuid4 hex (api.py
        picks the id so it can use the same id for the graph's checkpointer thread)."""
        chat_id = chat_id or uuid.uuid4().hex
        now = _now()
        await self._db.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (chat_id, title, now, now),
        )
        await self._db.commit()
        return {"id": chat_id, "title": title, "created_at": now, "updated_at": now}

    async def list(self) -> list[dict]:
        """All chats, newest `updated_at` first — so a chat you just used sorts to the top of the
        sidebar. Ties (two chats updated in the same microsecond) break on `rowid` — SQLite's hidden,
        always-increasing insertion-order column — so the order is deterministic instead of
        depending on how SQLite happens to walk ties."""
        cursor = await self._db.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC, rowid DESC"
        )
        rows = await cursor.fetchall()
        return [dict(zip(("id", "title", "created_at", "updated_at"), row)) for row in rows]

    async def get(self, chat_id: str) -> dict | None:
        """One chat by id, or None if it doesn't exist (callers turn that into a 404)."""
        cursor = await self._db.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return dict(zip(("id", "title", "created_at", "updated_at"), row)) if row else None

    async def rename(self, chat_id: str, title: str) -> dict | None:
        """Set a chat's title and bump updated_at to now. Returns the updated chat, or None if it
        doesn't exist."""
        if await self.get(chat_id) is None:
            return None
        await self._db.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, _now(), chat_id)
        )
        await self._db.commit()
        return await self.get(chat_id)

    async def touch(self, chat_id: str) -> None:
        """Bump a chat's updated_at to now, e.g. after a new turn, so it sorts to the top of `list()`."""
        await self._db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), chat_id))
        await self._db.commit()

    async def delete(self, chat_id: str) -> bool:
        """Delete a chat and its runs. Returns whether a chat actually existed to delete."""
        if await self.get(chat_id) is None:
            return False
        await self._db.execute("DELETE FROM runs WHERE chat_id = ?", (chat_id,))
        await self._db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        await self._db.commit()
        return True

    async def add_run(
        self, chat_id: str, prompt: str, lines: list[dict], summary: dict | None, error: str | None
    ) -> None:
        """Record one finished turn. `lines` (trace events) and `summary` are stored as JSON text and
        decoded back into Python values by `runs()`."""
        await self._db.execute(
            "INSERT INTO runs (chat_id, prompt, lines, summary, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                prompt,
                json.dumps(lines),
                json.dumps(summary) if summary is not None else None,
                error,
                _now(),
            ),
        )
        await self._db.commit()

    async def runs(self, chat_id: str) -> list[dict]:
        """A chat's runs, oldest first (the order a chat view replays them in), lines/summary decoded
        back from JSON so callers get plain Python values, matching the frontend's `Run` type."""
        cursor = await self._db.execute(
            "SELECT prompt, lines, summary, error FROM runs WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "prompt": prompt,
                "lines": json.loads(lines),
                "summary": json.loads(summary) if summary is not None else None,
                "error": error,
            }
            for prompt, lines, summary, error in rows
        ]

    async def close(self) -> None:
        """Close the underlying database connection (mirrors AsyncSqliteSaver's lifecycle in api.py)."""
        await self._db.close()
