/**
 * The windowing arithmetic — §16's *"lists > 50 items virtualized"*.
 *
 * The threshold is tested on both sides of itself because "more than 50" is exactly the kind of
 * boundary that ships off by one, and the consequence here is not cosmetic: a strip renders an
 * authenticated raster per row.
 */
import { describe, expect, it } from 'vitest'

import { OVERSCAN, ROW_HEIGHT, VIRTUALIZE_ABOVE, sliceOf } from './window.ts'

const viewport = { scrollTop: 0, height: ROW_HEIGHT * 10 }

describe('the threshold', () => {
  it('renders a list of exactly 50 whole, with no spacers', () => {
    const slice = sliceOf(VIRTUALIZE_ABOVE, viewport)
    expect(slice).toEqual({ start: 0, end: 50, padTop: 0, padBottom: 0, virtualized: false })
  })

  it('windows at 51', () => {
    const slice = sliceOf(VIRTUALIZE_ABOVE + 1, viewport)
    expect(slice.virtualized).toBe(true)
    expect(slice.end - slice.start).toBeLessThan(VIRTUALIZE_ABOVE + 1)
  })

  it('renders a handful of rows out of a 400-page binder', () => {
    const slice = sliceOf(400, viewport)
    expect(slice.end - slice.start).toBeLessThanOrEqual(10 + 2 * OVERSCAN)
  })
})

describe('the spacers', () => {
  it('always account for exactly the rows that are not rendered', () => {
    const count = 400
    const slice = sliceOf(count, { scrollTop: ROW_HEIGHT * 100, height: ROW_HEIGHT * 10 })
    expect(slice.padTop).toBe(slice.start * ROW_HEIGHT)
    expect(slice.padBottom).toBe((count - slice.end) * ROW_HEIGHT)
    expect(slice.padTop + (slice.end - slice.start) * ROW_HEIGHT + slice.padBottom).toBe(
      count * ROW_HEIGHT,
    )
  })

  it('overscans above the fold rather than starting exactly at the scroll position', () => {
    const slice = sliceOf(400, { scrollTop: ROW_HEIGHT * 100, height: ROW_HEIGHT * 10 })
    expect(slice.start).toBe(100 - OVERSCAN)
  })
})

describe('the awkward inputs', () => {
  it('renders a screenful before the container has been measured', () => {
    const slice = sliceOf(400, { scrollTop: 0, height: 0 })
    expect(slice.end).toBeGreaterThan(slice.start)
  })

  it('clamps a scroll position past the end of the list to a valid slice', () => {
    const slice = sliceOf(60, { scrollTop: ROW_HEIGHT * 10_000, height: ROW_HEIGHT * 10 })
    expect(slice.start).toBeLessThanOrEqual(slice.end)
    expect(slice.end).toBeLessThanOrEqual(60)
    expect(slice.padBottom).toBeGreaterThanOrEqual(0)
  })

  it('clamps a negative scroll position — a rubber-banding container reports one', () => {
    const slice = sliceOf(400, { scrollTop: -500, height: ROW_HEIGHT * 10 })
    expect(slice.start).toBe(0)
    expect(slice.padTop).toBe(0)
  })

  it('handles an empty list', () => {
    expect(sliceOf(0, viewport)).toEqual({
      start: 0,
      end: 0,
      padTop: 0,
      padBottom: 0,
      virtualized: false,
    })
  })
})
