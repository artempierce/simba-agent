/**
 * App.tsx — the whole page: header, chat pane and trace panel, plus all the state they share
 * (docs/contracts.md § 11).
 *
 *   ┌────────────────────────────────────────────────┐
 *   │ Header: Simba · New chat                        │
 *   ├────────────────────────────────┬────────────────┤
 *   │ ChatView (messages + input)    │ TracePanel     │
 *   └────────────────────────────────┴────────────────┘
 *
 * All state lives here and flows down to the panes as props; they never talk to the backend
 * themselves, only call back into App (onSend, onNew). One owner means one place to look when
 * something shows the wrong thing.
 */
import { useState } from 'react'
import { streamChat } from './api'
import { ChatView } from './components/ChatView'
import { TracePanel } from './components/TracePanel'
import type { Message, Run } from './types'

// Step 6 adds a Sidebar pane here (chat list: open/rename/delete/new), to the left of ChatView.

export default function App() {
  const [chatId, setChatId] = useState<string | null>(null) // null = a new, unsaved chat
  const [messages, setMessages] = useState<Message[]>([])
  const [runs, setRuns] = useState<Run[]>([]) // one trace-panel block per message sent
  const [busy, setBusy] = useState(false) // an answer is streaming; disables sending and "New chat"

  // The two helpers below change only the *last* item in their list — the run or reply currently
  // streaming. They pass a function to the setter rather than a plain value, so React always applies
  // the change to the latest state even when SSE events arrive faster than a render.

  /** Update the run currently streaming (always the last one in `runs`). */
  const updateLastRun = (change: (run: Run) => Run) =>
    setRuns((rs) => [...rs.slice(0, -1), change(rs[rs.length - 1])])

  /** Update the assistant reply currently streaming (always the last message). */
  const updateReply = (change: (reply: Message) => Message) =>
    setMessages((ms) => [...ms.slice(0, -1), change(ms[ms.length - 1])])

  /**
   * Send a message: show your bubble and an empty reply, start a new trace-panel Run, then stream
   * the backend's SSE events into them (docs/contracts.md § 9).
   *
   * 1. Add your bubble and an empty assistant bubble that fills up as tokens arrive.
   * 2. Start a new Run for this message.
   * 3. Stream the response; each handler updates the reply bubble or the run's trace lines.
   *    `onStart` records the chat id a new chat was just given, so the next message continues it.
   * 4. Re-enable sending once the stream ends, whether it finished, errored, or dropped.
   */
  async function send(text: string) {
    // 1.
    setMessages((ms) => [...ms, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    // 2.
    setRuns((rs) => [...rs, { prompt: text, lines: [] }])
    setBusy(true)
    // 3.
    await streamChat(text, chatId, {
      onStart: (id) => setChatId(id),
      onTrace: (line) => updateLastRun((r) => ({ ...r, lines: [...r.lines, line] })),
      onToken: (t) => updateReply((m) => ({ ...m, content: m.content + t })),
      onError: (message) => {
        // The trace panel is hidden below 1024px (lg), so an error must also reach the reply
        // bubble itself, or it would be invisible on narrow screens.
        updateLastRun((r) => ({ ...r, error: message }))
        updateReply((m) => ({ ...m, error: message }))
      },
      onDone: (summary) => updateLastRun((r) => ({ ...r, summary })),
    })
    // 4.
    setBusy(false)
  }

  /** Start a fresh chat: forget the open chat's messages and trace runs. */
  function newChat() {
    if (busy) return
    setChatId(null)
    setMessages([])
    setRuns([])
  }

  return (
    <div className="grid h-full grid-rows-[auto_1fr]">
      <header className="flex items-center justify-between border-b border-rule bg-surface px-6 py-3">
        <span className="text-lg font-semibold text-accent">Simba</span>
        <button
          type="button"
          onClick={newChat}
          disabled={busy}
          className="rounded-lg border border-rule px-3 py-1.5 text-sm hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
        >
          New chat
        </button>
      </header>
      <div className="grid min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px]">
        <ChatView messages={messages} busy={busy} onSend={send} />
        <TracePanel runs={runs} busy={busy} />
      </div>
    </div>
  )
}
