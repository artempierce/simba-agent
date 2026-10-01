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


def _trim_title(value: str) -> str:
    """Trim whitespace and reject a title over 80 characters after trimming (docs/contracts.md § 10).
    Shared by POST and PATCH: PATCH also rejects a blank result (a rename must say something), while
    POST treats a blank/missing title as "use the default" instead of an error.
    """
    trimmed = value.strip()
    if len(trimmed) > 80:
        raise ValueError("title must be at most 80 characters after trimming")
    return trimmed


class CreateChatBody(BaseModel):
    """POST body: an optional title, trimmed. Blank or missing -> "New chat" (title_from("")); over
    80 characters after trim -> 422 (same length rule as PATCH, via `_trim_title`)."""

    title: str | None = None

    @field_validator("title")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        return _trim_title(value) if value is not None else None


class RenameChatBody(BaseModel):
    """PATCH body: the new title, trimmed to 1-80 characters (docs/contracts.md § 10)."""

    title: str

    @field_validator("title")
    @classmethod
    def _trimmed_length(cls, value: str) -> str:
        """Trim whitespace and reject a title that's then empty (PATCH, unlike POST, has no default to
        fall back to) or over 80 characters, so FastAPI turns a bad title into a 422 response by itself."""
        trimmed = _trim_title(value)
        if not trimmed:
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
    5. #66b: attach `approval` — the calls a paused turn is waiting on ({"calls": [...]}), or None —
       so a reopened chat shows its approval card again.
    """
    # 1. Look up the chat, 404 if the id is unknown.
    chat = await _get_or_404(request, chat_id)
    # 2. Ask the graph for this thread's checkpointed state; a chat with no turns yet has no saved
    #    state, so `.values` is empty and `messages` defaults to [].
    state = await request.app.state.graph.aget_state({"configurable": {"thread_id": chat_id}})
    # 3. Keep only human/ai messages, renamed to the roles the frontend's Message type uses.
    messages = [
        {"role": _ROLE_OF[m.type], "content": text_of(m)}
        for m in state.values.get("messages", [])
        if m.type in _ROLE_OF
    ]
    # 4. Attach the chat's runs (trace history) from the ChatStore.
    runs = await request.app.state.chats.runs(chat_id)
    # 5. #66b: a turn paused for approval keeps its card after a reload: the waiting calls, or None.
    approval = next((i.value for task in state.tasks for i in task.interrupts), None)
    return {"chat": chat, "messages": messages, "runs": runs, "approval": approval}


@router.patch("/{chat_id}")
async def rename_chat(chat_id: str, body: RenameChatBody, request: Request) -> dict:
    """PATCH /api/chats/{id} -> rename it. `body.title` is already trimmed/validated by RenameChatBody."""
    # Checked here, not left to `rename()`'s own None return, so an unknown id gets the shared 404
    # (with its {"detail": ...} body) instead of `rename`'s None reaching the response as `null`.
    await _get_or_404(request, chat_id)
    return await request.app.state.chats.rename(chat_id, body.title)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: str, request: Request) -> None:
    """DELETE /api/chats/{id} -> remove the chat and its runs, erase its checkpointed graph state
    (adelete_thread), and forget its summary (#82), so nothing of a deleted chat is left anywhere.

    Checkpointer first, then the ChatStore row: if adelete_thread fails, the chat stays listed, so
    delete can be retried, instead of a checkpoint orphaned behind an already-gone chat.
    """
    # Checked here so an unknown id gets one clear 404 up front, rather than adelete_thread silently
    # doing nothing on a thread that was never there and chats.delete() then reporting False.
    await _get_or_404(request, chat_id)
    await request.app.state.checkpointer.adelete_thread(chat_id)
    await request.app.state.chats.delete(chat_id)
    # #82: the chat's summary goes too — memory of a deleted chat shouldn't outlive it.
    memory = getattr(request.app.state, "memory", None)
    if memory is not None:
        await memory.delete_summary(chat_id)
