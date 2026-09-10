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
| `data/fixtures/synthetic_3window/` | the M2a corpus's replay fixture: frozen S1 `facts/` + S2 `extract/`, keyed by §6.3 hash, + `expected.json` |
| `data/fixtures/legacy/` | the ported `impl` baseline of §12.1: 19 old-schema S2 responses + `labels.jsonl` / `withheld.jsonl` / `manifest.json` from `r-poc-5`, + `SOURCE.json` |
| `data/source/` | input PDFs, gitignored — except the generated `synthetic_3window.pdf` |

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

The M2a demo. Steps 01-10 of §6.1 over the generated 3-window corpus, with S1 and S2 both replayed
from the frozen fixture (D10). No network, no spend; steps 01-08 need no Qdrant either:

```bash
export VSIR_FIXTURE=data/fixtures/synthetic_3window
backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --vlm stub --until stitch
backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --until extract --raw  # full bodies
backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --until probe   # 01-02 only
VSIR_QDRANT_URL=http://localhost:6335 \
  backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --vlm stub --until index
```

`--until` takes
`manifest | probe | render | facts | window | extract | derive | stitch | embed | index | publish`;
later units extend the list. `--raw` prints every window's verbatim response body instead of its
first page form. Steps 01-03 need no fixture. From step 04 on, a `facts_key` or `extract_key` that
is not in `VSIR_FIXTURE` is a typed `fixture_miss` and a non-zero exit — never a live call (D10).
**`embed`, `index` and `publish` are the store-backed steps** (`vsir.cli.STORE_BACKED_STEPS`):
step 09 reads the embedding cache off the index, step 10 writes to it and step 11 flips
`is_current` on it, so with no reachable Qdrant all three refuse `qdrant_unavailable` rather than
re-billing every vector the index already holds. A store-backed run claims its **run point** at
step 01, before the first model call — so an unreachable store is named before anything is spent,
and a run that dies mid-flight is a run that exists.

Steps 07-08 cost nothing and print what they decided: a per-page table with the printed label,
`grounded_rate`, `codes_in_text` and any `moved_from`, then the section table with the window
folds each section survived. Both of §6.4's offset checks run at step 07, and a failure is a typed
`offset_check_failed` — the run bisects and re-bills rather than emitting a record for a window
whose pages it cannot place.

Steps 09-10 print the composed `types.Content` for the page with the most parts — §5.3's order,
one Part per language, the `dpi_index` raster last — then the `point_id` of every page written and
the surfaces each one carries. Everything is written `is_current=False`: step 11 (U011) is the only
thing that flips it. Re-running is free, because a page whose composition has not changed is
served from the vector already on its point (`embed_key`, register B5) — the second run of the
command above reports `0 embedded, 42 reused`.

The §6.6 fingerprint (`{embed_model, dim, distance, composition_version}`) is settled **before any
vector is bought** and recorded on a `kind: fingerprint` point in the `vsir_runs` control plane,
one per pages collection. Changing `VSIR_EMBED_MODEL`, `VSIR_EMBED_DIM` or the pinned
`COMPOSITION_VERSION` makes the next run refuse `embed_fingerprint_mismatch` with zero points
written — the remedy is a new collection plus a full re-embed plus an alias swap, never an
in-place mix:

```bash
VSIR_QDRANT_URL=http://localhost:6335 VSIR_EMBED_MODEL=some-other-embed-model \
  backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --vlm stub --until index
```

`--vlm gemini` is a live call and needs `VSIR_VLM_KEY` (from the platform secret store, never the
image); without it the run refuses `vlm_backend_unavailable`. **`VSIR_VLM` selects the embedding
backend too** — one switch for "does this release make live model calls", so a run that replays S2
from a fixture cannot quietly spend on embeddings. With `--vlm stub` the vectors are a
deterministic function of the composition, not a frozen response: there is nothing worth freezing
in 1,536 floats, and the property the tests need is that the same composition always gives the
same vector, which is why no embedding is in the fixture directory.

