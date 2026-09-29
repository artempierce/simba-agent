"""
tool_hooks.py — validation and injection checks run around every tool call (#17).

Where it sits: `settings.py` lists these hooks, and `simba/tools/web_search.py` runs them before
and after calling Tavily. Tool arguments and search results are untrusted text, so checks stay in
plain functions and the tool runner decides whether to call the service or pass data to the model.
"""

import json
from typing import Any

from simba.harness.guard import find_injection
from simba.harness.hooks import HookResult

# Keep model-written queries useful but bounded before they reach the external search provider.
MAX_WEB_SEARCH_QUERY_CHARS = 500

# #52: the search filters the model may choose. Tavily also has "finance"; it's left out until needed.
TOPICS = ("general", "news")
TIME_RANGES = ("day", "week", "month", "year")

# A single answer can use several searches, but cannot loop indefinitely against a metered provider.
MAX_WEB_SEARCH_CALLS_PER_TURN = 3


def allowlisted_tool_call(serialized_call: str) -> HookResult:
    """Allow only the explicitly supported read-only tool and reject malformed call data."""
    try:
        call = json.loads(serialized_call)
    except (TypeError, json.JSONDecodeError):
        return HookResult("block", "tool-call-format", "tool call arguments were malformed")
    if not isinstance(call, dict) or call.get("name") != "web_search":
        return HookResult("block", "tool-not-allowed", "tool is not on the allowlist")
    return HookResult("allow", None, "web_search is allowlisted")


def valid_web_search_query(serialized_call: str) -> HookResult:
    """Require a non-empty, bounded search query in the model's tool arguments."""
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
    """Block a search request after the turn's deterministic call allowance is used."""
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


def flag_instruction_like_tool_result(text: str) -> HookResult:
    """Flag search results containing known injection phrasing without treating them as instructions."""
    rule = find_injection(text)
    if rule is not None:
        return HookResult("flag", rule, "instruction-like text found in search results")
    return HookResult("allow", None, "no known injection phrasing")