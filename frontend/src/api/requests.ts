/**
 * The eight tools' request bodies — `backend/vsir/serve/inputs.py`, typed.
 *
 * `ToolRequest` forbids extras, so a misspelt parameter is a `400` rather than a quietly
 * different question. That is a good contract and it is also a trap for a hand-written client:
 * an optional field spelled wrong here fails at runtime, in production, as an `invalid_request`.
 * So every body below is a closed interface and the client takes nothing else.
 *
 * Two parameters this app pins rather than exposes:
 *
 *   * **`inline` is always `false`.** The console has a browser: it dereferences `image.url` and
 *     lets the raster travel as PNG once, instead of as base64 inside JSON and then as pixels
 *     again. `fetch(inline: true)` would move megabytes through JSON twice (§7.1).
 *   * **`read` has no `dpi` and no `region`**, because the pinned answer dpi is an input to
 *     `read_key` (F19) — a console that could raise it could miss the cache three times over one
 *     question.
 */
import type { CheckState } from './types.ts'

/** An `INDEXED` filter (§5.4). Narrowing only; a key outside `INDEXED` is a typed `400`. */
export type Scope = Record<string, unknown>

export interface LookupBody {
  label: string
  scope: Scope
  /** Opt-in, and every hit it adds is permanently `verified: false` (D3). */
  include_unverified: boolean
  cap: number
}

export interface VerifyBody {
  claims: string[]
  page_ids: string[]
}

export interface SkimPagesBody {
  query: string
  /** Base64. An image-only query runs the dense branch alone (D12) — and can never reach `lookup`. */
  image: string
  scope: Scope
  exclude: string[]
  limit: number
}

export interface SkimAggregateBody {
  query: string
  image: string
  scope: Scope
  exclude: string[]
}

export interface ResolveBody {
  printed_label: string
  doc_id: string
}

export type FetchPart = 'image' | 'text' | 'summary'

export interface FetchBody {
  page_ids: string[]
  include: FetchPart[]
  dpi: number
  region: [number, number, number, number] | null
  /** Always `false` from this app — see the module note. */
  inline: false
}

export interface ReadBody {
  page_ids: string[]
  question: string
}

export interface ClaimBody {
  code: string
  page_ids: string[]
}

/**
 * A draft the **operator** wrote, submitted to be gated — §8.1a's `fetch` route.
 *
 * The console is the one client of this service for which that route is literal: the page raster
 * is on the left of the screen and a person is looking at it. Nothing stamped what they read, so
 * the draft goes to the same server-side gate a `read` draft goes through, per `(claim, page)`,
 * before one word of it renders (§8.4, I8).
 *
 * `claims` is sent **empty on purpose**. The gate re-derives the claim set from the prose and
 * checks the union — a caller that listed two of the three codes in its own sentence would
 * otherwise have the third rendered with nothing having checked it. Declaring none is the
 * honest version of that: everything the operator typed is checked.
 */
export interface DraftBody {
  text: string
  claims: ClaimBody[]
  /** The pages it was written from — its citations, and what each code is checked against. */
  pages: string[]
}

export interface AskBody {
  question: string
  scope: Scope
  exclude: string[]
  /** Present only on the `fetch` route: nothing is searched and nothing is spent (§8.1a). */
  draft: DraftBody | null
}

/** `caps.MAX_SKIM_LIMIT` / `skim.SKIM_LIMIT`. Mirrored so a slider cannot ask for a `400`. */
export const SKIM_LIMIT = 10
export const MAX_SKIM_LIMIT = 25

/** `config.LOOKUP_CAP`. */
export const LOOKUP_CAP = 20

/** `config.MAX_READ_PAGES` — three, tightened from `impl`'s four deliberately (§7.3). */
export const MAX_READ_PAGES = 3

/** `caps.MAX_FETCH_PAGES`. */
export const MAX_FETCH_PAGES = 5

export const CHECK_STATES: readonly CheckState[] = ['present', 'absent', 'unverifiable']
