/**
 * MemoryPanel.tsx — the Memory tab (#80, D44): what Simba remembers about you, grouped by kind,
 * with add, edit, delete and "Delete all".
 *
 * Like Sidebar.tsx it holds no data of its own: App.tsx owns the facts and the calls to the backend
 * (memoryApi.ts); this component renders what it's given and reports what you did through its props.
 * Its only local state is UI state — the add form, which fact is being edited, and whether the
 * "Delete all" question is showing.
 *
 * Why "Delete all" asks inline instead of `window.confirm`: the same reason as the chat rows — the
 * question is ordinary page text a screen reader reads, and artifacts/embeds may block dialogs.
 */
import { useRef, useState } from 'react'
import type { Fact, FactKind } from '../types'

type Props = {
  facts: Fact[] // every saved fact, in the order to show them (newest change first)
  onAdd: (kind: FactKind, text: string) => void
  onEdit: (id: number, text: string) => void
  onDelete: (id: number) => void
  onDeleteAll: () => void
}

/** The kinds in the order they're listed, each with the label and hint shown to you. */
const KINDS: { kind: FactKind; label: string; hint: string }[] = [
  { kind: 'user', label: 'About you', hint: 'Always in Simba’s prompt (the newest 15)' },
  { kind: 'feedback', label: 'How you like to work', hint: 'Corrections and preferences' },
  { kind: 'project', label: 'Projects', hint: 'Ongoing work and dates' },
  { kind: 'reference', label: 'References', hint: 'Links and where things live' },
]

// Same limit as the backend (memory.MAX_FACT_CHARS), so the form stops you before the server does.
const MAX_FACT_CHARS = 300

/**
 * Renders the add form, the facts grouped by kind, and the "Delete all" control.
 *
 * 1. Add: a kind picker and a text box; "Save" sends the trimmed text if it isn't empty.
 * 2. Each kind with facts gets a heading; each fact a row with Edit and Delete.
 * 3. Edit swaps the row's text for an input: Enter saves, Escape cancels. Both just leave the input;
 *    its blur is the one place that saves, so a save can't happen twice, and Escape marks the edit
 *    as cancelled first so the blur that follows doesn't save it.
 * 4. "Delete all" first turns into "Forget everything? Yes / Cancel".
 */
export function MemoryPanel({ facts, onAdd, onEdit, onDelete, onDeleteAll }: Props) {
  const [kind, setKind] = useState<FactKind>('user')
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null)
  const [confirmAll, setConfirmAll] = useState(false)
  const cancelEdit = useRef(false) // set by Escape, read by the blur that follows

  // 1.
  function save(e: React.FormEvent) {
    e.preventDefault()
    const text = draft.trim()
    if (!text) return
    onAdd(kind, text)
    setDraft('')
  }

  // 3.
  function finishEdit() {
    if (!cancelEdit.current && editing && editing.text.trim()) onEdit(editing.id, editing.text.trim())
    cancelEdit.current = false
    setEditing(null)
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <form onSubmit={save} className="flex flex-col gap-2 rounded-xl border-[1.5px] border-ink bg-surface p-2.5">
        <label htmlFor="memory-kind" className="text-xs font-medium text-muted">
          Remember something
        </label>
        <select
          id="memory-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as FactKind)}
          className="rounded-lg border border-rule bg-surface px-2 py-1 text-sm text-ink"
        >
          {KINDS.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
        <textarea
          id="memory-text"
          aria-label="Fact to remember"
          value={draft}
          maxLength={MAX_FACT_CHARS}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. I mostly work in Python"
          rows={2}
          className="resize-none rounded-lg border border-rule bg-surface px-2 py-1 text-sm text-ink placeholder:text-muted"
        />
        <button
          type="submit"
          disabled={!draft.trim()}
          className="self-end rounded-full bg-accent px-3 py-1 text-sm font-medium text-accent-ink hover:opacity-90 disabled:opacity-40"
        >
          Save
        </button>
      </form>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
        {facts.length === 0 && (
          <p className="px-1 text-sm text-muted">Nothing remembered yet. Add a fact above.</p>
        )}
        {/* 2. */}
        {KINDS.map(({ kind: k, label, hint }) => {
          const group = facts.filter((f) => f.kind === k)
          if (group.length === 0) return null
          return (
            <section key={k} aria-label={label}>
              <h3 className="px-1 text-xs font-semibold tracking-wide text-ink uppercase">{label}</h3>
              <p className="px-1 text-xs text-muted">{hint}</p>
              <ul className="mt-1 flex flex-col gap-1">
                {group.map((fact) => (
                  <li key={fact.id} className="rounded-lg bg-surface px-2 py-1.5 text-sm text-ink">
                    {editing?.id === fact.id ? (
                      <input
                        autoFocus
                        aria-label="Edit fact"
                        value={editing.text}
                        maxLength={MAX_FACT_CHARS}
                        onChange={(e) => setEditing({ id: fact.id, text: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') cancelEdit.current = true
                          if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur()
                        }}
                        onBlur={finishEdit}
                        className="w-full rounded border border-rule px-1 py-0.5"
                      />
                    ) : (
                      <>
                        <p className="break-words">{fact.text}</p>
                        <div className="mt-1 flex gap-3 text-xs">
                          <button type="button" onClick={() => setEditing({ id: fact.id, text: fact.text })} className="text-muted hover:text-ink">
                            Edit
                          </button>
                          <button type="button" onClick={() => onDelete(fact.id)} aria-label={`Forget: ${fact.text}`} className="text-muted hover:text-danger">
                            Delete
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )
        })}
      </div>

      {/* 4. */}
      {facts.length > 0 &&
        (confirmAll ? (
          <div className="flex items-center justify-between gap-2 rounded-lg border border-danger px-2 py-1.5 text-sm text-danger">
            <span>Forget everything?</span>
            <span className="flex gap-2">
              <button type="button" onClick={() => { onDeleteAll(); setConfirmAll(false) }} className="font-semibold">
                Yes
              </button>
              <button type="button" onClick={() => setConfirmAll(false)} className="text-ink">
                Cancel
              </button>
            </span>
          </div>
        ) : (
          <button type="button" onClick={() => setConfirmAll(true)} className="self-start px-1 text-xs text-muted hover:text-danger">
            Delete all memory
          </button>
        ))}
    </div>
  )
}
