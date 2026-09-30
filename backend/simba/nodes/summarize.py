"""
nodes/summarize.py — keeps each chat's rolling summary up to date (#82, D41): episodic memory.

Where it sits: after after_model on every answered turn; it returns at once unless the chat has at
least SUMMARY_EVERY new owner turns since its summary was last written (`needs_summary`) — one cheap
database read, and no trace line, on the turns in between. One model call merges the previous
summary with the new turns, using the fixed template in prompts/summary.md, and the result is stored
with the chat (MemoryStore.save_summary). Later chats see a one-line index of recent summaries in their
prompt (MemoryStore.core_profile) — how Simba remembers what happened, not just facts.

Key ideas:
- Like Claude Code's compaction: older turns are condensed, and the summary is rewritten rather than
  appended to, so it stays short however long the chat gets.
- The conversation is untrusted text: it goes to the model fenced in <conversation> tags (escaped with
  neutralise_tag) and the template says it's data, never instructions.
- This call's tokens are never streamed to the chat (api.py forwards only the agent node's text), but
  its trace line carries the tokens and cost, so it counts toward the chat's budget like any call.
"""

import time
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from simba.common import emit_trace, neutralise_tag, text_of, tokens_used
from simba.memory import SUMMARY_EVERY, MemoryStore
from simba.prompts import load
from simba.state import ChatState

# The most characters of conversation one summary call reads. ~6 turns of normal chat fit easily;
# a turn with a huge answer is cut rather than making the call (and its cost) grow without limit.
MAX_CONVERSATION_CHARS = 12_000


def owner_turns(state: ChatState) -> int:
    """How many messages the owner has sent in this chat so far."""
    return sum(1 for m in state["messages"] if m.type == "human")


def make_summarize_node(model: BaseChatModel, store: MemoryStore) -> Callable:
    """Build the summarize node for one model and memory store (graph.py binds them once).

    The returned node, `summarize(state, config) -> {}`:
      1. Reads the chat's previous summary and how many owner turns it covers; stops here unless a
         new summary is due (needs_summary).
      2. Collects the conversation since then: owner and Simba text only (tool calls and raw search
         results are left out; the answer that used them is enough), capped at MAX_CONVERSATION_CHARS.
      3. Asks the model for the updated summary (prompts/summary.md), both inputs fenced as data.
      4. Stores it with the new turn count, and writes one trace line.
    It changes no graph state: the summary lives in the memory store, not in the conversation.
    """

    async def summarize(state: ChatState, config: RunnableConfig) -> dict:
        started = time.perf_counter()
        chat_id = config["configurable"]["thread_id"]
        # 1.
        previous = await store.get_summary(chat_id)
        covered = previous["turns"] if previous else 0
        if not needs_summary(covered, owner_turns(state)):
            return {}

        # 2. The turns after the last summarised one: skip `covered` owner messages, keep the rest.
        new_lines, seen = [], 0
        for message in state["messages"]:
            if message.type == "human":
                seen += 1
            if seen <= covered or message.type not in ("human", "ai") or not text_of(message):
                continue
            who = "User" if message.type == "human" else "Simba"
            new_lines.append(f"{who}: {text_of(message)}")
        conversation = "\n".join(new_lines)[-MAX_CONVERSATION_CHARS:]

        # 3.
        prompt = [
            SystemMessage(load("summary")),
            HumanMessage(
                f"<previous_summary>\n{neutralise_tag(previous['summary'], 'previous_summary') if previous else '(none yet)'}\n</previous_summary>\n\n"
                f"<conversation>\n{neutralise_tag(conversation, 'conversation')}\n</conversation>"
            ),
        ]
        reply = await model.ainvoke(prompt)
        summary = text_of(reply).strip()

        # 4.
        turns = owner_turns(state)
        if summary:
            await store.save_summary(chat_id, summary, turns)
        words = len(summary.split())
        emit_trace("summarize", "ok" if summary else "error",
                   f"{'updated' if previous else 'first summary'} · {turns} turns · {words} words", started,
                   tokens_used(reply))
        return {}

    return summarize


def needs_summary(summarized_turns: int, turns_now: int) -> bool:
    """Whether a chat is due a new summary: at least SUMMARY_EVERY owner turns since the last one.

    Example: needs_summary(0, 6) -> True; needs_summary(6, 11) -> False; needs_summary(6, 12) -> True
    """
    return turns_now - summarized_turns >= SUMMARY_EVERY
