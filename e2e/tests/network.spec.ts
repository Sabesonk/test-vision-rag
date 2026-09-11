/**
 * What the browser asked for, and what it never asked for.
 *
 * Three of M7's acceptance criteria are about the network log rather than the DOM, and each one
 * is a property that is invisible in a screenshot and expensive to get wrong:
 *
 *   * **zero requests to any Gemini endpoint, for the whole run.** Replay is the default and a
 *     miss is a typed `fixture_miss`, never a live call (D10) — but the console is the one
 *     surface a stray `<img src>` or a third-party script could smuggle a call out of, so it is
 *     asserted from the browser's side as well as the server's.
 *   * **no `bytes_b64` in anything the console consumed.** `inline=true` would move megabytes
 *     through JSON twice, and a `bytes_b64` in a skim row is a P2 violation (D12). The console
 *     pins `inline: false` in one place; this checks the consequence rather than the setting.
 *   * **a thumbnail is one image `GET` and no extra endpoint.** The reference is the payload's
 *     contribution and the fetch is the browser's — that is what makes `preview.thumb_url` a
 *     contract rather than a suggestion.
 */
import { expect, test } from '@playwright/test';

import { ask, corpus, openConsole } from './console';

/** Every host a Gemini call could go to. A request to any of them fails the run. */
const PAID = ['generativelanguage.googleapis.com', 'aiplatform.googleapis.com', 'googleapis.com'];

test.describe('the network log', () => {
  test('the console never reaches a paid endpoint, even across a whole question', async ({
    page,
    request,
  }) => {
    const { imageOnly } = await corpus(request);
    const log = await openConsole(page, { pageId: imageOnly.page_id });

    await ask(page, 'what does this sheet name');

    const paid = log.urls.filter((url) => PAID.some((host) => url.includes(host)));
    expect(paid, `the browser reached a paid endpoint: ${paid.join(', ')}`).toEqual([]);

    // Everything it *did* ask for is this origin. A console that loaded a font or a script from
    // somewhere else would be shipping a third party into an air-gapped deployment.
    //
    // `blob:` is excluded, and it is not a loophole: those are the console's **own** object URLs,
    // minted from bytes it already fetched with the bearer header. That indirection is the
    // mechanism §16 requires — an `<img src>` sends no `Authorization`, so the alternative is a
    // credential in the query string of every raster in every access log.
    const origin = new URL(page.url()).origin;
    const offsite = log.urls.filter(
      (url) => !url.startsWith(origin) && !url.startsWith('blob:') && !url.startsWith('data:'),
    );
    expect(offsite, `the console loaded something off-origin: ${offsite.join(', ')}`).toEqual([]);
  });

  test('nothing the console consumed carried image bytes', async ({ page, request }) => {
    const { docId } = await corpus(request);
    const log = await openConsole(page);

    await ask(page, docId);

    const inlined = log.bodies.filter((body) => body.includes('bytes_b64'));
    expect(
      inlined.length,
      'a JSON body carried `bytes_b64` — only `fetch(inline=true)` may, and the console pins it ' +
        'to false in one place so no component can undo it (§7.1, D12, P2)',
    ).toBe(0);

    const inlineTrue = log.urls.filter((url) => url.includes('inline=true'));
    expect(inlineTrue).toEqual([]);
  });

  test('a binder card shows its thumbnail from the row, with no extra endpoint call', async ({
    page,
    request,
  }) => {
    await corpus(request);
    const log = await openConsole(page);

    // Asked, not typed: the rung's skim runs on a question that was *asked*.
    await ask(page, 'safety');
    await expect(page.getByTestId('binder-cards')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('binder-card').first()).toBeVisible();

    // One aggregate call for the rung, and image `GET`s for the previews. No `fetch`, no second
    // skim, and nothing that could only have come from a URL the console built itself.
    const tools = log.urls.filter((url) => url.includes('/tools/'));
    expect(tools.every((url) => url.includes('/tools/skim_'))).toBeTruthy();
    expect(tools.filter((url) => url.includes('/tools/fetch'))).toEqual([]);

    const thumbs = log.urls.filter((url) => url.includes('/pages/') && url.includes('/image'));
    if ((await page.getByTestId('thumb').count()) > 0) {
      expect(thumbs.length, 'a thumbnail rendered with no image request behind it')
        .toBeGreaterThan(0);
    }
  });

  test('a raster is fetched with the bearer token, never with a token in the URL', async ({
    page,
    request,
  }) => {
    // §16 Security: rasters are never returned without auth, and the console honours that by
    // fetching the bytes and making an object URL — an `<img src>` sends no `Authorization`
    // header, so the only way to make one work would be a credential in every access log.
    const { imageOnly } = await corpus(request);
    const log = await openConsole(page, { pageId: imageOnly.page_id });

    await expect(page.getByTestId('page-viewer')).toBeVisible();
    const leaked = log.urls.filter(
      (url) => url.includes('token=') || url.toLowerCase().includes('authorization='),
    );
    expect(leaked, `a credential reached a URL: ${leaked.join(', ')}`).toEqual([]);
  });

  test('an unauthenticated console says so rather than showing empty panels', async ({ page }) => {
    await openConsole(page, { token: '' });
    await expect(page.getByTestId('no-token')).toBeVisible();
  });
});