Step 11 is the gates, the publish flip and retirement (§6.7, §11.1). It prints the five gates with
their metric and detail, then what the flip and the three retirement clauses did. Nothing is
queryable before it: step 10 writes every point `is_current=False` and this is the only thing that
flips it (I7). The three operational commands that go with it:

```bash
backend/.venv/bin/vsir runs show <run_id>      # the §6.9 run record, read from vsir_runs (D9)
backend/.venv/bin/vsir gates rerun <run_id>    # re-evaluate §11.1 against the INDEX; free, changes nothing
backend/.venv/bin/vsir publish <run_id> --override grounded_rate --reason "<why>"
```

`--override` takes exactly one gate — `grounded_rate`, the only one whose threshold is a judgement
(R4). `window_coverage` and `offset_check` refuse an override by name. `--reason` is required and
is recorded in the run record and stamped on every page as the `published_with_override` flag.

`vsir ingest --resume <run_id> [--steal]` continues an existing run under its own id. The lease is
**advisory** — Qdrant has no compare-and-swap — so `--resume` refuses a live lease (`lease_held`)
unless `--steal` is passed; a duplicated worker re-bills windows but cannot corrupt the index,
because `point_id` is idempotent (I1) and nothing is queryable until the gates pass (I7). A
`SIGTERM` checkpoints the run as `state: stopped` and releases the lease, which is the one state a
resume takes without `--steal`. A `SIGKILL` leaves it `running` with a lease that expires — and, in
both cases, **zero queryable pages** (F17).

`VSIR_VLM_TIER=batch` refuses `vlm_tier_unsupported` — the tier is not a cache-key input, so
switching it later re-bills nothing. `VSIR_VLM_RPM` is the client's token bucket, in calls a
minute.

