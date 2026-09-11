/**
 * Clicking a code, and what the console may say about a rejection.
 *
 * The load-bearing assertion here is the redaction one. §8.4 keeps a rejected `(claim, page)`
 * row in the call log and drops the code, and the temptation for a UI is to put the code back by
 * matching the row against the draft. These tests pin the honest behaviour: the console can say
 * a check came back `absent` on a page, and cannot say which code it was about.
 */
import { describe, expect, it } from 'vitest'

import { checksFor, citedPages, rejectedChecks, targetPage, unbadgedCodes } from './citations.ts'
import type { Answer, Check, RenderedClaim } from '../api/types.ts'

const claim = (code: string, pageId: string, status: RenderedClaim['status']): RenderedClaim => ({
  code,
  page_id: pageId,
  status,
  badge: status === 'present' ? 'verified' : 'read from image, not text-verified',
})

const answer = (over: Partial<Answer> = {}): Answer => ({
  text: '',
  citations: [],
  claims: [],
  warnings: [],
  route: 'read',
  ...over,
})

describe('citedPages', () => {
  it('is empty when there is no answer at all', () => {
    expect(citedPages(null)).toEqual([])
  })

  it('keeps look order and de-duplicates', () => {
    const value = answer({
      citations: ['d@1#p003', 'd@1#p001'],
      claims: [claim('K158', 'd@1#p001', 'present'), claim('X1', 'd@1#p009', 'unverifiable')],
    })
    expect(citedPages(value)).toEqual(['d@1#p003', 'd@1#p001', 'd@1#p009'])
  })

  it('includes a claim’s page even when the citation list omits it', () => {
    const value = answer({ citations: [], claims: [claim('K158', 'd@1#p007', 'present')] })
    expect(citedPages(value)).toEqual(['d@1#p007'])
  })
})

describe('targetPage', () => {
  it('is the page the claim was checked against, never the first citation', () => {
    expect(targetPage(claim('K158', 'd@1#p042', 'present'))).toBe('d@1#p042')
  })
})

describe('checksFor', () => {
  const checks: Check[] = [
    { claim: 'K158', page_id: 'd@1#p001', status: 'present' },
    { claim: 'K158', page_id: 'd@1#p002', status: 'absent' },
    { claim: 'X1', page_id: 'd@1#p001', status: 'unverifiable' },
  ]

  it('matches on the pair, not on the code alone', () => {
    expect(checksFor(claim('K158', 'd@1#p001', 'present'), checks)).toEqual([checks[0]])
  })
})

describe('rejectedChecks', () => {
  it('finds the `absent` rows and cannot name what they were about', () => {
    const checks: Check[] = [
      { claim: 'K158', page_id: 'd@1#p001', status: 'present' },
      { claim: '', page_id: 'd@1#p002', status: 'absent' },
    ]
    const rejected = rejectedChecks(checks)
    expect(rejected).toHaveLength(1)
    expect(rejected[0]?.page_id).toBe('d@1#p002')
    expect(rejected[0]?.claim).toBe('')
  })
})

describe('unbadgedCodes', () => {
  it('is empty on a cleared answer — the gate checks the codes in the text too (§8.4)', () => {
    const value = answer({
      text: 'Replace fuse K158 on the safety list.',
      claims: [claim('K158', 'd@1#p001', 'present')],
    })
    expect(unbadgedCodes(value)).toEqual([])
  })

  it('notices a code-shaped token in the prose with no badge beside it', () => {
    const value = answer({
      text: 'Replace K158, then check X22.',
      claims: [claim('K158', 'd@1#p001', 'present')],
    })
    expect(unbadgedCodes(value)).toEqual(['X22'])
  })

  it('is empty when there is no answer', () => {
    expect(unbadgedCodes(null)).toEqual([])
  })
})
