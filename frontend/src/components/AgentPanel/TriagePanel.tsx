/**
 * The tri-state triage table — §8.2's pass, as the pass it really was.
 *
 * **Driven by the typed `triage` field, never by a trace `Move.detail`.** That is a requirement
 * rather than an implementation note, and it is the reason this panel came with a backend change
 * (plan §4c P7): before U023, the only triage a caller could see was one prose sentence inside a
 * move, and the `exclude` set's page ids were not in the response body at all. A console that
 * regexed that sentence would be a second declaration of §8.2's contract, written in a language
 * that cannot fail a test when the sentence is reworded.
 *
 * What the table has to show, and why each column earns its place:
 *
 *   * **all three marks.** A binary keep/drop would not need a panel. `uncertain` is the pool —
 *     retained, drained before the scope is widened — and a reviewer who cannot see it cannot
 *     tell a rejection from a deferral.
 *   * **`reason`**, one of §8.2's rules and never free text: *which* rule produced the mark.
 *   * **`matched`**, the terms of the question the page's summary actually showed. This is the
 *     evidence, and it is what `triage.Mark` keeps it for — *"so a triage table can be reviewed
 *     rather than trusted"*.
 *   * **`promoted`**, where safeguard 4 fired and no summary was consulted at all.
 *
 * There is no score column, because there is no score (§7.6). `rank` is the ordinal the skim
 * already returned.
 */
import type { TriageRow, TriageTable } from '../../api/types.ts'
import { markBadge } from '../../lib/badges.ts'
import { Badge } from '../Badge.tsx'

export interface TriagePanelProps {
  /** `null` means nothing was ever triaged — not the same fact as a table with no rows. */
  triage: TriageTable | null
  onSelectPage: (pageId: string) => void
}

const MARKS = ['relevant', 'uncertain', 'irrelevant'] as const

export function TriagePanel({ triage, onSelectPage }: TriagePanelProps) {
  if (triage === null) {
    return (
      <section className="panel" data-testid="triage-none">
        <h2 className="panel-head">triage</h2>
        <div className="panel-body">
          <p className="empty">
            Nothing was ever triaged — the descent offered no candidate to mark.
          </p>
        </div>
      </section>
    )
  }

  const counts = MARKS.map((mark) => ({
    mark,
    rows: triage.rows.filter((row) => row.mark === mark),
  }))

  return (
    <details className="panel" open data-testid="triage">
      <summary>
        triage
        {counts.map(({ mark, rows }) => (
          <span key={mark} data-testid={`triage-count-${mark}`}>
            <Badge spec={markBadge(mark)} /> {rows.length}
          </span>
        ))}
        {triage.small_set ? <span className="faint">small set — nothing filtered</span> : null}
      </summary>
      <div className="panel-body">
        <p className="card-meta">
          triaged against <span className="mono">{triage.query}</span>
        </p>

        <table className="rows" data-testid="triage-rows">
          <thead>
            <tr>
              <th>page</th>
              <th>mark</th>
              <th>rule</th>
              <th>rank</th>
              <th>found by</th>
              <th>matched on</th>
            </tr>
          </thead>
          <tbody>
            {triage.rows.map((row) => (
              <Row key={row.page_id} row={row} onSelect={() => onSelectPage(row.page_id)} />
            ))}
          </tbody>
        </table>
        {triage.rows.length === 0 ? (
          <p className="empty" data-testid="triage-empty">
            A pass that marked nothing.
          </p>
        ) : null}

        <p className="card-meta" data-testid="triage-exclude" data-count={triage.exclude.length}>
          excluded from the next rung ({triage.exclude.length}):{' '}
          <span className="mono">{triage.exclude.join(', ') || 'none'}</span>
        </p>
        <p className="faint">
          The `uncertain` pool is never excluded — dropping it would delete the fallback the
          tri-state exists to keep (§8.2).
        </p>
      </div>
    </details>
  )
}

function Row({ row, onSelect }: { row: TriageRow; onSelect: () => void }) {
  return (
    <tr data-testid="triage-row" data-page-id={row.page_id} data-mark={row.mark}>
      <td>
        <button type="button" className="linkish" onClick={onSelect}>
          {row.page_id}
        </button>
      </td>
      <td>
        <Badge spec={markBadge(row.mark)} />
        {row.promoted ? <span className="faint"> promoted</span> : null}
      </td>
      <td className="mono">{row.reason}</td>
      <td className="mono">{row.rank}</td>
      <td className="terms">{row.why.join(' + ')}</td>
      <td className="terms">{row.matched.join(', ') || <span className="faint">—</span>}</td>
    </tr>
  )
}
