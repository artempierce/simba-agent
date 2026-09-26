"""
tests/test_generate.py — the generate node writes the reply using system.md plus the reason node's plan.

Protects: the reply is appended to the conversation; the plan block is built correctly whether the
plan has steps or is empty; the trace reports real token counts (and therefore a real cost), so the
UI's numbers mean something; and every run reports exactly one trace.
"""

from langchain_core.messages import HumanMessage

from simba.model import fake_model
from simba.nodes.generate import make_node
from tests.node_harness import run_node


async def test_reply_is_appended():
    """The model's reply comes back as a new message, ready for the `messages` reducer to append."""
    model = fake_model(reply="Hi there!")
    node = make_node(model)
    update, traces = await run_node(
        node, {"messages": [HumanMessage("hi")], "decision": {"action": "answer", "plan": ["greet back"]}}
    )
    assert update["messages"][0].content == "Hi there!"
    assert len(traces) == 1
    assert traces[0]["stage"] == "generate" and traces[0]["status"] == "ok"


async def test_system_prompt_has_system_md_and_plan_with_steps():
    """With a non-empty plan, the system prompt carries system.md's text plus each step, in order."""
    model = fake_model()
    node = make_node(model)
    _, traces = await run_node(
        node,
        {"messages": [HumanMessage("hi")], "decision": {"action": "answer", "plan": ["greet back", "ask how they are"]}},
    )
    system_text = model.calls[-1][0].content
    assert "You are Simba" in system_text  # from system.md
    assert "action: answer" in system_text
    assert "- greet back" in system_text
    assert "- ask how they are" in system_text
    assert len(traces) == 1


async def test_system_prompt_has_plan_with_no_steps():
    """An empty plan renders as "steps: none, answer directly" instead of an empty list."""
    model = fake_model()
    node = make_node(model)
    _, traces = await run_node(node, {"messages": [HumanMessage("hi")], "decision": {"action": "answer", "plan": []}})
    system_text = model.calls[-1][0].content
    assert "steps: none, answer directly" in system_text
    assert len(traces) == 1


async def test_trace_has_token_counts_and_cost():
    """The trace reports non-zero input/output tokens and a matching, non-zero cost."""
    model = fake_model()
    node = make_node(model)
    _, traces = await run_node(node, {"messages": [HumanMessage("hi")], "decision": {"action": "answer", "plan": []}})
    assert len(traces) == 1
    trace = traces[0]
    assert trace["input_tokens"] > 0 and trace["output_tokens"] > 0
    assert trace["cost_usd"] > 0
    assert trace["detail"] == f"{trace['output_tokens']} tokens out"
