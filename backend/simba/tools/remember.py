"""
remember.py — the `remember` tool (#81, D40): how Simba saves a fact about the owner by itself.

Where it sits: bound to the agent next to web_search. When the owner says something that will still
matter in a later chat, the agent calls remember(kind, fact, why). The call goes through the same
loop as a search — agent → before_tool (code checks) → tools → agent — so it shows in the trace,
the checks in harness/tool_hooks.py run first, and the agent sees "Saved" before it finishes its reply.

Key ideas:
- The decision to save is the model's, made in the same call as its answer (the prompt's Memory
  section says what's worth keeping). The limits are code: before_tool blocks a save after web
  results and a "fact" that isn't in the owner's own words; the store caps size and count and
  turns a near-duplicate into an update.
- Besides its trace line, the tool sends a `memory_event` through LangGraph's stream writer. api.py
  turns it into an SSE `memory` event, so the page can show "Remembered: … · Undo" under the reply.
"""

import time
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer

from simba.common import emit_trace
from simba.memory import MemoryFull, MemoryStore

# Trace details are shown in a narrow panel column (docs/contracts.md § 6): keep them short.
MAX_TRACE_DETAIL_CHARS = 80


def make_remember_tool(store: MemoryStore) -> BaseTool:
    """Build the `remember` tool bound to one MemoryStore (api.py passes the app's store).

    Why a factory: the tool needs the store, but a LangChain tool only receives the model's arguments
    (plus the injected run config); the closure carries the store in.
    """

    # The docstring below is what the model reads as the tool's description.
    @tool("remember")
    async def remember(
        kind: Literal["user", "feedback", "project", "reference"],
        fact: str,
        config: RunnableConfig,
        why: str | None = None,
    ) -> str:
        """Save one lasting fact about the user so you know it in later chats.

        kind: "user" (who they are, preferences), "feedback" (a correction or a way they like you to
        work — add why), "project" (ongoing work, goals, dates), "reference" (where something lives).
        fact: one short sentence in the user's own words, e.g. "Mostly works in Python".
        why: optional reason, mainly for feedback.
        """
        started = time.perf_counter()
        chat_id = config.get("configurable", {}).get("thread_id")
        # 1. Save, or update the near-duplicate (MemoryStore.remember); the store enforces the limits.
        try:
            saved, action, previous = await store.remember(kind, fact, why, source_chat_id=chat_id)
        except (MemoryFull, ValueError) as exc:
            emit_trace("remember", "error", f"not saved · {exc}"[:MAX_TRACE_DETAIL_CHARS], started)
            return f"Not saved: {exc}"
        # 2. One trace line, and the event the page uses for "Remembered: … · Undo".
        emit_trace("remember", "ok", f'{action} · {kind} · "{saved["text"]}"'[:MAX_TRACE_DETAIL_CHARS], started)
        get_stream_writer()({"memory_event": {
            "action": action, "fact_id": saved["id"], "kind": kind,
            "text": saved["text"], "previous_text": previous,
        }})
        return f"Saved ({action}): {saved['text']}"

    return remember
