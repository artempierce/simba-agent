"""
settings.py — the one place that lists which hooks run at each hook point, and in what order (#32,
D22/D26). `simba/nodes/hook_points.py` reads these lists; it never decides for itself which checks
exist.

Four hook points exist in the design (design book 0.3 § Hook points), one before and one after each
of the two kinds of model call the agent will eventually make: `before_model`/`after_model` (this
ticket) and `before_tool`/`after_tool` (#17, once Simba has tools). The two tool lists are empty for
now — `nodes/hook_points.py` doesn't even wire a node for them yet — so a future ticket can add tool
hooks by filling these lists, never by touching the runner or the graph.
"""

from simba.harness.classifier import InjectionClassifier, classifier_hook
from simba.harness.guard import injection_rules, size_limit
from simba.harness.hooks import Hook
from simba.harness.output_guard import no_internal_tags, no_prompt_leak, no_secrets


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

# #17: filled in when Simba gets its first tool.
BEFORE_TOOL: list[Hook] = []
AFTER_TOOL: list[Hook] = []
