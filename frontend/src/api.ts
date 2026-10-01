/**
 * api.ts — talks to the FastAPI backend's one streaming endpoint, POST /api/chat
 * (docs/contracts.md § 9, § 11).
 *
 * The page never calls the backend's address directly: it calls `/api/chat` on its own origin, and
 * the Vite dev server proxies that to http://127.0.0.1:8000 (see vite.config.ts), so there's no
 * cross-origin (CORS) setup to worry about in development.
 *
 * Why not the browser's built-in EventSource? It only supports GET requests, and /api/chat is a POST
 * (it sends a message body). So instead we read the response body as a stream and split
 * Server-Sent Events (SSE) out of it ourselves.
 */
import type { ApprovalRequest, MemoryEvent, RunSummary, TraceLine } from './types'

/** Callbacks streamChat calls as the backend's SSE events arrive (docs/contracts.md § 9). */
export type ChatHandlers = {
  onStart: (chatId: string, title: string) => void
  onTrace: (line: TraceLine) => void
  onToken: (text: string) => void
  // The output guard (#15) retracted the answer: swap everything streamed so far for `text`.
  onReplace: (text: string) => void
  // #81: the remember tool saved a fact; the reply shows it with an Undo.
  onMemory: (event: MemoryEvent) => void
  // #66: the turn paused; these calls wait for the owner's approve / deny (then `done` ends the stream).
  onApproval: (request: ApprovalRequest) => void
  onError: (message: string) => void
  onDone: (summary: RunSummary) => void
}

/**
 * Parse one "event: name\ndata: {json}" block (its trailing blank line already stripped) and call
 * the matching handler. Returns true for `done` and `error` — the two events that end a run — so
 * streamChat below can tell a normal end from a stream that just stopped sending events.
 */
function dispatchEvent(block: string, handlers: ChatHandlers): boolean {
  const name = block.match(/^event: (.*)$/m)?.[1]
  const data = block.match(/^data: (.*)$/m)?.[1]
  if (!name || !data) return false

  // JSON.parse gets its own try/catch: malformed data is a server/proxy bug, not a dropped
  // connection, so it's worth a distinct message rather than looking like a network failure.
  let payload
  try {
    payload = JSON.parse(data)
  } catch {
    handlers.onError('Bad data from the server.')
    return true // still ends the run — nothing after malformed data can be trusted
  }

  if (name === 'start') handlers.onStart(payload.chat_id, payload.title)
  else if (name === 'trace') handlers.onTrace(payload)
  else if (name === 'token') handlers.onToken(payload.text)
  else if (name === 'replace') handlers.onReplace(payload.text)
  else if (name === 'memory') handlers.onMemory(payload)
  else if (name === 'approval') handlers.onApproval(payload)
  else if (name === 'error') {
    handlers.onError(payload.message)
    return true
  } else if (name === 'done') {
    handlers.onDone(payload)
    return true
  }
  return false
}

/**
 * Send one message and stream the reply, calling the matching handler for every SSE event.
 * Resolves once the stream ends.
 *
 * `chatId` null starts a new chat; the `start` event reports the id the backend assigned it. Any
 * failure — can't reach the backend, a non-2xx response, a dropped connection, malformed event data,
 * or the stream closing without a `done`/`error` — is reported through `onError` instead of
 * throwing, so callers never need a try/catch around this call.
 *
 * 1. POST the message. A request that never reaches the server, a non-ok status, or a response with
 *    no body all count as a failure.
 * 2. Decode the byte stream to text and read it piece by piece as it arrives, normalising `\r\n` to
 *    `\n` (SSE allows either line ending, but the parsing below only looks for `\n`).
 * 3. Network chunks don't line up with event boundaries, so text is collected in `buffer` and cut
 *    into complete "event: name\ndata: {json}\n\n" blocks as they finish; each is dispatched to its
 *    matching handler.
 * 4. Once the connection closes, flush any final event left in `buffer` without its trailing blank
 *    line (a server that closes right after its last write shouldn't lose that event), then — if
 *    nothing dispatched a `done` or `error` — report that the stream ended unexpectedly.
 */
export async function streamChat(message: string, chatId: string | null, handlers: ChatHandlers): Promise<void> {
  return streamPost('/api/chat', { message, chat_id: chatId }, handlers)
}

/**
 * Answer an approval card (#66): POST /api/chat/{chatId}/resume and stream the rest of the paused
 * turn through the same handlers (the same events as a normal turn). Only `approve: true` approves.
 */
export async function streamResume(chatId: string, approve: boolean, handlers: ChatHandlers): Promise<void> {
  return streamPost(`/api/chat/${encodeURIComponent(chatId)}/resume`, { approve }, handlers)
}

/** POST `body` to `url` and dispatch the SSE reply to `handlers` — steps 1–4 above. */
async function streamPost(url: string, body: unknown, handlers: ChatHandlers): Promise<void> {
  // 1.
  let res: Response
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    handlers.onError("Can't reach the backend.")
    return
  }
  if (!res.ok || !res.body) {
    handlers.onError(`The server returned ${res.status}.`)
    return
  }

  // 2.
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let finished = false // set once dispatchEvent handles a `done` or `error`
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value.replace(/\r\n/g, '\n')

      // 3. Each event ends with a blank line.
      let end: number
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        if (dispatchEvent(block, handlers)) finished = true
      }
    }
  } catch {
    handlers.onError('Lost connection to the backend.')
    return
  }

  // 4.
  if (buffer.trim() && dispatchEvent(buffer, handlers)) finished = true
  if (!finished) handlers.onError('The reply ended unexpectedly.')
}
