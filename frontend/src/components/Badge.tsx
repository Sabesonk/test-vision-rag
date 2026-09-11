/**
 * A badge, drawn from a `BadgeSpec` and nothing else.
 *
 * There is deliberately no `color` prop and no `className` escape hatch. `lib/badges.ts` decides
 * what each state says and which tone it says it in; this component turns that into a DOM node.
 * Splitting it any other way would let a caller render the `verified` label in the tone of
 * `unverifiable`, and these three words are the product (§13 M7, R2).
 *
 * `data-testid` comes from the spec too, so an E2E assertion names a *state* — `badge-verified` —
 * rather than a colour or a position it happens to be drawn in (U024).
 */
import type { BadgeSpec } from '../lib/badges.ts'

export function Badge({ spec }: { spec: BadgeSpec }) {
  return (
    <span className="badge" data-tone={spec.tone} data-testid={spec.testId} title={spec.title}>
      {spec.label}
    </span>
  )
}
