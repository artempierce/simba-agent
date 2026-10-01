"""
state.py — the graph's state: the small typed dictionary every node reads and updates.

How LangGraph uses it: each node receives the current state and returns a dict of only the fields it
wants to change. LangGraph merges that dict into the state. For most fields "merge" means "replace";
`messages` is special — its *reducer* (`add_messages`) appends new messages instead of replacing
the whole list, so a node returns {"messages": [new_reply]} and the history is kept.

Per-turn fields (verdict, flag) describe the CURRENT message only. The checkpointer saves state
between turns, so api.py resets them to None at the start of every turn — otherwise a node could
read last turn's verdict by mistake. #33 removed `intent` and `decision`: the agent node now reasons
about both inside its one model call instead of writing them to state for a later node to read.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class Verdict(TypedDict):
    """A safety check's result for this turn, written by before_model, and overwritten by the agent
    node only when it calls report_unsafe (#33).

    status  "pass" or "blocked" — the conditional edges route on this
    rule    None when passed; else which check blocked it, e.g. "size", "ignore-instructions",
            "agent-injection", "agent-harmful"
    reason  one readable sentence, shown in the trace panel
    """

    status: Literal["pass", "blocked"]
    rule: str | None
    reason: str


class ChatState(TypedDict):
    """Everything the graph knows about one chat (one LangGraph thread).

    messages  the conversation, oldest first; `add_messages` appends (see file header)
    verdict   this turn's safety result (Verdict), or None before before_model runs
    flag      why the local classifier flagged this turn, e.g. "classifier 0.97" (#8); None = not
              flagged. Set by before_model, read by the agent node (nodes/hook_points.py § 7.2).
    tool_call_blocked whether `before_tool` rejected the latest model tool request; None before a
              tool call, then reset on the next request. Used to route rejected calls around ToolNode.
    web_search_calls number of search requests attempted during this turn; reset at each user turn
              and capped so one model loop cannot spend the search allowance indefinitely.
    approval_calls the tool calls waiting for the owner's approval (#66), each {"id", "tool", "args",
              "reason"}; None when nothing waits. Written by before_tool, cleared by the approval
              node once the owner has answered.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    verdict: Verdict | None
    flag: str | None
    tool_call_blocked: bool | None
    web_search_calls: int
    approval_calls: list[dict] | None
