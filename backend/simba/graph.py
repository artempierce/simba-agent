"""
graph.py — wires Simba's nodes into a LangGraph StateGraph.

Where it sits: api.py calls `build_graph(model, checkpointer)` once at startup and keeps the
compiled graph on `app.state.graph`; every chat turn runs through it via `graph.astream(...)`.

Key idea: the graph is only a map of "who runs next". Each node does one job and writes its result
into the state; *conditional edges* — routing functions LangGraph calls after a node to pick the
next node by name — read that result and choose the path:

    START -> before_model -+- pass -> agent -+- text reply -> after_model -> END
                           +- blocked -> refuse    +- report_unsafe -> refuse -> END

  before_model  hooks (harness/settings.py's before_model_hooks): size, injection regex,   nodes/hook_points.py
                local classifier — code + one local model call, $0 (#32, was "guard")
  agent         LLM: one call that answers, or calls report_unsafe (second gate) (#33)      nodes/agent.py
  after_model   hooks (harness/settings.py's AFTER_MODEL): checks on the finished reply;    nodes/hook_points.py
                retracts leaks, $0 (#15, #32, was "output_guard")
  refuse        fixed reply, no model, $0                                                    nodes/refuse.py

The MVP was drawn one step at a time: step 1 was START -> echo -> END, step 2 added the guard,
step 3 the intent check, step 4 reason, step 5 replaced the echo placeholder with generate, #32
turned the guard/output_guard nodes into hook points wired from harness/settings.py, and #33 merged
intent/reason/generate into the single `agent` node above. When tools arrive, `agent` gains a
conditional edge to a tools node and back — the ReAct loop (design book → Tools and subagents later);
nothing else here changes.
"""

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from simba.harness.classifier import InjectionClassifier
from simba.nodes import agent as agent_node
from simba.nodes.hook_points import after_model, make_before_model
from simba.nodes.refuse import refuse
from simba.state import ChatState


def after_before_model(state: ChatState) -> str:
    """Routing function for the edge after `before_model`: "agent" if the message passed, else
    "refuse". It only reads the verdict `before_model` just wrote — the decision itself lives in
    harness/hooks.py and the hook functions, so the graph stays a plain map of "who runs next"."""
    return "agent" if state["verdict"]["status"] == "pass" else "refuse"


def after_agent(state: ChatState) -> str:
    """Routing function for the edge after `agent`: "after_model" for a normal reply, else "refuse"
    when the model called `report_unsafe` instead. The agent node overwrites `before_model`'s
    verdict only on a report_unsafe call, so this reads the newest one."""
    return "after_model" if state["verdict"]["status"] == "pass" else "refuse"


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    classifier: InjectionClassifier | None = None,
) -> CompiledStateGraph:
    """Build and compile Simba's graph.

    Args:
        model: the chat model the agent node calls. Passed in, never created here, so tests can
               hand in the free fake model (model.py).
        checkpointer: where turn-by-turn state is saved between calls, keyed by thread_id; None
               compiles without one (fine for a single-turn test), api.py always passes an
               AsyncSqliteSaver so a chat remembers earlier turns.
        classifier: the local prompt-injection classifier (#8, harness/classifier.py); None turns
               that hook off. Passed straight through to `hook_points.make_before_model`.

    Returns: a compiled graph, ready for `.astream(...)` / `.ainvoke(...)`.

    Steps:
      1. Register the nodes by name. `agent` is built by its `make_node(model)` factory;
         `before_model` is built by its own `make_before_model(classifier)` factory (#8, #32).
      2. START always goes to `before_model`.
      3. After `before_model`, `after_before_model` picks `agent` or `refuse` (a conditional edge).
      4. After `agent`, `after_agent` picks `after_model` (a normal reply) or `refuse`
         (`report_unsafe`).
      5. Both `after_model` and `refuse` end the turn (refuse's fixed text needs no checking).
    """
    graph = StateGraph(ChatState)
    # 1. Nodes.
    graph.add_node("before_model", make_before_model(classifier))
    graph.add_node("agent", agent_node.make_node(model))
    graph.add_node("after_model", after_model)
    graph.add_node("refuse", refuse)
    # 2. Every turn starts with the before_model hooks.
    graph.add_edge(START, "before_model")
    # 3. The list names every node `after_before_model` may return, so LangGraph can draw and check the graph.
    graph.add_conditional_edges("before_model", after_before_model, ["agent", "refuse"])
    # 4. The agent's own report_unsafe call gets the second say.
    graph.add_conditional_edges("agent", after_agent, ["after_model", "refuse"])
    # 5. Both paths end the turn.
    graph.add_edge("after_model", END)
    graph.add_edge("refuse", END)
    return graph.compile(checkpointer=checkpointer)
