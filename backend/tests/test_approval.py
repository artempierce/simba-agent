"""
tests/test_approval.py — the owner-approval pause and the untrusted-content rule (#66, D35).

These pin the promise "a tool that changes things can't run without the owner's yes": the rule that
decides which calls wait (approval_rule), the graph pausing at the approval node and only reaching
the tool after an approve, and the API's `approval` event + resume endpoint. All with the free fake
model and a fake write tool that just records whether it ran.
"""

import json

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from simba.graph import build_graph
from simba.harness.tool_hooks import NEEDS_APPROVAL, approval_rule
from simba.model import fake_model
from simba.tools.registry import ToolManifest, declare
from tests.test_api import parse_sse, running_app

ASKING = ToolManifest(access="write", needs_approval=True, enabled=True)
WRITE = ToolManifest(access="write", enabled=True)
READ = ToolManifest(access="read", enabled=True)


def payload(manifest: ToolManifest, read_untrusted: bool = False) -> str:
    """A before_tool hook payload carrying only what approval_rule reads."""
    from dataclasses import asdict

    return json.dumps({"name": "x", "args": {}, "manifest": asdict(manifest), "turn_read_untrusted": read_untrusted})


# ---- the rule table ----

def test_approval_rule_table():
    """Which calls wait: anything whose manifest asks, and any write after web results (D35).
    A read never waits, and a write before any untrusted content doesn't either."""
    assert approval_rule(payload(ASKING)).rule == NEEDS_APPROVAL
    assert approval_rule(payload(WRITE, read_untrusted=True)).rule == NEEDS_APPROVAL
    assert approval_rule(payload(WRITE)).action == "allow"
    assert approval_rule(payload(READ, read_untrusted=True)).action == "allow"
    assert approval_rule("not json").action == "block"  # fail closed


# ---- the graph pauses, and only "approve" reaches the tool ----

def make_send_tool(ran: list):
    """A fake write tool that needs approval and records each run in `ran`."""

    @tool("send_note")
    async def send_note(text: str) -> str:
        """Send a note."""
        ran.append(text)
        return "sent"

    return declare(send_note, ASKING)


def start(ran: list):
    """A graph whose fake model asks for send_note once, plus the config for one thread."""
    model = fake_model(reply="Done.", structured={"send_note": {"text": "hello"}})
    graph = build_graph(model, InMemorySaver(), memory_tools=[make_send_tool(ran)])
    turn = {"messages": [HumanMessage("send a note")], "verdict": None, "flag": None,
            "tool_call_blocked": None, "web_search_calls": 0, "approval_calls": None}
    return graph, turn, {"configurable": {"thread_id": "t1"}}


async def test_graph_pauses_then_runs_the_tool_only_after_approve():
    """The turn stops at the approval node with the call's details; approving runs the tool once."""
    ran: list = []
    graph, turn, config = start(ran)
    await graph.ainvoke(turn, config)
    state = await graph.aget_state(config)
    assert state.next == ("approval",) and ran == []
    [held] = state.tasks[0].interrupts[0].value["calls"]
    assert (held["tool"], held["args"], held["reason"]) == ("send_note", {"text": "hello"}, "waits for approval")

    await graph.ainvoke(Command(resume={"approve": True}), config)
    assert ran == ["hello"]
    assert (await graph.aget_state(config)).next == ()


async def test_graph_deny_never_runs_the_tool_and_the_model_hears_why():
    """Declining answers the call with a denial the model reads; the tool never runs."""
    ran: list = []
    graph, turn, config = start(ran)
    await graph.ainvoke(turn, config)
    await graph.ainvoke(Command(resume={"approve": False}), config)
    assert ran == []
    messages = (await graph.aget_state(config)).values["messages"]
    assert any(m.type == "tool" and "declined" in m.content for m in messages)


