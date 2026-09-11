/**
 * The agent's moves, collapsible — §13 M7's *"collapsible agent moves (skim/read/verify)"*.
 *
 * The trace is the honest account of how the answer was reached: `descend → triage → look →
 * draft → verify`, one row per move, with the state it was in and the signal it left on. It is
 * collapsed by default because the answer is what a reader came for; it is *here* because an
 * answer nobody can audit is the thing this whole design distrusts.
 *
 * **`spends` is marked.** It is true on exactly the `read` moves (§8.1a), and it is the only
 * place in this response where money is visible at all — cost goes to the audit log, never into
 * the body (§7.4). What a reader gets is which move billed, and how much quota is left.
 */
import type { Check, Move } from '../../api/types.ts'
import { checkBadge } from '../../lib/badges.ts'
import { Badge } from '../Badge.tsx'

export interface MovesProps {
  trace: Move[]
  loops: string[]
  checks: Check[]
  reads: number
  readsRemaining: number
}

export function Moves({ trace, loops, checks, reads, readsRemaining }: MovesProps) {
  return (
    <>
      <details className="panel" data-testid="moves">
        <summary>
          moves <span className="faint">{trace.length}</span>
          {reads > 0 ? <span className="faint">· {reads} paid read(s)</span> : null}
        </summary>
        <div className="panel-body">
          <div className="numbers">
            <span>
              reads <b>{reads}</b>
            </span>
            <span>
              remaining <b>{readsRemaining}</b>
            </span>
          </div>
          <div className="moves">
            {trace.map((move) => (
              <details className="move" key={move.step} data-testid="move" data-action={move.action}>
                <summary>
                  <span className="move-step">{String(move.step).padStart(2, '0')}</span>
                  <span className="move-action">{move.action}</span>
                  <span className="faint">{move.state}</span>
                  {move.spends ? (
                    <span className="badge" data-tone="spend" data-testid="move-spends">
                      spends
                    </span>
                  ) : null}
                  <span className="faint">→ {move.signal}</span>
                </summary>
                <div className="move-detail">{move.detail}</div>
              </details>
            ))}
          </div>
          {loops.length > 0 ? (
            <p className="card-meta" data-testid="loops">
              correction loops fired: <span className="mono">{loops.join(', ')}</span>
            </p>
          ) : null}
        </div>
      </details>

      <details className="panel" data-testid="checks">
        <summary>
          the gate’s calls <span className="faint">{checks.length}</span>
        </summary>
        <div className="panel-body">
          <table className="rows" data-testid="check-rows">
            <thead>
              <tr>
                <th>claim</th>
                <th>page</th>
                <th>verdict</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((check, index) => (
                <tr key={`${check.page_id}-${index}`} data-testid="check-row" data-status={check.status}>
                  <td className="mono">
                    {check.claim !== '' ? (
                      check.claim
                    ) : (
                      <span className="faint" title="A rejection never echoes the code it rejected.">
                        redacted
                      </span>
                    )}
                  </td>
                  <td className="mono">{check.page_id}</td>
                  <td>
                    <Badge spec={checkBadge(check.status)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {checks.length === 0 ? <p className="empty">No claim was checked.</p> : null}
        </div>
      </details>
    </>
  )
}
