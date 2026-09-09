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

# Always wipe volumes on exit: a test run starts from an empty collection or it is not a test.
teardown() {
  echo ""
  echo "Tearing down test stack (wiping volumes)..."
  docker compose -f docker-compose.test.yml down -v
}
trap teardown EXIT

echo ""
echo "Starting test-qdrant and backend-test..."
docker compose -f docker-compose.test.yml up -d --build --wait test-qdrant backend-test

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
