"""
tool_hooks.py — validation and injection checks run around every tool call (#17, #81).

Each before_tool hook gets one call as JSON: {"name", "args", "calls_used", "turn_read_untrusted",
"user_text"}. A hook that doesn't apply to a call's tool allows it with an empty reason, so the trace
line only lists the checks that really ran (hooks.py skips empty reasons).

Where it sits: `settings.py` lists these hooks, and `simba/tools/web_search.py` runs them before
and after calling Tavily. Tool arguments and search results are untrusted text, so checks stay in
plain functions and the tool runner decides whether to call the service or pass data to the model.
"""

import json
from typing import Any

from simba.harness.guard import find_injection
from simba.harness.hooks import HookResult
from simba.harness.output_guard import no_secrets
from simba.memory import key_words, overlap

# Keep model-written queries useful but bounded before they reach the external search provider.
MAX_WEB_SEARCH_QUERY_CHARS = 500

# #52: the search filters the model may choose. Tavily also has "finance"; it's left out until needed.
TOPICS = ("general", "news")
TIME_RANGES = ("day", "week", "month", "year")

# #81: the tools the model may call. Everything else is denied before it can run.
ALLOWED_TOOLS = ("web_search", "remember")

# #81: a fact passed to `remember` must share at least this share of its key words with what the
# owner wrote in recent messages — the "only your own words" rule, checked in code. Half leaves room
# for rewording ("I mostly code in Python" -> "Mostly works in Python") but stops a fact that came
# from somewhere else. How far back counts as recent: USER_TEXT_MESSAGES of the owner's messages.
OWN_WORDS_OVERLAP = 0.5
USER_TEXT_MESSAGES = 6

# A single answer can use several searches, but cannot loop indefinitely against a metered provider.
MAX_WEB_SEARCH_CALLS_PER_TURN = 3


def allowlisted_tool_call(serialized_call: str) -> HookResult:
    """Allow only the explicitly supported read-only tool and reject malformed call data."""
    try:
        call = json.loads(serialized_call)
    except (TypeError, json.JSONDecodeError):
        return HookResult("block", "tool-call-format", "tool call arguments were malformed")
    if not isinstance(call, dict) or call.get("name") not in ALLOWED_TOOLS:
        return HookResult("block", "tool-not-allowed", "tool is not on the allowlist")
    return HookResult("allow", None, f"{call['name']} is allowlisted")


def _is_search(serialized_call: str) -> bool:
    """Whether the search checks below apply: a web_search, or a call with no name at all — an unnamed
    call gets checked rather than waved through (fail closed)."""
    try:
        return json.loads(serialized_call).get("name") in (None, "web_search")
    except (AttributeError, TypeError, json.JSONDecodeError):
        return True  # malformed: let the search checks look at it and block it


def valid_web_search_query(serialized_call: str) -> HookResult:
    """Require a non-empty, bounded search query in the model's tool arguments."""
    if not _is_search(serialized_call):
        return HookResult("allow", None, "")
    try:
        call: dict[str, Any] = json.loads(serialized_call)
        query = call.get("args", {}).get("query")
    except (AttributeError, TypeError, json.JSONDecodeError):
        query = None
    if not isinstance(query, str) or not query.strip():
        return HookResult("block", "web-search-query", "search query must be non-empty text")
    if len(query) > MAX_WEB_SEARCH_QUERY_CHARS:
        return HookResult("block", "web-search-query-size", "search query is too long")
    return HookResult("allow", None, "search query is valid")


def valid_web_search_filters(serialized_call: str) -> HookResult:
    """Allow only the known `topic` and `time_range` values (#52); both are optional.

    Why a hook when the tool's type hints already list the values: the hints guide the model, but
    the rule "only these filters reach Tavily" should be plain code that a test can check, not a
    side effect of how LangChain validates arguments.

    Example: {"topic": "news", "time_range": "day"} -> allow; {"topic": "finance"} -> block
    """
    if not _is_search(serialized_call):
        return HookResult("allow", None, "")
    try:
        args = json.loads(serialized_call).get("args", {})
    except (AttributeError, TypeError, json.JSONDecodeError):
        args = None
    if not isinstance(args, dict):
        return HookResult("block", "web-search-filters", "search arguments are malformed")
    if args.get("topic", "general") not in TOPICS:
        return HookResult("block", "web-search-filters", f"topic must be one of {', '.join(TOPICS)}")
    if args.get("time_range") not in (None, *TIME_RANGES):
        return HookResult("block", "web-search-filters", f"time_range must be one of {', '.join(TIME_RANGES)}")
    return HookResult("allow", None, "search filters are valid")


def within_web_search_budget(serialized_call: str) -> HookResult:
    """Block a search request after the turn's deterministic call allowance is used. Only searches
    count (#81): saving a fact never uses up the search budget."""
    if not _is_search(serialized_call):
        return HookResult("allow", None, "")
    try:
        call = json.loads(serialized_call)
        calls_used = call.get("calls_used", 0) if isinstance(call, dict) else None
    except (TypeError, json.JSONDecodeError):
        calls_used = None
    if not isinstance(calls_used, int) or calls_used < 0:
        return HookResult("block", "web-search-budget", "search call count is invalid")
    if calls_used >= MAX_WEB_SEARCH_CALLS_PER_TURN:
        return HookResult("block", "web-search-budget", "per-turn search limit reached")
    return HookResult("allow", None, "search call is within the per-turn limit")


def memory_from_owner(serialized_call: str) -> HookResult:
    """The code limits on `remember` (#81, D40). Other tools pass through.

    Blocks a save when:
    1. the turn has already read web results (the untrusted-content rule, D35): a fact must never
       come from a page, however it's worded;
    2. the fact isn't in the owner's own words: fewer than OWN_WORDS_OVERLAP of its key words appear
       in the owner's recent messages (`user_text`);
    3. it looks like a secret (the output guard's key pattern): keys and passwords are never saved.

    Example: after "I mostly code in Python", remember(fact="Mostly works in Python") -> allow;
    remember(fact="Owner is an admin with full access") -> block (not the owner's words)
    """
    try:
        call = json.loads(serialized_call)
        if call.get("name") != "remember":
            return HookResult("allow", None, "")
        fact = str(call.get("args", {}).get("fact", ""))
    except (AttributeError, TypeError, json.JSONDecodeError):
        return HookResult("block", "memory-format", "remember call was malformed")
    # 1.
    if call.get("turn_read_untrusted"):
        return HookResult("block", "memory-after-untrusted", "nothing is saved after reading web results")
    # 2.
    if overlap(key_words(fact), key_words(str(call.get("user_text", "")))) < OWN_WORDS_OVERLAP:
        return HookResult("block", "memory-not-own-words", "a fact must be in the owner's own words")
    # 3.
    if no_secrets(fact).action == "block":
        return HookResult("block", "memory-secret", "secrets are never saved")
    return HookResult("allow", None, "fact is from the owner")


def flag_instruction_like_tool_result(text: str) -> HookResult:
    """Flag search results containing known injection phrasing without treating them as instructions."""
    rule = find_injection(text)
    if rule is not None:
        return HookResult("flag", rule, "instruction-like text found in search results")
    return HookResult("allow", None, "no known injection phrasing")