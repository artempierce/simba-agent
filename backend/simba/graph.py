"""
graph.py — wires Simba's nodes into a LangGraph StateGraph.

Where it sits: api.py calls `build_graph(model, checkpointer)` once at startup and keeps the
compiled graph on `app.state.graph`; every chat turn runs through it via `graph.astream(...)`.

Key idea, step 1: the graph is just START -> echo -> END, so the chat UI, SSE streaming and
trace panel can all be built and tested before any real thinking node exists. Later steps
(contracts.md § 8) replace `echo` with the real pipeline:

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
    """
    graph = StateGraph(ChatState)
    graph.add_node("echo", echo)
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)
    return graph.compile(checkpointer=checkpointer)
