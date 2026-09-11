/// <reference types="vitest/config" />
//
// The dev/preview server, and the **proxy that keeps this app same-origin**.
//
// `VITE_API_URL` is the only deployment-varying value here (§15 Factor III), and it is a *proxy
// target* rather than a base URL the browser sees. That is deliberate, and it is what makes three
// separate problems disappear at once:
//
//   * **no CORS boundary.** The service has no CORS middleware and must not grow one: adding
//     `Access-Control-Allow-Origin` to a surface whose every route is bearer-authenticated widens
//     the attack surface of the credential for the convenience of one page. The browser talks to
//     the origin it loaded from; the proxy talks to the service.
//   * **`image.url` works as sent.** `raster_cache.page_image_url` returns a *relative* path on
//     purpose — "a browser resolves it against the origin it loaded the response from, which is
//     the only origin that can serve it". Same-origin is the condition that sentence assumes.
//   * **the container's target is not the browser's.** `docker-compose.test.yml` sets
//     `VITE_API_URL: http://backend-test:8000`, a name that resolves only inside the test
//     network. As a proxy target it is correct; as a URL handed to a browser on the host it would
//     be unreachable — which is the bug this arrangement avoids rather than documents.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Never a literal in a component, and never a credential: the operator's bearer token is typed
// into the page and lives in `sessionStorage` for the tab (§15 Factor III, §15.2). Baking a token
// into a bundle at build time would ship it to every browser that loads the app.
// `@types/node` is deliberately not a dependency: §4.2 pins the stack, and a console does not
// need Node's whole type surface to read one variable at config time. Declaring the single global
// this file touches keeps `tsc --noEmit` honest without widening the dependency set.
declare const process: { readonly env: Record<string, string | undefined> }

const target = process.env.VITE_API_URL ?? 'http://localhost:8000'

// Every path the service serves that this app calls. Listed rather than globbed, because a
// catch-all proxy would swallow the app's own routes and hide a 404 as an API error.
const API_PATHS = [
  '/ask',
  '/tools',
  '/pages',
  '/documents',
  '/runs',
  '/health',
  '/ready',
  '/openapi.json',
]

const proxy = Object.fromEntries(
  API_PATHS.map((path) => [path, { target, changeOrigin: false }]),
)

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  // The built image runs `vite preview`, so the proxy has to exist on both servers or the test
  // stack would work in dev and 404 in Docker — the parity failure §15 Factor X is about.
  preview: { port: 5173, proxy },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
})
