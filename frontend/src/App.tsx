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
 * drawer instead (closed by selecting a chat, Esc, "+ New chat", or clicking the backdrop).
 *
 * All state lives here and flows down to the panes as props; they never talk to the backend
 * themselves, only call back into App (onSend, onNew, onSelect, …). One owner means one place to
 * look when something shows the wrong thing.
 *
 * A few refs mirror state that an async handler needs to re-check *after* an `await`, because the
 * value its own closure captured when it started can go stale while it was waiting: `busyRef`
 * (mirrors `busy`), `chatIdRef` (mirrors `chatId`), `requestedChatRef` (the chat selectChat was most
 * recently asked to open) and `chatsSeqRef` (which chats-list-changing call was the latest one).
 */
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
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

  // See the file header comment: these mirror state for async handlers to re-check after an await.
  const busyRef = useRef(false)
  const chatIdRef = useRef<string | null>(null)
  const requestedChatRef = useRef<string | null>(null)
  const chatsSeqRef = useRef(0)

  // Refs for the mobile drawer's focus handling (item 3 below): the drawer panel itself (to focus
  // its first button on open, and to look for an open row menu on Escape), the header's "Chats"
  // button (to return focus to on close), and whether the drawer was open last render (so the
  // close-focus effect doesn't fire on first mount, before it's ever been opened).
  const drawerRef = useRef<HTMLDivElement>(null)
  const chatsButtonRef = useRef<HTMLButtonElement>(null)
  const wasDrawerOpenRef = useRef(false)

  function setBusyState(value: boolean) {
    busyRef.current = value
    setBusy(value)
  }

  function setChatIdBoth(id: string | null) {
    chatIdRef.current = id
    setChatId(id)
  }

  /** Record a failed chatsApi call (list/get/rename/delete) in the dismissible banner. */
  function reportChatsError(e: unknown) {
    setChatsError(e instanceof Error ? e.message : String(e))
  }

  /**
   * Fetch the chat list and apply it — unless a newer chats-changing call (another refresh, a
   * rename, or a delete) started since this one did, in which case this response is stale and is
   * dropped instead of overwriting the newer state.
   */
  async function refreshChats() {
    const seq = ++chatsSeqRef.current
    try {
      const fresh = await listChats()
      if (chatsSeqRef.current === seq) setChats(fresh)
    } catch (e) {
      if (chatsSeqRef.current === seq) reportChatsError(e)
    }
  }

  // Load the chat list once, on mount. A failure here surfaces in the banner rather than being
  // swallowed — the sidebar just stays empty until the owner notices and reloads. (oxlint's
  // react(set-state-in-effect) warns here because refreshChats eventually calls setChats; that's
  // exactly the standard "fetch on mount" pattern, so the warning is expected and safe to keep.)
  useEffect(() => {
    refreshChats()
  }, [])

  // Move focus when the drawer opens (into its first button) or closes (back to the button that
  // opened it) — see the drawerRef/chatsButtonRef/wasDrawerOpenRef comment above. Skipped on first
  // mount (drawerOpen starts false and has never been open) so the composer keeps its own autoFocus.
  useEffect(() => {
    if (drawerOpen) {
      wasDrawerOpenRef.current = true
      drawerRef.current?.querySelector('button')?.focus()
    } else if (wasDrawerOpenRef.current) {
      wasDrawerOpenRef.current = false
      chatsButtonRef.current?.focus()
    }
  }, [drawerOpen])

  // The two helpers below change only the *last* item in their list — the run or reply currently
  // streaming. They pass a function to the setter rather than a plain value, so React always applies
  // the change to the latest state even when SSE events arrive faster than a render. Each is a no-op
  // on an empty list: that can happen if selectChat swapped in a freshly loaded chat's (possibly
  // empty) runs/messages right as a trace/token event for the *previous* chat's stream arrived.

  /** Update the run currently streaming (always the last one in `runs`), if there is one. */
  const updateLastRun = (change: (run: Run) => Run) =>
    setRuns((rs) => (rs.length === 0 ? rs : [...rs.slice(0, -1), change(rs[rs.length - 1])]))

  /** Update the assistant reply currently streaming (always the last message), if there is one. */
  const updateReply = (change: (reply: Message) => Message) =>
    setMessages((ms) => (ms.length === 0 ? ms : [...ms.slice(0, -1), change(ms[ms.length - 1])]))

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
    setBusyState(true)
    // 3.
    await streamChat(text, chatId, {
      onStart: (id, title) => {
        setChatIdBoth(id)
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
    setBusyState(false)
    // 5.
    await refreshChats()
  }

  /** Start a fresh chat: forget the open chat's messages and trace runs, and close the mobile drawer
   * if it was open (its "+ New chat" button routes here too). No backend call — the chat row is only
   * created once the first message is sent (docs/contracts.md § 10, § 9 `start`). */
  function newChat() {
    if (busyRef.current) return
    requestedChatRef.current = null
    setChatIdBoth(null)
    setMessages([])
    setRuns([])
    setDrawerOpen(false)
  }

  /**
   * Open a chat from the sidebar: load its messages and trace runs and make it the active chat.
   * Ignored while busy (switching mid-stream would abandon the run in progress). A response that
   * comes back after busy became true, or after a *different* chat (or "New chat") was requested in
   * the meantime, is stale and is dropped instead of overwriting whatever's now on screen. Closes
   * the mobile drawer once the chat has actually loaded — not on failure, so the banner and the
   * drawer both stay up to let the user see the error and try again.
   */
  async function selectChat(id: string) {
    if (busyRef.current) return
    requestedChatRef.current = id
    try {
      const { chat, messages: loaded, runs: loadedRuns } = await getChat(id)
      if (busyRef.current || requestedChatRef.current !== id) return
      setChatIdBoth(chat.id)
      setMessages(loaded)
      setRuns(loadedRuns)
      setDrawerOpen(false)
    } catch (e) {
      if (busyRef.current || requestedChatRef.current !== id) return
      reportChatsError(e)
    }
  }

  /** Rename a chat and reflect the backend's (trimmed) title back into the sidebar list. */
  async function renameChatById(id: string, title: string) {
    chatsSeqRef.current++ // invalidate any in-flight refreshChats; our own update below is final
    try {
      const updated = await renameChat(id, title)
      setChats((cs) => cs.map((c) => (c.id === id ? updated : c)))
    } catch (e) {
      reportChatsError(e)
    }
  }

  /**
   * Delete a chat and drop it from the sidebar list. Ignored if it's the open chat and a stream is
   * still running (checked via the refs, not the `busy`/`chatId` closures, which could be stale by
   * the time this runs); otherwise, deleting the open chat resets the view to a new, unsaved chat —
   * unless a stream started for it while the delete was in flight, in which case that's left alone.
   */
  async function deleteChatById(id: string) {
    if (busyRef.current && id === chatIdRef.current) return
    chatsSeqRef.current++ // invalidate any in-flight refreshChats; our own update below is final
    try {
      await deleteChat(id)
      setChats((cs) => cs.filter((c) => c.id !== id))
      if (id === chatIdRef.current && !busyRef.current) newChat()
    } catch (e) {
      reportChatsError(e)
    }
  }

  /**
   * Escape closes the drawer — but not when it's already doing something *inside* the Sidebar: its
   * inline rename box (an `<input>`) and its row "⋯" menu (`aria-expanded="true"` while open) both
   * use Escape to back out of just that, not to leave the drawer. Checking here, on the drawer's own
   * container, instead of a `document`-wide listener, is what makes that distinction possible
   * without Sidebar needing to say "I already handled this".
   */
  function onDrawerKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'Escape' || e.defaultPrevented) return
    if ((e.target as HTMLElement).tagName === 'INPUT') return
    if (drawerRef.current?.querySelector('[aria-expanded="true"]')) return
    setDrawerOpen(false)
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
          ref={chatsButtonRef}
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
        <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)]">
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
      {/* Mobile drawer: the Sidebar as an overlay, closed by the backdrop, Escape (onDrawerKeyDown
          above), selecting a chat, or "+ New chat" (both inside selectChat/newChat). Only reachable
          below md; at md+ the Sidebar already sits in the grid, so this stays unrendered. */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden" onKeyDown={onDrawerKeyDown}>
          <div className="absolute inset-0 bg-ink/40" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
          <div ref={drawerRef} role="dialog" aria-modal="true" aria-label="Chats" className="relative h-full w-64">
            {sidebar}
          </div>
        </div>
      )}
    </div>
  )
}
