/**
 * The wire, typed — `backend/vsir/serve/envelope.py`, `runner/answer.py` and `AskResponse`,
 * field for field.
 *
 * **This file is not allowed to drift, and it is not trusted not to.**
 * `backend/tests/unit/test_frontend_client_contract.py` reads it and compares every interface
 * below against the Pydantic model it names, plus `SCHEMA_VERSION` against
 * `core.record.SCHEMA_VERSION`. A field added to an envelope and not to its interface fails L0 on
 * the commit that adds it — which is the closest honest thing to *"a mismatch is a compile
 * error"* without a code generator, and unlike a generator it also fails when a field is added
 * *here* that the service does not send.
 *
 * Two shapes of the surface are expressed as types rather than as comments, because they are the
 * two things a console can most easily get wrong:
 *
 *   * **the two envelope families** (§7.1). `SearchResponse` can be empty and carries the
 *     typed-absence machinery; `ToolEnvelope` cannot, and its `status` says whether the *call*
 *     ran. A `verify` in which every claim is `absent` is `ok`, and the union below cannot be
 *     narrowed in a way that treats it as nothing found.
 *   * **`ImageRef` is not `FetchImage`** (P2, D12). Only the second one can carry `bytesB64`, and
 *     only `fetch` returns it — so a component handed a skim row has no field to read pixels out
 *     of, by type rather than by convention.
 *
 * Field names are the wire's own (snake_case). Renaming them to camelCase here would put a
 * translation layer between the contract and the code that reads it, and a translation layer is
 * a second declaration — the thing the contract test exists to prevent.
 */

/** `core.record.SCHEMA_VERSION` — pinned, and asserted against the service's `provenance`. */
export const SCHEMA_VERSION = 1

// ── the six-value status enum (§7.1, I5) ────────────────────────────────────────────────────────

/** Four of these six are absences, and each is a different next move for the caller. */
export type Status =
  | 'ok'
  | 'not_found'
  | 'not_searchable'
  | 'out_of_scope'
  | 'found_only_in_superseded'
  | 'error'

export const ABSENCES: readonly Status[] = [
  'not_found',
  'not_searchable',
  'out_of_scope',
  'found_only_in_superseded',
]

/** `core.status.CHECK_STATES` — per `(claim, page)`, and never collapsed into a boolean. */
export type CheckState = 'present' | 'absent' | 'unverifiable'

/** `core.record.TextTrust` — how far a page's extracted text can be believed (§5.7). */
export type TextTrust = 'ok' | 'degraded' | 'untrusted' | 'no_text'

/** The two levels that make a page unsearchable. `degraded` is deliberately not one of them. */
export const UNSEARCHABLE_TRUST: readonly TextTrust[] = ['untrusted', 'no_text']

// ── shared pieces ───────────────────────────────────────────────────────────────────────────────

export interface Provenance {
  run_id: string
  release_id: string
  schema_version: number
}

/** A **reference** to a raster. Sixty bytes, and no field that could hold pixels (P2). */
export interface ImageRef {
  url: string
  thumb_url: string
  dpi: number
  width: number
  height: number
}

/** An aggregate row's thumbnail: the group's best-ranked matched page, or page 1. */
export interface Preview {
  page_id: string
  thumb_url: string
}

export interface NextMoves {
  expand: Record<string, unknown>
  neighbours: string[]
  references: string[]
  suggest: string[]
  /** The caller's own query tokens that *do* occur in scope — evidence, never a candidate (F16). */
  tokens_observed: string[]
}

export interface DocScopeStat {
  doc_id: string
  searchable_ratio: number
}

export interface ScopeStats {
  pages: number
  /** The blind spot, as a number: why F4 cannot happen quietly. */
  pages_no_text: number
  docs: DocScopeStat[]
}

// ── Family A hits, one interface per rung ───────────────────────────────────────────────────────

/** `envelope.UNRANKED` — the ordinal a disclosure row carries, having matched nothing (§5.7). */
export const UNRANKED = 0

export interface DocHit {
  doc_id: string
  title: string
  doc_type: string
  pages_matched: number
  best_rank: number
  searchable_ratio: number
  summary: string
  preview: Preview | null
  next: NextMoves | null
}

