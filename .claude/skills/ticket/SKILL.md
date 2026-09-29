---
name: ticket
description: Build one GitHub ticket from its approved plan in a fresh worktree, up to an open PR
disable-model-invocation: true
argument-hint: <issue-number>
model: sonnet
---

Build ticket #$ARGUMENTS. You are the builder: the plan was written and approved on Opus; follow it.

1. **Read.** `gh issue view $ARGUMENTS --comments`. Find the approved plan comment.
   - No plan and the change can't be described in one sentence → STOP. Tell the owner to plan it
     first (in a normal session: "plan #$ARGUMENTS"), then `/clear` and run `/ticket` again.
   - Then read only the files the plan names, plus `STATE.md`'s "Where to look" row.
2. **Worktree.** `git fetch && git worktree add .claude/worktrees/<n>-<slug> -b <n>-<slug> origin/main`,
   then enter it with the `EnterWorktree` tool (`path`) — file tools can't edit it otherwise.
3. **Build in small steps.** After each step run its check from the plan. A failing check → fix it
   before moving on. Logic diff past ~150 lines (docs and tests don't count) → stop, propose a split.
4. **Verify everything** and keep the evidence (command + last lines of output):
   `cd backend && uv run pytest -q --tb=short` · `cd frontend && npm run lint && npm run build` ·
   a screenshot if the UI changed.
5. **Document** to `.claude/rules/documentation.md` and keep `README.md` in sync.
6. **STATE.md.** Move the ticket to "Recently done", update "Current focus" and "Next up".
7. **PR.** Commit `#<n> <summary>`, push, `gh pr create --base main` with body `Closes #<n>`,
   what changed, and the evidence. Never target another feature branch.
8. **Hand off.** End with the PR link and: "Ready for review — run `/pr-review <pr-number>`."
   Don't review or merge here.
