"""
api.py — the HTTP API the web page talks to. Built with FastAPI.

Where it sits: the last stop for a chat message before it reaches the graph, and the first stop
for the graph's reply on its way back to the browser. It never contains chat logic itself — that
lives in graph.py and the nodes it wires — only the plumbing: loading settings, opening storage,
and turning one graph run into server-sent events (SSE).

Endpoints:

    GET  /api/health   liveness check for the frontend/dev loop: {"ok": true}
    GET  /api/info     what this server runs with (model, web search on/off, chat budget) — #57
         /api/memory   the Memory tab: list, add, edit, delete facts, forget all (memory_api.py) — #80
    POST /api/chat      send one message; the reply streams back as SSE
         /api/chats     the chat list: list, create, open, rename, delete (chats_api.py, § 10)

Two stores share one SQLite file: LangGraph's checkpointer keeps each chat's *conversation* (the
graph state, keyed by thread_id = chat id), and ChatStore (chats.py) keeps the *sidebar's* data —
titles, timestamps and each turn's trace lines, so an old chat's trace panel can be shown again.

How POST /api/chat streams. The response is SSE: a long-lived HTTP response made of small text
blocks, each shaped like

    event: token
    data: {"text": "Hello"}
    <blank line>

The browser reads them one at a time (frontend's streamChat, contracts.md § 11). Five event types
exist, always in this order for one turn: `start` (once, first) -> any number of `trace` -> any
number of `token` -> `done` (once, last) — or `error` instead of `done` if the graph raised. A sixth,
`replace`, comes just before `done` when the output guard retracts an answer (#15). A seventh,
`memory`, reports each fact the memory tools saved, updated or forgot (#81, #87), so the page can
show it (with Undo for saves and updates). Agent text is
held until the output guard passes, so unsafe answer text is never sent to the browser.
"""

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from simba.chats import ChatStore, title_from
from simba.chats_api import router as chats_router
from simba.memory import MemoryStore
from simba.memory_api import router as memory_router
from simba.common import ms_since, text_of
from simba.graph import build_graph
from simba.harness.classifier import InjectionClassifier, load_classifier
from simba.harness.output_guard import RETRACT_TEXT
from simba.harness.settings import CHAT_BUDGET_USD
from simba.model import cost_usd, make_model, model_name
from simba.tools.memory_tools import make_memory_tools
from simba.tools.web_search import make_web_search_tool

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


