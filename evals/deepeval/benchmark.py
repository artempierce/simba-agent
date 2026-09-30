"""
benchmark.py — the general benchmark (#72): runs everyday tasks through Simba and scores them with
DeepEval metrics against the targets in targets.yaml.

What it measures, and why these metrics (one line each; the reasoning is in the README):
  correctness          GEval: are the reference answer's facts there, and none contradicted?
  answer_relevancy     does every part of the reply address the question (no padding, no drift)?
  simba_style          GEval: answer first, warm without gushing, plain words, honest
  tool_correctness     searched exactly when the case needs live information — checked in code
  knowledge_retention  multi-turn cases: does it keep what the user said earlier?
  ops                  cost per turn and p50 / p95 latency, from Simba's own `done` events
  consistency (pass^k) with --repeats k: a case counts only if it passes on every run

Where it sits: outside the app, against Simba's running HTTP API (simba_client.py). Results go to
the main checkout's .claude/hillclimb/benchmark/<variant>/.

    cd evals/deepeval
    uv run python benchmark.py                           # plan only, nothing called
    uv run python benchmark.py --cases k01,m01 --run     # a pilot, paid
    uv run python benchmark.py --variant v1 --repeats 3 --run

Key idea: each metric object keeps the state of the case it just scored, so a fresh set of metric
objects is made for every case (`metrics_for`) and scored directly with `a_measure` — nothing is
cached, uploaded or written anywhere but the results folder.
"""

import argparse
import asyncio
import json
import math
import statistics
from pathlib import Path

import yaml

import common  # noqa: F401  (sets the telemetry opt-outs before deepeval is imported)
from common import EVALS_DIR, JUDGE_MODEL, claude, load_targets, require_run_flag, results_root

CASES_FILE = EVALS_DIR / "benchmark_cases.yaml"

# How many cases run at the same time. Low, so Simba's server and the API rate limits stay comfortable.
CONCURRENCY = 3

# The Simba-style rubric, from system.md's "How you talk". Written as checkable steps, so two runs of
# the judge read the same thing.
STYLE_STEPS = [
    "Check the reply gives the answer first, in as few words as the question needs, without padding.",
    "Check it is warm and friendly without gushing; any humour fits the topic and is never at the user's expense.",
    "Check it uses plain words and explains any technical term in a short line.",
    "Check it is honest: it does not flatter, does not cheer on a clearly bad idea, and does not invent facts.",
]

CORRECTNESS_CRITERIA = (
    "Decide whether the actual output contains the key facts of the expected output and contradicts "
    "none of them. Extra correct detail is fine; a missing or wrong key fact is not. When the expected "
    "output describes a behaviour (for example 'a short question asking ...'), judge whether the "
    "actual output does that."
)


def load_cases(only: str | None) -> list[dict]:
    """All benchmark cases, or the comma-separated ids in `only`."""
    cases = yaml.safe_load(CASES_FILE.read_text())
    if only:
        wanted = set(only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
        if missing := wanted - {c["id"] for c in cases}:
            raise SystemExit(f"unknown case ids: {', '.join(sorted(missing))}")
    return cases


def metric_names(case: dict) -> list[str]:
    """Which judged metrics apply to a case (tool_correctness is code, always applied)."""
    names = ["answer_relevancy", "simba_style"]
    if case.get("expected"):
        names.insert(0, "correctness")
    if case.get("remember"):
        names.append("knowledge_retention")
    return names


def build_plan(cases: list[dict], repeats: int) -> str:
    """What would run, without calling anything: turns, metrics, and a rough call count.

    Rough judge calls per metric: correctness and simba_style (GEval) ~2, answer_relevancy ~3,
    knowledge_retention ~1 per turn.
    """
    turns = sum(len(c["turns"]) for c in cases) * repeats
    judge = sum(
        {"correctness": 2, "simba_style": 2, "answer_relevancy": 3}.get(m, 0) + (len(c["turns"]) if m == "knowledge_retention" else 0)
        for c in cases for m in metric_names(c)
    ) * repeats
    groups: dict[str, int] = {}
    for c in cases:
        groups[c["group"]] = groups.get(c["group"], 0) + 1
    return "\n".join([
        f"Benchmark plan · judge {JUDGE_MODEL} · {len(cases)} cases × {repeats} repeat(s)",
        "  groups: " + ", ".join(f"{g} {n}" for g, n in groups.items()),
        f"  Simba turns: {turns} · judge calls: about {judge}",
    ])


def metrics_for(case: dict, judge) -> dict:
    """Fresh DeepEval metric objects for one case, all judged by Claude, thresholds from targets.yaml."""
    from deepeval.metrics import AnswerRelevancyMetric, GEval, KnowledgeRetentionMetric
    from deepeval.test_case import SingleTurnParams as P

    t = load_targets()["benchmark"]
    made = {
        "correctness": lambda: GEval(name="Correctness", criteria=CORRECTNESS_CRITERIA, model=judge,
                                     evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT, P.EXPECTED_OUTPUT],
                                     threshold=t["correctness"]["threshold"]),
        "answer_relevancy": lambda: AnswerRelevancyMetric(model=judge, threshold=t["answer_relevancy"]["threshold"]),
        "simba_style": lambda: GEval(name="Simba style", evaluation_steps=STYLE_STEPS, model=judge,
                                     evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT], threshold=t["simba_style"]["threshold"]),
        "knowledge_retention": lambda: KnowledgeRetentionMetric(model=judge, threshold=t["knowledge_retention"]["threshold"]),
    }
    return {name: made[name]() for name in metric_names(case)}


