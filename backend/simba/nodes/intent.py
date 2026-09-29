"""
simba/nodes/intent.py — the intent node: safety-checks the newest message and restates what the
user wants, in one line, before the reason/generate nodes ever see it.

Where it sits: guard -> intent -> reason -> generate (graph.py). The deterministic guard node has
already checked size and known injection patterns with plain regex; this node is a second,
model-based layer that catches what regex can't (paraphrased attacks, harmful requests dressed up
politely). It reads only the newest human message, never the rest of the conversation — a hostile
instruction planted earlier in the chat shouldn't get a free pass by riding along with a later,
unrelated message.

Key idea: delimiter breakout. The prompt below wraps the untrusted message in <user_message> tags
so the model can tell "data to classify" apart from "instructions to me" (docs/contracts.md § 7.4).
An attacker who writes their own "</user_message>" in their message could try to fake the end of
that wrapper and have the model treat whatever follows as a fresh instruction. So before wrapping,
any user_message tag already present in the text is neutralised with `common.neutralise_tag` — its
opening "<" is escaped to "&lt;" so it reads as plain text, not as a tag.

#8: when the local classifier flagged this message (`state["flag"]`, set in nodes/hook_points.py),
a short note is appended to the system prompt below so this node's judgement call can take that
extra signal into account. Only Simba's own words and the flag string (e.g. "classifier 0.97") are
added — never user text — so the note itself can't be hijacked by anything the user wrote.
"""

import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from simba.common import emit_trace, neutralise_tag, text_of, tokens_used
from simba.prompts import load
from simba.schemas import IntentCheck
from simba.state import ChatState

# Trace details are shown in a narrow panel column (docs/contracts.md § 6): keep them short.
MAX_DETAIL_CHARS = 80


def _last_human_text(messages: list) -> str:
    """The newest human message's text, or "" if there is none.

    Why: the intent node must check only the current turn, not the whole history (see file header).
    """
    for message in reversed(messages):
        if message.type == "human":
            return text_of(message)
    return ""


def make_node(model: BaseChatModel):
    """Build the intent node bound to `model` (docs/contracts.md § 7.4).

    Returns an async node function `intent(state) -> dict` that:
      1. Takes the newest human message's text and neutralises delimiter breakout attempts.
      2. Sends it, wrapped in <user_message> tags, as the only message — the intent.md instructions
         are the system message. No history: see file header. If `state["flag"]` is set (#8), a note
         naming the flag is appended to the system text (never to the user message itself).
      3. Asks the model for structured output (IntentCheck): a schema instead of free text, so the
         reply can only be {intent, verdict, reason} — see model.py's docstring for how that works.
      4. "safe" -> records the intent and a passing verdict. "injection"/"harmful" -> blocks with
         rule "intent-{verdict}".
      5. Fails closed: a missing or unparsable reply blocks the turn (rule "intent-error") rather
         than letting it through — this is a safety check, and CLAUDE.md requires failing closed.

    Why a factory: LangGraph nodes take only `state`, but this node needs a model. graph.py builds
    it once per model with `make_node(model)` (model.py: nodes never create models themselves).
    """

    async def intent(state: ChatState) -> dict:
        start = time.perf_counter()

        # 1. Only the newest message, and only after neutralising fake delimiters in it.
        text = neutralise_tag(_last_human_text(state["messages"]), "user_message")

        # 2. The wrapped message is the whole human turn; intent.md is the system prompt. #8: a flag
        #    from the guard's classifier adds a note to the system text, our own words plus only the
        #    flag string — never user text — so the model weighs it without it becoming an instruction.
        system_text = load("intent")
        if state["flag"] is not None:
            system_text += (
                "\n\nNote: a local classifier flagged this message as a possible prompt injection "
                f"({state['flag']}). It can be wrong; judge the message yourself, carefully."
            )
        prompt = [SystemMessage(system_text), HumanMessage(f"<user_message>\n{text}\n</user_message>")]

        # 3. Structured output: include_raw=True gives both the parsed IntentCheck (or None on a
        #    parsing failure) and the raw model reply, which carries the token counts for the trace.
        try:
            result = await model.with_structured_output(IntentCheck, include_raw=True).ainvoke(prompt)
        except Exception:
            # 5. The call itself blew up (e.g. a malformed reply the parser couldn't even wrap) — fail closed.
            emit_trace("intent", "error", "could not check the message", start)
            return {"verdict": {"status": "blocked", "rule": "intent-error", "reason": "could not check the message"}}

        parsed: IntentCheck | None = result["parsed"]
        tokens = tokens_used(result["raw"])

        if parsed is None:
            # 5. The reply didn't match the IntentCheck schema (e.g. an invalid verdict) — fail closed.
            emit_trace("intent", "error", "could not check the message", start, tokens)
            return {"verdict": {"status": "blocked", "rule": "intent-error", "reason": "could not check the message"}}

        if parsed.verdict == "safe":
            # 4. Safe: record the restated intent and let the turn continue.
            detail = f'safe · "{parsed.intent}"'[:MAX_DETAIL_CHARS]
            emit_trace("intent", "ok", detail, start, tokens)
            return {"intent": parsed.intent, "verdict": {"status": "pass", "rule": None, "reason": parsed.reason}}

        # 4. Unsafe ("injection" or "harmful"): block with a rule the refuse node can report.
        rule = f"intent-{parsed.verdict}"
        detail = f"{parsed.verdict} · {parsed.reason}"[:MAX_DETAIL_CHARS]
        emit_trace("intent", "blocked", detail, start, tokens)
        return {"verdict": {"status": "blocked", "rule": rule, "reason": parsed.reason}}

    return intent
