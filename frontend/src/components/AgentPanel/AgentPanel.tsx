/**
 * The right zone: what the agent did, and what it is willing to say.
 *
 * Ordered by what a reader needs first — the outcome, then the pass that chose the pages, then
 * the moves and the gate's calls. An answer and an abstention are mutually exclusive and both
 * are legitimate: §7.1's rule that an outage must never look like an absence has a twin here,
 * which is that an abstention must never look like a failure. A refusal is a `Banner` from the
 * call itself and does not reach this component at all.
 */
import type { AskResponse } from '../../api/types.ts'
import { AbstentionCard } from './AbstentionCard.tsx'
import { Draft } from './Draft.tsx'
import { Moves } from './Moves.tsx'
import { TriagePanel } from './TriagePanel.tsx'

export interface AgentPanelProps {
  response: AskResponse | null
  pending: boolean
  onSelectPage: (pageId: string) => void
}

export function AgentPanel({ response, pending, onSelectPage }: AgentPanelProps) {
  if (pending) {
    return (
      <section className="zone-right" aria-label="agent">
        <p className="empty" data-testid="ask-pending">
          descending, triaging, looking…
        </p>
      </section>
    )
  }

  if (response === null) {
    return (
      <section className="zone-right" aria-label="agent">
        <p className="empty" data-testid="ask-idle">
          Ask a question. Every code in the answer will carry a badge saying who checked it.
        </p>
      </section>
    )
  }

  return (
    <section className="zone-right" aria-label="agent" data-testid="agent-panel" data-status={response.status}>
      {response.answer !== null ? (
        <Draft answer={response.answer} checks={response.checks} onSelectPage={onSelectPage} />
      ) : null}

      {response.abstention !== null ? <AbstentionCard abstention={response.abstention} /> : null}

      <TriagePanel triage={response.triage} onSelectPage={onSelectPage} />

      <Moves
        trace={response.trace}
        loops={response.loops}
        checks={response.checks}
        reads={response.reads}
        readsRemaining={response.reads_remaining}
      />

      <p className="card-meta" data-testid="provenance">
        run <span className="mono">{response.provenance.run_id || '—'}</span> · release{' '}
        <span className="mono">{response.provenance.release_id}</span> · schema{' '}
        <span className="mono">{response.provenance.schema_version}</span>
      </p>
    </section>
  )
}
