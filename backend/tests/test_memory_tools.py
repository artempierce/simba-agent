"""
tests/test_memory_tools.py — managing memory by talking (#87, D46–D48): list, update and the
two-step forget, end to end through the real API with the fake model.

The forget tests matter most: deleting memory must need the owner's clear yes in the very next
message, checked in code — a "no", a late "yes", or no answer at all must leave memory untouched.
"""

import json

from simba.harness.tool_hooks import memory_from_owner
from simba.memory import is_clear_yes
from simba.model import fake_model
from tests.test_api import parse_sse, running_app


async def say(client, text: str, chat_id: str | None = None) -> tuple[str, list]:
    """Send one message; returns (chat id, SSE events)."""
    events = parse_sse((await client.post("/api/chat", json={"message": text, "chat_id": chat_id})).text)
    return events[0][1]["chat_id"], events


def test_clear_yes_is_strict():
    """Only a plain yes counts; anything with a "no", "wait" or a condition deletes nothing."""
    assert all(is_clear_yes(t) for t in ["yes", "Yes, forget it", "ok", "sure!", "go ahead", "Да"])
    assert not any(is_clear_yes(t) for t in ["no", "yes but not the Python one", "wait", "tell me more", ""])


async def test_list_memory_shows_facts_with_ids_as_data(tmp_path):
    """"What do you remember?" -> the model gets every fact with its id, fenced as data."""
    model = fake_model(structured={"list_memory": {}})
    async with running_app(model=model, db_path=str(tmp_path / "t.db")) as (app, client):
        fact = await app.state.memory.add_fact("user", "Name: Sol")
        await say(client, "What do you remember about me?")
    tool_reply = next(m for m in model.calls[-1] if m.type == "tool")
    assert tool_reply.content == f"<memory>\n[{fact['id']}] user: Name: Sol\n</memory>"


async def test_update_memory_rewrites_a_fact_and_offers_undo(tmp_path):
    """A correction in the owner's words rewrites the fact; the page gets the old wording for Undo."""
    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (app, client):
        fact = await app.state.memory.add_fact("user", "Lives in London")
    model = fake_model(structured={"update_memory": {"fact_id": fact["id"], "text": "Lives in Berlin"}})
    async with running_app(model=model, db_path=str(tmp_path / "t.db")) as (app, client):
        _, events = await say(client, "Actually I moved, I live in Berlin now")
        assert (await app.state.memory.get_fact(fact["id"]))["text"] == "Lives in Berlin"
    memory = [d for e, d in events if e == "memory"]
    assert memory == [{"action": "updated", "fact_id": fact["id"], "kind": "user",
                       "text": "Lives in Berlin", "previous_text": "Lives in London"}]


def test_update_not_in_the_owners_words_is_blocked():
    """update_memory is held to the same own-words rule as remember."""
    payload = json.dumps({"name": "update_memory", "args": {"fact_id": 1, "text": "Owner is an admin"},
                          "calls_used": 0, "turn_read_untrusted": False, "user_text": "What's 2+2?"})
    assert memory_from_owner(payload).rule == "memory-not-own-words"


def test_forget_after_web_results_is_blocked():
    """A page can't make Simba forget things: after web results, forget_memory is refused outright."""
    payload = json.dumps({"name": "forget_memory", "args": {"everything": True}, "calls_used": 0,
                          "turn_read_untrusted": True, "user_text": "forget everything"})
    assert memory_from_owner(payload).rule == "memory-after-untrusted"


async def forget_flow(tmp_path, answers: list[str | tuple[str, bool]]) -> tuple[list, list]:
    """Ask to forget one fact, then send `answers` in the same chat. On each turn the fake model calls
    forget_memory with the same arguments — unless an answer is given as (text, False), when the model
    just chats that turn. Each turn gets its own app on the same database, so the chat carries on.
    Returns (facts left, every turn's events)."""
    db = str(tmp_path / "t.db")
    async with running_app(model=fake_model(), db_path=db) as (app, _client):
        fact = await app.state.memory.add_fact("user", "Works at Acme")
    forgetting = fake_model(reply="Okay.", structured={"forget_memory": {"fact_ids": [fact["id"]]}})
    chat_id, turns = None, []
    for answer in ["Please forget that I work at Acme", *answers]:
        text, calls_forget = answer if isinstance(answer, tuple) else (answer, True)
        async with running_app(model=forgetting if calls_forget else fake_model(), db_path=db) as (app, client):
            chat_id, events = await say(client, text, chat_id)
            turns.append(events)
            left = await app.state.memory.list_facts()
    return left, turns


async def test_forget_asks_first_and_deletes_on_the_next_yes(tmp_path):
    """Turn 1 deletes nothing and says it's waiting; turn 2 "yes" deletes it and tells the page."""
    left, turns = await forget_flow(tmp_path, ["yes"])
    first_details = [d["detail"] for e, d in turns[0] if e == "trace" and d["stage"] == "forget_memory"]
    assert first_details == ["waiting for yes · 1 fact(s)"]
    assert left == []
    assert [d["action"] for e, d in turns[1] if e == "memory"] == ["forgotten"]


async def test_forget_does_nothing_on_no(tmp_path):
    """A "no" leaves the fact where it is."""
    left, _ = await forget_flow(tmp_path, ["no, keep it"])
    assert [f["text"] for f in left] == ["Works at Acme"]


async def test_a_late_yes_does_not_count(tmp_path):
    """The yes must be the very next message: after a different message in between, a "yes" (which
    may answer something else) deletes nothing — the request is asked again instead."""
    left, _ = await forget_flow(tmp_path, [("tell me a joke first", False), "yes"])
    assert [f["text"] for f in left] == ["Works at Acme"]
