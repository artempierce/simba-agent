/**
 * Doodles.tsx — original hand-drawn line art for Simba's empty state (docs/visual-style.md → "Empty
 * state"): four small icons (paw, fish, yarn ball, whisker marks) used both as the tiny doodle on
 * each suggestion card and, tiled low-contrast, as the pattern band behind the empty-state hero card.
 * All inline SVG, no image files — every mark here is drawn in this file, never traced from a
 * reference (the brief borrows only the *style* of Sol's reference screenshots, not any of its art).
 */

/** Shared shape for one small doodle: thick, rounded ink strokes, sized and positioned by the caller
 * (either loose on a suggestion card, or tiled as one repeat of the pattern band below). */
type DoodleProps = { x?: number; y?: number; size?: number; className?: string }

/** Stroke style shared by every doodle: no fill, rounded ends and corners, colour inherited from
 * whatever `className` sets `color` to (so one icon can be dark on a card and faint in the band). */
const STROKE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

/** A cat's paw print: one big pad, four small toes. */
export function Paw({ x = 0, y = 0, size = 24, className }: DoodleProps) {
  return (
    <svg x={x} y={y} width={size} height={size} viewBox="0 0 24 24" className={className} {...STROKE}>
      <circle cx="12" cy="15.5" r="5.5" />
      <circle cx="5.5" cy="8" r="2" />
      <circle cx="10.5" cy="4.5" r="2" />
      <circle cx="15.5" cy="4.7" r="2" />
      <circle cx="19.5" cy="8.5" r="2" />
    </svg>
  )
}

/** A little fish: a curved body, a two-line tail, and a dot eye. */
export function Fish({ x = 0, y = 0, size = 24, className }: DoodleProps) {
  return (
    <svg x={x} y={y} width={size} height={size} viewBox="0 0 24 24" className={className} {...STROKE}>
      <path d="M2 12c3.5-4.5 9-6.5 13.5-4C18 9.3 20 10.7 22 12c-2 1.3-4 2.7-6.5 4-4.5 2.5-10 .5-13.5-4Z" />
      <circle cx="16.5" cy="10.3" r="0.9" fill="currentColor" stroke="none" />
      <path d="M2 12 4.5 9M2 12 4.5 15" />
    </svg>
  )
}

/** A ball of yarn: a circle wrapped in a few loose strands, with one end trailing off. */
export function Yarn({ x = 0, y = 0, size = 24, className }: DoodleProps) {
  return (
    <svg x={x} y={y} width={size} height={size} viewBox="0 0 24 24" className={className} {...STROKE}>
      <circle cx="12" cy="12" r="8" />
      <path d="M4.5 9c4 2.5 8 2.5 12 0M3.7 15c5 2 10.6 1 15-1.5M6.2 4.8c3 5 3 10.4 0 15.6M12 4c1.4 5 1.4 10 0 16" />
      <path d="M19 6c1.4 1 2.4 2.6 2.4 4.4" />
    </svg>
  )
}

/** A cat's nose and whisker marks: a small triangle nose, three lines radiating from each side. */
export function Whiskers({ x = 0, y = 0, size = 24, className }: DoodleProps) {
  return (
    <svg x={x} y={y} width={size} height={size} viewBox="0 0 24 24" className={className} {...STROKE}>
      <path d="M12 12 10.4 10.6h3.2Z" fill="currentColor" stroke="none" />
      <path d="M9.5 12.6H2M9.5 10.6 3 7.4M9.5 14.6 3 17.4" />
      <path d="M14.5 12.6H22M14.5 10.6 21 7.4M14.5 14.6 21 17.4" />
    </svg>
  )
}

/**
 * A low-contrast band of repeating paw/fish/yarn/whisker marks, absolutely positioned to fill its
 * parent (which must itself be `position: relative` — the empty state sets that). Sits behind the
 * hero card and suggestion cards; `text-ink/10` (10% opacity ink) keeps it faint enough that text on
 * top of it stays easily readable.
 *
 * This is what the file header means by "tiled as a pattern": an SVG `<pattern>` is drawn ONCE, as a
 * small tile inside `<defs>`, then any shape can fill itself with endless copies of that tile via
 * `fill="url(#id)"` — the browser repeats it for you, as vector art that stays crisp at any zoom
 * level. `patternUnits="userSpaceOnUse"` means the tile's 72×72 size is in real pixels of this SVG,
 * so the doodles keep the same size however big the band is (the default would stretch the tile
 * relative to the shape it fills).
 *
 * No `z-index` here on purpose: a *negative* z-index (an earlier version used `-z-10` to push this
 * behind its siblings) doesn't just go behind the hero card — with no stacking context of its own in
 * between, it can end up behind the nearest opaque ancestor further up the tree too, disappearing
 * completely. Plain DOM order already does the job: this component is rendered first, so the hero
 * card and suggestion cards (rendered after it, with no z-index of their own) paint on top of it.
 */
export function DoodleBand() {
  return (
    <svg aria-hidden="true" className="absolute inset-0 h-full w-full text-ink/10">
      <defs>
        <pattern id="doodle-band" width="72" height="72" patternUnits="userSpaceOnUse">
          <Paw x={2} y={2} size={22} />
          <Fish x={38} y={8} size={22} />
          <Yarn x={6} y={40} size={22} />
          <Whiskers x={40} y={42} size={22} />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#doodle-band)" />
    </svg>
  )
}
