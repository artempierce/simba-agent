/**
 * approval.ts — puts a waiting tool call into plain words for the approval card (#66b).
 *
 * Kept out of ApprovalCard.tsx because a component file should export only components (React's fast
 * refresh reloads such files in place), and so the wording can be tested on its own.
 */
import type { ApprovalCall, Fact } from './types'

/**
 * One call in plain words. forget_memory gets the facts' own text; any other tool shows its name and
 * arguments as JSON (a tool we don't know yet should still show exactly what it would do).
 *
 * Example: forget_memory {fact_ids: [3]} with fact 3 "Works at Acme" -> 'Forget: “Works at Acme”'
 */
export function describeCall(call: ApprovalCall, facts: Fact[]): string {
  if (call.tool === 'forget_memory') {
    if (call.args.everything === true) return 'Forget everything Simba remembers about you'
    const ids = Array.isArray(call.args.fact_ids) ? call.args.fact_ids : []
    const texts = ids.map((id) => facts.find((f) => f.id === id)?.text ?? `fact #${String(id)}`)
    return `Forget: ${texts.map((t) => `“${t}”`).join(', ')}`
  }
  return `${call.tool} ${JSON.stringify(call.args)}`
}
