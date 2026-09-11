#!/usr/bin/env bash
# The local stack: bring it up, see what is queryable, put a document in it, take it down.
#
#   bash scripts/stack.sh up              build, start, create the collection, seed a document
#   bash scripts/stack.sh up --no-seed    the same, with an empty index
#   bash scripts/stack.sh status          probes, tools, documents, and the token to use
#   bash scripts/stack.sh seed [PDF]      ingest a PDF (default: the synthetic corpus, replayed)
#   bash scripts/stack.sh logs [SERVICE]  follow the JSON event stream
#   bash scripts/stack.sh vsir ...        any `vsir` subcommand, in the stack's own image
#   bash scripts/stack.sh down            stop, keep the index
#   bash scripts/stack.sh down --wipe     stop and drop the index
#
# It spends nothing: the stack runs VSIR_VLM=stub, which replays frozen responses by cache key and
# refuses a missing one as a typed `fixture_miss` rather than calling a model (D10).
set -euo pipefail

# Not `git rev-parse ... || cd ... && pwd`: shell precedence makes that `(a || b) && pwd`, so a
# successful rev-parse printed the toplevel *and* the pwd and the result was two lines.
if ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" && [[ -n "$ROOT" ]]; then
  :
else
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yml)
API="http://localhost:8055"
QDRANT="http://localhost:6353"

api_env() {
  # One variable read out of the **running** container. Printing what this shell believes is how
  # `status` came to advertise a token the API had never been given: a value set since the
  # container started, or a different variable name entirely, reads as authoritative and is not.
  local id
  id=$("${COMPOSE[@]}" ps -q api 2>/dev/null | head -1)
  [[ -n "$id" ]] || return 0
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$id" 2>/dev/null \
    | sed -n "s/^$1=//p" | head -1
}

# Resolved lazily, after the stack is up: before that there is no container to ask.
TOKEN=""
resolve_token() {
  TOKEN="$(api_env VSIR_API_TOKENS)"
  # Not running yet — fall back to what compose *would* substitute, in its own precedence order.
  [[ -n "$TOKEN" ]] || TOKEN="${VSIR_API_TOKENS:-dev-token-not-a-secret}"
  # A multi-token release is a comma-separated list; the first one is a working credential.
  TOKEN="${TOKEN%%,*}"
}

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
dim()  { printf "\033[2m%s\033[0m\n" "$*"; }

# A tiny JSON reader, because `jq` is not a dependency of this repo and a stack script that needs
# one installed is a stack script that does not run.
pyjson() { python3 -c "$1" 2>/dev/null || true; }

require_docker() {
  docker info >/dev/null 2>&1 || {
    echo "Docker is not running. Start Docker Desktop and try again." >&2
    exit 1
  }
}

