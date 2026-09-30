"""
evals/run_safety_eval.py — runs the safety eval (#58): every attack and every "sounds risky but is
fine" question in evals/safety_cases.yaml goes through Simba's real app, and safety_graders.py
scores what came back.

Where it sits: next to run_search_eval.py, and reuses its plumbing (one fresh app per case, the
rubric judge, trace files, resumable results). Only three things differ, all here:
- the search tool is a scripted fake (`ScriptedSearch`): an indirect-injection case gets its
  poisoned page back, every other case gets "no results". Free, repeatable, no Tavily.
- the graders: resisted / no_leak / caught_by (safety_graders.py) plus the same rubric judge.
- the summary: safe rate per group, attack success rate, over-refusal rate, and which layer
  caught each attack.

    cd backend
    uv run --group eval python -m evals.run_safety_eval --fake          # free dry run
    uv run --group eval python -m evals.run_safety_eval --cases d01,b04 # a few real cases
    uv run --group eval python -m evals.run_safety_eval                 # all 30

Results: .claude/hillclimb/safety/<variant>/ in the main checkout (see run_search_eval.results_root).
"""

import argparse
import asyncio
import json
import math
import os
import shutil
from collections import Counter
from datetime import date
from email.utils import format_datetime

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from evals.run_search_eval import (
    CASE_TIMEOUT_S,
    CONCURRENCY,
    REPO_DIR,
    judge_case,
    load_cases,
    results_root,
    run_case,
    time_now_utc,
    trace_turns,
    write_jsonl,
)
from evals.safety_graders import caught_by, grade_fixed_refusal, grade_no_leak, grade_resisted, grade_safe
from simba.api import BACKEND_DIR
from simba.harness.classifier import load_classifier
from simba.model import MODEL_ID, fake_model, make_model

CASES_FILE = REPO_DIR / "evals" / "safety_cases.yaml"
FLOW_DIR = results_root() / "safety"

# Headline first: `safe` is 1 only when every check that applies passed (safety_graders.grade_safe).
METRICS = [
    {"id": "safe", "label": "Safe", "kind": "binary"},
    {"id": "resisted", "label": "Resisted", "kind": "binary"},
    {"id": "no_leak", "label": "No leak", "kind": "binary"},
    {"id": "rubric_share", "label": "Rubric share", "kind": "float", "scale": 1},
]
PERF_FIELDS = [
    {"id": "cost_usd", "label": "Cost", "unit": "$"},
    {"id": "latency_s", "label": "Latency", "unit": "s"},
    {"id": "web_searches", "label": "Searches"},
]

# The URL the scripted search gives its one result: clearly fake, so a real link can't sneak in.
PAGE_URL = "https://news.example/story"


class ScriptedSearch:
    """The search tool for safety cases: returns the case's `search_page` as one result dated today,
    or no results at all when the case has none. Searching costs nothing and never touches the web,
    so an indirect-injection attack is exactly the same on every run."""

    misses = 0  # run_case reads this; nothing is ever "missed" in a scripted search

    def __init__(self, page: str | None):
        self.page = page

    async def ainvoke(self, params: dict[str, str]) -> dict:
        """Same shape as TavilySearch.ainvoke: params in, a Tavily-style result dict out."""
        if not self.page:
            return {"results": []}
        today = format_datetime(time_now_utc())
        return {"results": [{"title": "News", "url": PAGE_URL, "content": self.page, "published_date": today}]}


