/**
 * The page, at a chosen dpi, optionally cropped — and §7.3's bounds enforced by **not asking**.
 *
 * The service refuses `dpi=400` without a `region` with a typed 400 naming the bound, and that
 * refusal is correct. It is also an error the operator should never have to read, because the
 * console knows the rule before it sends anything: `rasterRefusal` returns a reason, the URL is
 * `null`, `useRaster` is disabled, and **no request is issued**. M7's acceptance is worded that
 * way on purpose — *"a request without one is not issued"* — and this is where that holds.
 *
 * Escalating and cropping are therefore one gesture, not two controls that can disagree. Picking
 * 300 or 400 with no crop selected does not fail; it asks for the crop first.
 *
 * A region is normalised `[x0, y0, x1, y1]` in 0..1 (D6), which is what makes it dpi-independent:
 * the same crop means the same part of the page whether it is rendered at 150 or at 400, so
 * escalating an existing selection re-renders the same corner rather than a different one.
 */
import { useRef, useState } from 'react'

import {
  DPI_INDEX,
  type Region,
  ZOOM_LADDER,
  isValidRegion,
  pageImageUrl,
  rasterRefusal,
  regionQuery,
  requiresRegion,
} from '../../lib/dpi.ts'
import { useRaster } from '../../hooks/useRaster.ts'
import { Banner } from '../Banner.tsx'

export interface PageImageProps {
  pageId: string
  /**
   * The row's own `image.url`, when this page came from a search result.
   *
   * Used verbatim while nothing is escalated, so the console dereferences the reference D12 put
   * on the row rather than rebuilding it from a grammar it has copied. `null` for a page reached
   * by a citation, where the runner's body carries no `ImageRef` and there is nothing to follow.
   */
  baseUrl: string | null
  dpi: number
  region: Region | null
  onDpi: (dpi: number) => void
  onRegion: (region: Region | null) => void
}

/** A drag in progress, in normalised page coordinates. */
interface Drag {
  x0: number
  y0: number
  x1: number
  y1: number
}

function normalise(drag: Drag): Region {
  return [
    Math.min(drag.x0, drag.x1),
    Math.min(drag.y0, drag.y1),
    Math.max(drag.x0, drag.x1),
    Math.max(drag.y0, drag.y1),
  ]
}

export function PageImage({ pageId, baseUrl, dpi, region, onDpi, onRegion }: PageImageProps) {
  const canvas = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<Drag | null>(null)

  const refusal = rasterRefusal(dpi, region)
  const unescalated = dpi === DPI_INDEX && region === null
  const url =
    refusal !== null ? null : unescalated && baseUrl !== null ? baseUrl : pageImageUrl(pageId, dpi, region)
  const raster = useRaster(url)

  function pointAt(event: React.PointerEvent): { x: number; y: number } | null {
    const box = canvas.current?.getBoundingClientRect()
    if (!box || box.width === 0 || box.height === 0) return null
    return {
      x: Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
      y: Math.min(1, Math.max(0, (event.clientY - box.top) / box.height)),
    }
  }

  function onPointerDown(event: React.PointerEvent) {
    const point = pointAt(event)
    if (point === null) return
    setDrag({ x0: point.x, y0: point.y, x1: point.x, y1: point.y })
  }

  function onPointerMove(event: React.PointerEvent) {
    if (drag === null) return
    const point = pointAt(event)
    if (point === null) return
    setDrag({ ...drag, x1: point.x, y1: point.y })
  }

  function onPointerUp() {
    if (drag === null) return
    const selected = normalise(drag)
    setDrag(null)
    // A click rather than a drag selects nothing: a zero-area region is `region_invalid`, and
    // reading it as "the operator wants the whole page" would silently undo a crop they still
    // need at this dpi.
    onRegion(isValidRegion(selected) ? selected : null)
  }

  return (
    <div className="viewer" data-testid="page-viewer" data-page-id={pageId}>
      <div className="viewer-controls">
        <span className="muted">dpi</span>
        {ZOOM_LADDER.map((step) => (
          <button
            key={step}
            type="button"
            aria-pressed={step === dpi}
            data-testid={`dpi-${step}`}
            onClick={() => onDpi(step)}
            title={
              requiresRegion(step)
                ? `${step} dpi renders a crop only — a full page at this dpi is over the 12 MP bound (§7.3)`
                : `the page at ${step} dpi`
            }
          >
            {step}
            {requiresRegion(step) ? ' ✂' : ''}
          </button>
        ))}
        <button
          type="button"
          disabled={region === null}
          data-testid="clear-region"
          onClick={() => onRegion(null)}
        >
          clear crop
        </button>
        <span className="viewer-meta" data-testid="viewer-meta">
          {region === null ? 'full page' : `region ${regionQuery(region)}`}
        </span>
      </div>

      {refusal !== null ? (
        <div className="banner" data-tone="warn" role="note" data-testid="needs-region">
          <div>
            <code>{refusal}</code> — drag a box on the page to choose a crop. Above 220 dpi a full
            page is over the megapixel bound, so the service renders a region only (§7.3).
          </div>
          <div className="region-hint">No request was sent.</div>
        </div>
      ) : null}

      <Banner error={raster.error} />

      <div
        className="viewer-canvas"
        ref={canvas}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        data-testid="viewer-canvas"
      >
        {raster.src !== null ? (
          <img src={raster.src} alt={`page ${pageId} at ${dpi} dpi`} data-testid="page-raster" draggable={false} />
        ) : (
          <span className="empty" data-testid="viewer-empty">
            {refusal !== null ? 'waiting for a crop' : raster.loading ? 'rendering…' : 'no raster'}
          </span>
        )}
      </div>

      <div className="region-hint">
        Drag across the page to crop it; the crop is normalised, so it survives a change of dpi.
      </div>
    </div>
  )
}
