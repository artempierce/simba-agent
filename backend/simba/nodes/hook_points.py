"""
nodes/hook_points.py — the graph's hook-point nodes: before_model and after_model (#32, D22/D29),
replacing nodes/guard.py and nodes/output_guard.py.

Where it sits: START -> before_model (contracts.md § 8, was "guard") runs before the agent node or
any model call; after the agent node (#33, was "generate"), after_model (was "output_guard") checks
the finished reply. Both nodes are thin LangGraph glue: they read the hook lists `harness/settings.py`
decides, hand them to `harness.hooks.run_hooks`, and turn the results into what the rest of the graph
reads — before_model's Verdict/flag (simba/state.py) keeps the same shape `nodes/guard.py` used to
write, so `after_before_model`/`after_agent` (graph.py) and `nodes/agent.py` (§ 7.4) don't change;
after_model's retraction (an AIMessage replacing the answer by id) is exactly what the old
output_guard node did.
"""

from collections.abc import Sequence
import json

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from simba.common import text_of
from simba.harness.classifier import InjectionClassifier
from simba.harness.hooks import run_hooks
from simba.harness.output_guard import RETRACT_TEXT
from simba.harness.settings import AFTER_MODEL, BEFORE_TOOL, before_model_hooks
from simba.state import ChatState


def _newest_human_text(messages: Sequence[BaseMessage]) -> str:
    """The text of the newest human message in `messages` (same helper the old guard node used:
    before_model runs right after the user's turn is added, so this is normally the last message —
    scanning from the end keeps it correct even if a later step changes what follows it)."""
    for message in reversed(messages):
        if message.type == "human":
            return text_of(message)
    return ""


def make_before_model(classifier: InjectionClassifier | None = None):
    """Build the before_model node, bound to `settings.before_model_hooks(classifier)` (#32, D22).

    Args:
        classifier: the local injection classifier (#8), or None; passed straight through to
                    `before_model_hooks`, same as the old guard node's factory argument.

    Returns an async node `before_model(state) -> dict` that:
      1. Finds the newest human message's text.
      2. Runs the hooks through `run_hooks("before_model", ...)` — one trace line for the whole
         point (D28/D29), stopping at the first block.
      3. A block -> Verdict "blocked" naming that hook's rule and reason (the same shape
         `nodes/guard.py` wrote, so `refuse` and `agent` need no change).
      4. No block -> Verdict "pass". Any hooks that flagged (never block, D15) have their rules
         joined with "; " into `state["flag"]` — several hooks could flag at once, where the old
         guard only ever had one (the classifier); `nodes/agent.py` reads whatever ends up there
         unchanged.
    """
    hooks = before_model_hooks(classifier)

    async def before_model(state: ChatState) -> dict:
        # 1.
        text = _newest_human_text(state["messages"])
        # 2.
        results = await run_hooks("before_model", hooks, text)

        # 3.
        blocked = next((r for r in results if r.action == "block"), None)
        if blocked is not None:
            return {"verdict": {"status": "blocked", "rule": blocked.rule, "reason": blocked.reason}}

        # 4.
        verdict = {"status": "pass", "rule": None, "reason": " · ".join(r.reason for r in results)}
        flags = [r.rule for r in results if r.action == "flag" and r.rule is not None]
        if flags:
            return {"verdict": verdict, "flag": "; ".join(flags)}
        return {"verdict": verdict}

    return before_model


async def after_model(state: ChatState) -> dict:
    """Check the newest reply against `settings.AFTER_MODEL`; retract it if a hook blocks (#15, #32).

    1. Take the reply the agent node just wrote (the newest message).
    2. Run the hooks through `run_hooks("after_model", ...)` — one trace line for the point.
    3. No block -> {} (no state change). A block -> RETRACT_TEXT under the SAME message id, so
       LangGraph's `add_messages` reducer replaces the answer in the saved history instead of
       appending — exactly what the old output_guard node did.
    """
    # 1.
    answer = state["messages"][-1]
    # 2.
    results = await run_hooks("after_model", AFTER_MODEL, text_of(answer))
    # 3.
    if not any(r.action == "block" for r in results):
        return {}
    return {"messages": [AIMessage(RETRACT_TEXT, id=answer.id)]}


async def before_tool(state: ChatState) -> dict:
    """Validate model-requested calls before ToolNode is allowed to dispatch them.

    An invalid or unknown call gets a ToolMessage explaining the denial and a state flag that routes
    straight back to the agent, never through ToolNode. Valid calls are left untouched for dispatch.
    """
    assistant_message = state["messages"][-1]
    calls_used = state["web_search_calls"]
    rejected: dict[str, str] = {}
    for index, call in enumerate(assistant_message.tool_calls):
        payload = json.dumps({"name": call["name"], "args": call["args"], "calls_used": calls_used + index})
        hook_results = await run_hooks("before_tool", BEFORE_TOOL, payload)
        blocked = next((result for result in hook_results if result.action == "block"), None)
        if blocked is not None:
            rejected[call["id"]] = blocked.reason

    if rejected:
        # Reject the whole batch and answer every call id, so valid siblings aren't left without
        # a ToolMessage when one unsafe sibling prevents dispatch.
        tool_messages = [
            ToolMessage(
                content=(
                    f"Tool request denied: {rejected[call['id']]}"
                    if call["id"] in rejected
                    else "Tool request not run because another call in this batch failed validation."
                ),
                tool_call_id=call["id"],
                name=call["name"],
            )
            for call in assistant_message.tool_calls
        ]
        return {
            "tool_call_blocked": True,
            "web_search_calls": calls_used + len(assistant_message.tool_calls),
            "messages": tool_messages,
        }
    return {
        "tool_call_blocked": False,
        "web_search_calls": calls_used + len(assistant_message.tool_calls),
    }
