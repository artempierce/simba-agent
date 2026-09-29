# Simba — rules for AI coding sessions

@STATE.md

## What Simba is

A personal assistant that can grow itself: on the owner's request it proposes a new capability
(skill, tool, MCP connection, behaviour) and, after the owner approves, builds and installs it.
It is also a **learning project**, grown one small step at a time so every agent pattern stays
readable (FastAPI + LangGraph backend, React frontend). The owner learns by reading the code.

## Where truth lives (read only what the task needs)

| Question | File |
|---|---|
| Where are we now? | `STATE.md` (imported above) |
| Why / what, acceptance criteria | `docs/requirements.md` |
| Which decision, and why | `docs/decisions/README.md` — new decisions go here first (D27+) |
| How it's designed | `docs/design.html` (published at https://claude.ai/artifact/Kh7t1hNsLvJdULwHgEtsSD) — read only for design work; then update and republish it |
| Exact interfaces | `docs/contracts.md`, `specs/api-spec.json` — code and contracts must agree; fix one of them in the same change |
| Work items | GitHub issues (`gh issue view <n>`); a ticket's plan is a comment on its issue |

`backend/CLAUDE.md`, `frontend/CLAUDE.md` and `.claude/rules/documentation.md` load by themselves
when a session works in those files.

## Commands

```bash
cd backend && uv run pytest -q --tb=short
cd backend && SIMBA_FAKE_LLM=1 uv run uvicorn simba.api:app --reload --port 8000
cd frontend && npm run lint && npm run build     # build includes the TypeScript check
cd frontend && npm run dev                        # http://localhost:5173
```

## Workflow

1. **Plan** (normal session, Opus): "plan #n" → read the issue, `STATE.md` and only the files it
   touches → post the plan as an issue comment (goal, files, steps each with a check, out of scope,
   done-when) → wait for the owner's OK. Skip for a change you can describe in one sentence.
2. **Build:** `/clear`, then `/ticket <n>` (Sonnet) — fresh worktree, build, verify, `STATE.md`, PR.
3. **Review:** `/pr-review <pr>` (Opus) — two passes, fix or waive findings, merge on green CI, tear down.

Every change starts from a GitHub issue (labels: `mvp`, `post-mvp`, `needs-owner`, `design`, `chore`).
One ticket, one worktree, one PR into `main` — never into another feature branch (PR #27).
No subagents unless the owner asks. Short replies, no filler.

## Self-improvement rules (Simba changing itself)

Hard limits for the self-growth feature (#30). They live in deterministic code, never only in prompts.

1. **Propose, never apply.** Nothing is installed until the owner approves it in the UI. The approval
   gate is code, not a model decision.
2. **Show the whole change:** files, permissions, network hosts, expected cost.
3. **Least privilege.** Every capability declares what it may touch; anything undeclared is denied.
   New MCP connections start disabled.
4. **Generated means untrusted:** validated, tested with the fake model, run sandboxed.
5. **Reversible and visible:** versioned, disabled or rolled back in one step, shown in the trace.
6. **Simba cannot loosen its own limits.** The guard, approval gate, budgets, secrets and these rules
   change only through a human-reviewed PR.

## Security rule: untrusted by default

Everything that doesn't come from Simba's own code and prompts is untrusted data — including the
user's messages. Hard limits live in deterministic code (guard, routing, what each node sees);
model-based checks are an extra layer, never the only one. Fail closed on safety checks.

## Cost rule

- Never make a real paid API call (Claude) without asking the owner first.
- Tests, CI and UI checks use the fake model (`simba.model.fake_model`, or `SIMBA_FAKE_LLM=1`).
- Never commit `.env` or a key: the repo is public.

## Done means

It runs and shows in the trace panel; tests, lint and build pass; review findings are resolved; code
is documented to `.claude/rules/documentation.md`; `STATE.md` is updated; a PR merged into `main`
with green CI.

## Compact instructions

When compacting, keep: the ticket and PR numbers, the worktree path, files changed, failing test
names, and open review findings.
