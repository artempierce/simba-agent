"""
memory_api.py — REST API for the Memory tab (#80): list, add, edit and delete facts, or forget
everything (docs/contracts.md § 10b).

Where it sits: mounted by api.py under /api/memory, next to the chats router. Like chats_api.py it
never builds its own store — it reads `request.app.state.memory` (a MemoryStore, memory.py), which
api.py opens at startup — so tests can run it against a temporary database.

Validation happens twice on purpose: the request bodies below reject a bad kind or an over-long
fact with a 422 before anything runs, and MemoryStore checks the same limits again, so a caller that
skips this router (M2's `remember` tool) is held to the same rules.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from simba.memory import MAX_FACT_CHARS, MemoryFull

router = APIRouter(prefix="/api/memory")

Kind = Literal["user", "feedback", "project", "reference"]


class NewFact(BaseModel):
    """POST body: a fact to remember. `why` is optional context (useful for feedback facts)."""

    kind: Kind
    text: str = Field(min_length=1, max_length=MAX_FACT_CHARS)
    why: str | None = Field(default=None, max_length=MAX_FACT_CHARS)


class FactChange(BaseModel):
    """PATCH body: any of kind, text, why; fields left out stay as they are."""

    kind: Kind | None = None
    text: str | None = Field(default=None, min_length=1, max_length=MAX_FACT_CHARS)
    why: str | None = Field(default=None, max_length=MAX_FACT_CHARS)


@router.get("/facts")
async def list_facts(request: Request) -> list[dict]:
    """GET /api/memory/facts -> every fact, newest change first."""
    return await request.app.state.memory.list_facts()


@router.post("/facts", status_code=201)
async def add_fact(body: NewFact, request: Request) -> dict:
    """POST /api/memory/facts -> the saved fact (201). 409 when memory is full, 422 when the text is
    only whitespace (MemoryStore's own check, after whitespace is collapsed)."""
    try:
        return await request.app.state.memory.add_fact(body.kind, body.text, body.why)
    except MemoryFull as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/facts/{fact_id}")
async def update_fact(fact_id: int, body: FactChange, request: Request) -> dict:
    """PATCH /api/memory/facts/{id} -> the changed fact; 404 for an unknown id."""
    try:
        fact = await request.app.state.memory.update_fact(fact_id, body.kind, body.text, body.why)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    return fact


@router.delete("/facts/{fact_id}", status_code=204)
async def delete_fact(fact_id: int, request: Request) -> None:
    """DELETE /api/memory/facts/{id} -> 204; 404 for an unknown id."""
    if not await request.app.state.memory.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="fact not found")


@router.delete("")
async def delete_all(request: Request) -> dict:
    """DELETE /api/memory -> {"deleted": n}: forget every fact (the "Delete all" button)."""
    return {"deleted": await request.app.state.memory.delete_all()}
