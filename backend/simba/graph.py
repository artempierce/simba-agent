"""
graph.py — wires Simba's nodes into a LangGraph StateGraph.

Where it sits: api.py calls `build_graph(model, checkpointer)` once at startup and keeps the
compiled graph on `app.state.graph`; every chat turn runs through it via `graph.astream(...)`.

Key idea: the graph is only a map of "who runs next". Each node does one job and writes its result
into the state; *conditional edges* — routing functions LangGraph calls after a node to pick the
next node by name — read that result and choose the path:

    START -> before_model -+- pass -> agent -+- text reply -> after_model -> END
                           +- blocked -> refuse    +- web_search -> tools -> agent (loop)
                                                  +- report_unsafe -> refuse -> END

    before_model  hooks (harness/settings.py's before_model_hooks): size, injection regex,   nodes/hook_points.py
                                local classifier — code + one local model call, $0 (#32, was "guard")
    agent         LLM: answers, calls report_unsafe, or requests web_search (#17, #33)       nodes/agent.py
    tools         runs allowlisted web_search between before/after hooks (#17)                langgraph ToolNode
  after_model   hooks (harness/settings.py's AFTER_MODEL): checks on the finished reply;    nodes/hook_points.py
                retracts leaks, $0 (#15, #32, was "output_guard")
  refuse        fixed reply, no model, $0                                                    nodes/refuse.py

The MVP was drawn one step at a time: step 1 was START -> echo -> END, step 2 added the guard,
step 3 the intent check, step 4 reason, step 5 replaced the echo placeholder with generate, #32
turned the guard/output_guard nodes into hook points, #33 merged intent/reason/generate into one
agent node, and #17 adds the first before_tool/tool/after_tool loop around read-only web search.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from simba.harness.classifier import InjectionClassifier
from simba.nodes import agent as agent_node
from simba.nodes.hook_points import after_model, before_tool, make_before_model
from simba.nodes.refuse import refuse
from simba.state import ChatState


def after_before_model(state: ChatState) -> str:
    """Routing function for the edge after `before_model`: "agent" if the message passed, else
    "refuse". It only reads the verdict `before_model` just wrote — the decision itself lives in
    harness/hooks.py and the hook functions, so the graph stays a plain map of "who runs next"."""
    return "agent" if state["verdict"]["status"] == "pass" else "refuse"


def after_agent(state: ChatState) -> str:
    """Route unsafe reports to refusal, tool calls to validation, and text to after_model."""
    if state["verdict"]["status"] != "pass":
        return "refuse"
    if getattr(state["messages"][-1], "tool_calls", []):
        return "before_tool"
    return "after_model"


def after_before_tool(state: ChatState) -> str:
    """Route a rejected call back to the agent; dispatch only calls that passed validation."""
    return "agent" if state["tool_call_blocked"] else "tools"


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    classifier: InjectionClassifier | None = None,
    web_search_tool: BaseTool | None = None,
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
        web_search_tool: the optional read-only Tavily tool. If present, only this tool and
            `ReportUnsafe` are exposed to the model; None means web search is unavailable.

    Returns: a compiled graph, ready for `.astream(...)` / `.ainvoke(...)`.

     Steps:
        1. Register the nodes by name. `agent` is built by its `make_node(model, tools)` factory;
            `before_model` is built by its own `make_before_model(classifier)` factory (#8, #32).
      2. START always goes to `before_model`.
      3. After `before_model`, `after_before_model` picks `agent` or `refuse` (a conditional edge).
        4. After `agent`, `after_agent` picks `after_model`, `refuse`, or the optional tool node.
        5. `before_tool` validates requested calls before `ToolNode` can execute them.
        6. A completed tool result loops back to `agent`; only plain text goes to after_model.
        7. Both `after_model` and `refuse` end the turn (refuse's fixed text needs no checking).
    """
    graph = StateGraph(ChatState)
    # 1. Nodes.
    graph.add_node("before_model", make_before_model(classifier))
    tools = [web_search_tool] if web_search_tool is not None else []
    graph.add_node("agent", agent_node.make_node(model, tools))
    graph.add_node("after_model", after_model)
    graph.add_node("refuse", refuse)
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_node("before_tool", before_tool)
    # 2. Every turn starts with the before_model hooks.
    graph.add_edge(START, "before_model")
    # 3. The list names every node `after_before_model` may return, so LangGraph can draw and check the graph.
    graph.add_conditional_edges("before_model", after_before_model, ["agent", "refuse"])
    # 4. The agent's own report_unsafe call gets the second say.
    destinations = ["after_model", "refuse"] + (["before_tool"] if tools else [])
    graph.add_conditional_edges("agent", after_agent, destinations)
    if tools:
        graph.add_conditional_edges("before_tool", after_before_tool, ["agent", "tools"])
        graph.add_edge("tools", "agent")
    # 7. Both terminal paths end the turn.
    graph.add_edge("after_model", END)
    graph.add_edge("refuse", END)
    return graph.compile(checkpointer=checkpointer)