def create_app(
    model: BaseChatModel | None = None,
    db_path: str | None = None,
    classifier: InjectionClassifier | None = None,
    load_real_classifier: bool = False,
    web_search_tool: BaseTool | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Args:
        model:      chat model to use; None means "decide from backend/.env" (see model.make_model).
                    Tests always pass a fake_model() so no run can ever cost money.
        db_path:    where the checkpointer's SQLite file lives; None means DEFAULT_DB_PATH. Tests
                    pass `str(tmp_path / "t.db")` so a test run never touches the real chat history.
        classifier: the guard's local prompt-injection classifier (#8, classifier.py) to use when
                    `load_real_classifier` is False; None means "off" — the guard reports "classifier
                    off" and never flags anything. Tests pass a tiny fake here, or nothing.
        load_real_classifier: True tells `lifespan` (below) to call `classifier.load_classifier()`
                    itself, once the server actually starts, ignoring `classifier`. Kept out of
                    `create_app`'s own body — not called here — because `load_classifier()` can
                    build the real ~740 MB ONNX model: doing that at import time would mean every
                    test that merely imports `create_app` pays for it too, and a corrupt model file
                    would break the import instead of just server start-up.
                web_search_tool: an optional search tool override for tests or alternate providers. When not
                        passed, a Tavily tool is built only if `TAVILY_API_KEY` is configured.

    Loads backend/.env (python-dotenv) so SIMBA_FAKE_LLM / ANTHROPIC_API_KEY are set before
    `make_model()` reads them. Building the model here is safe at import time: constructing
    ChatAnthropic doesn't call the API (§ "cost rule" — only an actual `.invoke` would), and the
    fake model never touches the network either way.

    The database itself is *not* opened here — only inside `lifespan`, below — so importing this
    module (which the bottom of this file does once, for uvicorn) never creates or locks a file.
    """
    load_dotenv(BACKEND_DIR / ".env")
    chat_model = model or make_model()
    resolved_web_search_tool = (
        web_search_tool if web_search_tool is not None else make_web_search_tool()
    )
    resolved_db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Runs once around the server's life: open storage, build the graph, clean up on exit.

        `AsyncSqliteSaver.from_conn_string` is itself an async context manager, so `async with`
        both opens its connection and guarantees it closes when the server stops. ChatStore isn't
        a context manager, so `try/finally` does the same job for it.
        """
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(resolved_db_path)) as checkpointer:
            chats = await ChatStore.open(str(resolved_db_path))
            memory = await MemoryStore.open(str(resolved_db_path))  # #80: same file, its own table
            try:
                # #8: the real classifier (if asked for) is loaded here, at start-up, not above in
                # create_app's own body — see the `load_real_classifier` docstring above.
                resolved_classifier = load_classifier() if load_real_classifier else classifier
                app.state.checkpointer = checkpointer
                app.state.chats = chats
                app.state.memory = memory
                graph_options = {"web_search_tool": resolved_web_search_tool} if resolved_web_search_tool else {}
                app.state.graph = build_graph(chat_model, checkpointer, resolved_classifier,
                                              load_profile=memory.core_profile,
                                              memory_tools=make_memory_tools(memory), **graph_options)
                yield
            finally:
                await chats.close()
                await memory.close()

    app = FastAPI(title="Simba", lifespan=lifespan)
    app.include_router(chats_router)
    app.include_router(memory_router)

    @app.get("/api/health")
    async def health():
        """Liveness check the frontend/dev loop polls for. No graph or storage touched."""
        return {"ok": True}

    @app.get("/api/info")
    async def info():
        """What this server is running with, for the header pill (#57): the model's name ("fake" for
        the free fake model), whether web search is on, and the per-chat budget.

        Why read it from the objects create_app built, not from environment variables: the pill must
        show what Simba will *really* use. A key typed into .env after the server started, for
        example, isn't in use until a restart — and the pill should say so.
        """
        return {
            "model": model_name(chat_model),
            "web_search": resolved_web_search_tool is not None,
            "chat_budget_usd": CHAT_BUDGET_USD,
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        """Run one turn of the graph and stream everything that happens back as SSE.

        Steps (contracts.md § 9):
          1. Find or create the chat's sidebar row: no chat_id → a new chat titled from this first
             message (`title_from`); a known chat_id → bump its `updated_at` so it moves to the top;
             an unknown chat_id (e.g. deleted in another tab) → 404, before any streaming starts.
          2. Send `start` with the chat id and title. Sent first, before anything below can fail.
             2b. Budget (#16): if this chat has already spent CHAT_BUDGET_USD, don't run the graph at
                 all — send one `budget` trace line and an `error` asking for a new chat, save the
                 run, and stop. Checked in code before any model call, so it can't be talked past.
          3. Reset this turn's input exactly to contracts.md § 4's shape (history itself is kept
             by the checkpointer, keyed by chat_id) and run the graph, forwarding `custom`
             chunks as `trace` and `messages` chunks as `token` (only the agent node's actual
             answer text — a `report_unsafe` call streams as tool-call chunks, not text the user
             should see).
          4. If nothing became a `token` (e.g. the refuse node's fixed reply never goes through the
             model, so it never streams as a "messages" chunk), fall back to the newest message: if it's this
             turn's AI reply (`type == "ai"` — the human message went in first, so an AI message
             at the end can only be from this turn), send its full text as one `token`;
             otherwise no reply was actually produced, so send `error` rather than letting the
             user's own message come back disguised as an answer.
             4b. If the output guard retracted the answer, send `replace` with the fixed reply.
                 Agent text is buffered until this check finishes, so blocked text never reaches
                 the browser. A `report_unsafe` call falls through to step 4's refusal fallback.
          5. Send `done` with totals summed from the `trace` events. Steps 3-4 share one
             try/except so *any* exception after `start` — from the graph itself, or from step
             4's own state lookup — becomes an `error` event instead of the stream just stopping.
          6. Save the turn's run (prompt, trace lines, totals or error) with the chat, so opening
             this chat later shows its trace panel again. Saved on every ending: done or error.
          7. If the stream is cut off before step 6 (the browser disconnected), save the run anyway,
             marked as interrupted — so a reopened chat never shows a message without its trace.
             (Rare edge case: if the cancellation instead lands while the ASGI server's own `send()`
             call is blocked on backpressure — outside this generator entirely — the save can't run
             until Python later closes the abandoned generator, e.g. via garbage collection, so it's
             no longer deterministic in that one case.)
        """
        graph = app.state.graph
        chats: ChatStore = app.state.chats
        # 1. Find or create the sidebar row. An id we don't know is refused, never created: the
        #    client's text must not become a database key (untrusted input — CLAUDE.md).
        if req.chat_id is None:
            chat = await chats.create(title_from(req.message))
        elif (chat := await chats.get(req.chat_id)) is not None:
            await chats.touch(chat["id"])
        else:
            raise HTTPException(status_code=404, detail="chat not found")
        chat_id = chat["id"]
        config = {"configurable": {"thread_id": chat_id}}

        async def events():
            """The SSE stream for this turn: `stream_turn` below, plus a guarantee that the turn's
            run is saved even if the stream is cut off (step 7)."""
            lines: list[dict] = []  # this turn's trace lines, kept for steps 6–7
            saved = False

            async def save_run(summary: dict | None, error: str | None) -> None:
                """6. Store this turn's trace block with the chat (see chats.ChatStore.add_run)."""
                nonlocal saved
                saved = True
                await chats.add_run(chat_id, req.message, lines, summary, error)

            try:
                async for event in stream_turn(lines, save_run):
                    yield event
            finally:
                # 7. The browser went away mid-answer (tab closed, "New chat" clicked): Starlette
                #    delivers this as cancellation of this generator, which skips the saves above.
                #    Save what we have, marked as interrupted. `CancelScope(shield=True)` lets this
                #    one await finish even though the surrounding task is being cancelled. (If the
                #    cancellation instead catches this task while it's blocked inside `send()` itself
                #    — backpressure from a slow client — it never reaches this generator's code at
                #    all, so the shield can't help; the save then only happens once the abandoned
                #    generator is closed by garbage collection, which is rare and not deterministic.)
                if not saved:
                    with anyio.CancelScope(shield=True):
                        await chats.add_run(chat_id, req.message, lines, None, "interrupted before the reply finished")

        async def stream_turn(lines: list[dict], save_run):
            """Steps 2–6 for one turn, yielding SSE strings (see `chat`'s docstring)."""
            started = time.perf_counter()
            # 2. Send `start` first, always, before anything below can fail.
            yield sse("start", {"chat_id": chat_id, "title": chat["title"]})

            # 2b. Refuse the turn if the chat is out of budget. The trace line is built here, not
            #     with common.emit_trace, because no graph node is running to stream it.
            spent = await chats.spent_usd(chat_id)
            if spent >= CHAT_BUDGET_USD:
                message = f"This chat reached its ${CHAT_BUDGET_USD:.2f} budget. Please start a new chat."
                line = {
                    "stage": "budget",
                    "status": "blocked",
                    "detail": f"spent ${spent:.4f} of ${CHAT_BUDGET_USD:.2f}",
                    "ms": ms_since(started),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
                lines.append(line)
                yield sse("trace", line)
                await save_run(None, message)
                yield sse("error", {"message": message})
                return

            turn_input = {
                "messages": [HumanMessage(req.message)],
                "verdict": None,
                "flag": None,
                "tool_call_blocked": None,
                "web_search_calls": 0,
            }
            tokens_in = tokens_out = 0
            token_sent = False
            answer_chunks: list[str] = []  # withheld until after_model confirms the full reply is safe
            retracted = False  # set when the output guard (#15) retracts this turn's answer
            agent_unsafe = False  # set when the agent's report_unsafe call blocks this turn (#33)
            try:
                # 3. Run the graph. Trace lines stream immediately; answer chunks wait for the
                #    completed reply's after_model check before they can reach the browser.
                async for mode, chunk in graph.astream(turn_input, config, stream_mode=["messages", "custom"]):
                    if mode == "custom" and "memory_event" in chunk:
                        # #81: the remember tool saved a fact; the page shows "Remembered: … · Undo".
                        yield sse("memory", chunk["memory_event"])
                    elif mode == "custom":
                        tokens_in += chunk.get("input_tokens", 0)
                        tokens_out += chunk.get("output_tokens", 0)
                        lines.append(chunk)
                        if chunk.get("stage") == "before_tool":
                            # Text emitted before a tool request isn't the final answer checked by
                            # after_model; discard it before the next agent iteration.
                            answer_chunks.clear()
                        if chunk.get("stage") == "after_model" and chunk.get("status") == "blocked":
                            retracted = True
                        elif chunk.get("stage") == "agent" and chunk.get("status") == "blocked":
                            agent_unsafe = True
                        yield sse("trace", chunk)
                    else:
                        message, metadata = chunk
                        if metadata.get("langgraph_node") == "agent" and (text := text_of(message)):
                            answer_chunks.append(text)

                # 4. Release model output only after its full answer passed after_model. The graph
                #    has already replaced a blocked answer in saved state; don't expose its chunks.
                if not retracted and not agent_unsafe and answer_chunks:
                    for text in answer_chunks:
                        token_sent = True
                        yield sse("token", {"text": text})

                # Refusals and other non-streamed replies come from the newest AI message. Never
                # fall back to state for a retracted answer: its replacement is sent below instead.
                if not token_sent and not retracted:
                    state = await graph.aget_state(config)
                    last = state.values["messages"][-1]
                    if last.type == "ai":
                        yield sse("token", {"text": text_of(last)})
                    else:
                        await save_run(None, "no reply was produced")
                        yield sse("error", {"message": "no reply was produced"})
                        return

                # 4b. Replace the empty reply bubble when after_model retracted the buffered answer.
                if retracted:
                    yield sse("replace", {"text": RETRACT_TEXT})
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                await save_run(None, message)
                yield sse("error", {"message": message})
                return

            # 5. Totals summed from the trace events above.
            summary = {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "cost_usd": cost_usd(tokens_in, tokens_out),
                "ms": ms_since(started),
            }
            await save_run(summary, None)
            yield sse("done", summary)

        # "no-cache" stops proxies/browsers from buffering the stream.
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app


# The app object uvicorn serves: `uv run uvicorn simba.api:app --reload --port 8000`.
# `load_real_classifier=True` defers `load_classifier()` to the lifespan (server start-up), not
# this import — so `from simba.api import create_app` (every test) never loads the ~740 MB model.
app = create_app(load_real_classifier=True)
