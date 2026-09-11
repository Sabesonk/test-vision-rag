# Project: vision_segmentation_index_and_retrieval

VSIR — vision segmentation, indexing and retrieval over engineering binders. A VLM extracts page
facts, pages are indexed into Qdrant as one dense + two sparse surfaces, and eight tools (§7.2)
serve them over HTTP, MCP and a CLI. `AGENTS.md` is the full operational reference; this file is
what must be true before any of it runs.

## Tech Stack

- **Backend** — Python **3.11** (pinned, §4.2), FastAPI, Pydantic v2. Venv at `backend/.venv`;
  `uv pip install --python backend/.venv/bin/python -e backend` puts `vsir` on the PATH.
- **Store** — Qdrant, and nothing else. Two collections, no relational database, no ORM, no
  migrations.
- **Models** — Gemini (VLM for S1/S2/`read`, plus embeddings), or the `stub` backend that replays
  frozen responses. Selected by one variable, never by a code branch.
- **Frontend** — React + TypeScript + Vite (`frontend/`), same-origin by proxy, no CORS middleware.
- **Tests** — pytest L0–L4 (`scripts/test-*.sh`), Playwright E2E, vitest.
- **Runtime** — Docker; uid 10001, read-only root filesystem, base pinned by digest, never `latest`.

## The two modes — `VSIR_VLM` is the whole switch

It selects the extraction backend **and** the embedding backend together, so a run that replays
extraction cannot quietly spend on embeddings (§15 Factor X, D10). Both backends are compiled into
the image and chosen by a dict lookup (`vsir.vlm.BACKENDS`, `vsir.ingest.embed.EMBEDDERS`).
**There is no `if TESTING:` in the production path** — a conformance grep fails the build if one
appears, so the path under test is the path that ships.

| | **replay** — `VSIR_VLM=stub` | **live** — `VSIR_VLM=gemini` |
|---|---|---|
| S1 / S2 / `read` | frozen bodies from `$VSIR_FIXTURE`, by the §6.3 key | `$VSIR_VLM_MODEL`, billed per call |
| embeddings | deterministic function of the composition | `$VSIR_EMBED_MODEL`, one call per page |
| credential | none | `VSIR_VLM_KEY`, else `vlm_backend_unavailable` |
| a key the fixture lacks | typed `fixture_miss`, non-zero exit — **never** a live fallback | — |
| cost | zero on every path | real money on every path |

### Activating replay (the default: CI, L0–L3, E2E, the console, every demo)

```bash
export VSIR_VLM=stub
export VSIR_FIXTURE=data/fixtures/synthetic_3window     # REQUIRED — see below
backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf
backend/.venv/bin/vsir ingest <pdf> --vlm stub --fixture /tmp/recorded   # per-run, no env edit
```

`VSIR_VLM=stub` with no fixture directory is a **refusal by name**, not a skip — a suite that
asserted nothing would be worse than one that stopped. `scripts/stack.sh up`, `scripts/test-*.sh`
and `docker-compose.test.yml` set the mode themselves and reference no secret.

### Activating live — four things that must move together

```bash
export VSIR_VLM=gemini                        # 1. extraction AND embeddings
export VSIR_VLM_KEY=<from the secret store>   # 2. never in the image, never in a log line
export VSIR_PROMPT_VERSION=s2-v2              # 3. the RELEASED prompts, not the fixtures' s2-v1
export VSIR_ALLOW_PAID=1                      # 4. POST /documents + scripts/test-paid.sh only
backend/.venv/bin/vsir ingest <pdf> --record data/fixtures/live/<doc>

bash scripts/stack.sh up --live               # exports all four, refuses without the key, seeds nothing
bash scripts/stack.sh status                  # reads the mode out of the RUNNING container
```

- `VSIR_PROMPT_VERSION` stays `s2-v1` in `.env` because replay keys on what the fixtures were
  frozen under; a live run must use the text the release ships or `prompt()` refuses
  `prompt_unavailable`. A prompt is part of the release, not configuration.
