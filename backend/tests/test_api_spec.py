"""
tests/test_api_spec.py — keeps specs/api-spec.json (the OpenAPI contract, ticket #24) honest.

A hand-written spec drifts silently unless something checks it. These tests fail CI when the spec is
not valid OpenAPI, when a route is added or removed without updating the spec, or when api.py starts
sending an SSE event the spec doesn't list.
"""

import inspect
import json
import re
from pathlib import Path

from openapi_spec_validator import validate

import simba.api
from simba.api import create_app
from simba.model import fake_model

SPEC_PATH = Path(__file__).resolve().parents[2] / "specs" / "api-spec.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_spec_is_valid_openapi():
    """The file is a valid OpenAPI 3.1 document (tools and codegen can rely on it)."""
    validate(SPEC)


def test_spec_paths_match_the_real_routes():
    """Every (path, method) in the spec exists in the FastAPI app and vice versa. The "real" list comes
    from `app.openapi()` — the spec FastAPI generates from the code itself — because it includes the
    routes of included routers (newer FastAPI wraps those, so `app.routes` alone would miss them)."""
    app = create_app(model=fake_model())
    real = {(path, method) for path, ops in app.openapi()["paths"].items() for method in ops}
    documented = {(path, method) for path, ops in SPEC["paths"].items() for method in ops if method != "parameters"}
    assert documented == real


def test_spec_lists_every_sse_event_api_py_sends():
    """The events named in api.py's `sse("...")` calls are exactly the spec's `x-sse-events`."""
    sent = set(re.findall(r'sse\("(\w+)"', inspect.getsource(simba.api)))
    listed = set(SPEC["paths"]["/api/chat"]["post"]["responses"]["200"]["x-sse-events"])
    assert sent == listed
