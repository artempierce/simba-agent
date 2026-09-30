/**
 * InfoPill.tsx — a small pill in the header saying which model Simba runs on and whether web search
 * is on (#57), e.g. "haiku-4-5 · search on".
 *
 * Why it exists: with no TAVILY_API_KEY, Simba quietly has no search tool, and the only way to find
 * out used to be asking it. The pill shows the server's real setup (GET /api/info) at a glance.
 */
import type { ServerInfo } from '../types'

/**
 * Render the pill, or nothing until the info has loaded (or if it failed — the header just stays
 * as it was; this is a hint, not something the page depends on).
 *
 * The model name drops its "claude-" prefix to stay short: "claude-haiku-4-5" -> "haiku-4-5".
 * "search on" gets the mint fill so the two states differ by more than one word.
 */
export function InfoPill({ info }: { info: ServerInfo | null }) {
  if (!info) return null
  const model = info.model === 'fake' ? 'fake model' : info.model.replace(/^claude-/, '')
  return (
    <div
      className="hidden items-center gap-1.5 rounded-full border-[1.5px] border-ink bg-surface px-3 py-1 font-mono text-xs text-ink shadow-sm sm:flex"
      title={`Model: ${info.model} · web search ${info.web_search ? 'on' : 'off'} · budget $${info.chat_budget_usd.toFixed(2)} per chat`}
    >
      <span>{model}</span>
      <span aria-hidden="true" className="text-muted">·</span>
      <span className={info.web_search ? 'rounded-full bg-mint px-1.5' : 'text-muted'}>
        search {info.web_search ? 'on' : 'off'}
      </span>
    </div>
  )
}
