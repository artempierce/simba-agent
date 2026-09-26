"""
tests/node_harness.py — run ONE node on its own, the way the real graph would, and capture what it did.

Why this exists: nodes write trace lines with `emit_trace`, which uses LangGraph's stream writer.
That writer only works inside a running graph ("runnable context"), so calling `await node(state)`
directly in a test would fail. `run_node` wraps the node in a one-node graph and streams it, which
gives the test both the node's state update and its trace events.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from simba.state import ChatState

# The per-turn fields at their "fresh turn" values (contracts.md § 4). Merged under the test's state.
EMPTY_TURN: dict[str, Any] = {"messages": [], "verdict": None, "intent": None, "decision": None}


async def run_node(node, state: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run `node` once on `state` and return (update, traces).

    Args:
        node:  an async node function, e.g. `guard` or `make_node(fake_model())`
        state: the fields the node needs, e.g. {"messages": [HumanMessage("hi")]}; missing per-turn
               fields default to None

    Returns:
        update  the dict the node returned (what it changed in the state)
        traces  the trace events it emitted (docs/contracts.md § 6), usually exactly one

    Example:
        update, traces = await run_node(guard, {"messages": [HumanMessage("hi")]})
        assert update["verdict"]["status"] == "pass" and traces[0]["stage"] == "guard"
    """
    graph = StateGraph(ChatState)
    graph.add_node("node", node)
    graph.add_edge(START, "node")
    graph.add_edge("node", END)
    compiled = graph.compile()

    update: dict[str, Any] = {}
    traces: list[dict[str, Any]] = []
    async for mode, chunk in compiled.astream({**EMPTY_TURN, **state}, stream_mode=["updates", "custom"]):
        if mode == "custom":
            traces.append(chunk)
        elif mode == "updates":
            update = chunk.get("node") or {}
    return update, traces
