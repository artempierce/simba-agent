/**
 * mood.ts — how Simba feels, worked out from the newest trace-panel run (docs/visual-style.md →
 * "Simba avatar").
 *
 * App already knows everything needed: the newest `Run` (its trace lines, summary or error) and
 * whether a reply is streaming. `moodFor` turns that into one of seven moods, and `SimbaAvatar`
 * draws the face for it. Keeping this pure function out of the component file means it can be read
 * (and tested) on its own, and the component file only exports a component (React Fast Refresh's
 * rule, which the linter checks).
 */
import type { Run } from './types'

/** What Simba is feeling right now; `SimbaAvatar` draws one face per mood. */
export type Mood = 'idle' | 'thinking' | 'talking' | 'happy' | 'grumpy' | 'suspicious' | 'dizzy'

/**
 * Pick Simba's mood from the newest run.
 *
 * Inputs: `run` is the newest trace-panel run (undefined before the first message), `busy` is true
 * while a reply is being streamed, and `streaming` is true once answer text has started arriving
 * (App knows this from the reply bubble; it defaults to false so callers that don't track it just
 * see "thinking" for the whole run).
 *
 * The checks run top to bottom and the first match wins, so the more specific story beats the
 * general one:
 *   1. a `blocked` line          → grumpy     (Simba refused; shows even mid-run, while he says no)
 *   2. a ⚑ `flagged` line and the
 *      run was answered (summary) → suspicious (it passed, but something looked off)
 *   3. the run has an error      → dizzy
 *   4. busy and text is arriving → talking
 *   5. busy, no text yet         → thinking
 *   6. a finished run            → happy
 *   7. no run at all             → idle
 *
 * Example: `moodFor({ prompt: 'hi', lines: [], summary }, false)` → 'happy'.
 */
export function moodFor(run: Run | undefined, busy: boolean, streaming = false): Mood {
  // 1.
  if (run?.lines.some((line) => line.status === 'blocked')) return 'grumpy'
  // 2.
  if (run?.summary && run.lines.some((line) => line.status === 'flagged')) return 'suspicious'
  // 3.
  if (run?.error) return 'dizzy'
  // 4. + 5.
  if (busy) return streaming ? 'talking' : 'thinking'
  // 6.
  if (run) return 'happy'
  // 7.
  return 'idle'
}
