/**
 * MemoryPage.tsx — the Memory tab's page (#87, D49): everything Simba remembers about you, wide and
 * easy to read, grouped the way the memory is used.
 *
 * It only reads. Memory changes by talking to Simba (D46): "what do you remember?", "actually I moved
 * to Berlin", "forget that…". So there are no add / edit / delete buttons here — the page says so at
 * the bottom. App.tsx owns the facts (fetched from GET /api/memory/facts) and passes them in.
 *
 * The first two sections are marked "always in Simba's prompt": they are exactly what Simba reads on
 * every turn (memory.ALWAYS_LOADED, ≤ 15 each). The rest is looked up when a chat needs it.
 */
import { useState } from 'react'
import type { Chat, Fact, FactKind } from '../types'

type Props = {
  facts: Fact[] // every saved fact, newest change first
  chats: Chat[] // to show which chat a fact came from, by title
  onOpenChat: (id: string) => void // a "from chat" link was clicked
}

/** Sections in reading order: what each kind means, and whether it's in every prompt. */
const SECTIONS: { kind: FactKind; title: string; hint: string; always: boolean }[] = [
  { kind: 'feedback', title: 'How you want me to work', hint: 'Learned rules: corrections and preferences, with the reason', always: true },
  { kind: 'user', title: 'About you', hint: 'Who you are and what you like', always: true },
  { kind: 'project', title: 'Projects', hint: 'Ongoing work, goals and dates', always: false },
  { kind: 'reference', title: 'References', hint: 'Where things live', always: false },
]

// How many facts of an always-loaded kind reach the prompt (memory.CORE_PROFILE_LIMIT).
const ALWAYS_LOADED_LIMIT = 15

/** "2026-09-30T14:03:11Z" -> "30 Sep 2026", in the reader's own locale. */
function shortDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/**
 * Renders the search box, the four sections and the "Past chats" placeholder.
 *
 * 1. Search keeps the facts whose text or reason contains every typed word (any order, any case).
 * 2. Each section lists its facts; an always-loaded section marks the ones beyond the first 15 as
 *    "not in the prompt right now", so the label never overstates what Simba sees.
 * 3. Each fact shows its reason, the chat it came from (a link that opens it) and when it last changed.
 */
export function MemoryPage({ facts, chats, onOpenChat }: Props) {
  const [query, setQuery] = useState('')
  const titles = new Map(chats.map((c) => [c.id, c.title]))

  // 1.
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = facts.filter((f) => words.every((w) => `${f.text} ${f.why ?? ''}`.toLowerCase().includes(w)))

  return (
    <main className="h-full overflow-y-auto bg-surface">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6 sm:px-8">
        <header className="flex flex-col gap-3">
          <h1 className="font-serif text-2xl font-semibold text-ink">What Simba remembers</h1>
          <label htmlFor="memory-search" className="sr-only">
            Search memory
          </label>
          <input
            id="memory-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search memory…"
            className="rounded-full border-[1.5px] border-ink bg-surface px-4 py-2 text-sm text-ink placeholder:text-muted"
          />
        </header>

        {/* 2. */}
        {SECTIONS.map(({ kind, title, hint, always }) => {
          const all = facts.filter((f) => f.kind === kind)
          const inSection = shown.filter((f) => f.kind === kind)
          return (
            <section key={kind} aria-label={title} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">{title}</h2>
                <span className="text-xs text-muted">({all.length})</span>
                {always && <span className="rounded-full bg-mint px-2 text-xs text-ink">always in Simba's prompt</span>}
              </div>
              <p className="text-xs text-muted">{hint}</p>
              {inSection.length === 0 ? (
                <p className="text-sm text-muted">{words.length ? 'Nothing matches.' : 'Nothing yet.'}</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {inSection.map((fact) => {
                    const beyondPrompt = always && all.indexOf(fact) >= ALWAYS_LOADED_LIMIT
                    const source = fact.source_chat_id
                    return (
                      // 3.
                      <li key={fact.id} className="rounded-xl border border-rule bg-bg px-4 py-3">
                        <p className="text-ink">{fact.text}</p>
                        {fact.why && <p className="mt-1 text-sm text-muted">Why: {fact.why}</p>}
                        <p className="mt-1 flex flex-wrap gap-x-2 text-xs text-muted">
                          {source && titles.has(source) ? (
                            <button type="button" onClick={() => onOpenChat(source)} className="underline decoration-dotted hover:text-ink">
                              from “{titles.get(source)}”
                            </button>
                          ) : (
                            <span>{source ? 'from a deleted chat' : 'source unknown'}</span>
                          )}
                          <span aria-hidden="true">·</span>
                          <span>{shortDate(fact.updated_at)}</span>
                          {beyondPrompt && <span>· not in the prompt right now (only the newest 15 are)</span>}
                        </p>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          )
        })}

        <section aria-label="Past chats" className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">Past chats</h2>
          <p className="text-sm text-muted">Chat summaries arrive with the next memory step (M3).</p>
        </section>

        <p className="border-t border-rule pt-4 text-sm text-muted">
          To change what Simba remembers, just tell it in a chat — for example “actually, I moved to Berlin” or
          “forget that I work at Acme”. It asks before forgetting anything.
        </p>
      </div>
    </main>
  )
}
