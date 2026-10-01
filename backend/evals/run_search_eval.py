"""
evals/run_search_eval.py — runs the web-search eval (#54): every question in evals/search_cases.yaml
goes through Simba's real app, and graders.py scores what came back.

Where it sits: outside the app and outside CI (a real run costs money). The owner runs it by hand:

    cd backend
    uv run --group eval python -m evals.run_search_eval                        # plan only, nothing called
    uv run --group eval python -m evals.run_search_eval --fake                 # free dry run
    uv run --group eval python -m evals.run_search_eval --cases t01,n04 --run  # pilot (paid)
    uv run --group eval python -m evals.run_search_eval --variant v1 --search replay --run

Key ideas:
- Real entry point: each case is one POST /api/chat on a fresh `create_app(...)` app, exactly like
  the browser, so hooks, the classifier, the tool loop and the output guard all run. Afterwards the
  runner reads the chat's saved state to see which searches ran and what they returned.
- Record / replay: the web changes by the hour, so comparing two prompts on two days' news isn't
  fair. `--search record` saves every Tavily answer under fixtures/; `--search replay` serves those
  saved answers again (a query not seen before is searched live and added, and counted as a miss).
- Results land in .claude/hillclimb/search/<variant>/ of the MAIN checkout (git-ignored), even when
  the runner runs from a git worktree: a worktree is deleted after its PR, and paid results with it
  (that happened once — see `results_root`). Files: results.jsonl (one row per
  case, written as each finishes, so a crash keeps the finished ones and a rerun skips them),
  traces/<case>_rep0.json (the whole exchange), errors.jsonl (cases that failed to run at all).
  The layout is the one the claude-api skill's eval report builder reads.
"""

import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from datetime import date
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import yaml
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models import BaseChatModel

from evals.graders import (
    JUDGE_SYSTEM,
    CaseRun,
    RubricGrade,
    grade_decision,
    grade_freshness,
    grade_grounding,
    grade_query,
    judge_prompt,
    rubric_scores,
)
from simba.api import BACKEND_DIR, create_app
from simba.common import text_of
from simba.harness.classifier import load_classifier
from simba.model import MODEL_ID, cost_usd, fake_model, make_model
from simba.nodes.agent import today_text
from simba.prompts import load
from simba.tools.web_search import make_tavily_client, make_web_search_tool

REPO_DIR = BACKEND_DIR.parent
CASES_FILE = REPO_DIR / "evals" / "search_cases.yaml"


def results_root() -> Path:
    """Where eval results live: `.claude/hillclimb/` in the main checkout, never in a worktree.

    Why: results are git-ignored, so deleting a worktree after its PR deletes them for good — the
    first search baseline (and its saved Tavily answers) was lost that way. `git rev-parse
    --git-common-dir` names the main checkout's `.git` folder from inside any worktree; its parent
    is the main checkout. Outside git (e.g. a copied folder) it falls back to this repo.
    """
    found = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           cwd=REPO_DIR, capture_output=True, text=True)
    main_checkout = Path(found.stdout.strip()).parent if found.returncode == 0 else REPO_DIR
    return main_checkout / ".claude" / "hillclimb"


FLOW_DIR = results_root() / "search"
FIXTURES_DIR = FLOW_DIR / "fixtures"

# The judge: a different, stronger model than the one under test, so it doesn't grade its own kind
# of mistakes kindly (owner's choice, #54 Q2). Prices are its US dollars per million tokens.
JUDGE_MODEL = "claude-opus-5-5"
JUDGE_PRICE_PER_MTOK = (4.00, 20.00)
JUDGE_MAX_TOKENS = 8_000  # includes the judge's thinking; its JSON verdict itself is short

# How many cases run at the same time. Low enough to stay well under the API's rate limits.
CONCURRENCY = 4

# A case that takes longer than this is stopped and logged as a timeout, never scored as a fail.
CASE_TIMEOUT_S = 240

# The metrics the report shows, headline first (the report builder treats the first binary metric
# as the headline). `kind` and `scale` follow the report schema.
METRICS = [
    {"id": "rubric_pass", "label": "Rubric pass", "kind": "binary"},
    {"id": "decision", "label": "Search choice", "kind": "binary"},
    {"id": "query", "label": "Query filters", "kind": "binary"},
    {"id": "fresh", "label": "Fresh results", "kind": "float", "scale": 1},
    {"id": "grounded", "label": "Real links", "kind": "binary"},
    {"id": "rubric_share", "label": "Rubric share", "kind": "float", "scale": 1},
]
PERF_FIELDS = [
    {"id": "cost_usd", "label": "Cost", "unit": "$"},
    {"id": "latency_s", "label": "Latency", "unit": "s"},
    {"id": "web_searches", "label": "Searches"},
]


