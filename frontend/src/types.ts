/**
 * types.ts — the shapes the frontend shares with the backend (docs/contracts.md § 6 and § 11).
 *
 * These mirror the JSON the API sends, so a mismatch here is a contract bug: change contracts.md,
 * the backend and this file together.
 */

/** One line in the trace panel: what one graph node did (backend: common.emit_trace). */
export type TraceLine = {
  stage: string // before_model | agent | before_tool | web_search | after_tool | remember | after_model | refuse | budget (intent | reason | generate on older chats)
  // (guard/output_guard on chats saved before #32; echo in step 1)
  status: 'ok' | 'blocked' | 'error' | 'flagged' // flagged (#8): passed, but the classifier raised a flag
  detail: string
  ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

/** Totals for one message's whole run, from the `done` event. */
export type RunSummary = { input_tokens: number; output_tokens: number; cost_usd: number; ms: number }

/** One message's trace block: your prompt, its trace lines, then a summary or an error. */
export type Run = { prompt: string; lines: TraceLine[]; summary?: RunSummary; error?: string }

/** One chat bubble. `error` is set when streaming the reply failed (a network/HTTP failure or a
 * mid-stream `error` event) — shown in the bubble instead of, or alongside, whatever text streamed. */
export type Message = {
  role: 'user' | 'assistant'
  content: string
  error?: string
  memories?: RememberedFact[] // #81: facts the reply saved, shown as "Remembered: … · Undo"
}

/** What the server runs with, from GET /api/info (#57): shown in the header pill. */
export type ServerInfo = { model: string; web_search: boolean; chat_budget_usd: number }

/** The four kinds of saved fact (#80, D40): who you are, how you like to work, ongoing work, pointers. */
export type FactKind = 'user' | 'feedback' | 'project' | 'reference'

/** One saved fact, as GET /api/memory/facts returns it (docs/contracts.md § 10b). */
export type Fact = {
  id: number
  kind: FactKind
  text: string
  why: string | null
  source_chat_id: string | null
  created_at: string
  updated_at: string
}

/** The SSE `memory` event (#81, #87): a memory tool saved, updated or forgot a fact while writing a reply. */
export type MemoryEvent = {
  action: 'added' | 'updated' | 'forgotten' // saved, rewritten (incl. near-duplicates), or deleted after your yes
  fact_id: number
  kind: FactKind
  text: string
  previous_text: string | null // an updated fact's old wording, which Undo puts back
}

/** A saved fact as the reply shows it; `undone` once you clicked Undo. */
export type RememberedFact = MemoryEvent & { undone?: boolean }

/** One chat in the sidebar (step 6). Times are ISO 8601 UTC strings. */
export type Chat = { id: string; title: string; created_at: string; updated_at: string }
