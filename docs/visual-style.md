# Simba visual style (tickets #20, #21)

Sol's reference: the hilos landing page on lapa.ninja (screenshots for builders:
`/Users/sol/simba-agent/.claude/ref/style-hero.jpeg`, `style-cards.jpeg`). We borrow its **style
only** — never its characters, logo, names or copy. Every drawing in Simba is original.

## The look in one line

A warm paper page, a bookish serif for headings, black pill buttons, white rounded cards with a thin
ink border, pastel accent cards, and thick-outline black-and-white doodle art — friendly, a little
funny, very readable. The trace panel stays a dark terminal column (it's the "engine room").

## Tokens (`frontend/src/index.css` `@theme`)

| Token | Value | Use |
|---|---|---|
| `bg` | `#F1F0EB` | page background (warm paper) |
| `surface` | `#FFFFFF` | cards, chat pane, input |
| `raised` | `#F7F6F1` | hovered rows, the open chat |
| `ink` | `#1A1A1A` | text, outlines, primary buttons |
| `muted` | `#6B6A66` | secondary text |
| `rule` | `#E3E1D9` | soft dividers |
| `accent` | `#1A1A1A` | primary action = ink (black pill) |
| `accent-ink` | `#FFFFFF` | text on a black pill |
| `sky` | `#BCD4F1` | pastel card / your chat bubble |
| `butter` | `#F1DE99` | pastel card |
| `blush` | `#EFD0DF` | pastel card |
| `coral` | `#EDB6A3` | pastel card, warnings that aren't errors |
| `danger` | `#B3261E` | errors, delete |
| trace: `term` `#161616`, `term-ink` `#E9E7E1`, `term-dim` `#8C8A84`, `term-rule` `#2B2A28`; stage colours stay pastel-bright on dark |

Keep contrast ≥ 4.5:1 for text (ink on every pastel passes).

## Type

- Headings: **Newsreader** (Google Fonts; a bookish serif close to the reference), weight 500–600,
  tight leading, used with restraint (wordmark, empty-state greeting, section titles).
- Text: **DM Sans** 400/500/600.
- Trace and code: **JetBrains Mono** (as today).

## Shapes

- Buttons: pills (`rounded-full`). Primary = ink fill, white text. Secondary = white fill + 1.5px ink
  border. Focus ring: 2px ink outline with offset.
- Cards: `rounded-2xl`, white, 1.5px ink border (`border-ink`) for the "hero card" feel, or no border +
  pastel fill for accent cards. Soft shadow only on floating things (header pill, drawer, cards on a
  pattern).
- Doodle art: thick black outline (~3px at 64px), white fill, solid black details, dot eyes. Original.

## Screens

- **Header:** a floating pill (white, ink border, soft shadow) with Simba's avatar + serif wordmark on
  the left; on phones the "Chats" pill button.
- **Sidebar:** on paper; "+ New chat" as a black pill; rows as soft rounded items; the open chat on
  `raised` with ink text.
- **Empty state:** a white hero card with an ink border, centred, over a subtle original doodle
  pattern band (paws, fish, yarn balls, whisker marks — drawn as a repeating SVG pattern, low
  contrast so text stays readable); big Simba avatar; serif greeting "Hi, I'm Simba."; one line of
  sans text; 4 pastel suggestion cards (sky, butter, blush, coral) with a tiny doodle each — clicking
  one sends that prompt.
- **Chat:** Simba's replies start with a small avatar; your bubbles are `sky` with ink text; the input
  is a white rounded card with an ink border and a black pill "Send".
- **Trace panel:** dark `term` column; each run a card with `term-rule` border; ⚑ flagged lines keep
  their stage colour.

## Simba avatar (#21)

`<SimbaAvatar mood size />` in `components/SimbaAvatar.tsx`, inline SVG, `viewBox="0 0 64 64"`, no image
files. An original funny cat: round head, big pointy ears, whiskers, a small scruffy tuft on top (a
wink at the lion name), thick ink outline, white fill, solid black nose and details.

| Mood | When (`moodFor(run, busy)`) | Face |
|---|---|---|
| `idle` | no run yet | calm, slow blink |
| `thinking` | busy, no answer text yet | eyes up, paw on chin or "…" |
| `talking` | busy and the answer is streaming | mouth open |
| `happy` | last run finished without problems | closed happy eyes, smile |
| `grumpy` | last run was refused (a `blocked` line) | flat eyes, frown |
| `suspicious` | last run had a ⚑ `flagged` line but was answered | side-eye |
| `dizzy` | last run ended with an error | spiral eyes |

`moodFor` needs to know whether answer text has arrived: it receives the newest run and `busy`, plus
(#21 decides) a `streaming` flag from App. Respect `prefers-reduced-motion` for any animation.
The favicon is Simba's `idle` face.
