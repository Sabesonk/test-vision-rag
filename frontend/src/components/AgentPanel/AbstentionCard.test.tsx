/**
 * The abstention — §8.5's honest nothing.
 *
 * The headline assertion is `image_only_unexamined`. While it is above zero the system may not
 * say *"not in these documents"*, because nobody has been to the pages where the answer would
 * be; the card has to put that number where a reader cannot miss it, and name the documents
 * those pages are in. U024's E2E asserts the same fact in a browser — *"the abstention text
 * names the unread image-only pages"* — so this is the L0 half of that.
 *
 * An abstention is also **not a failure**, and the second group below pins that: no `alert`, no
 * error banner, no empty panel. A console that rendered a considered refusal to answer as
 * something having gone wrong would teach an operator to distrust the one behaviour this whole
 * design exists to produce.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import { AbstentionCard } from './AbstentionCard.tsx'
import type { Abstention } from '../../api/types.ts'

afterEach(cleanup)

const abstention = (over: Partial<Abstention> = {}): Abstention => ({
  text: 'Not found in the searchable text of CE-TC1AV8.',
  reason: 'not_found',
  searched: ['CE-TC1AV8'],
  pages_searched: 42,
  pages_no_text: 6,
  pages_no_text_read: 1,
  image_only_unexamined: 5,
  blind_documents: ['CE-TC1AV8'],
  rejected_claims: 0,
  ...over,
})

describe('the blind spot', () => {
  it('names the unread image-only pages and the documents they are in', () => {
    render(<AbstentionCard abstention={abstention()} />)
    const notice = screen.getByTestId('blind-spot')
    expect(notice.textContent).toContain('5')
    expect(notice.textContent).toContain('CE-TC1AV8')
  })

  it('says why this is not “not in these documents”', () => {
    render(<AbstentionCard abstention={abstention()} />)
    expect(screen.getByTestId('blind-spot').textContent).toContain('not “not in these documents”')
  })

  it('does not warn when every image-only page was actually read', () => {
    render(
      <AbstentionCard
        abstention={abstention({ pages_no_text: 6, pages_no_text_read: 6, image_only_unexamined: 0 })}
      />,
    )
    expect(screen.queryByTestId('blind-spot')).toBeNull()
  })

  it('shows the coverage numbers §8.5 says make the wording honest', () => {
    render(<AbstentionCard abstention={abstention()} />)
    const coverage = screen.getByTestId('coverage').textContent ?? ''
    for (const number of ['42', '6', '1', '5']) expect(coverage).toContain(number)
  })
})

describe('an abstention is not a failure', () => {
  it('renders the loop’s own words, and no error banner', () => {
    render(<AbstentionCard abstention={abstention()} />)
    expect(screen.getByTestId('abstention-text').textContent).toBe(
      'Not found in the searchable text of CE-TC1AV8.',
    )
    expect(screen.queryByTestId('error-banner')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('carries the reason the loop stopped, for a reviewer who wants the state', () => {
    const { container } = render(<AbstentionCard abstention={abstention({ reason: 'rejected' })} />)
    expect(container.querySelector('[data-reason="rejected"]')).toBeTruthy()
  })

  it('counts rejected claims when that is why there is no answer, without naming the codes', () => {
    render(<AbstentionCard abstention={abstention({ reason: 'rejected', rejected_claims: 2 })} />)
    expect(screen.getByTestId('rejected-claims').textContent).toContain('2')
  })

  it('omits the rejection count entirely when nothing was rejected', () => {
    render(<AbstentionCard abstention={abstention()} />)
    expect(screen.queryByTestId('rejected-claims')).toBeNull()
  })
})