# ---- search clients: live, recording, replaying, fake -----------------------------------------


class FixtureSearch:
    """A search client that records and/or replays Tavily answers for one case.

    mode "live"    always calls Tavily, saves nothing
    mode "record"  calls Tavily and saves every (params -> result) pair to fixtures/<case>.json
    mode "replay"  answers from the saved pairs; an unseen params dict is searched live, saved, and
                   counted in `misses` (so the report can say how comparable the run really was)
    """

    def __init__(self, case_id: str, mode: str, real_client: Any):
        self.path = FIXTURES_DIR / f"{case_id}.json"
        self.mode = mode
        self.real = real_client
        self.misses = 0
        self.saved: list[dict] = json.loads(self.path.read_text()) if mode == "replay" and self.path.exists() else []

    async def ainvoke(self, params: dict[str, str]) -> Any:
        """Same shape as TavilySearch.ainvoke: params in, Tavily's result dict out."""
        if self.mode == "replay":
            for pair in self.saved:
                if pair["params"] == params:
                    return pair["result"]
            self.misses += 1
        result = await self.real.ainvoke(params)
        if self.mode != "live":
            self.saved.append({"params": params, "result": result})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.saved, ensure_ascii=False, indent=1, default=str))
        return result


class FakeSearch:
    """--fake: one made-up news result dated today, so the dry run exercises every grader for $0."""

    misses = 0

    async def ainvoke(self, params: dict[str, str]) -> dict:
        today = format_datetime(time_now_utc())
        return {"results": [{"title": "Fake news", "url": "https://example.test/news", "content": "x", "published_date": today}]}


def time_now_utc():
    """Now, in UTC, as an aware datetime (helper so FakeSearch's date format matches Tavily's)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


# ---- running one case -----------------------------------------------------------------------------


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Split an SSE body into [(event, data), ...] (same format as docs/contracts.md § 9)."""
    events = []
    for block in text.strip("\n").split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in lines and "data" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


async def run_case(case: dict, model: BaseChatModel, search: Any, classifier: Any) -> dict:
    """Send one question to a fresh Simba app and collect what the graders and report need.

    1. Build an app with its own temporary database, the given model and search client.
    2. POST the question as a new chat and read the SSE stream: the answer the user saw (tokens,
       or the replacement text if the output guard retracted it) and the trace lines.
    3. Read the chat's saved state: which web_search calls ran, what each returned, and which
       model actually answered (checked against the one we asked for).
    """
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        # 1.
        app = create_app(model=model, db_path=f"{tmp}/eval.db", classifier=classifier,
                         web_search_tool=make_web_search_tool(search))
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://eval", timeout=CASE_TIMEOUT_S) as http:
                # 2.
                response = await http.post("/api/chat", json={"message": case["question"], "chat_id": None})
                events = parse_sse(response.text)
            chat_id = events[0][1]["chat_id"]
            state = await app.state.graph.aget_state({"configurable": {"thread_id": chat_id}})

    answer = "".join(d["text"] for e, d in events if e == "token")
    answer = next((d["text"] for e, d in events if e == "replace"), answer)
    errors = [d["message"] for e, d in events if e == "error"]
    lines = [d for e, d in events if e == "trace"]
    done = next((d for e, d in events if e == "done"), {})

    # 3.
    messages = state.values.get("messages", [])
    calls = [c for m in messages if m.type == "ai" for c in (m.tool_calls or []) if c["name"] == "web_search"]
    results = [text_of(m) for m in messages if m.type == "tool" and m.name == "web_search"]
    last_ai = next((m for m in reversed(messages) if m.type == "ai"), None)
    metadata = getattr(last_ai, "response_metadata", {}) or {}
    return {
        "run": CaseRun(answer=answer, tool_calls=[c["args"] for c in calls], tool_results=results,
                       stages=[line["stage"] for line in lines]),
        "messages": messages,
        "lines": lines,
        "error": errors[0] if errors else None,
        "served_model": metadata.get("model_name") or metadata.get("model"),
        "stop_reason": metadata.get("stop_reason"),
        "usage": {"input_tokens": done.get("input_tokens", 0), "output_tokens": done.get("output_tokens", 0)},
        "cost_usd": done.get("cost_usd", 0.0),
        "latency_s": round(time.perf_counter() - started, 2),
        "replay_misses": search.misses,
    }


