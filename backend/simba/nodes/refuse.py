"""
nodes/refuse.py — the graph's fixed refusal reply, used whenever before_model's hooks or the agent
node's report_unsafe call blocks a message.

Where it sits: `after_before_model` / `after_agent` (graph.py) route straight here on "blocked"
(contracts.md § 8).
It never reads or repeats the user's text — the whole point of a hard-coded reply is that a blocked
message can't influence what Simba says back (CLAUDE.md's "untrusted by default" rule).
"""

import time

from langchain_core.messages import AIMessage

from simba.common import emit_trace
from simba.state import ChatState

# The fixed reply for every blocked message (D39, replaced D8's colder wording in #64): warm, short,
# and never built from the user's text, so nothing from a blocked message can reach the reply. No
# joke on purpose: a refusal can follow something serious, and humour there would land badly.
REFUSAL_TEXT = "Sorry, I can't help with that one. I'm happy to help with something else, though!"


async def refuse(state: ChatState) -> dict:
    """Reply with the fixed refusal for this turn's blocked verdict.

    1. Add REFUSAL_TEXT as the assistant's reply.
    2. Emit one trace line naming which rule blocked the message (state["verdict"]["rule"]).

    Returns {"messages": [AIMessage(REFUSAL_TEXT)]}. Makes no model call.
    """
    start = time.perf_counter()
    rule = state["verdict"]["rule"]

    # 1 & 2: fixed reply plus a trace line naming the rule that blocked this turn.
    emit_trace("refuse", "ok", f"fixed reply · {rule}", start)
    return {"messages": [AIMessage(REFUSAL_TEXT)]}
