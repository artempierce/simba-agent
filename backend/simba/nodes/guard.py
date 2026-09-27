"""
nodes/guard.py — the graph's first node: wires the deterministic checks in simba/guard.py, and (#8)
the local injection classifier in simba/classifier.py, into LangGraph.

Where it sits: START → guard (contracts.md § 8). Every turn passes through here before intent or any
model call. `check_input()` does the regex/size deciding; this node reads the newest human message,
calls it, then (if a classifier was given) scores the message a second way, and turns both results
into a Verdict (simba/state.py) and a trace line the browser can show.

Policy (Sol, 2026-09-27, contracts.md § 7.2): the classifier only *flags*, it never blocks. A high
score doesn't change the verdict or the route — it only sets `state["flag"]`, which the intent node
(contracts.md § 7.4) reads and judges alongside the message itself. So this node has two jobs that
must stay separate: the regex/size check decides pass-or-blocked; the classifier only adds a note.
"""

import asyncio
import time

from langchain_core.messages import BaseMessage

from simba.classifier import THRESHOLD, InjectionClassifier
from simba.common import emit_trace, text_of
from simba.guard import check_input
from simba.state import ChatState


def _newest_human_text(messages: list[BaseMessage]) -> str:
    """The text of the newest human message in `messages`.

    Guard runs right after the user's turn is added and before any reply, so this is normally just
    the last message — but scanning from the end (instead of assuming index -1) keeps the node
    correct even if a future step ever changes what comes after the human message in state.
    """
    for message in reversed(messages):
        if message.type == "human":
            return text_of(message)
    return ""


def make_node(classifier: InjectionClassifier | None = None):
    """Build the guard node, optionally bound to a local injection classifier (#8).

    Args:
        classifier: scores a message's P(injection); None means "off" (the classifier step is
                    skipped, same behaviour as before #8). `api.py` passes the real one when its
                    model files are on disk; tests pass a tiny fake, or nothing.

    Returns an async node function `guard(state) -> dict` that:
      1. Finds the newest human message's text and runs `check_input()` (size, then injection —
         simba/guard.py). Blocked -> verdict "blocked", trace "blocked", the classifier never runs
         (a message regex already condemned isn't worth a model call).
      2. Passed -> verdict "pass". If a classifier was given, score the text *off the event loop*
         with `asyncio.to_thread` — the ONNX model call is a blocking, CPU-bound function, and
         running it directly inside this `async def` would freeze every other chat's turn until it
         finished. `asyncio.to_thread` runs it in a background thread and awaits the result instead.
      3. Score >= THRESHOLD -> `state["flag"]` is set to "classifier {score:.2f}", trace "flagged".
         Score < THRESHOLD -> no flag, trace "ok". The classifier raising is treated the same as a
         high score (fail toward caution, contracts.md's security rule) -> flag "classifier failed",
         trace "flagged" — never crash the turn, never block it either.
      4. No classifier at all -> trace "ok", detail ends "classifier off".

    Why a factory: graph.py needs one guard node per classifier (real, fake, or none), the same
    pattern as the LLM nodes' `make_node(model)`.
    """

    async def guard(state: ChatState) -> dict:
        start = time.perf_counter()

        # 1. Newest human message's raw text, and the regex/size check.
        text = _newest_human_text(state["messages"])
        result = check_input(text)

        if result.rule is not None:
            # Blocked by layer 1: the classifier never runs on a message we already refuse.
            verdict = {"status": "blocked", "rule": result.rule, "reason": result.reason}
            emit_trace("guard", "blocked", f"blocked · {result.rule}", start)
            return {"verdict": verdict}

        verdict = {"status": "pass", "rule": None, "reason": result.reason}

        # 2-4. Layer 2: the local classifier, only reached once layer 1 has passed.
        if classifier is None:
            emit_trace("guard", "ok", f"{result.reason} · classifier off", start)
            return {"verdict": verdict}

        try:
            # asyncio.to_thread runs a normal (blocking) function in a worker thread and awaits its
            # result, so the ONNX model's CPU work doesn't block the event loop other chats share.
            score = await asyncio.to_thread(classifier.score, text)
        except Exception:
            # Fail toward caution: a broken classifier is treated like a flag, never a silent "ok".
            emit_trace("guard", "flagged", f"{result.reason} · classifier failed ⚑", start)
            return {"verdict": verdict, "flag": "classifier failed"}

        if score >= THRESHOLD:
            flag = f"classifier {score:.2f}"
            emit_trace("guard", "flagged", f"{result.reason} · {flag} ⚑", start)
            return {"verdict": verdict, "flag": flag}

        emit_trace("guard", "ok", f"{result.reason} · classifier {score:.2f}", start)
        return {"verdict": verdict}

    return guard
