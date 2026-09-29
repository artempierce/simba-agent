# Backend — FastAPI + LangGraph, Python 3.12, uv

Loaded only when a session works in `backend/`. Root rules still apply.

- One test file: `uv run pytest tests/test_intent.py -q`; all: `uv run pytest -q --tb=short`.
- Tests always use the fake model (`simba.model.fake_model`); never real Claude.
  Async tests need no decorator (`asyncio_mode = "auto"`).
- A graph step = `simba/nodes/<step>.py` + wiring in `graph.py` + field in `state.py` +
  `docs/contracts.md`. Change all four together.
- Test one node alone with `tests/node_harness.py`.
- Untrusted text going into a prompt: wrap it in tags and escape it with `common.neutralise_tag`.
- Every node reports through `common.emit_trace`; a step missing from the trace panel isn't done.
- API change → update `specs/api-spec.json` (`tests/test_api_spec.py` catches drift).
- Harness redesign: #32 moved the guard, classifier and output guard into `simba/harness/` as hooks
  (`hooks.py`, `settings.py`, `nodes/hook_points.py`). #33 (next) replaces intent/reason/generate with
  one agent node.
