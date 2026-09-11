#!/usr/bin/env bash
# Switch between the stub (free) and live (paid) configuration profiles.
#
#   bash scripts/use-env.sh stub    # replay: no model call can be made
#   bash scripts/use-env.sh live    # gemini: every ingest AND every search bills
#   bash scripts/use-env.sh         # report which profile .env currently is
#
# The samples are committed and carry no secret. This script copies the chosen one over `.env` and
# carries `VSIR_VLM_KEY` and `VSIR_API_TOKENS` across from the `.env` you already had, so switching
# profiles never silently drops the credential — a live run with an empty key fails per call, after
# billing whatever it managed to send.
set -euo pipefail

cd "$(dirname "$0")/.."

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

# The value of KEY in FILE, or empty. Tolerates a missing file and a commented line.
value_of() {
  local key=$1 file=$2
  [[ -f $file ]] || return 0
  sed -n "s/^${key}=//p" "$file" | tail -1
}

profile_of() {
  local vlm dim
  vlm=$(value_of VSIR_VLM .env)
  dim=$(value_of VSIR_EMBED_DIM .env)
  printf '%s (VSIR_VLM=%s, dim=%s -> %s_%s)\n' \
    "$([[ $vlm == gemini ]] && echo LIVE || echo STUB)" \
    "${vlm:-unset}" "${dim:-1536}" "$(value_of VSIR_COLLECTION .env)" "${dim:-1536}"
}

target=${1:-}

if [[ -z $target ]]; then
  if [[ -f .env ]]; then bold "current profile"; echo "  $(profile_of)"
  else warn "no .env — run: bash scripts/use-env.sh stub"; fi
  exit 0
fi

case $target in
  stub|live) ;;
  *) echo "usage: bash scripts/use-env.sh [stub|live]" >&2; exit 1 ;;
esac

sample=".env.${target}.example"
[[ -f $sample ]] || { echo "missing $sample" >&2; exit 1; }

# Carry the secrets over BEFORE overwriting.
carried_key=$(value_of VSIR_VLM_KEY .env)
carried_tokens=$(value_of VSIR_API_TOKENS .env)

if [[ -f .env ]]; then
  cp .env ".env.bak-$(date +%Y%m%d-%H%M%S)"
fi

cp "$sample" .env

if [[ -n $carried_key ]]; then
  # `|` as the delimiter: an API key can contain `/` but not `|`.
  sed -i.tmp "s|^VSIR_VLM_KEY=.*|VSIR_VLM_KEY=${carried_key}|" .env && rm -f .env.tmp
fi
if [[ -n $carried_tokens ]]; then
  sed -i.tmp "s|^VSIR_API_TOKENS=.*|VSIR_API_TOKENS=${carried_tokens}|" .env && rm -f .env.tmp
fi

bold "switched to ${target}"
echo "  $(profile_of)"
echo "  VSIR_PROMPT_VERSION=$(value_of VSIR_PROMPT_VERSION .env)  VSIR_ALLOW_PAID=$(value_of VSIR_ALLOW_PAID .env)"
echo "  VSIR_VLM_KEY $([[ -n $(value_of VSIR_VLM_KEY .env) ]] && echo 'carried over' || echo 'EMPTY')"

if [[ $target == live ]]; then
  echo
  warn "LIVE — every ingest bills S1, S2 per window and one embedding per page."
  warn "       Every SEARCH bills one query embedding. VSIR_ALLOW_PAID gates only POST /documents."
  [[ -n $(value_of VSIR_VLM_KEY .env) ]] || warn "       VSIR_VLM_KEY is EMPTY — set it before any run."
fi

echo
dim "Load it into the shell (the app never reads the file):"
dim "    set -a && . ./.env && set +a"
dim "Then restart the stack so the containers pick it up:"
dim "    bash scripts/stack.sh up$([[ $target == live ]] && echo ' --live')"
