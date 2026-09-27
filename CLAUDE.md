# Simba — rules for AI coding sessions

## What Simba is

A personal assistant that can grow itself: on the owner's request it proposes a new capability
(skill, tool, MCP connection, behaviour) and, after the owner approves, builds and installs it.
It is also a **learning project**, grown one small step at a time so every agent pattern stays
readable (FastAPI + LangGraph backend, React frontend). The owner learns by reading the code.

- **Start here:** `STATE.md` — current focus, next tickets, where to look. Read it first.
- Why and what: `docs/design.html` (published at https://claude.ai/artifact/Kh7t1hNsLvJdULwHgEtsSD).
  Read it only when the task changes the design; then update and republish it.
- Exact interfaces: `docs/contracts.md`. Code and contracts must agree; fix one of them in the same change.
- Work items: GitHub issues (`gh issue view <n>`). Issues are the source of truth; `STATE.md` points to them.

## Session rules (keep sessions cheap)

1. Read `STATE.md`, then the ticket, then only the files the ticket touches. Don't survey the repo.
2. Code directly. Short replies, no filler.
3. One ticket, one small PR. If the logic diff grows past ~150 lines (docs and tests don't count),
   stop and propose a split.
4. Verify with the commands below and read only the failing output.
5. No subagents unless the owner asks. Reviews happen in this session (see Workflow).
6. When a ticket's PR is ready, update `STATE.md` in that same PR (focus, next up, recently done).

## Commands

```bash
cd backend && uv run pytest -q --tb=short
cd backend && SIMBA_FAKE_LLM=1 uv run uvicorn simba.api:app --reload --port 8000
cd frontend && npm run lint && npm run build     # build includes the TypeScript check
cd frontend && npm run dev                        # http://localhost:5173
```

## Self-improvement rules (Simba changing itself)

Hard limits for the self-growth feature (#30). They live in deterministic code, never only in prompts.

1. **Propose, never apply.** Simba may draft a skill, tool, MCP connection or behaviour; nothing is
   installed until the owner approves it in the UI. The approval gate is code, not a model decision.
2. **Show the whole change.** The approval view lists exactly what gets added: files, permissions,
   network hosts, expected cost.
3. **Least privilege.** Every capability declares what it may touch (files, hosts, secrets);
   anything undeclared is denied. New MCP connections start disabled.
4. **Generated means untrusted.** Code and prompts Simba writes are treated like user input:
   validated, tested with the fake model, run sandboxed.
5. **Reversible and visible.** Every capability is versioned, can be disabled or rolled back in one
   step, and its install shows in the trace.
6. **Simba cannot loosen its own limits.** The guard, the approval gate, budgets, secrets and these
   rules change only through a human-reviewed PR.

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

- **Ticket first.** Every change starts from a GitHub issue (labels: `mvp`, `post-mvp`, `needs-owner`,
  `design`, `chore`). Branch `<n>-<slug>` (e.g. `8-guard-classifier`), PR title `#8 …`, PR body
  `Closes #8`. Related tickets may share one PR (`Closes #20, closes #21`).
- **One ticket, one fresh worktree:**
  1. `git fetch && git worktree add .claude/worktrees/<n>-<slug> -b <n>-<slug> origin/main`, then
     enter it with the `EnterWorktree` tool (`path`) — file tools can't edit it otherwise.
  2. Work and test there.
  3. Push and open the PR **into `main`**, never into another feature branch (stacked PRs had to be
     re-landed, PR #27). Merge when CI is green.
  4. Tear down right away: `git worktree remove …`, delete the local and the remote branch.
     A worktree that still exists means unfinished work.
- **Review once, in this session, two passes;** fix or explicitly waive every finding:
  1. *Architecture:* fits the design book and contracts, right layer, simplest design, no hidden
     coupling, security and self-improvement rules respected, no correctness bugs.
  2. *Quality:* no wasted work, blocking calls in async code, slow regexes or needless model / DB
     calls; tests prove what their docstrings claim and would fail if the code broke.

  Learning-first readability is the top criterion for both: code that works but a learner can't
  follow is not done.
- **Done means:** it runs and shows in the trace panel; tests, lint and build pass; review findings
  are resolved; code is documented to the standard; `STATE.md` is updated; a PR merged into `main`
  with green CI.
