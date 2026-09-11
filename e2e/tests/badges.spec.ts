/**
 * §13 M7's acceptance, in a browser: the three things the console must get right about trust.
 *
 * > *"a Playwright test drives the worked trace in replay mode and asserts that an
 * > `unverifiable` code renders with its badge, that a **rejected code is absent from the
 * > rendered answer**, and that the abstention text names the unread image-only pages."*
 *
 * All three **spend nothing**, and two of them are the operator's own draft — §8.1a's `fetch`
 * route, where a person looked at the raster on the left and wrote what it says. That is not an
 * economy, it is what makes the assertions fixture-independent: a trace that reaches a paid
 * `read` can only replay where somebody froze that exact page set, and which pages the ranking
 * offers is a property of the corpus and, as U024 found, of the platform that rendered it. The
 * gate is the same gate on both routes — §8.4 is unconditional and does not ask which one
 * produced the draft — so what these tests prove about badges holds for the paid route too, and
 * `worked-trace.spec.ts` drives that one to show it does.
 */
import { expect, test } from '@playwright/test';

import {
  absentCode,
  ask,
  askFor,
  corpus,
  openCallLog,
  openConsole,
  presentCode,
  readOff,
} from './console';

/** §8.5's forbidden sentence, lower-cased, as `runner/answer.py::FORBIDDEN_WORDING` holds it. */
const FORBIDDEN = 'not in these documents';

