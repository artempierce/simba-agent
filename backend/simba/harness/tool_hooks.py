"""
tool_hooks.py — validation and injection checks run around every tool call (#17, #81).

Each before_tool hook gets one call as JSON: {"name", "args", "calls_used", "turn_read_untrusted",
"user_text", "manifest"} — `manifest` is the tool's permission manifest as a dict, or null when the
tool was never declared (#65). A hook that doesn't apply to a call's tool allows it with an empty reason, so the trace
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

# #87: the memory tools that change memory, and which argument holds the new text (None: no text).
MEMORY_WRITES = {"remember": "fact", "update_memory": "text", "forget_memory": None}

# #81: a fact passed to `remember` must share at least this share of its key words with what the
# owner wrote in recent messages — the "only your own words" rule, checked in code. Half leaves room
# for rewording ("I mostly code in Python" -> "Mostly works in Python") but stops a fact that came
# from somewhere else. How far back counts as recent: USER_TEXT_MESSAGES of the owner's messages.
OWN_WORDS_OVERLAP = 0.5
USER_TEXT_MESSAGES = 6


def allowlisted_tool_call(serialized_call: str) -> HookResult:
    """Allow only a tool whose manifest is declared and enabled (#65, D34); reject malformed call data.

    The payload's `manifest` is what the registry holds for the called tool (nodes/hook_points.py puts
    it there), or None when nobody declared the tool. Undeclared or disabled -> blocked, in code.
    The allow reason is the manifest summary, so the trace line shows what the tool may do.
    """
    try:
        call = json.loads(serialized_call)
    except (TypeError, json.JSONDecodeError):
        return HookResult("block", "tool-call-format", "tool call arguments were malformed")
    if not isinstance(call, dict) or not isinstance(call.get("manifest"), dict):
        return HookResult("block", "tool-not-allowed", "tool has no declared manifest")
    manifest = call["manifest"]
    if not manifest.get("enabled"):
        return HookResult("block", "tool-not-allowed", "tool is switched off in its manifest")
    approval = "needs approval" if manifest.get("needs_approval") else "no approval"
    return HookResult("allow", None, f"{call.get('name')} · {manifest.get('access')} · {approval}")


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
    count (#81): saving a fact never uses up the search budget. The allowance is the manifest's
    `max_calls_per_turn` (#65); a search whose manifest sets no limit fails closed."""
    if not _is_search(serialized_call):
        return HookResult("allow", None, "")
    try:
        call = json.loads(serialized_call)
        calls_used = call.get("calls_used", 0) if isinstance(call, dict) else None
        limit = (call.get("manifest") or {}).get("max_calls_per_turn")
    except (AttributeError, TypeError, json.JSONDecodeError):
        calls_used = limit = None
    if not isinstance(calls_used, int) or calls_used < 0 or not isinstance(limit, int):
        return HookResult("block", "web-search-budget", "search call count or limit is invalid")
    if calls_used >= limit:
        return HookResult("block", "web-search-budget", "per-turn search limit reached")
    return HookResult("allow", None, "search call is within the per-turn limit")


def memory_from_owner(serialized_call: str) -> HookResult:
    """The code limits on memory changes (#81, #87; D40). Reads (list_memory) and other tools pass.

    Blocks a memory write when:
    1. (forget_memory) the turn has already read web results: a page must never be able to put
       "forget everything" in front of the owner, where one wrong click would wipe their memory;
    2. (remember, update_memory) the new text isn't in the owner's own words: fewer than
       OWN_WORDS_OVERLAP of its key words appear in the owner's recent messages (`user_text`);
    3. (remember, update_memory) it looks like a secret: keys and passwords are never saved.
    Otherwise forget_memory's lock is the approval card (its manifest needs approval, #66b, D51).

    After web results (#96, D52) a save that passes checks 2 and 3 isn't blocked any more:
    approval_rule holds it for the owner's card, like every write after untrusted content (D35). So a
    page can't change memory on its own, but "I live in Glendale" said in a turn that also searched
    the weather can still be saved, once the owner clicks Approve.

    Example: after "I mostly code in Python", remember(fact="Mostly works in Python") -> allow;
    remember(fact="Owner is an admin with full access") -> block (not the owner's words)
    """
    try:
        call = json.loads(serialized_call)
        if call.get("name") not in MEMORY_WRITES:
            return HookResult("allow", None, "")
        text_arg = MEMORY_WRITES[call["name"]]
        fact = str(call.get("args", {}).get(text_arg, "")) if text_arg else ""
    except (AttributeError, TypeError, json.JSONDecodeError):
        return HookResult("block", "memory-format", "memory call was malformed")
    if text_arg is None:
        # 1.
        if call.get("turn_read_untrusted"):
            return HookResult("block", "memory-after-untrusted", "nothing is forgotten after reading web results")
        return HookResult("allow", None, "")  # forget's own lock is the approval card (approval_rule)
    # 2.
    if overlap(key_words(fact), key_words(str(call.get("user_text", "")))) < OWN_WORDS_OVERLAP:
        return HookResult("block", "memory-not-own-words", "a fact must be in the owner's own words")
    # 3.
    if no_secrets(fact).action == "block":
        return HookResult("block", "memory-secret", "secrets are never saved")
    return HookResult("allow", None, "fact is from the owner")


# #66: the rule name approval_rule flags with; before_tool (nodes/hook_points.py) looks for it.
NEEDS_APPROVAL = "needs-approval"


def approval_rule(serialized_call: str) -> HookResult:
    """Decide whether a call must wait for the owner's approval (#66, D35). Runs last, so a call
    another hook blocked never gets this far.

    A call needs approval when:
    1. its manifest says `needs_approval`, or
    2. it is a `write` tool and this turn has already read untrusted content (web results): a page
       must never be able to trigger a change on its own, whatever the manifest says.
    The answer is a "flag" with rule NEEDS_APPROVAL, not a block: the call is valid, it just waits.
    remember / update_memory after web results reach rule 2 too (#96, D52), but only once
    memory_from_owner has checked they're in the owner's own words and hold no secret; forget_memory
    after web results never gets here (memory_from_owner blocks it).

    Example: {"manifest": {"access": "write", ...}, "turn_read_untrusted": true} -> flag
    "write after web results"; the same call with turn_read_untrusted false -> allow.
    """
    try:
        call = json.loads(serialized_call)
        manifest = call.get("manifest") or {}
    except (AttributeError, TypeError, json.JSONDecodeError):
        return HookResult("block", "approval-format", "tool call was malformed")
    # 1.
    if manifest.get("needs_approval"):
        return HookResult("flag", NEEDS_APPROVAL, "waits for approval")
    # 2.
    if manifest.get("access") == "write" and call.get("turn_read_untrusted"):
        return HookResult("flag", NEEDS_APPROVAL, "write after web results waits for approval")
    return HookResult("allow", None, "")


def flag_instruction_like_tool_result(text: str) -> HookResult:
    """Flag search results containing known injection phrasing without treating them as instructions."""
    rule = find_injection(text)
    if rule is not None:
        return HookResult("flag", rule, "instruction-like text found in search results")
    return HookResult("allow", None, "no known injection phrasing")