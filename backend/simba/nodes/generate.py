"""
simba/nodes/generate.py — the generate node: writes the actual reply, following the reason node's plan.

Where it sits: reason -> generate -> END (graph.py). The last node in a normal turn, and the only one
that makes a plain (non-structured) model call — the point here is free text for the user to read, and
LangGraph streams its tokens to the browser as they're produced (api.py forwards them for this node
only; intent/reason's "tokens" are tool-call arguments, not answer text).

Key idea: the reason node's plan is folded into the system prompt as its own block, so the model has
both its general instructions (system.md) and this turn's specific plan to follow.
"""

import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from simba.common import emit_trace, recent, tokens_used
from simba.prompts import load
from simba.state import ChatState

# How much conversation history the generate node sees. Wider than reason's HISTORY_LIMIT because
# this is what the user reads back — they may refer to something several turns earlier.
HISTORY_LIMIT = 20


def _plan_block(decision: dict) -> str:
    """Format the reason node's decision as the plan block appended to system.md.

    Example (with steps):
        ## Plan for this reply (from your reasoning step)
        action: answer
        steps:
        - greet back

    Example (no steps):
        ## Plan for this reply (from your reasoning step)
        action: answer
        steps: none, answer directly
    """
    action = decision.get("action", "answer")
    plan = decision.get("plan") or []
    if plan:
        steps_text = "steps:\n" + "\n".join(f"- {step}" for step in plan)
    else:
        steps_text = "steps: none, answer directly"
    return f"## Plan for this reply (from your reasoning step)\naction: {action}\n{steps_text}"


def make_node(model: BaseChatModel):
    """Build the generate node bound to `model` (docs/contracts.md § 7.6).

    Returns an async node function `generate(state) -> dict` that:
      1. Builds the system prompt: system.md plus a plan block describing this turn's decision.
      2. Sends it with the last HISTORY_LIMIT messages to the model as a plain call (no schema).
      3. Appends the reply to the conversation — state.py's `add_messages` reducer keeps history,
         so returning just the new message is enough.

    Why a factory: see intent.py's make_node docstring — same reason (the node needs a bound model).
    """

    async def generate(state: ChatState) -> dict:
        start = time.perf_counter()

        # 1. system.md plus this turn's plan, so the model knows both how to talk and what to do.
        system_text = load("system") + "\n\n" + _plan_block(state["decision"] or {})
        prompt = [SystemMessage(system_text), *recent(state["messages"], HISTORY_LIMIT)]

        # 2. Plain call: no with_structured_output, because the reply is free text for the user.
        reply = await model.ainvoke(prompt)

        # 3. Trace the output token count, then hand the reply back to be appended to `messages`.
        tokens = tokens_used(reply)
        emit_trace("generate", "ok", f"{tokens[1]} tokens out", start, tokens)
        return {"messages": [reply]}

    return generate
