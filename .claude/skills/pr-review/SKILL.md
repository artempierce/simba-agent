---
name: pr-review
description: Review a Simba PR in two passes (architecture, then quality), fix findings, merge on green CI, tear down
disable-model-invocation: true
argument-hint: <pr-number>
model: opus
---

Review PR #$ARGUMENTS in this session (no reviewer subagents). Learning-first readability is the top
criterion for both passes: code that works but a learner can't follow is not done.

1. **Read.** `gh pr view $ARGUMENTS` and `gh pr diff $ARGUMENTS`, the linked issue's plan comment,
   and only the surrounding code a finding needs.
2. **Pass 1 — Architecture.** Fits the design book and `docs/contracts.md`; right layer; simplest
   design; no hidden coupling; security rule and self-improvement limits respected; no correctness bugs.
3. **Pass 2 — Quality.** No wasted work; no blocking calls in async code; no slow regexes or needless
   model / DB calls; tests prove what their docstrings claim and would fail if the code broke;
   documented to `.claude/rules/documentation.md`; `STATE.md` updated.
4. **Findings.** List each one (file:line, what, why). Fix it in the PR's worktree, or waive it with a
   one-line reason. Flag only what affects correctness, the plan, or readability — not taste.
5. **Merge.** Re-run the checks after fixes, push, wait for green CI (`gh pr checks $ARGUMENTS --watch`),
   then `gh pr merge $ARGUMENTS --merge`.
6. **Tear down.** Leave the worktree (`ExitWorktree`, keep), then `git worktree remove <path>`,
   `git branch -D <branch>`, `git push origin --delete <branch>`. A worktree that still exists means
   unfinished work.
