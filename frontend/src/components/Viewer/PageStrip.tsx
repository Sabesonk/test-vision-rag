/**
 * The pages in view, as a scrollable strip — and the thing a citation click scrolls.
 *
 * Two jobs, and they pull in opposite directions, which is why they are in one component.
 *
 * **Windowed.** §16 caps an un-virtualized list at 50 rows, and every row here is a thumbnail,
 * which is an authenticated `GET`. A 400-page binder rendered whole would not just make a long
 * DOM — it would ask the service for 400 rasters nobody is going to look at. The arithmetic is
 * `lib/window.ts`; the spacers above and below keep the scrollbar telling the truth about a list
 * whose rows mostly do not exist.
 *
 * **Scrollable to an arbitrary row.** Clicking a code in the draft has to reach *that* page
 * (§13 M7), and windowing means the row may not be in the DOM to scroll to. So the effect below
 * checks first: a row inside the window is scrolled into view, a row outside it is reached by
 * setting `scrollTop` to where that row will be — which renders it, and lands on it. Calling
 * `scrollIntoView` on a row that does not exist is the bug this ordering avoids.
 */
import { useEffect, useRef, useState } from 'react'

import { ROW_HEIGHT, sliceOf } from '../../lib/window.ts'
import { trustBadge } from '../../lib/badges.ts'
import type { StripPage } from '../../lib/strip.ts'
import { Badge } from '../Badge.tsx'
import { Thumb } from '../Thumb.tsx'

export type { StripPage }

export interface PageStripProps {
  pages: StripPage[]
  selected: string | null
  onSelect: (pageId: string) => void
}

export function PageStrip({ pages, selected, onSelect }: PageStripProps) {
  const container = useRef<HTMLDivElement>(null)
  const rows = useRef(new Map<string, HTMLButtonElement>())
  const [scrollTop, setScrollTop] = useState(0)
  const [height, setHeight] = useState(0)

  useEffect(() => {
    const element = container.current
    if (element !== null) setHeight(element.clientHeight)
  }, [pages.length])

  useEffect(() => {
    if (selected === null) return
    const index = pages.findIndex((page) => page.pageId === selected)
    if (index < 0) return
    const element = container.current
    if (element === null) return

    const current = sliceOf(pages.length, {
      scrollTop: element.scrollTop,
      height: element.clientHeight,
    })
    if (index < current.start || index >= current.end) {
      const top = Math.max(0, index * ROW_HEIGHT)
      element.scrollTop = top
      setScrollTop(top)
      return
    }
    rows.current.get(selected)?.scrollIntoView({ block: 'nearest' })
  }, [selected, pages])

  const slice = sliceOf(pages.length, { scrollTop, height })
  const visible = pages.slice(slice.start, slice.end)

  if (pages.length === 0) {
    return (
      <p className="empty" data-testid="page-strip-empty">
        No pages in view.
      </p>
    )
  }

  return (
    <div
      className="strip"
      ref={container}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
      data-testid="page-strip"
      data-count={pages.length}
      data-virtualized={slice.virtualized}
    >
      <div style={{ height: slice.padTop }} data-testid="strip-pad-top" />
      {visible.map((page) => (
        <button
          type="button"
          key={page.pageId}
          className="strip-row"
          style={{ height: ROW_HEIGHT }}
          data-testid="strip-row"
          data-page-id={page.pageId}
          aria-current={page.pageId === selected}
          onClick={() => onSelect(page.pageId)}
          ref={(element) => {
            if (element === null) rows.current.delete(page.pageId)
            else rows.current.set(page.pageId, element)
          }}
        >
          <Thumb url={page.thumbUrl} alt={`thumbnail of ${page.label || page.pageId}`} />
          <span className="card-body">
            <span className="card-title mono">{page.label || page.pageId}</span>
            <span className="card-meta">{page.note}</span>
          </span>
          {page.trust !== null ? <Badge spec={trustBadge(page.trust)} /> : null}
        </button>
      ))}
      <div style={{ height: slice.padBottom }} data-testid="strip-pad-bottom" />
    </div>
  )
}
