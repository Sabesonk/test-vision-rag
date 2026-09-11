/**
 * A row in the page strip, and the two things that can produce one: a skim hit, and an answer.
 *
 * Pure, and separate from the component that scrolls, because the interesting half is what may
 * be said about a page and what may not.
 *
 * **A skim hit knows its own trust.** `text_trust` is on the row, so the strip can badge it.
 *
 * **An answer's cited page does not.** `AskResponse` carries page *ids* in `citations` and
 * `claims`, and no `text_trust` for them — so `trust` is `null` and no badge is drawn. That is
 * deliberate and it is the harder of the two choices: the tempting move is to infer *"this claim
 * came back `unverifiable`, so the page must have no text layer"*, which is very often true and
 * is still an invention. `unverifiable` has three causes (§5.7: no text layer, an untrusted
 * extraction, or a page that is not current) and the console was told which one by nobody. A
 * missing badge says *"not known here"*; a guessed one would say *"scan"* about a page that may
 * simply be superseded.
 *
 * What *is* known about a cited page is what the gate did to it, and that goes in the note.
 */
import type { Answer, PageHit, TextTrust } from '../api/types.ts'
import { DPI_INDEX, DPI_THUMB, pageImageUrl } from './dpi.ts'
import { citedPages } from './citations.ts'

export interface StripPage {
  pageId: string
  /** The printed label where one is known — never a sequence number dressed up as one (§6.4). */
  label: string
  thumbUrl: string | null
  /**
   * The row's **own** `image.url`, dereferenced as sent (D12) — not a URL this app rebuilt.
   *
   * The viewer uses it verbatim at the index dpi, and only constructs one when the operator
   * escalates, because at 300 or 400 with a crop there is no URL in the payload to use. Keeping
   * the payload's string for the common case is what makes `image.url` a contract rather than a
   * suggestion: if the service's grammar changes, the console follows it without being edited.
   */
  imageUrl: string | null
  /** `null` where the payload did not say. Not a guess, and not `ok` by default. */
  trust: TextTrust | null
  /** One line of why this page is in the strip. */
  note: string
}

/** A `skim_pages` hit → a row. `why` is the row's own account of which surfaces found it. */
export function stripPageOf(hit: PageHit): StripPage {
  return {
    pageId: hit.page_id,
    label: hit.printed_page_no || hit.page_id,
    thumbUrl: hit.image?.thumb_url ?? null,
    imageUrl: hit.image?.url ?? null,
    trust: hit.text_trust,
    note: [hit.why.join(' + '), hit.page_kind, ...hit.flags].filter(Boolean).join(' · '),
  }
}

/**
 * The pages an answer cites, in look order — the strip a citation click scrolls through.
 *
 * The thumbnail URL is built rather than read, because `AskResponse` carries no `ImageRef`: the
 * runner's body is a trace and a draft, not a search result. `pageImageUrl` is the same grammar
 * the service itself emits (`raster_cache.page_image_url`), at the same `DPI_THUMB` a
 * `thumb_url` is rendered at, so the browser's cache and the service's raster cache both see
 * the request a skim row would have produced.
 */
export function evidencePages(answer: Answer | null): StripPage[] {
  if (answer === null) return []
  return citedPages(answer).map((pageId) => {
    const claims = answer.claims.filter((claim) => claim.page_id === pageId)
    const note = claims.length
      ? claims.map((claim) => `${claim.code}: ${claim.badge}`).join(' · ')
      : 'cited, no code declared on this page'
    return {
      pageId,
      label: pageId,
      thumbUrl: pageImageUrl(pageId, DPI_THUMB),
      imageUrl: pageImageUrl(pageId, DPI_INDEX),
      trust: null,
      note,
    }
  })
}
