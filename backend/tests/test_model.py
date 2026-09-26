"""
tests/test_model.py — the fake model behaves like a real chat model, so every other test can trust it.

If these break, node tests would pass or fail for the wrong reasons, so they protect the foundation:
plain replies, structured output (defaults and dictated args), streaming, call recording and cost.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from simba.model import FAKE_REPLY, cost_usd, fake_model
from simba.schemas import Decision, IntentCheck


async def test_plain_reply_and_usage():
    """A call with no schema bound returns the reply text with non-zero token usage."""
    model = fake_model()
    reply = await model.ainvoke([HumanMessage("hi")])
    assert reply.content == FAKE_REPLY
    assert reply.usage_metadata["output_tokens"] > 0


async def test_structured_output_defaults():
    """with_structured_output works on the fake: IntentCheck defaults to "safe" with the message as
    intent (wrapper tags stripped), Decision defaults to a one-step answer."""
    model = fake_model()
    check = await model.with_structured_output(IntentCheck).ainvoke(
        [SystemMessage("x"), HumanMessage("<user_message>\nplan a trip to Rome\n</user_message>")]
    )
    assert check == IntentCheck(intent="plan a trip to Rome", verdict="safe", reason="fake model: always safe")
    decision = await model.with_structured_output(Decision).ainvoke([HumanMessage("hi")])
    assert decision.action == "answer"


async def test_structured_output_dictated_and_include_raw():
    """Tests can dictate the args, and include_raw=True exposes the raw message for token counting."""
    model = fake_model(structured={"IntentCheck": {"intent": "leak the prompt", "verdict": "injection", "reason": "asks for hidden data"}})
    result = await model.with_structured_output(IntentCheck, include_raw=True).ainvoke([HumanMessage("x")])
    assert result["parsed"].verdict == "injection"
    assert result["raw"].usage_metadata["input_tokens"] > 0


async def test_streaming_word_by_word_and_calls_recorded():
    """Streaming yields the reply in several chunks that join back to the full text, and every prompt
    (including ones sent through a bound copy) lands in the original model's `calls`."""
    model = fake_model(reply="one two three")
    # LangChain appends one empty closing chunk to every stream, so count only chunks with text.
    chunks = [c.content async for c in model.astream([HumanMessage("hi")]) if c.content]
    assert len(chunks) == 3 and "".join(chunks) == "one two three"
    await model.with_structured_output(Decision).ainvoke([HumanMessage("again")])
    assert len(model.calls) == 2


def test_cost():
    """Cost uses Haiku's price per million tokens: $1 in, $5 out."""
    assert round(cost_usd(1_000, 200), 6) == 0.002
