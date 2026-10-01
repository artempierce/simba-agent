"""
memory.py — Simba's long-term memory of facts (#80, design book § Memory, D40–D45).

Where it sits: api.py opens one MemoryStore at startup, next to the ChatStore, on the same SQLite
file. memory_api.py (the Memory tab) reads and changes facts through it; the agent node reads the
core profile from it at the start of every turn (`core_profile`), so what you told Simba in one chat
is known in the next.

Key ideas:
- A fact has a kind, the same four Claude Code uses for its own memory (see KINDS). `user` facts
  (the profile, D43) and `feedback` facts (learned "how to work with me" rules — procedural memory,
  D48) go into every prompt; `project` and `reference` facts are looked up when needed.
- Recall (#83, D50), the way Claude Code's memory works — no embedding model: the prompt's index of
  recent chats carries a short id per chat ("[c:3f2a91] …"), `summary_by_prefix` opens one chat's full
  summary by that id, and `search` is keyword search (SQLite FTS5, BM25) over every fact and summary.
  Claude matches meaning when it reads the index; the search finds exact words.
- Episodic memory (#82, D41): each chat keeps one rolling summary (`chat_summaries`), rewritten every
  SUMMARY_EVERY owner turns by the summarize node. The prompt gets a one-line index of the most
  recent ones (RECENT_CHATS_IN_PROMPT); the full text is read on demand (M4's recall).
- Memory changes only by talking to Simba (#87, D46): its tools call this store. Forgetting
  waits for the owner's approve on an approval card (#66, D51; replaced D47's next-message yes).
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

# How many facts of each always-loaded kind go into every prompt (D43, D48): the newest 15 `user`
# facts and the newest 15 `feedback` facts. ~30 short lines is a few hundred tokens — cheap on every
# turn, and it's what almost every answer can use.
CORE_PROFILE_LIMIT = 15

# #82: how many recent chat summaries the prompt lists, one line each (date · title · topic). Enough to
# spot "we talked about that last week"; the full summary is looked up when needed (M4).
RECENT_CHATS_IN_PROMPT = 20

# #83: how many matches one recall_memory search returns, best first. Enough to find the right fact or
# chat; few enough that a recall stays a short read for the model.
SEARCH_RESULTS = 5

# #83: how many characters of a chat id the prompt's index shows ("[c:3f2a91]"). Chat ids are 32 hex
# characters; 6 keep the index short and are unique in practice (recall checks, and says if not).
CHAT_REF_CHARS = 6

# #82: a chat's summary is rewritten after this many new owner turns (D41). Six is often enough that
# leaving a chat never loses much, rarely enough that summaries cost about one small call per 6 turns.
SUMMARY_EVERY = 6

# The kinds that are always in the prompt, in the order the prompt shows them.
ALWAYS_LOADED = ("user", "feedback")

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
        # #82: one rolling summary per chat. `topic` is the summary's first line, kept apart for the
        # prompt's index; `turns` is how many owner turns the summary covers.
        await db.execute(
            """CREATE TABLE IF NOT EXISTS chat_summaries (
                chat_id TEXT PRIMARY KEY, summary TEXT NOT NULL, topic TEXT NOT NULL,
                turns INTEGER NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        # #83: the keyword index over facts and summaries (SQLite FTS5 — full-text search built into
        # SQLite). `source` is "fact" or "chat", `ref` the fact id or chat id; only `text` is searched.
        # Triggers keep it in step with every insert, update and delete, and it's rebuilt at start-up,
        # so it can never drift from the real tables.
        await db.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(
                source UNINDEXED, ref UNINDEXED, text, tokenize = 'unicode61 remove_diacritics 2'
            )"""
        )
        for statement in _SEARCH_TRIGGERS:
            await db.execute(statement)
        await db.execute("DELETE FROM memory_search")
        await db.execute(
            "INSERT INTO memory_search (source, ref, text) "
            "SELECT 'fact', id, kind || ': ' || text || ' ' || coalesce(why, '') FROM memory_facts"
        )
        await db.execute("INSERT INTO memory_search (source, ref, text) SELECT 'chat', chat_id, summary FROM chat_summaries")
        # #66b: the old next-message-yes table for forget (#87) is gone; the approval card replaced it.
        await db.execute("DROP TABLE IF EXISTS memory_pending")
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

    async def core_profile(self) -> dict[str, list[str]]:
        """What every prompt includes: the newest CORE_PROFILE_LIMIT facts of each ALWAYS_LOADED kind,
        plus (#82) the index of recent chats, one line each.

        Example: {"user": ["Name: Sol"], "feedback": ["Prefers short answers"],
                  "recent_chats": ["30 Sep · Memory plan — designing Simba's memory"]}
        """
        profile: dict[str, list[str]] = {}
        for kind in ALWAYS_LOADED:
            cursor = await self._db.execute(
                "SELECT text FROM memory_facts WHERE kind = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
                (kind, CORE_PROFILE_LIMIT),
            )
            profile[kind] = [text for (text,) in await cursor.fetchall()]
        profile["recent_chats"] = [
            f"[c:{s['chat_id'][:CHAT_REF_CHARS]}] {_day(s['updated_at'])} · {s['title']} — {s['topic']}"
            for s in await self.list_summaries(RECENT_CHATS_IN_PROMPT)
        ]
        return profile

    async def get_summary(self, chat_id: str) -> dict | None:
        """One chat's summary as {"chat_id", "summary", "topic", "turns", "updated_at"}, or None."""
        cursor = await self._db.execute(
            "SELECT chat_id, summary, topic, turns, updated_at FROM chat_summaries WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return dict(zip(("chat_id", "summary", "topic", "turns", "updated_at"), row)) if row else None

    async def save_summary(self, chat_id: str, summary: str, turns: int) -> dict:
        """Store (or replace) a chat's rolling summary; its first line becomes the topic for the index."""
        summary = summary.strip()
        topic = summary.splitlines()[0].removeprefix("Topic:").strip()[:MAX_FACT_CHARS] if summary else ""
        # An upsert, not INSERT OR REPLACE: REPLACE deletes the old row without firing delete
        # triggers, which would leave the old summary in the search index (#83).
        await self._db.execute(
            """INSERT INTO chat_summaries (chat_id, summary, topic, turns, updated_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET summary = excluded.summary, topic = excluded.topic,
               turns = excluded.turns, updated_at = excluded.updated_at""",
            (chat_id, summary, topic, turns, _now()),
        )
        await self._db.commit()
        return await self.get_summary(chat_id)

    async def list_summaries(self, limit: int | None = None) -> list[dict]:
        """Chat summaries, newest first, each with its chat's title.

        The titles live in chats.py's `chats` table, in the same database file, so one SQL join
        reads both — a summary whose chat is gone is left out (delete_summary normally removes it).
        A store opened on a file without that table (a unit test of this store alone) uses the chat
        id as the title instead of failing.
        """
        keys = ("chat_id", "title", "summary", "topic", "turns", "updated_at")
        limit_value = limit if limit is not None else -1  # SQLite: LIMIT -1 means no limit
        try:
            cursor = await self._db.execute(
                """SELECT s.chat_id, c.title, s.summary, s.topic, s.turns, s.updated_at
                   FROM chat_summaries s JOIN chats c ON c.id = s.chat_id
                   ORDER BY s.updated_at DESC LIMIT ?""",
                (limit_value,),
            )
        except aiosqlite.OperationalError:  # no `chats` table in this file
            cursor = await self._db.execute(
                """SELECT chat_id, chat_id, summary, topic, turns, updated_at FROM chat_summaries
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit_value,),
            )
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def search(self, query: str, limit: int = SEARCH_RESULTS) -> list[dict]:
        """Keyword search over every fact and chat summary (#83): best matches first.

        1. Keep only the words of the query (letters and digits), so nothing the model writes can be
           read as FTS5 syntax (quotes, AND/NEAR, *, column filters).
        2. Match any of those words; FTS5's bm25() ranks rows higher the more — and the rarer — the
           words they share with the query. Lower bm25 is better.
        Returns [{"source": "fact" | "chat", "ref": fact id or chat id, "text": str}], at most `limit`.

        Example: search("where to stay in Lisbon?") matches "Decided: stay in Alfama, Lisbon".
        """
        # 1.
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1][:12]
        if not words:
            return []
        # 2.
        match = " OR ".join(f'"{w}"' for w in words)
        cursor = await self._db.execute(
            "SELECT source, ref, text FROM memory_search WHERE memory_search MATCH ? ORDER BY bm25(memory_search) LIMIT ?",
            (match, limit),
        )
        return [{"source": source, "ref": str(ref), "text": text} for source, ref, text in await cursor.fetchall()]

    async def summary_by_prefix(self, prefix: str) -> list[dict]:
        """Chat summaries whose chat id starts with `prefix` (the index shows 6 characters). Only hex
        characters are used, so the prefix can't carry SQL LIKE wildcards. A result of more than one
        means the prefix is ambiguous — the caller asks for more characters."""
        prefix = "".join(ch for ch in prefix.lower() if ch in "0123456789abcdef")
        if len(prefix) < 4:
            return []
        return [s for s in await self.list_summaries() if s["chat_id"].startswith(prefix)]

    async def delete_summary(self, chat_id: str) -> None:
        """Forget a chat's summary (called when the chat itself is deleted)."""
        await self._db.execute("DELETE FROM chat_summaries WHERE chat_id = ?", (chat_id,))
        await self._db.commit()

    async def delete_facts(self, fact_ids: list[int]) -> list[dict]:
        """Delete these facts; returns the ones that existed (so the caller can say what was forgotten)."""
        gone = [fact for fact_id in fact_ids if (fact := await self.get_fact(fact_id)) is not None]
        for fact in gone:
            await self._db.execute("DELETE FROM memory_facts WHERE id = ?", (fact["id"],))
        await self._db.commit()
        return gone

    async def close(self) -> None:
        """Close the database connection (api.py's lifespan calls this on shutdown)."""
        await self._db.close()


# #83: keep memory_search in step with the two tables it indexes. The fact's kind and reason are
# searchable too ("feedback", "why: said so").
_SEARCH_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS memory_facts_ai AFTER INSERT ON memory_facts BEGIN
         INSERT INTO memory_search (source, ref, text)
         VALUES ('fact', new.id, new.kind || ': ' || new.text || ' ' || coalesce(new.why, '')); END""",
    """CREATE TRIGGER IF NOT EXISTS memory_facts_au AFTER UPDATE ON memory_facts BEGIN
         DELETE FROM memory_search WHERE source = 'fact' AND ref = old.id;
         INSERT INTO memory_search (source, ref, text)
         VALUES ('fact', new.id, new.kind || ': ' || new.text || ' ' || coalesce(new.why, '')); END""",
    """CREATE TRIGGER IF NOT EXISTS memory_facts_ad AFTER DELETE ON memory_facts BEGIN
         DELETE FROM memory_search WHERE source = 'fact' AND ref = old.id; END""",
    """CREATE TRIGGER IF NOT EXISTS chat_summaries_ai AFTER INSERT ON chat_summaries BEGIN
         INSERT INTO memory_search (source, ref, text) VALUES ('chat', new.chat_id, new.summary); END""",
    """CREATE TRIGGER IF NOT EXISTS chat_summaries_au AFTER UPDATE ON chat_summaries BEGIN
         DELETE FROM memory_search WHERE source = 'chat' AND ref = old.chat_id;
         INSERT INTO memory_search (source, ref, text) VALUES ('chat', new.chat_id, new.summary); END""",
    """CREATE TRIGGER IF NOT EXISTS chat_summaries_ad AFTER DELETE ON chat_summaries BEGIN
         DELETE FROM memory_search WHERE source = 'chat' AND ref = old.chat_id; END""",
)


def _day(iso: str) -> str:
    """"2026-09-30T14:03:11+00:00" -> "30 Sep" (short dates for the prompt's chat index)."""
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso[:10]
    return f"{d.day} {d:%b}"  # not strftime("%-d"): that doesn't exist on Windows


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