async def test_a_write_after_web_results_pauses_even_without_needs_approval():
    """The untrusted-content rule end to end in the graph: search, then a plain write tool (no
    needs_approval in its manifest) still stops at the approval node instead of running."""
    from simba.tools.web_search import make_web_search_tool

    class OneResult:
        async def ainvoke(self, params):
            return {"results": [{"title": "t", "url": "https://example.test", "content": "c"}]}

    ran: list = []

    @tool("save_page")
    async def save_page(text: str) -> str:
        """Save a page."""
        ran.append(text)
        return "saved"

    class SearchThenSave(type(fake_model())):
        """Searches on its first call, asks to save on its second."""

        def _answer(self, messages):
            self.calls.append(list(messages))
            name, args = ("web_search", {"query": "q"}) if len(self.calls) == 1 else ("save_page", {"text": "x"})
            return "", {"name": name, "args": args, "id": f"c{len(self.calls)}"}, {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}

    graph = build_graph(SearchThenSave(), InMemorySaver(), web_search_tool=make_web_search_tool(OneResult()),
                        memory_tools=[declare(save_page, WRITE)])
    config = {"configurable": {"thread_id": "t2"}}
    await graph.ainvoke({"messages": [HumanMessage("find and save")], "verdict": None, "flag": None,
                         "tool_call_blocked": None, "web_search_calls": 0, "approval_calls": None}, config)
    state = await graph.aget_state(config)
    assert state.next == ("approval",) and ran == []
    assert state.tasks[0].interrupts[0].value["calls"][0]["reason"] == "write after web results waits for approval"


# ---- the API: `approval` event, resume, one run per turn ----

def app_with_send_tool(tmp_path, ran: list):
    """An app whose fake model asks for send_note (a needs-approval tool). The tool goes in through
    create_app's tool slot; no real tool needs approval yet (#66b gives forget_memory the card)."""
    model = fake_model(reply="Done.", structured={"send_note": {"text": "hello"}})
    return running_app(model=model, db_path=str(tmp_path / "a.db"), web_search_tool=make_send_tool(ran))


async def test_api_pauses_with_an_approval_event_then_resumes_on_approve(tmp_path):
    """The stream ends with an `approval` event (and a waiting trace line) instead of an answer;
    resuming with approve runs the tool and finishes the reply; the chat keeps one run."""
    ran: list = []
    async with app_with_send_tool(tmp_path, ran) as (_app, client):
        first = parse_sse((await client.post("/api/chat", json={"message": "send a note"})).text)
        chat_id = first[0][1]["chat_id"]
        approval = next(data for name, data in first if name == "approval")
        assert approval["calls"][0]["tool"] == "send_note" and ran == []
        assert [d["detail"] for n, d in first if n == "trace"][-1] == "waiting · send_note"
        assert first[-1][0] == "done"

        second = parse_sse((await client.post(f"/api/chat/{chat_id}/resume", json={"approve": True})).text)
        assert ran == ["hello"]
        assert "".join(d["text"] for n, d in second if n == "token") == "Done."
        assert any(n == "trace" and d["stage"] == "approval" and d["detail"].startswith("approved") for n, d in second)

        runs = (await client.get(f"/api/chats/{chat_id}")).json()["runs"]
        assert len(runs) == 1 and [line["stage"] for line in runs[0]["lines"]].count("approval") == 2


async def test_api_deny_never_runs_and_a_second_answer_or_new_message_is_refused(tmp_path):
    """Deny never runs the tool. While paused, a new message gets 409 (the held call needs an answer
    first); after the answer, a second resume gets 409, so a double click can't run anything twice."""
    ran: list = []
    async with app_with_send_tool(tmp_path, ran) as (_app, client):
        first = parse_sse((await client.post("/api/chat", json={"message": "send a note"})).text)
        chat_id = first[0][1]["chat_id"]
        assert (await client.post("/api/chat", json={"message": "hi", "chat_id": chat_id})).status_code == 409

        second = parse_sse((await client.post(f"/api/chat/{chat_id}/resume", json={"approve": False})).text)
        assert ran == [] and second[-1][0] == "done"
        assert (await client.post(f"/api/chat/{chat_id}/resume", json={"approve": True})).status_code == 409
        assert (await client.post("/api/chat/nope/resume", json={"approve": True})).status_code == 404


async def test_anything_but_an_explicit_true_is_a_no():
    """Fail closed: a malformed resume value (a string, a missing key) counts as declined."""
    ran: list = []
    graph, turn, config = start(ran)
    await graph.ainvoke(turn, config)
    await graph.ainvoke(Command(resume="yes"), config)
    assert ran == []
