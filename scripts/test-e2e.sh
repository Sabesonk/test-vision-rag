#!/usr/bin/env bash
# Layer 3 — E2E / UI tests: full Docker stack + Playwright.
#
# Usage:
#   ./scripts/test-e2e.sh          full automated run (up → test → down -v)
#   ./scripts/test-e2e.sh --up     start stack only (for interactive Playwright MCP session)
set -euo pipefail

# The suite never reaches a live model: the stack runs VSIR_VLM=stub against a frozen fixture
# (D10), so a UI assertion is deterministic and a run costs nothing.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

# Absolute: the teardown trap fires after the `cd e2e` below, where a relative path would
# silently resolve to nothing and leave the stack up.
COMPOSE="$ROOT/docker-compose.test.yml"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  E2E tests (Playwright — full Docker stack, replayed)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ "${1:-}" == "--up" ]]; then
  echo ""
  echo "Starting full test stack (leaving running for Playwright MCP)..."
  docker compose --profile e2e -f "$COMPOSE" up -d --build --wait
  echo ""
  echo "Stack is ready:"
  echo "  Frontend (test): http://localhost:5174"
  echo "  Backend  (test): http://localhost:8001"
  echo ""
  echo "Use Playwright MCP browser tools against http://localhost:5174"
  echo "Or run: cd e2e && npx playwright test"
  echo ""
  echo "Tear down when done:"
  echo "  docker compose --profile e2e -f $COMPOSE down -v"
  exit 0
fi

# Full automated run
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

echo ""
echo "Starting full test stack..."
docker compose --profile e2e -f "$COMPOSE" up -d --build --wait

echo ""
echo "── Playwright tests ─────────────────────"
cd e2e && npx playwright test "$@"