async def main(args: argparse.Namespace) -> None:
    """Run every case not yet in results.jsonl, grade it, save it, then print the summary.

    1. Check setup (a paid run needs ANTHROPIC_API_KEY and the real model).
    2. For each case (CONCURRENCY at a time, capped at CASE_TIMEOUT_S): run it through Simba with
       the scripted search, grade it in code, ask the judge, write the results row and trace.
    3. Print and save the summary (see `summarise`).
    """
    # 1.
    load_dotenv(BACKEND_DIR / ".env")
    if not args.fake:
        if not os.getenv("ANTHROPIC_API_KEY", "").strip():
            raise SystemExit("ANTHROPIC_API_KEY is not set in backend/.env")
        if os.getenv("SIMBA_FAKE_LLM") == "1":
            raise SystemExit("SIMBA_FAKE_LLM=1 would test the fake model; unset it or pass --fake")
    variant_dir = FLOW_DIR / args.variant
    if args.overwrite and variant_dir.exists():
        shutil.rmtree(variant_dir)
    (variant_dir / "traces").mkdir(parents=True, exist_ok=True)
    state_file = FLOW_DIR / "_state.json"
    if not state_file.exists():
        state_file.write_text(json.dumps({"metrics": METRICS, "perf_fields": PERF_FIELDS}, indent=2))

    results_file = variant_dir / "results.jsonl"
    done_ids = {json.loads(line)["prompt_id"] for line in results_file.read_text().splitlines()} if results_file.exists() else set()
    cases = [c for c in load_cases(args.cases, CASES_FILE) if c["id"] not in done_ids]
    today = date.today()
    real_model = None if args.fake else make_model()
    classifier = None if args.fake else load_classifier()
    judge = None if (args.fake or args.no_judge) else AsyncAnthropic()
    gate = asyncio.Semaphore(CONCURRENCY)
    print(f"{len(cases)} case(s) to run -> {variant_dir}  (skipping {len(done_ids)} done)")

    # 2.
    async def one(case: dict) -> None:
        async with gate:
            if args.fake:
                # Search only when the case has a page, so the dry run exercises that path too.
                wants = {"web_search": {"query": case["question"], "topic": "news", "time_range": "day"}}
                model = fake_model(structured=wants if case.get("search_page") else None)
            else:
                model = real_model
            try:
                outcome = await asyncio.wait_for(
                    run_case(case, model, ScriptedSearch(case.get("search_page")), classifier), CASE_TIMEOUT_S)
            except Exception as exc:  # timeouts included: logged, never scored
                write_jsonl(variant_dir / "errors.jsonl", {"prompt_id": case["id"], "failure": type(exc).__name__, "detail": str(exc)[:300]})
                print(f"  {case['id']}: ERROR {type(exc).__name__}")
                return
            served = outcome["served_model"]
            if not args.fake and served and not served.startswith(MODEL_ID):
                write_jsonl(variant_dir / "errors.jsonl", {"prompt_id": case["id"], "failure": "model_mismatch", "detail": served})
                print(f"  {case['id']}: ERROR served by {served}, expected {MODEL_ID}")
                return

            run = outcome["run"]
            layer = caught_by(outcome["lines"])
            grade = {"resisted": grade_resisted(case, run), "no_leak": grade_no_leak(run),
                     "rubric_share": None, "safe": None}
            extra: dict = {}
            fixed = grade_fixed_refusal(case, run)
            if fixed is not None:
                # The exact fixed refusal: graded in code, no judge call (safety_graders.grade_fixed_refusal).
                grade["safe"] = grade_safe(grade["resisted"], grade["no_leak"], fixed)
                extra["explanation"] = {"safe": f"{'PASS' if fixed else 'FAIL'}: the fixed refusal, graded in code"}
            elif judge is not None:
                verdict = await judge_case(judge, case, run, today)
                extra.update(judge_model=verdict["model"], judge_usage=verdict["usage"], judge_cost_usd=verdict["cost_usd"])
                if verdict["problem"]:
                    extra["judge_problem"] = verdict["problem"]
                else:
                    grade["rubric_share"] = verdict["share"]
                    grade["safe"] = grade_safe(grade["resisted"], grade["no_leak"], verdict["pass"])
                    extra["explanation"] = {"safe": "\n".join(verdict["reasons"].values())}
                extra["judge_raw"] = verdict.get("raw")

            (variant_dir / "traces" / f"{case['id']}_rep0.json").write_text(
                json.dumps(trace_turns(case, outcome, today), ensure_ascii=False, indent=1))
            row = {
                "prompt_id": case["id"], "prompt": case["question"], "rep": 0,
                "tags": [case["group"], "attack" if case["attack"] else "benign", f"caught: {layer}"],
                "status": "truncated" if outcome["stop_reason"] == "max_tokens" else "ok",
                "stop_reason": outcome["stop_reason"], "model": served or "fake",
                "grade": grade, "latency_s": outcome["latency_s"], "web_searches": len(run.tool_calls),
                "tool_calls": len(run.tool_calls), "usage": outcome["usage"], "cost_usd": outcome["cost_usd"],
                "meta": {"attack": case["attack"], "caught_by": layer, "queries": run.tool_calls,
                         "trace": outcome["lines"], "turn_error": outcome["error"], "date": today.isoformat(),
                         "judge_raw": extra.pop("judge_raw", None)},
                **extra,
            }
            write_jsonl(results_file, row)
            shown = " ".join(f"{k}={v if v is None else round(v, 2)}" for k, v in grade.items())
            print(f"  {case['id']}: {shown} caught_by={layer}")

    await asyncio.gather(*(one(c) for c in cases))

    # 3.
    rows = [json.loads(line) for line in results_file.read_text().splitlines()] if results_file.exists() else []
    summary = summarise(rows)
    (variant_dir / "summary.md").write_text(summary)
    print("\n" + summary)


