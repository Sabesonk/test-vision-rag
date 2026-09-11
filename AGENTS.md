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
| `frontend/` | React + TypeScript + Vite — the operator console (M7, U023) |
| `e2e/` | Playwright |
| `data/fixtures/` | frozen extractions, checked in |
| `data/fixtures/synthetic_pages/` | the §13 M1 corpus: hand-written page text + `expected.json` (§12.3) + `corpus_truth.json` (§12.6) |
| `data/fixtures/synthetic_3window/` | the M2a corpus's replay fixture: frozen S1 `facts/` + S2 `extract/` + `read/` (U020), keyed by §6.3 hash, + `expected.json` |
| `data/fixtures/synthetic_large/` | the M8 corpus's replay fixture: frozen S1 `facts/` + five S2 `extract/` windows + `expected.json`. 150 pages, **no contents page**, so the ladder folds at the cap and plans at Level 2 (U025) |
| `data/fixtures/legacy/` | the ported `impl` baseline of §12.1: 19 old-schema S2 responses + `labels.jsonl` / `withheld.jsonl` / `manifest.json` from `r-poc-5`, + `SOURCE.json` |
| `data/source/` | input PDFs, gitignored — except the generated `synthetic_3window.pdf` and `synthetic_large.pdf` |

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
command above reports `0 embedded, 42 reused`. **A stub run and a live run never reuse each other's
vectors**: `StubEmbedder` namespaces its model id as `stub:<model>` (`fixes/006`), so switching
`VSIR_VLM` re-embeds rather than silently reporting hash vectors as `reused`.

The §6.6 fingerprint (`{embed_model, dim, distance, composition_version, sparse_version}` — five
fields since `fixes/005`) is settled **before any vector is bought** and recorded on a `kind: fingerprint` point in the `vsir_runs` control plane, one per pages collection. Changing `VSIR_EMBED_MODEL`, `VSIR_EMBED_DIM`, the pinned `COMPOSITION_VERSION` or `SPARSE_VERSION` (which
covers `BM25_K1`, `BM25_B` and either `BM25_AVG_LEN_*` — change one, bump it) makes the next run
refuse `embed_fingerprint_mismatch` with zero points written — the remedy is a new collection plus a full re-embed plus an alias swap, never an
in-place mix:

```bash
VSIR_QDRANT_URL=http://localhost:6335 VSIR_EMBED_MODEL=some-other-embed-model \
  backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --vlm stub --until index
```

The same disagreement **refuses the boot**, which is where an operator meets it first: `vsir
doctor` and `vsir serve` run `collection_fingerprint` against that record and exit non-zero with
`failed_checks: ["collection_fingerprint"]` before a socket is bound, and `GET /ready` goes 503 if
it starts disagreeing under a running instance. A serving process writes nothing, so the ingest
guard above never fires for it — it would embed the query with one model and compare it against
vectors made by another. A collection nobody has ingested into yet has no record and boots fine:

