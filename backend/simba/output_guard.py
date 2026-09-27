"""
output_guard.py — checks on what Simba WRITES (ticket #15), the mirror of guard.py's checks on what it
reads. Pure functions: no LangGraph, no model, no cost.

Where it runs: the `output_guard` node (nodes/output_guard.py) calls `check_output()` on the finished
answer, right after the generate node. The answer has already streamed to the browser by then, so a
hit can't be "blocked" — it's RETRACTED: the node swaps the saved reply for RETRACT_TEXT and the API
tells the page to swap the bubble too (policy chosen by Sol, 2026-09-27).

The three checks, most serious first:

  1. secret        — something that looks like an Anthropic API key, or the variable's name
  2. internal-tags — our own prompt delimiters (<user_message>, <intent>) showing up in an answer means
                     prompt structure is leaking
  3. prompt-leak   — the answer repeats a run of LEAK_WORDS consecutive words from one of our prompt
                     files: Simba is quoting its own instructions

Like the input guard's regexes, this is a cheap first layer, not a full defence: a model could
paraphrase its instructions instead of quoting them. It catches the common, verbatim cases for $0.
"""

import re

from simba.guard import GuardResult

# The fixed reply that replaces a retracted answer. Never built from the answer itself.
RETRACT_TEXT = "I can't share that. Let's talk about something else."

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


def check_output(answer: str, prompts: list[str]) -> GuardResult:
    """Run the three output checks on one finished answer.

    Args:
        answer:  the reply the generate node wrote
        prompts: the texts of our prompt files (system.md, intent.md, reason.md) to check for leaks

    Returns:
        A GuardResult (the same shape the input guard uses): `rule` is None when the answer passes,
        else "secret", "internal-tags" or "prompt-leak"; `reason` is one readable sentence.

    Steps:
      1. secret: a key-like string or the key's variable name.
      2. internal-tags: one of our prompt delimiters.
      3. prompt-leak: any LEAK_WORDS-word run shared with a prompt file.
    """
    # 1.
    if SECRET.search(answer):
        return GuardResult("secret", "the answer contains something that looks like an API key")
    # 2.
    if INTERNAL_TAGS.search(answer):
        return GuardResult("internal-tags", "the answer contains one of Simba's internal prompt tags")
    # 3.
    answer_runs = word_runs(answer)
    for prompt in prompts:
        if answer_runs & word_runs(prompt):
            return GuardResult("prompt-leak", f"the answer repeats {LEAK_WORDS}+ words of Simba's instructions")
    return GuardResult(None, "pass · 3 checks")