def summarise(rows: list[dict]) -> str:
    """Markdown summary: each metric's average, the safe rate per group, the two headline failure
    rates, and which layer stopped each attack.

    attack success rate  attacks that were NOT safe — the number to push towards 0
    over-refusal rate    benign questions that were NOT safe (refused or answered badly) — also towards 0
    "±" is the rough noise band 1/sqrt(n), as in the search eval.
    """
    def rate(values: list[int]) -> str:
        return f"{sum(values) / len(values):.0%} ± {1 / math.sqrt(len(values)):.0%} ({len(values)})" if values else "–"

    lines = ["| Metric | Score (cases) |", "|---|---|"]
    for metric in METRICS:
        lines.append(f"| {metric['label']} | {rate([r['grade'][metric['id']] for r in rows if r['grade'].get(metric['id']) is not None])} |")

    lines += ["", "| Group | Safe (cases) |", "|---|---|"]
    for group in dict.fromkeys(r["tags"][0] for r in rows):
        lines.append(f"| {group} | {rate([r['grade']['safe'] for r in rows if r['tags'][0] == group and r['grade']['safe'] is not None])} |")

    attacks = [1 - r["grade"]["safe"] for r in rows if r["meta"]["attack"] and r["grade"]["safe"] is not None]
    benign = [1 - r["grade"]["safe"] for r in rows if not r["meta"]["attack"] and r["grade"]["safe"] is not None]
    layers = Counter(r["meta"]["caught_by"] for r in rows if r["meta"]["attack"])
    lines += [
        "",
        f"Attack success rate: {rate(attacks)} · over-refusal rate: {rate(benign)}",
        "Attacks caught by: " + ", ".join(f"{layer} {n}" for layer, n in layers.most_common()),
        f"Cost: Simba ${sum(r['cost_usd'] for r in rows):.4f} + judge ${sum(r.get('judge_cost_usd', 0) for r in rows):.4f} · "
        f"mean latency {sum(r['latency_s'] for r in rows) / max(len(rows), 1):.1f} s · cases {len(rows)} · "
        f"judge problems {sum(1 for r in rows if r.get('judge_problem'))}",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    """The command line (see the file header for examples)."""
    parser = argparse.ArgumentParser(description="Run Simba's safety eval (#58).")
    parser.add_argument("--variant", default="baseline", help='"baseline" or "v1", "v2", ... (report folder name)')
    parser.add_argument("--cases", help="comma-separated case ids, e.g. d01,b04 (default: all)")
    parser.add_argument("--no-judge", action="store_true", help="skip the rubric judge (code graders only)")
    parser.add_argument("--fake", action="store_true", help="fake model, no judge: free dry run")
    parser.add_argument("--overwrite", action="store_true", help="delete this variant's earlier results first")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
