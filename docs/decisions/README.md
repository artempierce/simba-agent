# Decisions

The canonical decision log. One line per decision; a decision that needs more than one line (context,
trade-offs, alternatives) also gets its own file, `D<n>-<slug>.md`, from the template below.
Decisions are never edited: a new one replaces an old one, and the old row says "replaced by".

D1–D26 were copied from design book 0.3 (`docs/design.html` § Decisions). New decisions start at D27
and are recorded here first; the design book catches up at its next sync.

| # | Decision | Status | Source |
|---|---|---|---|
| D1 | New repo simba-agent | accepted | Sol, 26 Sep |
| D2 | A separate intent step restates the request and checks it for injection or harm | replaced by D21, D24 | Sol, 26 Sep |
| D3 | Reason is a separate node that decides the next action | replaced by D21 | Sol, 26 Sep |
| D4 | LangGraph from the start | accepted | Sol, 26 Sep |
| D5 | Procedural, episodic and semantic memory are the target | accepted | Sol, 26 Sep |
| D6 | Local repo + GitHub with CI | accepted | Sol, 26 Sep |
| D7 | GitHub repo is public | accepted | Sol, 26 Sep |
| D8 | Refusal text: "I can't help with that request. Please ask about something else." | accepted | Sol, 26 Sep |
| D9 | Simba may ask a clarifying question instead of answering (now a plain reply from the agent) | accepted | Sol, 26 Sep |
| D10 | Memory is procedural + short-term first; episodic and semantic next | accepted | Sol, 26 Sep |
| D11 | Personality: friendly, warm, concise | accepted | Sol, 26 Sep |
| D12 | claude-haiku-4-5 for model calls, for now | accepted | Sol, 26 Sep |
| D13 | LangSmith tracing off for now | accepted | Sol, 26 Sep |
| D14 | Chats sidebar with rename and delete; title = first message cut to 40 characters | accepted | Sol, 26 Sep |
| D15 | The local classifier only flags, never blocks; the model makes the call | accepted | Sol, 27 Sep |
| D16 | The output guard retracts a streamed answer: the saved reply is replaced and the page swaps the bubble | accepted | Sol, 27 Sep |
| D17 | Unknown chat id → 404; a run's trace is saved even if the browser disconnects | accepted | MVP build |
| D18 | Every PR gets two review passes, architecture then quality; learning-first readability comes first | accepted | Sol |
| D19 | Ticket first, branch `<n>-<slug>`, one fresh worktree per ticket, PR into main | accepted | Sol, #18 |
| D20 | Hard limits live in deterministic code; model checks are an extra layer; fail closed | accepted | CLAUDE.md |
| D21 | One agent node replaces intent, reason and generate: one model call per turn | accepted | Sol, 28 Sep |
| D22 | Hooks are listed in settings.py and run at fixed hook points inside the graph; input and output checks become hooks | accepted | Sol, 28 Sep |
| D23 | Our own hook runner, not LangChain's create_agent middleware | accepted | Sol, 28 Sep |
| D24 | No separate LLM safety check: the classifier's flag becomes a note in the agent's prompt, and report_unsafe is the model's structured "no" | accepted | Sol, 28 Sep |
| D25 | LangGraph stays the engine for tools, owner approval and subagents | accepted | Sol, 28 Sep |
| D26 | Harness files live in a simba/harness/ folder: settings.py, hooks.py, guard.py, classifier.py, output_guard.py | accepted | Sol, 28 Sep (Q12) |
| D27 | Claude Code setup: rules split by load time (root, `backend/`, `frontend/`, path rule); tickets planned on Opus, built with the global `/ticket` skill on Sonnet, reviewed with the global `/pr-review` on Opus | accepted | Sol, 28 Sep, #35 |

## Template for a decision file

```markdown
# D<n> — <decision in a few words>
Status: accepted · <date>          (or: replaced by D<m>)

## Context       what forced a choice
## Decision      what we chose
## Consequences  good and bad
## Alternatives  what we didn't pick, and why
```
