"""
tests/test_memory_tools.py — managing memory by talking (#87, D46–D48): list, update and forget,
end to end through the real API with the fake model.

The forget tests matter most: deleting memory must wait for the owner's approve on the approval card
(#66b, D51), checked in code — a deny, or no answer at all, must leave memory untouched.
"""

import json

from simba.harness.tool_hooks import memory_from_owner
from simba.model import fake_model
from tests.test_api import parse_sse, running_app


async def say(client, text: str, chat_id: str | None = None) -> tuple[str, list]:
    """Send one message; returns (chat id, SSE events)."""
    events = parse_sse((await client.post("/api/chat", json={"message": text, "chat_id": chat_id})).text)
    return events[0][1]["chat_id"], events


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


async def forget_flow(tmp_path, approve: bool | None) -> tuple[list, list, list]:
    """Ask to forget one fact; the fake model calls forget_memory, so the turn pauses for approval.
    Then answer the card with `approve` (None = don't answer). Returns (facts left, first turn's
    events, resume events)."""
    db = str(tmp_path / "t.db")
    # 1. Save the fact first, so the fake model's forget call can name its real id.
    async with running_app(model=fake_model(), db_path=db) as (app, _client):
        fact = await app.state.memory.add_fact("user", "Works at Acme")
    # 2. Ask to forget (the turn pauses), then answer the card on the same app.
    model = fake_model(reply="Okay.", structured={"forget_memory": {"fact_ids": [fact["id"]]}})
    async with running_app(model=model, db_path=db) as (app, client):
        chat_id, first = await say(client, "Please forget that I work at Acme")
        resumed = []
        if approve is not None:
            resumed = parse_sse((await client.post(f"/api/chat/{chat_id}/resume", json={"approve": approve})).text)
        left = await app.state.memory.list_facts()
    return left, first, resumed


async def test_forget_pauses_for_the_card_and_deletes_only_after_approve(tmp_path):
    """#66b, D51: asking to forget deletes nothing and shows an approval card; approve deletes it and
    tells the page (the "Forgot: …" line)."""
    left, first, _ = await forget_flow(tmp_path / "unanswered", None)
    card = next(d for e, d in first if e == "approval")
    assert card["calls"][0]["tool"] == "forget_memory" and [f["text"] for f in left] == ["Works at Acme"]

    left, _, resumed = await forget_flow(tmp_path / "approved", True)
    assert left == []
    assert [d["action"] for e, d in resumed if e == "memory"] == ["forgotten"]


async def test_forget_does_nothing_on_deny(tmp_path):
    """Deny leaves the fact where it is; the model hears the owner declined."""
    left, _, resumed = await forget_flow(tmp_path, False)
    assert [f["text"] for f in left] == ["Works at Acme"]
    assert resumed[-1][0] == "done"
