/**
 * TracePanel.tsx — the right pane: a dark "terminal" log of what each backend graph node did for
 * your message (docs/contracts.md § 6, § 11). This is where Simba's guard/intent/reason/generate
 * steps become visible instead of a black box. Ported from art-lab's TracePanel and trimmed: no
 * trace IDs, no per-message replay, no extra statuses beyond ok/blocked/error.
 *
 * One block per Run (one Run per message you sent), one line per trace event, e.g.
 *   ✓ guard        pass · 38 chars                                            1ms
 *   ✓ intent       safe · "weekend ideas for Lisbon"                       640ms
 *   ✓ generate     42 tokens out                                           810ms
 *   612 tok · $0.0007 · 1.5s                            ← footer, once the run finishes
 *
 * Lines come straight from the backend's `trace` SSE events; a new stage only needs a colour below.
 */
import { useEffect, useRef } from 'react'
import type { Run, TraceLine } from '../types'

/** Trace stage → text colour (index.css `--color-t-*`, chosen to read on the dark terminal background). */
const STAGE_COLOR: Record<string, string> = {
  guard: 'text-t-guard',
  intent: 'text-t-intent',
  reason: 'text-t-reason',
  generate: 'text-t-generate',
  refuse: 'text-t-refuse',
  echo: 'text-t-echo', // step 1 only, until the real nodes land
}

/** Trace status → icon shown before the line. `flagged` (#8) means "passed, but the local classifier
 * raised a flag for the intent check to weigh" — a warning, not a failure. */
const STATUS_ICON: Record<TraceLine['status'], string> = { ok: '✓', blocked: '⛔', error: '✕', flagged: '⚑' }

/**
 * The colour of one trace line. Blocked and error lines always use the refusal colour, whatever the
 * stage, so a problem stands out at a glance. A flagged line keeps its stage's own colour: the message
 * still went through, and the ⚑ icon already marks it.
 */
function lineColor(line: TraceLine): string {
  if (line.status === 'blocked' || line.status === 'error') return 'text-t-refuse'
  return STAGE_COLOR[line.stage] ?? 'text-term-ink'
}

/** Short token count for the footer: 812 → "812", 1234 → "1.2k". */
function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

/**
 * The trace column: an explanatory hint until the first message, then one RunBlock per message sent
 * this session, newest at the bottom. `busy` marks whether the last run is still streaming — only it
 * may show "… running". Hidden below 1024px (Tailwind's `lg`): the trace panel is a bonus view, not
 * required to chat with Simba.
 *
 * 1. Keep the newest line in view as runs and lines are added.
 * 2. Show the explanatory hint until the first message, then one RunBlock per Run.
 */
export function TracePanel({ runs, busy }: { runs: Run[]; busy: boolean }) {
  const endRef = useRef<HTMLDivElement>(null)

  // 1.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [runs])

  return (
    <aside
      aria-label="Trace"
      className="hidden min-h-0 flex-col border-l border-rule bg-term font-mono text-[12.5px] text-term-ink lg:flex"
    >
      <header className="border-b border-term-rule px-4 py-3.5 text-xs tracking-widest text-term-dim uppercase">
        Trace
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* 2. */}
        {runs.length === 0 && (
          <p className="leading-relaxed text-term-dim">
            Send a message and each step Simba takes shows up here — the guard, the safety check, the plan and the
            reply — with tokens, cost and time for every step.
          </p>
        )}
        {runs.map((run, i) => (
          // Only the last run can still be running.
          <RunBlock key={i} run={run} running={busy && i === runs.length - 1} />
        ))}
        <div ref={endRef} />
      </div>
    </aside>
  )
}

/** One run's card: your prompt, one line per trace event, then a running/error line, then the footer. */
function RunBlock({ run, running }: { run: Run; running: boolean }) {
  return (
    <section className="rounded-lg border border-term-rule bg-term p-3 font-mono text-[12.5px] text-term-ink">
      <div className="mb-2 truncate text-term-dim">› {run.prompt}</div>
      <ul className="space-y-1.5">
        {run.lines.map((line, i) => {
          const color = lineColor(line)
          return (
            <li key={i} className="grid grid-cols-[1.4em_minmax(0,1fr)_auto] gap-x-2">
              <span className={color}>{STATUS_ICON[line.status] ?? '•'}</span>
              <span className={`font-medium ${color}`}>{line.stage}</span>
              <span className="col-span-2 col-start-2 row-start-2 break-words">{line.detail}</span>
              <span className="col-start-3 row-start-1 text-right text-term-dim tabular-nums">{line.ms}ms</span>
            </li>
          )
        })}
        {running && !run.summary && !run.error && <li className="animate-pulse text-term-dim">… running</li>}
        {run.error && <li className="break-words text-t-refuse">✕ {run.error}</li>}
      </ul>
      {run.summary && (
        <div className="mt-2 border-t border-dashed border-term-rule pt-2 text-term-dim tabular-nums">
          {formatTokens(run.summary.input_tokens + run.summary.output_tokens)} tok · $
          {run.summary.cost_usd.toFixed(4)} · {(run.summary.ms / 1000).toFixed(1)}s
        </div>
      )}
    </section>
  )
}
