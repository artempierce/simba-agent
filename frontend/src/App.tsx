/**
 * App.tsx — the whole page: header, chat sidebar, chat pane and trace panel, plus all the state
 * they share (docs/contracts.md § 11).
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │ Header: [Chats (< md)]  Simba                               │
 *   ├──────────┬─────────────────────────────────┬────────────────┤
 *   │ Sidebar  │ ChatView (messages + input)     │ TracePanel     │
 *   │ (≥ md)   │                                 │ (≥ lg)         │
 *   └──────────┴─────────────────────────────────┴────────────────┘
 *
 * Below md, the Sidebar isn't in the grid — the header's "Chats" button opens it as an overlay
 * drawer instead (closed by selecting a chat, Esc, or clicking the backdrop).
 *
 * All state lives here and flows down to the panes as props; they never talk to the backend
 * themselves, only call back into App (onSend, onNew, onSelect, …). One owner means one place to
 * look when something shows the wrong thing.
 */
import { useEffect, useState } from 'react'
import { streamChat } from './api'
import { deleteChat, getChat, listChats, renameChat } from './chatsApi'
import { ChatView } from './components/ChatView'
import { Sidebar } from './components/Sidebar'
import { TracePanel } from './components/TracePanel'
import type { Chat, Message, Run } from './types'