async def judge_case(client: AsyncAnthropic, case: dict, run: CaseRun, today: date) -> dict:
    """Ask the judge to grade the case's rubric. Returns scores, reasons, usage and cost.

    Uses structured outputs (`messages.parse` with a Pydantic model), so the verdict is valid JSON
    by construction instead of hoping prose parses. A refusal is recorded as such, not as a fail.
    """
    response = await client.messages.parse(
        model=JUDGE_MODEL,
        max_tokens=JUDGE_MAX_TOKENS,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": judge_prompt(case, run, today)}],
        output_format=RubricGrade,
    )
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    price_in, price_out = JUDGE_PRICE_PER_MTOK
    cost = (usage["input_tokens"] * price_in + usage["output_tokens"] * price_out) / 1_000_000
    base = {"usage": usage, "cost_usd": cost, "model": response.model}
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return {**base, "problem": "judge_refused"}
    scores = rubric_scores(case, response.parsed_output)
    if scores is None:
        return {**base, "problem": "judge_wrong_count", "raw": response.parsed_output.model_dump()}
    passed, share, reasons = scores
    return {**base, "problem": None, "pass": passed, "share": share, "reasons": reasons,
            "raw": response.parsed_output.model_dump()}


def trace_turns(case: dict, outcome: dict, today: date) -> list[dict]:
    """The exchange in the report's trace format: system, user, each tool call and result, answer."""
    turns = [{"role": "system", "content": f"{load('system')}\n\nToday is {today_text()}."},
             {"role": "user", "content": case["question"]}]
    for message in outcome["messages"][1:]:
        if message.type == "ai":
            for call in message.tool_calls or []:
                turns.append({"role": "tool_call", "name": call["name"], "content": json.dumps(call["args"], indent=2)})
        elif message.type == "tool":
            turns.append({"role": "tool_result", "content": text_of(message)})
    turns.append({"role": "assistant", "content": outcome["run"].answer})
    return turns


# ---- the whole run --------------------------------------------------------------------------------


def require_run_flag(args: argparse.Namespace, cases: list[dict], judged: bool) -> None:
    """Paid runs are opt-in (#77): without --run, say what would run and stop before any call.

    --fake never costs anything, so it runs without --run. A real run costs one Simba turn per case
    (Claude, plus Tavily in the search eval) and, unless --no-judge, one Opus judge call per case.
    """
    if args.fake or args.run:
        return
    judge = " + 1 Opus judge call" if judged else ""
    print(f"Plan: {len(cases)} case(s), each 1 real Simba turn{judge}. Nothing was called.")
    raise SystemExit("Paid runs are off by default. Add --run to spend money on it, or --fake for a free dry run.")


