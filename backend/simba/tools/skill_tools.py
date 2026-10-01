"""
skill_tools.py — the `load_skill` tool: how Simba reads one skill's full procedure (#95, D53).

Where it sits: bound to the agent next to web_search and the memory tools. The system prompt lists
every skill's name and description (nodes/agent.py `skills_block`); when a task matches one, the
model calls load_skill(name) and gets the body back. Like every tool call it goes agent →
before_tool (code checks) → tools → agent, so it shows in the trace.

Key idea: a skill is a file in the repo that came in through a reviewed PR, so it's Simba's own
instruction text — not untrusted data like a web page. That's why loading one doesn't count as
"read untrusted content" (nodes/hook_points.py only counts web_search results), and why its manifest
is read-only with no approval.
"""

import time

from langchain_core.tools import BaseTool, tool

from simba.common import emit_trace, neutralise_tag
from simba.skills import list_skills, read_skill
from simba.tools.registry import ToolManifest, declare

# #65: load_skill only reads files in simba/skills/: read-only, local, free, no approval. No per-turn
# limit: today only web_search's limit is enforced in code, so setting one here would promise
# something nothing checks. LangGraph's step limit (25 steps a turn) still stops a looping model.
MANIFEST = ToolManifest(access="read", enabled=True)


def make_skill_tools() -> list[BaseTool]:
    """Build the skill tools (just load_skill for now), declared with MANIFEST.

    Why a list from a factory: graph.py and api.py take tools in lists, the same way as the memory
    tools, so wiring a new kind of tool doesn't need a new code path.
    """

    # The docstring below is what the model reads as the tool's description.
    @tool("load_skill")
    async def load_skill(name: str) -> str:
        """Load one of your skills by name (from the "Skills" list in your instructions) and follow it.

        name: the skill's name exactly as listed, e.g. "explain-concept".
        """
        started = time.perf_counter()
        # 1. Find the skill. An unknown name gets the list of real ones, so the model can correct itself.
        skill = read_skill(name)
        if skill is None:
            names = ", ".join(s.name for s in list_skills()) or "none"
            emit_trace("load_skill", "error", f"no skill · {name}"[:80], started)
            return f"No skill called {name!r}. Available: {names}."
        # 2. Return the body fenced in <skill> tags, escaped so a body can't close the fence early.
        emit_trace("load_skill", "ok", f"skill · {skill.name}"[:80], started)
        return f'<skill name="{skill.name}">\n{neutralise_tag(skill.body, "skill")}\n</skill>'

    return [declare(load_skill, MANIFEST)]