- `VSIR_ALLOW_PAID` gates the **upload boundary**, not the CLI: `vsir ingest --vlm gemini` bills
  either way, because a CLI ingest is already deliberate.
- **Stub and live never reuse each other's vectors** — `StubEmbedder` namespaces its model id as
  `stub:<model>` (`fixes/006`), so switching `VSIR_VLM` re-embeds rather than reporting hash
  vectors as `reused`. The §6.6 fingerprint is unchanged by the switch.
- **Freeze the paid run or pay again.** `--record DIR` writes verbatim bodies under the §6.3 keys.
  It writes *after* the response is back, so an unwritable path fails **after the call is billed**,
  and `./data` is read-only in the container — record to a writable bind mount or run on the host.

`vsir doctor` emits `vlm`, `vlm_model`, `replay`, `fixture_dir` and `vlm_key_present` (presence,
never the value) on its `config_valid` check line. In the event stream `vlm_replay` is a served fixture and `vlm_cache_hit` is a call
that did not happen.

## Environment — the only source of configuration (§15 Factor III)

Nothing reads `.env` for you: `cp .env.example .env && set -a && . ./.env && set +a`. Anything that
does **not** vary by deployment — dpi, fusion weights, BM25 constants, page caps,
`COMPOSITION_VERSION`, `SPARSE_VERSION`, `TRUST_OK_MIN` — is a pin in code and must not become an
env var.

**Required (`config.REQUIRED_ENV`) — no fallback; a missing one is a named non-zero exit at boot:**

| Variable | Example | Decides |
|---|---|---|
| `VSIR_PORT` | `8000` | what `vsir serve` / `vsir mcp --sse` binds |
| `VSIR_QDRANT_URL` | `http://localhost:6333` | the only store |
| `VSIR_COLLECTION` | `vsir_pages` | the pages collection stem; served name is `{stem}_{dim}` |
| `VSIR_VLM` | `stub` \| `gemini` | replay or live (above) |
| `VSIR_VLM_MODEL` | `gemini-3.8-flash` | `-latest` refused (F11); a §6.3 cache-key input |
| `VSIR_EMBED_MODEL` | `gemini-embedding-2` | `-latest` refused; in the §6.6 fingerprint |
| `VSIR_PROMPT_VERSION` | `s2-v1` / `s2-v2` | a §6.3 key input — a change re-keys every fixture |
| `VSIR_API_TOKENS` | comma-separated | bearer tokens; identity is `caller-<sha256(token)[:12]>` |
| `VSIR_READ_QUOTA` | `50` | `read`s per caller per UTC day; exhausted is `429`, never a truncation |
| `VSIR_ALLOW_PAID` | `0` | the upload boundary and `test-paid.sh` only |
| `VSIR_LOG_LEVEL` | `INFO` | `DEBUG…CRITICAL` |
| `VSIR_RELEASE_ID` | `dev-0` | stamped on every run record and every response envelope |

**Optional, defaulted in code:** `VSIR_EMBED_DIM` (`1536`; in the collection name *and* the
fingerprint), `VSIR_RUNS_COLLECTION` (`vsir_runs`), `VSIR_READS_PER_QUESTION` (`3`), `VSIR_FIXTURE`
(empty — but required under `stub`), `VSIR_VLM_TIER` (`standard`), `VSIR_VLM_RPM` (`60`),
`VSIR_EMBED_TEXT_CHARS` (`2000`), `VSIR_DOC_STORE` (platform temp), `VSIR_SAFETY_DOC_TYPES` /
`VSIR_SAFETY_TOPICS` (empty), `VSIR_VLM_KEY` (empty; required under `gemini`).

**Read outside `load_config`:** `VSIR_SPOOL_DIR`, `VSIR_SYNTHETIC_PAGES`, `VSIR_LEGACY_FIXTURE`,
`VSIR_CORPUS_TRUTH`, `VSIR_TC1E_FIXTURE`, `VSIR_PILOT_PDF`, `VSIR_IMPL_ROOT`, and
`VSIR_GROUNDED_RATE_THRESHOLD` — which is read **by the report and by nothing that gates**, because
the publish bar is the `core.health.TRUST_OK_MIN` pin and adopting a threshold is a release (R4).