export interface SectionHit {
  section_id: string
  title: string
  page_range: [number, number] | null
  pages_matched: number
  best_rank: number
  preview: Preview | null
  next: NextMoves | null
}

export interface PageHit {
  page_id: string
  printed_page_no: string
  summary: string
  summary_lang: string
  page_kind: string
  /** The surfaces that found it — `['dense']` alone for an image-only query (D12). */
  why: string[]
  rank: number
  flags: string[]
  /** `null` where the page has no text layer: nothing to be grounded in (§5.7). */
  grounded_rate: number | null
  text_trust: TextTrust
  image: ImageRef | null
  next: NextMoves | null
}

export interface LookupHit {
  page_id: string
  page_no: number
  printed_page_no: string
  page_kind: string
  /** Which *surface* the hit came from — `text` true, `vlm_codes` false. Never a check state. */
  verified: boolean
  text_trust: TextTrust
  image: ImageRef | null
  next: NextMoves | null
}

export interface ResolveHit {
  page_id: string
  printed_page_no: string
  label_verified: boolean
  interpolated: boolean
  image: ImageRef | null
}

export type Hit = DocHit | SectionHit | PageHit | LookupHit | ResolveHit

/**
 * One revision, no longer current, that does carry what was asked for (F9, §6.7 clause 2).
 *
 * The evidence behind `found_only_in_superseded`, and why that status is not an abstention:
 * *not in the corpus* and *in revision 1.3, which 1.4 replaced* are different facts. It carries
 * no hits — a superseded page is not current, so the caller is told which revision to ask for
 * rather than shown its contents.
 */
export interface SupersededIn {
  doc_id: string
  revision: string
  /** How many pages of that revision match. A count, never a page id. */
  pages: number
}

/** Family A. An empty `ok` is impossible — the service raises rather than sending one. */
export interface SearchResponse<H extends Hit> {
  status: Status
  hits: H[]
  /** `vlm_codes` hits only, every one `verified: false`, and never merged into `hits` (D3). */
  unverified_hits: LookupHit[]
  total: number
  capped: boolean
  /** A server constant decides this — never the caller's `cap` (§7.1). */
  weak: boolean
  needs_scope: boolean
  next: NextMoves | null
  effective_scope: Record<string, unknown>
  scope_stats: ScopeStats
  /** The revisions behind a `found_only_in_superseded`, and empty under every other status. */
  superseded: SupersededIn[]
  reads_remaining: number
  provenance: Provenance
}

// ── Family B: the call ran, and the answer is in `result` ───────────────────────────────────────

export interface ClaimVerdict {
  status: CheckState
  page_ids: string[]
  /** A capped prefix lookup over observed tokens, labelled *different part* (F16). */
  present_instead: string[]
  reason: string
}

export interface VerifyResult {
  claims: Record<string, ClaimVerdict>
}

/** The one shape in the whole surface that may carry pixels, and only when asked (§7.2.5). */
export interface FetchImage {
  url: string
  dpi: number
  region: [number, number, number, number] | null
  width: number
  height: number
  /** `null` when `inline: false` — *"no pixels travelled"*, in a shape a typed caller can read. */
  bytes_b64: string | null
}

export interface Summary {
  lang: string
  text: string
}

export interface FetchPage {
  page_id: string
  image: FetchImage | null
  /** `null` means *"I did not ask"*; `''` means the page's text layer is blank. */
  text: string | null
  summary: Summary | null
  text_trust: TextTrust
}

export interface FetchResult {
  pages: FetchPage[]
}

export interface ReadCode {
  /** The code **as the model returned it**, never normalised — that is what makes `absent` legible. */
  raw: string
  status: CheckState
  page_ids: string[]
  present_instead: string[]
  reason: string
}

export interface PageProvenance {
  page_id: string
  text_trust: TextTrust
}

export interface ReadResult {
  extract: string
  codes: ReadCode[]
  /** Whether these pages answer the question **on their own**. Never defaulted (§7.2.6). */
  sufficient: boolean
  flags: string[]
  page_provenance: PageProvenance[]
}

