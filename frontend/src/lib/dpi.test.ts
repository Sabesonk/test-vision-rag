/**
 * The raster URL grammar and §7.3's bounds, client side.
 *
 * The URL assertions are a contract test in miniature: the strings below are the ones
 * `backend/vsir/serve/raster_cache.py` produces, including §7.2.5's worked example. If the
 * service's grammar changes, this app dereferences a URL that 404s, and this is where that is
 * noticed.
 */
import { describe, expect, it } from 'vitest'

import {
  ALLOWED_DPI,
  DPI_ANSWER,
  DPI_INDEX,
  DPI_THUMB,
  RasterRefused,
  type Region,
  isValidRegion,
  pageImageUrl,
  quotedPageId,
  rasterRefusal,
  regionQuery,
  requiresRegion,
} from './dpi.ts'

describe('the URL grammar', () => {
  it('encodes the `#` and leaves the `@` alone — §7.2.5’s worked example, exactly', () => {
    expect(quotedPageId('TC1E-SF@1.3#p001')).toBe('TC1E-SF@1.3%23p001')
    expect(pageImageUrl('TC1E-SF@1.3#p001')).toBe('/pages/TC1E-SF@1.3%23p001/image?dpi=150')
  })

  it('is relative, so the browser resolves it against the origin that served the row', () => {
    expect(pageImageUrl('d@1#p002').startsWith('/pages/')).toBe(true)
  })

  it('formats a region as `%g` does, so `0` is not `0.0`', () => {
    expect(regionQuery([0, 0, 1, 0.55])).toBe('0,0,1,0.55')
    expect(pageImageUrl('d@1#p001', 300, [0, 0, 1, 0.55])).toBe(
      '/pages/d@1%23p001/image?dpi=300&region=0,0,1,0.55',
    )
  })
})

describe('§7.3’s bounds', () => {
  it('defaults to the dpi the index was built at', () => {
    expect(DPI_INDEX).toBe(150)
    expect(DPI_ANSWER).toBe(220)
    expect(DPI_THUMB).toBe(72)
    expect(ALLOWED_DPI).toContain(DPI_THUMB)
  })

  it('requires a region above 220 and not at or below it', () => {
    expect(requiresRegion(220)).toBe(false)
    expect(requiresRegion(300)).toBe(true)
    expect(requiresRegion(400)).toBe(true)
  })

  it('refuses to build a region-less URL above 220 — the request is never issued', () => {
    expect(() => pageImageUrl('d@1#p001', 400)).toThrow(RasterRefused)
    try {
      pageImageUrl('d@1#p001', 400)
    } catch (error) {
      expect((error as RasterRefused).code).toBe('dpi_requires_region')
    }
  })

  it('builds the same request happily once a region is given', () => {
    expect(pageImageUrl('d@1#p001', 400, [0.5, 0, 1, 0.5])).toContain('dpi=400&region=0.5,0,1,0.5')
  })

  it('names the bound rather than clamping to it', () => {
    expect(rasterRefusal(199, null)).toBe('dpi_not_allowed')
    expect(rasterRefusal(400, null)).toBe('dpi_requires_region')
    expect(rasterRefusal(150, [1, 0, 0, 1])).toBe('region_invalid')
    expect(rasterRefusal(150, null)).toBeNull()
  })
})

describe('isValidRegion', () => {
  const cases: [string, Region | null, boolean][] = [
    ['a normalised box', [0, 0, 1, 1], true],
    ['a zero-area click', [0.5, 0.5, 0.5, 0.5], false],
    ['inverted on x', [0.8, 0, 0.2, 1], false],
    ['inverted on y', [0, 0.8, 1, 0.2], false],
    ['outside 0..1', [0, 0, 1.2, 1], false],
    ['nothing at all', null, false],
  ]
  it.each(cases)('%s → %s', (_name, region, expected) => {
    expect(isValidRegion(region)).toBe(expected)
  })
})
