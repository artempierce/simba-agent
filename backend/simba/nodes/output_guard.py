"""
nodes/output_guard.py — the graph node that checks Simba's finished answer (ticket #15).

Where it sits: generate -> output_guard -> END (graph.py). It reads the reply generate just added and
runs `check_output` (simba/output_guard.py) on it against our own prompt files.

Key idea — replacing a message by id: LangGraph's `add_messages` reducer (state.py) appends a message
with a NEW id, but a message whose id already exists REPLACES the old one in place. So to retract the
answer, this node returns an AIMessage carrying the answer's own id: the leaked text is overwritten in
the saved chat history, not just hidden on screen.
"""

import time

from langchain_core.messages import AIMessage

from simba.common import emit_trace, text_of
from simba.output_guard import RETRACT_TEXT, check_output
from simba.prompts import load
from simba.state import ChatState

# The prompt files an answer must never quote (prompts/*.md). Read on every check (load() reads the
# file each time), so an edited prompt is protected on the next message too.
PROMPT_NAMES = ("system", "intent", "reason")


async def output_guard(state: ChatState) -> dict:
    """Check the newest reply; retract it if a check fails.

    1. Take the reply generate just wrote (the newest message).
    2. Run the three checks against our prompt files.
    3. Pass → no change, trace `ok`, detail "pass · 3 checks".
       Fail → return RETRACT_TEXT under the SAME message id (replaces the answer), trace `blocked`,
       detail "retracted · {rule}". The API sees that blocked line and tells the page to swap the bubble.

    Returns {} on pass, or {"messages": [AIMessage(RETRACT_TEXT, id=<answer's id>)]} on a retraction.
    Makes no model call.
    """
    start = time.perf_counter()
    # 1.
    answer = state["messages"][-1]
    # 2.
    result = check_output(text_of(answer), [load(name) for name in PROMPT_NAMES])
    # 3.
    if result.rule is None:
        emit_trace("output_guard", "ok", result.reason, start)
        return {}
    emit_trace("output_guard", "blocked", f"retracted · {result.rule}", start)
    return {"messages": [AIMessage(RETRACT_TEXT, id=answer.id)]}
