# Prompt log

Why `backend/simba/prompts/system.md` changed, newest first. One entry per change: what, why, and how
it was checked. (#10 asked for this before/after log.)

## 2026-10-01 — a fact and a search in one message; weather searches (#96)

- **Before:** nothing on a message that both states a fact and needs a search; search topic: "For news
  use the news topic with a time range".
- **After:** "One message can mean two things" — save the fact *and* search, and save first (or in the
  same step), because a save after web results waits for the user's approval (D52). Weather,
  forecasts, prices and other live facts that aren't news articles use the general topic, no time range.
- **Why:** owner bug report: "Yeah, I live in Glendale, CA" after a weather question searched first,
  so the save was blocked; the `news` topic turned the weather search into flight ads.
- **Checked:** backend tests with the fake model; the owner tries it on real Claude by hand (paid).

## 2026-10-01 — forget waits for the approval card (#66b)

- **Before:** forget_memory "deletes nothing until you have asked 'Forget …? (yes/no)' and they answer
  yes in their next message; then call it again with the same arguments."
- **After:** call forget_memory once; the user approves or denies it on a card, so don't ask in chat.
- **Why:** D51 — the approval card replaced the next-message yes (D47); the old wording would make
  Simba ask twice.
- **Checked:** backend tests with the fake model; no paid runs (a wording fix to match the code).

## 2026-09-30 — recall past chats (#83)

- **Added:** when the user refers to an earlier chat or something not in <memory>, use recall_memory — with
  the chat id from "Recent chats" to read its summary, or with keywords to search; try other words before
  saying you don't remember.
- **Why:** D50 — recall the way Claude Code's memory works: index + open by id + keyword search.
- **Checked:** backend tests with the fake model; no paid runs.

## 2026-09-30 — memory by talking (#87)

- **Changed:** the Memory section now covers the "how the user wants you to work" notes (follow them),
  and managing memory by talking: list_memory for "what do you remember", update_memory for
  corrections, forget_memory only after asking "Forget …? (yes/no)" and getting a yes.
- **Why:** owner decision D46–D48: memory is managed only through conversation, like Claude Code's own.
- **Checked:** backend tests with the fake model (incl. the forget flow); no paid runs.

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
## 2026-09-29 — when and how to search (#55)

- **Before:** one line: "If web_search is available, use it for current information… Cite source URLs…"
- **After:** a "When to search" section of principles: search when the answer depends on something that
  changes (news, prices, weather, scores, versions, who holds a job); don't search for things that
  don't change; search when unsure; judge "latest" from today's date ("latest news" = today's), news
  topic + time range, no year in the query; check result dates and search again or say what's old;
  a source link next to each fact; never claim to have no live access.
- **Why:** the search eval baseline (#54) failed on missing links (7 cases), "latest" read as this week
  (t01, t02) and no search for live weather (t03, and the safety eval's i04).
- **Checked:** search eval rerun with `--search replay` against a fresh baseline (see PR).

## 2026-09-29 — personality: warm, upbeat, a little funny (#10)

- **Before:** "Warm and friendly, like a helpful friend. Never stiff or formal."
- **After:** warm and upbeat ("a good friend who's glad you asked"); a light touch of humour when it
  fits (never at the user's expense, none for serious, sad or urgent topics); lifts the user's mood
  by noticing effort and progress, while staying honest rather than flattering.
- **Why:** the owner wants Simba to feel like a warm person who is sometimes funny and leaves them in
  a better mood.
- **Checked:** backend tests (fake model); a few real replies reviewed by the owner (see PR).
