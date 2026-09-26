/**
 * Sidebar.tsx — the left pane (step 6): "New chat" plus the list of saved chats, per
 * docs/contracts.md § 11. App.tsx owns the chat data and where the sidebar sits on the page; this
 * component only renders what it's given and reports clicks back through its props.
 *
 * Each row has a "⋯" button that opens a small inline popover (Rename / Delete). Rename swaps the
 * row for a text input; Delete swaps it for an inline "Delete this chat? Yes / Cancel" — never
 * `window.confirm` — so the row itself carries the question, as plain text a screen reader reads
 * like any other content (no separate live region).
 */
import { useEffect, useRef, useState } from 'react'
import type { Chat } from '../types'

/** What the sidebar needs from its owner, and how it reports interaction back up. */
type Props = {
  chats: Chat[] // chats to list, in the order the caller wants them shown
  activeId: string | null // the open chat, highlighted; null when nothing is open yet
  onSelect: (id: string) => void // a chat row was clicked
  onNew: () => void // "New chat" was clicked
  onRename: (id: string, title: string) => void // a rename was confirmed with a valid title
  onDelete: (id: string) => void // "Yes" was clicked in a row's delete confirmation
}

/** Which row is doing something out of the ordinary right now, and which row it is. */
type RowMode = { kind: 'menu' | 'rename' | 'delete'; id: string }

/**
 * Renders the chat list and its per-row "⋯" menu.
 * Inputs/outputs: see `Props` above; this component holds no chat data itself, only the small bit
 * of local UI state (which row's menu/rename/delete is open) needed to drive that interaction.
 *
 * Main logic, per row:
 * 1. While the "⋯" menu is open, close it on Esc or a click outside that row.
 * 2. Commit (or drop) a rename and always close the input.
 * 3. Render an open rename as a text input in place of the title/⋯ pair.
 * 4. Render an open delete confirmation as inline "Delete this chat? Yes / Cancel".
 * 5. Otherwise render the normal row: a title button plus a "⋯" button that opens the menu.
 *
 * Whenever a row leaves menu/rename/delete mode (step 1's Esc/outside-click, or Cancel), focus
 * returns to that row's "⋯" button so keyboard/screen-reader focus never falls back to `<body>`.
 */
export function Sidebar({ chats, activeId, onSelect, onNew, onRename, onDelete }: Props) {
  const [mode, setMode] = useState<RowMode | null>(null)
  const [renameValue, setRenameValue] = useState('')
  // Each row's "⋯" button, keyed by chat id, so focus can be sent back to it (see the effect below).
  const menuButtons = useRef(new Map<string, HTMLButtonElement>())
  // The row that was in menu/rename/delete mode most recently, so that when `mode` goes back to
  // null we know whose "⋯" button should get focus back.
  const lastRowId = useRef<string | null>(null)

  // 1. While the "⋯" menu is open, close it on Esc or on any click outside that row.
  useEffect(() => {
    if (mode?.kind !== 'menu') return
    function onPointerDown(e: MouseEvent) {
      const row = (e.target as HTMLElement).closest('[data-chat-row]')
      if (!row || row.getAttribute('data-chat-row') !== mode?.id) setMode(null)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setMode(null)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [mode])

  // Track which row is/was in a special mode, and once it goes back to null, hand focus back to
  // that row's "⋯" button — otherwise Esc/Cancel would drop keyboard focus onto `<body>`.
  useEffect(() => {
    if (mode) {
      lastRowId.current = mode.id
      return
    }
    if (lastRowId.current) menuButtons.current.get(lastRowId.current)?.focus()
  }, [mode])

  /** Opens rename mode for a chat, seeding the input with its current title. */
  function startRename(chat: Chat) {
    setRenameValue(chat.title)
    setMode({ kind: 'rename', id: chat.id })
  }

  /**
   * 2. Commits (or silently drops) a rename and always closes the input.
   * Trims the value first; an empty result cancels rather than saving, matching the 1-80 character
   * rule the backend enforces (docs/contracts.md § 10) — there's nothing valid to send otherwise.
   */
  function saveRename(id: string) {
    const trimmed = renameValue.trim()
    if (trimmed.length >= 1 && trimmed.length <= 80) onRename(id, trimmed)
    setMode(null)
  }

  return (
    <div className="flex h-full w-64 flex-col gap-2 bg-bg p-3">
      <button
        type="button"
        onClick={onNew}
        className="rounded-md border border-rule bg-surface px-3 py-2 text-left text-sm font-medium text-ink hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      >
        + New chat
      </button>

      {chats.length === 0 && <p className="px-2 py-1 text-sm text-muted">No chats yet — start one above.</p>}

      <ul className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        {chats.map((chat) => {
          const active = chat.id === activeId
          const menuOpen = mode?.kind === 'menu' && mode.id === chat.id

          // 3. Rename mode: the row becomes a text input in place of the title/⋯ pair.
          if (mode?.kind === 'rename' && mode.id === chat.id) {
            return (
              <li key={chat.id} data-chat-row={chat.id}>
                <input
                  autoFocus
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') e.currentTarget.blur() // onBlur below saves it
                    else if (e.key === 'Escape') setMode(null) // React 19 doesn't fire onBlur for this removal
                  }}
                  onBlur={() => saveRename(chat.id)}
                  maxLength={80}
                  aria-label={`Rename chat: ${chat.title}`}
                  className="w-full rounded-md border border-accent bg-surface px-2 py-1.5 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                />
              </li>
            )
          }

          // 4. Delete mode: the row becomes an inline confirmation, never window.confirm.
          if (mode?.kind === 'delete' && mode.id === chat.id) {
            return (
              <li
                key={chat.id}
                data-chat-row={chat.id}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm"
              >
                <span className="min-w-0 flex-1 truncate text-muted">Delete this chat?</span>
                <button
                  type="button"
                  onClick={() => {
                    onDelete(chat.id)
                    setMode(null)
                  }}
                  className="font-medium text-danger focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                >
                  Yes
                </button>
                <button
                  type="button"
                  autoFocus
                  onClick={() => setMode(null)}
                  className="text-muted hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                >
                  Cancel
                </button>
              </li>
            )
          }

          // 5. Normal row: title button (selects the chat) + "⋯" button (opens the menu below it).
          return (
            <li key={chat.id} data-chat-row={chat.id}>
              <div className={`flex items-stretch rounded-md ${active ? 'bg-raised' : 'hover:bg-raised'}`}>
                <button
                  type="button"
                  onClick={() => onSelect(chat.id)}
                  aria-current={active ? 'page' : undefined}
                  className={`min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
                    active ? 'font-semibold text-ink' : 'text-ink'
                  }`}
                >
                  {chat.title}
                </button>
                <button
                  type="button"
                  ref={(el) => {
                    if (el) menuButtons.current.set(chat.id, el)
                    else menuButtons.current.delete(chat.id)
                  }}
                  onClick={() => setMode(menuOpen ? null : { kind: 'menu', id: chat.id })}
                  aria-label={`Options for ${chat.title}`}
                  aria-haspopup="true"
                  aria-expanded={menuOpen}
                  className="shrink-0 rounded-md px-2 text-muted hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                >
                  ⋯
                </button>
              </div>
              {menuOpen && (
                <div className="ml-2 mt-0.5 flex gap-1 rounded-md border border-rule bg-surface px-2 py-1">
                  <button
                    type="button"
                    onClick={() => startRename(chat)}
                    className="rounded px-2 py-1 text-sm text-ink hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode({ kind: 'delete', id: chat.id })}
                    className="rounded px-2 py-1 text-sm text-danger hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    Delete
                  </button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
