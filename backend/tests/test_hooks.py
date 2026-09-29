"""
tests/test_hooks.py — simba/harness/hooks.py's runner: order, the stop-at-first-block rule, flag
collection, a raising hook's fail-closed block, and the one trace line `run_hooks` emits per point
(contracts.md § 6, D28/D29). No graph, no model — plain fake hooks stand in for the real checks.
"""

from simba.harness.hooks import HookResult, run_hooks
from tests.node_harness import run_node


def make_hook(name: str, calls: list[str] | None = None, action: str = "allow", reason: str | None = None):
    """A tiny fake hook named `name` that records itself into `calls` (if given) and returns a fixed
    `HookResult`. `hook.__name__` is set to `name` so run_hooks's `f"{hook.__name__}-error"` naming
    can be tested."""

    def hook(text: str) -> HookResult:
        if calls is not None:
            calls.append(name)
        return HookResult(action, None if action == "allow" else name, reason or f"{name} ok")

    hook.__name__ = name
    return hook


def make_broken_hook(name: str):
    """A fake hook that always raises — proves run_hooks fails closed instead of crashing the turn."""

    def hook(text: str) -> HookResult:
        raise RuntimeError("boom")

    hook.__name__ = name
    return hook


async def call_run_hooks(point: str, hooks: list, text: str):
    """Run `run_hooks` inside a one-node graph (like tests/node_harness.run_node) so its
    `emit_trace` call has the stream-writer context it needs, and return (results, traces)."""

    async def node(state):
        nonlocal results
        results = await run_hooks(point, hooks, text)
        return {}

    results: list[HookResult] = []
    _, traces = await run_node(node, {})
    return results, traces


async def test_hooks_run_in_the_order_given():
    """Order matters (settings.py lists cheapest first): hooks must run in list order, not be
    reordered or run concurrently."""
    calls: list[str] = []
    hooks = [make_hook("first", calls), make_hook("second", calls), make_hook("third", calls)]

    results, _ = await call_run_hooks("before_model", hooks, "hi")

    assert calls == ["first", "second", "third"]
    assert [r.action for r in results] == ["allow", "allow", "allow"]


async def test_a_hook_after_a_block_is_never_called():
    """The whole point of stopping early: a hook that blocks must prevent every later hook in the
    list from running at all, not just from mattering."""
    calls: list[str] = []
    blocker = make_hook("blocker", calls, action="block")
    spy = make_hook("spy", calls)

    results, traces = await call_run_hooks("before_model", [blocker, spy], "attack")

    assert calls == ["blocker"]  # spy never ran
    assert len(results) == 1
    assert traces[0]["status"] == "blocked"
    assert traces[0]["detail"] == "blocked · blocker"


async def test_flags_are_collected_and_reported():
    """Two hooks that both flag (never block) must both show up in the results and in the trace
    line's joined detail, with the overall status "flagged"."""
    hooks = [make_hook("flag_a", action="flag", reason="a flagged"), make_hook("flag_b", action="flag", reason="b flagged")]

    results, traces = await call_run_hooks("before_model", hooks, "hi")

    assert [r.action for r in results] == ["flag", "flag"]
    assert traces[0]["status"] == "flagged"
    assert traces[0]["detail"] == "pass · a flagged · b flagged"


async def test_a_raising_hook_blocks_with_its_own_name_error():
    """A hook that raises must never crash the turn or be read as "trusted": it's treated as a block
    named "<hook name>-error" (fail closed), and the real exception goes to the logger, not the
    trace panel or the user."""
    broken = make_broken_hook("classifier_hook")

    results, traces = await call_run_hooks("before_model", [broken], "hi")

    assert results == [HookResult("block", "classifier_hook-error", "hook raised an exception")]
    assert traces[0]["status"] == "blocked"
    assert traces[0]["detail"] == "blocked · classifier_hook-error"


async def test_all_pass_reports_ok_with_every_reason_joined():
    """No block, no flag: status "ok", and the trace detail joins every hook's short reason behind a
    "pass · " prefix — the shape nodes/hook_points.py's callers (and the trace panel) depend on."""
    hooks = [make_hook("size", reason="44 chars"), make_hook("rules", reason="rules ok")]

    results, traces = await call_run_hooks("before_model", hooks, "hi")

    assert [r.action for r in results] == ["allow", "allow"]
    assert traces[0]["status"] == "ok"
    assert traces[0]["detail"] == "pass · 44 chars · rules ok"


async def test_trace_stage_is_the_hook_points_own_name():
    """The trace line's `stage` is exactly the `point` argument (D29: code names, not a display
    name) — proves `after_model` traces show up under that name too, not hard-coded to
    "before_model"."""
    _, traces = await call_run_hooks("after_model", [make_hook("no_secrets", reason="3 checks")], "reply text")

    assert traces[0]["stage"] == "after_model"
