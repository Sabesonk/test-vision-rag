/**
 * §11.3's edge cases, seen from a browser: an outage must never look like an absence.
 *
 * This is §7.1's rule at the last layer it can be broken. The service is careful — a backend
 * failure is a 5xx and never an empty result — and a console can still throw all of that away by
 * rendering a failed query as an empty list. A reader cannot tell *"nothing matched"* from
 * *"nothing answered"* by looking at zero rows, and on this product that is the difference
 * between abstaining and concluding a part does not exist.
 *
 * The Qdrant container really is stopped here, which is why this file runs alone (`workers: 1`).
 * It is restored in an `afterAll` that runs even when an assertion fails — leaving the store
 * down would fail every file collected after it for a reason that has nothing to do with them.
 */
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

import { API, AUTH, absentCode, ask, openConsole } from './console';

const COMPOSE = resolve('../docker-compose.test.yml');
const STORE = 'test-qdrant';

function compose(...args: string[]): void {
  execFileSync('docker', ['compose', '-f', COMPOSE, ...args], { stdio: 'pipe' });
}

async function readyAgain(): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`${API}/ready`);
      if (response.status === 200) return;
    } catch {
      // The backend is up — it is the store that is not. Keep waiting.
    }
    await new Promise((wake) => setTimeout(wake, 1_000));
  }
  throw new Error('the store did not come back: every test after this one would fail for it');
}

test.describe('an outage is not an absence', () => {
  test.describe.configure({ mode: 'serial' });

  test.afterAll(async () => {
    compose('start', STORE);
    await readyAgain();
  });

  test('the store going down mid-session renders a banner, never a blank page', async ({
    page,
    request,
  }) => {
    // A code no page prints: the loop descends, finds nothing and abstains, **spending nothing
    // and reading no page**. That matters here for a reason that is not thrift — a question
    // that reached a `read` would depend on somebody having frozen that page set, and this file
    // is about the store being down, not about the fixture.
    const nothing = await absentCode(request);

    await openConsole(page);
    // A first question against a healthy stack, so the failure below is visibly a *change* and
    // not a console that never worked.
    await ask(page, nothing);
    await expect(page.getByTestId('agent-panel')).toBeVisible();
    await expect(page.getByTestId('error-banner')).toHaveCount(0);

    compose('stop', STORE);

    await page.getByTestId('question').fill('emergency stop reset');
    await page.getByTestId('ask').click();
    await expect(page.getByTestId('ask-pending')).toHaveCount(0, { timeout: 25_000 });

    // A typed refusal in a banner, carrying the service's own error code — and emphatically not
    // an abstention, which would be this console telling a reader the corpus holds nothing.
    // `.first()` because there is legitimately more than one: the question's own refusal at the
    // top, and the rung's, because the skims behind the viewer failed for the same reason. Every
    // surface that could not answer says so, which is the behaviour rather than a duplicate.
    const banner = page.getByTestId('error-banner').first();
    await expect(banner).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('abstention')).toHaveCount(0);
    await expect(page.locator('h1')).toHaveText('vsir console');

    const code = await banner.getAttribute('data-code');
    expect(code, 'the banner carried no typed error code').toBeTruthy();
    expect(code).not.toBe('not_found');
  });

  test('liveness stays green while readiness goes red — a restart would not fix the store', async () => {
    // §15.1, and the reason the two probes are separate: restart-looping a process whose backing
    // service is the thing that is down is how an outage becomes an outage plus a crash loop.
    const live = await fetch(`${API}/health`);
    expect(live.status, 'liveness went red on a backing-service outage').toBe(200);

    const ready = await fetch(`${API}/ready`);
    expect(ready.status).toBe(503);
    expect((await ready.json()).status).toBe('not_ready');
  });

  test('the store comes back and the console answers again', async ({ page, request }) => {
    compose('start', STORE);
    await readyAgain();

    const nothing = await absentCode(request);
    await openConsole(page);
    await ask(page, nothing);
    await expect(page.getByTestId('agent-panel')).toBeVisible();
    const banners = page.getByTestId('error-banner');
    const codes = await banners.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute('data-code')),
    );
    expect(codes, 'the console did not recover after the store came back').toEqual([]);
  });
});

test.describe('a cap is a message, not a crash', () => {
  test('a refusal from a tool reaches the operator as a typed banner', async ({ page }) => {
    // §7.3's caps are typed 400s naming their bound, and §11.3 asks that they surface as a
    // message rather than a stack trace. The console cannot construct an over-cap `read` — it
    // pins the page set and the dpi — so the refusal is provoked at the API and the assertion
    // is that the shape the console renders banners from is the shape the service sends.
    const refused = await fetch(`${API}/tools/read`, {
      method: 'POST',
      headers: { ...AUTH, 'content-type': 'application/json' },
      body: JSON.stringify({
        page_ids: ['a@1#p001', 'a@1#p002', 'a@1#p003', 'a@1#p004'],
        question: 'four pages is one more than the cap',
      }),
    });
    expect(refused.status).toBe(400);
    const body = await refused.json();
    expect(body.error).toBeTruthy();
    expect(String(body.detail)).toMatch(/3/);

    await openConsole(page);
    await expect(page.locator('h1')).toHaveText('vsir console');
  });
});
