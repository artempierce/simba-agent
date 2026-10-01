"""
tests/test_skills.py — skills: the file format, the load_skill tool, the prompt index, a full turn (#95, D53).

Skills are instructions Simba follows, so the rules that keep them safe and tidy are pinned here:
every shipped skill is valid, a broken file fails loudly with its name, a name can never be a path,
a body can't break out of its <skill> fence, and loading one shows in the trace. All on the fake
model; $0.
"""

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from simba.model import fake_model
from simba.nodes.agent import make_node, skills_block
from simba.skills import SKILLS_DIR, Skill, SkillError, list_skills, parse_skill, read_skill
from simba.tools.skill_tools import MANIFEST, make_skill_tools
from tests.node_harness import run_node
from tests.test_api import parse_sse, running_app


def write_skill(folder: Path, name: str, text: str) -> Path:
    """Write `text` as folder/<name>.md and return the path."""
    path = folder / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


async def call_load_skill(name: str) -> tuple[str, list[dict]]:
    """Run load_skill inside a one-node graph (its trace line needs LangGraph's stream writer) and
    return (what the model would read, the trace lines)."""
    (load_skill,) = make_skill_tools()
    result: list[str] = []

    async def node(_state):
        result.append(await load_skill.ainvoke({"name": name}))
        return {}

    _, traces = await run_node(node, {})
    return result[0], traces


GOOD = "---\nname: tidy-notes\ndescription: Turn messy notes into a short list\n---\n1. Group the notes.\n"


# ---- the file format ----

def test_every_shipped_skill_is_valid():
    """Each skill in simba/skills/ parses — so a PR that adds a broken skill fails CI, not a chat."""
    skills = list_skills()
    assert "explain-concept" in [s.name for s in skills]
    assert all(s.body for s in skills)


def test_a_valid_skill_parses(tmp_path):
    """Name, description and body come out of the file as written."""
    skill = parse_skill(write_skill(tmp_path, "tidy-notes", GOOD))
    assert skill == Skill("tidy-notes", "Turn messy notes into a short list", "1. Group the notes.")


@pytest.mark.parametrize("name,text,message", [
    ("no-front", "Just a body\n", "front matter"),
    ("other-name", GOOD, "match the file name"),
    ("Bad_Name", GOOD.replace("tidy-notes", "Bad_Name"), "lowercase-with-dashes"),
    ("no-desc", "---\nname: no-desc\n---\nbody\n", "description"),
    ("long-desc", f"---\nname: long-desc\ndescription: {'x' * 201}\n---\nbody\n", "longer than 200"),
    ("empty", "---\nname: empty\ndescription: Nothing inside\n---\n\n", "no body"),
    ("bad-yaml", "---\nname: [unclosed\n---\nbody\n", "valid YAML"),
])
def test_a_broken_skill_fails_loudly_naming_the_file(tmp_path, name, text, message):
    """Every way a skill file can be wrong raises SkillError with the file's name and the reason."""
    with pytest.raises(SkillError, match=message) as error:
        parse_skill(write_skill(tmp_path, name, text))
    assert f"{name}.md" in str(error.value)


def test_a_skill_name_can_never_be_a_path(tmp_path):
    """read_skill checks the name's shape before touching a file, so "../" tricks find nothing."""
    write_skill(tmp_path, "tidy-notes", GOOD)
    assert read_skill("tidy-notes", tmp_path).name == "tidy-notes"
    assert read_skill("../prompts/system", tmp_path) is None
    assert read_skill("missing", tmp_path) is None


# ---- the load_skill tool ----

async def test_load_skill_returns_the_body_fenced_and_traced():
    """The body comes back inside <skill> tags, and the trace shows which skill was loaded."""
    result, traces = await call_load_skill("explain-concept")
    assert result.startswith('<skill name="explain-concept">') and result.endswith("</skill>")
    assert "one plain definition" in result
    assert traces[0]["stage"] == "load_skill" and traces[0]["detail"] == "skill · explain-concept"


async def test_load_skill_with_an_unknown_name_lists_the_real_ones():
    """A wrong name isn't an error the model can't recover from: it gets the list of real skills."""
    result, traces = await call_load_skill("nope")
    assert result.startswith("No skill called 'nope'.") and "explain-concept" in result
    assert traces[0]["status"] == "error"


def test_load_skill_manifest_is_read_only_and_needs_no_approval():
    """Reading a reviewed file in the repo changes nothing, so it's a plain read tool (#65)."""
    assert (MANIFEST.access, MANIFEST.needs_approval, MANIFEST.enabled, MANIFEST.hosts) == ("read", False, True, ())


# ---- the prompt index ----

def test_skills_block_lists_names_and_descriptions_only():
    """The prompt gets one line per skill; the body stays out until load_skill is called."""
    block = skills_block([Skill("tidy-notes", "Turn messy notes into a short list", "SECRET BODY")])
    assert "- tidy-notes: Turn messy notes into a short list" in block and "SECRET BODY" not in block
    assert skills_block([]) == ""


async def test_the_agent_prompt_has_the_index_only_when_load_skill_is_offered():
    """With load_skill among the tools the system prompt lists the skills; without it, it doesn't."""
    with_skills, without = fake_model(), fake_model()
    await run_node(make_node(with_skills, make_skill_tools()), {"messages": [HumanMessage("hi")]})
    await run_node(make_node(without), {"messages": [HumanMessage("hi")]})
    assert "- explain-concept:" in with_skills.calls[0][0].content
    assert "Skills (load one" not in without.calls[0][0].content


# ---- a whole turn through the API ----

async def test_a_turn_loads_a_skill_and_the_model_reads_it(tmp_path):
    """End to end on the fake model: the model asks for explain-concept, before_tool allows it, the
    body reaches the model's next call, the trace shows the load, and the answer arrives."""
    model = fake_model(reply="An embedding is a list of numbers.",
                       structured={"load_skill": {"name": "explain-concept"}})
    async with running_app(model=model, db_path=str(tmp_path / "t.db")) as (app, client):
        events = parse_sse((await client.post("/api/chat", json={"message": "What is an embedding?"})).text)
        info = (await client.get("/api/info")).json()

    tool_reply = next(m for m in model.calls[-1] if m.type == "tool")
    assert tool_reply.content.startswith('<skill name="explain-concept">')
    stages = [d["stage"] for e, d in events if e == "trace"]
    assert stages == ["before_model", "agent", "before_tool", "load_skill", "agent", "after_model"]
    assert "".join(d["text"] for e, d in events if e == "token") == "An embedding is a list of numbers."
    assert {"name": "explain-concept", "description": list_skills()[0].description} in info["skills"]
    assert "load_skill" in [t["name"] for t in info["tools"]]


def test_skills_live_next_to_the_loader():
    """SKILLS_DIR is the package folder, so a new skill is just a new .md file there."""
    assert (SKILLS_DIR / "explain-concept.md").is_file()
