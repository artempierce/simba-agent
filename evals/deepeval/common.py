"""
common.py — settings shared by benchmark.py and redteam.py (#72, #73): which Claude models judge and
attack, where results are saved, the targets, and the "plan first, pay only with --run" guard.

Key ideas:
- DeepEval and DeepTeam default to OpenAI models (gpt-4o-mini, gpt-4o) for judging and for writing
  attacks. Simba is a Claude project with no OpenAI key, so every metric, vulnerability and attack
  gets an explicit Claude model from here — never the library default.
- Telemetry off: both libraries report usage to their vendor unless told not to. The two opt-out
  variables are set here, before either library is imported.
- Every run costs money (Simba's own model, the judge, the attacker), so a script prints its plan and
  a rough call count and stops, unless it was started with --run (CLAUDE.md's cost rule).
"""

import os
import subprocess
from pathlib import Path

import yaml

# Must happen before `import deepeval` / `import deepteam` anywhere in the process.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPTEAM_TELEMETRY_OPT_OUT", "YES")

HERE = Path(__file__).resolve().parent
EVALS_DIR = HERE.parent  # the repo's evals/ folder (case files live there)
TARGETS_FILE = HERE / "targets.yaml"

# The judge grades answers; a different, stronger model than Simba's own, as in the search and
# safety evals (D32). The attacker writes attacks for red teaming: Sonnet is cheaper and good at it.
# Both can be changed per run with environment variables, e.g. SIMBA_EVAL_JUDGE=claude-sonnet-5-5.
JUDGE_MODEL = os.getenv("SIMBA_EVAL_JUDGE", "claude-opus-5-5")
ATTACKER_MODEL = os.getenv("SIMBA_EVAL_ATTACKER", "claude-sonnet-5-5")


def claude(model: str):
    """A DeepEval model object for a Claude model (reads ANTHROPIC_API_KEY itself).

    deepeval's AnthropicModel switches on adaptive thinking for current models and sends no
    temperature unless one is given — current Claude models reject a temperature setting.
    Imported here, not at the top, so `--help` and the plan step never load the library.
    """
    from deepeval.models import AnthropicModel

    return AnthropicModel(model=model)


def results_root() -> Path:
    """`.claude/hillclimb/` in the repo's main checkout, even when run from a git worktree (a
    worktree is deleted after its PR, and git-ignored results with it — see backend/evals)."""
    found = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           cwd=HERE, capture_output=True, text=True)
    main_checkout = Path(found.stdout.strip()).parent if found.returncode == 0 else EVALS_DIR.parent
    return main_checkout / ".claude" / "hillclimb"


def load_targets() -> dict:
    """The target for every metric (targets.yaml): what "good enough" means, decided up front."""
    return yaml.safe_load(TARGETS_FILE.read_text())


def require_run_flag(run: bool, plan: str) -> None:
    """Print the plan; exit unless --run was given. Keeps a paid run a deliberate choice.

    Also checks ANTHROPIC_API_KEY is set before any paid run, so a missing key fails in one line
    instead of halfway through (the backend's .env isn't read here: export the key, or put it in
    evals/deepeval/.env, which is git-ignored).
    """
    print(plan)
    if not run:
        raise SystemExit("\nPlan only — nothing was called. Add --run to spend money on it.")
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise SystemExit("ANTHROPIC_API_KEY is not set (export it or add it to evals/deepeval/.env).")
