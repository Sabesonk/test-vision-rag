/**
 * The shared harness: how a test opens the console, and where its inputs come from.
 *
 * **Nothing in this suite is a literal out of one fixture.** M7's acceptance says the assertions
 * hold on whichever fixture is present (`TC1E-SF` if OQ-1 is answered, else `synthetic_3window`),
 * and a suite that knew a page number or a printed code would pass on one corpus and fail on the
 * other while asserting nothing about either. So every input is derived, and by one of exactly
 * two routes:
 *
 *   * **from the running corpus** — the document, an image-only page, a page whose text
 *     extracted cleanly. `GET /documents` and `GET /documents/{doc}/pages` say all three, so the
 *     suite asks rather than assumes;
 *   * **from the fixture's own acceptance table** — the worked trace's question, read out of
 *     `expected.json` exactly as `tests/api/test_ask_replay.py` reads it. A question has to come
 *     from somewhere, and the table beside the frozen responses is the one place where it is
 *     already written down for the corpus that is loaded (C10).
 *
 * The one thing that is neither is :func:`absentCode` — a code-shaped token invented here — and
 * it is **verified absent through the service** before any test relies on it. An invented token
 * that turned out to be printed would make the rejection tests pass for the wrong reason.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

/** The backend, on its published port (§4.2: test `8001`, never dev's `8000`). */
export const API = process.env.E2E_API_URL ?? 'http://localhost:8001';

/**
 * The credential the container was configured with.
 *
 * Resolved the same way `docker-compose.test.yml` and `tests/api/conftest.py::CONTAINER_TOKEN`
 * resolve it, and from the same variable — reading `VSIR_API_TOKENS` here would pick up a
 * developer's real token out of `.env` and assert about a string the container never had.
 */
export const TOKEN = (process.env.VSIR_TEST_API_TOKENS ?? 'test-only-not-a-secret')
  .split(',')[0]
  .trim();

export const AUTH = { Authorization: `Bearer ${TOKEN}` };

/** `sessionStorage` key from `frontend/src/auth/token.ts`. Seeded before the bundle runs. */
const TOKEN_KEY = 'vsir.token';

/** The fixture directory on the host — the container sees the same tree under `/srv/data`. */
const FIXTURE = resolve(
  process.env.E2E_FIXTURE ?? '../data/fixtures/synthetic_3window',
);

export interface CorpusPage {
  page_id: string;
  page_no: number;
  has_text: boolean;
  text_trust: string;
  image_url: string;
}

export interface Corpus {
  docId: string;
  pages: CorpusPage[];
  /** A page with no text layer — where every code is `unverifiable` forever (R2, §5.7). */
  imageOnly: CorpusPage;
  /** A page whose text extracted cleanly — where a code can be `present` or `absent`. */
  searchable: CorpusPage;
}

/**
 * The corpus as the service describes it: a document, and one page of each kind in it.
 *
 * Both kinds have to exist for M7's badges to mean anything — `verified` needs a page with text
 * to check against, and *read from image* needs one without, because `unverifiable` is by
 * definition the verdict on a page nothing could check (§5.7, R2).
 *
 * **Which document is chosen is a search, not `documents[0]`.** A release can legitimately hold
 * a born-digital binder with no scan in it at all — `data/fixtures/TC1E-SF/expected.json`
 * predicts exactly that for the pilot — and picking the first row would then fail here with
 * *"no image-only page"* while another published document had one. So every document is asked,
 * and the first that has both kinds is the one the suite drives. That is the difference between
 * *"fixture-independent"* and *"independent of this fixture"*.
 *
 * If **no** document has both, the suite says so and stops. That is the honest outcome rather
 * than a skip: on a corpus with no scanned page, *"an `unverifiable` code renders with its
 * badge"* is not a UI assertion that has regressed, it is a state the corpus cannot produce.
 */
export async function corpus(request: APIRequestContext): Promise<Corpus> {
  const listed = await request.get(`${API}/documents`, { headers: AUTH });
  expect(listed.ok(), await listed.text()).toBeTruthy();
  const documents = (await listed.json()).documents as { doc_id: string }[];
  expect(documents.length, 'the E2E stack published no document to ask about').toBeGreaterThan(0);

  const missing: string[] = [];
  for (const { doc_id: docId } of documents) {
    const pages = await pagesOf(request, docId);
    const imageOnly = pages.find((page) => !page.has_text);
    const searchable = pages.find((page) => page.has_text && page.text_trust === 'ok');
    if (imageOnly && searchable) return { docId, pages, imageOnly, searchable };
    missing.push(
      `${docId}: ${imageOnly ? '' : 'no image-only page'}${!imageOnly && !searchable ? ', ' : ''}` +
        `${searchable ? '' : 'no page with clean text'}`,
    );
  }

  throw new Error(
    'no published document has both a page with no text layer and a page whose text extracted ' +
      'cleanly, so neither trust badge has a page to be about — ' +
      missing.join(' · '),
  );
}

