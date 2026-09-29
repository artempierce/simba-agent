# Simba — current state

Handoff note for AI sessions, imported into every session by CLAUDE.md. GitHub issues are the source of
truth; this file only points to them. Update it in the same PR that closes a ticket. Keep it under ~40 lines.

## Milestone
MVP done: guard → intent → reason → generate → output guard, on real Claude or the fake model.
Harness redesign done (design book 0.3): hooks listed in `harness/settings.py` run at hook points
(#32); one `agent` node replaces intent/reason/generate (#33).

## Current focus
None open — next items need the owner's input before they can be planned (see Next up).

## Next up (post-MVP)
- #10 Personality prompts (needs owner, one `system.md` to tune)
- #17 First tool + ReAct loop, before/after_tool hooks (settings.py's empty lists) → then #30 self-improvement (propose → approve → install)
- #12 Frontend tests (Vitest) · #16 Per-chat cost budget · #13 / #14 memory designs

## Recently done
#33 one `agent` node replaces intent/reason/generate: `ReportUnsafe` tool, safety rules merged into
`system.md` · #32 hooks in settings: `harness/` folder, hook runner, before_model/after_model nodes ·
#35 Claude Code setup (rules by load time, requirements, decision log) · #11 design book 0.3 (harness
redesign) · #9 real Claude + token counts in trace · #15 output guard

## Where to look
| Task | Files |
|---|---|
| Change a graph step | `backend/simba/nodes/<step>.py`, wiring in `graph.py`, fields in `state.py`, `docs/contracts.md` |
| Prompts / personality | `backend/simba/prompts/system.md` (the only prompt) |
| Hook points (before/after_model) | `harness/settings.py` (which hooks run), `harness/hooks.py` (the runner), `nodes/hook_points.py` (graph glue) |
| Input checks | `harness/guard.py` (rules), `harness/classifier.py` (local model) |
| Output checks | `harness/output_guard.py` |
| Model, cost, tokens | `model.py` |
| HTTP API / SSE | `api.py`, `chats_api.py`, `specs/api-spec.json` (checked by `tests/test_api_spec.py`) |
| Chat storage | `chats.py` (SQLite in `data/`) |
| Frontend | `App.tsx` (state), `api.ts` (SSE parser), `components/TracePanel.tsx`, `ChatView.tsx`; style in `docs/visual-style.md` |
| Tests | `backend/tests/test_<module>.py`; `node_harness.py` runs one node in isolation |

## Blockers / notes
None.
