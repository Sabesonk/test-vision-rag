/**
 * The escalated viewer, and the request it refuses to make.
 *
 * M7's acceptance is worded as a negative — *"requesting a region at `dpi=400` includes a
 * `region` parameter (a request without one is not issued)"* — so the assertions are about the
 * network stub. The service would refuse a region-less 400 with a typed 400 naming its bound,
 * and that refusal is correct; it is also an error the operator should never have to read,
 * because the console knows the rule before it sends anything.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'

import { PageImage } from './PageImage.tsx'
import { renderWithQuery } from '../../test/harness.tsx'

let urls: string[] = []

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
        json: async () => ({}),
        blob: async () => new Blob(['png']),
      } as unknown as Response)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  cleanup()
})

const draw = (
  dpi: number,
  region: [number, number, number, number] | null,
  onDpi = vi.fn(),
  baseUrl: string | null = null,
) => {
  renderWithQuery(
    <PageImage
      pageId="d@1#p001"
      baseUrl={baseUrl}
      dpi={dpi}
      region={region}
      onDpi={onDpi}
      onRegion={vi.fn()}
    />,
  )
  return onDpi
}

describe('within the bounds', () => {
  it('requests the page at the index dpi', async () => {
    draw(150, null)
    await waitFor(() => expect(urls).toEqual(['/pages/d@1%23p001/image?dpi=150']))
  })

  it('dereferences the row’s own `image.url` verbatim when nothing is escalated (D12)', async () => {
    draw(150, null, vi.fn(), '/pages/d@1%23p001/image?dpi=150&served=by-the-row')
    await waitFor(() =>
      expect(urls).toEqual(['/pages/d@1%23p001/image?dpi=150&served=by-the-row']),
    )
  })

  it('builds its own URL once escalated — the payload has none for a crop', async () => {
    draw(300, [0, 0, 0.5, 0.5], vi.fn(), '/pages/d@1%23p001/image?dpi=150&served=by-the-row')
    await waitFor(() =>
      expect(urls).toEqual(['/pages/d@1%23p001/image?dpi=300&region=0,0,0.5,0.5']),
    )
  })

  it('requests a crop at 400 when one is selected', async () => {
    draw(400, [0, 0, 1, 0.5])
    await waitFor(() =>
      expect(urls).toEqual(['/pages/d@1%23p001/image?dpi=400&region=0,0,1,0.5']),
    )
  })
})

describe('above 220 with no crop', () => {
  it('issues no request at all', async () => {
    draw(400, null)
    await waitFor(() => expect(screen.getByTestId('needs-region')).toBeTruthy())
    expect(urls).toEqual([])
  })

  it('names the bound the service would have named, rather than showing an error', async () => {
    draw(400, null)
    await waitFor(() =>
      expect(screen.getByTestId('needs-region').textContent).toContain('dpi_requires_region'),
    )
    expect(screen.queryByTestId('error-banner')).toBeNull()
  })

  it('does not clamp to 220 — the operator keeps the dpi they chose', async () => {
    draw(400, null)
    await waitFor(() => expect(screen.getByTestId('dpi-400').getAttribute('aria-pressed')).toBe('true'))
  })
})

describe('the ladder', () => {
  it('offers the four rungs of §7.3', () => {
    draw(150, null)
    for (const dpi of [150, 220, 300, 400]) {
      expect(screen.getByTestId(`dpi-${dpi}`)).toBeTruthy()
    }
  })

  it('reports a change of dpi rather than fetching behind the caller’s back', () => {
    const onDpi = draw(150, null)
    fireEvent.click(screen.getByTestId('dpi-300'))
    expect(onDpi).toHaveBeenCalledWith(300)
  })
})