/**
 * Every page of one document, paged.
 *
 * The listing caps at 200 rows and answers a larger ask with a typed `listing_limit_exceeded`
 * rather than silently truncating. A suite that only ever saw the first 200 pages of a long
 * manual could miss the corpus's only scan, which is the page half of these tests need.
 */
async function pagesOf(request: APIRequestContext, docId: string): Promise<CorpusPage[]> {
  const pages: CorpusPage[] = [];
  let offset = 1;
  for (;;) {
    const listed = await request.get(
      `${API}/documents/${encodeURIComponent(docId)}/pages?limit=200&offset=${offset}`,
      { headers: AUTH },
    );
    expect(listed.ok(), await listed.text()).toBeTruthy();
    const body = await listed.json();
    pages.push(...((body.pages ?? []) as CorpusPage[]));
    if (!body.next_offset || body.next_offset === offset) return pages;
    offset = body.next_offset as number;
  }
}

interface ReadCase {
  question: string;
  sufficient: boolean;
  stamps: { raw: string; status: string }[];
}

function readCases(): Record<string, ReadCase> {
  const table = JSON.parse(readFileSync(resolve(FIXTURE, 'expected.json'), 'utf-8'));
  const cases = table?.read?.cases as Record<string, ReadCase> | undefined;
  expect(
    cases,
    `${FIXTURE}/expected.json declares no \`read.cases\` — the worked trace has no question to ` +
      'ask, and inventing one would drive the loop into a read nobody froze (D10)',
  ).toBeTruthy();
  return cases!;
}

/**
 * The worked trace's question: the frozen case that answers, with every code it names printed.
 *
 * Picked by the shape of the case rather than by its name, so a fixture that calls it something
 * else still yields the same test. `sufficient` and *"every stamp `present`"* together are the
 * definition of the case §13 M6 calls the worked trace — the one that reaches a rendered answer
 * rather than an abstention.
 */
export function answeringQuestion(): string {
  const cases = Object.values(readCases()).filter(
    (one) =>
      one.sufficient &&
      one.stamps.length > 0 &&
      one.stamps.every((stamp) => stamp.status === 'present'),
  );
  expect(cases.length, 'no frozen case answers with every code present').toBeGreaterThan(0);
  // The shortest page set is the cheapest trace that still proves the property: one `read`.
  return cases[0].question;
}

/**
 * A code-shaped token (§6.8: *"a token containing at least one digit"*) that the corpus does not
 * print, **checked against the service rather than assumed**.
 *
 * This is what a misread looks like — the thing the answer gate exists to catch — and a test
 * that asserted a rejection while the token was quietly printed somewhere would be asserting
 * nothing at all. `lookup` is the exact surface (`MatchPhrase` over `variants`, I3), so a
 * `not_found` from it is the strongest statement available that no page prints this.
 */