**Compose / scripts / console, not read by the app:** `VSIR_DOCUMENTS_DIR`, `VSIR_CONSOLE_PORT`,
`VSIR_PROMPT_VERSION_LIVE`, `VSIR_TEST_API_TOKENS`, `VSIR_TEST_READ_QUOTA`, `VSIR_TEST_FIXTURE`,
`VSIR_TEST_SOURCE`, `VSIR_TEST_CONSOLE_PORT`, `VSIR_TEST_QDRANT_URL`, `VSIR_TEST_BASE_URL`,
`E2E_API_URL`, `E2E_FIXTURE`, `VITE_API_URL`. There is no `VITE_API_TOKEN` and must not be — it
would be baked into the bundle; the token is typed into the page and lives in `sessionStorage`.

`AGENTS.md` § *Environment* carries the annotated table, with the failure mode of each.

## External state

| What | Named by | Absent → |
|---|---|---|
| **Qdrant pages collection** — one point per page: dense + `lexical` + `captions`, the §6.8 payload, `is_current`. **This collection *is* the embedding cache** (register B5) | `{VSIR_COLLECTION}_{VSIR_EMBED_DIM}` | `qdrant_unavailable`; the store-backed steps refuse *before* the first model call |
| **Qdrant control plane** — run records, per-window checkpoints, the advisory lease, the §6.3 response cache, the `kind: fingerprint` record, the `kind: budget` ledger, observed tokens. Payload-only | `VSIR_RUNS_COLLECTION` | same |
| **Document store** — the **source** PDFs, `<doc_id>@<revision>.pdf`, written at ingest step 02 | `VSIR_DOC_STORE` (host: `VSIR_DOCUMENTS_DIR`) | `503 document_not_stored` naming the document — never a blank image |
| **Fixture directories** — read-only, checked in, **not in the image** (build context is `backend/`) | `VSIR_FIXTURE` + the four eval paths | `fixture_miss` / a refusal naming the path |
| **Upload spool** — the `POST /documents` body, on disk only until the pipeline reads it | `VSIR_SPOOL_DIR` | falls back to platform temp; not one of the required twelve |
| **Gemini API** — the only dependency that costs money | `VSIR_VLM_KEY`, paced by `VSIR_VLM_RPM` | `vlm_backend_unavailable` |
| **stdout** — the event stream, one JSON object per line | — | the app never opens a log file |

**Not external state, deliberately:** page rasters are re-rendered on demand into an in-process LRU
and are never persisted (§4.2). Dropping the pages collection drops the embedding cache with it,
which is why a `SPARSE_VERSION` bump has `vsir migrate sparse` rather than a re-ingest.

## Project-Specific Notes

- **Configuration is the environment.** Never a literal, never a committed config file, never a
  secret in an image or a log line. A deployment-varying value belongs in `.env.example`.
- **One dispatcher, every surface.** HTTP, MCP (stdio and SSE) and the `vsir <tool>` one-shots all
  go through `vsir.serve.app.dispatch` with one tool table. Adding a tool is adding a row.
- **The units are documents, revisions, pages and runs — there is no chunk.** A window is a page
  range stitching deletes again; the addressable unit is the page, under the `page_id` of §5.2.
- **A model-id or prompt-version change is a fixture re-key.** Re-run
  `python -m vsir.eval.synthetic_pdf`, delete the files under the old keys, and keep the test
  environments on the same id as `.env` (dev/prod parity).
- **Test layers:** `bash scripts/test-unit.sh` (always, first) → `scripts/test-api.sh` →
  `scripts/test-e2e.sh`; `VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh` only for a unit marked
  `Spend: paid`. L0–L3 and E2E can never reach a paid API.
- Conformance greps (`bash scripts/test-unit.sh -k conformance`) enforce the rules above and must
  stay green.

<!-- OPENWIKI:START -->

## OpenWiki

See [AGENTS.md](AGENTS.md) for OpenWiki agent instructions.

<!-- OPENWIKI:END -->
