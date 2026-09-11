/**
 * The zoom-ladder trail: corpus › binder › chapter › page, and the crop below it.
 *
 * Every crumb behind the current one is a button, because the only way to widen is to climb —
 * and `climbTo` clears everything below the rung it returns to (`lib/ladder.ts`). That is the
 * same lesson U022 learned in the runner and wrote down in the progress file: *"widening by
 * dropping a scope key was undone by the next descent"*. A breadcrumb that left the `doc_id` set
 * would be the same defect with a mouse attached.
 */
import { type Crumb, type Ladder, type Rung, crumbs, rungOf } from '../../lib/ladder.ts'
import { regionQuery } from '../../lib/dpi.ts'

export interface BreadcrumbsProps {
  ladder: Ladder
  onClimb: (rung: Rung) => void
}

export function Breadcrumbs({ ladder, onClimb }: BreadcrumbsProps) {
  const trail: Crumb[] = crumbs(ladder)
  const here = rungOf(ladder)

  return (
    <nav className="breadcrumbs" aria-label="zoom ladder" data-testid="breadcrumbs" data-rung={here}>
      {trail.map((crumb, index) => (
        <span key={crumb.rung}>
          {index > 0 ? <span className="crumb-sep"> › </span> : null}
          <button
            type="button"
            className="crumb"
            data-testid={`crumb-${crumb.rung}`}
            aria-current={crumb.current ? 'step' : undefined}
            disabled={!crumb.reachable || crumb.current}
            onClick={() => onClimb(crumb.rung)}
          >
            {crumb.label}
          </button>
        </span>
      ))}
      {ladder.region !== null ? (
        <span data-testid="crumb-region">
          <span className="crumb-sep"> › </span>
          <span className="crumb" aria-current="step">
            region {regionQuery(ladder.region)} @ {ladder.dpi} dpi
          </span>
        </span>
      ) : null}
    </nav>
  )
}