```bash
VSIR_EMBED_MODEL=some-other-embed-model backend/.venv/bin/vsir doctor   # exit 1, named refusal
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

The M4 demo. One query narrowed to page rows carrying only `ImageRef`s, the reference dereferenced
to bytes, `fetch` with and without the pixels, a `region` crop at 400 dpi, every §7.3 bound as a
typed 400, and the raster cache proved evictable and byte-identical when cold:

```bash
bash scripts/stack.sh up                  # it runs over what this release has PUBLISHED
bash scripts/stack.sh vsir demo narrow    # a one-off container of the same image
backend/.venv/bin/vsir demo narrow --query "guard door interlocks" --limit 5
```

Unlike `demo exact --synthetic` it **seeds nothing**: `fetch` needs the source document reachable
through the store, so a demo that built its own corpus would be proving that a directory it had
just written to could be read back. With nothing published it names the command that ingests one
rather than failing as an empty result.

### The document store (U029)

Step 02 deposits the source PDF as `<doc_id>@<revision>.pdf` under **`VSIR_DOC_STORE`** — a mounted
volume, `document-store:/srv/documents` in `docker-compose.yml`, and a directory under the platform
temporary directory when the variable is unset. It is the **source**, not a raster: rasters are
still re-rendered on demand into an in-process LRU and are never written down (§4.2). Until it
existed there was nothing to re-render them *from*, so `page_id` resolved to no bytes at all.

```bash
export VSIR_DOC_STORE=/srv/documents
backend/.venv/bin/vsir documents                              # what the store holds
backend/.venv/bin/vsir documents --page 'TC1E-SF@1.3#p001'    # page_id -> bytes -> a raster
```

A document that is not there is a typed `document_not_stored` naming `doc_id@revision` and a
non-zero exit — never a blank image. A `doc_id` or `revision` that cannot be a file name (a
separator, a `..`, a leading dot) is `document_id_unsafe` at ingest, because a `page_id` can arrive
from a caller's saved citation. Bytes that disagree with the run record's `content_hash` are
`document_hash_mismatch`: the same `(doc_id, revision)` re-ingested from a corrected file would
otherwise render the new document for the previous run's still-indexed pages.

The store is what makes an **uploaded** run resumable after the instance that took it is gone — the
spool went with it, the document did not:

```bash
backend/.venv/bin/vsir ingest --resume <run_id> --steal --until publish   # no path at all
```

The PDF argument is optional with `--resume`: the run record names `doc_id@revision`, the store
resolves the file, and the `content_hash` on the record is checked before a byte is read. `--steal`
because a worker that died holding a lease does not release it (D9); that is the lease's design,
not the store's.

`vsir ingest --resume <run_id> [--steal]` continues an existing run under its own id. The lease is
**advisory** — Qdrant has no compare-and-swap — so `--resume` refuses a live lease (`lease_held`)
unless `--steal` is passed; a duplicated worker re-bills windows but cannot corrupt the index,
because `point_id` is idempotent (I1) and nothing is queryable until the gates pass (I7). A
`SIGTERM` checkpoints the run as `state: stopped` and releases the lease, which is the one state a
resume takes without `--steal`. A `SIGKILL` leaves it `running` with a lease that expires — and, in
both cases, **zero queryable pages** (F17).

A resume **buys nothing twice**. Every S2 and S1 response is read from and written to the §6.3
cache in `vsir_runs` (`vlm/cached.py`, D9), so the windows a killed run had finished come back out
of the control plane under the keys they were billed under and only the window that was in flight
can be re-billed. Step 06 checkpoints **per window** as each one returns — `running` on the way
out, `done` with its `extract_key` on the way back — which is what makes *"at most one window
lost"* a fact rather than a hope. The event stream distinguishes the two: `vlm_replay` is a call,
`vlm_cache_hit` is a call that did not happen.

```bash
export VSIR_FIXTURE=data/fixtures/synthetic_large
backend/.venv/bin/vsir ingest data/source/synthetic_large.pdf --vlm stub &   # 150 pages, 5 windows
kill -TERM %1                                            # -> state: stopped, 0 queryable pages
backend/.venv/bin/vsir runs show <run_id>                # which windows are `done`, with their keys
backend/.venv/bin/vsir ingest --resume <run_id>          # finishes; re-bills only the interrupted one
```

Regenerate that corpus with `python -m vsir.eval.synthetic_large` — the same contract as
`synthetic_pdf`: deterministic bytes, and the keys move when the model id, the prompt version, the
dpi or the S2 schema moves.

### Retiring a document (U025)

```bash
backend/.venv/bin/vsir retire <doc_id>                   # every revision stops answering
backend/.venv/bin/vsir retire <doc_id> --revision 1.3    # one revision
```

It sets `is_current=False` and **keeps every page** — deletion is not offered anywhere, over HTTP
or otherwise (§2.5 A). A retired page is what `found_only_in_superseded` reads and what an audit of
an answer already given is checked against. Idempotent (a filtered write of a constant), scoped by
construction (no filter this path builds can omit the `doc_id`), and a `doc_id` the index has never
held is a typed `run_not_found` with a non-zero exit.

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

**`--record` writes, so the path must be writable by the process that runs it.** From inside a
container `./data` is mounted **read-only**, so `--record /srv/data/fixtures/…` fails — and it fails
*after* the response is back, which on a live run is after the call is billed. Record to a
writable bind mount, or run the command on the host.

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

The two evals of §12.3 and §12.4, as commands. Both need a reachable Qdrant, neither spends and
neither has a key to spend with — they create, seed, query and drop collections of their own, and
the serving collection is never written:

```bash
backend/.venv/bin/vsir eval acceptance && backend/.venv/bin/vsir eval abstention
backend/.venv/bin/vsir eval acceptance --only parity     # synthetic | parity | real | all
backend/.venv/bin/vsir eval abstention --corpus indexed --doc-id TC1E-SF
backend/.venv/bin/vsir eval corpus                       # §12.6 + the D11 gates
backend/.venv/bin/vsir eval corpus --corpus indexed --doc-id TC1E-SF
```

`eval acceptance` prints one row per §12.3 assertion — the assertion, what the table expects, what
the index answered, `PASS`/`FAIL`/`SKIP` — in three sections. **SYNTHETIC** is the §13 M1 corpus
and always runs. **PARITY** is the baseline `impl` already paid for: §12.3's PARITY block, the
`withheld.jsonl` negative row, the **GAINS** report (which §12.3 says to *record*, so it is never
a verdict) and `NO_LEGACY_COVERAGE`. **REAL** is the pilot document: the rows that assert
`expected.json`'s faithfulness to §12.3 run today and the rows that need the M2b extraction are a
named `SKIP` until OQ-1/OQ-2 close — the skip names the three absent artefacts, and the summary
counts it, because a skip nobody notices is worse than a failure. Every expectation is read out of
a checked-in `expected.json`; neither command holds a number of its own (C10).

`eval abstention` mutates one character of codes from the observed-token inventory of the corpus
it is pointed at and reports `abstention_correctness`, which D11 fixes at **1.00** — a single leak
is a P0 stop, and the report names the leak, the real code it came from and the surface it reached.
`--corpus synthetic` (the default) seeds the M1 pages and drops them; `--corpus indexed` reads
`{VSIR_COLLECTION}_{VSIR_EMBED_DIM}` as it stands and writes nothing, which is how the number gets
measured on a real document after an ingest. A collection holding more than one document refuses
until `--doc-id` names one: a safety metric measured over an unnamed corpus is not a measurement.
A refusal prints `abstention_correctness: not measured` and exits non-zero — 0 of 0 is never 1.00.

Both are in CI on every commit (`.github/workflows/ci.yml`), named as their own step beside the
§12.4 assertions so a failure is legible in the run summary:

```bash
bash scripts/test-api.sh -k "near_miss or eval_commands or eval_corpus"
```

`eval corpus` is §12.6's report and the **D11 gates**: `code_precision` (= 1.00), `code_recall`
(≥ 0.95, blocked below 0.90), `abstention_correctness` (= 1.00), `alarm_label_hit` (≥ 0.99) and
`xref_resolve` (≥ 0.99), one row each with the measurement beside the gate, non-zero on any
failure. A `code_precision` or `abstention_correctness` shortfall prints a **P0 STOP** block
naming every offending code and page; a `code_recall` under 0.90 prints **BLOCKED**. The two
register ratios are counted over **(code, page) pairs** — the injury is the wrong page, not the
wrong code — and each row prints `1/denominator` so a set too small to evidence its own gate is
marked *underpowered* rather than read as a result.

The ground truth is a checked-in `corpus_truth.json` beside the corpus it describes
(`data/fixtures/synthetic_pages/corpus_truth.json` today), relocatable with `--truth` or
`$VSIR_CORPUS_TRUTH`, and located for `--corpus indexed` by the `corpus.doc_id` it declares rather
than by its directory name. A set the file marks `unavailable` **skips with that reason printed**
and neither fails the run nor counts as measured; a report where *every* set skipped is red,
because it produced no evidence. The command reads only — no ingest step, no model call on any
path (`vsir.vlm` is not in its import graph) — and it also re-validates R4's `grounded_rate`
publish bar against whatever is indexed and prints R7's `NO LEGACY COVERAGE` list beside the
metrics.

D11's numbers are pinned in `vsir/eval/corpus.py::D11` and may be re-baselined **once, from the
M2b measurement, with a recorded rationale** (C10) — `REBASELINED` is empty in this release. A
re-baseline missing its rationale, its measurement or the corpus it was measured on is refused, as
is one that moves nothing, one that drops under D11's blocking floor, and any attempt to lower
`code_precision`: §12.6 makes precision a safety property, not a measured target.

Neither corpus is in the image — the build context is `backend/` — so a container running these
commands mounts the fixtures and points `VSIR_SYNTHETIC_PAGES`, `VSIR_LEGACY_FIXTURE` and
`VSIR_TC1E_FIXTURE` at the mounts, exactly as `vsir demo exact --synthetic` does. A section whose
fixture is not found is a **refusal** naming the path and a non-zero exit, never a silent pass:
a skipped *row* is evidence deferred, a missing *corpus* is no evidence at all.

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

**So a model-id change is a fixture re-key, and forgetting it breaks replay for everyone.** U028
corrected `VSIR_VLM_MODEL` to the id the API actually serves and the committed fixtures stayed on
the old one, so `bash scripts/stack.sh up` refused at step 04 with `fixture_miss` while the whole
test suite stayed green — the suites carried the old id in their own environment. Re-run the
generator after any change to `VSIR_VLM_MODEL` or `VSIR_PROMPT_VERSION`, delete the files under
the old keys, and keep the test environments on the same id as `.env` (dev/prod parity, §15 X):
the responses are identical, only their names move.

The HTTP surface — `vsir serve` binds `$VSIR_PORT` and exports §7.4. The boot self-check runs
**before** anything is bound, so a floating model id, a live schema that disagrees with `INDEXED`
or a missing variable is a named non-zero exit and never a partially serving process (§4.3):

```bash
backend/.venv/bin/vsir serve                     # binds 0.0.0.0:$VSIR_PORT; --host for a laptop
export TOKEN=$(cut -d, -f1 <<< "$VSIR_API_TOKENS")

