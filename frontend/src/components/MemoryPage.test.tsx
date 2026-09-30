/**
 * MemoryPage.test.tsx — the read-only Memory page (#87): facts grouped by how they're used, search,
 * the source-chat link, and no editing controls (memory changes by talking to Simba, D46).
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Chat, Fact } from '../types'
import { MemoryPage } from './MemoryPage'

afterEach(cleanup)

const fact = (id: number, kind: Fact['kind'], text: string, extra: Partial<Fact> = {}): Fact => ({
  id, kind, text, why: null, source_chat_id: null, created_at: '2026-09-30T10:00:00Z', updated_at: '2026-09-30T10:00:00Z', ...extra,
})
const chats: Chat[] = [{ id: 'c1', title: 'Memory plan', created_at: '', updated_at: '' }]

describe('MemoryPage', () => {
  /** Learned rules and the profile are marked "always in Simba's prompt"; projects are not. */
  it('groups facts and marks what is always in the prompt', () => {
    render(<MemoryPage facts={[fact(1, 'feedback', 'Prefers short answers', { why: 'said so' }), fact(2, 'project', 'Building Simba')]} chats={chats} onOpenChat={vi.fn()} />)
    const rules = screen.getByRole('region', { name: 'How you want me to work' })
    expect(rules.textContent).toContain('Prefers short answers')
    expect(rules.textContent).toContain('Why: said so')
    expect(rules.textContent).toContain("always in Simba's prompt")
    expect(screen.getByRole('region', { name: 'Projects' }).textContent).not.toContain("always in Simba's prompt")
  })

  /** Search keeps facts containing every typed word, in any order and case. */
  it('filters by search words', () => {
    render(<MemoryPage facts={[fact(1, 'user', 'Mostly works in Python'), fact(2, 'user', 'Has a cat')]} chats={chats} onOpenChat={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search memory'), { target: { value: 'python WORKS' } })
    const about = screen.getByRole('region', { name: 'About you' }).textContent
    expect(about).toContain('Mostly works in Python')
    expect(about).not.toContain('Has a cat')
  })

  /** The source chat is a link back to it; the page has no add, edit or delete buttons. */
  it('links to the source chat and offers no editing', () => {
    const onOpenChat = vi.fn()
    render(<MemoryPage facts={[fact(1, 'user', 'Name: Sol', { source_chat_id: 'c1' })]} chats={chats} onOpenChat={onOpenChat} />)
    fireEvent.click(screen.getByRole('button', { name: 'from “Memory plan”' }))
    expect(onOpenChat).toHaveBeenCalledWith('c1')
    expect(screen.queryByRole('button', { name: /edit|delete|add|save/i })).toBeNull()
  })
})
