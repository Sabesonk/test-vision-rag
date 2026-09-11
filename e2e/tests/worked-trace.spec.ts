/**
 * The worked trace, through the console: one question, the loop, and a badged answer.
 *
 * This is the paid route in replay (D10) — the loop descends, triages, delegates a `read` to a
 * frozen response and gates what comes back — and it is the only test in the suite that depends
 * on a frozen page set, which is why the question is read out of the fixture's own acceptance
 * table rather than written here (`console.ts::answeringQuestion`).
 *
 * What it proves that `badges.spec.ts` cannot: that the same three badges, the same call log and
 * the same citation behaviour appear on the route where a **sub-model** looked, and that the
 * console's triage panel is fed by the typed `triage` table rather than by a sentence scraped
 * out of a trace move (§8.2, plan §4c P7).
 */
import { expect, test } from '@playwright/test';

import { answeringQuestion, ask, openCallLog, openConsole } from './console';

test.describe('the worked trace', () => {
  test('answers with a badge on every code, and the gate checked each one', async ({ page }) => {
    await openConsole(page);
    await ask(page, answeringQuestion());

    await expect(page.getByTestId('agent-panel')).toHaveAttribute('data-status', 'answered');
    const draft = page.getByTestId('draft');
    await expect(draft).toBeVisible();
    await expect(draft).toHaveAttribute('data-route', 'read');

    // Every rendered code carries one of the two badges — there is no third, because `absent`
    // never renders (§8.4) and `RenderedClaim`'s union does not contain it.
    const claims = page.getByTestId('claim');
    const count = await claims.count();
    expect(count, 'the worked trace rendered no code at all').toBeGreaterThan(0);
    for (let index = 0; index < count; index += 1) {
      const claim = claims.nth(index);
      const status = await claim.getAttribute('data-status');
      expect(['present', 'unverifiable']).toContain(status);
      await expect(
        claim.getByTestId(status === 'present' ? 'badge-verified' : 'badge-read-from-image'),
      ).toBeVisible();
    }

    // And the call log has a row per `(claim, page)` the gate really checked — I8 as an
    // observation about calls made, not as a claim about intent.
    await openCallLog(page);
    const rows = page.getByTestId('check-row');
    expect(await rows.count(), 'a code rendered with no check behind it').toBeGreaterThanOrEqual(
      count,
    );
    await expect(rows.first()).toBeVisible();
    await expect(page.getByTestId('citations')).toContainText('#p');
  });

  test('clicking a cited code takes the viewer to the page it was checked against', async ({
    page,
  }) => {
    await openConsole(page);
    await ask(page, answeringQuestion());

    const claim = page.getByTestId('claim').first();
    const cited = await claim.getAttribute('data-page-id');
    expect(cited).toBeTruthy();

    await claim.click();

    // The viewer is on that page — `claim.page_id`, the page the gate checked the code against,
    // and never the first citation (`lib/citations.ts`).
    await expect(page.getByTestId('page-viewer')).toHaveAttribute('data-page-id', cited!);
    // The strip beside it is the answer's evidence rather than the skim's rows, and the row for
    // the cited page is the selected one — which is what *"scrolls the viewer to its cited
    // page"* means when the strip is virtualised.
    await expect(page.getByTestId('strip-head')).toContainText('pages this answer cites');
    const row = page.locator(`[data-testid="strip-row"][data-page-id="${cited}"]`);
    await expect(row).toBeVisible();
    await expect(row, 'the cited page is in the strip but is not the selected row')
      .toHaveAttribute('aria-current', 'true');
  });

  test('the triage panel renders the typed table, including the excluded set', async ({ page }) => {
    await openConsole(page);
    await ask(page, answeringQuestion());

    // `triage` is a field on the body (plan §4c P7). The panel renders all three marks and the
    // `exclude` set **from that field** — the alternative, regexing a `Move.detail`, could not
    // produce the page ids at all because they were never in the prose.
    const panel = page.getByTestId('triage').or(page.getByTestId('triage-none'));
    await expect(panel).toBeVisible();

    if (await page.getByTestId('triage').count()) {
      await expect(page.getByTestId('triage-count-relevant')).toBeVisible();
      await expect(page.getByTestId('triage-count-uncertain')).toBeVisible();
      await expect(page.getByTestId('triage-count-irrelevant')).toBeVisible();

      const excluded = page.getByTestId('triage-exclude');
      await expect(excluded).toBeVisible();
      const declared = Number(await excluded.getAttribute('data-count'));
      const irrelevant = await page
        .locator('[data-testid="triage-row"][data-mark="irrelevant"]')
        .count();
      expect(
        declared,
        '§8.2: `exclude` is exactly the pages triage marked `irrelevant` — the `uncertain` pool ' +
          'is retained, and a console that excluded it would delete the fallback',
      ).toBe(irrelevant);
    }
  });

  test('the moves are collapsible and the spending one is marked as such', async ({ page }) => {
    await openConsole(page);
    await ask(page, answeringQuestion());

    const moves = page.getByTestId('moves');
    await expect(moves).toBeVisible();
    // `>` — the panel's **own** summary. Every move inside it is a `<details>` of its own, which
    // is the collapsibility §13 M7 asks for and also seven matches for a bare descendant query.
    await moves.locator('> summary').click();
    await expect(page.getByTestId('move').first()).toBeVisible();

    // The trace is the call log, so *"exactly one paid step"* is something a reader can see
    // rather than something the body asserts about itself (§8.4, AC-009).
    const spending = page.getByTestId('move-spends');
    expect(await spending.count()).toBeGreaterThan(0);
  });
});
