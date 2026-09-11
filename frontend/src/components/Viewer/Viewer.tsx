/**
 * The left zone: the ladder, and whatever rung it is standing on.
 *
 * `corpus → binder → chapter` are card grids; `page` is the raster. The **strip** below the
 * raster is whichever set of pages the reader is actually looking at, and that is decided by one
 * rule rather than a mode switch: if the selected page is one the answer cited, the strip is the
 * answer's evidence; otherwise it is the skim's rows. So clicking a code lands the reader among
 * the pages the answer was written from, and climbing a crumb puts them back in the corpus —
 * without a toggle that could disagree with the breadcrumbs about where they are.
 *
 * Every thumbnail on this side comes from a `thumb_url` that was already in the row (D12). The
 * console never calls `fetch` to obtain a picture, and never asks for `inline=true` — the
 * reference is the payload's contribution and the `GET` is the browser's.
 */
import { useMemo } from 'react'

import type { DocHit, SectionHit } from '../../api/types.ts'
import { statusBadge } from '../../lib/badges.ts'
import {
  type Ladder,
  type Rung,
  climbTo,
  rungOf,
  toBinder,
  toChapter,
  toPage,
} from '../../lib/ladder.ts'
import { useBinders, useChapters, usePages } from '../../hooks/useSkim.ts'
import { ApiError } from '../../api/client.ts'
import { Badge } from '../Badge.tsx'
import { Banner } from '../Banner.tsx'
import { Thumb } from '../Thumb.tsx'
import { Breadcrumbs } from './Breadcrumbs.tsx'
import { PageImage } from './PageImage.tsx'
import { ReadOff } from './ReadOff.tsx'
import { type StripPage, stripPageOf } from '../../lib/strip.ts'
import { PageStrip } from './PageStrip.tsx'

export interface ViewerProps {
  /** The narrowing query the ladder skims with — the operator's question, **as asked**. */
  query: string
  /**
   * The question as currently *typed*, which is what a draft answers.
   *
   * Two fields rather than one because they are two different moments. The skims above re-run
   * when a question is **asked**, or every keystroke would spend a rung; a draft is written
   * about the page on screen and answers the question the operator has in front of them, which
   * may be one they have not pressed *ask* on — and on an image-only page they never will,
   * because there is nothing there for a text search to find.
   */
  draftQuestion: string
  ladder: Ladder
  onLadder: (ladder: Ladder) => void
  /** The pages the current answer cites. Empty when there is no answer yet. */
  evidence: StripPage[]
  /** §8.1a's `fetch` route: what the operator reads off the page on screen, sent to the gate. */
  onReadOff: (pageId: string, text: string) => void
  /** An `/ask` already in flight — the same mutation both routes go through. */
  pending: boolean
}

function asError(error: unknown): ApiError | null {
  return error instanceof ApiError ? error : null
}

export function Viewer({
  query,
  draftQuestion,
  ladder,
  onLadder,
  evidence,
  onReadOff,
  pending,
}: ViewerProps) {
  const rung = rungOf(ladder)
  // Hoisted so the `page` rung's callbacks close over a `string` rather than a cast: TypeScript
  // cannot carry the `!== null` narrowing of a field into a callback, and `as string` would be
  // an assertion where a binding does the job.
  const pageId = ladder.pageId

  const binders = useBinders(query, rung === 'corpus')
  const chapters = useChapters(query, rung === 'binder' ? ladder.docId : null)
  const pages = usePages(query, rung === 'chapter' || rung === 'page' ? ladder.docId : null, ladder.sectionId)

  const skimmed = useMemo(
    () => (pages.data?.hits ?? []).map(stripPageOf),
    [pages.data],
  )

  // The one rule that decides which strip is on screen — see the module note.
  const showingEvidence =
    ladder.pageId !== null && evidence.some((page) => page.pageId === ladder.pageId)
  const strip = showingEvidence ? evidence : skimmed

  function climb(rung: Rung) {
    onLadder(climbTo(ladder, rung))
  }

  function selectPage(pageId: string) {
    const row = strip.find((page) => page.pageId === pageId)
    onLadder(toPage(ladder, pageId, row?.label ?? ''))
  }

  return (
    <section className="zone-left" aria-label="page viewer">
      <Breadcrumbs ladder={ladder} onClimb={climb} />

      <div className="rung" data-testid="rung" data-rung={rung}>
        {rung === 'corpus' ? (
          <BinderCards
            hits={binders.data?.hits ?? []}
            error={asError(binders.error)}
            loading={binders.isFetching}
            status={binders.data?.status ?? null}
            onOpen={(hit) => onLadder(toBinder(ladder, hit.doc_id, hit.title || hit.doc_id))}
          />
        ) : null}

        {rung === 'binder' ? (
          <ChapterCards
            hits={chapters.data?.hits ?? []}
            error={asError(chapters.error)}
            loading={chapters.isFetching}
            status={chapters.data?.status ?? null}
            onOpen={(hit) => onLadder(toChapter(ladder, hit.section_id, hit.title || hit.section_id))}
          />
        ) : null}

        {rung === 'page' && pageId !== null ? (
          <PageImage
            pageId={pageId}
            baseUrl={strip.find((page) => page.pageId === ladder.pageId)?.imageUrl ?? null}
            dpi={ladder.dpi}
            region={ladder.region}
            onDpi={(dpi) => onLadder({ ...ladder, dpi: dpi as Ladder['dpi'] })}
            onRegion={(region) => onLadder({ ...ladder, region })}
          />
        ) : null}

        {rung === 'page' && pageId !== null ? (
          <ReadOff
            pageId={pageId}
            question={draftQuestion}
            pending={pending}
            onSubmit={(text) => onReadOff(pageId, text)}
          />
        ) : null}

        {rung === 'chapter' || rung === 'page' ? (
          <>
            <Banner error={asError(pages.error)} />
            <h2 className="panel-head" data-testid="strip-head">
              {showingEvidence ? 'pages this answer cites' : 'pages'}
              {pages.data !== undefined && !showingEvidence ? (
                <Badge spec={statusBadge(pages.data.status)} />
              ) : null}
            </h2>
            <PageStrip pages={strip} selected={ladder.pageId} onSelect={selectPage} />
          </>
        ) : null}
      </div>
    </section>
  )
}

