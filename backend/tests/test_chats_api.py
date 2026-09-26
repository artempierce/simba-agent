"""
tests/test_chats_api.py — the /api/chats router (simba/chats_api.py) end to end, against a tiny
stand-in graph instead of Simba's real guard/intent/reason/generate graph.

The test app wires up exactly what the router reads off `request.app.state`: a ChatStore, an
AsyncSqliteSaver checkpointer, and a one-node graph compiled with that checkpointer. That's enough to
exercise every endpoint, including proving that DELETE really erases the checkpointer's saved state
(not just the ChatStore row).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from simba.chats import ChatStore
from simba.chats_api import router
from simba.state import ChatState


async def _reply(state: ChatState) -> dict:
    """The stand-in graph's only node: always answers "pong", so no real model is needed to test the API."""
    return {"messages": [AIMessage("pong")]}


@asynccontextmanager
async def _test_app(tmp_path):
    """Build a FastAPI app carrying the app.state the router expects: .chats, .checkpointer, .graph.

    Library concept: `AsyncSqliteSaver.from_conn_string` is an async context manager because it owns
    a real database connection that must be closed; `async with` guarantees that even if a test fails
    partway through. Yields (app, chats, graph) so tests can also assert on the store/graph directly.
    """
    db_path = str(tmp_path / "t.db")
    chats = await ChatStore.open(db_path)
    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        builder = StateGraph(ChatState)
        builder.add_node("reply", _reply)
        builder.add_edge(START, "reply")
        builder.add_edge("reply", END)
        graph = builder.compile(checkpointer=checkpointer)

        app = FastAPI()
        app.include_router(router)
        app.state.chats = chats
        app.state.checkpointer = checkpointer
        app.state.graph = graph
        try:
            yield app, chats, graph
        finally:
            await chats.close()


async def _seed_thread(graph, chat_id: str) -> None:
    """Give a chat some checkpointed history by running the stand-in graph on its thread id, the same
    per-turn input shape api.py sends (docs/contracts.md § 4)."""
    await graph.ainvoke(
        {"messages": [HumanMessage("hi")], "verdict": None, "intent": None, "decision": None},
        {"configurable": {"thread_id": chat_id}},
    )


async def test_create_list_and_get_chat(tmp_path):
    """POST creates a chat (201); GET / lists it; GET /{id} returns the chat, its messages (built
    from the graph's checkpointed state, human/ai only) and its runs."""
    async with _test_app(tmp_path) as (app, chats, graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/chats", json={"title": "trip"})
            assert created.status_code == 201
            chat_id = created.json()["id"]
            assert created.json()["title"] == "trip"

            listed = await client.get("/api/chats")
            assert listed.status_code == 200
            assert [c["id"] for c in listed.json()] == [chat_id]

            await _seed_thread(graph, chat_id)
            detail = await client.get(f"/api/chats/{chat_id}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["chat"]["id"] == chat_id
            assert body["messages"] == [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "pong"},
            ]
            assert body["runs"] == []


async def test_create_without_title_defaults_to_new_chat(tmp_path):
    """POST with no title in the body still creates a usable chat, titled "New chat" (same rule
    title_from uses for an empty message)."""
    async with _test_app(tmp_path) as (app, chats, graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/chats", json={})
            assert created.status_code == 201
            assert created.json()["title"] == "New chat"


async def test_rename_chat_trims_and_validates_title_length(tmp_path):
    """PATCH trims the title and rejects an empty or over-80-character title with 422
    (docs/contracts.md § 10: "1-80 chars after trim")."""
    async with _test_app(tmp_path) as (app, chats, graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            chat_id = (await client.post("/api/chats", json={"title": "old"})).json()["id"]

            ok = await client.patch(f"/api/chats/{chat_id}", json={"title": "  new title  "})
            assert ok.status_code == 200
            assert ok.json()["title"] == "new title"

            empty = await client.patch(f"/api/chats/{chat_id}", json={"title": "   "})
            assert empty.status_code == 422

            too_long = await client.patch(f"/api/chats/{chat_id}", json={"title": "x" * 81})
            assert too_long.status_code == 422


async def test_delete_chat_removes_row_and_checkpointed_state(tmp_path):
    """DELETE returns 204 and erases both the ChatStore row and the checkpointer's thread history, so
    a re-fetch of that thread's state has no messages left."""
    async with _test_app(tmp_path) as (app, chats, graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            chat_id = (await client.post("/api/chats", json={"title": "bye"})).json()["id"]
            await _seed_thread(graph, chat_id)

            deleted = await client.delete(f"/api/chats/{chat_id}")
            assert deleted.status_code == 204

            assert await chats.get(chat_id) is None
            state = await graph.aget_state({"configurable": {"thread_id": chat_id}})
            assert state.values.get("messages", []) == []


async def test_unknown_chat_id_returns_404(tmp_path):
    """GET, PATCH and DELETE on an unknown id all report the same shared 404 shape."""
    async with _test_app(tmp_path) as (app, chats, graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for response in (
                await client.get("/api/chats/nope"),
                await client.patch("/api/chats/nope", json={"title": "x"}),
                await client.delete("/api/chats/nope"),
            ):
                assert response.status_code == 404
                assert response.json() == {"detail": "chat not found"}