export default function App() {
  const [chatId, setChatId] = useState<string | null>(null) // null = a new, unsaved chat
  const [messages, setMessages] = useState<Message[]>([])
  const [runs, setRuns] = useState<Run[]>([]) // one trace-panel block per message sent
  const [busy, setBusy] = useState(false) // an answer is streaming; disables sending and "New chat"
  const [chats, setChats] = useState<Chat[]>([]) // the sidebar's chat list
  const [chatsError, setChatsError] = useState<string | null>(null) // last chatsApi failure, shown in a banner
  const [drawerOpen, setDrawerOpen] = useState(false) // mobile-only overlay showing the Sidebar

  // Load the chat list once, on mount. A failure here surfaces in the banner rather than being
  // swallowed — the sidebar just stays empty until the owner notices and reloads.
  useEffect(() => {
    listChats()
      .then(setChats)
      .catch((e: unknown) => setChatsError(e instanceof Error ? e.message : String(e)))
  }, [])

  // While the drawer is open, Esc closes it (the backdrop click below handles the other case).
  useEffect(() => {
    if (!drawerOpen) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setDrawerOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [drawerOpen])

  // The two helpers below change only the *last* item in their list — the run or reply currently
  // streaming. They pass a function to the setter rather than a plain value, so React always applies
  // the change to the latest state even when SSE events arrive faster than a render.

  /** Update the run currently streaming (always the last one in `runs`). */
  const updateLastRun = (change: (run: Run) => Run) =>
    setRuns((rs) => [...rs.slice(0, -1), change(rs[rs.length - 1])])

  /** Update the assistant reply currently streaming (always the last message). */
  const updateReply = (change: (reply: Message) => Message) =>
    setMessages((ms) => [...ms.slice(0, -1), change(ms[ms.length - 1])])

  /** Record a failed chatsApi call (list/get/rename/delete) in the dismissible banner. */
  function reportChatsError(e: unknown) {
    setChatsError(e instanceof Error ? e.message : String(e))
  }

  /**
   * Send a message: show your bubble and an empty reply, start a new trace-panel Run, then stream
   * the backend's SSE events into them (docs/contracts.md § 9). Also keeps the sidebar's chat list
   * in step with what the turn just did to it (docs/contracts.md § 10).
   *
   * 1. Add your bubble and an empty assistant bubble that fills up as tokens arrive.
   * 2. Start a new Run for this message. Remember whether this was a brand-new chat (no id yet).
   * 3. Stream the response; each handler updates the reply bubble or the run's trace lines.
   *    `onStart` records the chat id a new chat was just given, so the next message continues it;
   *    for a chat that was new, it also adds that chat to the sidebar right away (optimistically —
   *    the backend row exists by the time `start` fires, but we don't want to wait for a second
   *    round trip just to show it).
   * 4. Re-enable sending once the stream ends, whether it finished, errored, or dropped.
   * 5. Refresh the chat list from the server: this is what actually fixes ordering and title for
   *    both a brand-new chat and one that already existed (its `updated_at` just moved to now).
   */
  async function send(text: string) {
    // 1.
    setMessages((ms) => [...ms, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    // 2.
    setRuns((rs) => [...rs, { prompt: text, lines: [] }])
    const wasNewChat = chatId === null
    setBusy(true)
    // 3.
    await streamChat(text, chatId, {
      onStart: (id, title) => {
        setChatId(id)
        if (wasNewChat) {
          const now = new Date().toISOString()
          setChats((cs) => [{ id, title, created_at: now, updated_at: now }, ...cs])
        }
      },
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
    // 5.
    try {
      setChats(await listChats())
    } catch (e) {
      reportChatsError(e)
    }
  }

  /** Start a fresh chat: forget the open chat's messages and trace runs. No backend call — the
   * chat row is only created once the first message is sent (docs/contracts.md § 10, § 9 `start`). */
  function newChat() {
    if (busy) return
    setChatId(null)
    setMessages([])
    setRuns([])
  }

  /**
   * Open a chat from the sidebar: load its messages and trace runs and make it the active chat.
   * Ignored while busy (switching mid-stream would abandon the run in progress). Closes the mobile
   * drawer either way once a selection is made.
   */
  async function selectChat(id: string) {
    if (busy) return
    try {
      const { chat, messages: loaded, runs: loadedRuns } = await getChat(id)
      setChatId(chat.id)
      setMessages(loaded)
      setRuns(loadedRuns)
      setDrawerOpen(false)
    } catch (e) {
      reportChatsError(e)
    }
  }

  /** Rename a chat and reflect the backend's (trimmed) title back into the sidebar list. */
  async function renameChatById(id: string, title: string) {
    try {
      const updated = await renameChat(id, title)
      setChats((cs) => cs.map((c) => (c.id === id ? updated : c)))
    } catch (e) {
      reportChatsError(e)
    }
  }

  /**
   * Delete a chat and drop it from the sidebar list. Ignored if it's the open chat and a stream is
   * still running; otherwise, deleting the open chat resets the view to a new, unsaved chat.
   */
  async function deleteChatById(id: string) {
    if (busy && id === chatId) return
    try {
      await deleteChat(id)
      setChats((cs) => cs.filter((c) => c.id !== id))
      if (id === chatId) newChat()
    } catch (e) {
      reportChatsError(e)
    }
  }

  const sidebar = (
    <Sidebar
      chats={chats}
      activeId={chatId}
      onSelect={selectChat}
      onNew={newChat}
      onRename={renameChatById}
      onDelete={deleteChatById}
    />
  )

  return (
    <div className="grid h-full grid-rows-[auto_1fr]">
      <header className="flex items-center gap-3 border-b border-rule bg-surface px-6 py-3">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          className="rounded-lg border border-rule px-3 py-1.5 text-sm hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-accent md:hidden"
        >
          Chats
        </button>
        <span className="text-lg font-semibold text-accent">Simba</span>
      </header>
      <div className="grid min-h-0 grid-cols-1 md:grid-cols-[16rem_minmax(0,1fr)] lg:grid-cols-[16rem_minmax(0,1fr)_320px]">
        <div className="hidden md:block">{sidebar}</div>
        <div className="grid min-h-0 grid-rows-[auto_1fr]">
          {chatsError && (
            <div className="flex items-center justify-between gap-3 border-b border-rule bg-surface px-4 py-2 text-sm text-danger">
              <span>{chatsError}</span>
              <button
                type="button"
                onClick={() => setChatsError(null)}
                aria-label="Dismiss error"
                className="shrink-0 rounded px-1 hover:opacity-70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              >
                ✕
              </button>
            </div>
          )}
          <ChatView messages={messages} busy={busy} onSend={send} />
        </div>
        <TracePanel runs={runs} busy={busy} />
      </div>
      {/* Mobile drawer: the Sidebar as an overlay, closed by the backdrop, Esc (effect above), or
          selecting a chat (selectChat above). Only reachable below md; at md+ the Sidebar already
          sits in the grid, so this stays unrendered. */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
          <div className="relative h-full w-64">{sidebar}</div>
        </div>
      )}
    </div>
  )
}