async def run_case(http, case: dict, judge) -> dict:
    """One run of one case: send its turns in one new chat, then score the last reply.

    1. Send every turn, continuing the same Simba chat, and keep each reply.
    2. Tool correctness, in code: did it search exactly when the case says it should?
    3. Build DeepEval test cases — the last turn as an LLMTestCase; the whole chat as a
       ConversationalTestCase for knowledge retention — and score each metric.
    """
    from deepeval.test_case import ConversationalTestCase, LLMTestCase, Turn

    from simba_client import ask

    # 1.
    chat_id, replies = None, []
    for message in case["turns"]:
        turn = await ask(http, message, chat_id)
        chat_id = turn.chat_id
        replies.append(turn)
    last = replies[-1]

    # 2.
    scores = {"tool_correctness": float(any(r.searched for r in replies) == case["needs_search"])}
    reasons, judge_cost = {}, 0.0

    # 3.
    single = LLMTestCase(input=case["turns"][-1], actual_output=last.answer or f"[no reply: {last.error}]",
                         expected_output=case.get("expected"))
    conversation = ConversationalTestCase(turns=[
        turn for message, reply in zip(case["turns"], replies)
        for turn in (Turn(role="user", content=message), Turn(role="assistant", content=reply.answer or "[no reply]"))
    ])
    for name, metric in metrics_for(case, judge).items():
        await metric.a_measure(conversation if name == "knowledge_retention" else single)
        scores[name], reasons[name] = metric.score, metric.reason
        judge_cost += metric.evaluation_cost or 0.0
    return {
        "scores": scores, "reasons": reasons, "answer": last.answer, "blocked_by": last.blocked_by,
        "cost_usd": sum(r.cost_usd for r in replies), "judge_cost_usd": judge_cost,
        "latencies_s": [r.seconds for r in replies], "turns": len(replies),
    }


def passed(name: str, score: float | None, targets: dict) -> bool | None:
    """Did one metric score reach its threshold? None when it doesn't apply."""
    if score is None:
        return None
    return score >= targets["benchmark"][name]["threshold"]


