"""
prompts — Simba's procedural memory: plain-text instructions, one file per job.

  system.md   who Simba is and how it talks — used by the generate node
  intent.md   how to restate and safety-check a message — used by the intent node
  reason.md   how to choose an action and plan — used by the reason node

They are Markdown files, not Python strings, so you can tune Simba without touching code. `load()`
reads the file on every call, so an edit takes effect on the next message without restarting.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Return the text of prompts/<name>.md, e.g. load("system").

    Raises FileNotFoundError for an unknown name — a typo should fail loudly, not send an empty prompt.
    """
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
