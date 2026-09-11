/**
 * The badges — the mapping this console exists to get right.
 *
 * These assertions are deliberately about *distinctness* rather than about wording alone. A test
 * that only checked the labels would pass on a UI that drew all three in the same colour, and
 * "visually distinct" is the actual requirement (§13 M7, §16 Frontend): a technician scanning an
 * answer sees the tone before they read the word.
 */
import { describe, expect, it } from 'vitest'

import {
  UNVERIFIABLE_WARNING,
  checkBadge,
  claimBadge,
  markBadge,
  statusBadge,
  trustBadge,
  warnsUnverifiable,
} from './badges.ts'
import { BADGE_READ_FROM_IMAGE, BADGE_VERIFIED, type Status } from '../api/types.ts'

describe('claimBadge', () => {
  it('badges a text-verified code with the service’s own word', () => {
    expect(claimBadge('present')?.label).toBe(BADGE_VERIFIED)
    expect(claimBadge('present')?.tone).toBe('ok')
  })

  it('badges an image-read code with the service’s own wording, not a paraphrase', () => {
    expect(claimBadge('unverifiable')?.label).toBe(BADGE_READ_FROM_IMAGE)
    expect(claimBadge('unverifiable')?.tone).toBe('warn')
  })

  it('refuses to badge `absent` — a rejected draft never reaches a reader (§8.4, I8)', () => {
    expect(claimBadge('absent')).toBeNull()
  })

  it('draws the two claim badges in different tones and with different test ids', () => {
    const verified = claimBadge('present')
    const read = claimBadge('unverifiable')
    expect(verified?.tone).not.toBe(read?.tone)
    expect(verified?.testId).not.toBe(read?.testId)
  })
})

describe('checkBadge', () => {
  it('gives all three verdicts a distinct tone, label and test id', () => {
    const specs = (['present', 'absent', 'unverifiable'] as const).map(checkBadge)
    expect(new Set(specs.map((spec) => spec.tone)).size).toBe(3)
    expect(new Set(specs.map((spec) => spec.label)).size).toBe(3)
    expect(new Set(specs.map((spec) => spec.testId)).size).toBe(3)
  })

  it('is distinct from the claim badges — a log verdict is not a disclosure on an answer', () => {
    expect(checkBadge('unverifiable').testId).not.toBe(claimBadge('unverifiable')?.testId)
  })
})

describe('warnsUnverifiable', () => {
  it('warns exactly when a rendered code carries the read-from-image badge', () => {
    expect(warnsUnverifiable([])).toBe(false)
    expect(warnsUnverifiable([{ status: 'present' }])).toBe(false)
    expect(warnsUnverifiable([{ status: 'present' }, { status: 'unverifiable' }])).toBe(true)
  })

  it('carries the service’s constant, not a restatement of it', () => {
    expect(UNVERIFIABLE_WARNING).toContain('read from the page image')
  })
})

describe('statusBadge', () => {
  const ABSENCES: Status[] = ['not_found', 'not_searchable', 'out_of_scope', 'found_only_in_superseded']

  it('keeps `not_found` and `not_searchable` visually and verbally apart (F4)', () => {
    const notFound = statusBadge('not_found')
    const notSearchable = statusBadge('not_searchable')
    expect(notFound.tone).not.toBe(notSearchable.tone)
    expect(notFound.label).not.toBe(notSearchable.label)
    expect(notFound.testId).not.toBe(notSearchable.testId)
    expect(notFound.action).not.toBe(notSearchable.action)
  })

  it('gives each of the four absences its own next move', () => {
    const actions = ABSENCES.map((status) => statusBadge(status).action)
    expect(new Set(actions).size).toBe(4)
  })

  it('tells a reader never to abstain on an error — it is not an absence', () => {
    expect(statusBadge('error').action.toLowerCase()).toContain('never abstain')
    expect(statusBadge('error').tone).toBe('bad')
  })

  it('says `escalate to vision` on not_searchable, and does not deny the part exists', () => {
    const spec = statusBadge('not_searchable')
    expect(spec.action.toLowerCase()).toContain('escalate to vision')
    expect(spec.action.toLowerCase()).toContain('do not conclude')
  })
})

describe('trustBadge and markBadge', () => {
  it('gives the four text-trust levels four distinct labels', () => {
    const labels = (['ok', 'degraded', 'untrusted', 'no_text'] as const).map(
      (trust) => trustBadge(trust).label,
    )
    expect(new Set(labels).size).toBe(4)
  })

  it('gives the three triage marks three distinct tones — the panel must show all three', () => {
    const tones = (['relevant', 'uncertain', 'irrelevant'] as const).map(
      (mark) => markBadge(mark).tone,
    )
    expect(new Set(tones).size).toBe(3)
  })

  it('describes the `uncertain` pool as retained, not rejected (§8.2)', () => {
    expect(markBadge('uncertain').title.toLowerCase()).toContain('retained')
  })
})
