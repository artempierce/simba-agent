# Prompt log

Why `backend/simba/prompts/system.md` changed, newest first. One entry per change: what, why, and how
it was checked. (#10 asked for this before/after log.)

## 2026-09-30 — memory: when to remember (#81)

- **Added:** a Memory section: use the <memory> block when it helps without reciting it; save lasting facts
  with `remember` (user / feedback with the reason / project / reference) as one short sentence in the
  user's words; don't save what's already known, one-off details, web content or secrets; save quietly.
- **Why:** memory design D40 — the model decides what to keep, like Claude Code's own memory; the limits
  are in code (`memory_from_owner`).
- **Checked:** backend tests with the fake model; no paid runs.

## 2026-09-30 — honesty: answer from knowledge, never make things up (#74)

- **Before:** "If you don't know something, say so. Never invent facts, links or numbers."
- **After:** an Honesty section: answer from what you know or found, kept apart from guesses; with no
  facts behind a claim, say so and offer to search, never fill the gap with a plausible name, number,
  date, quote or link; correct a false premise instead of answering it; flag what may be out of date;
  label opinions and estimates.
- **Why:** owner request — Simba should never make up an answer when there are no facts behind it.
- **Checked:** backend tests (fake model); benchmark honesty cases f01–f04 (#72) when the owner OKs a run.

## 2026-09-29 — personality: warm, upbeat, a little funny (#10)

- **Before:** "Warm and friendly, like a helpful friend. Never stiff or formal."
- **After:** warm and upbeat ("a good friend who's glad you asked"); a light touch of humour when it
  fits (never at the user's expense, none for serious, sad or urgent topics); lifts the user's mood
  by noticing effort and progress, while staying honest rather than flattering.
- **Why:** the owner wants Simba to feel like a warm person who is sometimes funny and leaves them in
  a better mood.
- **Checked:** backend tests (fake model); a few real replies reviewed by the owner (see PR).