def load_cases(only: str | None, cases_file: Path = CASES_FILE) -> list[dict]:
    """All cases from a YAML file (the search cases by default), or just the comma-separated ids in `only`."""
    cases = yaml.safe_load(cases_file.read_text())
    if only:
        wanted = set(only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            raise SystemExit(f"unknown case ids: {', '.join(sorted(missing))}")
    return cases


def write_jsonl(path: Path, row: dict) -> None:
    """Append one JSON row (results and errors are both append-only files)."""
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


async def main(args: argparse.Namespace) -> None:
    """Run every case not yet in results.jsonl, grade it, save it, then print the summary.

    1. Check setup: keys present for a paid run; the model really is the real one (or fake).
    2. For each case (CONCURRENCY at a time, each capped at CASE_TIMEOUT_S): run it through Simba,
       grade it in code, ask the judge, and write the results row and trace file.
    3. Print and save the summary (see `summarise`).
    """
    # 1. Paid runs need --run (#77); then the keys must be there.
    require_run_flag(args, load_cases(args.cases), judged=not args.no_judge)
    load_dotenv(BACKEND_DIR / ".env")
    if not args.fake:
        for key in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
            if not os.getenv(key, "").strip():
                raise SystemExit(f"{key} is not set in backend/.env")
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
    cases = [c for c in load_cases(args.cases) if c["id"] not in done_ids]
    today = date.today()
    real_model = None if args.fake else make_model()
    real_search = None if args.fake else make_tavily_client()
    classifier = None if args.fake else load_classifier()
    judge = None if (args.fake or args.no_judge) else AsyncAnthropic()
    gate = asyncio.Semaphore(CONCURRENCY)
    print(f"{len(cases)} case(s) to run -> {variant_dir}  (skipping {len(done_ids)} done)")

    # 2.
    async def one(case: dict) -> None:
        async with gate:
            if args.fake:
                wants = {"web_search": {"query": case["question"], "topic": "news", "time_range": "day"}}
                model, search = fake_model(structured=wants if case["should_search"] else None), FakeSearch()
            else:
                model, search = real_model, FixtureSearch(case["id"], args.search, real_search)
            try:
                outcome = await asyncio.wait_for(run_case(case, model, search, classifier), CASE_TIMEOUT_S)
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
            grade = {
                "decision": grade_decision(case, run),
                "query": grade_query(case, run, today),
                "fresh": grade_freshness(case, run, today),
                "grounded": grade_grounding(run),
                "rubric_pass": None,
                "rubric_share": None,
            }
            row: dict = {}
            if judge is not None:
                verdict = await judge_case(judge, case, run, today)
                row.update(judge_model=verdict["model"], judge_usage=verdict["usage"], judge_cost_usd=verdict["cost_usd"],
                           judge_raw=verdict.get("raw"))  # the judge's own words, kept for audits
                if verdict["problem"]:
                    row["judge_problem"] = verdict["problem"]  # rubric metrics stay None: not scored
                else:
                    grade.update(rubric_pass=verdict["pass"], rubric_share=verdict["share"])
                    row["explanation"] = {"rubric_pass": "\n".join(verdict["reasons"].values())}

            (variant_dir / "traces" / f"{case['id']}_rep0.json").write_text(
                json.dumps(trace_turns(case, outcome, today), ensure_ascii=False, indent=1))
            row = {
                "prompt_id": case["id"], "prompt": case["question"], "rep": 0,
                "tags": [case["group"], "should search" if case["should_search"] else "no search"],
                "status": "truncated" if outcome["stop_reason"] == "max_tokens" else "ok",
                "stop_reason": outcome["stop_reason"], "model": served or "fake",
                "grade": grade, "latency_s": outcome["latency_s"], "web_searches": len(run.tool_calls),
                "tool_calls": len(run.tool_calls), "usage": outcome["usage"], "cost_usd": outcome["cost_usd"],
                "meta": {"queries": run.tool_calls, "trace": outcome["lines"], "turn_error": outcome["error"],
                         "replay_misses": outcome["replay_misses"], "date": today.isoformat(),
                         "judge_raw": row.pop("judge_raw", None)},
                **row,
            }
            write_jsonl(results_file, row)
            shown = " ".join(f"{k}={v if v is None else round(v, 2)}" for k, v in grade.items())
            print(f"  {case['id']}: {shown}")

    await asyncio.gather(*(one(c) for c in cases))

    # 3.
    rows = [json.loads(line) for line in results_file.read_text().splitlines()] if results_file.exists() else []
    summary = summarise(rows)
    (variant_dir / "summary.md").write_text(summary)
    print("\n" + summary)


def summarise(rows: list[dict]) -> str:
    """A markdown table: each metric's average over the cases it applies to, the search decision
    split into precision / recall / specificity, and total cost and mean latency.

    "±" is a rough noise band (1/sqrt(n)): two variants whose difference is inside it aren't
    really different yet — add cases or repeats before trusting it.
    """
    lines = ["| Metric | Score | Cases |", "|---|---|---|"]
    for metric in METRICS:
        values = [r["grade"][metric["id"]] for r in rows if r["grade"].get(metric["id"]) is not None]
        if values:
            mean = sum(values) / len(values)
            lines.append(f"| {metric['label']} | {mean:.0%} ± {1 / math.sqrt(len(values)):.0%} | {len(values)} |")
        else:
            lines.append(f"| {metric['label']} | – | 0 |")

    searched = [bool(r["meta"]["queries"]) for r in rows]
    should = [r["tags"][1] == "should search" for r in rows]
    tp = sum(s and w for s, w in zip(searched, should))
    fp = sum(s and not w for s, w in zip(searched, should))
    fn = sum(not s and w for s, w in zip(searched, should))
    tn = sum(not s and not w for s, w in zip(searched, should))
    ratio = lambda a, b: f"{a / b:.0%}" if b else "–"  # noqa: E731
    lines += [
        "",
        f"Search decision: precision {ratio(tp, tp + fp)} (searches that were needed) · "
        f"recall {ratio(tp, tp + fn)} (needed searches made) · specificity {ratio(tn, tn + fp)} (skipped when not needed)",
        f"Cost: Simba ${sum(r['cost_usd'] for r in rows):.4f} + judge ${sum(r.get('judge_cost_usd', 0) for r in rows):.4f} · "
        f"mean latency {sum(r['latency_s'] for r in rows) / max(len(rows), 1):.1f} s · "
        f"replay misses {sum(r['meta']['replay_misses'] for r in rows)} · cases {len(rows)}",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    """The command line (see the file header for examples)."""
    parser = argparse.ArgumentParser(description="Run Simba's web-search eval (#54).")
    parser.add_argument("--variant", default="baseline", help='"baseline" or "v1", "v2", ... (report folder name)')
    parser.add_argument("--cases", help="comma-separated case ids, e.g. t01,n04 (default: all)")
    parser.add_argument("--search", choices=["live", "record", "replay"], default="record")
    parser.add_argument("--no-judge", action="store_true", help="skip the rubric judge (code graders only)")
    parser.add_argument("--fake", action="store_true", help="fake model, fake search, no judge: free dry run")
    parser.add_argument("--run", action="store_true", help="really run it (costs money); without it, only the plan")
    parser.add_argument("--overwrite", action="store_true", help="delete this variant's earlier results first")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
