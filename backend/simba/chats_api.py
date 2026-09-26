"""
chats_api.py — REST API for the chat list: list/create/rename/delete chats, and read one chat's
full history (its messages plus past runs) for the sidebar and chat view.

Where it sits: mounted into the FastAPI app under /api/chats by api.py (the step-6 integration, not
this file). This router never builds its own ChatStore, checkpointer or graph — it reads them off
`request.app.state` (.chats, .checkpointer, .graph), which api.py sets up at startup. That keeps this
file testable with any small stand-in graph/checkpointer (see test_chats_api.py), without a real
Simba conversation graph.

Library concept: APIRouter groups a set of related endpoints — here, everything under /api/chats — so
api.py can add them all with one `app.include_router(router)` instead of defining routes on the app
directly.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from simba.chats import title_from
from simba.common import text_of

router = APIRouter(prefix="/api/chats")

# ai/human are the only message types a chat view shows; system/tool messages are internal plumbing.
_ROLE_OF = {"human": "user", "ai": "assistant"}


class CreateChatBody(BaseModel):
    """POST body: an optional title. None/omitted falls back to title_from("") = "New chat"."""

    title: str | None = None


class RenameChatBody(BaseModel):
    """PATCH body: the new title, trimmed to 1-80 characters (docs/contracts.md § 10)."""

    title: str

    @field_validator("title")
    @classmethod
    def _trimmed_length(cls, value: str) -> str:
        """Trim whitespace and reject a title that's then empty or over 80 characters, so FastAPI
        turns a bad title into a 422 response by itself (no manual check needed in the endpoint)."""
        trimmed = value.strip()
        if not 1 <= len(trimmed) <= 80:
            raise ValueError("title must be 1-80 characters after trimming")
        return trimmed


async def _get_or_404(request: Request, chat_id: str) -> dict:
    """Fetch a chat by id or raise the shared 404, so every endpoint reports an unknown id the same way."""
    chat = await request.app.state.chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


@router.get("")
async def list_chats(request: Request) -> list[dict]:
    """GET /api/chats -> every chat, newest updated_at first (Sidebar.tsx's list)."""
    return await request.app.state.chats.list()


@router.post("", status_code=201)
async def create_chat(body: CreateChatBody, request: Request) -> dict:
    """POST /api/chats -> a new, empty chat. No title given -> "New chat" (same rule as the first
    real message would produce via title_from)."""
    title = body.title or title_from("")
    return await request.app.state.chats.create(title)


@router.get("/{chat_id}")
async def get_chat(chat_id: str, request: Request) -> dict:
    """GET /api/chats/{id} -> the chat row, its messages, and its run history.

    1. Look up the chat, 404 if the id is unknown.
    2. Ask the graph for this thread's checkpointed state (LangGraph keeps the actual conversation,
       not this store); a chat with no turns yet has no saved state, so default to no messages.
    3. Keep only human/ai messages, renamed to the roles the frontend's Message type uses.
    4. Attach the chat's runs (trace history) from the ChatStore.
    """
    chat = await _get_or_404(request, chat_id)
    state = await request.app.state.graph.aget_state({"configurable": {"thread_id": chat_id}})
    messages = [
        {"role": _ROLE_OF[m.type], "content": text_of(m)}
        for m in state.values.get("messages", [])
        if m.type in _ROLE_OF
    ]
    runs = await request.app.state.chats.runs(chat_id)
    return {"chat": chat, "messages": messages, "runs": runs}


@router.patch("/{chat_id}")
async def rename_chat(chat_id: str, body: RenameChatBody, request: Request) -> dict:
    """PATCH /api/chats/{id} -> rename it. `body.title` is already trimmed/validated by RenameChatBody."""
    await _get_or_404(request, chat_id)
    return await request.app.state.chats.rename(chat_id, body.title)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: str, request: Request) -> None:
    """DELETE /api/chats/{id} -> remove the chat and its runs, and erase its checkpointed graph state
    (adelete_thread) so nothing of a deleted chat is left in either store."""
    await _get_or_404(request, chat_id)
    await request.app.state.chats.delete(chat_id)
    await request.app.state.checkpointer.adelete_thread(chat_id)
