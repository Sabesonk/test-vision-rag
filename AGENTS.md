# AI Agent Context — vision_segmentation_index_and_retrieval

Operational reference: run, build and test commands only. No status, no progress notes — those live
in `development/cr1/progress/implementation-progress.md`.

## Layout

| Path | What |
|---|---|
| `backend/vsir/` | the service and the CLI (Python 3.11, FastAPI, Pydantic v2) |
| `backend/vsir/eval/` | the corpora the `vsir demo` / `vsir eval` commands run against |
| `backend/tests/unit/` | L0/L1 — no Docker, no network, no paid API |
| `backend/tests/api/` | L2/L3 — needs the Docker test stack |
| `backend/tests/paid/` | L4 — real model calls, gated |
| `frontend/` | React + TypeScript + Vite (M7; does not exist yet) |
| `e2e/` | Playwright |
| `data/fixtures/` | frozen extractions, checked in |
| `data/fixtures/synthetic_pages/` | the §13 M1 corpus: hand-written page text + `expected.json` |
| `data/source/` | input PDFs, gitignored |

## Setup

The pin is Python **3.11** (`§4.2`), which is usually not the host's `python`. The project venv is
`backend/.venv` and the test scripts prefer it automatically when it exists.

```bash
uv venv backend/.venv --python 3.11
uv pip install --python backend/.venv/bin/python -r backend/requirements-dev.txt
uv pip install --python backend/.venv/bin/python -e backend        # puts `vsir` on the PATH
```

Configuration is the environment and only the environment. Nothing reads `.env` for you:

```bash
cp .env.example .env
set -a && . ./.env && set +a
```

Regenerate the lock after any change to `backend/requirements.txt`:

```bash
cd backend && uv pip compile requirements.txt --universal --python-version 3.11 \
  --generate-hashes --no-annotate --output-file requirements.lock
```

## Run

```bash
backend/.venv/bin/vsir doctor            # the §4.3 boot self-check; also `python -m vsir doctor`
backend/.venv/bin/vsir --help            # the §4.4 command table, as far as it is built
```

The M1 demo. It seeds `{VSIR_COLLECTION}_synthetic_{dim}` from `data/fixtures/synthetic_pages/`,
runs the §12.3 acceptance table against it and **drops the collection on the way out** — so it
needs a reachable Qdrant but never touches the serving collection:

```bash
backend/.venv/bin/vsir demo exact --synthetic              # both sections
backend/.venv/bin/vsir demo exact --only primitives        # pure: no Qdrant, no configuration
VSIR_QDRANT_URL=http://localhost:6335 backend/.venv/bin/vsir demo exact --synthetic
```

`--only corpus` without `--synthetic` has no data source at M1 and says so. Set
`VSIR_SYNTHETIC_PAGES` when the fixture is not at the repository path — the image's build context
is `backend/`, so a container running this command needs the corpus mounted.

The HTTP probes, until `vsir serve` lands in U014:

```bash
backend/.venv/bin/uvicorn --factory vsir.serve.app:app_factory --port 8000   # from backend/
curl -s localhost:8000/health            # liveness — green even with Qdrant down
curl -s localhost:8000/ready             # readiness — 503 `qdrant_unavailable` with Qdrant down
```

## Test

| Layer | Command | When |
|---|---|---|
| L0/L1 + conformance | `bash scripts/test-unit.sh` | always, first — fast, no Docker |
| L2/L3 | `bash scripts/test-api.sh` | after any `core`, `ingest`, `tool`, `mcp` or `runner` unit |
| E2E | `bash scripts/test-e2e.sh` | after any frontend unit, once L2 is green |
| L4 (paid) | `VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh` | only for a unit marked `Spend: paid` |

All arguments reach pytest: `bash scripts/test-unit.sh -k conformance`,
`bash scripts/test-api.sh -k probes`. L0–L3 and E2E can never reach a paid API — the stack and the
scripts set `VSIR_VLM=stub` and `VSIR_ALLOW_PAID=0`.

## Docker

```bash
docker build -t vsir:$VSIR_RELEASE_ID -f backend/Dockerfile backend
docker run --read-only --tmpfs /tmp:rw,noexec,nosuid,size=512m --env-file .env \
  vsir:$VSIR_RELEASE_ID doctor
```

The image runs as uid 10001 with a read-only root filesystem, its base is pinned by digest, and it
is never tagged `latest`. `ENTRYPOINT` is `vsir`, so the command is a subcommand.

Test stack (`docker-compose.test.yml`):

```bash
docker compose -f docker-compose.test.yml up -d --build --wait test-qdrant backend-test
docker compose -f docker-compose.test.yml stop test-qdrant     # prove /health vs /ready
docker compose -f docker-compose.test.yml down -v               # always -v
```

| Service | Host port | Note |
|---|---|---|
| `test-qdrant` | `6335` → 6333 | **never 6334** — that is the dev instance's gRPC port |
| `backend-test` | `8001` → 8000 | same image as production, env and ports differ |
| `frontend-test` | `5174` → 5173 | behind the `e2e` compose profile until M7 |

Dev ports, for reference: backend `8000`, Qdrant `6333` REST and `6334` gRPC, frontend `5173`.

## Conventions

- **Configuration is the environment.** A deployment-varying value is an env var in `.env.example`;
  never a literal, never a committed config file, never a secret in an image or a log line.
- **Qdrant is the only store**, two collections: `vsir_pages_<dim>` and `vsir_runs`. No relational
  database, no ORM, no migrations.
- **The stub VLM is selected by `VSIR_VLM=stub`**, never by a code branch and never by a test-only
  import. There is no `if TESTING:` in the production path.
- **Logs are JSON on stdout**, one event per line. The app never opens a log file.
- Conformance greps (`bash scripts/test-unit.sh -k conformance`) enforce the above and must stay
  green.

## The previous implementation

The working system this CR ports from is **outside this repo**:

```
/Users/sabesonk/Documents/VisionRag/dilmah-engineering-solutioning/poc/vision_segmentation_index_and_retrieval/impl
```

16 modules, 3,268 lines, no tests. Read the module a new one descends from before writing it — Spec
§2.4 is the port ledger and §4.1 maps new → old.
