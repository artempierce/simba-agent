# Simba

A small, friendly AI assistant built as a **learning lab**. Every message goes through a visible
pipeline — a code guard, an intent check, a reasoning step and the answer — and each step shows up
live in a trace panel next to the chat.

- Requirements (why, and what "working" means): [`docs/requirements.md`](docs/requirements.md)
- Design book (how): [`docs/design.html`](docs/design.html) · [published version](https://claude.ai/artifact/Kh7t1hNsLvJdULwHgEtsSD)
- Decisions (which, and why): [`docs/decisions/README.md`](docs/decisions/README.md)
- Interfaces (exactly how the pieces fit): [`docs/contracts.md`](docs/contracts.md)

## How one message flows

```
your message → guard (code rules + local classifier) ─┬─ blocked → refuse (fixed reply)
                                                      └─ pass (maybe ⚑ flagged) → intent (LLM: restate + safety verdict) ─┬─ unsafe → refuse
                                                                                                                         └─ safe → reason (LLM: action + plan) → generate (LLM: streamed answer) → output guard (code checks; retracts a leak)
```

**Planned redesign** (design book 0.3, #32 / #33): the checks become hooks listed in
`harness/settings.py`, and intent + reason + generate become one `agent` node — one model call per turn.

The guard has two layers: regex rules that **block**, then a small local model
(`protectai/deberta-v3-base-prompt-injection-v2`, runs on your CPU, $0) that only **flags** (⚑). A flag
never blocks on its own: it tells the intent check to look carefully, and the LLM makes the call.

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
| 7 | Personality tuning | planned |

**Known gap:** the frontend has no automated tests yet (only lint + type-check + build in CI). The
riskiest untested logic is App.tsx's stale-response guards (`requestedChatRef`, `chatsSeqRef`); a
small Vitest suite is a good first addition after the MVP.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Node 22+.

```bash
cp backend/.env.example backend/.env          # SIMBA_FAKE_LLM=1 = free fake model
cd backend && uv sync && uv run pytest -q
cd backend && uv run python -m simba.classifier   # optional, once: downloads the ~740 MB injection classifier
cd backend && uv run uvicorn simba.api:app --reload --port 8000
cd frontend && npm install && npm run dev     # http://localhost:5173
```

## Repo layout

```
simba-agent/
├── CLAUDE.md                 rules for AI coding sessions (backend/ and frontend/ have their own, loaded on demand)
├── STATE.md                  current focus + where to look (imported by CLAUDE.md)
├── .claude/                  shared Claude Code setup: settings.json, rules/, skills/ (/ticket, /pr-review)
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
│   ├── guard.py              the code guard's rules: size limit (1,000 chars) + prompt-injection patterns
│   ├── classifier.py         the local prompt-injection model the guard uses to flag (⚑) messages
│   ├── output_guard.py       checks on the finished answer: secrets, internal tags, prompt leaks
│   ├── nodes/                one file per graph node: guard, intent, reason, generate, output_guard, refuse
│   ├── model.py              real Claude or the free fake model; cost per call
│   ├── state.py              the graph's state
│   ├── schemas.py            structured-output shapes (IntentCheck, Decision)
│   ├── common.py             shared helpers, including the trace-line writer
│   └── prompts/              Simba's procedural memory: system.md, intent.md, reason.md
└── frontend/src/
    ├── App.tsx               the page and all its state
    ├── api.ts                streamChat: POST + a small SSE parser
    ├── chatsApi.ts           the chat list's REST calls
    ├── types.ts              shapes shared with the backend
    └── components/           Sidebar (chat list), MobileDrawer, ChatView (messages + input),
                              TracePanel (the dark right pane)
```
