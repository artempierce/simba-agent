/**
 * TracePanel.tsx — the right pane: a log of what each backend graph node did for your message
 * (docs/contracts.md § 6, § 11). This is where Simba's guard/intent/reason/generate steps become
 * visible instead of a black box.
 *
 * Restyled 2026-09-27 (docs/visual-style.md → "Trace panel", Sol: "match design for right trace
 * part"): it used to be its own dark terminal column; now it sits on the same warm paper background
 * as the sidebar, and each run is a plain white card like everywhere else in the app. A trace event's
 * stage now shows as a small pastel pill (one pastel per stage, reusing the same tokens as the
 * empty-state suggestion cards) instead of coloured text, so the panel reads as part of the app rather
 * than a separate "engine room" screen.
 *
 * One block per Run (one Run per message you sent), one line per trace event, e.g.
 *   ✓ [guard]        pass · 38 chars                                            1ms
 *   ✓ [intent]       safe · "weekend ideas for Lisbon"                       640ms
 *   ✓ [generate]     42 tokens out                                           810ms
 *   612 tok · $0.0007 · 1.5s                            ← footer, once the run finishes
 *
 * Lines come straight from the backend's `trace` SSE events; a new stage only needs a pill colour and
 * an icon (already covered: ok/blocked/error/flagged) below.
 */
import { useEffect, useRef } from 'react'
import type { Run, TraceLine } from '../types'

/**
 * Trace stage → pastel pill background (docs/visual-style.md's stage→colour table). Every stage gets
 * its OWN colour, always — even a blocked or error line keeps its stage's pill, because a soft coral
 * background on the whole line (see `TraceLineRow` below) is what actually marks a problem; the pill
 * only ever answers "which node was this".
 */
const STAGE_PILL: Record<string, string> = {
  guard: 'bg-butter',
  intent: 'bg-sky',
  reason: 'bg-blush',
  generate: 'bg-mint',
  output_guard: 'bg-butter', // same colour as guard: both are code checks (#15 checks what Simba wrote)
  refuse: 'bg-coral',
}

/** Trace status → icon shown before the line. `flagged` (#8) means "passed, but the local classifier
 * raised a flag for the intent check to weigh" — a warning, not a failure. All icons are plain ink;
 * a blocked/error line's own row background (not the icon colour) is what makes it stand out. */
const STATUS_ICON: Record<TraceLine['status'], string> = { ok: '✓', blocked: '⛔', error: '✕', flagged: '⚑' }

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
      className="hidden min-h-0 flex-col border-l border-rule bg-bg font-mono text-[12.5px] text-ink lg:flex"
    >
      <header className="border-b border-rule px-4 py-3.5">
        <h2 className="font-serif text-lg font-semibold">Trace</h2>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {/* 2. */}
        {runs.length === 0 && (
          <p className="leading-relaxed text-muted">
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

/** One run's card: your prompt, one line per trace event, then a running/error line, then the footer.
 * `rounded-2xl` + a 1.5px ink border is the same "card" shape used everywhere else in the app
 * (docs/visual-style.md → Shapes), so this card doesn't look like a different app bolted on the side. */
function RunBlock({ run, running }: { run: Run; running: boolean }) {
  return (
    <section className="rounded-2xl border-[1.5px] border-ink bg-surface p-3">
      <div className="mb-2 truncate text-muted">{run.prompt}</div>
      <ul className="space-y-1">
        {run.lines.map((line, i) => (
          <TraceLineRow key={i} line={line} />
        ))}
        {running && !run.summary && !run.error && <li className="animate-pulse px-2 py-1.5 text-muted">… running</li>}
        {run.error && <li className="rounded-lg bg-coral/40 px-2 py-1.5 break-words">✕ {run.error}</li>}
      </ul>
      {run.summary && (
        <div className="mt-2 border-t border-dashed border-rule pt-2 text-muted tabular-nums">
          {formatTokens(run.summary.input_tokens + run.summary.output_tokens)} tok · $
          {run.summary.cost_usd.toFixed(4)} · {(run.summary.ms / 1000).toFixed(1)}s
        </div>
      )}
    </section>
  )
}

/**
 * One trace event: an ink status icon, the stage's pastel pill, the time (top row), then the detail
 * text underneath, indented to line up under the pill. A blocked or error line gets a soft coral
 * background on the whole row so it stands out at a glance; a flagged line is left alone here — its
 * stage pill plus the ⚑ icon already say "this one's worth a second look".
 */
function TraceLineRow({ line }: { line: TraceLine }) {
  const isProblem = line.status === 'blocked' || line.status === 'error'
  return (
    <li className={`rounded-lg px-2 py-1.5 ${isProblem ? 'bg-coral/40' : ''}`}>
      <div className="flex items-center gap-2">
        {/* The icon is for eyes; the sr-only word ("blocked", "flagged"…) is what a screen reader says. */}
        <span aria-hidden="true">{STATUS_ICON[line.status]}</span>
        <span className="sr-only">{line.status}:</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium text-ink ${STAGE_PILL[line.stage] ?? 'bg-rule'}`}>
          {line.stage}
        </span>
        {/* On a coral problem row, muted grey falls below 4.5:1 contrast, so the time goes ink there. */}
        <span className={`ml-auto tabular-nums ${isProblem ? 'text-ink' : 'text-muted'}`}>{line.ms}ms</span>
      </div>
      <div className="mt-1 pl-6 break-words">{line.detail}</div>
    </li>
  )
}
