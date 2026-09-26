"""
tests/test_api.py — the FastAPI app (contracts.md § 9): health check, the POST /api/chat SSE
stream's event order and payloads, chat-id handling (new vs. continued chat), and that a node
exception surfaces as an `error` event instead of crashing the request.

Every test builds its own app with `create_app(model=fake_model(), db_path=...)` so no test ever
touches the real database or makes a network call, and runs it through `app.router.lifespan_context`
so `app.state.graph` / `.checkpointer` exist exactly as they would under uvicorn (contracts.md § 12).
"""

import json
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from simba.api import create_app
from simba.model import fake_model
from simba.state import ChatState


@asynccontextmanager
async def running_app(**create_app_kwargs):
    """Build an app, run its lifespan, and hand back an AsyncClient wired straight to it (no
    real network socket — ASGITransport calls the app in-process).

    Why this helper: every test below needs the same three lines (create_app, enter the lifespan,
    build the client), and duplicating them per test would bury what each test is actually
    checking (contracts.md § 12's required pattern).
    """
    app = create_app(**create_app_kwargs)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield app, client


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Turn a raw SSE response body into [(event_name, data_dict), ...], in the order they arrived.

    Example: "event: start\\ndata: {\"a\": 1}\\n\\n" -> [("start", {"a": 1})]
    """
    events = []
    for block in text.strip("\n").split("\n\n"):
        if not block:
            continue
        event_line, data_line = block.split("\n")
        events.append((event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
    return events


async def test_health(tmp_path):
    """GET /api/health reports liveness without touching the graph or storage."""
    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (_app, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


async def test_chat_event_order_and_echo_fallback_token(tmp_path):
    """One turn on the step-1 graph produces events in order start -> trace -> token -> done, and
    since `echo` never streams through the model, its reply reaches the browser via the fallback
    token (contracts.md § 9's "if no token was sent" rule) — not a real streamed token."""
    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (_app, client):
        resp = await client.post("/api/chat", json={"message": "hello", "chat_id": None})
        events = parse_sse(resp.text)

        names = [name for name, _ in events]
        assert names == ["start", "trace", "token", "done"]

        _, start_data = events[0]
        assert start_data["title"] == "New chat"
        assert isinstance(start_data["chat_id"], str) and start_data["chat_id"]

        _, trace_data = events[1]
        assert trace_data["stage"] == "echo" and trace_data["status"] == "ok"

        _, token_data = events[2]
        assert token_data == {"text": "You said: hello"}


async def test_chat_done_totals(tmp_path):
    """`done`'s totals are summed from the trace events: echo's trace carries no token usage
    (it never calls the model), so both counts and the cost are zero, and `ms` is a real reading."""
    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (_app, client):
        resp = await client.post("/api/chat", json={"message": "hi", "chat_id": None})
        events = parse_sse(resp.text)
        _, done_data = events[-1]
        assert done_data["input_tokens"] == 0
        assert done_data["output_tokens"] == 0
        assert done_data["cost_usd"] == 0.0
        assert done_data["ms"] >= 0


async def test_second_message_continues_same_chat(tmp_path):
    """Posting again with the chat_id from the first `start` event continues the same LangGraph
    thread: the checkpointer's saved state ends up with all 4 messages (2 turns × human+echo),
    proving the per-turn input reset (contracts.md § 4) doesn't wipe earlier history."""
    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (app, client):
        first = parse_sse((await client.post("/api/chat", json={"message": "one", "chat_id": None})).text)
        chat_id = first[0][1]["chat_id"]

        await client.post("/api/chat", json={"message": "two", "chat_id": chat_id})

        state = await app.state.graph.aget_state({"configurable": {"thread_id": chat_id}})
        assert [m.content for m in state.values["messages"]] == [
            "one", "You said: one", "two", "You said: two",
        ]


async def test_new_chat_without_id_gets_different_ids(tmp_path):
    """Two requests with chat_id: null each mint their own uuid4 hex — one request never
    accidentally reuses another's chat."""
    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (_app, client):
        first = parse_sse((await client.post("/api/chat", json={"message": "a", "chat_id": None})).text)
        second = parse_sse((await client.post("/api/chat", json={"message": "b", "chat_id": None})).text)
        assert first[0][1]["chat_id"] != second[0][1]["chat_id"]


async def test_chat_error_event_on_node_exception(monkeypatch, tmp_path):
    """A node that raises produces an `error` event instead of a broken/hanging response. Kept
    simple: `simba.api.build_graph` is monkeypatched (for this test only) to compile a one-node
    graph whose node always raises, standing in for a future real node's bug."""

    def broken_build_graph(model, checkpointer=None):
        async def boom(state):
            raise RuntimeError("node boom")

        graph = StateGraph(ChatState)
        graph.add_node("boom", boom)
        graph.add_edge(START, "boom")
        graph.add_edge("boom", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr("simba.api.build_graph", broken_build_graph)

    async with running_app(model=fake_model(), db_path=str(tmp_path / "t.db")) as (_app, client):
        resp = await client.post("/api/chat", json={"message": "hi", "chat_id": None})
        events = parse_sse(resp.text)

        assert [name for name, _ in events] == ["start", "error"]
        assert "node boom" in events[-1][1]["message"]