curl -s localhost:8000/health            # liveness — green even with Qdrant down, no token
curl -s localhost:8000/ready             # readiness — 503 `qdrant_unavailable` with Qdrant down
curl -s localhost:8000/metrics           # ingest_grounded_rate_median, ingest_gate_failures_total

curl -s -H "Authorization: Bearer $TOKEN" -X POST localhost:8000/tools/lookup \
     -d '{"label":"SF 1.1A"}'            # the tools of §7.2, one envelope each
curl -s -H "Authorization: Bearer $TOKEN" -X POST localhost:8000/tools/verify \
     -d '{"claims":["K73"],"page_ids":["SYN-M1@1.0#p006"]}'
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/runs/<run_id>
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/runs/<run_id>/export/labels.jsonl
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/runs/<run_id>/export/observed_tokens.jsonl
```

`vsir serve` is the only subcommand that **prints nothing**: it runs as the `web` process type, so
its stdout *is* the event stream and the contract there is one JSON object per line (§15 XI).

**Those three probes are the entire unauthenticated surface.** Auth is middleware and default
deny, so a path that does not exist yet — `POST /ask` — is already refused without a token; a
route added later is protected before it is written. `GET /pages/{page_id}/image` was that example
until U018 and is now a real route, protected by the middleware that already refused it. The identity in
the audit line and the budget ledger is `caller-<sha256(token)[:12]>`, never the token itself, so
a rotated credential is a new caller id and no log line ever held the secret (§15.1).

**Each tool has its own path** — `POST /tools/lookup`, `POST /tools/read`, and so on for all
eight of §7.2 — and every one of them is a two-line closure over the same transport, generated in
a loop **from the tool table**, so a tool cannot get a route without being in the table or be in
the table without getting a route. They exist for the description and not the dispatch: one
generic operation published an untyped body for eight tools whose parameters have nothing in
common, so `/docs` showed a single "tool_name + JSON" form and a generated client got one
`call_tool(name, dict)`. Each route now publishes its own request schema and its own §7.1
envelope.

`POST /tools/{tool_name}` is still mounted **beneath** them and is no longer published. It
catches every name the eight do not, which is the behaviour it should keep: a tool absent from
this release is a typed `404` listing what *is* served, never an empty result. Registration order
is what makes the literal paths win.

The named routes do **not** validate their own bodies, and that is the load-bearing detail. A
typed FastAPI parameter would answer a misspelt field with a `422` and a JSON pointer; §7.3
promises a code an agent can switch on, so the schema is published through `openapi_extra` and
`dispatch` stays the only validator on either transport. `test_tool_routes.py` asserts both
halves: byte-identity between a named route and the generic one, and `invalid_request` — never a
`422` — for `includeUnverified`.

One append-only audit line goes to stdout per `read` and per `fetch` and none for a free
tool; **cost is in that line and never in a response body**, where the caller gets the single
integer `reads_remaining` (§7.4). The per-caller quota is `VSIR_READ_QUOTA` reads per UTC day,
held as a `kind: budget` point in `vsir_runs` so N replicas enforce one ceiling, and exhausting it
is a `429 budget_exhausted` — never a truncated result.

Both exports are **generated from the index and streamed** — nothing is written to the instance's
filesystem and there is no file to read from it (§6.8, §15 Factor VI), so any replica serves any
run. `withheld.jsonl`, `impl`'s third file, is gone with the allowlist gate that produced it and is
a typed 404. The gauges are recomputed from `vsir_runs` on every scrape rather than counted in the
process, so two replicas agree and a restart is not a hole in the series.

**The corpus surface** — `GET /documents`, `GET /documents/{doc_id}`,
`GET /documents/{doc_id}/pages`. `POST /documents` put documents in and nothing told you what
went in: the only way to learn what the index held was to search it, so a document browser could
not be built at all. All three are queries over the two collections ingestion already writes
(register **E1**) — they compute nothing ingestion did not record and store nothing of their own,
so they cannot drift from what a search sees. Counts are `exact=True` throughout: a management
surface is where somebody decides whether an ingest was correct, and an estimated page count
short by two is indistinguishable from an ingest that dropped two pages.

Three things they deliberately show rather than tidy away. A **superseded revision is listed**,
because §6.7 keeps it (F9) and its pages are still reachable by `page_id` — `is_current: false`
with `pages: 1` is the fact an operator needs. `searchable_ratio` is on every document row, the
same number `skim_documents` reports for the same document, because at `0.00` every code on every
page is `unverifiable` rather than absent and a "not found" from that binder would be wrong.
And an unknown `doc_id` is a typed `404 document_not_found`, never a zero-page row — a document
never ingested and one whose revisions were all retired are different facts.

**All three are read-only, and nothing here retires anything.** Retirement is §6.7's and it runs
*inside* a publish, where the run record is its evidence for F12 and F9 at once. A bare "retire
this revision" endpoint would be the one call on this surface that silently changes what every
future search returns, so it is not here — `test_corpus_management.py` asserts the collection
count is unchanged after every route is called, and that `DELETE` is a `405`.

**The units are documents, revisions, pages and runs — there is no chunk.** By design: a *window*
is a page range that stitching deletes again and it never becomes a retrieval boundary
(`ingest/window.py`), and window (attention), section (semantics) and page (index) stay separate
throughout. The addressable unit is the **page**, under the `page_id` of §5.2 — which is what
`fetch`, `read` and `verify` take, so a listed `page_id` is one the tools accept (asserted).

The MCP surface (§7.5) and the one-shots (§4.4). All three call `vsir.serve.app.dispatch` — the
same table, the same validation, the same budget and the same typed refusals the tool routes
use — so there is no second code path and nothing to keep in step:

```bash
backend/.venv/bin/vsir skim pages "emergency stop reset" --scope doc_id=SYN-M1   # NARROW, §7.2.1
backend/.venv/bin/vsir skim pages --image ./panel.png --scope doc_id=SYN-M1      # D12, dense only
backend/.venv/bin/vsir skim pages "reset K158" --limit 3 --exclude "SYN-M1@1.0#p001"
backend/.venv/bin/vsir skim documents "emergency stop reset"          # which binder? §7.2.1
backend/.venv/bin/vsir skim sections "emergency stop reset" --scope doc_id=SYN-M1  # which chapter?
backend/.venv/bin/vsir resolve "Page 8 of 55" --doc-id SYN-M1                    # FOLLOW, §7.2.3
backend/.venv/bin/vsir lookup "SF 1.1A"                      # JUMP, §7.2.2
backend/.venv/bin/vsir lookup "alarm 152" --json | jq        # the envelope, verbatim
backend/.venv/bin/vsir lookup "SF 9.9" --scope page_no=5 --include-unverified
backend/.venv/bin/vsir verify --claims K73 --pages "SYN-M1@1.0#p006"     # CHECK, §7.2.4
# LOOK (§7.2.5) — needs a document store, so an INGESTED corpus, not the M1 one
backend/.venv/bin/vsir fetch --pages "synthetic-3window@1.0#p019,synthetic-3window@1.0#p021"
backend/.venv/bin/vsir fetch --pages "SYN-M1@1.0#p001" --include text,summary   # no store needed
backend/.venv/bin/vsir fetch --pages "synthetic-3window@1.0#p019" --dpi 400 --region 0,0,1,0.55
# COMPREHEND (§7.2.6) — the ONE tool that spends. Free here only because VSIR_VLM=stub replays a
# frozen response by `read_key`; with VSIR_VLM=gemini this call bills. No --dpi: it is pinned at
# 220 server-side because it is a `read_key` input (§6.3), so a caller cannot vary it.
backend/.venv/bin/vsir read --pages "synthetic-3window@1.0#p019,synthetic-3window@1.0#p020" \
  --question "what must be true before the guard door interlock releases?"

