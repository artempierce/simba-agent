/**
 * LeftPane.tsx — the left column with two tabs, Chats and Memory (#80, D44). It only switches
 * between the two panels App.tsx hands it; the panels themselves are Sidebar.tsx and MemoryPanel.tsx.
 *
 * The tabs use the ARIA tab pattern (role="tablist" / "tab" / "tabpanel", aria-selected), so a screen
 * reader announces "Memory, tab, 2 of 2" instead of two unexplained buttons.
 */
import type { ReactNode } from 'react'

export type LeftTab = 'chats' | 'memory'

type Props = {
  tab: LeftTab // which panel is showing
  onTab: (tab: LeftTab) => void // a tab was clicked
  chats: ReactNode // the Chats panel (Sidebar)
  memory: ReactNode // the Memory panel (MemoryPanel)
}

const TABS: { id: LeftTab; label: string }[] = [
  { id: 'chats', label: 'Chats' },
  { id: 'memory', label: 'Memory' },
]

/** Renders the tab row and the chosen panel. */
export function LeftPane({ tab, onTab, chats, memory }: Props) {
  return (
    <div className="flex h-full w-64 flex-col bg-bg">
      <div role="tablist" aria-label="Left pane" className="flex gap-1 px-3 pt-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => onTab(t.id)}
            className={`flex-1 rounded-full border-[1.5px] px-3 py-1 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink ${
              tab === t.id ? 'border-ink bg-surface text-ink' : 'border-transparent text-muted hover:text-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="min-h-0 flex-1">
        {tab === 'chats' ? chats : memory}
      </div>
    </div>
  )
}
