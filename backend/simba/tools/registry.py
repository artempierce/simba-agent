"""
registry.py — the tool permission manifests and the registry that loads tools from them (#65, D34).

Where it sits: every tool file (tools/web_search.py, tools/memory_tools.py) declares a `ToolManifest`
and attaches it to its LangChain tool with `declare`. graph.py builds a `ToolRegistry` from the tools
it is given; before_tool (nodes/hook_points.py) looks each model-requested call up in it, and the
`allowlisted_tool_call` hook denies a call whose tool has no manifest or is switched off. The registry
also feeds `GET /api/info` and the trace line, so the owner can see what each tool may do.

Key idea: least privilege, enforced in code (D34). A tool is allowed only because its manifest says so;
a tool nobody declared simply isn't in the registry, so it is denied — the model can't talk its way in.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from langchain_core.tools import BaseTool

# Where a tool's manifest lives on the LangChain tool: BaseTool.metadata is a free-form dict that
# LangChain passes along but never reads, so it is a safe place to carry our own field.
MANIFEST_KEY = "manifest"


@dataclass(frozen=True)
class ToolManifest:
    """What one tool may do. Frozen, so a tool can't loosen its own manifest at run time.

    access              "read" (looks things up) or "write" (changes something). #66's approval rule
                        reads this: a write tool needs the owner's approval after untrusted content.
    hosts               network hosts the tool talks to. Shown to the owner; not enforced (#65: the one
                        host, api.tavily.com, is fixed inside langchain-tavily).
    cost_per_call       plain words for the owner, e.g. "1 Tavily credit". Shown only; no budget on it yet.
    max_calls_per_turn  most calls one turn may make, or None for no limit. Enforced in code.
    needs_approval      the owner must approve each call (#66 builds the pause; nothing sets it yet).
    enabled             False = denied in code. A new manifest starts switched off (design book
                        § Permissions) until someone sets True on purpose.
    """

    access: Literal["read", "write"]
    hosts: tuple[str, ...] = ()
    cost_per_call: str = "free"
    max_calls_per_turn: int | None = None
    needs_approval: bool = False
    enabled: bool = False

    def summary(self, name: str) -> str:
        """One line for the trace panel, e.g. "web_search · read · no approval"."""
        return f"{name} · {self.access} · {'needs approval' if self.needs_approval else 'no approval'}"


def declare(tool: BaseTool, manifest: ToolManifest) -> BaseTool:
    """Attach `manifest` to `tool` and return the tool, so a tool file can end with `declare(tool, M)`."""
    tool.metadata = {**(tool.metadata or {}), MANIFEST_KEY: manifest}
    return tool


class ToolRegistry:
    """Name -> manifest for the tools a graph was built with. Anything not in it is denied.

    Why built from the tools rather than a separate list: the registry can't disagree with what the
    model is offered. A tool without a manifest never gets in, whatever the model asks for.

    Example: ToolRegistry.from_tools([web_search]).manifest("web_search").access == "read";
    ToolRegistry.from_tools([web_search]).manifest("shell") is None.
    """

    def __init__(self, manifests: dict[str, ToolManifest]):
        self._manifests = dict(manifests)

    @classmethod
    def from_tools(cls, tools: list[BaseTool]) -> "ToolRegistry":
        """Register each tool that carries a manifest; skip the rest (they stay undeclared = denied)."""
        return cls({t.name: t.metadata[MANIFEST_KEY] for t in tools if MANIFEST_KEY in (t.metadata or {})})

    def manifest(self, name: str) -> ToolManifest | None:
        """The manifest for `name`, or None when the tool is undeclared."""
        return self._manifests.get(name)

    def max_calls(self, name: str) -> int | None:
        """The tool's per-turn call limit (None = no limit, or an undeclared tool)."""
        found = self.manifest(name)
        return found.max_calls_per_turn if found else None

    def describe(self) -> list[dict]:
        """The registry as plain dicts for `GET /api/info`: name plus every manifest field."""
        return [{"name": name, **asdict(m), "hosts": list(m.hosts)} for name, m in self._manifests.items()]
