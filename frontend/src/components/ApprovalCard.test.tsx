/**
 * ApprovalCard.test.tsx — the approve / deny card (#66b).
 *
 * It must say in words what will happen (the facts forget_memory would delete, not just ids), send
 * exactly one answer, and lock its buttons after a click so a double click can't answer twice.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { describeCall } from '../approval'
import type { Fact } from '../types'
import { ApprovalCard } from './ApprovalCard'

const fact = (id: number, text: string): Fact => ({
  id, kind: 'user', text, why: null, source_chat_id: null, created_at: '', updated_at: '',
})
const forget = { id: 'c1', tool: 'forget_memory', args: { fact_ids: [3] }, reason: 'waits for approval' }

afterEach(cleanup)

describe('ApprovalCard', () => {
  /** The card names the fact in its own words, and Approve sends true once, then locks. */
  it('shows what will be forgotten and answers once', () => {
    const onAnswer = vi.fn()
    render(<ApprovalCard request={{ calls: [forget] }} facts={[fact(3, 'Works at Acme')]} onAnswer={onAnswer} />)
    expect(screen.getByText('Forget: “Works at Acme”')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    fireEvent.click(screen.getByRole('button', { name: 'Deny' }))
    expect(onAnswer).toHaveBeenCalledTimes(1)
    expect(onAnswer).toHaveBeenCalledWith(true)
    expect((screen.getByRole('button', { name: 'Deny' }) as HTMLButtonElement).disabled).toBe(true)
  })

  /** Unknown ids still show (as "fact #n"); everything=true and other tools get honest wording. */
  it('describes calls it cannot fully name', () => {
    expect(describeCall(forget, [])).toBe('Forget: “fact #3”')
    expect(describeCall({ ...forget, args: { everything: true } }, [])).toBe('Forget everything Simba remembers about you')
    expect(describeCall({ ...forget, tool: 'send_note', args: { text: 'hi' } }, [])).toBe('send_note {"text":"hi"}')
  })
})
