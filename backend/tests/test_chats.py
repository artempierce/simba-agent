"""
tests/test_chats.py — the chat-list store (simba/chats.py) behaves as docs/contracts.md § 10 says:
titles are built correctly, and every ChatStore method does exactly what the sidebar and API need.

Each async test opens its own on-disk SQLite file under pytest's tmp_path, so tests never share
state and each one starts from an empty database.
"""

import asyncio

import pytest

from simba import chats as chats_module
from simba.chats import ChatStore, title_from


def test_title_from_short_message_unchanged():
    """A message that already fits becomes its own title, only whitespace-collapsed."""
    assert title_from("plan a trip to Rome") == "plan a trip to Rome"


def test_title_from_collapses_whitespace():
    """Newlines and repeated spaces collapse to single spaces, so a title fits on one sidebar line."""
    assert title_from("  plan   a trip\nto Rome  ") == "plan a trip to Rome"


def test_title_from_cuts_long_message_with_ellipsis():
    """Anything over 40 characters is cut to exactly 40 chars plus a trailing "…" marker."""
    title = title_from("x" * 50)
    assert title == "x" * 40 + "…"
    assert len(title) == 41


def test_title_from_empty_message_is_new_chat():
    """An empty (or all-whitespace) message can't make a title, so it falls back to "New chat" (Q9)."""
    assert title_from("") == "New chat"
    assert title_from("   ") == "New chat"


async def test_create_returns_chat_with_matching_timestamps(tmp_path):
    """A freshly created chat has created_at == updated_at and carries the given title — checked
    against a fresh read from the database, not just the dict `create()` handed back, so this also
    proves the row was actually written, not merely echoed back in memory."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    chat = await store.create("hello")
    stored = await store.get(chat["id"])
    assert stored["title"] == "hello"
    assert stored["created_at"] == stored["updated_at"]
    await store.close()


async def test_list_orders_newest_updated_first(tmp_path):
    """The sidebar shows the most recently active chat on top, not creation order, so `list()` must
    sort by updated_at, not by insertion order."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    first = await store.create("first")
    await asyncio.sleep(0.01)
    second = await store.create("second")
    await asyncio.sleep(0.01)
    await store.touch(first["id"])  # bump `first` back to the top
    chats = await store.list()
    assert [c["id"] for c in chats] == [first["id"], second["id"]]
    await store.close()


async def test_list_breaks_updated_at_ties_by_rowid(tmp_path, monkeypatch):
    """Two chats created in the same instant (a real possibility — `_now()`'s microsecond resolution
    isn't guaranteed unique) must still sort deterministically: `list()`'s `ORDER BY ..., rowid DESC`
    puts the more recently inserted one first, not whatever order SQLite happens to walk ties in."""
    monkeypatch.setattr(chats_module, "_now", lambda: "2026-01-01T00:00:00+00:00")
    store = await ChatStore.open(str(tmp_path / "t.db"))
    first = await store.create("first")
    second = await store.create("second")
    assert first["updated_at"] == second["updated_at"]  # the tie this test is about
    chats = await store.list()
    assert [c["id"] for c in chats] == [second["id"], first["id"]]
    await store.close()


async def test_get_unknown_id_returns_none(tmp_path):
    """A missing chat id comes back as None, not an exception, so the router can turn it into a 404."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    assert await store.get("nope") is None
    await store.close()


async def test_rename_updates_title_and_bumps_updated_at(tmp_path):
    """Renaming changes the title and moves updated_at forward, so a renamed chat also reorders in the sidebar."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    chat = await store.create("old title")
    await asyncio.sleep(0.01)
    renamed = await store.rename(chat["id"], "new title")
    assert renamed["title"] == "new title"
    assert renamed["updated_at"] > chat["updated_at"]
    await store.close()


async def test_touch_bumps_updated_at_without_changing_title(tmp_path):
    """touch() is used after a turn completes; it must move updated_at without touching the title."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    chat = await store.create("keep me")
    await asyncio.sleep(0.01)
    await store.touch(chat["id"])
    updated = await store.get(chat["id"])
    assert updated["title"] == "keep me"
    assert updated["updated_at"] > chat["updated_at"]
    await store.close()


async def test_delete_removes_chat_and_its_runs(tmp_path):
    """Deleting a chat also deletes its run history, so no orphaned rows are left in `runs`."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    chat = await store.create("bye")
    await store.add_run(chat["id"], "hi", [{"stage": "guard"}], {"ms": 1}, None)
    assert await store.delete(chat["id"]) is True
    assert await store.get(chat["id"]) is None
    assert await store.runs(chat["id"]) == []
    await store.close()


async def test_delete_unknown_id_returns_false(tmp_path):
    """Deleting an id that doesn't exist reports failure instead of silently "succeeding"."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    assert await store.delete("nope") is False
    await store.close()


async def test_add_run_and_runs_round_trip_oldest_first(tmp_path):
    """Runs come back oldest first, with lines/summary decoded back from JSON, matching the
    frontend's Run type ({"prompt", "lines", "summary", "error"})."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    chat = await store.create("chat")
    await store.add_run(chat["id"], "first prompt", [{"stage": "guard", "status": "ok"}], {"ms": 10}, None)
    await store.add_run(chat["id"], "second prompt", [{"stage": "guard", "status": "blocked"}], None, "boom")
    runs = await store.runs(chat["id"])
    assert [r["prompt"] for r in runs] == ["first prompt", "second prompt"]
    assert runs[0]["lines"] == [{"stage": "guard", "status": "ok"}]
    assert runs[0]["summary"] == {"ms": 10}
    assert runs[0]["error"] is None
    assert runs[1]["summary"] is None
    assert runs[1]["error"] == "boom"
    await store.close()


async def test_spent_usd_sums_every_trace_line_of_this_chat_only(tmp_path):
    """#16's budget reads this total. It must count failed turns too (no summary, but their model
    calls still cost money), ignore lines without a cost, and never mix in another chat's spending."""
    store = await ChatStore.open(str(tmp_path / "t.db"))
    chat = await store.create("chat")
    other = await store.create("other")
    assert await store.spent_usd(chat["id"]) == 0.0  # no runs yet

    await store.add_run(chat["id"], "ok turn", [{"cost_usd": 0.001}, {"cost_usd": 0.002}], {"ms": 1}, None)
    await store.add_run(chat["id"], "failed turn", [{"cost_usd": 0.0005}, {"stage": "old line"}], None, "boom")
    await store.add_run(other["id"], "other chat", [{"cost_usd": 9.0}], {"ms": 1}, None)

    assert await store.spent_usd(chat["id"]) == pytest.approx(0.0035)
    await store.close()
