# Simba — current state

Handoff note for AI sessions, imported into every session by CLAUDE.md. GitHub issues are the source of
truth; this file only points to them. Update it in the same PR that closes a ticket. Keep it under ~40 lines.

## Milestone
MVP done: guard → intent → reason → generate → output guard, on real Claude or the fake model.
Now: harness redesign (design book 0.3, approved 2026-09-28): hooks listed in `harness/settings.py`
run at hook points; one `agent` node replaces intent/reason/generate.

## Current focus
- #32 H2 Hooks in settings: `harness/` folder, hook runner, before/after_model nodes (answer Q13/Q14 in the book first)
- #33 H3 One agent node (after #32)

## Next up (post-MVP)
- #10 Personality prompts (needs owner; after #33, one `system.md`)
- #17 First tool + ReAct loop, before/after_tool hooks → then #30 self-improvement (propose → approve → install)
- #12 Frontend tests (Vitest) · #16 Per-chat cost budget · #13 / #14 memory designs

## Recently done
#35 Claude Code setup (`/ticket`, `/pr-review`, requirements, decision log) · #11 design book 0.3 (harness redesign) · #9 real Claude + token counts in trace · #15 output guard · #24 OpenAPI spec · #20/#21 redesign + avatar · #8 guard classifier

## Where to look
| Task | Files |
|---|---|
| Change a graph step | `backend/simba/nodes/<step>.py`, wiring in `graph.py`, fields in `state.py`, `docs/contracts.md` |
| Prompts / personality | `backend/simba/prompts/*.md` |
| Input guard | `guard.py` (rules), `classifier.py` (local model), `nodes/guard.py` |
| Output guard | `output_guard.py`, `nodes/output_guard.py` |
| Model, cost, tokens | `model.py` |
| HTTP API / SSE | `api.py`, `chats_api.py`, `specs/api-spec.json` (checked by `tests/test_api_spec.py`) |
| Chat storage | `chats.py` (SQLite in `data/`) |
| Frontend | `App.tsx` (state), `api.ts` (SSE parser), `components/TracePanel.tsx`, `ChatView.tsx`; style in `docs/visual-style.md` |
| Tests | `backend/tests/test_<module>.py`; `node_harness.py` runs one node in isolation |

## Blockers / notes
None.
