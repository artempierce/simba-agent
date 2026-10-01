"""
nodes/approval.py — the owner-approval pause (#66, D35).

Where it sits: before_tool -> approval -> tools (approved) or agent (declined). before_tool routes
here only when approval_rule (harness/tool_hooks.py) held at least one call in `approval_calls`.

Key idea: LangGraph's `interrupt(value)` stops the graph in the middle of this node and saves the
paused turn in the checkpointer. The API sends `value` to the page as an `approval` event and the
stream ends. When the owner answers, api.py's resume endpoint runs the graph again with
`Command(resume={"approve": true|false})`: LangGraph re-runs this node from the top, and this time
`interrupt()` returns that answer instead of pausing. So the approval gate is code, not a model
decision: without a "yes" from the owner the tool node is never reached.
"""

import time

from langchain_core.messages import ToolMessage
from langgraph.types import interrupt

from simba.common import emit_trace
from simba.state import ChatState

# What the model reads back when the owner says no: a plain fact, plus a nudge not to ask again.
DECLINED_TEXT = "The owner declined this action. Don't retry it; tell them it wasn't done."
NOT_RUN_TEXT = "Not run because the owner declined another call in this batch."


async def approval(state: ChatState) -> dict:
    """Wait for the owner's answer, then let the held calls run or turn them into denials.

    1. Pause with `interrupt({"calls": approval_calls})`. Nothing below runs until the owner answers.
    2. Read the answer. Only `{"approve": True}` approves; anything else is a no (fail closed).
    3. Approved: clear `approval_calls`; graph.py routes to the tool node, which runs the batch.
       Declined: answer every call id with a ToolMessage (the declined call, and its siblings as
       "not run" — a ToolNode can't run half a batch) and route back to the agent.

    Why one answer for the whole batch: the model asked for these calls together; running some and
    not others would leave the agent with a half-done plan it didn't choose.
    """
    calls = state["approval_calls"] or []
    started = time.perf_counter()
    # 1. Pause. (On resume, this line returns the owner's answer instead.)
    answer = interrupt({"calls": calls})
    # 2.
    approved = isinstance(answer, dict) and answer.get("approve") is True
    names = ", ".join(call["tool"] for call in calls)
    emit_trace("approval", "ok" if approved else "blocked", f"{'approved' if approved else 'denied'} · {names}"[:80], started)
    # 3.
    if approved:
        return {"approval_calls": None, "tool_call_blocked": False}
    held = {call["id"] for call in calls}
    messages = [
        ToolMessage(DECLINED_TEXT if call["id"] in held else NOT_RUN_TEXT, tool_call_id=call["id"], name=call["name"])
        for call in state["messages"][-1].tool_calls
    ]
    return {"approval_calls": None, "tool_call_blocked": True, "messages": messages}
