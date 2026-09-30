/**
 * chatsApi.ts — fetch helpers for the chat sidebar (step 6): list, rename and delete chats, and load
 * one chat's messages and trace runs. Talks to `simba/chats_api.py` per docs/contracts.md § 10.
 *
 * `Sidebar.tsx` and `App.tsx` call these functions and get back typed data or a thrown `Error` —
 * never a raw `Response` — so callers don't each have to repeat status-checking and JSON parsing.
 */
import type { Chat, Message, Run, ServerInfo } from './types'

/**
 * What the server runs with (GET /api/info, #57): model name and whether web search is on.
 * Lives here with the other small JSON GETs; throws on a failed response like they do.
 */
export async function getInfo(): Promise<ServerInfo> {
  const res = await fetch('/api/info')
  if (!res.ok) await throwForStatus(res)
  return (await res.json()) as ServerInfo
}

/** All chat routes share this prefix (docs/contracts.md § 10). */
const BASE = '/api/chats'

/**
 * Reads a failed response's JSON body and throws an `Error` with a readable message.
 * Input: a `Response` whose `.ok` is false. Output: never returns — it always throws.
 * Why: the backend sends `{"detail": str}` on errors (e.g. 404 "chat not found"); surfacing that
 * beats a bare "404 Not Found" when, say, a rename targets a chat that was just deleted.
 */
async function throwForStatus(res: Response): Promise<never> {
  let detail: string | undefined
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    // Body wasn't JSON (or there wasn't one) — fall back to the status line below.
  }
  throw new Error(detail ?? `${res.status} ${res.statusText}`)
}

/** List every chat, newest `updated_at` first (GET /api/chats). */
export async function listChats(): Promise<Chat[]> {
  const res = await fetch(BASE)
  if (!res.ok) await throwForStatus(res)
  return (await res.json()) as Chat[]
}

/** Load one chat's row plus its rendered messages and trace runs (GET /api/chats/{id}). */
export async function getChat(id: string): Promise<{ chat: Chat; messages: Message[]; runs: Run[] }> {
  const res = await fetch(`${BASE}/${id}`)
  if (!res.ok) await throwForStatus(res)
  return (await res.json()) as { chat: Chat; messages: Message[]; runs: Run[] }
}

/** Rename a chat; the backend requires 1-80 characters after trimming (PATCH /api/chats/{id}). */
export async function renameChat(id: string, title: string): Promise<Chat> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) await throwForStatus(res)
  return (await res.json()) as Chat
}

/** Delete a chat and its runs (DELETE /api/chats/{id}); resolves once the 204 comes back. */
export async function deleteChat(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${id}`, { method: 'DELETE' })
  if (!res.ok) await throwForStatus(res)
}
