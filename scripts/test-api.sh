#!/usr/bin/env bash
# Layer 2/3 — API and integration tests against a real Qdrant in Docker.
# Run after any core, ingest, tool, mcp or runner unit, once Layer 0/1 is green.
#
#   bash scripts/test-api.sh                 everything under backend/tests/api/
#   bash scripts/test-api.sh -k probes       one slice; all arguments reach pytest
#
# No paid API is reachable from this layer: the stack sets VSIR_VLM=stub and VSIR_ALLOW_PAID=0.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  API integration tests (Layer 2/3 — Docker)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

COMPOSE="$ROOT/docker-compose.test.yml"

# Always wipe volumes on exit: a test run starts from an empty collection or it is not a test.
# The path is absolute because the trap fires from wherever the script happens to be — including
# after the `cd backend` below, where a relative path silently resolves to nothing and the
# teardown becomes a no-op that also fails the run.
teardown() {
  # Capture the run's status FIRST: an EXIT trap whose last command succeeds would otherwise
  # replace it, and a failing suite would report success.
  local status=$?
  echo ""
  echo "Tearing down test stack (wiping volumes)..."
  docker compose -f "$COMPOSE" down -v
  exit $status
}
trap teardown EXIT

echo ""
echo "Starting test-qdrant and backend-test..."
docker compose -f "$COMPOSE" up -d --build --wait test-qdrant backend-test

PY="python"
if [[ -x backend/.venv/bin/python ]]; then
  PY="$ROOT/backend/.venv/bin/python"
fi

echo ""
echo "── API tests ────────────────────────────"
# The host talks to the published ports: Qdrant on 6335, the backend on 8001 (§4.2).
cd backend && VSIR_TEST_QDRANT_URL="http://localhost:6335" \
              VSIR_TEST_BASE_URL="http://localhost:8001" \
              "$PY" -m pytest -p no:cacheprovider --no-cov tests/api/ -v "$@"
