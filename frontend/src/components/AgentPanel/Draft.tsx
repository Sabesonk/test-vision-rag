/**
 * The answer, with a badge on every code — the surface §8.4 and I8 exist to make safe.
 *
 * Four properties, and each is an acceptance criterion rather than a design preference:
 *
 *   * **Every rendered code carries a badge.** The claims are rendered from `answer.claims`, and
 *     a `RenderedClaim` can only be `present` or `unverifiable` — `absent` is not in the union,
 *     because a draft carrying one was rejected whole (not the code: the draft). So *"a code the
 *     gate rejected is absent from the rendered draft"* is true here by construction, and the
 *     rejection shows up one panel down as a redacted row in the call log.
 *   * **The prose is not rewritten.** `answer.text` is the look step's own words (§7.6 refuses
 *     composition), so it is rendered as it arrived. What this component may do is *notice*: if
 *     a code-shaped token appears in the text with no badge beside it, that is reported as a
 *     warning rather than quietly displayed, because the gate checks the union of the declared
 *     claims and the codes in the text.
 *   * **The amber warning appears exactly when a rendered code was read from an image.** Not
 *     when the answer took the `read` route, not when a page had no text — when a code a reader
 *     can see carries the *read from image* badge.
 *   * **Clicking a code goes to the page it was checked against**, which is `claim.page_id` and
 *     never the first citation (`lib/citations.ts`).
 */
import type { Answer, Check, RenderedClaim } from '../../api/types.ts'
import { UNVERIFIABLE_WARNING, checkBadge, claimBadge, warnsUnverifiable } from '../../lib/badges.ts'
import { checksFor, unbadgedCodes } from '../../lib/citations.ts'
import { Badge } from '../Badge.tsx'
import { Notice } from '../Banner.tsx'

export interface DraftProps {
  answer: Answer
  checks: Check[]
  onSelectPage: (pageId: string) => void
}

export function Draft({ answer, checks, onSelectPage }: DraftProps) {
  const unverifiable = warnsUnverifiable(answer.claims)
  const unbadged = unbadgedCodes(answer)

  return (
    <section className="panel" data-testid="draft" data-route={answer.route}>
      <h2 className="panel-head">
        answer
        <span className="faint">via {answer.route}</span>
      </h2>
      <div className="panel-body">
        {unverifiable ? (
          <Notice testId="unverifiable-warning">{UNVERIFIABLE_WARNING}</Notice>
        ) : null}

        {unbadged.length > 0 ? (
          <Notice testId="unbadged-warning">
            {unbadged.length} code-shaped token(s) appear in this text with no badge beside them:{' '}
            <span className="mono">{unbadged.join(', ')}</span>. Every code the gate cleared is
            listed below; treat anything else as unchecked.
          </Notice>
        ) : null}

        <p className="draft-text" data-testid="draft-text">
          {answer.text}
        </p>

        <div className="claims" data-testid="claims">
          {answer.claims.map((claim) => (
            <Claim
              key={`${claim.code}@${claim.page_id}`}
              claim={claim}
              checks={checksFor(claim, checks)}
              onSelect={() => onSelectPage(claim.page_id)}
            />
          ))}
          {answer.claims.length === 0 ? (
            <p className="empty" data-testid="claims-empty">
              This answer declares no codes.
            </p>
          ) : null}
        </div>

        <p className="card-meta" data-testid="citations">
          cited pages: <span className="mono">{answer.citations.join(', ') || 'none'}</span>
        </p>
      </div>
    </section>
  )
}

function Claim({
  claim,
  checks,
  onSelect,
}: {
  claim: RenderedClaim
  checks: Check[]
  onSelect: () => void
}) {
  const badge = claimBadge(claim.status)
  // Unreachable through `RenderedClaim`, whose union excludes `absent` — and rendering nothing
  // rather than a bare code is what keeps it unreachable if that ever stops being true.
  if (badge === null) return null

  return (
    <button
      type="button"
      className="claim"
      data-testid="claim"
      data-code={claim.code}
      data-page-id={claim.page_id}
      data-status={claim.status}
      onClick={onSelect}
      title={`go to ${claim.page_id} — the page this code was checked against`}
    >
      <span className="claim-code">{claim.code}</span>
      <Badge spec={badge} />
      {checks.map((check, index) => (
        <Badge key={`${check.page_id}-${index}`} spec={checkBadge(check.status)} />
      ))}
      <span className="claim-page">{claim.page_id}</span>
    </button>
  )
}
