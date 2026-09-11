#!/usr/bin/env bash
# E2E — the console, driven by Playwright against the full Docker stack (Spec §12.2, U024).
#
#   ./scripts/test-e2e.sh              full automated run (up → seed → test → down -v)
#   ./scripts/test-e2e.sh --up         start the stack only, and leave it running
#   ./scripts/test-e2e.sh --headed     any further argument reaches `playwright test`
#
# It spends nothing and it cannot: the backend runs `VSIR_VLM=stub` against a frozen fixture
# (D10), `VSIR_ALLOW_PAID=0`, and no credential is in the environment it is given. A cache key
# the fixture does not hold is a typed `fixture_miss` — never a live call, never an invention.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

# Absolute: the teardown trap fires after the `cd e2e` below, where a relative path would
# silently resolve to nothing and leave the stack up.
COMPOSE="$ROOT/docker-compose.test.yml"

# The stack `docker-compose.test.yml` reads, and the suite reads the same names — so moving to
# the `TC1E-SF` fixture when OQ-1 is answered is one variable and no edit to a test.
#
# The **host** path and the **container** path are two variables for one directory: the compose
# file mounts `./data` read-only at `/srv/data`, so the container sees `/srv/data/fixtures/...`
# while Playwright reads `../data/fixtures/...` for the acceptance table beside the responses.
export VSIR_TEST_FIXTURE="${VSIR_TEST_FIXTURE:-/srv/data/fixtures/synthetic_3window}"
export E2E_FIXTURE="${E2E_FIXTURE:-$ROOT/data/${VSIR_TEST_FIXTURE#/srv/data/}}"
export VSIR_TEST_SOURCE="${VSIR_TEST_SOURCE:-/srv/data/source/synthetic_3window.pdf}"
# A whole question can spend three reads (§8.4) and the suite asks several. Ten is the right
# ceiling for L2/L3, where a leaked read should be noticed; here it would only make a later test
# fail for what an earlier one spent. The bound itself is exercised on its own instance
# (`tests/api/test_read_caps.py`).
export VSIR_TEST_READ_QUOTA="${VSIR_TEST_READ_QUOTA:-500}"
# The credential the container is given, resolved exactly as `docker-compose.test.yml` and
# `tests/api/conftest.py::CONTAINER_TOKEN` resolve it — the *test* variable, never the
# production one, which is where a developer's real token lives.
export VSIR_TEST_API_TOKENS="${VSIR_TEST_API_TOKENS:-test-only-not-a-secret}"

# 5174 is §4.2's pin and the default everywhere. The override exists because a developer machine
# can already have something on it, and it has to reach three places at once: the published port,
# the URL this script waits on, and the base URL Playwright drives.
CONSOLE_PORT="${VSIR_TEST_CONSOLE_PORT:-5174}"
export VSIR_TEST_CONSOLE_PORT="$CONSOLE_PORT"
API="http://localhost:8001"
CONSOLE="http://localhost:${CONSOLE_PORT}"
export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-$CONSOLE}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  E2E tests (Playwright — full Docker stack, replayed)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

require_docker() {
  docker info >/dev/null 2>&1 || {
    echo "Docker is not running. Start Docker Desktop and try again." >&2
    exit 1
  }
}

# `/ready` and not `/health`: liveness is green through a Qdrant outage by design (§15.1), so
# waiting on it would start the suite against a store that is not answering and an index that
# does not exist. Readiness is the probe that knows.
wait_for_ready() {
  local attempt=0
  until [[ "$(curl -s -o /dev/null -w '%{http_code}' "$API/ready" || true)" == "200" ]]; do
    attempt=$((attempt + 1))
    if (( attempt > 60 )); then
      echo "  /ready never went green — the boot checks, Qdrant or the collection:" >&2
      curl -s "$API/ready" >&2 || true
      docker compose -f "$COMPOSE" logs --tail 40 backend-test >&2 || true
      exit 1
    fi
    sleep 2
  done
  echo "  GET /ready → 200"
}

wait_for_console() {
  local attempt=0
  until [[ "$(curl -s -o /dev/null -w '%{http_code}' "$CONSOLE/" || true)" == "200" ]]; do
    attempt=$((attempt + 1))
    if (( attempt > 60 )); then
      echo "  the console never answered on $CONSOLE" >&2
      docker compose -f "$COMPOSE" logs --tail 40 frontend-test >&2 || true
      exit 1
    fi
    sleep 2
  done
  echo "  GET $CONSOLE → 200"
}

bring_up() {
  require_docker
  echo ""
  echo "── Stack (backend 8001 · Qdrant 6335 · console ${CONSOLE_PORT}) ────"
  # Qdrant and the backend first, so `/ready` can be waited on before a one-off ingest runs
  # against a collection that does not exist yet.
  docker compose --profile e2e -f "$COMPOSE" up -d --build --wait test-qdrant backend-test

  echo ""
  echo "── Collection and corpus (one-off admin, same image) ────"
  # Two `vsir` subcommands of the same release, not a branch in the server (§15 Factor XII).
  # They are compose *services* rather than ad-hoc `run` invocations so that `frontend-test`'s
  # `service_completed_successfully` dependency is satisfied by the same containers this ran —
  # a second seeding path would put the corpus in the index twice under two doc ids.
  docker compose --profile e2e -f "$COMPOSE" up --exit-code-from test-seed \
    --abort-on-container-failure test-seed 2>&1 | tail -4
  wait_for_ready

  echo ""
  echo "── Console ──────────────────────────────"
  docker compose --profile e2e -f "$COMPOSE" up -d --build --wait frontend-test
  wait_for_console
}

if [[ "${1:-}" == "--up" ]]; then
  bring_up
  echo ""
  echo "Stack is ready — left running:"
  echo "  Console (test): $CONSOLE"
  echo "  Backend (test): $API"
  echo "  Qdrant  (test): http://localhost:6335/dashboard"
  echo "  token:          ${VSIR_TEST_API_TOKENS%%,*}"
  echo ""
  echo "  cd e2e && npx playwright test          run the suite against it"
  echo "  docker compose --profile e2e -f $COMPOSE down -v"
  exit 0
fi

teardown() {
  # Capture the run's status FIRST: an EXIT trap whose last command succeeds would otherwise
  # replace it, and a failing suite would report success.
  local status=$?
  echo ""
  echo "Tearing down test stack (wiping volumes)..."
  docker compose --profile e2e -f "$COMPOSE" down -v
  exit $status
}
trap teardown EXIT

bring_up

echo ""
echo "── Playwright ───────────────────────────"
cd e2e
# The browser is a build input, not a dependency of the repo: install it on demand so a clean
# checkout runs the suite rather than failing with an executable-not-found the reader has to
# translate. It is a no-op once the cache is warm.
npm install --no-audit --no-fund --silent
npx playwright install chromium >/dev/null
npx playwright test "$@"
