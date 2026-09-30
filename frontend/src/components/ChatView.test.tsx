/**
 * ChatView.test.tsx — the "Remembered: … · Undo" note under a reply (#81).
 *
 * Memory saves itself, so the note is where the owner notices and can take a save back; the tests
 * pin the wording for both kinds of save and that Undo reports the right fact, then goes away.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Message } from '../types'
import { ChatView } from './ChatView'

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn() // jsdom has no layout; ChatView auto-scrolls
})
afterEach(cleanup)

const added = { action: 'added' as const, fact_id: 1, kind: 'user' as const, text: 'Mostly works in Python', previous_text: null }
const updated = { action: 'updated' as const, fact_id: 2, kind: 'user' as const, text: 'Has two cats', previous_text: 'Has a cat' }

/** Render one exchange whose reply saved `memories`; returns the Undo spy. */
function setup(memories: Message['memories']) {
  const onUndoMemory = vi.fn()
  const messages: Message[] = [
    { role: 'user', content: 'I mostly work in Python' },
    { role: 'assistant', content: 'Nice!', memories },
  ]
  render(<ChatView messages={messages} runs={[]} busy={false} mood="happy" onSend={vi.fn()} onUndoMemory={onUndoMemory} />)
  return onUndoMemory
}

describe('ChatView memory notes', () => {
  /** A new fact reads "Remembered", a reworded one "Updated memory"; Undo passes the fact back up. */
  it('shows each saved fact with an Undo', () => {
    const onUndo = setup([added, updated])
    expect(screen.getByText('Remembered: “Mostly works in Python”')).toBeTruthy()
    expect(screen.getByText('Updated memory: “Has two cats”')).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: 'Undo' })[1])
    expect(onUndo).toHaveBeenCalledWith(updated)
  })

  /** After Undo the note says what happened and offers no button that no longer applies. */
  it('shows the result instead of Undo once undone', () => {
    setup([{ ...added, undone: true }, { ...updated, undone: true }])
    expect(screen.getByText('Forgotten: “Mostly works in Python”')).toBeTruthy()
    expect(screen.getByText('Put back the old wording: “Has two cats”')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  })
})