cmd_up() {
  local seed=1 live=0
  for arg in "$@"; do
    case "$arg" in
      --no-seed) seed=0 ;;
      --live)    live=1; seed=0 ;;   # nothing is seeded with real money by accident
      *) echo "unknown option: $arg" >&2; exit 1 ;;
    esac
  done
  require_docker

  if [[ $live -eq 1 ]]; then
    # Exported so compose's `${VSIR_VLM:-stub}` and `${VSIR_ALLOW_PAID:-0}` resolve to these.
    # A shell variable beats `.env` in compose interpolation, which is what makes this an
    # override rather than an edit.
    export VSIR_VLM=gemini
    export VSIR_ALLOW_PAID=1
    # The **released** prompt set. `.env` stays on the version the checked-in fixtures were
    # frozen under, because replay is the default mode and its keys have to match them; a live
    # run has no fixtures to match and must use the text this release actually ships, or
    # `prompt()` refuses it by name. See PROMPT_DIGESTS in `vlm/client.py`.
    export VSIR_PROMPT_VERSION="${VSIR_PROMPT_VERSION_LIVE:-s2-v2}"
    [[ -n "${VSIR_VLM_KEY:-}" ]] || {
      echo "VSIR_VLM_KEY is not set — a live stack with no credential fails per call, after"  >&2
      echo "billing whatever it managed to send. Load it first:"                              >&2
      echo "  set -a && . ./.env && set +a"                                                   >&2
      exit 1
    }
    bold "LIVE: VSIR_VLM=gemini · VSIR_ALLOW_PAID=1"
    dim  "  Every ingest now calls ${VSIR_VLM_MODEL:-gemini-3.8-flash} for S1 and once per window"
    dim  "  for S2, and ${VSIR_EMBED_MODEL:-gemini-embedding-2} once per page. This costs real money."
    dim  "  Nothing is seeded in this mode. Freeze a paid run for free replay with:"
    dim  "     mkdir -p data/fixtures/live/your-doc   # ./data is mounted READ-ONLY;"
    dim  "     ...then bind that directory in writable and --record into it. Recording into"
    dim  "     /srv/data fails AFTER the call is billed: the recorder writes once the response"
    dim  "     is back, and cache.write does not handle an unwritable path."
  fi

  bold "Building the image (same Dockerfile as production and the test stack)"
  "${COMPOSE[@]}" build --quiet api

  bold "Starting Qdrant, creating the collection, starting the API"
  # `--wait` blocks until the API's healthcheck passes; `init` has to finish first, which the
  # compose file expresses as `service_completed_successfully`.
  "${COMPOSE[@]}" up -d --wait qdrant api

  if [[ $seed -eq 1 ]]; then
    bold "Seeding the synthetic corpus (42 pages, replayed, free)"
    cmd_seed
  fi

  echo
  cmd_status
}

cmd_seed() {
  require_docker
  local pdf="${1:-}"
  if [[ -z "$pdf" ]]; then
    # The one-shot service, exactly as the compose file declares it.
    "${COMPOSE[@]}" run --rm --no-deps seed | tail -25
    return
  fi
  [[ -f "$pdf" ]] || { echo "no such file: $pdf" >&2; exit 1; }
  bold "Ingesting $pdf"
  dim  "steps 01-03 need no model; 04 onwards replay from --fixture, or bill if --vlm gemini"
  # Mounted read-only under a fixed name, so a path with spaces or a symlink cannot surprise the
  # container, and the source stays untouched.
  "${COMPOSE[@]}" run --rm --no-deps \
    -v "$(cd "$(dirname "$pdf")" && pwd)/$(basename "$pdf")":/srv/in.pdf:ro \
    --entrypoint vsir seed ingest /srv/in.pdf "${@:2}"
}

