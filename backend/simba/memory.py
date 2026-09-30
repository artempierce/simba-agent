"""
memory.py — Simba's long-term memory of facts (#80, design book § Memory, D40–D45).

Where it sits: api.py opens one MemoryStore at startup, next to the ChatStore, on the same SQLite
file. memory_api.py (the Memory tab) reads and changes facts through it; the agent node reads the
core profile from it at the start of every turn (`core_profile`), so what you told Simba in one chat
is known in the next.

Key ideas:
- A fact has a kind, the same four Claude Code uses for its own memory (see KINDS). Only `user`
  facts make up the core profile that goes into every prompt (D43); the other kinds wait for the
  recall tool (#83).
- Everything is plain SQL on one table. Size limits are enforced here, in code, so no caller can
  store a fact longer than MAX_FACT_CHARS or more than MAX_FACTS facts (D40's code limits).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import aiosqlite

# The four kinds of fact (D40), as in Claude Code's own memory:
#   user       who the owner is: name, role, preferences, how they like answers
#   feedback   a correction or a confirmed way of working, with the reason
#   project    ongoing work, goals and dates
#   reference  a pointer to something outside (a site, a document, a dashboard)
KINDS = ("user", "feedback", "project", "reference")

# Longest fact, in characters: one or two sentences. A fact is a note, not a document.
MAX_FACT_CHARS = 300

# Most facts kept in total. Enough for a personal assistant; small enough that nothing grows forever.
MAX_FACTS = 200

# How many `user` facts go into every prompt (D43): the newest ones. ~15 short lines is a few hundred
# tokens — cheap on every turn, and it's what almost every answer can use.
CORE_PROFILE_LIMIT = 15

_COLUMNS = ("id", "kind", "text", "why", "source_chat_id", "created_at", "updated_at")

# #81: two facts of the same kind sharing at least this share of their key words are "the same fact
# said again" — `remember` updates the old one instead of adding a copy. 0.6 catches rewordings like
# "Works mostly in Python" vs "Mostly works in Python 3" without merging different facts.
DUPLICATE_OVERLAP = 0.6

# Short, common words that say nothing about a fact's content; left out when comparing facts.
_STOPWORDS = frozenset(
    "the a an and or but of to in on at for with from by as is are was were be been am i me my mine "
    "you your he she they them their it its this that these those we our us do does did not no yes "
    "so very really just about into over also than then there here have has had will would can could "
    "should like likes want wants".split()
)


def key_words(text: str) -> set[str]:
    """The words that carry a text's meaning, cut to their first 5 letters so "works" and "working"
    compare equal (a cheap stand-in for proper word stemming).

    Example: key_words("Sol mostly works in Python") -> {"sol", "mostl", "works", "pytho"}
    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:5] for w in words if w not in _STOPWORDS and len(w) > 1}