backend/.venv/bin/vsir mcp --stdio     # one client on a pipe; stdout is JSON-RPC, events on stderr
backend/.venv/bin/vsir mcp --sse       # == `vsir serve`: the SSE transport binds $VSIR_PORT
```

`--scope` is repeatable `KEY=VALUE` and its values are read as Python literals, so `page_no=5`
filters on the integer the payload holds. A key outside `INDEXED` is a typed `400`
(`filter_unknown_key`) here exactly as it is over HTTP.

**`skim pages` needs a collection with vectors.** It is the first tool that reads one, so a corpus
seeded by `vsir demo exact --synthetic` (payloads only, §13 M1) answers it with `not_found` — use
`bash scripts/stack.sh up`, which ingests the 42-page generated corpus through the real pipeline.
`--image` takes a path and is sent base64 over the same JSON body an MCP client uses; with no query
text beside it the two sparse branches are skipped and every row's `why` is `["dense"]` (D12).
`--limit` is 1…25 and **truncates** the fused list rather than re-ranking it, so the first three
rows of a ten-row skim are the three rows of a three-row skim.

**`skim documents` and `skim sections` run the same search and group it** — one `_candidates()`
call, grouped by `doc_id` or by `section_id`, so their rows can never disagree with `skim pages`
about what matched. They take no `--limit`: ten groups, and a caller who wants rows wants
`skim pages`. Two things to expect from `skim documents` and nowhere else: `searchable_ratio` on
every row, and **a row for a binder with no text layer at all even when nothing in it matched**
(`pages_matched: 0`, `best_rank: 0`), because a query carrying a printed code excludes every page
of such a binder from every branch and its silent absence is what F4 is about. Both rungs carry
`next.expand` — the dict to hand the next rung down as its `--scope`.

`resolve` takes the label **as printed** — `"8"`, or the citation `"Page 8 of 55"`, whose
digit-bearing words are probed as labels in their own right when the citation as typed matches
nothing. An ambiguous label returns **every** candidate (F5); narrow with `--doc-id`.

**`fetch` and `GET /pages/{page_id}/image` need `VSIR_DOC_STORE` to hold the source PDF.** Rasters
are never persisted (§4.2) — they are re-rendered on demand into an in-process LRU — so the bytes
have to come from the document store U029 writes at ingest step 02. A page that is indexed but
whose document is not on that volume is a **503 `document_not_stored`**, not a 404: the citation
is fine and a volume is missing. Dropping `"image"` from `--include` needs no store at all and
renders nothing, which is the cheap text/summary read.

The dpi tiers are `{36, 72, 150, 220, 300, 400}` and anything **above 220 requires `--region`** —
a full page at 400 dpi is 15 megapixels. `--region` is `x0,y0,x1,y1` normalised to the page.
Every §7.3 bound is a typed 400 naming what it broke (`fetch_budget_exceeded` carries `bound`,
`limit` and `requested`), never a clamp and never a truncated page list. The URL a row hands back
percent-encodes the `#` of a `page_id` — `/pages/SYN-M1@1.0%23p001/image?dpi=150` — because a bare
`#` is a fragment delimiter and the server would only ever see `/pages/SYN-M1@1.0`.

