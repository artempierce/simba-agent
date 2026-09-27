# Simba — rules for AI coding sessions

Simba is a **learning project**: a small, friendly assistant (FastAPI + LangGraph backend, React
frontend) grown one step at a time so every agent pattern stays understandable. The owner learns by
reading the code.

- What to build and why: `docs/design.html` (the design book, published at
  https://claude.ai/artifact/Kh7t1hNsLvJdULwHgEtsSD). Update and republish it when a step changes the design.
- Exact interfaces: `docs/contracts.md`. Code and contracts must agree; fix one of them in the same change.

## Documentation standard (required for every change)

This overrides any general "keep comments minimal" preference.

1. **Every file** starts with a header comment: what the file is, where it sits in the message flow,
   and the key idea a reader needs.
2. **Every function / component** has a docstring: what it does, inputs and outputs, and *why* it
   exists or is shaped that way. Add a small example when it helps (see `model.cost_usd`).
3. **Main logic** gets numbered step comments that match the docstring's steps. Explain a library
   concept on first use (reducers, stream modes, structured output, SSE…).
4. **Constants** say what they control and why that value.
5. **Tests** have a docstring saying what behaviour they protect and why it matters.
6. Plain words for a learner; don't comment the obvious.
7. Keep `README.md` in sync in the same change.

## Security rule: untrusted by default

Everything that doesn't come from Simba's own code and prompts is untrusted data — including the
user's messages. Hard limits live in deterministic code (guard, routing, what each node sees);
model-based checks are an extra layer, never the only one. Fail closed on safety checks.

## Cost rule

- Never make a real paid API call (Claude) without asking the owner first.
- Tests, CI and UI checks use the fake model (`simba.model.fake_model`, or `SIMBA_FAKE_LLM=1`).
- Never commit `.env` or a key: the repo is public.

## Workflow

Work is split between a lead (plans, writes contracts, integrates, opens PRs) and builder agents
(implement one task each, in their own worktree, touching only the files they own). Before any PR,
the change is reviewed by two critics, and every finding is fixed or explicitly waived:

1. **Code expert (architecture)** — does it fit the design book and `docs/contracts.md`? Right layer,
   simplest design, no hidden coupling, security rule respected, correctness bugs.
2. **Quality engineer (efficiency + tests)** — wasted work, blocking calls in async code, slow regexes,
   needless model calls or DB round-trips; do the tests prove what their docstrings claim, and would
   they fail if the code broke?

Both critics treat **learning-first readability as the top criterion**: the documentation standard
above, clear names, small functions, one idea per step. Code that works but a learner can't follow
is not done.

A step is done only when: it runs and shows in the trace panel; `cd backend && uv run pytest` and
`cd frontend && npm run lint && npm run build` pass; both critics' findings are resolved; code is
documented to the standard; it went through a pull request into `main` with green CI.

## Commands

```bash
cd backend && uv run pytest -q
cd backend && SIMBA_FAKE_LLM=1 uv run uvicorn simba.api:app --reload --port 8000
cd frontend && npm run dev          # http://localhost:5173
cd frontend && npm run lint && npm run build
```
