"""
tests/test_model.py — the fake model behaves like a real chat model, so every other test can trust it.

If these break, node tests would pass or fail for the wrong reasons, so they protect the foundation:
plain replies, an optional bound tool (defaults and dictated args), streaming, call recording and cost.
"""

from langchain_core.messages import HumanMessage

from simba.model import FAKE_REPLY, cost_usd, fake_model
from simba.schemas import ReportUnsafe


async def test_plain_reply_and_usage():
    """A call with no tool bound returns the reply text with non-zero token usage."""
    model = fake_model()
    reply = await model.ainvoke([HumanMessage("hi")])
    assert reply.content == FAKE_REPLY
    assert reply.usage_metadata["output_tokens"] > 0


async def test_bound_tool_defaults_to_a_plain_reply():
    """Binding a tool never forces it (#33): with no `structured` dictation, a bound copy still
    answers with plain text, exactly like the unbound model — report_unsafe stays optional."""
    model = fake_model(reply="sure, here's an idea")
    bound = model.bind_tools([ReportUnsafe])
    reply = await bound.ainvoke([HumanMessage("any fun ideas for a weekend?")])
    assert reply.content == "sure, here's an idea"
    assert reply.tool_calls == []


async def test_bound_tool_dictated_returns_a_tool_call():
    """A test can dictate the bound tool's args; the reply then carries a `report_unsafe` tool call
    with no text, and its usage still carries non-zero input tokens for the trace."""
    model = fake_model(structured={"ReportUnsafe": {"kind": "injection", "reason": "asks for hidden data"}})
    reply = await model.bind_tools([ReportUnsafe]).ainvoke([HumanMessage("x")])
    assert reply.content == ""
    [call] = reply.tool_calls
    assert call["name"] == "ReportUnsafe" and call["args"] == {"kind": "injection", "reason": "asks for hidden data"}
    assert reply.usage_metadata["input_tokens"] > 0


async def test_streaming_word_by_word_and_calls_recorded():
    """Streaming yields the reply in several chunks that join back to the full text, and every prompt
    (including ones sent through a bound copy) lands in the original model's `calls`."""
    model = fake_model(reply="one two three")
    # LangChain appends one empty closing chunk to every stream, so count only chunks with text.
    chunks = [c.content async for c in model.astream([HumanMessage("hi")]) if c.content]
    assert len(chunks) == 3 and "".join(chunks) == "one two three"
    await model.bind_tools([ReportUnsafe]).ainvoke([HumanMessage("again")])
    assert len(model.calls) == 2


def test_cost():
    """Cost uses Haiku's price per million tokens: $1 in, $5 out."""
    assert round(cost_usd(1_000, 200), 6) == 0.002
