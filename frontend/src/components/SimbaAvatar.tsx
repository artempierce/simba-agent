/**
 * SimbaAvatar.tsx — Simba's face: an original doodle cat drawn as inline SVG, one face per mood
 * (docs/visual-style.md → "Simba avatar"; the mood itself comes from `moodFor` in ../mood.ts).
 *
 * How the drawing works: everything sits on a 64×64 grid (`viewBox="0 0 64 64"`), so the numbers
 * below are grid points — (0, 0) is the top-left corner, (32, 32) the centre — and the SVG scales to
 * whatever `size` it's given. Shapes are painted in order, later ones on top: ears, then the head
 * (which hides the ears' bases), then the tuft, whiskers, and finally the face for the mood.
 *
 * Ink is `currentColor`, the text colour of whatever contains the avatar, so it follows the theme.
 * The face is split into lookup tables (EYES, MOUTHS, EXTRAS) keyed by mood: to change how Simba
 * looks when he's happy, edit `EYES.happy` / `MOUTHS.happy` and nothing else.
 */
import type { ReactNode } from 'react'
import type { Mood } from '../mood'

/** Outline width for the head, ears and tuft: the "thick ink" of the doodle style (~3 at 64px). */
const OUTLINE = 3
/** Width for face details (eyes, mouth, whiskers): thinner, so the outline stays the boldest line. */
const DETAIL = 2.2

/**
 * Animations, as CSS keyframes. Only the keyframes live here; *whether* they run is decided by the
 * Tailwind `motion-safe:` classes on the animated groups below, so people who ask their OS for
 * reduced motion get a still Simba.
 * - simba-blink: squash the eyes flat for a moment every few seconds (idle).
 * - simba-yap:   open and close the mouth (talking).
 */
const KEYFRAMES = `
@keyframes simba-blink { 0%, 92%, 100% { transform: scaleY(1) } 96% { transform: scaleY(0.1) } }
@keyframes simba-yap { 0%, 100% { transform: scaleY(1) } 50% { transform: scaleY(0.45) } }
`

/**
 * Classes that make an SVG group scale around its own centre. SVG elements normally transform
 * around the canvas's top-left corner; `transform-box: fill-box` + `origin-center` fixes that.
 */
const OWN_CENTRE = '[transform-box:fill-box] origin-center'

/** Words a screen reader says for each mood (the `aria-label`). */
const LABELS: Record<Mood, string> = {
  idle: 'Simba the cat, relaxed',
  thinking: 'Simba the cat, thinking',
  talking: 'Simba the cat, talking',
  happy: 'Simba the cat, happy',
  grumpy: 'Simba the cat, grumpy: he said no to that one',
  suspicious: 'Simba the cat, suspicious: something looked off',
  dizzy: 'Simba the cat, dizzy: something went wrong',
}

/** A spiral for one dizzy eye, centred on (x, y): half-circles that grow as they turn. */
function spiral(x: number, y: number) {
  return `M${x} ${y} a1.2 1.2 0 0 1 2.4 0 a2.4 2.4 0 0 1 -4.8 0 a3.6 3.6 0 0 1 7.2 0 a4.8 4.8 0 0 1 -9.6 0`
}

/**
 * Eyes per mood. Simba's eyes sit at about (23, 35) and (41, 35).
 * Plain dots are his resting look; other moods change shape or add brows.
 */
const EYES: Record<Mood, ReactNode> = {
  // Dot eyes that blink now and then.
  idle: (
    <g className={`${OWN_CENTRE} motion-safe:animate-[simba-blink_5s_ease-in-out_infinite]`}>
      <circle cx="23" cy="35" r="3.3" fill="currentColor" stroke="none" />
      <circle cx="41" cy="35" r="3.3" fill="currentColor" stroke="none" />
    </g>
  ),
  // Big round eyes, pupils rolled up and to the side: "hmm, let me think".
  thinking: (
    <g>
      <circle cx="23" cy="35" r="4.6" strokeWidth={DETAIL} />
      <circle cx="41" cy="35" r="4.6" strokeWidth={DETAIL} />
      <circle cx="24.6" cy="32.8" r="2.1" fill="currentColor" stroke="none" />
      <circle cx="42.6" cy="32.8" r="2.1" fill="currentColor" stroke="none" />
    </g>
  ),
  // Dot eyes, same as idle but without the blink (the mouth is busy moving instead).
  talking: (
    <g fill="currentColor" stroke="none">
      <circle cx="23" cy="35" r="3.3" />
      <circle cx="41" cy="35" r="3.3" />
    </g>
  ),
  // Eyes squeezed shut into two happy arches: ^ ^
  happy: (
    <g fill="none" strokeWidth={DETAIL + 0.4}>
      <path d="M19 37 Q23 31 27 37" />
      <path d="M37 37 Q41 31 45 37" />
    </g>
  ),
  // Flat, unimpressed half-closed eyes under brows angled down towards the nose.
  grumpy: (
    <g strokeWidth={DETAIL + 0.4}>
      <path d="M19 36 H27" fill="none" />
      <path d="M37 36 H45" fill="none" />
      <path d="M20.5 36.5 a2.5 2.5 0 0 0 5 0 Z" fill="currentColor" stroke="none" />
      <path d="M38.5 36.5 a2.5 2.5 0 0 0 5 0 Z" fill="currentColor" stroke="none" />
      <path d="M18 29 L27 32" fill="none" />
      <path d="M46 29 L37 32" fill="none" />
    </g>
  ),
  // Side-eye: heavy flat lids, pupils slid all the way to one side, one brow cocked up.
  suspicious: (
    <g strokeWidth={DETAIL}>
      <path d="M18.5 35 H27.5 a4.5 4.5 0 0 1 -9 0 Z" />
      <path d="M36.5 35 H45.5 a4.5 4.5 0 0 1 -9 0 Z" />
      <circle cx="25" cy="36.8" r="2" fill="currentColor" stroke="none" />
      <circle cx="43" cy="36.8" r="2" fill="currentColor" stroke="none" />
      <path d="M36.5 29 Q41 25.5 45.5 28" fill="none" />
    </g>
  ),
  // Spiral eyes: the classic "seeing stars" look.
  dizzy: (
    <g fill="none" strokeWidth={1.7}>
      <path d={spiral(23, 35)} />
      <path d={spiral(41, 35)} />
    </g>
  ),
}