export async function absentCode(request: APIRequestContext): Promise<string> {
  for (const candidate of ['ZQ7731', 'ZQ7732', 'ZQ7733']) {
    const response = await request.post(`${API}/tools/lookup`, {
      headers: AUTH,
      data: { label: candidate, scope: {}, include_unverified: true, cap: 20 },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    const body = await response.json();
    if (body.total === 0 && (body.unverified_hits ?? []).length === 0) return candidate;
  }
  throw new Error('every candidate token is printed in this corpus — pick another shape');
}

/**
 * A code the given page really prints, **confirmed by `verify` before it is used**.
 *
 * Derived the same way the service itself would: the page's own extracted text (`fetch`, which
 * returns what `ingest/probe.py` wrote and nothing else — I2), split into tokens, and each
 * code-shaped candidate (§6.8: contains a digit) put to `verify` against that page until one
 * comes back `present`. Guessing at which token shape a corpus uses is exactly the identifier
 * grammar §5.2 prohibits; asking the exact surface is not a guess.
 */
export async function presentCode(
  request: APIRequestContext,
  pageId: string,
): Promise<string> {
  const fetched = await request.post(`${API}/tools/fetch`, {
    headers: AUTH,
    data: { page_ids: [pageId], include: ['text'], dpi: 150, region: null, inline: false },
  });
  expect(fetched.ok(), await fetched.text()).toBeTruthy();
  const text = String((await fetched.json()).result?.pages?.[0]?.text ?? '');

  const candidates = Array.from(
    new Set(
      text
        .split(/\s+/)
        .map((token) => token.replace(/^[^0-9A-Za-z]+|[^0-9A-Za-z]+$/g, ''))
        .filter((token) => token.length >= 2 && /[0-9]/.test(token)),
    ),
  ).slice(0, 40);
  expect(candidates.length, `no code-shaped token in the text of ${pageId}`).toBeGreaterThan(0);

  for (const candidate of candidates) {
    const verified = await request.post(`${API}/tools/verify`, {
      headers: AUTH,
      data: { claims: [candidate], page_ids: [pageId] },
    });
    if (!verified.ok()) continue;
    const verdicts = (await verified.json()).result?.claims ?? {};
    const verdict = verdicts[candidate.toLowerCase()] ?? verdicts[candidate];
    if (verdict?.status === 'present') return candidate;
  }
  throw new Error(`no token of ${pageId} verified as present — the exact surface disagrees ` +
                  'with the text the page returned, which is a defect and not a test problem');
}

/** Every request the browser made, so a test can assert on what was *not* asked for. */
export interface NetworkLog {
  urls: string[];
  bodies: string[];
}

/**
 * Open the console with the operator's token already in the tab, and record what it fetches.
 *
 * The token is seeded through `addInitScript` rather than typed, for a reason the console itself
 * states: §16 requires that a raster is never served without auth, so an unauthenticated console
 * renders nothing and the first skim would 401 before a test could type. Typing it is covered
 * separately — `token.spec.ts` asserts the unauthenticated console says so rather than showing
 * empty panels.
 */
export async function openConsole(
  page: Page,
  options: { pageId?: string; token?: string } = {},
): Promise<NetworkLog> {
  const log: NetworkLog = { urls: [], bodies: [] };
  const token = options.token ?? TOKEN;

  await page.addInitScript(
    ([key, value]) => {
      if (value) window.sessionStorage.setItem(key, value);
      else window.sessionStorage.removeItem(key);
    },
    [TOKEN_KEY, token] as const,
  );

  page.on('request', (request) => {
    log.urls.push(request.url());
  });
  page.on('response', async (response) => {
    const type = response.headers()['content-type'] ?? '';
    if (!type.includes('json')) return;
    try {
      log.bodies.push(await response.text());
    } catch {
      // A response the browser discarded before the test read it. Nothing to record.
    }
  });

  const target = options.pageId ? `/#/page/${encodeURIComponent(options.pageId)}` : '/';
  await page.goto(target);
  await expect(page.locator('h1')).toHaveText('vsir console');
  return log;
}

/** Type a question into the header. Does not submit — some tests submit a draft instead. */
export async function askFor(page: Page, question: string): Promise<void> {
  await page.getByTestId('question').fill(question);
}

/** Ask, and wait for the loop to come back with an answer, an abstention or a banner. */
export async function ask(page: Page, question: string): Promise<void> {
  await askFor(page, question);
  await page.getByTestId('ask').click();
  await expect(page.getByTestId('ask-pending')).toHaveCount(0, { timeout: 25_000 });
  await expect(
    page.getByTestId('agent-panel').or(page.getByTestId('error-banner')),
  ).toBeVisible();
}

/**
 * Open the gate's call log — the `<details>` the check rows live in.
 *
 * Collapsed by default, and rightly: the log is the audit trail, not the answer, and a console
 * that led with it would put a redacted rejection at the top of what a reader came to read. A
 * badge inside a closed `<details>` is in the DOM and not on the screen, so a test that means
 * *"an operator can see this"* has to open it first.
 */
export async function openCallLog(page: Page): Promise<void> {
  const log = page.getByTestId('checks');
  await expect(log).toBeVisible();
  if ((await log.getAttribute('open')) === null) await log.locator('summary').click();
  await expect(log.getByTestId('check-rows')).toBeVisible();
}

/**
 * §8.1a's `fetch` route through the UI: stand on a page, write what it says, send it to the gate.
 *
 * Spends nothing — the operator looked, so no model is paid to — which is what makes it usable
 * as the setup step of three assertions without touching the read budget.
 */
export async function readOff(page: Page, text: string): Promise<void> {
  await page.getByTestId('read-off-text').fill(text);
  await page.getByTestId('read-off-submit').click();
  await expect(page.getByTestId('ask-pending')).toHaveCount(0, { timeout: 25_000 });
  await expect(
    page.getByTestId('agent-panel').or(page.getByTestId('error-banner')),
  ).toBeVisible();
}
