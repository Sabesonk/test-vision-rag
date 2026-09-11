# syntax=docker/dockerfile:1
#
# The console, built and served — the `frontend-test` service of `docker-compose.test.yml`, and
# the image the Playwright suite of U024 drives.
#
#   docker build -t vsir-console:$VSIR_RELEASE_ID -f frontend/Dockerfile frontend
#
# Tag with the release id, never `latest` (§15.2), and pin the base by digest rather than by tag
# for the same reason `backend/Dockerfile` does: `node:22-bookworm-slim` moves, a digest does not.
# Spec §4.2 pins the Python minor by the image digest and says nothing about Node, so the pin
# lives here and is the only place it is stated.
#
# **It serves with `vite preview`, not with a static file server, and that is load-bearing.**
# `vite.config.ts` declares the API proxy on *both* the dev server and the preview server
# precisely so this container is same-origin with the service: the console has no CORS boundary
# to cross, `image.url` arrives relative and resolves against the origin that served the page,
# and `VITE_API_URL` stays a proxy target (`http://backend-test:8000`, a name that resolves only
# inside the test network) rather than a URL handed to a browser on the host. Swapping in nginx
# would move that proxy into a second configuration file and break dev/prod parity (§15 X).
ARG NODE_BASE=node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

# ── build ────────────────────────────────────────────────────────────────────────────────────────
FROM ${NODE_BASE} AS build

ENV CI=1
WORKDIR /app

# The lockfile first, so a source edit does not re-resolve the dependency graph. `npm ci` installs
# exactly what `package-lock.json` pins and fails when the two disagree — the Node equivalent of
# the backend's `--require-hashes` (Factor II).
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html vitest.setup.ts ./
COPY src ./src

# `npm run build` is `tsc --noEmit && vite build`: a type error fails the image build rather than
# shipping a console that type-checks nowhere. `any` and raw hex are caught one layer earlier, by
# `src/conformance.test.ts` in `test-unit.sh`.
RUN npm run build

# ── runtime ──────────────────────────────────────────────────────────────────────────────────────
FROM ${NODE_BASE} AS runtime

LABEL org.opencontainers.image.title="vsir-console" \
      org.opencontainers.image.description="Operator console for vision segmentation, index and retrieval"

ENV NODE_ENV=production \
    CI=1
WORKDIR /app

# `node_modules` comes over whole rather than pruned to production dependencies: `vite preview` is
# what serves this app, and vite is a devDependency. Pruning it would leave an image that builds
# and cannot start.
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json /app/vite.config.ts ./

# One writable directory, and only one. Vite loads a **TypeScript** config by bundling it to
# `node_modules/.vite-temp/` first, so `vite preview` as an unprivileged user needs that path and
# nothing else. Found by running the image: the container exited `EACCES` on a path no test could
# have named. Creating it here rather than chowning `/app` keeps the rest of the bundle
# read-only to the process serving it.
RUN mkdir -p /app/node_modules/.vite-temp && chown -R node:node /app/node_modules/.vite-temp

# The base image's own unprivileged user. Nothing here writes to its own filesystem — the bundle
# is built, the proxy is stateless, and no configuration is baked in: `VITE_API_URL` arrives from
# the environment at start-up, which is when `vite.config.ts` reads it (§15 Factor III).
USER node

EXPOSE 5173

# No shell form: the process is PID 1 and has to receive SIGTERM directly, or a `down -v` waits
# out the ten-second grace period on every run (§15 Factor IX).
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "5173"]
