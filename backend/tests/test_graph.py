"""
tests/test_graph.py — the step-1 graph (a single `echo` node) behaves the way api.py depends on:
it replies "You said: {text}" and emits exactly one trace line. If this breaks, api.py's SSE
tests would fail for a confusing reason (the graph, not the streaming code), so this isolates it.
"""

from langchain_core.messages import HumanMessage

from simba.graph import build_graph, echo
from simba.model import fake_model
from tests.node_harness import run_node


async def test_echo_node_via_run_node():
    """The `echo` node itself: replies "You said: {text}" and traces stage "echo", status "ok",
    detail "echoed {n} chars" — the exact shape contracts.md § 8 promises."""
    update, traces = await run_node(echo, {"messages": [HumanMessage("hi there")]})
    assert [m.content for m in update["messages"]] == ["You said: hi there"]
    assert len(traces) == 1
    assert traces[0]["stage"] == "echo"
    assert traces[0]["status"] == "ok"
    assert traces[0]["detail"] == "echoed 8 chars"


async def test_build_graph_runs_echo_end_to_end():
    """`build_graph` wires START -> echo -> END: running the compiled graph on one human message
    returns a two-message history ending in the echo reply. The fake model is passed but unused
    (contracts.md § 8 says step 1's echo doesn't call it) — protects that `build_graph` still
    accepts a model without needing it, and `model.calls == []` proves it truly went unused,
    not just unread by this assertion."""
    model = fake_model()
    graph = build_graph(model)
    turn_input = {"messages": [HumanMessage("test")], "verdict": None, "intent": None, "decision": None}
    result = await graph.ainvoke(turn_input)
    assert [m.content for m in result["messages"]] == ["test", "You said: test"]
    assert model.calls == []
