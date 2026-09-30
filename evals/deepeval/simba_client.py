"""
simba_client.py — talks to a running Simba over its HTTP API, the way the browser does (#72, #73).

Where it sits: the benchmark (benchmark.py) and the red teaming run (redteam.py) are a separate
project from the backend — DeepEval's pinned dependencies clash with the backend's — so they can't
import Simba's code. They test it from the outside instead: POST /api/chat, read the SSE stream.
That is also the honest way to test it: exactly what a user (or an attacker) can reach.

Key idea: one call = one turn. `ask` sends a message (to a new chat, or to an existing one to
continue it) and returns everything the graders need: the answer the user saw, the chat id, the
trace lines (which steps ran, which guardrail blocked), tokens, cost and time.
"""

import json
import os
import time
from dataclasses import dataclass, field

import httpx

# Where Simba runs. The owner's dev server by default; override with SIMBA_URL for a scratch server.
SIMBA_URL = os.getenv("SIMBA_URL", "http://127.0.0.1:8000")

# One turn can search the web up to three times; give it room before calling it a failure.
TURN_TIMEOUT_S = 180


@dataclass
class Turn:
    """What one POST /api/chat produced.

    answer     the text the user saw (tokens joined, or the output guard's replacement)
    chat_id    the chat this turn belongs to; pass it back to continue the conversation
    trace      the trace lines, e.g. {"stage": "agent", "status": "ok", "detail": "..."}
    error      the stream's `error` message, if the turn failed
    cost_usd, input_tokens, output_tokens, seconds   from the `done` event and the clock
    """

    answer: str
    chat_id: str
    trace: list[dict] = field(default_factory=list)
    error: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    @property
    def searched(self) -> bool:
        """True when the turn ran at least one web search (a `web_search` trace line)."""
        return any(line.get("stage") == "web_search" for line in self.trace)

    @property
    def blocked_by(self) -> str:
        """Which guardrail blocked the turn, if any: before_model / report_unsafe / after_model / budget / none."""
        for line in self.trace:
            if line.get("status") == "blocked":
                return "report_unsafe" if line.get("stage") == "agent" else line.get("stage", "?")
        return "none"


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Split an SSE body into [(event, data), ...] (docs/contracts.md § 9).

    Example: "event: token\\ndata: {\\"text\\": \\"Hi\\"}\\n\\n" -> [("token", {"text": "Hi"})]
    """
    events = []
    for block in text.replace("\r\n", "\n").strip("\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields and "data" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def turn_from_events(events: list[tuple[str, dict]], seconds: float) -> Turn:
    """Build a Turn from one response's SSE events (kept separate from the HTTP call so it's testable)."""
    answer = "".join(d["text"] for e, d in events if e == "token")
    answer = next((d["text"] for e, d in events if e == "replace"), answer)
    done = next((d for e, d in events if e == "done"), {})
    return Turn(
        answer=answer,
        chat_id=next((d["chat_id"] for e, d in events if e == "start"), ""),
        trace=[d for e, d in events if e == "trace"],
        error=next((d["message"] for e, d in events if e == "error"), None),
        cost_usd=done.get("cost_usd", 0.0),
        input_tokens=done.get("input_tokens", 0),
        output_tokens=done.get("output_tokens", 0),
        seconds=round(seconds, 2),
    )


async def ask(client: httpx.AsyncClient, message: str, chat_id: str | None = None) -> Turn:
    """Send one message to Simba and wait for the whole streamed reply.

    Args:
        client:  a shared httpx.AsyncClient (one per run, so connections are reused)
        message: what the user types
        chat_id: None starts a new chat; an id continues that chat (Simba keeps its history)
    """
    started = time.perf_counter()
    response = await client.post(f"{SIMBA_URL}/api/chat", json={"message": message, "chat_id": chat_id},
                                 timeout=TURN_TIMEOUT_S)
    response.raise_for_status()
    return turn_from_events(parse_sse(response.text), time.perf_counter() - started)


async def server_info(client: httpx.AsyncClient) -> dict:
    """GET /api/info (#57): which model the server runs and whether search is on. Checked before a
    paid run, so a server on the fake model can't produce a meaningless benchmark."""
    response = await client.get(f"{SIMBA_URL}/api/info", timeout=10)
    response.raise_for_status()
    return response.json()
