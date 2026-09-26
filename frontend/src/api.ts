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
import type { RunSummary, TraceLine } from './types'

/** Callbacks streamChat calls as the backend's SSE events arrive (docs/contracts.md § 9). */
export type ChatHandlers = {
  onStart: (chatId: string, title: string) => void
  onTrace: (line: TraceLine) => void
  onToken: (text: string) => void
  onError: (message: string) => void
  onDone: (summary: RunSummary) => void
}

/**
 * Send one message and stream the reply, calling the matching handler for every SSE event.
 * Resolves once the stream ends.
 *
 * `chatId` null starts a new chat; the `start` event reports the id the backend assigned it. Any
 * network or HTTP failure (backend down, non-2xx response, a dropped connection) is reported through
 * `onError` instead of throwing, so callers never need a try/catch around this call.
 *
 * 1. POST the message. A request that never reaches the server, a non-ok status, or a response with
 *    no body all count as a failure.
 * 2. Decode the byte stream to text and read it piece by piece as it arrives.
 * 3. Network chunks don't line up with event boundaries, so text is collected in `buffer` and cut
 *    into complete "event: name\ndata: {json}\n\n" blocks as they finish; each block is dispatched
 *    to its matching handler.
 */
export async function streamChat(message: string, chatId: string | null, handlers: ChatHandlers): Promise<void> {
  // 1.
  let res: Response
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, chat_id: chatId }),
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
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value

      // 3. Each event ends with a blank line.
      let end: number
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        const name = block.match(/^event: (.*)$/m)?.[1]
        const data = block.match(/^data: (.*)$/m)?.[1]
        if (!name || !data) continue
        const payload = JSON.parse(data)
        if (name === 'start') handlers.onStart(payload.chat_id, payload.title)
        else if (name === 'trace') handlers.onTrace(payload)
        else if (name === 'token') handlers.onToken(payload.text)
        else if (name === 'error') handlers.onError(payload.message)
        else if (name === 'done') handlers.onDone(payload)
      }
    }
  } catch {
    handlers.onError('Lost connection to the backend.')
  }
}