cmd_status() {
  require_docker
  resolve_token
  bold "Containers"
  "${COMPOSE[@]}" ps --format "  {{.Service}}\t{{.Status}}\t{{.Publishers}}" 2>/dev/null \
    || "${COMPOSE[@]}" ps

  echo
  bold "Mode"
  # Read from the running container, not from this shell: what bills money is the API's own
  # environment, and a shell variable set since it started would report a comfortable lie.
  local vlm paid model
  vlm=$(api_env VSIR_VLM)
  paid=$(api_env VSIR_ALLOW_PAID)
  model=$(api_env VSIR_VLM_MODEL)
  if [[ "$vlm" == "gemini" ]]; then
    printf "  \033[1;33mLIVE — %s · every ingest bills S1, S2 per window, one embedding per page\033[0m\n" "${model:-?}"
    printf "  VSIR_ALLOW_PAID=%s%s\n" "${paid:-?}" \
      "$([[ "$paid" == "1" ]] && echo "" || echo "  (uploads are refused 403 spend_not_permitted)")"
  elif [[ -n "$vlm" ]]; then
    echo "  replay — VSIR_VLM=$vlm, frozen responses by cache key, spends nothing (D10)"
  else
    echo "  (the api container is not running)"
  fi

  echo
  bold "Probes"
  for probe in /health /ready; do
    printf "  GET %-8s %s\n" "$probe" "$(curl -s -o /dev/null -w '%{http_code}' "$API$probe" || echo "unreachable")"
  done

  echo
  bold "Tools this release serves"
  local tools
  tools=$(curl -s -H "Authorization: Bearer $TOKEN" -X POST "$API/tools/__list__" \
          | pyjson 'import sys,json;print(", ".join(json.load(sys.stdin).get("available",[])))')
  echo "  ${tools:-(the API did not answer)}"
  dim  "  all eight of §7.2 from U020. `read` is the only one that spends — and in replay"
  dim  "  mode it does not either: it is served from a frozen response by read_key (D10)."

  echo
  bold "Documents in the index"
  curl -s "$QDRANT/collections/${VSIR_COLLECTION:-vsir_pages}_${VSIR_EMBED_DIM:-1536}/points/scroll" \
       -H 'Content-Type: application/json' \
       -d '{"limit":500,"with_payload":["doc_id","revision","is_current"]}' \
    | pyjson '
import sys, json, collections
points = json.load(sys.stdin).get("result", {}).get("points", [])
live = collections.Counter(
    (p["payload"].get("doc_id"), p["payload"].get("revision"))
    for p in points if p["payload"].get("is_current"))
if not live:
    print("  (none yet — `bash scripts/stack.sh seed`)")
for (doc, rev), pages in sorted(live.items()):
    print(f"  {doc}@{rev}  {pages} page(s) queryable")'

  echo
  bold "Try it"
  echo "  Console      $API/console      (paste the token below into the header)"
  echo "  Swagger UI   $API/docs         (Authorize with the token below)"
  echo "  OpenAPI      $API/openapi.json"
  echo "  token        $TOKEN"
  dim  "               read out of the running container, so it is the one that works"
  echo
  echo "  curl -H \"Authorization: Bearer \$TOKEN\" -X POST $API/tools/lookup \\"
  echo "       -H 'Content-Type: application/json' -d '{\"label\":\"SF 1.13b\"}'"
  echo
  echo "  curl -H \"Authorization: Bearer \$TOKEN\" -X POST $API/documents \\"
  echo "       -F file=@your.pdf -F doc_id=YOUR-DOC -F revision=1.0"
}

cmd_down() {
  require_docker
  if [[ "${1:-}" == "--wipe" ]]; then
    bold "Stopping and dropping the index and the stored documents"
    "${COMPOSE[@]}" down -v
    # The documents are a host directory now, not a named volume, so `down -v` no longer takes
    # them. Emptying it here is what keeps §6.7's invariant: a wipe that dropped the index and
    # left the documents would leave a store describing a corpus that is no longer indexed —
    # every `page_id` in it unresolvable, and nothing saying why.
    local documents="${VSIR_DOCUMENTS_DIR:-$ROOT/var/documents}"
    if [[ -d "$documents" ]]; then
      # The directory itself survives: the compose mount expects it to exist, and recreating it
      # empty is the state a fresh stack starts in. `-mindepth 1` is what keeps `rm` off the
      # mount point, and the quoted path is what keeps it off everything else.
      find "$documents" -mindepth 1 -delete
      bold "Emptied $documents"
    fi
  else
    bold "Stopping; the index survives — `down --wipe` drops it"
    "${COMPOSE[@]}" down
  fi
}

cmd_logs()  { require_docker; "${COMPOSE[@]}" logs -f "${@:-api}"; }
cmd_vsir()  { require_docker; "${COMPOSE[@]}" run --rm --no-deps --entrypoint vsir seed "$@"; }

case "${1:-help}" in
  up)     shift; cmd_up "$@" ;;
  down)   shift; cmd_down "$@" ;;
  status) shift; cmd_status ;;
  seed)   shift; cmd_seed "$@" ;;
  logs)   shift; cmd_logs "$@" ;;
  vsir)   shift; cmd_vsir "$@" ;;
  *)      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
