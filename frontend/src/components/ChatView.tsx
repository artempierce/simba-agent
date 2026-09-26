/**
 * ChatView.tsx — the middle pane: chat bubbles and the message box (docs/contracts.md § 11).
 *
 * Holds one piece of state of its own: `draft`, the text currently in the textarea. Messages, the
 * busy flag and the send callback all come from App as props — ChatView never talks to the backend
 * directly, it only calls back into App via `onSend`.
 */
import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import type { Message } from '../types'

type Props = {
  messages: Message[] // bubbles to show
  busy: boolean // an answer is streaming; sending is disabled
  onSend: (text: string) => void // called with the trimmed message to send
}

/**
 * The chat column: a friendly empty-state greeting before the first message, then one bubble per
 * message, then the input box.
 *
 * 1. Show the greeting, or the message bubbles.
 * 2. Keep an empty marker after the last bubble, scrolled into view whenever messages change, so the
 *    newest text (including tokens streaming in) is always visible.
 * 3. The composer: Enter sends, Shift+Enter inserts a newline, read-only while an answer is streaming.
 */
export function ChatView({ messages, busy, onSend }: Props) {
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  // 2.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  /** Send the draft unless it's empty or an answer is still streaming; then clear the box. */
  function submit() {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    onSend(text)
  }

  return (
    <main className="flex min-h-0 min-w-0 flex-col bg-surface">
      {/* 1. */}
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-5 px-6 py-8">
          {messages.length === 0 ? (
            <EmptyState />
          ) : (
            // Only the last bubble can be "waiting" (the reply that's currently streaming in).
            messages.map((m, i) => <Bubble key={i} message={m} waiting={busy && i === messages.length - 1} />)
          )}
          <div ref={endRef} />
        </div>
      </div>

      {/* 3. */}
      <form
        onSubmit={(e) => {
          e.preventDefault() // stop the browser's default full-page form submit
          submit()
        }}
        className="border-t border-rule px-6 py-4"
      >
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-rule bg-bg p-2 focus-within:border-accent">
          <label htmlFor="composer" className="sr-only">
            Message
          </label>
          <textarea
            id="composer"
            rows={1}
            autoFocus
            value={draft}
            // `readOnly` (not `disabled`) while busy: a disabled field is un-focusable, so the
            // browser blurs it the moment a send starts — you'd have to click back in to keep
            // typing. `readOnly` blocks edits without dropping focus; `submit()` already refuses to
            // send while busy, and aria-disabled tells assistive tech the field isn't accepting input.
            readOnly={busy}
            aria-disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter adds a new line. isComposing is true mid-way through an
              // input method (e.g. Japanese) building a character — Enter there only confirms it.
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder="Ask Simba…"
            // field-sizing-content: the box grows with its text, up to max-h-48, then scrolls.
            className={`field-sizing-content max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted ${busy ? 'opacity-60' : ''}`}
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            className="rounded-lg bg-accent px-4 py-2 font-medium text-accent-ink hover:opacity-90 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
          >
            Send
          </button>
        </div>
        <p className="mx-auto mt-2 max-w-3xl text-xs text-muted">Enter to send · Shift+Enter for a new line</p>
      </form>
    </main>
  )
}

/**
 * One chat message: your own text right-aligned in a raised bubble; Simba's reply rendered as
 * Markdown (so lists, code and emphasis show properly); a pulsing status line while nothing has
 * streamed in for the reply yet; an error note in the danger colour if streaming the reply failed
 * (whatever text did stream in first, if any, is kept above it).
 */
function Bubble({ message, waiting }: { message: Message; waiting: boolean }) {
  if (message.role === 'user') {
    return (
      <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-raised px-4 py-2.5 whitespace-pre-wrap">
        {message.content}
      </div>
    )
  }
  if (!message.content && !message.error && waiting) {
    return (
      <div role="status" className="animate-pulse text-muted">
        Thinking…
      </div>
    )
  }
  // `prose-neutral` (the Tailwind typography plugin) styles the HTML that Markdown produces to read
  // well without a bubble around it, like a normal page of text; links and code are then pulled back
  // onto our own token colours instead of the plugin's built-in palette.
  return (
    <div>
      {message.content && (
        <div className="prose prose-neutral max-w-none min-w-0 prose-p:my-2 prose-pre:bg-bg prose-a:text-accent prose-code:text-ink">
          <Markdown>{message.content}</Markdown>
        </div>
      )}
      {/* aria-live only here, not on the div above: that div's content grows one token at a time,
          and announcing every token would spam a screen reader. This line only ever appears once,
          when streaming has already failed, so it's safe to announce. */}
      {message.error && (
        <p role="alert" aria-live="polite" className="mt-1 text-danger">
          Couldn't get a reply: {message.error}
        </p>
      )}
    </div>
  )
}

/** The greeting shown before the first message. */
function EmptyState() {
  return (
    <div className="flex flex-col gap-3 pt-[12vh]">
      <h2 className="text-3xl font-bold tracking-tight text-balance">Hi, I'm Simba</h2>
      <p className="text-muted">Ask me anything — I'll show every step I take in the trace panel on the right.</p>
    </div>
  )
}
