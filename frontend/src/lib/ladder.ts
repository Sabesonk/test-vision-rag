/**
 * The zoom ladder, as state — §13 M7's *"zoom-ladder breadcrumbs"*, and §8.1's *"the same move
 * repeated at three zoom levels"* with a person on the controls instead of the runner.
 *
 * The four rungs are the corpus, a **binder** (`skim_documents`), a **chapter**
 * (`skim_sections`) and a **page** (`skim_pages`), and below the page a `region` at escalated
 * dpi — which §7.3 makes part of the same gesture rather than a separate control, because above
 * 220 dpi a full page is over the megapixel bound and a crop is the only thing that can be
 * rendered.
 *
 * Kept here, pure, for two reasons. Climbing **up** has to clear everything below — a `doc_id`
 * left behind when the operator returns to the corpus would silently scope the next search to a
 * binder whose name is no longer on screen — and that is a rule worth a test rather than a
 * `setState` in a click handler. And jumping straight to a page is the gesture the draft's
 * citations use (`citations.ts`), from a component that knows a `page_id` and nothing else.
 */
import { DPI_ANSWER, DPI_INDEX, type Dpi, type Region, requiresRegion } from './dpi.ts'

export type Rung = 'corpus' | 'binder' | 'chapter' | 'page'

/** In order. A rung is reachable only when the one above it is satisfied. */
export const RUNGS: readonly Rung[] = ['corpus', 'binder', 'chapter', 'page']

export interface Ladder {
  docId: string | null
  docTitle: string
  sectionId: string | null
  sectionTitle: string
  pageId: string | null
  pageLabel: string
  dpi: Dpi
  region: Region | null
}

export const TOP: Ladder = {
  docId: null,
  docTitle: '',
  sectionId: null,
  sectionTitle: '',
  pageId: null,
  pageLabel: '',
  dpi: DPI_INDEX,
  region: null,
}

/** Where we are: the deepest rung whose id is set. */
export function rungOf(ladder: Ladder): Rung {
  if (ladder.pageId !== null) return 'page'
  if (ladder.sectionId !== null) return 'chapter'
  if (ladder.docId !== null) return 'binder'
  return 'corpus'
}

export interface Crumb {
  rung: Rung
  label: string
  /** False for a rung below where we are: there is nothing there to go back to yet. */
  reachable: boolean
  current: boolean
}

/** The breadcrumb trail, left to right. The labels are the corpus's own, never an id we invented. */
export function crumbs(ladder: Ladder): Crumb[] {
  const here = rungOf(ladder)
  const depth = RUNGS.indexOf(here)
  const labels: Record<Rung, string> = {
    corpus: 'corpus',
    binder: ladder.docTitle || ladder.docId || 'binder',
    chapter: ladder.sectionTitle || ladder.sectionId || 'chapter',
    page: ladder.pageLabel || ladder.pageId || 'page',
  }
  return RUNGS.map((rung, index) => ({
    rung,
    label: labels[rung],
    reachable: index <= depth,
    current: rung === here,
  }))
}

/**
 * Climb to `rung`, discarding everything below it — **including the region and the dpi**.
 *
 * The dpi reset is the part worth stating. An operator who escalated to 400 on a crop and then
 * went back up to the chapter list would, on picking the next page, ask for that page at 400 with
 * the previous page's region still set: a crop of the wrong page's corner, rendered successfully.
 * Escalation belongs to the page it was made on.
 */
export function climbTo(ladder: Ladder, rung: Rung): Ladder {
  const depth = RUNGS.indexOf(rung)
  return {
    docId: depth >= 1 ? ladder.docId : null,
    docTitle: depth >= 1 ? ladder.docTitle : '',
    sectionId: depth >= 2 ? ladder.sectionId : null,
    sectionTitle: depth >= 2 ? ladder.sectionTitle : '',
    pageId: depth >= 3 ? ladder.pageId : null,
    pageLabel: depth >= 3 ? ladder.pageLabel : '',
    dpi: depth >= 3 ? ladder.dpi : DPI_INDEX,
    region: depth >= 3 ? ladder.region : null,
  }
}

