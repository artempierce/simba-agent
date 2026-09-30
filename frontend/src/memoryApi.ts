/**
 * memoryApi.ts — fetch helpers for the Memory tab (#80): list, add, edit and delete saved facts, or
 * forget everything. Talks to `simba/memory_api.py` per docs/contracts.md § 10b.
 *
 * Same shape as chatsApi.ts: callers get typed data or a thrown `Error` with the server's own
 * message, never a raw `Response`.
 */
import type { Fact, FactKind } from './types'

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

/** Save a new fact (POST /api/memory/facts); the server trims it and enforces the size limits. */
export const addFact = (kind: FactKind, text: string) => send<Fact>('/facts', 'POST', { kind, text })

/** Change a fact's text (PATCH /api/memory/facts/{id}). */
export const updateFact = (id: number, text: string) => send<Fact>(`/facts/${id}`, 'PATCH', { text })

/** Forget one fact (DELETE /api/memory/facts/{id}). */
export const deleteFact = (id: number) => send<void>(`/facts/${id}`, 'DELETE')

/** Forget every fact (DELETE /api/memory); resolves to how many were deleted. */
export const deleteAllFacts = () => send<{ deleted: number }>('', 'DELETE')