Recording a fixture. `--record DIR` freezes the run's **verbatim** S1/S2 bodies under the §6.3
keys replay reads them back by, plus `text.json` (§12.1's per-page extractor output). It is what
makes one paid ingest buy a permanent test corpus — and it works against the stub too, which is
how it is tested at zero spend:

```bash
export VSIR_FIXTURE=data/fixtures/synthetic_3window
backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --vlm stub \
  --record /tmp/recorded --until extract          # writes facts/, extract/ and text.json
backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --vlm stub \
  --fixture /tmp/recorded --until stitch          # ... and the recording replays
```

Recording is a **flag on one run, never configuration**: an ambient record mode would let a fixture
accumulate responses from runs nobody meant to freeze. A call that raised — a truncation to bisect,
an unreachable provider — freezes nothing, so the fixture holds only responses the pipeline
accepted (§6.2, F13). Each half of a bisected window is its own receipt.

The `grounded_rate` distribution report (§11.1, R4). It says what each candidate publish threshold
would have done to a document, and refuses to propose one off a corpus the extractor never
measured:

```bash
cd backend && ../backend/.venv/bin/python -m vsir.eval.grounded_rate --legacy   # a projection
cd backend && ../backend/.venv/bin/python -m vsir.eval.grounded_rate --synthetic --json
cd backend && ../backend/.venv/bin/python -m vsir.eval.grounded_rate --records pages.json \
  --threshold 0.75
```

`--records` takes a JSON array or JSONL of `PageRecord.to_payload()` payloads — the run's pages as
the index holds them. `VSIR_GROUNDED_RATE_THRESHOLD` is the same knob as `--threshold` and is read
**by this report only**: the number the publish gate uses is the `vsir.core.health.TRUST_OK_MIN`
pin, so adopting a threshold is a release rather than an env edit (§5.7, F14).

The M2b parity baseline. `data/fixtures/legacy/` is 19 S2 responses `impl` already paid for, plus
the export whose `labels.jsonl` is the §12.3 parity set and whose `withheld.jsonl` is the negative
set. Nothing here spends and nothing here needs a key:

```bash
cd backend && ../backend/.venv/bin/python -m vsir.eval.legacy   # what is in it, and the gains
bash scripts/test-api.sh -k "parity or withheld"                # the suites over it
```

The report prints, per document, the pages, windows, accepted identifiers, withheld codes and the
codes the old grammar dropped that the phrase index now finds — plus
`vsir.eval.legacy.NO_LEGACY_COVERAGE`, the list of §7/§8 paths parity says nothing about (R7).

Re-port it from an `impl` tree (idempotent; it rewrites `SOURCE.json`'s digests from the bytes it
copied, and `python -m pytest tests/unit/test_legacy_fixture_integrity.py` re-checks them against
the source when `VSIR_IMPL_ROOT` points at one):

```bash
cd backend && ../backend/.venv/bin/python -m vsir.eval.legacy --port /path/to/impl
VSIR_IMPL_ROOT=/path/to/impl bash scripts/test-unit.sh -k legacy_fixture_integrity
```

The export run is pinned to `r-poc-5` (`vsir.eval.legacy.EXPORT_RUN`) and the reason is recorded in
`SOURCE.json`: it is the only one of `impl`'s five whose `withheld.jsonl` is what §12.1 describes.
The raw responses are **not** a `VSIR_FIXTURE` replay directory — they answer the old schema under
the old cache key, so replay would be a lie; `vsir.eval.legacy.adapt` renames them for the L1 suite
instead.

Regenerate the corpus (reproducible byte for byte; the PDF and every fixture file are committed):

```bash
cd backend && ../backend/.venv/bin/python -m vsir.eval.synthetic_pdf
```

It reads `VSIR_VLM_MODEL` and `VSIR_PROMPT_VERSION`, because all four keys of §6.3 are keyed on
them: change either and the frozen responses are written under new names. The S2 responses also
move when `DPI_ANSWER` or the `WindowOut` schema moves, and the old files stop being found — a
typed `fixture_miss` rather than a stale hit. Editing `backend/vsir/vlm/prompts/*.md` without
adding a new version to `PROMPT_DIGESTS` is refused by name (`prompt_unavailable`): a prompt is
part of the release, not configuration.

The HTTP surface, until `vsir serve` lands in U014 — the two probes, the run record, the two
exports and the §11.4 gauges:

```bash
backend/.venv/bin/uvicorn --factory vsir.serve.app:app_factory --port 8000   # from backend/
curl -s localhost:8000/health            # liveness — green even with Qdrant down
curl -s localhost:8000/ready             # readiness — 503 `qdrant_unavailable` with Qdrant down
curl -s localhost:8000/runs/<run_id>     # the §6.9 run record; a typed 404 for an unknown run
curl -s localhost:8000/runs/<run_id>/export/labels.jsonl           # one NDJSON line per page
curl -s localhost:8000/runs/<run_id>/export/observed_tokens.jsonl  # one line per document
curl -s localhost:8000/metrics           # ingest_grounded_rate_median, ingest_gate_failures_total
```

Both exports are **generated from the index and streamed** — nothing is written to the instance's
filesystem and there is no file to read from it (§6.8, §15 Factor VI), so any replica serves any
run. `withheld.jsonl`, `impl`'s third file, is gone with the allowlist gate that produced it and is
a typed 404. The gauges are recomputed from `vsir_runs` on every scrape rather than counted in the
process, so two replicas agree and a restart is not a hole in the series.

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

CI runs the first two on every push and pull request (`.github/workflows/ci.yml`), and names the
§12.4 abstention eval as its own step so a failure there is legible in the run summary rather than
buried in 136 dots. It references no secret: L0–L3 are replay-mode only (D10), and L4 is not run
there at all.

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
  `VSIR_SAFETY_DOC_TYPES` and `VSIR_SAFETY_TOPICS` are the §6.8 export's two sources for
  `safety_flag`; both default to empty, and a list compiled into the image would be the keyword
  taxonomy §6.8 deletes.
- **Qdrant is the only store**, two collections: `vsir_pages_<dim>` and `vsir_runs`. No relational
  database, no ORM, no migrations. `vsir_runs` is payload-only (`vectors_config={}`) and every
  point in it says which `kind` of control record it is.
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
