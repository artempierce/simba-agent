"""
tests/test_reason.py — the reason node turns the intent and history into a Decision, safely.

Protects: the decision is stored as a plain dict (state.py needs it JSON-able for the checkpointer);
the intent is fenced as data in the prompt, not appended as free text; the history window is trimmed
to start with a human message (common.recent); "clarify" passes through untouched; and a bad or
missing reply fails open to a plain answer, since the message is already known safe by this point.
"""

from langchain_core.messages import AIMessage, HumanMessage

from simba.model import fake_model
from simba.nodes.reason import make_node
from tests.node_harness import run_node


async def test_decision_stored_as_dict():
    """The parsed Decision comes back as a plain dict, not a pydantic object."""
    model = fake_model()
    node = make_node(model)
    update, traces = await run_node(node, {"messages": [HumanMessage("hi")], "intent": "say hi"})
    assert update["decision"] == {"action": "answer", "plan": ["answer briefly"]}
    assert isinstance(update["decision"], dict)
    assert traces[0]["stage"] == "reason" and traces[0]["status"] == "ok"


async def test_intent_is_fenced_in_prompt():
    """The user's intent is sent inside <intent> tags in the system message, marked as data."""
    model = fake_model()
    node = make_node(model)
    await run_node(node, {"messages": [HumanMessage("hi")], "intent": "plan a trip to Rome"})
    system_text = model.calls[-1][0].content
    assert "<intent>plan a trip to Rome</intent>" in system_text


async def test_history_window_starts_with_human_message():
    """The trimmed history sent to the model never starts with a stray non-human message."""
    model = fake_model()
    node = make_node(model)
    history = [AIMessage("stray reply"), HumanMessage("a"), AIMessage("b"), HumanMessage("c")]
    await run_node(node, {"messages": history, "intent": "x"})
    prompt = model.calls[-1]
    assert prompt[0].type == "system"
    assert prompt[1].type == "human"  # the leading stray AI message was trimmed off


async def test_clarify_action_passes_through():
    """A "clarify" decision from the model is stored as-is; the node doesn't second-guess it."""
    model = fake_model(structured={"Decision": {"action": "clarify", "plan": ["ask about budget"]}})
    node = make_node(model)
    update, traces = await run_node(node, {"messages": [HumanMessage("plan something")], "intent": "x"})
    assert update["decision"] == {"action": "clarify", "plan": ["ask about budget"]}
    assert "clarify" in traces[0]["detail"]


async def test_failure_falls_back_to_answer_with_empty_plan():
    """A reply that doesn't match the Decision schema fails open: answer, empty plan, error trace."""
    model = fake_model(structured={"Decision": {"action": "invalid-action", "plan": []}})
    node = make_node(model)
    update, traces = await run_node(node, {"messages": [HumanMessage("hi")], "intent": "x"})
    assert update["decision"] == {"action": "answer", "plan": []}
    assert traces[0]["status"] == "error"
    assert traces[0]["detail"] == "could not plan · answering directly"
