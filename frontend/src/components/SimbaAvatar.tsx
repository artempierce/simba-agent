/**
 * SimbaAvatar.tsx — PLACEHOLDER. Ticket #21 replaces this file with the real doodle cat.
 *
 * The interface below is final (docs/visual-style.md → "Simba avatar"), so the redesign (#20) can
 * place the avatar now and the drawing can land in parallel without either side waiting. `Mood` and
 * `moodFor` used to live in this file; #20 moved them to `../mood` so callers can compute a mood
 * without pulling in this file's SVG drawing code (see mood.ts's header comment). #21 will overwrite
 * this whole file with the real drawing but should keep importing `Mood` the same way.
 */
import type { Mood } from '../mood'

/** Simba's face. `size` is the width and height in pixels. Placeholder: a plain outlined circle. */
export function SimbaAvatar({ mood, size = 40 }: { mood: Mood; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label={`Simba (${mood})`}>
      <circle cx="32" cy="32" r="28" fill="white" stroke="currentColor" strokeWidth="3" />
    </svg>
  )
}
