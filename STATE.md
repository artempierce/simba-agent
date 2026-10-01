# Simba — current state

Handoff note for AI sessions, imported into every session by CLAUDE.md. GitHub issues are the source of
truth; this file only points to them. Update it in the same PR that closes a ticket. Keep it under ~40 lines.

## Milestone
MVP done: guard → intent → reason → generate → output guard, on real Claude or the fake model.
Harness redesign done (design book 0.3): hooks listed in `harness/settings.py` run at hook points
(#32); one `agent` node replaces intent/reason/generate (#33).

## Current focus
Design book 0.4 (safe growth, #67). Phase 2: #66 split in two (owner, 1 Oct) — #66a backend pause
done; #66b next: approval card in the UI, `forget_memory` moves to the card, D51, e2e (starts after
#66a merges). Phase 1 leftover: #62 Sonnet by evals.

## Next up (post-MVP)
- #30 Self-improvement (propose → approve → install), after the tool and approval design is ready
- Memory done (M1–M4: #80 #81 #87 #82 #83); parked: #90 vector recall
- #39 subagents (needs owner answers)

## Recently done
#66a approval pause (backend): `approval_rule` hook, `approval` node with `interrupt()`, SSE `approval` + `POST /api/chat/{id}/resume`, safety cases w01–w03 (not run); no real tool pauses yet ·
#65 tool manifests: each tool declares a `ToolManifest` (read/write, hosts, cost, per-turn limit, needs_approval, enabled); `tools/registry.py` loads them, undeclared or disabled tools are denied in `before_tool`, `/api/info` lists them ·
#83 memory M4: `recall_memory` — open a chat by id, keyword search (FTS5); no embeddings (D50; vector design parked in #90) ·
#82 memory M3: rolling chat summary every 6 owner turns (summarize node, `prompts/summary.md`), recent-chats index in the prompt, Past chats page ·
#87 memory by talking (list / update / two-step forget), feedback rules always loaded, read-only Memory page; D46–D49 ·
#55 search prompt: "When to search" principles (merged without an eval run; owner tests by hand) ·
#81 memory M2: `remember` tool saves facts itself (own words only, never after web results, no secrets, dedupe) + Undo ·
#80 memory M1: fact store, Memory tab (sidebar), core profile (≤ 15 user facts) in the prompt ·
#79 memory design: auto facts with code limits, summaries every 6 turns, hybrid recall; D40–D45 ·
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
| Prompts / personality | `backend/simba/prompts/system.md` (the agent); `summary.md` (chat summaries, #82) |
| Hook points (model/tool) | `harness/settings.py`, `harness/hooks.py`, `harness/tool_hooks.py`, `nodes/hook_points.py` |
| Web search | `backend/simba/tools/web_search.py` (Tavily, requires optional `TAVILY_API_KEY`) |
| Tool permissions | `backend/simba/tools/registry.py` (manifest + registry), each tool file's `MANIFEST`, `docs/contracts.md` § 7.5b; approval pause: `nodes/approval.py`, `approval_rule`, api.py `resume` (§ 7.9) |
| Input checks | `harness/guard.py` (rules), `harness/classifier.py` (local model) |
| Output checks | `harness/output_guard.py` |
| Model, cost, tokens | `model.py`; per-chat budget in `harness/settings.py` + `api.py` step 2b |
| HTTP API / SSE | `api.py`, `chats_api.py`, `specs/api-spec.json` (checked by `tests/test_api_spec.py`) |
| Chat storage | `chats.py` (SQLite in `data/`) |
| Memory | `memory.py` (facts, pending forget, chat summaries), `nodes/summarize.py`, `memory_api.py` (read + Undo), `tools/memory_tools.py`, hook `memory_from_owner`, `nodes/agent.py` `profile_block`; frontend `MemoryPage.tsx` |
| Frontend | `App.tsx` (state), `api.ts` (SSE parser), `components/TracePanel.tsx`, `ChatView.tsx`; style in `docs/visual-style.md` |
| Benchmark + red team | `evals/deepeval/` (separate uv project, HTTP black-box), `evals/benchmark_cases.yaml`, `targets.yaml` |
| Evals (search, safety) | `evals/*_cases.yaml` (cases + rubrics), `backend/evals/` (runners, graders); results in the main checkout's `.claude/hillclimb/`; README → Evals |
| Tests | `backend/tests/test_<module>.py`; `node_harness.py` runs one node in isolation |

## Blockers / notes
No paid eval runs until the owner has reviewed the evals (2026-09-30).
