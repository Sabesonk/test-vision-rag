/**
 * The stack the suite is asserting about — checked, rather than assumed.
 *
 * Every other file here would pass just as happily against a dev server on the host talking to a
 * dev Qdrant, and would then be evidence about nothing that ships. §15 Factor X asks for the
 * *same image as production, differing only in environment and ports*, and §4.2 pins which
 * ports: backend `8001`, Qdrant `6335` — **never** `6334`, which belongs to the dev instance and
 * which a test run could otherwise read and wipe — and the console on `5174`.
 *
 * The `latest` check is §15.2's, and it is cheap to keep honest: a tag that moves makes every
 * run above it a run against an unknown build.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

import { API, AUTH } from './console';

const COMPOSE = readFileSync(resolve('../docker-compose.test.yml'), 'utf-8');

test.describe('the replay stack', () => {
  test('declares the three ports §4.2 pins, and not the dev instance\'s', async ({ page }) => {
    // The **declaration** is the pin, and it is what this asserts: a host can legitimately
    // publish the console somewhere else (`VSIR_TEST_CONSOLE_PORT`) when 5174 is already taken,
    // and asserting on whatever port this run happens to use would assert nothing.
    expect(COMPOSE).toContain('"6335:6333"');
    expect(COMPOSE, '6334 is the dev instance\'s gRPC port: a test run there could wipe dev data')
      .not.toContain('"6334:');
    expect(COMPOSE).toContain('"8001:8000"');
    expect(COMPOSE).toContain('${VSIR_TEST_CONSOLE_PORT:-5174}:5173');

    // And that all three are actually answering, wherever this run published them.
    await page.goto('/');
    await expect(page.locator('h1')).toHaveText('vsir console');
    expect((await fetch(`${API}/health`)).status).toBe(200);
    expect(API).toContain(':8001');
    expect((await fetch('http://localhost:6335/collections')).status, 'Qdrant is not on 6335')
      .toBe(200);
  });

  test('runs tagged images and never `latest`', () => {
    const tags = Array.from(COMPOSE.matchAll(/^\s*image:\s*(\S+)\s*$/gm)).map((match) => match[1]);
    expect(tags.length, 'no image is declared at all').toBeGreaterThan(0);
    for (const tag of tags) {
      expect(tag, `${tag} has no tag, so it resolves to \`latest\``).toContain(':');
      expect(tag.endsWith(':latest'), `${tag} is a moving tag (§15.2)`).toBeFalsy();
    }
    // The backend the browser is talking to is built from the production Dockerfile, not from a
    // test-only target: one image, many process types (§15 Factors I, V, XII).
    expect(COMPOSE).toContain('dockerfile: Dockerfile');
    expect(COMPOSE).toContain('vsir:test');
  });

  test('is in replay mode: the stub VLM, a fixture, and no credential', async () => {
    // D10, from the outside. `/ready` is the only probe that knows, and the boot self-check
    // behind it refuses a `-latest` model id, so a green readiness is also F11 holding.
    const ready = await fetch(`${API}/ready`);
    expect(ready.status, await ready.text()).toBe(200);

    expect(COMPOSE).toContain('VSIR_VLM: "stub"');
    expect(COMPOSE).toContain('VSIR_ALLOW_PAID: "0"');
    expect(COMPOSE).toMatch(/VSIR_FIXTURE:/);
    expect(COMPOSE, 'a credential literal in a committed file (§15.2)').not.toMatch(/VSIR_VLM_KEY:\s*["']?\w/);
  });

  test('serves all eight tools of §7.2 and a corpus to ask about', async () => {
    // Asking for a tool that does not exist is how a caller learns which ones do: the refusal
    // is a typed `tool_not_found` carrying `available`, because *"a tool that is not here is
    // absent, not empty"* (§7.1). A 200 here would mean the release had grown a `__list__` tool.
    const listed = await fetch(`${API}/tools/__list__`, { method: 'POST', headers: AUTH });
    expect(listed.status).toBe(404);
    const body = await listed.json();
    expect(body.error).toBe('tool_not_found');
    const available = body.available as string[];
    expect(available.sort()).toEqual([
      'fetch',
      'lookup',
      'read',
      'resolve',
      'skim_documents',
      'skim_pages',
      'skim_sections',
      'verify',
    ]);

    const documents = await fetch(`${API}/documents`, { headers: AUTH });
    expect((await documents.json()).total, 'nothing was seeded to ask about').toBeGreaterThan(0);
  });
});
