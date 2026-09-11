/**
 * The triage panel, and the field it is not allowed to be built from.
 *
 * Plan §4c P7 is the reason this component and its backend half shipped together: before U023
 * the only triage a caller could see was a sentence inside a trace `Move.detail`, and the
 * `exclude` set's page ids were nowhere in the body. The last test in this file is the one that
 * keeps it that way — the panel renders a table that contradicts the prose, and the table wins.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { TriagePanel } from './TriagePanel.tsx'
import type { TriageRow, TriageTable } from '../../api/types.ts'

afterEach(cleanup)

const row = (over: Partial<TriageRow> & Pick<TriageRow, 'page_id' | 'mark'>): TriageRow => ({
  reason: 'summary_terms',
  rank: 1,
  why: ['dense'],
  matched: [],
  promoted: false,
  ...over,
})

const table: TriageTable = {
  query: 'which fuse protects the pump',
  rows: [
    row({ page_id: 'd@1#p001', mark: 'relevant', matched: ['fuse', 'pump'], rank: 1 }),
    row({ page_id: 'd@1#p004', mark: 'uncertain', reason: 'no_summary', rank: 2 }),
    row({ page_id: 'd@1#p009', mark: 'irrelevant', reason: 'no_term_overlap', rank: 3 }),
  ],
  exclude: ['d@1#p009'],
  small_set: false,
}

function draw(value: TriageTable | null, onSelect = vi.fn()) {
  render(<TriagePanel triage={value} onSelectPage={onSelect} />)
  return onSelect
}

describe('all three states', () => {
  it('renders a row per candidate, marked', () => {
    draw(table)
    const rows = screen.getAllByTestId('triage-row')
    expect(rows.map((element) => element.getAttribute('data-mark'))).toEqual([
      'relevant',
      'uncertain',
      'irrelevant',
    ])
  })

  it('shows the `uncertain` pool rather than collapsing triage to keep/drop', () => {
    draw(table)
    expect(screen.getByTestId('triage-count-uncertain').textContent).toContain('1')
  })

  it('shows the §8.2 rule that produced each mark, and the terms it matched on', () => {
    draw(table)
    expect(screen.getByText('no_term_overlap')).toBeTruthy()
    expect(screen.getByText('fuse, pump')).toBeTruthy()
  })

  it('carries no score column — `rank` is the ordinal the skim returned (§7.6)', () => {
    draw(table)
    const headers = screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    expect(headers).not.toContain('score')
    expect(headers).toContain('rank')
  })
})

describe('the exclude set', () => {
  it('is read from the typed field, not counted off the rows', () => {
    // The table below says two rows are `irrelevant`; the `exclude` field — the loop's own
    // cumulative set, which after Loop 4 also holds the page a rejected claim was cited on —
    // says three ids. The panel must report the field.
    draw({
      ...table,
      rows: [
        row({ page_id: 'a#p1', mark: 'irrelevant' }),
        row({ page_id: 'a#p2', mark: 'irrelevant' }),
      ],
      exclude: ['a#p1', 'a#p2', 'a#p7'],
    })
    const exclude = screen.getByTestId('triage-exclude')
    expect(exclude.getAttribute('data-count')).toBe('3')
    expect(exclude.textContent).toContain('a#p7')
  })

  it('never lists the `uncertain` pool', () => {
    draw(table)
    expect(screen.getByTestId('triage-exclude').textContent).not.toContain('d@1#p004')
  })

  it('says `none` rather than going blank when nothing was excluded', () => {
    draw({ ...table, exclude: [] })
    expect(screen.getByTestId('triage-exclude').textContent).toContain('none')
  })
})

describe('null is not an empty table', () => {
  it('says nothing was ever triaged when the field is null', () => {
    draw(null)
    expect(screen.getByTestId('triage-none')).toBeTruthy()
    expect(screen.queryByTestId('triage-rows')).toBeNull()
  })

  it('says a pass marked nothing when the rows are empty', () => {
    draw({ ...table, rows: [], exclude: [] })
    expect(screen.queryByTestId('triage-none')).toBeNull()
    expect(screen.getByTestId('triage-empty')).toBeTruthy()
  })
})

describe('navigation', () => {
  it('a page id in the table goes to that page', () => {
    const onSelect = draw(table)
    fireEvent.click(screen.getByText('d@1#p004'))
    expect(onSelect).toHaveBeenCalledWith('d@1#p004')
  })
})
