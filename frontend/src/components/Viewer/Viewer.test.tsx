/**
 * The ladder's card rungs, and the one network property M7 asserts about them.
 *
 * *"Binder and chapter cards render thumbnails from `preview.thumb_url` with no additional
 * endpoint call beyond the image `GET`"* — so the assertion counts requests, not pixels. The
 * failure this guards against is a console that receives a `preview` and then calls `fetch` to
 * turn the `page_id` into a picture, which is the whole reason D12 puts a dereferenceable
 * reference on the row instead of a bare id.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen, waitFor } from '@testing-library/react'

import { Viewer } from './Viewer.tsx'
import { TOP, toBinder } from '../../lib/ladder.ts'
import { renderWithQuery } from '../../test/harness.tsx'

let urls: string[] = []
let body: unknown = {}

beforeEach(() => {
  urls = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      urls.push(url)
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: 'ok',
        json: async () => body,
        blob: async () => new Blob(['png']),
      } as unknown as Response)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  cleanup()
})

const envelope = (hits: unknown[]) => ({
  status: 'ok',
  hits,
  unverified_hits: [],
  total: hits.length,
  capped: false,
  weak: false,
  needs_scope: false,
  next: null,
  effective_scope: {},
  scope_stats: { pages: 1, pages_no_text: 0, docs: [] },
  reads_remaining: 3,
  provenance: { run_id: 'r1', release_id: 'rel', schema_version: 1 },
})

describe('binder cards', () => {
  it('renders the thumbnail from `preview.thumb_url`, and asks for nothing else', async () => {
    body = envelope([
      {
        doc_id: 'TC1E-SF@1.3',
        title: 'Service manual',
        doc_type: 'manual',
        pages_matched: 4,
        best_rank: 1,
        searchable_ratio: 1,
        summary: 'the safety list',
        preview: { page_id: 'TC1E-SF@1.3#p001', thumb_url: '/pages/TC1E-SF@1.3%23p001/image?dpi=72' },
        next: null,
      },
    ])

    renderWithQuery(<Viewer query="fuse" draftQuestion="fuse" ladder={TOP} onLadder={vi.fn()} evidence={[]} onReadOff={vi.fn()} pending={false} />)

    await waitFor(() => expect(screen.getByTestId('binder-card')).toBeTruthy())
    await waitFor(() => expect(urls).toHaveLength(2))

    expect(urls[0]).toBe('/tools/skim_documents')
    expect(urls[1]).toBe('/pages/TC1E-SF@1.3%23p001/image?dpi=72')
  })

  it('says a fully scanned binder is not searchable rather than showing it as ordinary', async () => {
    body = envelope([
      {
        doc_id: 'scan@1',
        title: 'A scanned binder',
        doc_type: 'manual',
        pages_matched: 0,
        best_rank: 0,
        searchable_ratio: 0,
        summary: '',
        preview: null,
        next: null,
      },
    ])

    renderWithQuery(<Viewer query="fuse" draftQuestion="fuse" ladder={TOP} onLadder={vi.fn()} evidence={[]} onReadOff={vi.fn()} pending={false} />)

    await waitFor(() => expect(screen.getByTestId('searchable-ratio')).toBeTruthy())
    expect(screen.getByTestId('status-not-searchable')).toBeTruthy()
    // F4: `not_searchable` must not read as `not_found`. It published; it is simply not text.
    expect(screen.queryByTestId('status-not-found')).toBeNull()
  })
})

describe('chapter cards', () => {
  it('uses the section row’s own preview too', async () => {
    body = envelope([
      {
        section_id: 'sec-4',
        title: 'Safety',
        page_range: [40, 52],
        pages_matched: 2,
        best_rank: 1,
        preview: { page_id: 'TC1E-SF@1.3#p040', thumb_url: '/pages/TC1E-SF@1.3%23p040/image?dpi=72' },
        next: null,
      },
    ])

    renderWithQuery(
      <Viewer
        query="fuse"
        draftQuestion="fuse"
        ladder={toBinder(TOP, 'TC1E-SF@1.3', 'Service manual')}
        onLadder={vi.fn()}
        evidence={[]}
        onReadOff={vi.fn()}
        pending={false}
      />,
    )

    await waitFor(() => expect(screen.getByTestId('chapter-card')).toBeTruthy())
    await waitFor(() => expect(urls).toContain('/pages/TC1E-SF@1.3%23p040/image?dpi=72'))
    expect(urls.filter((url) => url.startsWith('/tools/'))).toEqual(['/tools/skim_sections'])
  })
})

describe('the breadcrumb trail', () => {
  it('marks the rung the reader is standing on', async () => {
    body = envelope([])
    renderWithQuery(
      <Viewer
        query="fuse"
        draftQuestion="fuse"
        ladder={toBinder(TOP, 'TC1E-SF@1.3', 'Service manual')}
        onLadder={vi.fn()}
        evidence={[]}
        onReadOff={vi.fn()}
        pending={false}
      />,
    )
    expect(screen.getByTestId('breadcrumbs').getAttribute('data-rung')).toBe('binder')
    expect(screen.getByTestId('crumb-binder').getAttribute('aria-current')).toBe('step')
    expect(screen.getByTestId('crumb-corpus').hasAttribute('disabled')).toBe(false)
  })
})
