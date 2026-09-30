# Simba — current state

Handoff note for AI sessions, imported into every session by CLAUDE.md. GitHub issues are the source of
truth; this file only points to them. Update it in the same PR that closes a ticket. Keep it under ~40 lines.

## Milestone
MVP done: guard → intent → reason → generate → output guard, on real Claude or the fake model.
Harness redesign done (design book 0.3): hooks listed in `harness/settings.py` run at hook points
(#32); one `agent` node replaces intent/reason/generate (#33).

## Current focus
Design book 0.4 (safe growth, #67). Phase 1: #55 search prompt, #62 Sonnet by evals, #63 input
normalisation, #64 safety-eval follow-ups. Phase 2: #65 tool manifests, #66 approval pause.

## Next up (post-MVP)
- #30 Self-improvement (propose → approve → install), after the tool and approval design is ready
- #39 subagents (needs owner answers) · #13 / #14 memory designs

## Recently done
#77 every eval is plan-only unless `--run` (owner: no paid runs until reviewed) ·
#74 honesty section in `system.md`: no made-up answers, false premises corrected ·
#72 #73 DeepEval benchmark (30 cases, targets) + DeepTeam red teaming, built not run (`evals/deepeval/`) ·
#63 guard folds spelling tricks (look-alike letters, accents, spaced letters, leetspeak, line breaks) ·
#64 warm fixed refusal (D39); safety eval grades the fixed refusal in code ·
#67 design book 0.4: permissions, approvals, skills, developer agent; D30–D38 ·
#58 safety eval: 30 OWASP-based cases (injection, leaks, harm, secrets, over-refusal) ·
#10 personality: warm, upbeat, light humour (`system.md`; history in `docs/prompt-log.md`) ·
#57 header pill: model + web search on/off from `GET /api/info` ·
#54 web-search eval: 30 rubric cases, code graders + Opus judge, record/replay search ·
#52 fresher search: today's date in the prompt, `topic`/`time_range` per search, query + filters in the trace ·
#50 fix: trace panel's sr-only labels no longer stretch the page (empty scroll) ·
#48 fix: a call to a tool that isn't configured becomes a text answer (was KeyError 'before_tool') ·
#16 per-chat cost budget: $0.50 (`harness/settings.py`), checked in `api.py` before the graph ·
#12 frontend tests: Vitest for the SSE parser and App's stale-response guards, run in CI ·
#17 Tavily `web_search` + ReAct loop (optional, needs `TAVILY_API_KEY`); the per-turn search budget
ends the turn in code (follow-up to PR #44) · #42 no unsafe stream leaks, chat-delete race ·
#33 one `agent` node replaces intent/reason/generate: `ReportUnsafe` tool, safety rules merged into
`system.md` · #32 hooks in settings: `harness/` folder, hook runner, before_model/after_model nodes ·
#35 Claude Code setup (rules by load time, requirements, decision log) · #11 design book 0.3 (harness
redesign) · #9 real Claude + token counts in trace · #15 output guard

## Where to look
| Task | Files |
|---|---|
| Change a graph step | `backend/simba/nodes/<step>.py`, wiring in `graph.py`, fields in `state.py`, `docs/contracts.md` |
| Prompts / personality | `backend/simba/prompts/system.md` (the only prompt) |
| Hook points (model/tool) | `harness/settings.py`, `harness/hooks.py`, `harness/tool_hooks.py`, `nodes/hook_points.py` |
| Web search | `backend/simba/tools/web_search.py` (Tavily, requires optional `TAVILY_API_KEY`) |
| Input checks | `harness/guard.py` (rules), `harness/classifier.py` (local model) |
| Output checks | `harness/output_guard.py` |
| Model, cost, tokens | `model.py`; per-chat budget in `harness/settings.py` + `api.py` step 2b |
| HTTP API / SSE | `api.py`, `chats_api.py`, `specs/api-spec.json` (checked by `tests/test_api_spec.py`) |
| Chat storage | `chats.py` (SQLite in `data/`) |
| Frontend | `App.tsx` (state), `api.ts` (SSE parser), `components/TracePanel.tsx`, `ChatView.tsx`; style in `docs/visual-style.md` |
| Benchmark + red team | `evals/deepeval/` (separate uv project, HTTP black-box), `evals/benchmark_cases.yaml`, `targets.yaml` |
| Evals (search, safety) | `evals/*_cases.yaml` (cases + rubrics), `backend/evals/` (runners, graders); results in the main checkout's `.claude/hillclimb/`; README → Evals |
| Tests | `backend/tests/test_<module>.py`; `node_harness.py` runs one node in isolation |

## Blockers / notes
No paid eval runs until the owner has reviewed the evals (2026-09-30).
