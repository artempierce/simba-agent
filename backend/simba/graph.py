"""
graph.py — wires Simba's nodes into a LangGraph StateGraph.

Where it sits: api.py calls `build_graph(model, checkpointer)` once at startup and keeps the
compiled graph on `app.state.graph`; every chat turn runs through it via `graph.astream(...)`.

Key idea: the graph is only a map of "who runs next". Each node does one job and writes its result
into the state; *conditional edges* — routing functions LangGraph calls after a node to pick the
next node by name — read that result and choose the path:

    START -> guard -+- pass -> intent -+- pass -> reason -> generate -> output_guard -> END
                    +- blocked -> refuse    +- blocked -> refuse -> END

  guard         code rules (size + injection patterns) + local classifier, $0   nodes/guard.py
  intent        LLM: restate the request + safety verdict (second gate)         nodes/intent.py
  reason        LLM: choose the action (answer / clarify) and plan it            nodes/reason.py
  generate      LLM: write the reply, streamed to the browser                    nodes/generate.py
  output_guard  code checks on the finished reply; retracts leaks, $0 (#15)      nodes/output_guard.py
  refuse        fixed reply, no model, $0                                         nodes/refuse.py

The MVP was drawn one step at a time: step 1 was START -> echo -> END, step 2 added the guard,
step 3 the intent check, step 4 reason, and step 5 replaced the echo placeholder with generate.
When tools arrive, `reason` gains a "use_tool" action and a loop through a tools node
(design book → What "reason" means); nothing else here changes.
"""

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from simba.classifier import InjectionClassifier
from simba.nodes import generate, guard, intent, reason
from simba.nodes.output_guard import output_guard
from simba.nodes.refuse import refuse
from simba.state import ChatState


def after_guard(state: ChatState) -> str:
    """Routing function for the edge after `guard`: "intent" if the message passed, else "refuse".

    It only reads the verdict the guard just wrote — the decision itself lives in guard.py, so the
    graph stays a plain map of "who runs next".
    """
    return "intent" if state["verdict"]["status"] == "pass" else "refuse"


def after_intent(state: ChatState) -> str:
    """Routing function for the edge after `intent`: "reason" if the LLM check judged the message
    safe, else "refuse". The intent node overwrites the guard's verdict, so this reads the newest one."""
    return "reason" if state["verdict"]["status"] == "pass" else "refuse"


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    classifier: InjectionClassifier | None = None,
) -> CompiledStateGraph:
    """Build and compile Simba's graph.

    Args:
        model: the chat model the LLM nodes (intent, reason, generate) call. Passed in, never created
               here, so tests can hand in the free fake model (model.py).
        checkpointer: where turn-by-turn state is saved between calls, keyed by thread_id; None
               compiles without one (fine for a single-turn test), api.py always passes an
               AsyncSqliteSaver so a chat remembers earlier turns.
        classifier: the guard's local prompt-injection classifier (#8, classifier.py); None turns
               that half of the guard off. Passed straight through to `guard.make_node`.

    Returns: a compiled graph, ready for `.astream(...)` / `.ainvoke(...)`.

    Steps:
      1. Register the nodes by name. The LLM nodes are built by their `make_node(model)` factories;
         the guard node is built by its own `make_node(classifier)` factory (#8).
      2. START always goes to `guard`.
      3. After `guard`, `after_guard` picks `intent` or `refuse` (a conditional edge).
      4. After `intent`, `after_intent` picks `reason` or `refuse`.
      5. `reason` always goes on to `generate` (a plain edge: there's only one way forward today).
      6. Every generated reply is checked by `output_guard` (#15) before the turn ends.
      7. Both `output_guard` and `refuse` end the turn (refuse's fixed text needs no checking).
    """
    graph = StateGraph(ChatState)
    # 1. Nodes.
    graph.add_node("guard", guard.make_node(classifier))
    graph.add_node("intent", intent.make_node(model))
    graph.add_node("reason", reason.make_node(model))
    graph.add_node("generate", generate.make_node(model))
    graph.add_node("output_guard", output_guard)
    graph.add_node("refuse", refuse)
    # 2. Every turn starts with the code guard.
    graph.add_edge(START, "guard")
    # 3. The list names every node `after_guard` may return, so LangGraph can draw and check the graph.
    graph.add_conditional_edges("guard", after_guard, ["intent", "refuse"])
    # 4. The LLM safety check gets the second say.
    graph.add_conditional_edges("intent", after_intent, ["reason", "refuse"])
    # 5. Plan, then reply.
    graph.add_edge("reason", "generate")
    # 6. Check what Simba wrote.
    graph.add_edge("generate", "output_guard")
    # 7. Both paths end the turn.
    graph.add_edge("output_guard", END)
    graph.add_edge("refuse", END)
    return graph.compile(checkpointer=checkpointer)
