"""
graph.py — wires Simba's nodes into a LangGraph StateGraph.

Where it sits: api.py calls `build_graph(model, checkpointer)` once at startup and keeps the
compiled graph on `app.state.graph`; every chat turn runs through it via `graph.astream(...)`.

Key idea: the graph is only a map of "who runs next". Each node does one job and writes its result
into the state; *conditional edges* — routing functions LangGraph calls after a node to pick the
next node by name — read that result and choose the path:

    START -> before_model -+- pass -> intent -+- pass -> reason -> generate -> after_model -> END
                           +- blocked -> refuse    +- blocked -> refuse -> END

  before_model  hooks (harness/settings.py's before_model_hooks): size, injection regex,   nodes/hook_points.py
                local classifier — code + one local model call, $0 (#32, was "guard")
  intent        LLM: restate the request + safety verdict (second gate)                    nodes/intent.py
  reason        LLM: choose the action (answer / clarify) and plan it                       nodes/reason.py
  generate      LLM: write the reply, streamed to the browser                               nodes/generate.py
  after_model   hooks (harness/settings.py's AFTER_MODEL): checks on the finished reply;    nodes/hook_points.py
                retracts leaks, $0 (#15, #32, was "output_guard")
  refuse        fixed reply, no model, $0                                                    nodes/refuse.py

The MVP was drawn one step at a time: step 1 was START -> echo -> END, step 2 added the guard,
step 3 the intent check, step 4 reason, step 5 replaced the echo placeholder with generate, and #32
turned the guard/output_guard nodes into hook points wired from harness/settings.py. When tools
arrive, `reason` gains a "use_tool" action and a loop through a tools node (design book → What
"reason" means); nothing else here changes.
"""

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from simba.harness.classifier import InjectionClassifier
from simba.nodes import generate, intent, reason
from simba.nodes.hook_points import after_model, make_before_model
from simba.nodes.refuse import refuse
from simba.state import ChatState


def after_before_model(state: ChatState) -> str:
    """Routing function for the edge after `before_model`: "intent" if the message passed, else
    "refuse". It only reads the verdict `before_model` just wrote — the decision itself lives in
    harness/hooks.py and the hook functions, so the graph stays a plain map of "who runs next"."""
    return "intent" if state["verdict"]["status"] == "pass" else "refuse"


def after_intent(state: ChatState) -> str:
    """Routing function for the edge after `intent`: "reason" if the LLM check judged the message
    safe, else "refuse". The intent node overwrites `before_model`'s verdict, so this reads the
    newest one."""
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
        classifier: the local prompt-injection classifier (#8, harness/classifier.py); None turns
               that hook off. Passed straight through to `hook_points.make_before_model`.

    Returns: a compiled graph, ready for `.astream(...)` / `.ainvoke(...)`.

    Steps:
      1. Register the nodes by name. The LLM nodes are built by their `make_node(model)` factories;
         `before_model` is built by its own `make_before_model(classifier)` factory (#8, #32).
      2. START always goes to `before_model`.
      3. After `before_model`, `after_before_model` picks `intent` or `refuse` (a conditional edge).
      4. After `intent`, `after_intent` picks `reason` or `refuse`.
      5. `reason` always goes on to `generate` (a plain edge: there's only one way forward today).
      6. Every generated reply is checked by `after_model` (#15, #32) before the turn ends.
      7. Both `after_model` and `refuse` end the turn (refuse's fixed text needs no checking).
    """
    graph = StateGraph(ChatState)
    # 1. Nodes.
    graph.add_node("before_model", make_before_model(classifier))
    graph.add_node("intent", intent.make_node(model))
    graph.add_node("reason", reason.make_node(model))
    graph.add_node("generate", generate.make_node(model))
    graph.add_node("after_model", after_model)
    graph.add_node("refuse", refuse)
    # 2. Every turn starts with the before_model hooks.
    graph.add_edge(START, "before_model")
    # 3. The list names every node `after_before_model` may return, so LangGraph can draw and check the graph.
    graph.add_conditional_edges("before_model", after_before_model, ["intent", "refuse"])
    # 4. The LLM safety check gets the second say.
    graph.add_conditional_edges("intent", after_intent, ["reason", "refuse"])
    # 5. Plan, then reply.
    graph.add_edge("reason", "generate")
    # 6. Check what Simba wrote.
    graph.add_edge("generate", "after_model")
    # 7. Both paths end the turn.
    graph.add_edge("after_model", END)
    graph.add_edge("refuse", END)
    return graph.compile(checkpointer=checkpointer)
