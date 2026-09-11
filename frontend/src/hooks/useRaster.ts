/**
 * An authenticated raster, as something `<img src>` can use.
 *
 * The whole hook exists because of one line in §16: *"rasters are never returned without auth"*.
 * An `<img src="/pages/…/image">` sends no `Authorization` header, so the browser's own image
 * loader cannot fetch one. The two ways out are a token in the query string — which lands in
 * every access log, every referrer and every screenshot — and this: `fetch` with the header,
 * then an object URL over the bytes. The second one costs a hook and leaks nothing.
 *
 * **Who owns the URL.** React Query owns the `Blob` (so two components showing the same page
 * share one download, and a revisit is instant); this effect owns the `URL`, and revokes it when
 * the blob changes or the component unmounts. Neither half can outlive the other.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { ApiError, rasterBlob } from '../api/client.ts'

export interface Raster {
  /** An object URL, or `null` while loading, on error, or when there is nothing to show. */
  src: string | null
  loading: boolean
  error: ApiError | null
}

/** `url` is a relative path from `lib/dpi.ts::pageImageUrl`, or `null` to show nothing. */
export function useRaster(url: string | null): Raster {
  const query = useQuery({
    queryKey: ['raster', url],
    queryFn: () => rasterBlob(url as string),
    enabled: url !== null,
    // A page raster at a given dpi and region is immutable: the render is deterministic and the
    // service treats it as a cache, not a source of truth. Refetching it on a window focus would
    // re-render a PDF page on the server to get the same bytes back.
    staleTime: Infinity,
    retry: false,
  })

  const [src, setSrc] = useState<string | null>(null)
  const blob = query.data ?? null

  useEffect(() => {
    if (blob === null) {
      setSrc(null)
      return
    }
    const objectUrl = URL.createObjectURL(blob)
    setSrc(objectUrl)
    return () => {
      URL.revokeObjectURL(objectUrl)
      setSrc(null)
    }
  }, [blob])

  return {
    src,
    loading: query.isFetching,
    error: query.error instanceof ApiError ? query.error : null,
  }
}