interface CardsProps<H> {
  hits: H[]
  error: ApiError | null
  loading: boolean
  status: string | null
  onOpen: (hit: H) => void
}

function BinderCards({ hits, error, loading, status, onOpen }: CardsProps<DocHit>) {
  return (
    <>
      <Banner error={error} />
      <Empty hits={hits.length} loading={loading} status={status} what="binders" />
      <div className="cards" data-testid="binder-cards">
        {hits.map((hit) => (
          <button
            type="button"
            key={hit.doc_id}
            className="card"
            data-testid="binder-card"
            data-doc-id={hit.doc_id}
            onClick={() => onOpen(hit)}
          >
            <Thumb url={hit.preview?.thumb_url ?? null} alt={`first page of ${hit.title}`} />
            <span className="card-body">
              <span className="card-title">{hit.title || hit.doc_id}</span>
              <span className="card-meta">
                {hit.doc_type} · {hit.pages_matched} page(s) matched
              </span>
              <span className="card-meta">{hit.summary}</span>
              <Searchable ratio={hit.searchable_ratio} />
            </span>
          </button>
        ))}
      </div>
    </>
  )
}

function ChapterCards({ hits, error, loading, status, onOpen }: CardsProps<SectionHit>) {
  return (
    <>
      <Banner error={error} />
      <Empty hits={hits.length} loading={loading} status={status} what="chapters" />
      <div className="cards" data-testid="chapter-cards">
        {hits.map((hit) => (
          <button
            type="button"
            key={hit.section_id}
            className="card"
            data-testid="chapter-card"
            data-section-id={hit.section_id}
            onClick={() => onOpen(hit)}
          >
            <Thumb url={hit.preview?.thumb_url ?? null} alt={`first page of ${hit.title}`} />
            <span className="card-body">
              <span className="card-title">{hit.title || hit.section_id}</span>
              <span className="card-meta">
                {hit.page_range !== null ? `pages ${hit.page_range[0]}–${hit.page_range[1]} · ` : ''}
                {hit.pages_matched} page(s) matched
              </span>
            </span>
          </button>
        ))}
      </div>
    </>
  )
}

/**
 * A binder's searchable fraction, said out loud.
 *
 * **`0.00` is the one that matters.** A fully scanned document publishes and answers
 * `not_searchable` (§5.7, I7) — it is not missing, it is unsearchable by text, and a card that
 * showed it as an ordinary result with no rows would read as "nothing here". F4 is exactly that
 * confusion, and this is where a person meets it.
 */
function Searchable({ ratio }: { ratio: number }) {
  if (ratio >= 0.999) return null
  return (
    <span className="card-meta" data-testid="searchable-ratio" data-ratio={ratio.toFixed(2)}>
      {ratio <= 0 ? (
        <Badge spec={statusBadge('not_searchable')} />
      ) : (
        <>searchable text on {(ratio * 100).toFixed(0)}% of pages</>
      )}
    </span>
  )
}

function Empty({
  hits,
  loading,
  status,
  what,
}: {
  hits: number
  loading: boolean
  status: string | null
  what: string
}) {
  if (hits > 0) return null
  if (loading) return <p className="empty">searching…</p>
  if (status === null) return <p className="empty">Ask something, or browse from here.</p>
  return (
    <p className="empty" data-testid="rung-empty">
      No {what} matched — <span className="mono">{status}</span>.
    </p>
  )
}
