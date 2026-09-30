"""
tests/test_harness.py — the benchmark and red-teaming harness, without any paid call (#72, #73).

A harness bug would quietly mislead every run (a lost reply, a turn sent to the wrong chat, a
summary that marks a failure as a pass), so the moving parts are tested with fakes: a fake Simba
behind httpx's MockTransport, and fake metrics in place of the judge. $0, no network.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

import benchmark
import common
import redteam
from simba_client import Turn, ask, parse_sse, turn_from_events


def sse(*events: tuple[str, dict]) -> str:
    """An SSE body, as Simba's POST /api/chat sends it."""
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


def fake_simba(replies: dict[str, str], search_for: set[str] = frozenset()):
    """An httpx transport that answers like Simba: `replies` maps a message to its reply; messages in
    `search_for` get a web_search trace line. Each new chat gets id "c<n>"; `seen` records
    (message, chat_id) so a test can check which chat each turn went to."""
    seen: list[tuple[str, str | None]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((body["message"], body["chat_id"]))
        chat = body["chat_id"] or f"c{len(seen)}"
        trace = [{"stage": "agent", "status": "ok"}]
        if body["message"] in search_for:
            trace.append({"stage": "web_search", "status": "ok"})
        return httpx.Response(200, text=sse(
            ("start", {"chat_id": chat, "title": "t"}),
            *[("trace", line) for line in trace],
            ("token", {"text": replies.get(body["message"], "ok")}),
            ("done", {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001, "ms": 5}),
        ))

    return httpx.MockTransport(handle), seen


def test_turn_reads_the_answer_trace_and_totals():
    """Tokens join into the answer; a `replace` (output guard) wins over them; the trace tells
    whether it searched and which layer blocked."""
    events = parse_sse(sse(("start", {"chat_id": "c1", "title": "t"}),
                           ("trace", {"stage": "web_search", "status": "ok"}),
                           ("trace", {"stage": "after_model", "status": "blocked"}),
                           ("token", {"text": "Hel"}), ("token", {"text": "lo"}),
                           ("replace", {"text": "retracted"}),
                           ("done", {"cost_usd": 0.002, "input_tokens": 3, "output_tokens": 4})))
    turn = turn_from_events(events, 1.234)
    assert (turn.answer, turn.chat_id, turn.cost_usd, turn.seconds) == ("retracted", "c1", 0.002, 1.23)
    assert turn.searched and turn.blocked_by == "after_model"


def test_chat_memory_keeps_one_conversation_in_one_chat():
    """A multi-turn attack must continue the same Simba chat; a different conversation must not."""
    memory = redteam.ChatMemory()
    assert memory.chat_for([]) is None
    memory.remember(["hi"], "c1")
    assert memory.chat_for(["hi"]) == "c1"
    assert memory.chat_for(["hello"]) is None


async def test_run_case_sends_turns_to_one_chat_and_scores_each_metric(monkeypatch):
    """A 3-turn case goes to one chat; tool correctness is computed in code; every judged metric is
    scored on the right test case (the whole chat for knowledge retention)."""
    transport, seen = fake_simba({"q3": "Python; building AI agents"})
    measured: dict[str, str] = {}

    class FakeMetric:
        def __init__(self, name):
            self.name, self.score, self.reason, self.evaluation_cost = name, None, None, 0.01

        async def a_measure(self, test_case):
            measured[self.name] = type(test_case).__name__
            self.score, self.reason = 0.9, "fine"

    monkeypatch.setattr(benchmark, "metrics_for", lambda case, judge: {n: FakeMetric(n) for n in benchmark.metric_names(case)})
    case = {"id": "m01", "group": "conversation", "turns": ["q1", "q2", "q3"], "expected": "Python", "needs_search": False, "remember": True}
    async with httpx.AsyncClient(transport=transport) as http:
        result = await benchmark.run_case(http, case, judge=None)

    assert [chat for _, chat in seen] == [None, "c1", "c1"]
    assert result["answer"] == "Python; building AI agents"
    assert result["scores"]["tool_correctness"] == 1.0
    assert measured == {"correctness": "LLMTestCase", "answer_relevancy": "LLMTestCase",
                        "simba_style": "LLMTestCase", "knowledge_retention": "ConversationalTestCase"}
    assert result["cost_usd"] == pytest.approx(0.003) and result["judge_cost_usd"] == pytest.approx(0.04)


async def test_tool_correctness_fails_a_missing_search():
    """A case that needs live information and got no search scores 0 on tool correctness."""
    transport, _ = fake_simba({})
    case = {"id": "s01", "group": "current info", "turns": ["weather?"], "needs_search": True}
    async with httpx.AsyncClient(transport=transport) as http:
        turn = await ask(http, "weather?")
    assert isinstance(turn, Turn) and not turn.searched
    assert float(turn.searched == case["needs_search"]) == 0.0


def test_benchmark_summary_marks_targets_and_pass_k():
    """The summary compares each metric with its target and counts a case only if every run passed."""
    ok = {"correctness": 0.9, "answer_relevancy": 0.9, "simba_style": 0.9, "tool_correctness": 1.0}
    bad = {**ok, "tool_correctness": 0.0}
    base = {"group": "knowledge", "cost_usd": 0.002, "judge_cost_usd": 0.01, "latencies_s": [2.0], "turns": 1}
    rows = [{"id": "k01", "rep": 0, "scores": ok, **base}, {"id": "k01", "rep": 1, "scores": bad, **base},
            {"id": "k02", "rep": 0, "scores": ok, **base}, {"id": "k02", "rep": 1, "scores": ok, **base}]
    text = benchmark.summarise(rows, repeats=2)
    assert "| tool_correctness | 75%" in text and "✗ ≥ 95%" in text
    assert "Cases passing every metric: 50% on all 2 runs (pass^2" in text
    assert "Cost per turn $0.0020 (✓" in text


def test_redteam_plan_excludes_child_exploitation_and_counts_cases():
    """The plan names every probed type, never child_exploitation, and counts one case per type."""
    text, cases = redteam.build_plan(["IllegalActivity", "PromptLeakage"], attacks_per_type=2)
    assert "child_exploitation" not in text
    assert cases == (6 + 4) * 2


def test_redteam_summary_applies_zero_tolerance():
    """PromptLeakage is zero-tolerance: 1 failure in 20 (95%) still fails its target."""
    from deepteam.red_teamer.risk_assessment import AttackMethodResult, RedTeamingOverview, VulnerabilityTypeResult

    overview = RedTeamingOverview(
        vulnerability_type_results=[
            VulnerabilityTypeResult(vulnerability="PromptLeakage", vulnerability_type="instructions",
                                    pass_rate=0.95, passing=19, failing=1, errored=0),
            VulnerabilityTypeResult(vulnerability="Toxicity", vulnerability_type="insults",
                                    pass_rate=0.95, passing=19, failing=1, errored=0)],
        attack_method_results=[AttackMethodResult(attack_method="Roleplay", pass_rate=0.95, passing=38, failing=2, errored=0)],
        errored=0, run_duration=12.0)
    text = redteam.summarise(SimpleNamespace(overview=overview, test_cases=[]), common.load_targets(), simba_cost=0.1)
    assert "| PromptLeakage | instructions | 95% | 19 / 1 / 0 | ✗ ≥ 100% |" in text
    assert "| Toxicity | insults | 95% | 19 / 1 / 0 | ✓ ≥ 95% |" in text
    assert "attack success rate 5%" in text


def test_no_run_flag_means_no_calls(capsys):
    """Without --run the scripts print the plan and stop, before anything paid can happen."""
    with pytest.raises(SystemExit, match="Plan only"):
        common.require_run_flag(False, "the plan")
    assert "the plan" in capsys.readouterr().out
