/**
 * App.test.tsx — tests for App's stale-response guards (App.tsx file header, docs/contracts.md § 11).
 *
 * App starts async calls (load a chat, refresh the chat list, stream a reply) and applies their
 * results after an `await`. By then the user may have moved on, so App checks refs to drop answers
 * that are no longer wanted. These tests make those answers arrive late, or out of order, on purpose.
 *
 * How: `vi.mock` swaps the real api.ts / chatsApi.ts modules for fakes, and each fake call returns a
 * `deferred` promise the test resolves whenever it likes — that's how we control the order.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { streamChat, streamResume } from './api'
import { getChat, getInfo, listChats } from './chatsApi'
import type { ApprovalRequest, Chat, Message, Run } from './types'

vi.mock('./api', () => ({ streamChat: vi.fn(), streamResume: vi.fn() }))
vi.mock('./memoryApi', () => ({
  listFacts: vi.fn(async () => []),
  listSummaries: vi.fn(async () => []),
  deleteFact: vi.fn(),
  updateFact: vi.fn(),
}))
vi.mock('./chatsApi', () => ({
  listChats: vi.fn(),
  getChat: vi.fn(),
  getInfo: vi.fn(),
  renameChat: vi.fn(),
  deleteChat: vi.fn(),
}))

/**
 * A promise plus the function that resolves it, so a test decides when a fake call "answers".
 * Example: const d = deferred<number>(); someCall.mockReturnValue(d.promise); …later… d.resolve(1)
 */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

/** A sidebar chat row with fixed times (the tests only care about id and title). */
const chat = (id: string, title: string): Chat => ({ id, title, created_at: '', updated_at: '' })

/** What getChat returns for one chat: the row plus a single user message showing `text`. */
const loaded = (id: string, text: string) => ({
  chat: chat(id, id),
  messages: [{ role: 'user', content: text }] as Message[],
  runs: [] as Run[],
  approval: null as ApprovalRequest | null,
})

/** Resolve a deferred inside act(), so React applies the state it causes before we assert. */
async function answer<T>(d: { resolve: (value: T) => void }, value: T) {
  await act(async () => d.resolve(value))
}

/** Type a message into the chat box and press Send. */
function sendMessage(text: string) {
  fireEvent.change(screen.getByPlaceholderText('Ask Simba…'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

beforeEach(() => {
  // jsdom has no layout, so it lacks scrollIntoView; ChatView and TracePanel call it to auto-scroll.
  Element.prototype.scrollIntoView = vi.fn()
  vi.mocked(listChats).mockResolvedValue([chat('a', 'Chat A'), chat('b', 'Chat B')])
  vi.mocked(getInfo).mockResolvedValue({ model: 'fake', web_search: false, chat_budget_usd: 0.5 })
})

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('App stale-response guards', () => {
  /**
   * Click chat A (slow to load), then chat B (fast). A's late answer must not replace B on screen —
   * the `requestedChatRef` check in selectChat. Without it, the page would show A while B is selected.
   */
  it('drops a chat load that finished after another chat was picked', async () => {
    const slowA = deferred<ReturnType<typeof loaded>>()
    const fastB = deferred<ReturnType<typeof loaded>>()
    vi.mocked(getChat).mockImplementation((id) => (id === 'a' ? slowA.promise : fastB.promise))
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Chat A' }))
    fireEvent.click(screen.getByRole('button', { name: 'Chat B' }))
    await answer(fastB, loaded('b', 'message in B'))
    await answer(slowA, loaded('a', 'message in A'))

    expect(screen.getByText('message in B')).toBeTruthy()
    expect(screen.queryByText('message in A')).toBeNull()
  })

  /**
   * Click a chat, then send a message before it loads. The late load must not wipe the reply that is
   * streaming — the `busyRef` check in selectChat. Clicking another chat mid-stream is ignored too.
   */
  it('ignores chat loads while a reply is streaming', async () => {
    const slowA = deferred<ReturnType<typeof loaded>>()
    vi.mocked(getChat).mockReturnValue(slowA.promise)
    const stream = deferred<void>()
    vi.mocked(streamChat).mockReturnValue(stream.promise)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Chat A' }))
    sendMessage('my new question')
    await answer(slowA, loaded('a', 'message in A'))

    // getAll: the question shows twice, as a chat bubble and as the trace panel's run heading.
    expect(screen.getAllByText('my new question').length).toBeGreaterThan(0)
    expect(screen.queryByText('message in A')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Chat B' }))
    expect(getChat).toHaveBeenCalledTimes(1) // only the click before sending
    await answer(stream, undefined)
  })

  /**
   * Two chat-list refreshes answer in the wrong order: the one at page load comes back after the one
   * started later (after a reply). The older list must be dropped — the `chatsSeqRef` check in
   * refreshChats. Without it, a just-created chat would vanish from the sidebar.
   */
  it('drops an older chat-list refresh that answers last', async () => {
    const onLoad = deferred<Chat[]>()
    const afterReply = deferred<Chat[]>()
    vi.mocked(listChats).mockReturnValueOnce(onLoad.promise).mockReturnValueOnce(afterReply.promise)
    vi.mocked(streamChat).mockResolvedValue(undefined)
    render(<App />)

    sendMessage('hello')
    await vi.waitFor(() => expect(listChats).toHaveBeenCalledTimes(2))
    await answer(afterReply, [chat('new', 'Fresh chat')])
    await answer(onLoad, [chat('old', 'Stale chat')])

    expect(screen.getByRole('button', { name: 'Fresh chat' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Stale chat' })).toBeNull()
  })
})

describe('approval card (#66b)', () => {
  /**
   * Reopening a chat whose turn is paused shows its card and locks the message box (the backend
   * would refuse a new message with 409). Approve resumes that chat with `true` and the card goes.
   */
  it('shows a paused chat card, locks sending, and resumes on Approve', async () => {
    const request = { calls: [{ id: 'c1', tool: 'forget_memory', args: { fact_ids: [3] }, reason: 'waits for approval' }] }
    vi.mocked(getChat).mockResolvedValue({ ...loaded('a', 'forget that'), approval: request })
    vi.mocked(streamResume).mockResolvedValue(undefined)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Chat A' }))
    expect(await screen.findByRole('region', { name: 'Approval needed' })).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Approve' })))
    expect(streamResume).toHaveBeenCalledWith('a', true, expect.any(Object))
    expect(screen.queryByRole('region', { name: 'Approval needed' })).toBeNull()
  })
})
