"""
settings.py — the one place that lists which hooks run at each hook point, and in what order (#32,
D22/D26). `simba/nodes/hook_points.py` reads these lists; it never decides for itself which checks
exist.

Four hook points exist in the design (design book 0.3 § Hook points), one before and one after each
model or tool call: `before_model`/`after_model` and `before_tool`/`after_tool` (#17). The first
tool is read-only web search; its hooks are listed here so checks stay separate from the runner
and graph wiring.
"""

from simba.harness.classifier import InjectionClassifier, classifier_hook
from simba.harness.guard import injection_rules, size_limit
from simba.harness.hooks import Hook
from simba.harness.output_guard import no_internal_tags, no_prompt_leak, no_secrets
from simba.harness.tool_hooks import (
    allowlisted_tool_call,
    flag_instruction_like_tool_result,
    valid_web_search_query,
    within_web_search_budget,
)


def before_model_hooks(classifier: InjectionClassifier | None) -> list[Hook]:
    """The `before_model` hooks, cheapest first, so an expensive check never runs on a message a
    cheaper one already blocked (`harness/hooks.py`'s run_hooks stops at the first block).

    Args:
        classifier: the local prompt-injection classifier (#8), or None to turn that hook off —
                    `classifier_hook(None)` reports "classifier off" and never scores anything.

    Order: `size_limit` (a length check) -> `injection_rules` (regex over the text) ->
    `classifier_hook(classifier)` (a local model call, the most expensive of the three).
    """
    return [size_limit, injection_rules, classifier_hook(classifier)]


# The `after_model` hooks, in the order they run: a key-like string, then our own prompt delimiters,
# then a shared-wording check against the prompt files — cheapest regex checks before the one that
# reads and scans every prompt file. No classifier here; the output guard is code-only (§ 7.7).
AFTER_MODEL: list[Hook] = [no_secrets, no_internal_tags, no_prompt_leak]

# #16: the most one chat may spend on model calls, in US dollars, before new messages are refused
# (api.py checks it before running the graph). $0.50 is roughly 150 turns at today's haiku prices —
# far more than a normal chat needs, low enough that a runaway loop can't run up a surprise bill.
# The check sits before a turn, so the turn that crosses the line still finishes; the next is refused.
CHAT_BUDGET_USD = 0.50

# #17: only the read-only web_search tool is exposed; returned page text is untrusted.
BEFORE_TOOL: list[Hook] = [allowlisted_tool_call, valid_web_search_query, within_web_search_budget]
AFTER_TOOL: list[Hook] = [flag_instruction_like_tool_result]
