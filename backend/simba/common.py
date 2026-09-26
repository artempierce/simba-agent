"""
common.py — small helpers every node shares: reading a message's text and token counts, timing,
and writing one line to the trace panel.

The trace line is the key idea. A node calls `emit_trace(...)` once when it finishes. That uses
LangGraph's *stream writer* (`get_stream_writer`): anything written to it comes out of
`graph.astream(..., stream_mode="custom")`, which api.py forwards to the browser as a `trace` event.
So the node doesn't know about HTTP or the UI — it just reports what it did.
"""

import re
import time

from langchain_core.messages import BaseMessage
from langgraph.config import get_stream_writer

from simba.model import cost_usd


def neutralise_tag(text: str, tag: str) -> str:
    """Escape every opening/closing form of `<tag>` in `text` so it can't be mistaken for a real
    delimiter a prompt wraps untrusted data in (see intent.py, reason.py).

    Untrusted text (a user's message, or a model's restatement of it) must never be able to fake the
    end of the tag it's about to be wrapped in and have whatever follows read as a fresh instruction.
    Matches the tag name case-insensitively and tolerates whitespace slipped around the slash — the
    cheap tricks for hiding a closing tag from a naive string check — but keeps the matched text's own
    casing and spacing, only turning "<" into "&lt;" so it renders as plain text instead of a tag.

    Examples:
        neutralise_tag("<user_message>", "user_message")   -> "&lt;user_message>"
        neutralise_tag("</ USER_message", "user_message")  -> "&lt;/ USER_message"
        neutralise_tag("<  /  intent", "intent")            -> "&lt;  /  intent"
    """
    # `\s*(?:/\s*)?` instead of `\s*/?\s*`: two adjacent `\s*` can split a run of spaces in n ways,
    # so "<" + 4,000 spaces took ~200 ms (quadratic backtracking). This form matches the same tags in
    # linear time. re.escape keeps a tag name from being read as regex syntax.
    return re.sub(rf"<(\s*(?:/\s*)?{re.escape(tag)})", r"&lt;\1", text, flags=re.IGNORECASE)


def text_of(message: BaseMessage) -> str:
    """A message's plain text. Claude can return content as a list of blocks; this joins the text ones.

    Example: AIMessage(content=[{"type": "text", "text": "Hi"}]) -> "Hi"
    """
    if isinstance(message.content, str):
        return message.content
    return "".join(block.get("text", "") for block in message.content if isinstance(block, dict))


def tokens_used(message: BaseMessage) -> tuple[int, int]:
    """(input_tokens, output_tokens) from a model reply's usage_metadata; (0, 0) if it has none."""
    usage = getattr(message, "usage_metadata", None) or {}
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def recent(messages: list[BaseMessage], limit: int) -> list[BaseMessage]:
    """The last `limit` messages, trimmed so the window starts with a human message.

    Why trim: Claude's API expects a conversation to start with the user's turn. Cutting the history
    at an arbitrary point could start it with Simba's reply, so leading non-human messages are dropped.

    Example: [human "a", ai "b", human "c", ai "d", human "e"] with limit=4
             -> last 4 = [ai "b", human "c", ai "d", human "e"] -> [human "c", ai "d", human "e"]
    """
    window = list(messages[-limit:])
    while window and window[0].type != "human":
        window.pop(0)
    return window


def ms_since(start: float) -> int:
    """Whole milliseconds since `start`, a `time.perf_counter()` reading."""
    return round((time.perf_counter() - start) * 1000)


def emit_trace(stage: str, status: str, detail: str, start: float, tokens: tuple[int, int] = (0, 0)) -> dict:
    """Send one trace line to the browser and return it (returned so tests can check it too).

    Args:
        stage:  the node's name as shown in the panel: "guard", "intent", "reason", "generate", "refuse"
        status: "ok", "blocked" or "error"
        detail: one short readable line, e.g. 'safe · "weekend ideas for Lisbon"'
        start:  time.perf_counter() from when the node began, for the ms column
        tokens: (input, output) tokens if the node called the model

    The event's shape is fixed by docs/contracts.md § 6 (the frontend reads exactly these keys).
    """
    tokens_in, tokens_out = tokens
    event = {
        "stage": stage,
        "status": status,
        "detail": detail,
        "ms": ms_since(start),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost_usd": cost_usd(tokens_in, tokens_out),
    }
    get_stream_writer()(event)
    return event
