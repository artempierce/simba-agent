# Simba — current state

Handoff note for AI sessions: read this first, then the ticket. GitHub issues are the source of
truth; this file only points to them. Update it in the same PR that closes a ticket. Keep it under ~40 lines.

## Milestone
MVP almost done: full pipeline (guard → intent → reason → generate → output guard) runs on real
Claude or the fake model, with a live trace panel and a chats sidebar.

## Current focus
- #11 Design book: sync with what was built + republish (also fix README: flow and layout miss the output guard; step 5 still says "real Claude awaits OK")
- #10 Personality prompts (needs owner)

## Next up (post-MVP)
- #17 First tool + ReAct loop (design first) → then #30 self-improvement (propose → approve → install)
- #12 Frontend tests (Vitest) · #16 Per-chat cost budget · #13 / #14 memory designs

## Recently done
#9 real Claude + token counts in trace · #15 output guard · #24 OpenAPI spec · #20/#21 redesign + avatar · #8 guard classifier

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
