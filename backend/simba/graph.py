"""
graph.py — wires Simba's nodes into a LangGraph StateGraph.

Where it sits: api.py calls `build_graph(model, checkpointer)` once at startup and keeps the
compiled graph on `app.state.graph`; every chat turn runs through it via `graph.astream(...)`.

Key idea: the graph is drawn one step at a time. Step 1 was START -> echo -> END. Step 2 puts the
guard in front, with a *conditional edge* — a routing function LangGraph calls after a node to pick
the next node by name. Step 3 adds the LLM intent check as a second gate:

    START -> guard -+- pass -> intent -+- pass -> echo -> END
                    +- blocked -> refuse    +- blocked -> refuse -> END

Later steps (contracts.md § 8) replace `echo` with the real pipeline:

    START -> guard -+- pass -> intent -+- pass -> reason -> generate -> END
                    +- blocked -> refuse    +- blocked -> refuse -> END
"""

import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from simba.common import emit_trace, text_of
from simba.nodes import intent
from simba.nodes.guard import guard
from simba.nodes.refuse import refuse
from simba.state import ChatState


async def echo(state: ChatState) -> dict:
    """Step-1 placeholder node: reply with the newest human message, prefixed by "You said: ".

    Inputs:  state["messages"][-1] — this turn's HumanMessage (api.py resets the per-turn
             fields and appends it before running the graph; see contracts.md § 4).
    Outputs: {"messages": [AIMessage(...)]}, merged onto the state's message history by the
             `add_messages` reducer (state.py).
    Why: step 1 needs *something* to answer with so the SSE stream, trace panel and tests can
    be built now. It emits one trace line, like every node will (contracts.md § 6), so the
    trace panel and the `done` totals work the same way from day one.
    """
    start = time.perf_counter()
    text = text_of(state["messages"][-1])
    emit_trace("echo", "ok", f"echoed {len(text)} chars", start)
    return {"messages": [AIMessage(f"You said: {text}")]}


def after_guard(state: ChatState) -> str:
    """Routing function for the edge after `guard`: "intent" if the message passed, else "refuse".

    It only reads the verdict the guard just wrote — the decision itself lives in guard.py, so the
    graph stays a plain map of "who runs next".
    """
    return "intent" if state["verdict"]["status"] == "pass" else "refuse"


def after_intent(state: ChatState) -> str:
    """Routing function for the edge after `intent`: "echo" if the LLM check judged the message safe,
    else "refuse". The intent node overwrites the guard's verdict, so this reads the newest one."""
    return "echo" if state["verdict"]["status"] == "pass" else "refuse"


def build_graph(model: BaseChatModel, checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Build and compile Simba's graph.

    Args:
        model: the chat model the real nodes (intent, reason, generate — contracts.md § 7) will
               call once they land. `echo` doesn't use it, but `build_graph` takes it now so
               api.py's call site doesn't have to change shape when those nodes replace `echo`.
        checkpointer: where turn-by-turn state is saved between calls, keyed by thread_id; None
               compiles without one (fine for a single-turn test), api.py always passes an
               AsyncSqliteSaver so a chat remembers earlier turns.

    Returns: a compiled graph, ready for `.astream(...)` / `.ainvoke(...)`.

    Steps:
      1. Register the nodes by name. `intent` needs the model, so it's built by its factory.
      2. START always goes to `guard`.
      3. After `guard`, `after_guard` picks `intent` or `refuse` (a conditional edge).
      4. After `intent`, `after_intent` picks `echo` or `refuse`.
      5. Both `echo` and `refuse` end the turn.
    """
    graph = StateGraph(ChatState)
    # 1. Nodes.
    graph.add_node("guard", guard)
    graph.add_node("intent", intent.make_node(model))
    graph.add_node("refuse", refuse)
    graph.add_node("echo", echo)
    # 2. Every turn starts with the code guard.
    graph.add_edge(START, "guard")
    # 3. The list names every node `after_guard` may return, so LangGraph can draw and check the graph.
    graph.add_conditional_edges("guard", after_guard, ["intent", "refuse"])
    # 4. The LLM safety check gets the second say.
    graph.add_conditional_edges("intent", after_intent, ["echo", "refuse"])
    # 5. Both paths end the turn.
    graph.add_edge("echo", END)
    graph.add_edge("refuse", END)
    return graph.compile(checkpointer=checkpointer)
