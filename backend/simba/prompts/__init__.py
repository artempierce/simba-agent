"""
prompts — Simba's procedural memory: plain-text instructions.

  system.md   who Simba is, how it talks, and its safety rules — the only prompt, used by the
              agent node (#33 merged intent.md's safety rules into it and deleted reason.md)

It is a Markdown file, not a Python string, so you can tune Simba without touching code. `load()`
reads the file on every call, so an edit takes effect on the next message without restarting.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Return the text of prompts/<name>.md, e.g. load("system").

    Raises FileNotFoundError for an unknown name — a typo should fail loudly, not send an empty prompt.
    """
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
