/**
 * ChatView.tsx — the middle pane: chat bubbles and the message box (docs/contracts.md § 11).
 *
 * Holds one piece of state of its own: `draft`, the text currently in the textarea. Messages, the
 * busy flag and the send callback all come from App as props — ChatView never talks to the backend
 * directly, it only calls back into App via `onSend`. `mood` is App's current `moodFor(...)` result
 * (docs/visual-style.md → "Simba avatar"); ChatView only uses it to draw the empty state's big avatar.
 */
import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { Fish, Paw, Whiskers, Yarn, DoodleBand } from './Doodles'
import { SimbaAvatar } from './SimbaAvatar'
import type { Mood } from '../mood'
import type { Message } from '../types'
import type { ComponentType } from 'react'

type Props = {
  messages: Message[] // bubbles to show
  busy: boolean // an answer is streaming; sending is disabled
  mood: Mood // Simba's current mood, for the empty state's avatar
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
export function ChatView({ messages, busy, mood, onSend }: Props) {
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  // 2.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  /** Send the draft unless it's empty or an answer is still streaming; then clear the box. */
  function submit(text: string) {
    if (!text || busy) return
    setDraft('')
    onSend(text)
  }

  return (
    <main className="flex h-full min-h-0 min-w-0 flex-col bg-surface">
      {/* 1. */}
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-5 px-6 py-8">
          {messages.length === 0 ? (
            <EmptyState mood={mood} onSend={submit} />
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
          submit(draft.trim())
        }}
        className="border-t border-rule px-6 py-4"
      >
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border-[1.5px] border-ink bg-surface p-2 focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ink">
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
                submit(draft.trim())
              }
            }}
            placeholder="Ask Simba…"
            // field-sizing-content: the box grows with its text, up to max-h-48, then scrolls.
            className={`field-sizing-content max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted ${busy ? 'opacity-60' : ''}`}
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            className="rounded-full bg-accent px-4 py-2 font-medium text-accent-ink hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:opacity-40"
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
 * One chat message: your own text right-aligned in a `sky` bubble; Simba's reply starts with a small
 * avatar and is rendered as Markdown (so lists, code and emphasis show properly); a pulsing status
 * line while nothing has streamed in for the reply yet; an error note in the danger colour if
 * streaming the reply failed (whatever text did stream in first, if any, is kept above it).
 *
 * The reply's avatar picks its own small mood from this one message only (busy/error), rather than
 * taking App's global `mood` prop — a past, finished reply should always look `happy` (or `dizzy` if
 * it errored), never flip moods just because a *later* message is now streaming.
 */
function Bubble({ message, waiting }: { message: Message; waiting: boolean }) {
  if (message.role === 'user') {
    return (
      <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-sky px-4 py-2.5 whitespace-pre-wrap text-ink">
        {message.content}
      </div>
    )
  }
  const avatarMood = message.error ? 'dizzy' : waiting ? 'thinking' : 'happy'
  return (
    <div className="flex items-start gap-2.5">
      <SimbaAvatar mood={avatarMood} size={28} />
      <div className="min-w-0 flex-1 pt-0.5">
        {!message.content && !message.error && waiting ? (
          <div role="status" className="animate-pulse text-muted">
            Thinking…
          </div>
        ) : (
          message.content && (
            // `prose-neutral` (the Tailwind typography plugin) styles the HTML that Markdown produces
            // to read well without a bubble around it, like a normal page of text; links and code are
            // then pulled back onto our own token colours instead of the plugin's built-in palette.
            <div className="prose prose-neutral max-w-none min-w-0 prose-p:my-2 prose-pre:bg-bg prose-a:text-accent prose-code:text-ink">
              <Markdown>{message.content}</Markdown>
            </div>
          )
        )}
        {/* aria-live only here, not on the prose div above: that div's content grows one token at a
            time, and announcing every token would spam a screen reader. This line only ever appears
            once, when streaming has already failed, so it's safe to announce. */}
        {message.error && (
          <p role="alert" aria-live="polite" className="mt-1 text-danger">
            Couldn't get a reply: {message.error}
          </p>
        )}
      </div>
    </div>
  )
}

/**
 * The greeting shown before the first message (docs/visual-style.md → "Empty state"): a white hero
 * card (big avatar, serif greeting, one line of copy) floating over a faint doodle pattern band, then
 * four pastel suggestion cards that send their prompt through `onSend` when clicked.
 */
function EmptyState({ mood, onSend }: { mood: Mood; onSend: (text: string) => void }) {
  return (
    <div className="relative overflow-hidden rounded-2xl pt-[6vh] pb-2">
      <DoodleBand />
      <div className="relative mx-auto flex max-w-xl flex-col items-center gap-3 rounded-2xl border-[1.5px] border-ink bg-surface px-6 py-8 text-center shadow-md">
        <SimbaAvatar mood={mood} size={96} />
        <h2 className="font-serif text-3xl font-semibold tracking-tight text-balance">Hi, I'm Simba.</h2>
        <p className="text-muted">Ask me anything — I'll show every step I take in the trace panel on the right.</p>
      </div>
      <div className="relative mx-auto mt-6 grid max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
        {SUGGESTIONS.map(({ icon: Icon, prompt, color }) => (
          <button
            key={prompt}
            type="button"
            onClick={() => onSend(prompt)}
            className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm font-medium text-ink ${color} hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink`}
          >
            <Icon size={26} className="shrink-0" />
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}

/** One of the four small doodles, as a component ChatView can drop straight into a suggestion card. */
type DoodleIcon = ComponentType<{ size?: number; className?: string }>

/** The empty state's four suggestion cards: a prompt, a pastel card colour, and a matching doodle
 * (docs/visual-style.md → "Empty state"). Card colours use every pastel token once, per the brief. */
const SUGGESTIONS: { icon: DoodleIcon; prompt: string; color: string }[] = [
  { icon: Paw, prompt: 'Plan a cozy weekend', color: 'bg-sky' },
  { icon: Whiskers, prompt: 'Explain something simply', color: 'bg-butter' },
  { icon: Yarn, prompt: 'Help me write a message', color: 'bg-blush' },
  { icon: Fish, prompt: 'Brainstorm ideas', color: 'bg-coral' },
]
