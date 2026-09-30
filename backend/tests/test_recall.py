"""
tests/test_recall.py — recall without embeddings (#83, D50): the keyword index over facts and chat
summaries, opening a past chat by the id the prompt's index shows, and the recall_memory tool.

The index must never drift from the real memory — a deleted fact that can still be "recalled" would
be a quiet privacy bug — and nothing the model types may break the search. Fake model; $0.
"""

from simba.memory import MemoryStore
from simba.model import fake_model
from tests.test_api import parse_sse, running_app


async def test_the_search_index_follows_every_change(tmp_path):
    """Adds, updates and deletes of facts and summaries all show up in search at once."""
    store = await MemoryStore.open(str(tmp_path / "m.db"))
    fact = await store.add_fact("user", "Works at Acme")
    await store.save_summary("3f2a91aa", "Topic: Lisbon trip\nDecided / learned: stay in Alfama", 6)
    assert [h["source"] for h in await store.search("where to stay in Lisbon?")] == ["chat"]
    assert [h["ref"] for h in await store.search("acme")] == [str(fact["id"])]

    await store.update_fact(fact["id"], text="Works at Globex")
    await store.save_summary("3f2a91aa", "Topic: Porto trip", 12)  # an upsert: the old text must go
    assert await store.search("acme") == [] and await store.search("lisbon") == []
    assert {h["source"] for h in await store.search("globex porto")} == {"fact", "chat"}

    await store.delete_fact(fact["id"])
    await store.delete_summary("3f2a91aa")
    assert await store.search("globex porto") == []
    await store.close()


async def test_the_index_is_rebuilt_on_start_up(tmp_path):
    """Memory saved before the index existed (or while it was out of step) is searchable after a restart."""
    path = str(tmp_path / "m.db")
    store = await MemoryStore.open(path)
    await store.add_fact("project", "Building Simba")
    await store._db.execute("DELETE FROM memory_search")  # simulate an index that lost its rows
    await store._db.commit()
    await store.close()
    store = await MemoryStore.open(path)
    assert [h["text"] for h in await store.search("simba")] == ["project: Building Simba "]
    await store.close()


async def test_search_words_cannot_carry_fts_syntax(tmp_path):
    """Quotes, operators and wildcards from the model are reduced to plain words, never an error."""
    store = await MemoryStore.open(str(tmp_path / "m.db"))
    await store.add_fact("user", "Likes cats")
    for query in ['" OR * NEAR(', 'cats" OR "x', "text:cats", "", "?!"]:
        await store.search(query)  # must not raise
    assert [h["text"] for h in await store.search('cats" OR "x')] == ["user: Likes cats "]
    await store.close()


async def test_open_a_chat_by_its_short_id(tmp_path):
    """The index shows 6 characters of a chat id; that's enough to open it. Too short, or not hex, finds nothing."""
    store = await MemoryStore.open(str(tmp_path / "m.db"))
    await store.save_summary("3f2a91aa", "Topic: Lisbon trip", 6)
    assert [s["chat_id"] for s in await store.summary_by_prefix("3f2a91")] == ["3f2a91aa"]
    assert await store.summary_by_prefix("3f") == [] and await store.summary_by_prefix("%%%%") == []
    await store.close()


async def seeded_chat(app, title: str, summary: str) -> str:
    """A chat row plus its summary, as six real turns would have left them; returns the chat id."""
    chat = await app.state.chats.create(title)
    await app.state.memory.save_summary(chat["id"], summary, 6)
    return chat["id"]


async def test_recent_chats_index_carries_short_ids(tmp_path):
    """Every index line starts with the id recall_memory accepts, e.g. "[c:3f2a91]"."""
    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (app, _client):
        chat_id = await seeded_chat(app, "Lisbon trip", "Topic: planning a May trip")
        profile = await app.state.memory.core_profile()
    assert profile["recent_chats"][0].startswith(f"[c:{chat_id[:6]}] ")
    assert profile["recent_chats"][0].endswith("· Lisbon trip — planning a May trip")


async def test_recall_memory_opens_a_chat_and_searches(tmp_path):
    """End to end: the model opens a past chat by id, and (next turn) searches by keyword; each result
    reaches it fenced as data, and each recall is one trace line."""
    db = str(tmp_path / "t.db")
    async with running_app(model=fake_model(), db_path=db) as (app, _client):
        chat_id = await seeded_chat(app, "Lisbon trip", "Topic: Lisbon trip\nDecided / learned: stay in Alfama")

    opener = fake_model(structured={"recall_memory": {"chat": chat_id[:6]}})
    async with running_app(model=opener, db_path=db) as (_app, client):
        events = parse_sse((await client.post("/api/chat", json={"message": "what did we decide about Lisbon?", "chat_id": None})).text)
    opened = next(m for m in opener.calls[-1] if m.type == "tool").content
    assert opened.startswith('<memory>\nChat "Lisbon trip"') and "stay in Alfama" in opened
    assert [d["detail"] for e, d in events if e == "trace" and d["stage"] == "recall_memory"] == ['chat · "Lisbon trip"']

    searcher = fake_model(structured={"recall_memory": {"query": "Alfama"}})
    async with running_app(model=searcher, db_path=db) as (_app, client):
        await client.post("/api/chat", json={"message": "where did we want to stay?", "chat_id": None})
    found = next(m for m in searcher.calls[-1] if m.type == "tool").content
    assert found == f"<memory>\n[chat {chat_id[:6]}] Topic: Lisbon trip\nDecided / learned: stay in Alfama\n</memory>"
