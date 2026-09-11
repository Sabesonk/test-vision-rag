/**
 * A thumbnail, from the `thumb_url` the payload already carries.
 *
 * This is the component M7's acceptance is about: *"binder and chapter cards render thumbnails
 * from `preview.thumb_url` with no additional endpoint call beyond the image `GET`"*. So it takes
 * a URL string that came off a skim row and dereferences exactly that — no `fetch` tool call to
 * turn a `page_id` into an image, no second round trip to discover a dpi. The row said where the
 * picture is; D12's whole point is that the row is enough.
 *
 * It still goes through `useRaster`, because a thumbnail is a raster and §16 does not exempt
 * small ones from authentication.
 */
import { useRaster } from '../hooks/useRaster.ts'

export interface ThumbProps {
  url: string | null
  alt: string
}

export function Thumb({ url, alt }: ThumbProps) {
  const raster = useRaster(url)

  if (raster.src === null) {
    return (
      <div className="thumb thumb-placeholder" data-testid="thumb-placeholder" aria-hidden="true">
        {raster.error !== null ? raster.error.code : raster.loading ? '…' : 'no image'}
      </div>
    )
  }
  return <img className="thumb" src={raster.src} alt={alt} data-testid="thumb" />
}
