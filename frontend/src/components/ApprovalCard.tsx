/**
 * ApprovalCard.tsx — the approve / deny card for a tool call that waits for you (#66, D35, D51).
 *
 * Where it sits: when a turn pauses (the backend's `approval` SSE event, or a reopened chat whose
 * GET /api/chats/{id} has `approval`), App passes the waiting calls to ChatView, which shows this card
 * under the conversation. Approve or Deny calls `onAnswer`; App then streams POST
 * /api/chat/{id}/resume and the turn carries on in the same reply bubble.
 *
 * Key idea: the card shows the whole change before anything happens ("Show the whole change",
 * CLAUDE.md). For forget_memory that means the facts' own words, looked up in `facts`, not just ids.
 * The buttons lock after one click, so a double click can't send two answers.
 */
import { useState } from 'react'
import { describeCall } from '../approval'
import type { ApprovalRequest, Fact } from '../types'

type Props = {
  request: ApprovalRequest // the calls the paused turn waits on
  facts: Fact[] // saved facts, to show forget_memory's targets in words
  onAnswer: (approve: boolean) => void
}

/** The card: a heading, one line per waiting call, and Approve / Deny. */
export function ApprovalCard({ request, facts, onAnswer }: Props) {
  const [answered, setAnswered] = useState(false)

  /** Lock the buttons, then hand the answer to App. */
  function answer(approve: boolean) {
    if (answered) return
    setAnswered(true)
    onAnswer(approve)
  }

  return (
    <section
      aria-label="Approval needed"
      className="rounded-2xl border-[1.5px] border-ink bg-butter px-4 py-3 text-ink shadow-sm"
    >
      <h2 className="font-medium">Simba wants to do this — OK?</h2>
      <ul className="mt-2 space-y-1.5 text-sm">
        {request.calls.map((call) => (
          <li key={call.id}>
            <span className="font-medium">{describeCall(call, facts)}</span>
            <span className="block text-xs text-muted">{call.reason}</span>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={answered}
          onClick={() => answer(true)}
          className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-ink hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:opacity-40"
        >
          Approve
        </button>
        <button
          type="button"
          disabled={answered}
          onClick={() => answer(false)}
          className="rounded-full border-[1.5px] border-ink bg-surface px-4 py-1.5 text-sm font-medium text-ink hover:bg-raised focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:opacity-40"
        >
          Deny
        </button>
      </div>
    </section>
  )
}
