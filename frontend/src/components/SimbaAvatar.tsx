/**
 * SimbaAvatar.tsx — PLACEHOLDER. Ticket #21 replaces this file with the real doodle cat.
 *
 * The interface below is final (docs/visual-style.md → "Simba avatar"), so the redesign (#20) can
 * place the avatar now and the drawing can land in parallel without either side waiting.
 */
import type { Run } from '../types'

/** What Simba is feeling right now; picks which face the avatar draws. */
export type Mood = 'idle' | 'thinking' | 'talking' | 'happy' | 'grumpy' | 'suspicious' | 'dizzy'

/**
 * Pick Simba's mood from the newest run and whether a reply is streaming. Placeholder logic; #21
 * refines it (see docs/visual-style.md for the mapping).
 */
export function moodFor(run: Run | undefined, busy: boolean): Mood {
  if (busy) return 'thinking'
  if (!run) return 'idle'
  return run.error ? 'dizzy' : 'happy'
}

/** Simba's face. `size` is the width and height in pixels. Placeholder: a plain outlined circle. */
export function SimbaAvatar({ mood, size = 40 }: { mood: Mood; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label={`Simba (${mood})`}>
      <circle cx="32" cy="32" r="28" fill="white" stroke="currentColor" strokeWidth="3" />
    </svg>
  )
}
