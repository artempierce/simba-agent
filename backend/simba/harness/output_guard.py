"""
output_guard.py — checks on what Simba WRITES (ticket #15, #32), the mirror of guard.py's checks on
what it reads. Pure functions: no LangGraph, no model, no cost.

Where it runs: `settings.py`'s `AFTER_MODEL` list runs these three hooks (via `harness/hooks.py`) on
the finished answer, right after the generate node. The answer has already streamed to the browser by
then, so a hit can't be "blocked" in the input-guard sense — it's RETRACTED: `nodes/hook_points.py`'s
`after_model` swaps the saved reply for RETRACT_TEXT and the API tells the page to swap the bubble too
(policy chosen by Sol, 2026-09-27).

The three hooks, most serious first:

  1. no_secrets        — something that looks like an Anthropic API key, or the variable's name
  2. no_internal_tags   — our own prompt delimiters (<user_message>, <intent>) showing up in an
                          answer means prompt structure is leaking
  3. no_prompt_leak     — the answer repeats a run of LEAK_WORDS consecutive words from one of our
                          prompt files: Simba is quoting its own instructions

Like the input guard's regexes, this is a cheap first layer, not a full defence: a model could
paraphrase its instructions instead of quoting them. It catches the common, verbatim cases for $0.
"""

import re

from simba.harness.hooks import HookResult
from simba.prompts import load

# The fixed reply that replaces a retracted answer. Never built from the answer itself.
RETRACT_TEXT = "I can't share that. Let's talk about something else."

# The prompt files an answer must never quote. Read on every check (load() reads the file each time),
# so an edited prompt is protected on the next message too. Loaded here, not passed in, so
# `no_prompt_leak` has the same one-argument shape as every other hook (Hook = Callable[[str], HookResult]).
PROMPT_NAMES = ("system", "intent", "reason")

# How many consecutive words an answer must share with a prompt file to count as a leak. 8 is long
# enough that ordinary phrases ("in as few words as") don't trip it, short enough that quoting any
# real sentence of the instructions does.
LEAK_WORDS = 8

# Looks like an Anthropic key (they start "sk-ant-"), or names the environment variable holding it.
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}|ANTHROPIC_API_KEY")

# Our own delimiters (see nodes/intent.py and nodes/reason.py), opening or closing, any case/spacing.
INTERNAL_TAGS = re.compile(r"<\s*(?:/\s*)?(?:user_message|intent)\b", re.IGNORECASE)

# A "word" for leak matching: letters, digits and apostrophes, lowercased — so punctuation, line
# breaks and capital letters can't hide a copied sentence.
WORD = re.compile(r"[a-z0-9']+")


def word_runs(text: str, n: int = LEAK_WORDS) -> set[tuple[str, ...]]:
    """Every run of `n` consecutive words in `text`, lowercased, as a set of tuples ("shingles").

    Two texts share a copied passage of at least n words exactly when their shingle sets overlap.

    Example: word_runs("A b, C d!", 3) == {("a", "b", "c"), ("b", "c", "d")}
    """
    words = WORD.findall(text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def no_secrets(text: str) -> HookResult:
    """Hook: block an answer that contains something that looks like an API key."""
    if SECRET.search(text):
        return HookResult("block", "secret", "the answer contains something that looks like an API key")
    return HookResult("allow", None, "no secrets")


def no_internal_tags(text: str) -> HookResult:
    """Hook: block an answer that contains one of Simba's own prompt delimiters."""
    if INTERNAL_TAGS.search(text):
        return HookResult("block", "internal-tags", "the answer contains one of Simba's internal prompt tags")
    return HookResult("allow", None, "no tags")


def no_prompt_leak(text: str) -> HookResult:
    """Hook: block an answer that repeats LEAK_WORDS+ consecutive words from a prompt file.

    Loads PROMPT_NAMES's texts itself (moved here from the old output_guard node) so this hook keeps
    the same one-argument shape as every other hook.
    """
    answer_runs = word_runs(text)
    for name in PROMPT_NAMES:
        if answer_runs & word_runs(load(name)):
            return HookResult("block", "prompt-leak", f"the answer repeats {LEAK_WORDS}+ words of Simba's instructions")
    return HookResult("allow", None, "no leak")
