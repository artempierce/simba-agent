/**
 * MobileDrawer.tsx — the Sidebar's mobile overlay: a full-screen backdrop plus a slide-in panel
 * (docs/contracts.md § 11). Used only below the md breakpoint; App.tsx renders the Sidebar as this
 * drawer's `children` when `open` is true, and directly in the page grid at md+ (not through here).
 *
 * A modal-style overlay needs the same bookkeeping every time — close on backdrop click or Escape,
 * move focus in on open and back on close — so it all lives here instead of in App.tsx, which only
 * has to track one boolean (`open`) and pass it down.
 */
import { useEffect, useRef } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'

/** What the drawer needs from its owner: whether it's open, how to ask to close it, and its content
 * (the Sidebar). */
type Props = {
  open: boolean
  onClose: () => void
  children: ReactNode
}

/**
 * Renders the backdrop + panel while `open`; renders nothing otherwise.
 *
 * 1. Remember whatever had focus right before the drawer opened, so it can be handed back on close —
 *    this is what lets Tab/shift-Tab and screen readers return exactly where the user was, instead of
 *    falling back to `<body>`. On first mount (`open` starts false) there's nothing to restore focus
 *    to yet, so this safely does nothing.
 * 2. On open, move focus to the panel's first button (the Sidebar's "+ New chat"); on close, restore
 *    the focus step 1 saved.
 * 3. Escape closes the drawer — but only if nothing *inside* it already handled the key. The Sidebar's
 *    own onKeyDown calls `e.preventDefault()` when Escape closes one of its own rows' menu/rename/
 *    delete mode; since that handler sits closer to the key press, it runs first, so by the time this
 *    one sees the event `e.defaultPrevented` already reflects that.
 */
export function MobileDrawer({ open, onClose, children }: Props) {
  const panelRef = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)

  // 1, 2.
  useEffect(() => {
    if (open) {
      previouslyFocused.current = document.activeElement as HTMLElement | null
      panelRef.current?.querySelector('button')?.focus()
    } else {
      previouslyFocused.current?.focus()
    }
  }, [open])

  if (!open) return null

  // 3.
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape' && !e.defaultPrevented) onClose()
  }

  return (
    <div className="fixed inset-0 z-50 md:hidden" onKeyDown={onKeyDown}>
      <div className="absolute inset-0 bg-ink/40" onClick={onClose} aria-hidden="true" />
      <div ref={panelRef} role="dialog" aria-modal="true" aria-label="Chats" className="relative h-full w-64">
        {children}
      </div>
    </div>
  )
}
