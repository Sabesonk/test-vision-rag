/**
 * Windowing — §16 Frontend's *"lists > 50 items virtualized"*, as arithmetic.
 *
 * A binder here is a few dozen pages; `TC1E-SF` is 55 and a real service manual is hundreds. The
 * rule exists because a page strip renders a thumbnail per row, and a thumbnail is an
 * authenticated `GET` — an un-windowed strip of four hundred pages does not merely make a long
 * DOM, it asks the service for four hundred rasters the operator will never look at.
 *
 * Kept as a pure function over numbers, separately from the component that scrolls, for the
 * usual reason: the acceptance criterion is *"asserted on the rendered DOM node count"*, and a
 * number that a test can compute independently is what makes that assertion mean something.
 *
 * **Below the threshold nothing is windowed.** A short list renders whole — no padding
 * elements, no scroll maths, and `virtualized: false` so a test can tell the two regimes apart
 * rather than inferring the regime from the count it is trying to check.
 */

/** §16's threshold, exactly. A list of 50 renders whole; 51 windows. */
export const VIRTUALIZE_ABOVE = 50

/** The fixed row height the strip is laid out on, in px. Fixed, so the maths is not a measurement. */
export const ROW_HEIGHT = 88

/** Rows rendered beyond each edge of the viewport, so a fast scroll does not show a gap. */
export const OVERSCAN = 4

export interface Viewport {
  /** `scrollTop` of the scrolling container. */
  scrollTop: number
  /** Its `clientHeight`. Zero before layout, which the slice below handles rather than divides by. */
  height: number
  rowHeight?: number
  overscan?: number
}

export interface Slice {
  /** First rendered index, inclusive. */
  start: number
  /** Last rendered index, exclusive. */
  end: number
  /** Spacer height above the rendered rows, in px — what keeps the scrollbar honest. */
  padTop: number
  /** Spacer height below them. */
  padBottom: number
  /** False when the list was short enough to render whole. */
  virtualized: boolean
}

/**
 * Which rows to render for a list of `count` items scrolled to `viewport`.
 *
 * Clamped at both ends: a `scrollTop` past the end of the list (which a container reports for one
 * frame after the list shrinks) yields an empty-but-valid slice at the end rather than a
 * `start > end` that a component would render as nothing while the scrollbar says otherwise.
 */
export function sliceOf(count: number, viewport: Viewport): Slice {
  const rowHeight = viewport.rowHeight ?? ROW_HEIGHT
  const overscan = viewport.overscan ?? OVERSCAN

  if (count <= VIRTUALIZE_ABOVE) {
    return { start: 0, end: count, padTop: 0, padBottom: 0, virtualized: false }
  }

  const scrollTop = Math.max(0, viewport.scrollTop)
  // Before first layout a container reports `height: 0`. Rendering the overscan alone would show
  // an empty strip until a scroll event arrived, so an unmeasured viewport gets one screenful.
  const height = viewport.height > 0 ? viewport.height : rowHeight * 10

  const first = Math.floor(scrollTop / rowHeight)
  const visible = Math.ceil(height / rowHeight)

  const start = Math.max(0, Math.min(count - 1, first - overscan))
  const end = Math.max(start, Math.min(count, first + visible + overscan))

  return {
    start,
    end,
    padTop: start * rowHeight,
    padBottom: (count - end) * rowHeight,
    virtualized: true,
  }
}