**A typed absence exits 0.** `vsir lookup "alarm 152"` searched, found nothing and said so
correctly — that is a successful call (§7.1), which is what lets the §4.4 demo chain with `&&`.
Only a refusal (a `400` naming a bound, a `404`, a `503`) is a non-zero exit.

**`--json` makes stdout the envelope and nothing else** — the event stream moves to stderr, which
is the same rule `vsir mcp --stdio` follows and for the same reason: a flag that declares stdout
the machine surface makes a perfectly good `boot_check_ok` a parse error at whatever is reading it
(§15 XI). The events are *separated, never silenced*, so a boot refusal is still reported in full
on stderr. Without `--json` the output is a human rendering and stdout stays the event stream.
Byte-identity with `POST /tools/{name}` is asserted for six calls and both typed refusals in
`backend/tests/api/test_one_shot_parity.py`.

**MCP over SSE is not a second server.** §15 Factor VII pins it to the serving port, so
`vsir serve` mounts `GET /sse` and `POST /messages/` beside the HTTP tools and `vsir mcp --sse`
runs that same app. Both paths are behind the same default-deny middleware: they need a bearer
token, because the socket is the boundary. **stdio does not** — it is a one-off process of this
release (Factor XII) spawned by its own client over a pipe, and its identity in the audit line and
the budget ledger is `local-mcp-stdio`, beside `local-cli` for the one-shots and
`caller-<digest>` for a network caller. An operator who can run `vsir mcp --stdio` can already run
`vsir publish`; a credential read from the same environment the server reads would be ceremony.

