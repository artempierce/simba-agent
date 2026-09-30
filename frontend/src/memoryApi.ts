/**
 * memoryApi.ts — fetch helpers for memory (#80, #87): read every saved fact (the Memory page), and the
 * two calls Undo needs. Talks to `simba/memory_api.py` per docs/contracts.md § 10b. Adding and
 * forgetting happen by talking to Simba, so there are no helpers for those.
 *
 * Same shape as chatsApi.ts: callers get typed data or a thrown `Error` with the server's own
 * message, never a raw `Response`.
 */
import type { Fact } from './types'

/** All memory routes share this prefix. */
const BASE = '/api/memory'

/** Throw an `Error` carrying the backend's `{"detail": ...}` message, or the status line. */
async function fail(res: Response): Promise<never> {
  let detail: string | undefined
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    // No JSON body: fall back to the status line.
  }
  throw new Error(detail ?? `${res.status} ${res.statusText}`)
}

/** JSON request helper: send `body` (if any) and return the parsed reply. */
async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) await fail(res)
  return (res.status === 204 ? undefined : await res.json()) as T
}

/** Every saved fact, newest change first (GET /api/memory/facts). */
export const listFacts = () => send<Fact[]>('/facts', 'GET')

/** Put back a fact's text (PATCH /api/memory/facts/{id}) — Undo of an update. */
export const updateFact = (id: number, text: string) => send<Fact>(`/facts/${id}`, 'PATCH', { text })

/** Delete one fact (DELETE /api/memory/facts/{id}) — Undo of a save. */
export const deleteFact = (id: number) => send<void>(`/facts/${id}`, 'DELETE')
