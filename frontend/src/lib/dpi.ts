/**
 * The raster URL grammar and §7.3's dpi bounds, on the client side of them.
 *
 * The service refuses a bad request with a typed 400 naming its bound, and that is the contract —
 * this module does not soften it and does not clamp. What it does is **not issue** the request
 * that would be refused, which is a different thing and is what M7's acceptance asks for: a
 * region-less `dpi=400` is a request this app is structurally unable to make, so the escalated
 * viewer cannot show a caller an error it could have avoided.
 *
 * The one rule worth stating plainly: **above 220 dpi a region is required.** A full page at 400
 * dpi is over the megapixel bound, and an E-size drawing is over it at 220 — so escalation and
 * cropping are the same gesture, not two independent controls.
 */

/** `caps.ALLOWED_DPI`. A value outside it is `dpi_not_allowed`. */
export const ALLOWED_DPI = [36, 72, 150, 220, 300, 400] as const

export type Dpi = (typeof ALLOWED_DPI)[number]

/** `lookup.DPI_THUMB` — what a `thumb_url` is rendered at. */
export const DPI_THUMB = 72

/** `config.DPI_INDEX` — the dpi the index was built at, and `fetch`'s default. */
export const DPI_INDEX = 150

/** `config.DPI_ANSWER` — the raster `read` sees. Pinned; a caller cannot change it (F19). */
export const DPI_ANSWER = 220

/** Above this, `region` is mandatory (`dpi_requires_region`). */
export const DPI_REGION_REQUIRED_ABOVE = 220

/** The ladder the viewer offers: the page as indexed, as read, and two escalations. */
export const ZOOM_LADDER: readonly Dpi[] = [150, 220, 300, 400]

/** A normalised crop, `[x0, y0, x1, y1]` in 0..1 (D6). */
export type Region = [number, number, number, number]

export function isAllowedDpi(dpi: number): dpi is Dpi {
  return (ALLOWED_DPI as readonly number[]).includes(dpi)
}

export function requiresRegion(dpi: number): boolean {
  return dpi > DPI_REGION_REQUIRED_ABOVE
}

/** Normalised, `x0 < x1`, `y0 < y1` — `caps.validate_region`'s rule, checked before we send. */
export function isValidRegion(region: Region | null): region is Region {
  if (region === null) return false
  const [x0, y0, x1, y1] = region
  return (
    region.every((value) => Number.isFinite(value) && value >= 0 && value <= 1) &&
    x0 < x1 &&
    y0 < y1
  )
}

/** Why a raster request would be refused, in the service's own code, or `null` if it would not. */
export function rasterRefusal(dpi: number, region: Region | null): string | null {
  if (!isAllowedDpi(dpi)) return 'dpi_not_allowed'
  if (region !== null && !isValidRegion(region)) return 'region_invalid'
  if (requiresRegion(dpi) && region === null) return 'dpi_requires_region'
  return null
}

/** `raster_cache.region_query` — `'0,0,1,0.55'`, formatted as `%g` does. */
export function regionQuery(region: Region): string {
  return region.map((value) => String(Number(value.toPrecision(6)))).join(',')
}

/** `raster_cache.quoted_page_id` — everything encoded except `@`, so a citation stays readable. */
export function quotedPageId(pageId: string): string {
  return encodeURIComponent(pageId).replace(/%40/g, '@')
}

export class RasterRefused extends Error {
  readonly code: string

  constructor(code: string, detail: string) {
    super(detail)
    this.name = 'RasterRefused'
    this.code = code
  }
}

/**
 * `raster_cache.page_image_url`, client side — and it **throws instead of returning a URL** the
 * service would refuse. The throw is the acceptance criterion: a `dpi=400` with no region is a
 * request that is never issued, rather than one that comes back as a 400 the operator has to read.
 */
export function pageImageUrl(pageId: string, dpi: number = DPI_INDEX, region: Region | null = null): string {
  const refusal = rasterRefusal(dpi, region)
  if (refusal !== null) {
    throw new RasterRefused(
      refusal,
      refusal === 'dpi_requires_region'
        ? `dpi ${dpi} renders a full page above the megapixel bound; pass a region (§7.3)`
        : `${refusal}: dpi ${dpi}, region ${JSON.stringify(region)}`,
    )
  }
  const query = region === null ? `dpi=${dpi}` : `dpi=${dpi}&region=${regionQuery(region)}`
  return `/pages/${quotedPageId(pageId)}/image?${query}`
}
