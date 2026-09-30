# Simba — requirements

Why Simba exists and what "working" means. Changes rarely. How it's built lives in `docs/design.html`,
why each choice was made in `docs/decisions/`, exact interfaces in `docs/contracts.md`.

## Problem
The owner lost track of how bigger agent apps worked (art-lab, ninja-agent) and couldn't give detailed
requirements for them. Simba is a personal assistant grown one small, readable pattern at a time, so
every agent pattern stays understandable.

## Users
- **Owner (Sol):** chats with Simba, approves anything Simba proposes to add to itself, learns by
  reading the code and the trace panel.

## Goals
- A friendly chat assistant whose harness, graph and agent can each be read in one sitting.
- Every step of every turn is visible in the trace panel, with tokens and cost.
- Safety limits live in deterministic code; model checks are an extra layer.
- Free to develop: tests, CI and UI checks run on the fake model ($0).
- Later: Simba proposes new capabilities (skill, tool, MCP connection, behaviour) and installs them
  only after the owner approves (#30).

## Non-goals (for now)
Login, deployment, multiple users, tools before #17, subagents.

## Scope
| Now (design book 0.3) | Later |
|---|---|
| Chat UI with streamed answers; chats sidebar (new, open, rename, delete) | First tool + tool loop (#17) |
| Trace panel showing every step | Self-growth: propose → approve → install (#30) |
| Hooks listed in `harness/settings.py`, run at hook points (#32) | Subagents |
| Input hooks: size, injection rules, local classifier (flags only) | |
| Output hooks: secrets, internal tags, prompt leaks (retract) | Episodic and semantic memory (#13, #14) |
| One agent call with a structured `report_unsafe` signal (#33) | |
| Per-chat cost budget, $0.50 (#16) | |
| Procedural + short-term memory; fake model; public repo with CI | |

## Acceptance criteria
Each line should map to at least one test.

- **Given** a message over 1,000 characters, **when** it's sent, **then** Simba replies with the fixed
  refusal, makes no model call, and the trace shows the size rule.
- **Given** a known injection phrase ("ignore previous instructions…"), **when** it's sent, **then** it's
  blocked before any model call.
- **Given** the local classifier scores a message as injection, **when** it's sent, **then** the message
  is only flagged (never blocked by the classifier) and the flag reaches the model as a note.
- **Given** a request for harm, **when** the model judges it unsafe, **then** the reply is the fixed
  refusal: "Sorry, I can't help with that one. I'm happy to help with something else, though!"
- **Given** a streamed reply that contains a secret, an internal tag or a prompt leak, **when** it
  finishes, **then** it's retracted: the saved reply is replaced and the page swaps the bubble.
- **Given** any turn, **then** the trace panel shows one line per step with status, detail, time, and a
  footer with tokens and cost.
- **Given** an unknown chat id, **then** the API returns 404; **given** a browser disconnect mid-run,
  **then** the run's trace is still saved.
- **Given** a chat that has already spent $0.50 (sum of its trace costs), **when** a message is sent,
  **then** it's refused with a clear message and a `budget` trace line, and no model call is made.
- **Given** a new chat, **then** its title is the first message cut to 40 characters, and it can be
  renamed and deleted.

## Constraints
- Stack: FastAPI + LangGraph backend, Vite + React + TypeScript + Tailwind frontend.
- Model: `claude-haiku-4-5` for now (D12). No paid call without the owner's OK.
- Public repo: no keys or `.env` in git.
- Self-improvement limits (root `CLAUDE.md`) change only through a human-reviewed PR.

## Open questions
Q13–Q14 in the design book (trace line per hook point; step names) — answer before #32.