**The corpus is on MCP as resources, not as a ninth tool.** §7.5 fixes the tool surface at *the
same eight tools* as HTTP, and that is a statement about what an agent chooses between: the eight
are **moves**, and an agent picking among nine where one of them is "list the corpus" is choosing
between a search and a filing cabinet. MCP already has the right concept — a resource is context a
client reads and attaches, not an action the model decides to take. So `resources/list` serves one
concrete resource, `vsir://corpus`, and declares `vsir://documents/{doc_id}` and
`vsir://documents/{doc_id}/pages` as **templates** a client fills from the ids it found there:
`resources/list` stays O(1), and a thousand-binder corpus does not put a thousand entries in a
client's picker. `tool_definitions` is untouched and `test_mcp_resources.py` asserts the table is
still eight.

They resolve through `serve/manage.py` — the very functions the HTTP routes call — so reading
`vsir://corpus` is **byte-identical** to `GET /documents`, and the import-graph rule that keeps
`tools/call` honest still holds: no filter, no count and no scroll anywhere in `mcp/server.py`.

The `tools/call` result is **byte-identical** to the HTTP response body for the same request, on
both transports — one serialiser (`vsir.serve.envelope.wire`), one dict. To check it by hand,
remembering that MCP requires the `initialize` handshake first and that the SDK cancels in-flight
work on stdin EOF (hence the trailing `sleep`, which a real client does not need):

```bash
{ printf '%s\n' \
   '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"demo","version":"0"}}}' \
   '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
   '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"lookup","arguments":{"label":"SF 1.1A"}}}'; sleep 2; } \
  | backend/.venv/bin/vsir mcp --stdio 2>/dev/null | tail -1
```

The tool descriptions and the input schemas an MCP client sees are generated from the release's
own tool table: the schema is each tool's Pydantic request model, so `extra="forbid"` is
advertised and a parameter cannot reach one surface without reaching the other.

### The runner (U021, U022)

`vsir ask --explain` runs the free half of §8 — the descent, the tri-state triage and the route —
against whatever this release has published. It spends nothing on any path, and the last step is
the evidence rather than the claim: a spy counts the tools that were dispatched, refuses the VLM
backend outright, and reports `reads_remaining` off every envelope that came back.

```bash
backend/.venv/bin/vsir ask --explain "the carton discharge won't restart after an E-stop reset"
backend/.venv/bin/vsir ask --explain --no-vision "…"   # a text-only caller: the route becomes `read`
backend/.venv/bin/vsir ask --explain --prompt "…"      # also print the system prompt
```

Eight steps: `skim_documents` → `skim_sections` → `skim_pages`, each descending with the previous
rung's `next.expand`; then the triage table (mark, reason, `why`, `grounded_rate`, `text_trust`
and the query terms the summary actually showed); the `exclude` set, **proved by re-skimming with
it**; the route per candidate; the state machine's transitions; and the spend spy. It needs a
reachable Qdrant and a collection with vectors — `bash scripts/stack.sh up` — and no credential.

Three things the output is worth reading for:

- **`irrelevant` is the only mark that becomes `exclude`.** The `uncertain` pool is printed beside
  it and is deliberately not excluded: it is what a `sufficient: false` drains before anything
  widens the scope (§8.2 safeguard 1), and step 07 prints that transition out of the shipped
  table rather than describing it.
- **≤ 3 candidates are never filtered** (safeguard 2), so a narrow descent legitimately shows
  every row `relevant` with reason `small_set`.
