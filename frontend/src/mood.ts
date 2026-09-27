/**
 * mood.ts — Simba's mood: what he's feeling right now, picked from the latest chat run and whether
 * an answer is currently streaming (docs/visual-style.md → "Simba avatar"). Lives on its own, not
 * inside SimbaAvatar.tsx, so App.tsx (the header avatar), ChatView.tsx (the empty-state avatar) and
 * SimbaAvatar.tsx itself can all import the `Mood` type without SimbaAvatar.tsx having to know how
 * mood is computed.
 *
 * PLACEHOLDER: this is the same logic ticket #21's SimbaAvatar.tsx placeholder used before the split.
 * Ticket #21 will overwrite this file with the full mood table from docs/visual-style.md (thinking
 * while the answer hasn't started streaming yet, talking while it has, grumpy on a refusal,
 * suspicious on a flagged-but-answered run, dizzy on an error); #20 only needs *a* mood to wire the
 * avatar into the header and empty state.
 */
import type { Run } from './types'

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