def summarise(rows: list[dict], repeats: int) -> str:
    """Markdown summary against the targets: pass rate per metric, pass^k, per group, ops.

    "±" is the rough noise band 1/sqrt(n): a difference inside it between two variants isn't real yet.
    """
    targets = load_targets()
    t = targets["benchmark"]
    names = ["correctness", "answer_relevancy", "simba_style", "tool_correctness", "knowledge_retention"]
    lines = ["| Metric | Pass rate | Mean score | Target | Cases |", "|---|---|---|---|---|"]
    for name in names:
        oks = [passed(name, r["scores"].get(name), targets) for r in rows]
        oks = [o for o in oks if o is not None]
        if not oks:
            continue
        rate = sum(oks) / len(oks)
        mean = statistics.mean(r["scores"][name] for r in rows if r["scores"].get(name) is not None)
        mark = "✓" if rate >= t[name]["pass_rate"] else "✗"
        lines.append(f"| {name} | {rate:.0%} ± {1 / math.sqrt(len(oks)):.0%} | {mean:.2f} | {mark} ≥ {t[name]['pass_rate']:.0%} | {len(oks)} |")

    # A case passes a run when every metric that applies passed; pass^k needs all k runs.
    def run_ok(row: dict) -> bool:
        return all(passed(n, s, targets) is not False for n, s in row["scores"].items())

    by_case: dict[str, list[bool]] = {}
    for r in rows:
        by_case.setdefault(r["id"], []).append(run_ok(r))
    all_pass = sum(all(v) for v in by_case.values()) / max(len(by_case), 1)
    lines += ["", f"Cases passing every metric: {all_pass:.0%}" + (
        f" on all {repeats} runs (pass^{repeats}; target ≥ {t['consistency_pass_k']['pass_rate']:.0%})" if repeats > 1 else "")]

    lines += ["", "| Group | Cases passing every metric |", "|---|---|"]
    for group in dict.fromkeys(r["group"] for r in rows):
        mine = [run_ok(r) for r in rows if r["group"] == group]
        lines.append(f"| {group} | {sum(mine)}/{len(mine)} |")

    turns = sum(r["turns"] for r in rows)
    latencies = sorted(s for r in rows for s in r["latencies_s"])
    p95 = latencies[min(len(latencies) - 1, math.ceil(0.95 * len(latencies)) - 1)] if latencies else 0.0
    cost_per_turn = sum(r["cost_usd"] for r in rows) / max(turns, 1)
    ops = t["ops"]
    lines += [
        "",
        f"Cost per turn ${cost_per_turn:.4f} ({'✓' if cost_per_turn <= ops['cost_per_turn_usd'] else '✗'} ≤ ${ops['cost_per_turn_usd']}) · "
        f"latency p50 {statistics.median(latencies) if latencies else 0:.1f} s, p95 {p95:.1f} s "
        f"({'✓' if p95 <= ops['latency_p95_s'] else '✗'} ≤ {ops['latency_p95_s']} s)",
        f"Total cost: Simba ${sum(r['cost_usd'] for r in rows):.4f} + judge ${sum(r['judge_cost_usd'] for r in rows):.4f} · runs {len(rows)}",
    ]
    return "\n".join(lines) + "\n"


async def main(args: argparse.Namespace) -> None:
    """Plan; with --run, run every case (× --repeats), score it, save rows as they finish, summarise."""
    cases = load_cases(args.cases)
    require_run_flag(args.run, build_plan(cases, args.repeats))

    import httpx

    from simba_client import server_info

    out: Path = results_root() / "benchmark" / args.variant
    out.mkdir(parents=True, exist_ok=True)
    rows_file = out / "results.jsonl"
    if args.overwrite and rows_file.exists():
        rows_file.unlink()
    judge = claude(JUDGE_MODEL)
    gate = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as http:
        info = await server_info(http)
        if info["model"] == "fake":
            raise SystemExit("Simba is running the fake model; start it with a real one to benchmark it.")

        async def one(case: dict, rep: int) -> None:
            async with gate:
                try:
                    result = await run_case(http, case, judge)
                except Exception as exc:  # recorded, never scored as a fail
                    with (out / "errors.jsonl").open("a") as f:
                        f.write(json.dumps({"id": case["id"], "rep": rep, "error": f"{type(exc).__name__}: {exc}"[:300]}) + "\n")
                    print(f"  {case['id']}#{rep}: ERROR {type(exc).__name__}")
                    return
                row = {"id": case["id"], "group": case["group"], "rep": rep, "model": info["model"], **result}
                with rows_file.open("a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                shown = " ".join(f"{k}={v:.2f}" for k, v in result["scores"].items() if v is not None)
                print(f"  {case['id']}#{rep}: {shown}")

        await asyncio.gather(*(one(c, rep) for c in cases for rep in range(args.repeats)))

    rows = [json.loads(line) for line in rows_file.read_text().splitlines()] if rows_file.exists() else []
    summary = summarise(rows, args.repeats)
    (out / "summary.md").write_text(summary)
    print("\n" + summary + f"\nSaved to {out}")


def parse_args() -> argparse.Namespace:
    """The command line (see the file header for examples)."""
    parser = argparse.ArgumentParser(description="Benchmark Simba with DeepEval (#72).")
    parser.add_argument("--cases", help="comma-separated case ids, e.g. k01,m01 (default: all)")
    parser.add_argument("--variant", default="baseline", help='results folder: "baseline", "v1", ...')
    parser.add_argument("--repeats", type=int, default=1, help="runs per case; with k > 1 the summary shows pass^k")
    parser.add_argument("--overwrite", action="store_true", help="start this variant's results from scratch")
    parser.add_argument("--run", action="store_true", help="actually run it (costs money); without it, only the plan")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
