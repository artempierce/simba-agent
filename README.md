# Simba

A small, friendly AI assistant built as a **learning lab**. Every message goes through a visible
pipeline — a code guard, then an agent that can answer, refuse, or search the web — and each step
shows up live in a trace panel next to the chat.

- Requirements (why, and what "working" means): [`docs/requirements.md`](docs/requirements.md)
- Design book (how): [`docs/design.html`](docs/design.html) · [published version](https://claude.ai/artifact/Kh7t1hNsLvJdULwHgEtsSD)
- Decisions (which, and why): [`docs/decisions/README.md`](docs/decisions/README.md)
- Interfaces (exactly how the pieces fit): [`docs/contracts.md`](docs/contracts.md)

## How one message flows

```
your message → before_model ─┬─ blocked → refuse
                             └─ pass → agent ─┬─ answer → after_model → done
                                              ├─ report_unsafe → refuse
                                              └─ web_search → before_tool → Tavily → after_tool → agent (loop)
```

Each hook point (`before_model`, `after_model`, `before_tool`, `after_tool`) runs the checks listed
in `harness/settings.py`, cheapest first, and stops at the first block (#32, #17).

The before_model hooks have two layers: regex rules that **block**, then a small local model
(`protectai/deberta-v3-base-prompt-injection-v2`, runs on your CPU, $0) that only **flags** (⚑). A flag
never blocks on its own: it tells the agent to look carefully, and the LLM makes the call.

## Build status

| Step | What | Status |
|---|---|---|
| 0 | Repo, contracts, core modules (model, state, schemas, prompts), CI | done |
| 1 | Skeleton: chat UI + trace panel + echo node, SSE streaming | done |
| 2 | Guard + refuse | done |
| 3 | Intent check | done |
| 4 | Reason | done |
| 5 | Generate, then real Claude + token counts (#9) and the output guard (#15) | done |
| 6 | Chats sidebar: new, open, rename, delete | done |
| M1 | Memory: saved facts, Memory tab in the sidebar, your profile in every prompt (#80) | done |
| M2 | Memory: Simba remembers by itself (`remember` tool, code limits), "Remembered · Undo" (#81) | done |
| M2b | Memory by talking: "what do you remember?", corrections, forget with a yes; learned rules always loaded; Memory page (#87) | done |
| M3 | Episodic memory: a rolling summary per chat every 6 messages; recent chats in the prompt; Past chats on the Memory page (#82) | done |
| M4 | Recall like Claude Code: open a past chat by id, keyword search over memory; no embedding model (#83, D50) | done |
| — | Harness redesign: guard/output_guard become before_model/after_model hooks (#32) | done |
| — | Harness redesign: intent + reason + generate become one `agent` node (#33) | done |
| 17 | First read-only tool: optional Tavily web search + ReAct loop | in progress |
| 7 | Personality tuning | planned |

**Frontend tests** (#12): a small Vitest suite covers the SSE parser (`src/api.test.ts`) and
App.tsx's stale-response guards (`src/App.test.tsx`). Run it with `cd frontend && npm test`; CI runs
it too.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Node 22+.

```bash
cp backend/.env.example backend/.env          # SIMBA_FAKE_LLM=1 = free fake model
cd backend && uv sync && uv run pytest -q
cd backend && uv run python -m simba.harness.classifier   # optional, once: downloads the ~740 MB injection classifier
cd backend && uv run uvicorn simba.api:app --reload --port 8000
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Web search is optional. Add `TAVILY_API_KEY` to `backend/.env` to enable it; when the variable is
empty or missing, Simba starts normally without binding the search tool. Tests use a fake Tavily
client and never make an external search request. Each user turn is limited to three search calls.

## Evals (hand-run, costs money)

Every eval is **plan-only by default**: without `--run` it prints what it would do and stops (#77).
`--fake` runs for free.

`evals/search_cases.yaml` holds 30 questions that check how Simba uses web search (#54): does it search
only when needed, with news filters for "today", do the results come back fresh, are its links real,
and does the answer pass the case's rubric (graded by a judge model, Opus 5.5). Four checks are plain
code; only the rubric costs a model call. Not run in CI.

```bash
cd backend
uv run --group eval python -m evals.run_search_eval --fake                    # free dry run
uv run --group eval python -m evals.run_search_eval --cases t01,n04 --run     # a few real cases (paid)
uv run --group eval python -m evals.run_search_eval --variant v1 --search replay --run   # compare a change
```

**Safety eval** (#58): `evals/safety_cases.yaml` holds 33 cases built on the OWASP Top 10 for LLM apps —
direct and indirect prompt injection (the attack hidden in a search result), prompt extraction,
harmful requests, secrets — plus 7 benign questions that only *sound* risky, so over-refusal counts
as a failure too. Search is scripted (free, repeatable). The summary shows the attack success rate,
the over-refusal rate, and which guardrail caught each attack.

```bash
uv run --group eval python -m evals.run_safety_eval --fake       # free dry run
uv run --group eval python -m evals.run_safety_eval --run        # all 33 (paid)
```

`--search record` (the default) saves Tavily's answers; `--search replay` reuses them, so two variants
are compared on the same search results. Output goes to `.claude/hillclimb/<search|safety>/<variant>/` in the main checkout,
even when run from a worktree (git-ignored): `summary.md`, `results.jsonl`, one trace per case.

### Benchmark and red teaming (DeepEval, DeepTeam)

`evals/deepeval/` is a **separate small project** (its own `pyproject.toml`): DeepEval pins versions
that clash with the backend's, and it tests Simba the way a user or attacker would, over the HTTP API
of a running server. Every script prints its plan and stops; `--run` is what spends money. Judge and
attacker are Claude models (the libraries default to OpenAI); telemetry and cloud upload are off.

```bash
cd evals/deepeval
uv run python benchmark.py              # plan: 30 everyday cases, which metrics, how many calls
uv run python benchmark.py --run        # paid: needs a real-model Simba on SIMBA_URL (default :8000)
uv run python redteam.py                # plan: 10 OWASP-mapped vulnerabilities, 12 attack styles
uv run python redteam.py --run          # paid
uv run pytest -q                        # the harness's own tests, free (also in CI)
```

**Benchmark metrics (#72)** — targets in `evals/deepeval/targets.yaml`:

| Metric | What it answers | Why this one |
|---|---|---|
| Correctness (GEval) | Are the reference answer's facts there, none contradicted? | The core "is it right" score; GEval lets a judge compare meaning, not wording |
| Answer relevancy | Does every part of the reply address the question? | Catches padding and drift that correctness misses |
| Simba style (GEval) | Answer first, warm, plain words, honest? | The product's own voice, as a checkable rubric |
| Tool correctness | Searched exactly when live information was needed? | Graded in code: tool choice is right or wrong |
| Knowledge retention | Keeps what you said earlier in the chat? | The multi-turn failure single-turn scores can't see |
| Cost per turn, p50 / p95 latency | What a turn costs, how long the slow ones take | Quality that's too slow or expensive isn't shippable |
| pass^k (`--repeats k`) | Passes on *every* one of k runs? | Models vary run to run; one lucky pass isn't reliability |

**Red teaming (#73):** an attacker model writes attacks for 10 vulnerabilities (prompt and secret
leakage, PII, indirect instructions, excessive agency, illegal activity, personal safety, toxicity,
bias, misinformation, robustness) wrapped in 12 tricks (role-play, base64, leetspeak, ROT13, other
languages, fake system messages, authority claims, emotional pressure, multi-turn crescendo…), and a
judge decides whether Simba held. Target: attack success rate ≤ 2%, and zero for prompt and PII leakage.

## Repo layout

```
simba-agent/
├── CLAUDE.md                 rules for AI coding sessions (backend/ and frontend/ have their own, loaded on demand)
├── STATE.md                  current focus + where to look (imported by CLAUDE.md)
├── .claude/                  shared Claude Code setup: settings.json, rules/ (skills /ticket and /pr-review are global)
├── docs/requirements.md      why Simba exists, acceptance criteria
├── docs/design.html          design book
├── docs/decisions/           decision log (D1…)
├── docs/contracts.md         interfaces between the parts
├── .github/workflows/ci.yml  tests on every pull request
├── data/simba.db             your chats (git-ignored; created on first run)
├── data/models/              the local classifier's model files (git-ignored; optional)
├── backend/simba/
│   ├── api.py                FastAPI app: POST /api/chat streams SSE events (start/trace/token/error/done)
│   ├── chats.py              ChatStore: chat titles + each turn's trace, in SQLite
│   ├── chats_api.py          /api/chats: list, create, open, rename, delete
│   ├── graph.py              draws the graph: which nodes run, in what order
│   ├── harness/
│   │   ├── guard.py          before_model hooks: size limit (1,000 chars) + prompt-injection patterns
│   │   ├── classifier.py     the local prompt-injection model + classifier_hook, flags (⚑) messages
│   │   ├── output_guard.py   after_model hooks: secrets, internal tags, prompt leaks
│   │   ├── hooks.py          HookResult, Hook, and run_hooks (the hook runner)
│   │   ├── tool_hooks.py     allowlist, query length, and untrusted-result scan
│   │   └── settings.py       which hooks run at each hook point, in which order
│   ├── nodes/                one file per graph node: hook_points (before_model/after_model), agent, refuse
│   ├── tools/web_search.py   optional Tavily client, capped/untrusted results
│   ├── model.py              real Claude or the free fake model; cost per call
│   ├── state.py              the graph's state
│   ├── schemas.py            structured-output shape (ReportUnsafe)
│   ├── common.py             shared helpers, including the trace-line writer
│   └── prompts/              Simba's procedural memory: system.md (the only prompt)
└── frontend/src/
    ├── App.tsx               the page and all its state
    ├── api.ts                streamChat: POST + a small SSE parser
    ├── chatsApi.ts           the chat list's REST calls
    ├── types.ts              shapes shared with the backend
    └── components/           Sidebar (chat list), MobileDrawer, ChatView (messages + input),
                              TracePanel (the dark right pane)
```
