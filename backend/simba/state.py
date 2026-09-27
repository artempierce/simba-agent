"""
state.py — the graph's state: the small typed dictionary every node reads and updates.

How LangGraph uses it: each node receives the current state and returns a dict of only the fields it
wants to change. LangGraph merges that dict into the state. For most fields "merge" means "replace";
`messages` is special — its *reducer* (`add_messages`) appends new messages instead of replacing
the whole list, so a node returns {"messages": [new_reply]} and the history is kept.

Per-turn fields (verdict, intent, decision) describe the CURRENT message only. The checkpointer saves
state between turns, so api.py resets them to None at the start of every turn — otherwise a node could
read last turn's verdict by mistake.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class Verdict(TypedDict):
    """A safety check's result for this turn, written by the guard node and then the intent node.

    status  "pass" or "blocked" — the conditional edges route on this
    rule    None when passed; else which check blocked it, e.g. "size", "ignore-instructions",
            "intent-injection", "intent-harmful"
    reason  one readable sentence, shown in the trace panel
    """

    status: Literal["pass", "blocked"]
    rule: str | None
    reason: str


class ChatState(TypedDict):
    """Everything the graph knows about one chat (one LangGraph thread).

    messages  the conversation, oldest first; `add_messages` appends (see file header)
    verdict   this turn's safety result (Verdict), or None before the guard runs
    intent    this turn's request restated in one line by the intent node, or None
    decision  this turn's Decision from the reason node, stored as a plain dict
              {"action": "answer" | "clarify", "plan": [...]} so the checkpointer can save it
    flag      why the local classifier flagged this turn, e.g. "classifier 0.97" (#8); None = not
              flagged. Set by the guard node, read by the intent node (nodes/guard.py § 7.2).
    """

    messages: Annotated[list[AnyMessage], add_messages]
    verdict: Verdict | None
    intent: str | None
    decision: dict | None
    flag: str | None
