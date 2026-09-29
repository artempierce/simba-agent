/**
 * api.test.ts — tests for streamChat's SSE parser (api.ts, docs/contracts.md § 9).
 *
 * The backend is replaced by a fake `fetch` that answers with a stream of text chunks we choose.
 * That lets each test cut the stream in awkward places (mid-event, mid-line) the way a real network
 * does, and check which handlers streamChat called.
 *
 * Runs in plain Node, not jsdom: streamChat only needs fetch, streams and TextDecoderStream, which
 * Node has built in.
 *
 * @vitest-environment node
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamChat, type ChatHandlers } from './api'

/**
 * Make `fetch` answer with a 200 response whose body arrives as exactly these text chunks, one per
 * read. Example: fakeStream(['event: tok', 'en\ndata: {}\n\n']) splits one event across two reads.
 */
function fakeStream(chunks: string[]) {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })))
}

/** A full set of handlers that record every call as [name, argument] in `calls`, in order. */
function recordingHandlers() {
  const calls: [string, unknown][] = []
  const record = (name: string) => (value: unknown) => {
    calls.push([name, value])
  }
  const handlers: ChatHandlers = {
    onStart: (chatId, title) => calls.push(['start', { chatId, title }]),
    onTrace: record('trace'),
    onToken: record('token'),
    onReplace: record('replace'),
    onError: record('error'),
    onDone: record('done'),
  }
  return { calls, handlers }
}

/** One SSE event as the backend writes it: name line, data line, blank line. */
const sse = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`

afterEach(() => vi.unstubAllGlobals())

describe('streamChat', () => {
  /** The happy path: every event reaches its handler in order, and a `done` ends without an error. */
  it('dispatches each event to its handler', async () => {
    fakeStream([sse('start', { chat_id: 'c1', title: 'Hi' }) + sse('token', { text: 'Hel' }) + sse('token', { text: 'lo' }) + sse('done', { cost_usd: 0 })])
    const { calls, handlers } = recordingHandlers()
    await streamChat('hi', null, handlers)
    expect(calls).toEqual([
      ['start', { chatId: 'c1', title: 'Hi' }],
      ['token', 'Hel'],
      ['token', 'lo'],
      ['done', { cost_usd: 0 }],
    ])
  })

  /** Network chunks don't line up with events; an event cut in two must still arrive exactly once. */
  it('joins an event split across chunks', async () => {
    const whole = sse('token', { text: 'abc' }) + sse('done', {})
    fakeStream([whole.slice(0, 9), whole.slice(9, 20), whole.slice(20)])
    const { calls, handlers } = recordingHandlers()
    await streamChat('hi', null, handlers)
    expect(calls).toEqual([
      ['token', 'abc'],
      ['done', {}],
    ])
  })

  /** SSE allows \r\n line endings (some proxies rewrite them); they must parse like \n. */
  it('accepts CRLF line endings', async () => {
    fakeStream([(sse('token', { text: 'x' }) + sse('done', {})).replace(/\n/g, '\r\n')])
    const { calls, handlers } = recordingHandlers()
    await streamChat('hi', null, handlers)
    expect(calls).toEqual([
      ['token', 'x'],
      ['done', {}],
    ])
  })

  /** A server that closes right after its last write, without the final blank line, loses nothing. */
  it('flushes a trailing event that has no blank line after it', async () => {
    fakeStream([sse('token', { text: 'x' }) + 'event: done\ndata: {}'])
    const { calls, handlers } = recordingHandlers()
    await streamChat('hi', null, handlers)
    expect(calls).toEqual([
      ['token', 'x'],
      ['done', {}],
    ])
  })

  /** Malformed data gets its own message (a server bug, not a network drop) and ends the run. */
  it('reports bad JSON once and does not also report an unexpected end', async () => {
    fakeStream(['event: token\ndata: {not json\n\n'])
    const { calls, handlers } = recordingHandlers()
    await streamChat('hi', null, handlers)
    expect(calls).toEqual([['error', 'Bad data from the server.']])
  })

  /** A stream that stops without `done` or `error` must not look like a finished answer. */
  it('reports a stream that ends without done', async () => {
    fakeStream([sse('token', { text: 'half an ans' })])
    const { calls, handlers } = recordingHandlers()
    await streamChat('hi', null, handlers)
    expect(calls).toEqual([
      ['token', 'half an ans'],
      ['error', 'The reply ended unexpectedly.'],
    ])
  })

  /** A backend `error` event is a proper end: its message is shown, with no second error on top. */
  it('treats an error event as the end of the run', async () => {
    fakeStream([sse('error', { message: 'Model failed.' })])
    const { calls, handlers } = recordingHandlers()
    await streamChat('hi', null, handlers)
    expect(calls).toEqual([['error', 'Model failed.']])
  })

  /** Failures before any stream starts come back through onError, never as a thrown exception. */
  it('reports an unreachable backend and a non-2xx status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('network'))))
    const first = recordingHandlers()
    await streamChat('hi', null, first.handlers)
    expect(first.calls).toEqual([['error', "Can't reach the backend."]])

    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })))
    const second = recordingHandlers()
    await streamChat('hi', null, second.handlers)
    expect(second.calls).toEqual([['error', 'The server returned 500.']])
  })
})
