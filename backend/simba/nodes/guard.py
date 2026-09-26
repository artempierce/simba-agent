"""
nodes/guard.py — the graph's first node: wires the deterministic checks in simba/guard.py into
LangGraph.

Where it sits: START → guard (contracts.md § 8). Every turn passes through here before intent or any
model call. `check_input()` does the actual deciding; this node just reads the newest human message,
calls it, and turns the result into a Verdict (simba/state.py) and a trace line the browser can show.
"""

import time

from langchain_core.messages import BaseMessage

from simba.common import emit_trace, text_of
from simba.guard import check_input
from simba.state import ChatState


def _newest_human_text(messages: list[BaseMessage]) -> str:
    """The text of the newest human message in `messages`.

    Guard runs right after the user's turn is added and before any reply, so this is normally just
    the last message — but scanning from the end (instead of assuming index -1) keeps the node
    correct even if a future step ever changes what comes after the human message in state.
    """
    for message in reversed(messages):
        if message.type == "human":
            return text_of(message)
    return ""


async def guard(state: ChatState) -> dict:
    """Run the deterministic input checks on this turn's message.

    1. Find the newest human message's text.
    2. Run `check_input()` (size, then injection — simba/guard.py).
    3. Build the Verdict and emit one trace line: "ok" with `check_input`'s pass reason when it
       passed, or "blocked" with `blocked · {rule}` when a rule fired.

    Returns {"verdict": Verdict} — the routing function `after_guard` (contracts.md § 8) reads
    `verdict["status"]` to send the turn to `intent` or `refuse`. Makes no model call, so a blocked
    message never reaches (and can't influence) the LLM.
    """
    start = time.perf_counter()

    # 1. Newest human message's raw text.
    text = _newest_human_text(state["messages"])

    # 2. The pure, testable check.
    result = check_input(text)

    # 3. Verdict + trace, one line either way.
    if result.rule is None:
        verdict = {"status": "pass", "rule": None, "reason": result.reason}
        emit_trace("guard", "ok", result.reason, start)
    else:
        verdict = {"status": "blocked", "rule": result.rule, "reason": result.reason}
        emit_trace("guard", "blocked", f"blocked · {result.rule}", start)

    return {"verdict": verdict}
