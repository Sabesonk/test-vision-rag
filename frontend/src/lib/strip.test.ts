/**
 * Strip rows, and the one fact this console refuses to invent.
 *
 * `evidencePages` is handed an answer that carries page ids and no `text_trust`, and the
 * assertion that matters is the negative one: it leaves `trust` null rather than inferring
 * "scan" from an `unverifiable` verdict. `unverifiable` has three causes (§5.7) and the body did
 * not say which — a guessed badge would be the console asserting something nobody measured.
 */
import { describe, expect, it } from 'vitest'

import { evidencePages, stripPageOf } from './strip.ts'
import { DPI_THUMB } from './dpi.ts'
import type { Answer, PageHit } from '../api/types.ts'

const hit = (over: Partial<PageHit> = {}): PageHit => ({
  page_id: 'd@1#p001',
  printed_page_no: '4-12',
  summary: '',
  summary_lang: 'en',
  page_kind: 'schematic',
  why: ['dense', 'lexical'],
  rank: 1,
  flags: [],
  grounded_rate: 0.8,
  text_trust: 'ok',
  image: { url: '/pages/d@1%23p001/image?dpi=150', thumb_url: '/pages/d@1%23p001/image?dpi=72', dpi: 150, width: 1, height: 1 },
  next: null,
  ...over,
})

describe('stripPageOf', () => {
  it('uses the thumb_url already on the row — no second endpoint (D12)', () => {
    expect(stripPageOf(hit()).thumbUrl).toBe('/pages/d@1%23p001/image?dpi=72')
  })

  it('prefers the printed label over the id', () => {
    expect(stripPageOf(hit()).label).toBe('4-12')
    expect(stripPageOf(hit({ printed_page_no: '' })).label).toBe('d@1#p001')
  })

  it('carries the row’s own trust, and its account of which surfaces found it', () => {
    const row = stripPageOf(hit({ text_trust: 'no_text', why: ['dense'] }))
    expect(row.trust).toBe('no_text')
    expect(row.note).toContain('dense')
  })

  it('has no thumbnail when the row carried no image reference', () => {
    expect(stripPageOf(hit({ image: null })).thumbUrl).toBeNull()
  })
})

describe('evidencePages', () => {
  const answer: Answer = {
    text: 'K158 is on the safety list; X1 was read off the drawing.',
    citations: ['d@1#p001'],
    claims: [
      { code: 'K158', page_id: 'd@1#p001', status: 'present', badge: 'verified' },
      { code: 'X1', page_id: 'd@1#p009', status: 'unverifiable', badge: 'read from image, not text-verified' },
    ],
    warnings: [],
    route: 'read',
  }

  it('is empty without an answer', () => {
    expect(evidencePages(null)).toEqual([])
  })

  it('lists every cited page once, in look order', () => {
    expect(evidencePages(answer).map((page) => page.pageId)).toEqual(['d@1#p001', 'd@1#p009'])
  })

  it('leaves trust unknown rather than inferring a scan from an `unverifiable` verdict', () => {
    expect(evidencePages(answer).every((page) => page.trust === null)).toBe(true)
  })

  it('builds the thumbnail at the same dpi a thumb_url is rendered at', () => {
    expect(evidencePages(answer)[0]?.thumbUrl).toBe(`/pages/d@1%23p001/image?dpi=${DPI_THUMB}`)
  })

  it('says what the gate decided about each page, using the badge the service sent', () => {
    expect(evidencePages(answer)[1]?.note).toContain('read from image, not text-verified')
  })
})