- **The default route is `fetch`** (§8.1a) — `read` appears only for a caller that cannot see or a
  context that cannot hold another raster, and `--no-vision` is how to see that branch. A page
  past the route's cap is reported `deferred_over_cap`, which is a second call the runner may
  make, not a truncation.

An empty triage is not a refusal — it prints §8.1's coverage branch (`empty_no_text` → look at
the image-only pages, `empty_searchable` → abstain naming what was searched) and exits 0.

#### `vsir ask` without `--explain` — the whole loop, and the one path in this CLI that spends

```bash
backend/.venv/bin/vsir ask "why won't the guard door interlock release when K119 is monitored"
backend/.venv/bin/vsir ask --scope doc_id=TC1E-SF "…"      # narrow every rung
backend/.venv/bin/vsir ask --exclude 'doc@1.0#p003' "…"     # pages you have already rejected
```

It prints the move-by-move trace — `descend → triage → look → draft → verify`, with `$` on the
one move that bills — then the gated answer with a badge per code, or the abstention with its
coverage numbers, then three assertions read off the outcome: every rendered code has a
`(claim, page)` check behind it, no rejected code is anywhere in the output, and the read budget
was respected. Exit 0 on an answer **or** an abstention; non-zero on a typed refusal.

Two ceilings bound it, both the server's: `VSIR_READS_PER_QUESTION` (default 3) per question and
`VSIR_READ_QUOTA` per caller per UTC day. A question that needs a second look when the first is
exhausted is `429 budget_exhausted` — a refusal, never an answer from pages the model said did
not answer.

**`POST /ask` is the same loop over HTTP** (bearer, §7.4) and is the only route in the release
that may return prose — asserted by scanning every route's published 200 schema. Its body is
`{question, scope?, exclude?, draft?}`:

```bash
curl -s localhost:8055/ask -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"question":"why won'"'"'t the guard door interlock release when K119 is monitored"}' | jq .
```

`draft` is the other half of §8.1a: a **vision-capable caller** that looked at the rasters itself
(`fetch`, free) sends its draft — `{text, claims:[{code, page_ids}], pages}` — and the identical
gate runs on it, per `(claim, page)`, before a word of it is rendered. Nothing is searched and
nothing is spent on that path; the route comes back as `fetch`. The eight MCP tools are
deliberately still eight (§7.5): an MCP client *is* the agent, so it drives the ladder itself with
the system prompt `--prompt` shows and brings its draft back through `POST /ask` to be gated.