/** Family B. `status` says whether the **call** ran, not what it found. */
export interface ToolEnvelope<R> {
  status: 'ok' | 'error'
  result: R
  reads_remaining: number
  provenance: Provenance
}

// ── the runner (§8.4) ───────────────────────────────────────────────────────────────────────────

/** `answer.BADGE_VERIFIED` — the code is printed in the page's own extracted text (I2). */
export const BADGE_VERIFIED = 'verified'

/** `answer.BADGE_READ_FROM_IMAGE`, verbatim. Rewording it is a change to a product contract. */
export const BADGE_READ_FROM_IMAGE = 'read from image, not text-verified'

/** `answer.WARNING_UNVERIFIABLE` — one amber warning on the answer, not one per claim. */
export const WARNING_UNVERIFIABLE =
  'one or more codes in this answer were read from the page image and could not be checked ' +
  'against extracted text'

export interface RenderedClaim {
  code: string
  page_id: string
  /** `absent` is absent from this union on purpose: a rejected code never renders (§8.4). */
  status: 'present' | 'unverifiable'
  badge: string
}

export interface Answer {
  /** The look step's own words. Never rewritten by the service, and never by this app (§7.6). */
  text: string
  citations: string[]
  claims: RenderedClaim[]
  warnings: string[]
  route: 'read' | 'fetch'
}

export interface Abstention {
  text: string
  reason: string
  searched: string[]
  pages_searched: number
  pages_no_text: number
  pages_no_text_read: number
  /** The image-only pages nobody looked at — why *"not in these documents"* cannot be said. */
  image_only_unexamined: number
  blind_documents: string[]
  rejected_claims: number
}

export interface Move {
  step: number
  state: string
  action: string
  detail: string
  signal: string
  /** True on exactly the `read` moves (§8.1a). */
  spends: boolean
}

/** The gate's call log. `claim` is `''` on a rejection: it never echoes the code it rejected. */
export interface Check {
  claim: string
  page_id: string
  status: CheckState
}

export type TriageMark = 'relevant' | 'uncertain' | 'irrelevant'

export interface TriageRow {
  page_id: string
  mark: TriageMark
  reason: string
  /** An ordinal from the fused list. There is no score anywhere in this surface (§7.6). */
  rank: number
  why: string[]
  matched: string[]
  promoted: boolean
}

export interface TriageTable {
  query: string
  rows: TriageRow[]
  /** The `irrelevant` ids the next rung was sent — never the `uncertain` pool (§8.2). */
  exclude: string[]
  small_set: boolean
}

export interface AskResponse {
  status: 'answered' | 'abstained'
  answer: Answer | null
  abstention: Abstention | null
  trace: Move[]
  loops: string[]
  checks: Check[]
  reads: number
  reads_remaining: number
  route: string | null
  /** `null` when nothing was ever triaged — not the same fact as an empty table. */
  triage: TriageTable | null
  effective_scope: Record<string, unknown>
  provenance: Provenance
}

// ── the corpus (U031, `serve/manage.py`) ────────────────────────────────────────────────────────

/** One revision of one document. The others are **kept**, not deleted (§6.7, F9). */
export interface RevisionRow {
  revision: string
  pages: number
  /** Zero means retired or never published — step 11's gates are the only thing that flips it. */
  current_pages: number
  is_current: boolean
  run_id: string
}

export interface DocumentRow {
  doc_id: string
  doc_type: string
  subjects: string[]
  tags: string[]
  pages: number
  current_pages: number
  current_revision: string
  revisions: RevisionRow[]
  /** At 0.0 every code on every page is `unverifiable` rather than absent (§5.7, §7.1). */
  searchable_ratio: number
}

export interface DocumentList {
  documents: DocumentRow[]
  /** Documents in the index — not the length of `documents`. */
  total: number
  returned: number
  truncated: boolean
}

/** `serve/errors.py::ErrorResponse` — `extra="allow"`, so the bound's own fields ride along. */
export interface ErrorBody {
  error: string
  detail: string
  [key: string]: unknown
}