export function toBinder(ladder: Ladder, docId: string, title: string): Ladder {
  return { ...climbTo(ladder, 'corpus'), docId, docTitle: title }
}

export function toChapter(ladder: Ladder, sectionId: string, title: string): Ladder {
  return { ...climbTo(ladder, 'binder'), sectionId, sectionTitle: title }
}

/** Open a page from within the ladder: the binder and chapter above it stay as they are. */
export function toPage(ladder: Ladder, pageId: string, label: string): Ladder {
  return { ...climbTo(ladder, 'chapter'), pageId, pageLabel: label, dpi: DPI_INDEX, region: null }
}

/**
 * Jump to a page from a citation, knowing only its `page_id` — the draft's click target.
 *
 * The binder is recovered from the id (`doc_id@revision#pNNN`, §5.1) so the breadcrumbs still
 * say where the reader has landed. The chapter is not: a `page_id` does not carry one, and
 * inventing a chapter label to fill the crumb would be a fact the corpus never stated. The trail
 * shows the binder and the page, which is what is actually known.
 */
export function jumpToPage(pageId: string, label = ''): Ladder {
  const docId = docIdOf(pageId)
  return {
    ...TOP,
    docId,
    docTitle: docId ?? '',
    pageId,
    pageLabel: label || printedHint(pageId),
  }
}

/** `"TC1E-SF@1.3#p001"` → `"TC1E-SF@1.3"`, or `null` if this id is not shaped like one. */
export function docIdOf(pageId: string): string | null {
  const hash = pageId.indexOf('#')
  return hash > 0 ? pageId.slice(0, hash) : null
}

/**
 * The `#p001` tail, for a crumb label when nothing better is to hand.
 *
 * **A sequence number, not a printed page number.** They differ by the front matter's offset,
 * which is the whole subject of §6.4, so this is labelled `p001` rather than presented as a page
 * number a reader could look for on the paper.
 */
function printedHint(pageId: string): string {
  const hash = pageId.indexOf('#')
  return hash > 0 ? pageId.slice(hash + 1) : pageId
}

// ── the deep link (§13 M7's left zone, addressable) ─────────────────────────────────────────────

/**
 * `#/page/<page_id>` — the one piece of this app's state that belongs in the address bar.
 *
 * A page is the thing an operator points a colleague at (*"look at this sheet"*), and until the
 * viewer was addressable the only way to reach one was to repeat the search that found it. The
 * hash carries it, so a reload keeps the reader where they were and a link lands them there.
 *
 * It is the **hash** rather than a path on purpose: the console is served as one static bundle
 * and the service owns every other path on this origin (`vite.config.ts` proxies eight of them).
 * A client-side path route would need a server rewrite and would shadow a route the API may add.
 *
 * This is client state, not a session: nothing about it reaches the service, and every request
 * the page then makes still carries its own scope (C11).
 */
export const PAGE_HASH = '#/page/'

/** The page a hash addresses, or `null` when it addresses nothing. Never throws on junk. */
export function pageIdFromHash(hash: string): string | null {
  if (!hash.startsWith(PAGE_HASH)) return null
  const raw = hash.slice(PAGE_HASH.length)
  if (raw === '') return null
  try {
    return decodeURIComponent(raw)
  } catch {
    // A half-written percent escape in a pasted link. Addressing nothing is the right reading
    // of an address nobody can parse — better than throwing inside a render.
    return null
  }
}

/** The hash a ladder should be wearing. Empty above the page rung: there is nothing to address. */
export function hashForPage(pageId: string | null): string {
  return pageId === null ? '' : `${PAGE_HASH}${encodeURIComponent(pageId)}`
}

/** The ladder a hash names, or `null` to leave the current one alone. */
export function ladderFromHash(hash: string): Ladder | null {
  const pageId = pageIdFromHash(hash)
  return pageId === null ? null : jumpToPage(pageId)
}

/** Escalating past 220 without a crop is a request §7.3 refuses — so the UI asks for one first. */
export function needsRegion(ladder: Ladder): boolean {
  return requiresRegion(ladder.dpi) && ladder.region === null
}

/** The dpi the answer was read at, offered as a rung so a reviewer can see what `read` saw. */
export const DPI_READ = DPI_ANSWER
