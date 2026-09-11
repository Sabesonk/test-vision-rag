/**
 * The strip: the virtualization bound, and the scroll a citation click depends on.
 *
 * Both halves of §16's list rule are asserted on the rendered DOM, because that is where the
 * cost is — a row here is an authenticated raster request, so an un-windowed 400-page binder is
 * 400 `GET`s nobody asked for.
 *
 * The scroll test is the other half of *"clicking a code scrolls the viewer to its cited page"*:
 * `Draft.test.tsx` proves the click reports `claim.page_id`, and this proves the strip goes
 * there — including when the row is outside the window and therefore not in the DOM to scroll to.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen } from '@testing-library/react'

import { PageStrip } from './PageStrip.tsx'
import { ROW_HEIGHT, VIRTUALIZE_ABOVE } from '../../lib/window.ts'
import type { StripPage } from '../../lib/strip.ts'
import { renderWithQuery } from '../../test/harness.tsx'

const pages = (count: number): StripPage[] =>
  Array.from({ length: count }, (_unused, index) => ({
    pageId: `d@1#p${String(index + 1).padStart(3, '0')}`,
    label: `page ${index + 1}`,
    thumbUrl: null,
    imageUrl: null,
    trust: 'ok' as const,
    note: 'dense',
  }))

beforeEach(() => {
  // No thumbnail bytes are needed for these assertions, and a real request would make the test
  // depend on a service. A rejected fetch renders the placeholder, which is the point: the row
  // count is what is being measured, not the pictures.
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('no network in L0'))))
})

afterEach(() => {
  vi.unstubAllGlobals()
  cleanup()
})

describe('virtualization', () => {
  it('renders a 50-row list whole', () => {
    renderWithQuery(<PageStrip pages={pages(VIRTUALIZE_ABOVE)} selected={null} onSelect={vi.fn()} />)
    expect(screen.getAllByTestId('strip-row')).toHaveLength(VIRTUALIZE_ABOVE)
    expect(screen.getByTestId('page-strip').getAttribute('data-virtualized')).toBe('false')
  })

  it('renders far fewer than 400 rows for a 400-page binder', () => {
    renderWithQuery(<PageStrip pages={pages(400)} selected={null} onSelect={vi.fn()} />)
    const rendered = screen.getAllByTestId('strip-row')
    expect(rendered.length).toBeLessThan(40)
    expect(screen.getByTestId('page-strip').getAttribute('data-virtualized')).toBe('true')
    expect(screen.getByTestId('page-strip').getAttribute('data-count')).toBe('400')
  })

  it('keeps the scrollbar honest with spacers for the rows it did not render', () => {
    renderWithQuery(<PageStrip pages={pages(400)} selected={null} onSelect={vi.fn()} />)
    const rendered = screen.getAllByTestId('strip-row').length
    const padTop = screen.getByTestId('strip-pad-top').style.height
    const padBottom = screen.getByTestId('strip-pad-bottom').style.height
    expect(padTop).toBe('0px')
    expect(padBottom).toBe(`${(400 - rendered) * ROW_HEIGHT}px`)
  })

  it('says so rather than rendering an empty box when there are no pages', () => {
    renderWithQuery(<PageStrip pages={[]} selected={null} onSelect={vi.fn()} />)
    expect(screen.getByTestId('page-strip-empty')).toBeTruthy()
  })
})

describe('scrolling to a cited page', () => {
  it('scrolls the selected row into view when it is rendered', () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView

    renderWithQuery(
      <PageStrip pages={pages(5)} selected="d@1#p004" onSelect={vi.fn()} />,
    )

    expect(scrollIntoView).toHaveBeenCalled()
    const selected = screen
      .getAllByTestId('strip-row')
      .find((row) => row.getAttribute('aria-current') === 'true')
    expect(selected?.getAttribute('data-page-id')).toBe('d@1#p004')
  })

  it('reaches a row outside the window by scrolling to where it will be, not into a missing node', () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView

    const { container } = renderWithQuery(
      <PageStrip pages={pages(400)} selected="d@1#p300" onSelect={vi.fn()} />,
    )

    const strip = container.querySelector('[data-testid="page-strip"]') as HTMLElement
    expect(strip.scrollTop).toBe(299 * ROW_HEIGHT)
    // The node was never in the DOM, so there was nothing to call it on — and calling it on the
    // wrong row would have scrolled somewhere plausible and wrong.
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('does nothing when the selected page is not in this strip at all', () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    renderWithQuery(<PageStrip pages={pages(5)} selected="other@1#p001" onSelect={vi.fn()} />)
    expect(scrollIntoView).not.toHaveBeenCalled()
  })
})
