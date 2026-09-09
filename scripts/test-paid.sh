#!/usr/bin/env bash
# Layer 4 — the paid tests. These call a real model and cost real money.
#
#   VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh
#
# Run this ONLY for a unit marked `Spend: paid` in the plan. Every other layer runs in replay mode
# (VSIR_VLM=stub + VSIR_FIXTURE, D10), where a cache miss is a typed fixture_miss and never a live
# call. The gate below is deliberately a refusal and not a prompt: an accidental full-corpus run is
# a four-figure mistake.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Paid tests (Layer 4 — REAL MODEL CALLS)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ "${VSIR_ALLOW_PAID:-0}" != "1" ]]; then
  echo ""
  echo "REFUSED: VSIR_ALLOW_PAID is not 1 — this layer spends money."
  echo "         Re-run as: VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh"
  exit 1
fi

if [[ -z "${VSIR_VLM_KEY:-}" ]]; then
  echo ""
  echo "REFUSED: VSIR_VLM_KEY is not set — a paid layer with no credential would fail per-call,"
  echo "         after billing whatever it managed to send. See .env.example."
  exit 1
fi

if [[ ! -d backend/tests/paid ]] || ! compgen -G "backend/tests/paid/test_*.py" >/dev/null; then
  echo ""
  echo "No paid tests in this release — nothing to run. They arrive with U013 (§12.2 L4)."
  exit 0
fi

PY="python"
if [[ -x backend/.venv/bin/python ]]; then
  PY="$ROOT/backend/.venv/bin/python"
fi

echo ""
echo "── Paid tests ───────────────────────────"
cd backend && "$PY" -m pytest -p no:cacheprovider --no-cov tests/paid/ -v "$@"
