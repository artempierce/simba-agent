"""
model.py — which chat model Simba talks to, a free fake one for tests, and what a call costs.

Where it sits: graph.py calls `make_model()` once and hands the model to every node that needs one
(intent, reason, generate). Nodes never import ChatAnthropic themselves, so swapping the real model
for the fake one is a single switch here.

Two models, one interface. Both are LangChain `BaseChatModel`s, so a node can't tell them apart:

  real  ChatAnthropic(claude-haiku-4-5)   costs money, needs ANTHROPIC_API_KEY
  fake  FakeChatModel                     costs $0, answers instantly, deterministic

The fake is on when SIMBA_FAKE_LLM=1 (the whole test suite and CI use it). It also supports
*structured output* — the trick the intent and reason nodes use to make the model fill fixed fields
instead of writing free text. How that works, in LangChain:

  model.with_structured_output(IntentCheck)
      → calls model.bind_tools([IntentCheck], tool_choice="any")   the schema becomes a "tool"
      → the model must reply with a tool call whose args match the schema
      → a parser turns those args into an IntentCheck object

So the fake only needs `bind_tools` (remember which schema was asked for) and a reply that is a tool
call with sensible args. Tests can dictate those args with `fake_model(structured={...})`.
"""

import json
import os
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

# The real model. Haiku is the cheapest current Claude model, plenty for a small assistant (D12).
MODEL_ID = "claude-haiku-4-5"

# Longest reply the real model may write, in tokens (~700 words). Caps the cost of one answer.
MAX_TOKENS = 1024

# US dollars per million tokens for MODEL_ID: (input, output). Used for the cost shown in the trace.
PRICE_PER_MTOK = (1.00, 5.00)

# What the fake model says when no reply is given. Says plainly that nothing was spent.
FAKE_REPLY = "Hi! I'm Simba on the fake model. No API call was made, so this reply cost $0."


def make_model() -> BaseChatModel:
    """Return the model the app should use, based on the SIMBA_FAKE_LLM environment variable.

      SIMBA_FAKE_LLM=1   -> FakeChatModel (free; tests, CI, UI work)
      anything else      -> ChatAnthropic(MODEL_ID) (paid; needs ANTHROPIC_API_KEY)

    The import of langchain_anthropic sits inside the function so fake mode never needs it configured.
    """
    if os.getenv("SIMBA_FAKE_LLM") == "1":
        return FakeChatModel()
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=MODEL_ID, max_tokens=MAX_TOKENS)


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Dollar cost of one call at PRICE_PER_MTOK.

    Example: cost_usd(1_000, 200) -> 0.001 + 0.001 = 0.002
    """
    price_in, price_out = PRICE_PER_MTOK
    return input_tokens * price_in / 1_000_000 + output_tokens * price_out / 1_000_000


def _last_user_text(messages: list[BaseMessage]) -> str:
    """The newest human message's text with any <user_message> wrapper tags removed.

    The fake uses it to build a plausible `intent` line. Example:
      [HumanMessage("<user_message>\\nhi there\\n</user_message>")] -> "hi there"
    """
    for m in reversed(messages):
        if m.type == "human":
            text = m.content if isinstance(m.content, str) else str(m.content)
            return re.sub(r"</?user_message>", "", text).strip()
    return ""


def _default_args(schema_name: str, messages: list[BaseMessage]) -> dict[str, Any]:
    """Args the fake returns for a structured-output call when a test didn't dictate them.

    Chosen so the whole app runs end to end in fake mode: every message is "safe", and the plan is
    always a one-step "answer". A schema the fake doesn't know is a programming error, so it raises.
    """
    if schema_name == "IntentCheck":
        words = _last_user_text(messages).split()[:15]
        return {"intent": " ".join(words) or "empty message", "verdict": "safe", "reason": "fake model: always safe"}
    if schema_name == "Decision":
        return {"action": "answer", "plan": ["answer briefly"]}
    raise ValueError(f"FakeChatModel has no default args for {schema_name!r}; pass fake_model(structured={{...}})")


class FakeChatModel(BaseChatModel):
    """A free, deterministic stand-in for Claude.

    Fields:
      reply       the text it answers with when no schema is bound (the generate node's call)
      structured  schema name -> the args to return for that schema, e.g.
                  {"IntentCheck": {"intent": "hack", "verdict": "injection", "reason": "asks to leak"}}
      bound       the schema names bound by with_structured_output (set by bind_tools, not by you)
      calls       every prompt it was sent, oldest first — tests read this to check what a node sent,
                  or that a node made no call at all. Shared between copies made by bind_tools, so the
                  original fake sees calls made through its bound copies too.
    """

    reply: str = FAKE_REPLY
    structured: dict[str, dict[str, Any]] = Field(default_factory=dict)
    bound: list[str] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "simba-fake"

    def bind_tools(self, tools: list, *, tool_choice: Any = None, **kwargs: Any) -> "FakeChatModel":
        """Remember which schemas were bound. Returns a copy (LangChain's convention: binding never
        changes the original model). `model_copy` is shallow, so `calls` stays the same list."""
        names = [convert_to_openai_tool(t)["function"]["name"] for t in tools]
        return self.model_copy(update={"bound": names})

    def _answer(self, messages: list[BaseMessage]) -> tuple[str, dict[str, Any] | None, dict[str, int]]:
        """Decide the reply: (text, tool_call or None, usage). Records the prompt in `calls`.

        Token counts are a rough estimate (4 characters ≈ 1 token) so the trace shows non-zero numbers.
        """
        self.calls.append(list(messages))
        tokens_in = max(1, sum(len(str(m.content)) for m in messages) // 4)
        if self.bound:
            name = self.bound[0]
            args = self.structured.get(name) or _default_args(name, messages)
            usage = {"input_tokens": tokens_in, "output_tokens": 20, "total_tokens": tokens_in + 20}
            return "", {"name": name, "args": args, "id": "fake-call-1"}, usage
        tokens_out = max(1, len(self.reply) // 4)
        return self.reply, None, {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out}

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        """One complete reply (used by plain `invoke` / `ainvoke`)."""
        text, tool_call, usage = self._answer(messages)
        message = AIMessage(content=text, tool_calls=[tool_call] if tool_call else [], usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any):
        """The same reply in pieces (used when LangGraph streams tokens to the browser).

        Text replies stream word by word, so the UI's typing effect works in fake mode too. A tool call
        comes as one chunk; LangChain joins chunks back into one message with `tool_calls`. Usage rides
        on the last chunk, like the real model's.
        """
        text, tool_call, usage = self._answer(messages)
        if tool_call:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": tool_call["name"], "args": json.dumps(tool_call["args"]), "id": tool_call["id"], "index": 0}],
                usage_metadata=usage,
            ))
            return
        words = text.split(" ")
        for i, word in enumerate(words):
            last = i == len(words) - 1
            chunk = AIMessageChunk(content=word + ("" if last else " "), usage_metadata=usage if last else None)
            if run_manager:
                run_manager.on_llm_new_token(chunk.content, chunk=ChatGenerationChunk(message=chunk))
            yield ChatGenerationChunk(message=chunk)


def fake_model(reply: str = FAKE_REPLY, structured: dict[str, dict[str, Any]] | None = None) -> FakeChatModel:
    """Build a FakeChatModel for a test.

    Example:
      model = fake_model(structured={"IntentCheck": {"intent": "x", "verdict": "injection", "reason": "y"}})
    """
    return FakeChatModel(reply=reply, structured=structured or {})
