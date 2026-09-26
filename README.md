# Simba

A small, friendly AI assistant built as a **learning lab**. Every message goes through a visible
pipeline — a code guard, an intent check, a reasoning step and the answer — and each step shows up
live in a trace panel next to the chat.

- Design book (what and why): [`docs/design.html`](docs/design.html) · [published version](https://claude.ai/artifact/Kh7t1hNsLvJdULwHgEtsSD)
- Interfaces (exactly how the pieces fit): [`docs/contracts.md`](docs/contracts.md)

## How one message flows

```
your message → guard (code rules) ─┬─ blocked → refuse (fixed reply)
                                   └─ pass → intent (LLM: restate + safety verdict) ─┬─ unsafe → refuse
                                                                                    └─ safe → reason (LLM: action + plan) → generate (LLM: streamed answer)
```

## Build status

| Step | What | Status |
|---|---|---|
| 0 | Repo, contracts, core modules (model, state, schemas, prompts), CI | done |
| 1 | Skeleton: chat UI + trace panel + echo node, SSE streaming | done |
| 2 | Guard + refuse | done |
| 3 | Intent check | planned |
| 4 | Reason | planned |
| 5 | Generate (first real Claude call after the owner's OK) | planned |
| 6 | Chats sidebar: new, open, rename, delete | planned |
| 7 | Personality tuning | planned |

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Node 22+.

```bash
cp backend/.env.example backend/.env          # SIMBA_FAKE_LLM=1 = free fake model
cd backend && uv sync && uv run pytest -q
cd backend && uv run uvicorn simba.api:app --reload --port 8000
cd frontend && npm install && npm run dev     # http://localhost:5173
```

## Repo layout

```
simba-agent/
├── CLAUDE.md                 rules for AI coding sessions
├── docs/design.html          design book
├── docs/contracts.md         interfaces between the parts
├── .github/workflows/ci.yml  tests on every pull request
├── backend/simba/
│   ├── api.py                FastAPI app: POST /api/chat streams SSE events (start/trace/token/error/done)
│   ├── graph.py              draws the graph: which nodes run, in what order
│   ├── guard.py              the code guard's rules: size limit + prompt-injection patterns
│   ├── nodes/                one file per graph node: guard, refuse (more each step)
│   ├── model.py              real Claude or the free fake model; cost per call
│   ├── state.py              the graph's state
│   ├── schemas.py            structured-output shapes (IntentCheck, Decision)
│   ├── common.py             shared helpers, including the trace-line writer
│   └── prompts/              Simba's procedural memory: system.md, intent.md, reason.md
└── frontend/src/
    ├── App.tsx               the page and all its state
    ├── api.ts                streamChat: POST + a small SSE parser
    ├── types.ts              shapes shared with the backend
    └── components/           ChatView (messages + input), TracePanel (the dark right pane)
```
