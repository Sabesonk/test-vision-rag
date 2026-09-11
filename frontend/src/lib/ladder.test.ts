/**
 * The zoom ladder.
 *
 * Two of these are regression tests for defects the runner already hit once. U022's progress
 * note records that *"widening by dropping a scope key was undone by the next descent"*; a
 * breadcrumb that climbed without clearing what is below it is that same defect with a mouse
 * attached. And carrying a crop from one page to the next would render a successful picture of
 * the wrong corner — a failure that looks like a success, which is the class this project spends
 * most of its effort on.
 */
import { describe, expect, it } from 'vitest'

import { DPI_INDEX } from './dpi.ts'
import {
  TOP,
  climbTo,
  crumbs,
  docIdOf,
  hashForPage,
  jumpToPage,
  ladderFromHash,
  pageIdFromHash,
  rungOf,
  toBinder,
  toChapter,
  toPage,
} from './ladder.ts'

const deep = toPage(
  toChapter(toBinder(TOP, 'TC1E-SF@1.3', 'Service manual'), 'sec-4', 'Safety'),
  'TC1E-SF@1.3#p041',
  '4-12',
)

describe('rungOf', () => {
  it('is the deepest rung whose id is set', () => {
    expect(rungOf(TOP)).toBe('corpus')
    expect(rungOf(toBinder(TOP, 'd@1', 'D'))).toBe('binder')
    expect(rungOf(toChapter(toBinder(TOP, 'd@1', 'D'), 's', 'S'))).toBe('chapter')
    expect(rungOf(deep)).toBe('page')
  })
})

describe('climbTo', () => {
  it('clears everything below the rung it returns to', () => {
    const atBinder = climbTo(deep, 'binder')
    expect(atBinder.docId).toBe('TC1E-SF@1.3')
    expect(atBinder.sectionId).toBeNull()
    expect(atBinder.pageId).toBeNull()
  })

  it('drops the crop and the escalated dpi with the page they were made on', () => {
    const escalated = { ...deep, dpi: 400 as const, region: [0, 0, 0.5, 0.5] as [number, number, number, number] }
    const atChapter = climbTo(escalated, 'chapter')
    expect(atChapter.region).toBeNull()
    expect(atChapter.dpi).toBe(DPI_INDEX)
  })

  it('returning to the corpus leaves no scope behind', () => {
    expect(climbTo(deep, 'corpus')).toEqual(TOP)
  })
})

describe('crumbs', () => {
  it('marks the current rung and makes only the rungs above it reachable', () => {
    const trail = crumbs(toBinder(TOP, 'd@1', 'Binder one'))
    expect(trail.map((crumb) => crumb.reachable)).toEqual([true, true, false, false])
    expect(trail.find((crumb) => crumb.current)?.rung).toBe('binder')
  })

  it('labels a binder with the corpus’s own title', () => {
    expect(crumbs(toBinder(TOP, 'd@1', 'Service manual'))[1]?.label).toBe('Service manual')
  })

  it('falls back to the id rather than inventing a name', () => {
    expect(crumbs(toBinder(TOP, 'd@1', ''))[1]?.label).toBe('d@1')
  })
})

describe('jumpToPage', () => {
  it('recovers the binder from the page id so the trail says where the reader landed', () => {
    const landed = jumpToPage('TC1E-SF@1.3#p041')
    expect(landed.docId).toBe('TC1E-SF@1.3')
    expect(landed.pageId).toBe('TC1E-SF@1.3#p041')
    expect(rungOf(landed)).toBe('page')
  })

  it('claims no chapter — a page id does not carry one', () => {
    expect(jumpToPage('TC1E-SF@1.3#p041').sectionId).toBeNull()
  })

  it('opens at the index dpi with no crop, whatever the previous page was showing', () => {
    const landed = jumpToPage('d@1#p002')
    expect(landed.dpi).toBe(DPI_INDEX)
    expect(landed.region).toBeNull()
  })

  it('labels with the `pNNN` tail — a sequence number, never presented as a printed page', () => {
    expect(jumpToPage('d@1#p007').pageLabel).toBe('p007')
  })

  it('survives an id that is not shaped like one, rather than guessing', () => {
    expect(docIdOf('not-a-page-id')).toBeNull()
    expect(jumpToPage('not-a-page-id').docId).toBeNull()
  })
})

// ── the deep link (U024) ────────────────────────────────────────────────────────────────────────

describe('the page deep link', () => {
  const PAGE = 'TC1E-SF@1.3#p012'

  it('round-trips a page id through the hash, escapes and all', () => {
    const hash = hashForPage(PAGE)
    // `#` and `@` both occur in a page id (§5.1) and one of them is the hash delimiter, so the
    // escaping is the whole of this assertion rather than a formality.
    expect(hash).toBe('#/page/TC1E-SF%401.3%23p012')
    expect(pageIdFromHash(hash)).toBe(PAGE)
  })

  it('addresses nothing above the page rung, and reads nothing out of an unrelated hash', () => {
    expect(hashForPage(null)).toBe('')
    expect(pageIdFromHash('')).toBeNull()
    expect(pageIdFromHash('#/page/')).toBeNull()
    expect(pageIdFromHash('#something-else')).toBeNull()
  })

  it('reads a half-written escape as addressing nothing rather than throwing in a render', () => {
    expect(pageIdFromHash('#/page/%E0%A4%A')).toBeNull()
  })

  it('lands on the page with the binder recovered, exactly as a citation click does', () => {
    expect(ladderFromHash(hashForPage(PAGE))).toEqual(jumpToPage(PAGE))
    expect(ladderFromHash('#/page/')).toBeNull()
  })
})