Reading a trace: `route` is `read` on every loop-driven answer, because the party that drafts
there is this process, which cannot look at a raster (§8.1a's *"or when the caller is not
vision-capable"*). A rejected draft renders **nothing** — not the code, not the sentence — and
the rejection discloses only the page and `present_instead`. `"not in these documents"` cannot
appear while `pages_no_text_read < scope_stats.pages_no_text`, which the composer enforces on the
string it just built (§8.5).

The M6 demo, over the generated corpus in replay (no credential, no spend):

```bash
export VSIR_QDRANT_URL=http://localhost:6335 VSIR_COLLECTION=vsir_demo_m6 \
       VSIR_RUNS_COLLECTION=vsir_demo_m6_runs VSIR_DOC_STORE=/tmp/vsir-m6-store \
       VSIR_FIXTURE=data/fixtures/synthetic_3window VSIR_VLM=stub
backend/.venv/bin/vsir ingest data/source/synthetic_3window.pdf --vlm stub
backend/.venv/bin/vsir ask "why won't the guard door interlock release when K119 is monitored"
backend/.venv/bin/vsir ask "which contactor does the interlock relay K120 switch"   # the gate rejects
```

**The questions are not arbitrary and must not be paraphrased.** Each one names a code the corpus
prints, so the handle branch resolves the page set on the exact surface and the `read` that
follows lands on a response frozen under exactly that `(pages, question)` key
(`vsir.eval.synthetic_pdf.READ_CASES`). Reword the question and replay is a typed `fixture_miss`,
which is D10 working: add a case to the generator and re-run `python -m vsir.eval.synthetic_pdf`.


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

### E2E (U024)

`bash scripts/test-e2e.sh` brings up the whole stack behind the compose `e2e` profile — Qdrant on
`6335`, the backend on `8001`, one-off `test-init` and `test-seed` admin runs of the **same
image**, then the console on `5174` — waits for `GET /ready`, runs Playwright headless and tears
down with `down -v`. `--up` leaves it running; any other argument reaches `playwright test`
(`--headed`, `--debug`, a file name).

```bash
bash scripts/test-e2e.sh                      # up → seed → test → down -v
bash scripts/test-e2e.sh --up                 # leave it running, then: cd e2e && npx playwright test
bash scripts/test-e2e.sh badges.spec.ts       # one file
npm --prefix e2e install && npx --prefix e2e playwright install chromium
```

Four operational things worth not rediscovering:

- **`VSIR_TEST_CONSOLE_PORT` exists for a port collision.** 5174 is §4.2's pin and the default; if
  another project on the machine already publishes it, set this and the script threads the value
  through the compose mapping, its own readiness wait and `PLAYWRIGHT_BASE_URL`. The suite asserts
  the *declared default* is still 5174.
- **`VSIR_TEST_FIXTURE` moves the whole run to another corpus** (`/srv/data/fixtures/TC1E-SF` when
  OQ-1 is answered). The script derives the host-side `E2E_FIXTURE` from it, and no assertion in
  `e2e/tests/` names a page, a code or a question: they are read from `GET /documents`,
  `GET /documents/{doc}/pages` and the fixture's own `expected.json`.
- **`VSIR_TEST_READ_QUOTA` is raised to 500 for E2E** and stays 10 for L2/L3. A browser run asks
  several whole questions and each may spend three reads; the ceiling itself is exercised on its
  own instance in `tests/api/test_read_caps.py`.
- **`tests/outage.spec.ts` really stops the Qdrant container** and restarts it in an `afterAll`.
  That is why `playwright.config.ts` pins `workers: 1`.

**A `fixture_miss` in an E2E run is usually a page *order*, not a missing response.** `read_key` is
over the rasters and the question, and the dpi-220 renders are byte-identical everywhere — but the
dpi-150 raster that feeds the *embedding* goes through Pillow, whose PNG bytes differ between the
macOS wheel and the Linux one. Different bytes, different stub vector, and a near-tie in a dense
ranking can come out in the other order: `skim_pages(has_text=False)` returns `[p001, p002]` in the
container and `[p002, p001]` in the host-run L2 suite, so the loop asks for a page set nobody
froze. Nothing in `e2e/tests/` depends on that ordering — the paid-route test reads a single page,
and the abstention test spends nothing at all.

## Frontend

The console is a Vite app in `frontend/`, and it is **same-origin by proxy** rather than by CORS:
the service has no CORS middleware and must not grow one, so `vite.config.ts` proxies the API
paths to `VITE_API_URL` (default `http://localhost:8000`). That is a *proxy target*, not a base
URL the browser sees — which is why `image.url` works exactly as the service sends it (relative),
and why the container's `http://backend-test:8000` is correct inside the test network.

```bash
npm --prefix frontend install
npm --prefix frontend run dev        # 5173, proxying to VITE_API_URL
npm --prefix frontend run build      # tsc --noEmit, then the production bundle
npm --prefix frontend test           # vitest, L0 — no Docker, no network
npm --prefix frontend run typecheck
```

`scripts/test-unit.sh` runs `vitest` and `tsc --noEmit` after the backend suite, so the frontend is
part of Layer 0/1 and not a separate thing to remember.

**The token is typed into the page**, never built into the bundle: a `VITE_API_TOKEN` would be
substituted at build time and shipped to every browser that loaded the app. It lives in
`sessionStorage` for the tab. Every route is bearer-authenticated including the page rasters, so
an `<img src>` cannot load one — `hooks/useRaster.ts` fetches with the header and mints an object
URL instead.

Two rules of §16 have no compiler behind them and are enforced by `src/conformance.test.ts`
instead: **no written `any`**, and **no raw hex colour in a component** (`src/styles.css` is the
one file allowed to name a colour; components ask for a `Tone`). It also refuses `inline: true`
and any read of `bytes_b64` outside the type that declares `fetch` may carry one.

`backend/tests/unit/test_frontend_client_contract.py` compares `frontend/src/api/types.ts` against
the Pydantic models field for field, **in both directions**, plus `SCHEMA_VERSION` and the badge
wording. Add a field to an envelope and not to its interface — or the reverse — and L0 fails on
that commit.

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
| `backend-test` | `8001` → 8000 | same image as production, `command: ["serve"]`, env and ports differ |
| `frontend-test` | `5174` → 5173 | behind the `e2e` compose profile; the image is U024's |

The test stack's bearer token is `${VSIR_TEST_API_TOKENS:-test-only-not-a-secret}` — deliberately
**not** `VSIR_API_TOKENS`. Compose interpolates from `.env`, which is where a developer's real
token lives, so reading the production variable made the stack's credential whatever happened to
be in an untracked file. `tests/api/conftest.py::CONTAINER_TOKEN` resolves the same name; override
both or neither.

Dev ports, for reference: backend `8000`, Qdrant `6333` REST and `6334` gRPC, frontend `5173`.

## Conventions

- **Configuration is the environment.** A deployment-varying value is an env var in `.env.example`;
  never a literal, never a committed config file, never a secret in an image or a log line.
  `VSIR_SAFETY_DOC_TYPES` and `VSIR_SAFETY_TOPICS` are the §6.8 export's two sources for
  `safety_flag`; both default to empty, and a list compiled into the image would be the keyword
  taxonomy §6.8 deletes.
- **One dispatcher, every surface.** HTTP, MCP (stdio and SSE) and the `vsir <tool>` one-shots all
  go through `vsir.serve.app.dispatch` with the release's one tool table. Adding a tool is adding
  a row to `tool_table()`; a wrapper that re-validated, re-capped or re-classified anything would
  be the second code path §7.5 forbids.
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
