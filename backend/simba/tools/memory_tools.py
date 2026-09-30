"""
memory_tools.py — how Simba reads and changes its own memory, by talking (#81, #87; D40, D46–D47).

Where it sits: bound to the agent next to web_search. There are no memory buttons in the UI: the
owner just talks ("what do you remember about me?", "actually I moved to Berlin", "forget that I work
at Acme") and the agent uses these tools, the way Claude Code uses its file tools on its own memory.
Every call goes through the same loop as a search — agent → before_tool (code checks) → tools → agent —
so it shows in the trace, and the checks in harness/tool_hooks.py run first.

The five tools:
  remember       save a lasting fact; a reworded repeat updates the old one (M2)
  list_memory    read what's saved, with ids — read-only
  recall_memory  find things by keyword across facts and chat summaries, or open one past chat's full
                 summary by the id the prompt's index shows (#83, D50) — read-only
  update_memory  rewrite one fact by id, e.g. after a correction
  forget_memory  delete facts (or everything) — two steps: the first call only parks the request and
                 tells the agent to ask; the delete happens when the owner's very next message is a
                 clear yes (checked here, in code — `memory.is_clear_yes`), never on the model's say-so.

Saves, updates and deletions also send a `memory_event` through LangGraph's stream writer; api.py turns
it into an SSE `memory` event so the reply can show "Remembered: … · Undo" (or "Forgot: …").
"""

import time
from typing import Annotated, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer
from langgraph.prebuilt import InjectedState

from simba.common import emit_trace, neutralise_tag, text_of
from simba.memory import MemoryFull, MemoryStore, is_clear_yes

# Trace details are shown in a narrow panel column (docs/contracts.md § 6): keep them short.
MAX_TRACE_DETAIL_CHARS = 80

Kind = Literal["user", "feedback", "project", "reference"]


def _send_memory_event(action: str, fact: dict, previous: str | None = None) -> None:
    """Tell the page what changed (api.py -> SSE `memory`), so the reply can show it with Undo."""
    get_stream_writer()({"memory_event": {
        "action": action, "fact_id": fact["id"], "kind": fact["kind"],
        "text": fact["text"], "previous_text": previous,
    }})


def _chat_id(config: RunnableConfig) -> str | None:
    """The chat this turn belongs to (LangGraph's thread id is the chat id, api.py)."""
    return config.get("configurable", {}).get("thread_id")


