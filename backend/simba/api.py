"""
api.py — the HTTP API the web page talks to. Built with FastAPI.

Where it sits: the last stop for a chat message before it reaches the graph, and the first stop
for the graph's reply on its way back to the browser. It never contains chat logic itself — that
lives in graph.py and the nodes it wires — only the plumbing: loading settings, opening storage,
and turning one graph run into server-sent events (SSE).

Endpoints (step 1; § 10 adds a `/api/chats` router in step 6):

    GET  /api/health   liveness check for the frontend/dev loop: {"ok": true}
    POST /api/chat      send one message; the reply streams back as SSE

How POST /api/chat streams. The response is SSE: a long-lived HTTP response made of small text
blocks, each shaped like

    event: token
    data: {"text": "Hello"}
    <blank line>

The browser reads them one at a time (frontend's streamChat, contracts.md § 11). Five event types
exist, always in this order for one turn: `start` (once, first) -> any number of `trace` -> any
number of `token` -> `done` (once, last) — or `error` instead of `done` if the graph raised.
"""

import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from simba.common import ms_since, text_of
from simba.graph import build_graph
from simba.model import cost_usd, make_model

# backend/.env holds SIMBA_FAKE_LLM / ANTHROPIC_API_KEY (git-ignored: the repo is public).
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Default chat database, at the repo root so it sits next to docs/ and frontend/, not inside
# backend/. Tests always pass their own db_path (a tmp_path file) instead of touching this.
DEFAULT_DB_PATH = BACKEND_DIR.parent / "data" / "simba.db"


class ChatRequest(BaseModel):
    """The JSON body of POST /api/chat (contracts.md § 9).

    message  what the user typed
    chat_id  which chat this continues; null starts a new chat (the server makes an id)
    """

    message: str
    chat_id: str | None = None


def sse(event: str, data: dict) -> str:
    """Format one server-sent event: an `event:` line, a `data:` line (JSON), a blank line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def create_app(model: BaseChatModel | None = None, db_path: str | None = None) -> FastAPI:
    """Build the FastAPI app.

    Args:
        model:   chat model to use; None means "decide from backend/.env" (see model.make_model).
                 Tests always pass a fake_model() so no run can ever cost money.
        db_path: where the checkpointer's SQLite file lives; None means DEFAULT_DB_PATH. Tests
                 pass `str(tmp_path / "t.db")` so a test run never touches the real chat history.

    Loads backend/.env (python-dotenv) so SIMBA_FAKE_LLM / ANTHROPIC_API_KEY are set before
    `make_model()` reads them. Building the model here is safe at import time: constructing
    ChatAnthropic doesn't call the API (§ "cost rule" — only an actual `.invoke` would), and the
    fake model never touches the network either way.

    The database itself is *not* opened here — only inside `lifespan`, below — so importing this
    module (which the bottom of this file does once, for uvicorn) never creates or locks a file.
    """
    load_dotenv(BACKEND_DIR / ".env")
    chat_model = model or make_model()
    resolved_db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Runs once around the server's life: open storage, build the graph, clean up on exit.

        `AsyncSqliteSaver.from_conn_string` is itself an async context manager, so `async with`
        both opens its connection and guarantees it closes when the server stops.
        """
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(resolved_db_path)) as checkpointer:
            app.state.checkpointer = checkpointer
            app.state.graph = build_graph(chat_model, checkpointer)
            yield

    app = FastAPI(title="Simba", lifespan=lifespan)

    @app.get("/api/health")
    async def health():
        """Liveness check the frontend/dev loop polls for. No graph or storage touched."""
        return {"ok": True}

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        """Run one turn of the graph and stream everything that happens back as SSE.

        Steps (contracts.md § 9):
          1. Pick the chat id: the one given, or a fresh uuid4 hex for a new chat.
          2. Send `start` with that id and a title (step 1: always "New chat" — step 6 swaps
             this for `chats.title_from(req.message)` once real chat titles exist). Sent first,
             before anything below can fail.
          3. Reset this turn's input exactly to contracts.md § 4's shape (history itself is kept
             by the checkpointer, keyed by chat_id) and run the graph, forwarding `custom`
             chunks as `trace` and `messages` chunks as `token` (only the generate node's actual
             answer text — other nodes' model calls are structured-output tool calls, not text
             the user should see).
          4. If nothing became a `token` (e.g. the refuse node's fixed reply never goes through the
             model, so it never streams as a "messages" chunk), fall back to the newest message: if it's this
             turn's AI reply (`type == "ai"` — the human message went in first, so an AI message
             at the end can only be from this turn), send its full text as one `token`;
             otherwise no reply was actually produced, so send `error` rather than letting the
             user's own message come back disguised as an answer.
          5. Send `done` with totals summed from the `trace` events. Steps 3-4 share one
             try/except so *any* exception after `start` — from the graph itself, or from step
             4's own state lookup — becomes an `error` event instead of the stream just stopping.
        """
        graph = app.state.graph
        # 1. Pick the chat id: the one given, or a fresh uuid4 hex for a new chat.
        chat_id = req.chat_id or uuid.uuid4().hex
        config = {"configurable": {"thread_id": chat_id}}

        async def events():
            started = time.perf_counter()
            # 2. Send `start` first, always, before anything below can fail.
            yield sse("start", {"chat_id": chat_id, "title": "New chat"})

            turn_input = {
                "messages": [HumanMessage(req.message)],
                "verdict": None,
                "intent": None,
                "decision": None,
            }
            tokens_in = tokens_out = 0
            token_sent = False
            try:
                # 3. Run the graph, forwarding trace lines and the generate node's answer text.
                async for mode, chunk in graph.astream(turn_input, config, stream_mode=["messages", "custom"]):
                    if mode == "custom":
                        tokens_in += chunk.get("input_tokens", 0)
                        tokens_out += chunk.get("output_tokens", 0)
                        yield sse("trace", chunk)
                    else:
                        message, metadata = chunk
                        if metadata.get("langgraph_node") == "generate" and (text := text_of(message)):
                            token_sent = True
                            yield sse("token", {"text": text})

                # 4. No streamed token (e.g. refuse, which never calls the model): fall back to the
                #    newest message, but only if it's really this turn's reply.
                if not token_sent:
                    state = await graph.aget_state(config)
                    last = state.values["messages"][-1]
                    if last.type == "ai":
                        yield sse("token", {"text": text_of(last)})
                    else:
                        yield sse("error", {"message": "no reply was produced"})
                        return
            except Exception as exc:
                yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})
                return

            # 5. Totals summed from the trace events above.
            yield sse("done", {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "cost_usd": cost_usd(tokens_in, tokens_out),
                "ms": ms_since(started),
            })

        # "no-cache" stops proxies/browsers from buffering the stream.
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app


# The app object uvicorn serves: `uv run uvicorn simba.api:app --reload --port 8000`.
app = create_app()
