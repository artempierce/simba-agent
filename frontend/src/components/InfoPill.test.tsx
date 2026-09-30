/**
 * InfoPill.test.tsx — the header pill that shows the server's model and web-search state (#57).
 *
 * The pill exists so a missing search key is visible at a glance; these tests pin the two states
 * the owner needs to tell apart, and that nothing renders before the info arrives.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { InfoPill } from './InfoPill'

afterEach(cleanup)

describe('InfoPill', () => {
  /** A real model with search: short model name, "search on". */
  it('shows the short model name and search on', () => {
    render(<InfoPill info={{ model: 'claude-haiku-4-5', web_search: true, chat_budget_usd: 0.5 }} />)
    expect(screen.getByText('haiku-4-5')).toBeTruthy()
    expect(screen.getByText('search on')).toBeTruthy()
  })

  /** The free fake model without a search key: says so plainly. */
  it('shows fake model and search off', () => {
    render(<InfoPill info={{ model: 'fake', web_search: false, chat_budget_usd: 0.5 }} />)
    expect(screen.getByText('fake model')).toBeTruthy()
    expect(screen.getByText('search off')).toBeTruthy()
  })

  /** Before /api/info answers (or if it fails) the header shows no pill at all. */
  it('renders nothing without info', () => {
    const { container } = render(<InfoPill info={null} />)
    expect(container.innerHTML).toBe('')
  })
})