def overlap(a: set[str], b: set[str]) -> float:
    """Share of the smaller set's words that the two sets have in common (0.0 when either is empty).

    Example: overlap({"python", "works"}, {"python", "works", "mostl"}) -> 1.0
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _now() -> str:
    """The current time as ISO 8601 UTC (same format as chats.py)."""
    return datetime.now(timezone.utc).isoformat()


class MemoryFull(Exception):
    """Raised when adding a fact would pass MAX_FACTS. The API turns it into a 409."""


class MemoryStore:
    """SQLite-backed store for facts. Build it with `await MemoryStore.open(db_path)`.

    One table, `memory_facts`: a row per fact. `why` is optional context (mostly for feedback facts,
    where the reason is what makes the fact useful later). `source_chat_id` says which chat a fact
    came from, when it came from one (M2's `remember` tool will fill it; facts added in the Memory
    tab have none).
    """

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    @classmethod
    async def open(cls, db_path: str) -> MemoryStore:
        """Connect to `db_path` and create the table if it doesn't exist yet."""
        db = await aiosqlite.connect(db_path)
        await db.execute(
            """CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, text TEXT NOT NULL,
                why TEXT, source_chat_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        await db.commit()
        return cls(db)

    async def list_facts(self, kind: str | None = None) -> list[dict]:
        """All facts (or one kind's), newest change first — the order the Memory tab shows."""
        where, params = ("WHERE kind = ?", (kind,)) if kind else ("", ())
        cursor = await self._db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM memory_facts {where} ORDER BY updated_at DESC, id DESC", params
        )
        return [dict(zip(_COLUMNS, row)) for row in await cursor.fetchall()]

    async def get_fact(self, fact_id: int) -> dict | None:
        """One fact by id, or None."""
        cursor = await self._db.execute(f"SELECT {', '.join(_COLUMNS)} FROM memory_facts WHERE id = ?", (fact_id,))
        row = await cursor.fetchone()
        return dict(zip(_COLUMNS, row)) if row else None

    async def add_fact(self, kind: str, text: str, why: str | None = None, source_chat_id: str | None = None) -> dict:
        """Save a new fact and return it.

        1. Check the kind and the size limits (ValueError for a bad fact, MemoryFull when full).
        2. Insert it with created_at = updated_at = now.
        """
        # 1.
        text = _checked_text(text)
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        cursor = await self._db.execute("SELECT COUNT(*) FROM memory_facts")
        (count,) = await cursor.fetchone()
        if count >= MAX_FACTS:
            raise MemoryFull(f"memory is full ({MAX_FACTS} facts); delete some first")
        # 2.
        now = _now()
        cursor = await self._db.execute(
            "INSERT INTO memory_facts (kind, text, why, source_chat_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, text, _clean_why(why), source_chat_id, now, now),
        )
        await self._db.commit()
        return await self.get_fact(cursor.lastrowid)

    async def remember(self, kind: str, text: str, why: str | None = None,
                       source_chat_id: str | None = None) -> tuple[dict, str, str | None]:
        """Save a fact the agent decided to keep (#81): add it, or update a near-duplicate.

        Returns (fact, action, previous_text): action is "added" or "updated"; previous_text is the
        old wording of an updated fact (the page's Undo puts it back), None for an added one.

        1. Look for a fact of the same kind whose key words overlap by DUPLICATE_OVERLAP or more.
        2. Found: rewrite it with the new text (the newest wording wins). Otherwise add a new fact.
        The size limits and MAX_FACTS apply either way (add_fact / update_fact enforce them).
        """
        # 1.
        new_words = key_words(text)
        for fact in await self.list_facts(kind):
            if overlap(new_words, key_words(fact["text"])) >= DUPLICATE_OVERLAP:
                # 2. The same fact said again: keep one, in the newest wording.
                updated = await self.update_fact(fact["id"], text=text, why=why)
                return updated, "updated", fact["text"]
        return await self.add_fact(kind, text, why, source_chat_id), "added", None

    async def update_fact(self, fact_id: int, kind: str | None = None, text: str | None = None, why: str | None = None) -> dict | None:
        """Change any of a fact's kind, text or why; bumps updated_at. None if the fact doesn't exist."""
        fact = await self.get_fact(fact_id)
        if fact is None:
            return None
        if kind is not None and kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        await self._db.execute(
            "UPDATE memory_facts SET kind = ?, text = ?, why = ?, updated_at = ? WHERE id = ?",
            (kind or fact["kind"], _checked_text(text) if text is not None else fact["text"],
             _clean_why(why) if why is not None else fact["why"], _now(), fact_id),
        )
        await self._db.commit()
        return await self.get_fact(fact_id)

    async def delete_fact(self, fact_id: int) -> bool:
        """Delete one fact. Returns whether it existed."""
        cursor = await self._db.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_all(self) -> int:
        """Forget everything. Returns how many facts were deleted."""
        cursor = await self._db.execute("DELETE FROM memory_facts")
        await self._db.commit()
        return cursor.rowcount

    async def core_profile(self) -> list[str]:
        """The texts of the newest CORE_PROFILE_LIMIT `user` facts: what every prompt includes (D43)."""
        cursor = await self._db.execute(
            "SELECT text FROM memory_facts WHERE kind = 'user' ORDER BY updated_at DESC, id DESC LIMIT ?",
            (CORE_PROFILE_LIMIT,),
        )
        return [text for (text,) in await cursor.fetchall()]

    async def close(self) -> None:
        """Close the database connection (api.py's lifespan calls this on shutdown)."""
        await self._db.close()


def _checked_text(text: str) -> str:
    """Collapse whitespace, then require 1..MAX_FACT_CHARS characters.

    Example: _checked_text("  likes   cats \\n") -> "likes cats"
    """
    text = " ".join(text.split())
    if not text:
        raise ValueError("a fact can't be empty")
    if len(text) > MAX_FACT_CHARS:
        raise ValueError(f"a fact can be at most {MAX_FACT_CHARS} characters")
    return text


def _clean_why(why: str | None) -> str | None:
    """Collapse whitespace in the optional reason; an empty one becomes None. Same length cap as a fact."""
    if why is None:
        return None
    why = " ".join(why.split())
    return why[:MAX_FACT_CHARS] or None
