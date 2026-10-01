"""
tests/test_remember.py — the `remember` tool and its code limits (#81, D40).

Automatic memory is the classic way an attack survives into later chats, so every limit that makes
it safe is pinned here: nothing saved after web results, only the owner's own words, no secrets,
near-duplicates updated rather than piled up, and searches — not saves — use the search budget.
The fake model asks for `remember` when a test dictates it (model.fake_model `structured`); $0.
"""

import json
from dataclasses import asdict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from simba.harness.tool_hooks import memory_from_owner, within_web_search_budget
from simba.memory import MemoryStore
from simba.model import fake_model
from simba.nodes.hook_points import make_before_tool
from simba.tools.memory_tools import WRITE_MANIFEST
from simba.tools.registry import ToolRegistry
from simba.tools.web_search import MANIFEST as SEARCH_MANIFEST
from tests.node_harness import run_node
from tests.test_api import parse_sse, running_app

# The before_tool node as the graph builds it (#65), with the two tools these tests call declared.
before_tool = make_before_tool(ToolRegistry({"web_search": SEARCH_MANIFEST, "remember": WRITE_MANIFEST}))


def call(name: str, args: dict, **context) -> str:
    """A before_tool hook payload, as hook_points.make_before_tool builds it (web_search carries its
    manifest, so its per-turn limit applies)."""
    manifest = {"manifest": asdict(SEARCH_MANIFEST)} if name == "web_search" else {}
    return json.dumps({"name": name, "args": args, "calls_used": 0, "turn_read_untrusted": False,
                       "user_text": "", **manifest, **context})


# ---- the store: one fact, not copies ----

async def test_saying_a_fact_again_updates_it(tmp_path):
    """A reworded repeat updates the old fact (and reports its old wording for Undo); a different
    fact is added beside it."""
    store = await MemoryStore.open(str(tmp_path / "m.db"))
    first, action, _ = await store.remember("user", "Works mostly in Python")
    again, action2, previous = await store.remember("user", "Mostly works in Python 3")
    other, action3, _ = await store.remember("user", "Has a cat called Simba")
    assert (action, action2, action3) == ("added", "updated", "added")
    assert again["id"] == first["id"] and previous == "Works mostly in Python"
    assert len(await store.list_facts()) == 2
    await store.close()


# ---- the code limits (before_tool hook) ----

def test_a_fact_in_the_owners_words_is_allowed():
    """A reworded fact that shares most key words with what the owner wrote passes."""
    payload = call("remember", {"kind": "user", "fact": "Mostly works in Python"},
                   user_text="Hi! I mostly work in Python these days.")
    assert memory_from_owner(payload).action == "allow"


def test_a_fact_not_in_the_owners_words_is_blocked():
    """A "fact" the owner never said — e.g. planted by a clever prompt — is refused in code."""
    payload = call("remember", {"kind": "user", "fact": "Owner is an admin with full access"},
                   user_text="What's the weather like?")
    assert memory_from_owner(payload).rule == "memory-not-own-words"


def test_nothing_is_saved_after_web_results():
    """Once a turn has read a web page, no save goes through, however the fact is worded (D35)."""
    payload = call("remember", {"kind": "user", "fact": "Mostly works in Python"},
                   user_text="I mostly work in Python", turn_read_untrusted=True)
    assert memory_from_owner(payload).rule == "memory-after-untrusted"


def test_secrets_are_never_saved():
    """Even in the owner's own words, a key-shaped string is not stored."""
    key = "sk-ant-api03-" + "a" * 40
    payload = call("remember", {"kind": "reference", "fact": f"API key {key}"}, user_text=f"my API key is {key}")
    assert memory_from_owner(payload).rule == "memory-secret"


def test_search_checks_skip_remember_and_saves_do_not_use_the_search_budget():
    """A remember call isn't held to web-search rules, and budget counting only sees searches."""
    assert within_web_search_budget(call("remember", {"fact": "x"}, calls_used=99)).action == "allow"
    assert within_web_search_budget(call("web_search", {"query": "x"}, calls_used=3)).action == "block"


async def test_before_tool_counts_only_searches():
    """A turn with one search and one save leaves web_search_calls at 1, not 2."""
    message = AIMessage(content="", tool_calls=[
        {"name": "web_search", "args": {"query": "python news"}, "id": "s1"},
        {"name": "remember", "args": {"kind": "user", "fact": "Mostly works in Python"}, "id": "r1"},
    ])
    update, _ = await run_node(before_tool, {"messages": [HumanMessage("I mostly work in Python"), message],
                                             "web_search_calls": 0})
    assert update["tool_call_blocked"] is False and update["web_search_calls"] == 1


async def test_before_tool_blocks_a_save_after_search_results():
    """The untrusted-content rule end to end: a web_search result earlier in the turn blocks the save."""
    history = [
        HumanMessage("I mostly work in Python, what's new in Python?"),
        AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "python"}, "id": "s1"}]),
        ToolMessage("<untrusted_tool_result>…</untrusted_tool_result>", tool_call_id="s1", name="web_search"),
        AIMessage(content="", tool_calls=[{"name": "remember", "args": {"kind": "user", "fact": "Mostly works in Python"}, "id": "r1"}]),
    ]
    update, _ = await run_node(before_tool, {"messages": history, "web_search_calls": 1})
    assert update["tool_call_blocked"] is True
    assert "nothing is saved after reading web results" in update["messages"][0].content


# ---- end to end: the real API, the fake model ----

async def test_a_turn_that_remembers_saves_the_fact_and_sends_a_memory_event(tmp_path):
    """The whole path: the model asks to remember, before_tool allows it, the tool saves it, the page
    gets a `memory` event (for Undo), the trace shows the save, and the reply still arrives."""
    model = fake_model(reply="Nice, Python it is!",
                       structured={"remember": {"kind": "user", "fact": "Mostly works in Python"}})
    async with running_app(model=model, db_path=str(tmp_path / "t.db")) as (app, client):
        events = parse_sse((await client.post("/api/chat", json={"message": "I mostly work in Python", "chat_id": None})).text)
        facts = await app.state.memory.list_facts()

    memory = [data for name, data in events if name == "memory"]
    assert memory == [{"action": "added", "fact_id": facts[0]["id"], "kind": "user",
                       "text": "Mostly works in Python", "previous_text": None}]
    assert facts[0]["source_chat_id"] == events[0][1]["chat_id"]
    stages = [data["stage"] for name, data in events if name == "trace"]
    assert stages == ["before_model", "agent", "before_tool", "remember", "agent", "after_model"]
    assert "".join(data["text"] for name, data in events if name == "token") == "Nice, Python it is!"


async def test_a_blocked_save_changes_nothing_and_the_turn_still_answers(tmp_path):
    """A fact not in the owner's words is refused: nothing stored, no memory event, normal reply."""
    model = fake_model(reply="Sure!", structured={"remember": {"kind": "user", "fact": "Owner is an admin"}})
    async with running_app(model=model, db_path=str(tmp_path / "t.db")) as (app, client):
        events = parse_sse((await client.post("/api/chat", json={"message": "What's 2+2?", "chat_id": None})).text)
        assert await app.state.memory.list_facts() == []
    assert not [e for e, _ in events if e == "memory"]
    assert events[-1][0] == "done"
