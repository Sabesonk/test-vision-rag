/**
 * One bearer-authenticated caller for the whole app.
 *
 * Three properties are enforced here rather than asked of each component, because each one is a
 * thing M7's acceptance asserts on the network log:
 *
 *   * **every request carries the token** (§16 Security: *"rasters never returned without auth"*).
 *     That is why a raster is fetched with `fetch()` and turned into an object URL instead of
 *     being handed to `<img src>`: an `<img>` sends no `Authorization` header, so the only way to
 *     make it work would be a token in the query string — which lands in every log and every
 *     referrer.
 *   * **a refusal is a refusal.** The service never returns an empty result for a failure
 *     (§7.1, §11.3), so neither does this: a non-2xx becomes an :class:`ApiError` carrying the
 *     typed `error` code, and the UI shows a banner rather than an empty list. A blank page that
 *     means "the backend is down" is the exact confusion the two envelope families exist to
 *     prevent.
 *   * **`inline` is `false` on every `fetch`.** Set in one place, so no component can undo it.
 *
 * Same-origin relative paths throughout — see the note in `vite.config.ts`.
 */
import type {
  AskResponse,
  DocHit,
  DocumentList,
  ErrorBody,
  FetchResult,
  LookupHit,
  PageHit,
  ResolveHit,
  SearchResponse,
  SectionHit,
  ToolEnvelope,
  ReadResult,
  VerifyResult,
} from './types.ts'
import type {
  AskBody,
  FetchBody,
  LookupBody,
  ReadBody,
  ResolveBody,
  SkimAggregateBody,
  SkimPagesBody,
  VerifyBody,
} from './requests.ts'
import { LOOKUP_CAP, SKIM_LIMIT } from './requests.ts'
import { readToken } from '../auth/token.ts'
import { DPI_INDEX, type Region } from '../lib/dpi.ts'

/** A typed refusal, in the shape the service sends it (`serve/errors.py`). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly body: ErrorBody

  constructor(status: number, body: ErrorBody) {
    super(body.detail || body.error || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = body.error || 'error'
    this.body = body
  }

  /** `retryable` rides on the body of an outage refusal (§11.3). */
  get retryable(): boolean {
    return this.body.retryable === true
  }
}

async function refusal(response: Response): Promise<ApiError> {
  let body: ErrorBody = { error: `http_${response.status}`, detail: response.statusText }
  try {
    const parsed: unknown = await response.json()
    if (parsed && typeof parsed === 'object') body = parsed as ErrorBody
  } catch {
    // A body that is not JSON is a proxy or a gateway talking, not this service. The status is
    // still the truth, and `detail` above still says something a person can act on.
  }
  return new ApiError(response.status, body)
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const token = readToken()
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await refusal(response)
  return (await response.json()) as T
}

async function get<T>(path: string): Promise<T> {
  const token = readToken()
  const response = await fetch(path, {
    headers: token ? { authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw await refusal(response)
  return (await response.json()) as T
}

// ── the eight tools of §7.2, each under its own named route (U031) ──────────────────────────────

export function skimDocuments(body: Partial<SkimAggregateBody>): Promise<SearchResponse<DocHit>> {
  return post('/tools/skim_documents', aggregate(body))
}

export function skimSections(body: Partial<SkimAggregateBody>): Promise<SearchResponse<SectionHit>> {
  return post('/tools/skim_sections', aggregate(body))
}

export function skimPages(body: Partial<SkimPagesBody>): Promise<SearchResponse<PageHit>> {
  return post('/tools/skim_pages', {
    ...aggregate(body),
    limit: body.limit ?? SKIM_LIMIT,
  })
}

export function lookup(body: Partial<LookupBody>): Promise<SearchResponse<LookupHit>> {
  return post('/tools/lookup', {
    label: body.label ?? '',
    scope: body.scope ?? {},
    include_unverified: body.include_unverified ?? false,
    cap: body.cap ?? LOOKUP_CAP,
  })
}

export function resolve(body: ResolveBody): Promise<SearchResponse<ResolveHit>> {
  return post('/tools/resolve', body)
}

export function verify(body: VerifyBody): Promise<ToolEnvelope<VerifyResult>> {
  return post('/tools/verify', body)
}

/**
 * `fetch`, always by reference. `inline` is pinned `false` here and is not a parameter of this
 * function — a component cannot ask for base64 even by accident (§7.1, P2).
 */
export function fetchPages(
  pageIds: string[],
  options: { include?: FetchBody['include']; dpi?: number; region?: Region | null } = {},
): Promise<ToolEnvelope<FetchResult>> {
  const body: FetchBody = {
    page_ids: pageIds,
    include: options.include ?? ['image', 'text', 'summary'],
    dpi: options.dpi ?? DPI_INDEX,
    region: options.region ?? null,
    inline: false,
  }
  return post('/tools/fetch', body)
}

/** The one tool that spends. Named `readPages` so no call site reads as a free `read`. */
export function readPages(body: ReadBody): Promise<ToolEnvelope<ReadResult>> {
  return post('/tools/read', body)
}

// ── the runner (§8.4) ───────────────────────────────────────────────────────────────────────────

export function ask(body: Partial<AskBody> & { question: string }): Promise<AskResponse> {
  return post('/ask', {
    question: body.question,
    scope: body.scope ?? {},
    exclude: body.exclude ?? [],
    // `null` rather than omitted: the field is declared on `AskRequest`, and sending it
    // explicitly keeps the two branches of this surface — run the loop, or gate a draft — one
    // request shape rather than two.
    draft: body.draft ?? null,
  })
}

// ── the corpus (U031) ───────────────────────────────────────────────────────────────────────────

/**
 * `GET /documents` — the corpus, without asking a question.
 *
 * Its shapes live in `types.ts` with every other wire type, and that placement is the fix for a
 * real defect rather than tidiness: they were declared here instead, where
 * `test_frontend_client_contract.py` does not look, and every field of them was wrong — a
 * `title` and a `grounded_rate` the route has never sent, and no `revisions` array, which is the
 * one thing this row exists to carry (§6.7 keeps superseded revisions rather than deleting
 * them). Nothing had consumed it yet, so nothing broke; the lesson is that a type outside the
 * checked file is an unchecked type.
 */
export function documents(): Promise<DocumentList> {
  return get('/documents')
}

// ── rasters: authenticated bytes → an object URL ────────────────────────────────────────────────

/**
 * A raster, fetched with the token, as **bytes**.
 *
 * It stops at the `Blob` rather than returning an object URL, and the reason is ownership: an
 * object URL has to be revoked by somebody, and this function is called through React Query,
 * which caches what it is given and evicts it without telling anyone. A cached object URL is
 * therefore a leak with a timer on it. A `Blob` is inert and collectable, so the cache can hold
 * it safely and `hooks/useRaster.ts` — the one place that mints a URL — revokes it on the effect
 * that made it.
 */
export async function rasterBlob(url: string): Promise<Blob> {
  const token = readToken()
  const response = await fetch(url, {
    headers: token ? { authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw await refusal(response)
  return await response.blob()
}

function aggregate(body: Partial<SkimAggregateBody>): SkimAggregateBody {
  return {
    query: body.query ?? '',
    image: body.image ?? '',
    scope: body.scope ?? {},
    exclude: body.exclude ?? [],
  }
}
