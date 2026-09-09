#!/usr/bin/env bash
# Layer 0/1 — unit tests and the Spec §12.5 conformance greps. No Docker, no network, no paid API.
# Run after every unit, first: it is the fast layer and it is where the conformance gate lives.
#
#   bash scripts/test-unit.sh                      everything
#   bash scripts/test-unit.sh -k conformance       one slice; all arguments reach pytest
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Unit tests + conformance (Layer 0/1 — no Docker)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# The interpreter is pinned to 3.11 (§4.2) and the host's `python` usually is not, so prefer the
# project venv when it exists. Create it with:
#   uv venv backend/.venv --python 3.11 && uv pip install --python backend/.venv/bin/python \
#     -r backend/requirements-dev.txt && uv pip install --python backend/.venv/bin/python -e backend
PY="python"
if [[ -x backend/.venv/bin/python ]]; then
  PY="$ROOT/backend/.venv/bin/python"
fi

FAILED=0

echo ""
echo "── Backend ──────────────────────────────"
# Replay mode is the default for every test (D10): no test may reach a live model, and
# VSIR_ALLOW_PAID stays off so a stray paid call fails loudly rather than quietly billing.
(cd backend && VSIR_VLM=stub VSIR_ALLOW_PAID=0 "$PY" -m pytest -p no:cacheprovider --no-cov -q "$@") \
  || FAILED=1

if [[ -d frontend ]]; then
  echo ""
  echo "── Frontend ─────────────────────────────"
  (cd frontend && npx vitest run) || FAILED=1
  echo ""
  echo "── TypeScript ───────────────────────────"
  (cd frontend && npx tsc --noEmit) || FAILED=1
fi

echo ""
if [[ $FAILED -eq 0 ]]; then
  echo "Layer 0/1 PASSED"
else
  echo "Layer 0/1 FAILED — fix all failures before proceeding"
fi

exit $FAILED
