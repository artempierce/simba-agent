"""
skills — Simba's skills: markdown procedures it reads when a task needs one (#95, D37, D53).

Where it sits: each skill is one file here, `<name>.md`, added by the owner in a reviewed PR (Simba
never writes one in this phase). The agent node (nodes/agent.py) puts every skill's name and
description in the system prompt as a short index; when a task matches, the model calls the
`load_skill` tool (tools/skill_tools.py), which reads the body with `read_skill`.

Key idea: progressive disclosure, as in Claude Code's skills. The prompt carries only one line per
skill, so it stays small however many skills exist; the full procedure is read only when it's needed.

A skill file looks like this — "front matter" is the YAML block between the two `---` lines:

    ---
    name: explain-concept
    description: Explain an idea or term the user wants to understand
    ---
    1. Give one plain definition ...

A skill is text only: it can't switch tools on or grant permissions (tool manifests decide that, #65).
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).parent

# A skill's name is also its file name and what the model passes to load_skill: lowercase words
# joined by dashes, e.g. "explain-concept". Nothing else, so a name can never be a path.
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# The description goes into every prompt, so it must stay one short line.
MAX_DESCRIPTION_CHARS = 200


class SkillError(ValueError):
    """A skill file breaks the format above. The message names the file, so the fix is obvious."""


@dataclass(frozen=True)
class Skill:
    """One skill: `name` and `description` from the front matter, `body` is the procedure itself."""

    name: str
    description: str
    body: str


def parse_skill(path: Path) -> Skill:
    """Read and check one skill file.

    1. Split the text into front matter and body (the file must start with a `---` line).
    2. Read the front matter with `yaml.safe_load` (safe_load builds only plain data, never objects).
    3. Check it: the name is a slug and matches the file name; the description is 1–200 characters
       on one line; the body isn't empty. Any break raises SkillError naming the file.

    Example: parse_skill(Path("explain-concept.md")).name == "explain-concept"
    """
    # 1.
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        raise SkillError(f"{path.name}: must start with front matter between two '---' lines")
    _, front, body = parts
    # 2.
    try:
        meta = yaml.safe_load(front)
    except yaml.YAMLError as exc:
        raise SkillError(f"{path.name}: front matter isn't valid YAML ({exc})") from exc
    if not isinstance(meta, dict):
        raise SkillError(f"{path.name}: front matter must have name and description")
    # 3.
    name, description, body = meta.get("name"), meta.get("description"), body.strip()
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name) or name != path.stem:
        raise SkillError(f"{path.name}: name must be lowercase-with-dashes and match the file name")
    if not isinstance(description, str) or not description.strip() or "\n" in description.strip():
        raise SkillError(f"{path.name}: description must be one line of text")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise SkillError(f"{path.name}: description is longer than {MAX_DESCRIPTION_CHARS} characters")
    if not body:
        raise SkillError(f"{path.name}: the skill has no body")
    return Skill(name=name, description=description.strip(), body=body)


def list_skills(skills_dir: Path = SKILLS_DIR) -> list[Skill]:
    """Every skill in `skills_dir`, sorted by name. Read fresh on every call (like prompts.load), so
    an edited skill counts on the next message without a restart. A bad file raises SkillError: a
    broken skill should fail loudly in the tests, not quietly vanish from the prompt."""
    return [parse_skill(path) for path in sorted(skills_dir.glob("*.md"))]


def read_skill(name: str, skills_dir: Path = SKILLS_DIR) -> Skill | None:
    """The skill called `name`, or None when there's no such skill. The name is checked against
    NAME_PATTERN before any file is touched, so "../system" can't read a file outside this folder."""
    if not NAME_PATTERN.fullmatch(name):
        return None
    return next((skill for skill in list_skills(skills_dir) if skill.name == name), None)