test.describe('the trust badges', () => {
  test('a code read off an image-only page renders with the *read from image* badge', async ({
    page,
    request,
  }) => {
    const { imageOnly } = await corpus(request);
    const code = await absentCode(request);

    await openConsole(page, { pageId: imageOnly.page_id });
    await expect(page.getByTestId('page-viewer')).toHaveAttribute(
      'data-page-id',
      imageOnly.page_id,
    );

    await askFor(page, 'what does this sheet name');
    await readOff(page, `This sheet names ${code}.`);

    // Rendered, and badged. The page has no text layer, so nothing could check it — which is
    // exactly why it renders *with the disclosure* rather than silently or not at all (R2).
    const claim = page.getByTestId('claim');
    await expect(claim).toHaveCount(1);
    await expect(claim).toHaveAttribute('data-status', 'unverifiable');
    await expect(claim.getByTestId('badge-read-from-image')).toHaveText(
      'read from image, not text-verified',
    );

    // The amber warning rides with it, and says the same thing about the answer as a whole.
    await expect(page.getByTestId('unverifiable-warning')).toBeVisible();

    // The gate's own call log agrees about the verdict, on the page it was cited on.
    await openCallLog(page);
    const check = page.getByTestId('check-row');
    await expect(check).toHaveCount(1);
    await expect(check).toHaveAttribute('data-status', 'unverifiable');
    await expect(check).toHaveAttribute('data-page-id', imageOnly.page_id);
  });

  test('a code the page really prints renders as `verified`, and carries no warning', async ({
    page,
    request,
  }) => {
    // The other end of the same vocabulary, and the reason the first test is not merely *"a
    // badge appeared"*: the two states have to be visually and structurally distinguishable,
    // reached by the same gesture on the same route.
    const { searchable } = await corpus(request);
    const code = await presentCode(request, searchable.page_id);

    await openConsole(page, { pageId: searchable.page_id });
    await askFor(page, 'what does this sheet name');
    await readOff(page, `This sheet names ${code}.`);

    const claim = page.getByTestId('claim').first();
    await expect(claim).toHaveAttribute('data-status', 'present');
    await expect(claim.getByTestId('badge-verified')).toHaveText('verified');
    await expect(page.getByTestId('badge-read-from-image')).toHaveCount(0);
    await expect(page.getByTestId('unverifiable-warning')).toHaveCount(0);
  });

  test('a code the gate rejected is absent from the rendered answer', async ({ page, request }) => {
    const { searchable } = await corpus(request);
    const code = await absentCode(request);

    await openConsole(page, { pageId: searchable.page_id });
    await askFor(page, 'which part does this sheet name');
    await readOff(page, `This sheet names ${code} on the safe input channel.`);

    // Not the code, not the sentence around it: one rejection discards the whole draft (§8.4).
    await expect(page.getByTestId('agent-panel')).toHaveAttribute('data-status', 'abstained');
    await expect(page.getByTestId('draft')).toHaveCount(0);
    await expect(page.getByTestId('abstention')).toHaveAttribute('data-reason', 'rejected');
    await expect(page.getByTestId('rejected-claims')).toBeVisible();

    // Auditable all the same — the row is kept and the claim is redacted, so the rejection can
    // be reviewed without putting the misread code back in front of a reader.
    await openCallLog(page);
    const check = page.getByTestId('check-row');
    await expect(check).toHaveText(/redacted/);
    await expect(check).toHaveAttribute('data-status', 'absent');
    await expect(check.getByTestId('check-absent')).toBeVisible();

    // *"Absent from the rendered answer"*, read at its strongest: with the call log **open**,
    // the whole right zone — draft, abstention, triage, moves and every one of the gate's rows
    // — does not contain the code anywhere. The operator's own text is still in the form on the
    // left, which is theirs and was never a rendered answer; what §8.4 forbids is this service
    // handing the string back.
    const answered = (await page.getByTestId('agent-panel').innerText()).toLowerCase();
    expect(answered).not.toContain(code.toLowerCase());
  });

  test('the abstention names the unread image-only pages and will not claim the corpus is exhausted', async ({
    page,
    request,
  }) => {
    const { docId } = await corpus(request);
    const code = await absentCode(request);

    // A question that is *nothing but* a code no page prints. The handle branch finds nothing,
    // the ladder finds nothing, and Loop 5 has no prose left to skim the blind spot with — so
    // the image-only pages stay unexamined and §8.5's inequality bites. Zero reads, which is
    // why this holds on any corpus with a scanned page rather than on one frozen page set.
    await openConsole(page);
    await ask(page, code);

    await expect(page.getByTestId('agent-panel')).toHaveAttribute('data-status', 'abstained');
    await expect(page.getByTestId('abstention')).toBeVisible();

    // The blind spot, named: how many pages nobody looked at, and which binder they are in.
    const blind = page.getByTestId('blind-spot');
    await expect(blind).toBeVisible();
    await expect(blind).toContainText(docId);
    await expect(page.getByTestId('image-only-unexamined')).toBeVisible();

    const text = (await page.getByTestId('abstention-text').innerText()).toLowerCase();
    expect(text).toContain('were not examined');
    expect(
      text,
      'an abstention that sounds complete while a page nobody looked at remains is a fabricated ' +
        'absence in the one direction nobody audits (§8.5)',
    ).not.toContain(FORBIDDEN);
  });

  test('an empty rung names which absence it is, never a bare "no results"', async ({
    page,
    request,
  }) => {
    // F4, one layer up in the UI. `not_found` says *abstain* and `not_searchable` says *escalate
    // to vision*: two different instructions, and a console that drew both as "nothing found"
    // would throw away the reason §7.1 has four absences instead of one. What the corpus rung
    // shows when it matches nothing is the **typed status**, and that is what this reads.
    const code = await absentCode(request);
    await openConsole(page);
    // Asked rather than typed: the ladder's skims re-run when a question is *asked*, so a
    // console that skimmed on every keystroke would spend a rung per letter.
    await ask(page, code);

    const empty = page.getByTestId('rung-empty');
    await expect(empty).toBeVisible({ timeout: 20_000 });
    const said = await empty.innerText();
    const named = [
      'not_found',
      'not_searchable',
      'out_of_scope',
      'found_only_in_superseded',
      'error',
    ].filter((status) => said.includes(status));
    expect(named, `the empty rung said "${said}" and named no status from the enum`).toHaveLength(1);
  });
});
