/**
 * The replay suite's configuration (U024).
 *
 * Everything here is a property of the stack `scripts/test-e2e.sh` brings up, and nothing here
 * starts it. There is deliberately **no `webServer`**: the console under test is a container
 * built from `frontend/Dockerfile` and served by the same `vite preview` a release runs, sharing
 * a network with the same backend image production runs (§15 Factor X). A `webServer` block
 * would quietly substitute a dev server on the host for both of those, and the suite would stop
 * being evidence about anything that ships.
 *
 * `forbidOnly` and the single retry are on in CI only: a `test.only` that reaches CI is a suite
 * that silently stopped covering the rest, and a retry on a developer's machine hides a flake
 * they should see.
 */
import { defineConfig, devices } from '@playwright/test';

const CI = Boolean(process.env.CI);

export default defineConfig({
  testDir: './tests',
  // A whole `/ask` runs the loop: three free rungs, a triage, a replayed `read` and one `verify`
  // call per (claim, page). Thirty seconds is generous for that and still short enough that a
  // hung backend fails the run rather than stalling it.
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  // One worker: `test_outage.spec.ts` stops the Qdrant container, and a second worker asking a
  // question at that moment would be asserting about an outage it did not arrange.
  workers: 1,
  reporter: CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5174',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // The console is a two-zone workspace; below this the zones stack and the strip virtualises
    // differently. Pinned so a DOM-count assertion means the same thing on every machine.
    viewport: { width: 1600, height: 1000 },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
