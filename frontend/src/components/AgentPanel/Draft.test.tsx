/**
 * The draft — M7's load-bearing UI, rendered.
 *
 * Every assertion here is one of U023's acceptance criteria, and three of them are negative:
 * what the console must **not** put on screen. A positive-only suite would pass on a component
 * that rendered the rejected code in grey next to the cleared ones.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { Draft } from './Draft.tsx'
import type { Answer, Check, RenderedClaim } from '../../api/types.ts'
import { BADGE_READ_FROM_IMAGE, BADGE_VERIFIED } from '../../api/types.ts'

afterEach(cleanup)

const verified: RenderedClaim = {
  code: 'K158',
  page_id: 'd@1#p001',
  status: 'present',
  badge: BADGE_VERIFIED,
}

const fromImage: RenderedClaim = {
  code: 'X1',
  page_id: 'd@1#p009',
  status: 'unverifiable',
  badge: BADGE_READ_FROM_IMAGE,
}

function answer(over: Partial<Answer> = {}): Answer {
  return {
    text: 'Fuse K158 is on the safety list.',
    citations: ['d@1#p001'],
    claims: [verified],
    warnings: [],
    route: 'read',
    ...over,
  }
}

function draw(value: Answer, checks: Check[] = [], onSelect = vi.fn()) {
  render(<Draft answer={value} checks={checks} onSelectPage={onSelect} />)
  return onSelect
}

describe('trust badges', () => {
  it('badges a text-verified code `verified`', () => {
    draw(answer())
    expect(screen.getByTestId('badge-verified').textContent).toBe(BADGE_VERIFIED)
  })

  it('badges an image-read code with the service’s exact wording', () => {
    draw(answer({ claims: [fromImage] }))
    expect(screen.getByTestId('badge-read-from-image').textContent).toBe(BADGE_READ_FROM_IMAGE)
  })

  it('draws the two in different tones — the badge is read before the word', () => {
    draw(answer({ claims: [verified, fromImage] }))
    const ok = screen.getByTestId('badge-verified').getAttribute('data-tone')
    const warn = screen.getByTestId('badge-read-from-image').getAttribute('data-tone')
    expect(ok).not.toBe(warn)
  })

  it('renders all three of §13 M7’s badges, each saying a different thing', () => {
    draw(answer({ claims: [verified, fromImage] }), [
      { claim: 'K158', page_id: 'd@1#p001', status: 'present' },
      { claim: 'X1', page_id: 'd@1#p009', status: 'unverifiable' },
    ])
    const labels = ['badge-verified', 'badge-read-from-image', 'check-unverifiable'].map(
      (testId) => screen.getByTestId(testId).textContent,
    )
    expect(labels).toEqual([BADGE_VERIFIED, BADGE_READ_FROM_IMAGE, 'unverifiable'])
    expect(new Set(labels).size).toBe(3)
  })

  it('shares the amber tone between the two disclosures, and only the wording tells them apart', () => {
    // Not an oversight: *read from image* and `unverifiable` are the same condition seen from
    // two places — nobody could check it. Giving the log verdict a third colour would imply a
    // third kind of doubt. What has to differ is the sentence, which the test above pins.
    draw(answer({ claims: [fromImage] }), [
      { claim: 'X1', page_id: 'd@1#p009', status: 'unverifiable' },
    ])
    expect(screen.getByTestId('check-unverifiable').getAttribute('data-tone')).toBe('warn')
    expect(screen.getByTestId('badge-read-from-image').getAttribute('data-tone')).toBe('warn')
    expect(screen.getByTestId('check-unverifiable').textContent).not.toBe(
      screen.getByTestId('badge-read-from-image').textContent,
    )
  })
})

describe('the amber warning', () => {
  it('appears when a rendered code was read from an image', () => {
    draw(answer({ claims: [verified, fromImage] }))
    expect(screen.getByTestId('unverifiable-warning').textContent).toContain(
      'read from the page image',
    )
  })

  it('does not appear when every rendered code was text-verified', () => {
    draw(answer({ claims: [verified] }))
    expect(screen.queryByTestId('unverifiable-warning')).toBeNull()
  })

  it('does not appear merely because the answer took the paid `read` route', () => {
    draw(answer({ claims: [verified], route: 'read' }))
    expect(screen.queryByTestId('unverifiable-warning')).toBeNull()
  })
})

describe('what a rejection leaves on screen', () => {
  it('renders no code for a claim the gate could not clear', () => {
    // `absent` is outside `RenderedClaim`'s union; this is the shape a regression would take,
    // and the component must still refuse to badge it rather than render a bare code.
    const rejected = { ...verified, code: 'K999', status: 'absent' } as unknown as RenderedClaim
    draw(answer({ claims: [rejected] }))
    expect(screen.queryByText('K999')).toBeNull()
    expect(screen.queryAllByTestId('claim')).toHaveLength(0)
  })

  it('warns when a code-shaped token sits in the prose with no badge beside it', () => {
    draw(answer({ text: 'Replace K158, then check X22.', claims: [verified] }))
    expect(screen.getByTestId('unbadged-warning').textContent).toContain('X22')
  })

  it('stays quiet when every code in the prose is badged', () => {
    draw(answer())
    expect(screen.queryByTestId('unbadged-warning')).toBeNull()
  })
})

describe('the citation click', () => {
  it('goes to the page the code was checked against, not the first citation', () => {
    const onSelect = draw(answer({ claims: [verified, fromImage] }))
    fireEvent.click(screen.getByText('X1').closest('button') as HTMLElement)
    expect(onSelect).toHaveBeenCalledWith('d@1#p009')
  })

  it('renders the prose exactly as the look step wrote it (§7.6)', () => {
    draw(answer())
    expect(screen.getByTestId('draft-text').textContent).toBe('Fuse K158 is on the safety list.')
  })
})
