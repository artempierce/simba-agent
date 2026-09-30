"""
memory_api.py — REST API for the Memory page (#80, #87; docs/contracts.md § 10b): read every fact,
plus the two calls the reply's Undo needs (rewrite a fact, delete a fact).

Memory is changed by talking to Simba (D46) — its tools, not this router, add, update and forget
facts. So there is no "add" or "delete all" route here: the page only reads, and Undo only reverses
what a reply just saved.

Where it sits: mounted by api.py under /api/memory, next to the chats router. Like chats_api.py it
never builds its own store — it reads `request.app.state.memory` (a MemoryStore, memory.py), which
api.py opens at startup — so tests can run it against a temporary database.

Validation happens twice on purpose: the PATCH body rejects a bad kind or an over-long fact with a
422 before anything runs, and MemoryStore checks the same limits again, so the memory tools (which
skip this router) are held to the same rules.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from simba.memory import MAX_FACT_CHARS

router = APIRouter(prefix="/api/memory")

Kind = Literal["user", "feedback", "project", "reference"]


class FactChange(BaseModel):
    """PATCH body: any of kind, text, why; fields left out stay as they are."""

    kind: Kind | None = None
    text: str | None = Field(default=None, min_length=1, max_length=MAX_FACT_CHARS)
    why: str | None = Field(default=None, max_length=MAX_FACT_CHARS)


@router.get("/facts")
async def list_facts(request: Request) -> list[dict]:
    """GET /api/memory/facts -> every fact, newest change first (the Memory page)."""
    return await request.app.state.memory.list_facts()


@router.get("/summaries")
async def list_summaries(request: Request) -> list[dict]:
    """GET /api/memory/summaries -> every chat summary with its chat's title, newest first (#82: the
    Memory page's "Past chats")."""
    return await request.app.state.memory.list_summaries()


@router.patch("/facts/{fact_id}")
async def update_fact(fact_id: int, body: FactChange, request: Request) -> dict:
    """PATCH /api/memory/facts/{id} -> the changed fact; 404 for an unknown id. Used by Undo to put
    back an updated fact's old wording."""
    try:
        fact = await request.app.state.memory.update_fact(fact_id, body.kind, body.text, body.why)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    return fact


@router.delete("/facts/{fact_id}", status_code=204)
async def delete_fact(fact_id: int, request: Request) -> None:
    """DELETE /api/memory/facts/{id} -> 204; 404 for an unknown id. Used by Undo to take back a fact
    a reply just added."""
    if not await request.app.state.memory.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="fact not found")
