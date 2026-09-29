"""
hooks.py — the shape every check in simba/harness returns, and the runner that executes a list of
them at one hook point (#32, D22/D23).

Where it sits: `simba/nodes/hook_points.py` calls `run_hooks(point, hooks, text)` once per hook point
(`before_model`, `after_model`), with the hook list it reads from `settings.py`. This file knows
nothing about LangGraph or the graph's state — it only runs plain functions over a string and reports
what happened, the same separation `simba/guard.py` used to keep between deciding and doing.

Key idea: every hook — a regex check, the local classifier, an output check — is just a function
`str -> HookResult`. `run_hooks` treats them all the same way (off the event loop, in order, stop at
the first block), so a new hook point only ever needs a new list in `settings.py`, never a change here.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Literal

from simba.common import emit_trace

# So a hook's crash still leaves a full traceback somewhere findable (server logs), even though the
# policy below deliberately keeps it out of the trace panel and any user-facing text.
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookResult:
    """One hook's verdict on a piece of text. Replaces the old per-file `GuardResult`: every hook,
    input or output, now returns this same shape.

    action  "allow" (nothing to report), "flag" (worth a note, never stops the turn) or "block"
            (stop here — the rest of the hooks at this point never run)
    rule    None for "allow"; otherwise the hook's own name for what fired, e.g. "size",
            "ignore-instructions", or "<hook_name>-error" when the hook raised
    reason  one short, human-readable sentence (contracts.md's 80-character trace budget), e.g.
            "44 chars", "rules ok", "classifier 0.02" — `run_hooks` joins these into one trace line
    """

    action: Literal["allow", "flag", "block"]
    rule: str | None
    reason: str


# Anything that takes the text being checked and returns its verdict. `size_limit`, `injection_rules`
# (harness/guard.py), `classifier_hook(classifier)` (harness/classifier.py) and the output checks
# (harness/output_guard.py) all have this shape, so `settings.py` can list them interchangeably.
Hook = Callable[[str], HookResult]


async def run_hooks(point: str, hooks: list[Hook], text: str) -> list[HookResult]:
    """Run `hooks` against `text`, in order, and emit one trace line for `point` (D28/D29).

    Args:
        point: the hook point's name, used as the trace line's `stage` (e.g. "before_model") — the
               code name, not a separate display name (D29).
        hooks: the checks to run, in order (settings.py decides the order: cheapest first).
        text:  the text being checked — the newest human message for `before_model`, the newest
               reply for `after_model`.

    Steps:
      1. Run each hook off the event loop with `asyncio.to_thread`: one rule for every hook, cheap
         regex or the CPU-bound classifier alike, so the event loop other chats share never blocks.
      2. A hook that raises is treated as a block (fail closed, CLAUDE.md's security rule): rule
         `f"{hook.__name__}-error"`, and the real traceback is logged — never shown to the user or in
         the trace panel.
      3. Stop at the first block: hooks after it never run.
      4. Emit one trace line for the whole point (D28: one line per hook point, each hook's result
         inline). Status is "blocked" if any hook blocked, else "flagged" if any hook flagged, else
         "ok". Detail is `blocked · {rule}` for a block, else every hook's reason joined by " · "
         behind a "pass · " prefix, cut to 80 characters.

    Returns every `HookResult` produced (fewer than `len(hooks)` when a block stopped the run early).
    """
    results: list[HookResult] = []
    start = time.perf_counter()

    # 1-3.
    for hook in hooks:
        try:
            result = await asyncio.to_thread(hook, text)
        except Exception:
            logger.exception(f"{hook.__name__} raised; blocking the message instead of crashing")
            result = HookResult("block", f"{hook.__name__}-error", "hook raised an exception")
        results.append(result)
        if result.action == "block":
            break

    # 4.
    blocked = next((r for r in results if r.action == "block"), None)
    if blocked is not None:
        status, detail = "blocked", f"blocked · {blocked.rule}"
    else:
        status = "flagged" if any(r.action == "flag" for r in results) else "ok"
        detail = ("pass · " + " · ".join(r.reason for r in results))[:80]

    emit_trace(point, status, detail, start)
    return results