/**
 * Mouths per mood. They hang just under the nose, which sits at about (32, 42).
 */
const MOUTHS: Record<Mood, ReactNode> = {
  // The classic cat "w", with one tiny fang poking out.
  idle: (
    <g>
      <path d="M33.2 46.6 L34.6 49.8 L35.8 46.8" strokeWidth={1.4} />
      <path d="M27 45 Q29.5 48 32 45 Q34.5 48 37 45" fill="none" />
    </g>
  ),
  // A little sideways squiggle: mulling it over.
  thinking: <path d="M26 47 Q28 45 30 47 T34 46" fill="none" />,
  // Open mouth that opens and closes while the answer streams in.
  talking: (
    <g className={`${OWN_CENTRE} motion-safe:animate-[simba-yap_0.35s_ease-in-out_infinite]`}>
      <path d="M28 45 Q32 53 36 45 Z" fill="currentColor" />
    </g>
  ),
  // A wide open grin.
  happy: <path d="M25 45 Q32 55 39 45 Z" fill="currentColor" />,
  // An upside-down smile.
  grumpy: <path d="M27 49 Q32 44 37 49" fill="none" />,
  // A flat mouth pulled off to one side: "hmm, really?"
  suspicious: <path d="M30 47 L37 45.5" fill="none" />,
  // A wobbly line with the tongue poking out.
  dizzy: (
    <g>
      <path d="M26 46 q1.5 -2 3 0 t3 0 t3 0 t3 0" fill="none" />
      <path d="M33 46.3 v3 a2 2 0 0 0 4 0 v-3" />
    </g>
  ),
}

/** Small extra touches some moods add around the face (drawn last, on top of everything). */
const EXTRAS: Partial<Record<Mood, ReactNode>> = {
  // A paw raised to the chin: a bean with three toe bumps on top.
  thinking: (
    <path
      d="M36 60 C31 60 31 53 34 52 C34 49 37.5 49 38 51 C39 48.5 42 48.5 42.5 51 C43.5 49 47 50 46 53 C49 55 47 60 43 60 Z"
      strokeWidth={OUTLINE - 0.5}
    />
  ),
  // A drop of sweat sliding down the forehead: fed up.
  grumpy: <path d="M50 24 Q53 29 52 31 A2.2 2.2 0 0 1 48 31 Q47.5 29 50 24 Z" strokeWidth={1.6} />,
}

/**
 * Simba's face for one mood.
 *
 * Inputs: `mood` (from `moodFor`) picks the eyes, mouth and extras; `size` is the rendered width and
 * height in pixels (the drawing scales, so 40 in a chat row and 96 on the welcome card both work).
 *
 * Drawing order (later on top):
 *   1. ears   — one pointy, one with a floppy bent tip, each with a solid inner ear
 *   2. head   — a wide, slightly squashed circle that covers the ears' bases
 *   3. tuft   — a scruffy three-spike tuft of hair on top (a wink at "Simba" the lion)
 *   4. whiskers and nose
 *   5. eyes, mouth and any extra for the mood
 */
export function SimbaAvatar({ mood, size = 40 }: { mood: Mood; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label={LABELS[mood]}>
      <style>{KEYFRAMES}</style>
      {/* Defaults for every shape inside: white fill, rounded ink lines. Shapes override as needed. */}
      <g fill="white" stroke="currentColor" strokeWidth={OUTLINE} strokeLinecap="round" strokeLinejoin="round">
        {/* 1. Ears. Left: a tall point. Right: the tip flops over, with a fold line. */}
        <path d="M12 30 L9 5 L28 18 Z" />
        <path d="M14.5 21 L13 12 L20.5 17.5 Z" fill="currentColor" stroke="none" />
        <path d="M37 18 L47 8 L52 10 L55 30 Z" />
        <path d="M47 8 L52 10 L61 17 Z" fill="currentColor" />
        <path d="M45 17 L48.5 13 L50.5 20 Z" fill="currentColor" stroke="none" />

        {/* 2. Head. */}
        <ellipse cx="32" cy="37" rx="25" ry="21" />

        {/* 3. Tuft: an open path, so its white fill hides the head's outline underneath it. */}
        <path d="M24 18.5 C25 12 29 10 29.5 15.5 C30 7 36 7 34.5 15.5 C37 10 41.5 12 40 18.5" />

        {/* 4. Whiskers (two per cheek, poking past the head) and a small solid nose. */}
        <g fill="none" strokeWidth={DETAIL - 0.4}>
          <path d="M14 41 L2 38.5 M14 45 L3 48" />
          <path d="M50 41 L62 38.5 M50 45 L61 48" />
        </g>
        <path d="M29.5 40.5 H34.5 L32 43.5 Z" fill="currentColor" strokeWidth={1.5} />

        {/* 5. The face for this mood. */}
        <g strokeWidth={DETAIL}>
          {EYES[mood]}
          {MOUTHS[mood]}
          {EXTRAS[mood]}
        </g>
      </g>
    </svg>
  )
}