def make_memory_tools(store: MemoryStore) -> list[BaseTool]:
    """Build the memory tools bound to one MemoryStore (api.py passes the app's store).

    Why a factory: a LangChain tool receives only the model's arguments (plus what LangGraph injects:
    the run config, the graph state); the closure carries the store in.
    """

    # Each docstring below is what the model reads as that tool's description.
    @tool("remember")
    async def remember(kind: Kind, fact: str, config: RunnableConfig, why: str | None = None) -> str:
        """Save one lasting fact about the user so you know it in later chats.

        kind: "user" (who they are, preferences), "feedback" (a correction or a way they like you to
        work — add why), "project" (ongoing work, goals, dates), "reference" (where something lives).
        fact: one short sentence in the user's own words, e.g. "Mostly works in Python".
        why: optional reason, mainly for feedback.
        """
        started = time.perf_counter()
        try:
            saved, action, previous = await store.remember(kind, fact, why, source_chat_id=_chat_id(config))
        except (MemoryFull, ValueError) as exc:
            emit_trace("remember", "error", f"not saved · {exc}"[:MAX_TRACE_DETAIL_CHARS], started)
            return f"Not saved: {exc}"
        emit_trace("remember", "ok", f'{action} · {kind} · "{saved["text"]}"'[:MAX_TRACE_DETAIL_CHARS], started)
        _send_memory_event(action, saved, previous)
        return f"Saved ({action}): {saved['text']}"

    @tool("list_memory")
    async def list_memory(kind: Kind | None = None) -> str:
        """List what you have saved about the user, with each fact's id, newest first.

        Use it when the user asks what you remember, or before updating or forgetting a fact (you need
        its id). kind: optionally only "user", "feedback", "project" or "reference".
        """
        started = time.perf_counter()
        facts = await store.list_facts(kind)
        emit_trace("list_memory", "ok", f"{len(facts)} fact(s){' · ' + kind if kind else ''}", started)
        if not facts:
            return "Nothing saved yet."
        lines = "\n".join(
            f"[{f['id']}] {f['kind']}: {neutralise_tag(f['text'], 'memory')}"
            + (f" (why: {neutralise_tag(f['why'], 'memory')})" if f["why"] else "")
            for f in facts
        )
        return f"<memory>\n{lines}\n</memory>"

    @tool("recall_memory")
    async def recall_memory(query: str | None = None, chat: str | None = None) -> str:
        """Look something up in your memory of earlier chats and saved facts.

        chat: the id shown in "Recent chats" (e.g. "3f2a91") to read that chat's full summary.
        query: a few keywords to search every saved fact and chat summary, e.g. "Lisbon stay". If
        nothing turns up, try other words (a synonym, a name) before saying you don't remember.
        """
        started = time.perf_counter()
        # 1. Open one chat's summary by its id (like opening a memory file from the index).
        if chat:
            found = await store.summary_by_prefix(chat)
            if len(found) != 1:
                emit_trace("recall_memory", "ok", f"chat {chat} · {'ambiguous' if found else 'not found'}", started)
                return (f"More than one chat starts with {chat}; give more characters of its id."
                        if found else f"No saved summary for chat {chat}.")
            s = found[0]
            emit_trace("recall_memory", "ok", f'chat · "{s["title"]}"'[:MAX_TRACE_DETAIL_CHARS], started)
            return (f"<memory>\nChat \"{neutralise_tag(s['title'], 'memory')}\" (last updated {s['updated_at'][:10]}, "
                    f"{s['turns']} messages):\n{neutralise_tag(s['summary'], 'memory')}\n</memory>")
        # 2. Keyword search over facts and summaries (MemoryStore.search), best first.
        hits = await store.search(query or "")
        emit_trace("recall_memory", "ok", f'{len(hits)} result(s) · "{query}"'[:MAX_TRACE_DETAIL_CHARS], started)
        if not hits:
            return "Nothing found for those words. Try other words, or say you don't remember."
        lines = [
            f"[{'fact ' + h['ref'] if h['source'] == 'fact' else 'chat ' + h['ref'][:6]}] {neutralise_tag(h['text'], 'memory')}"
            for h in hits
        ]
        return "<memory>\n" + "\n".join(lines) + "\n</memory>"

    @tool("update_memory")
    async def update_memory(fact_id: int, text: str, why: str | None = None) -> str:
        """Rewrite one saved fact, e.g. when the user corrects something ("I moved to Berlin").

        fact_id: the id from list_memory. text: the new fact, one short sentence in the user's words.
        """
        started = time.perf_counter()
        old = await store.get_fact(fact_id)
        if old is None:
            emit_trace("update_memory", "error", f"no fact #{fact_id}", started)
            return f"There is no fact #{fact_id}; use list_memory to find the right id."
        try:
            new = await store.update_fact(fact_id, text=text, why=why)
        except ValueError as exc:
            emit_trace("update_memory", "error", f"not saved · {exc}"[:MAX_TRACE_DETAIL_CHARS], started)
            return f"Not saved: {exc}"
        emit_trace("update_memory", "ok", f'#{fact_id} · "{new["text"]}"'[:MAX_TRACE_DETAIL_CHARS], started)
        _send_memory_event("updated", new, old["text"])
        return f"Updated #{fact_id}: {new['text']}"

    @tool("forget_memory")
    async def forget_memory(
        config: RunnableConfig,
        state: Annotated[dict, InjectedState],
        fact_ids: list[int] | None = None,
        everything: bool = False,
    ) -> str:
        """Delete saved facts the user wants forgotten — only with their confirmation.

        Call it once with the fact_ids (from list_memory), or everything=true for all of memory. The
        first call deletes nothing: it tells you to ask the user "Forget …? (yes/no)". When they
        answer, call it again with the same arguments; it deletes only if their answer is a clear yes.
        """
        started = time.perf_counter()
        chat_id = _chat_id(config) or ""
        target: list[int] | str = "all" if everything else sorted(set(fact_ids or []))
        if not target:
            return "Say which facts to forget (fact_ids from list_memory), or everything=true."

        # 1. Which owner message are we on? The request may only be confirmed by the next one.
        human_texts = [text_of(m) for m in state["messages"] if m.type == "human"]
        human_turn = len(human_texts)
        pending = await store.get_pending(chat_id)

        # 2. Confirmed: this exact request was parked on the owner's previous message, and this
        #    message is a clear yes. Only now is anything deleted.
        if pending == (target, human_turn - 1) and is_clear_yes(human_texts[-1] if human_texts else ""):
            await store.clear_pending(chat_id)
            if target == "all":
                gone = await store.list_facts()
                await store.delete_all()
            else:
                gone = await store.delete_facts(target)
            for fact in gone:
                _send_memory_event("forgotten", fact)
            emit_trace("forget_memory", "ok", f"forgot {len(gone)} fact(s)", started)
            return f"Forgot {len(gone)} fact(s)."

        # 3. Otherwise park the request and have the agent ask. Anything else the owner says next
        #    (a "no", a new question) leaves memory untouched.
        await store.set_pending(chat_id, target, human_turn)
        facts = await store.list_facts() if target == "all" else [f for i in target if (f := await store.get_fact(i))]
        emit_trace("forget_memory", "ok", f"waiting for yes · {len(facts)} fact(s)", started)
        listed = "; ".join(f'"{f["text"]}"' for f in facts[:10]) + (" …" if len(facts) > 10 else "")
        return (f"Nothing deleted yet. Ask the user to confirm: forget {len(facts)} fact(s): {listed}? "
                "Only a clear yes in their next message lets you delete; then call forget_memory again "
                "with the same arguments.")

    return [remember, list_memory, recall_memory, update_memory, forget_memory]

