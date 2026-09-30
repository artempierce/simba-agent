/**
 * MemoryPanel.test.tsx — the Memory tab (#80): facts show under their kind, and add, edit, delete
 * and "Delete all" report the right thing back to App.
 *
 * "Delete all" is the one destructive control here, so the tests pin that it asks first and only a
 * "Yes" goes through.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Fact } from '../types'
import { MemoryPanel } from './MemoryPanel'

afterEach(cleanup)

const fact = (id: number, kind: Fact['kind'], text: string): Fact => ({
  id, kind, text, why: null, source_chat_id: null, created_at: '', updated_at: '',
})

/** Render with spy callbacks; returns them for the assertions. */
function setup(facts: Fact[]) {
  const props = { onAdd: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn(), onDeleteAll: vi.fn() }
  render(<MemoryPanel facts={facts} {...props} />)
  return props
}

describe('MemoryPanel', () => {
  /** Each fact is listed under its kind's heading; an empty kind shows no heading at all. */
  it('groups facts by kind', () => {
    setup([fact(1, 'user', 'Name: Sol'), fact(2, 'project', 'Building Simba')])
    expect(screen.getByRole('region', { name: 'About you' }).textContent).toContain('Name: Sol')
    expect(screen.getByRole('region', { name: 'Projects' }).textContent).toContain('Building Simba')
    expect(screen.queryByRole('region', { name: 'References' })).toBeNull()
  })

  /** Saving sends the chosen kind and the trimmed text, then clears the box. */
  it('adds a fact with its kind', () => {
    const { onAdd } = setup([])
    fireEvent.change(screen.getByLabelText('Remember something'), { target: { value: 'feedback' } })
    fireEvent.change(screen.getByLabelText('Fact to remember'), { target: { value: '  Short answers please ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onAdd).toHaveBeenCalledWith('feedback', 'Short answers please')
    expect((screen.getByLabelText('Fact to remember') as HTMLTextAreaElement).value).toBe('')
  })

  /** Edit swaps the text for an input; Enter saves the new text. */
  it('edits a fact in place', () => {
    const { onEdit } = setup([fact(7, 'user', 'Name: Sol')])
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const input = screen.getByLabelText('Edit fact')
    fireEvent.change(input, { target: { value: 'Name: Sol K.' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.blur(input)
    expect(onEdit).toHaveBeenCalledOnce()
    expect(onEdit).toHaveBeenCalledWith(7, 'Name: Sol K.')
  })

  /** Escape cancels: the blur that follows must not save the half-typed text. */
  it('does not save an edit cancelled with Escape', () => {
    const { onEdit } = setup([fact(7, 'user', 'Name: Sol')])
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const input = screen.getByLabelText('Edit fact')
    fireEvent.change(input, { target: { value: 'oops' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    fireEvent.blur(input)
    expect(onEdit).not.toHaveBeenCalled()
  })

  /** Delete forgets one fact; "Delete all" asks first, and Cancel does nothing. */
  it('deletes one fact, and asks before deleting everything', () => {
    const { onDelete, onDeleteAll } = setup([fact(3, 'user', 'Name: Sol')])
    fireEvent.click(screen.getByRole('button', { name: 'Forget: Name: Sol' }))
    expect(onDelete).toHaveBeenCalledWith(3)

    fireEvent.click(screen.getByRole('button', { name: 'Delete all memory' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onDeleteAll).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Delete all memory' }))
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    expect(onDeleteAll).toHaveBeenCalledOnce()
  })
})
