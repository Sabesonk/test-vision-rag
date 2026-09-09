# CR1 Implementation Progress

**Plan:** `development/cr1/plan/cr1-implementation-plan.md`
**Release tag:** (pending — set when all units are [x])

## Rollup

| | |
|---|---|
| **Complete** | 5 / 26 units (19%) |
| **Current milestone** | M1 — `core/` and the exact surface (3 / 4 units); M0 closed and tagged |
| **Next unit** | U006 — `verify_claims`, `present_instead`, and the L3 abstention eval |
| **Blocked** | none |

---

## Units

<!-- Claude updates this file after each unit. Format:
  - [ ] U001 Not started
  - [~] U002 In progress
  - [x] U003 Complete
  - [!] U004 Blocked — reason
  Record the demo command's output under "Demo evidence" when a unit completes. -->

### M0 — skeleton, pins, harness (spend: none)
- [x] U001 Runtime skeleton, pins, and `vsir doctor`
- [x] U002 Qdrant test harness, probes, and conformance greps

### M1 — `core/` and the exact surface on synthetic text (spend: none) — the whole proof
- [x] U003 Page record, identifiers, and the `INDEXED` schema
- [x] U004 Tokenisation, variants, the exact filter, and both envelopes
- [x] U005 Synthetic exact surface, `lookup`, and `vsir demo exact`
- [ ] U006 `verify_claims`, `present_instead`, and the L3 abstention eval

### M2a — ingest a generated PDF with a stubbed VLM (spend: none)
- [ ] U007 Manifest, probe, render, S1 facts, and the windowing ladder
- [ ] U008 The VLM boundary, cache keys, replay mode, and S2 extraction
- [ ] U009 Derivation, health signals, label attribution, and stitching
- [ ] U010 Embedding, the three surfaces, the fingerprint, and indexing
- [ ] U011 Gates, publish, retirement, the run control plane, and exports

### M2b — ingest the pilot PDF; freeze the fixture (spend: S2 + embed, once)
- [ ] U012 Port the paid-for `impl` fixtures and the parity / negative sets — spend: none
- [ ] U013 The one paid `TC1E-SF` ingest and the `grounded_rate` baseline — spend: paid

### M3 — `lookup` + `verify` over HTTP and MCP (spend: none)
- [ ] U014 The serving app — auth, audit, budget, and degradation
- [ ] U015 `lookup` and `verify` over HTTP and MCP
- [ ] U016 `vsir eval acceptance` and `vsir eval abstention`

### M4 — `skim_pages`, `fetch`, `resolve` (spend: none)
- [ ] U017 `skim_pages`, deterministic fusion, image queries, and `resolve`
- [ ] U018 The page-image endpoint, the raster cache, and `fetch`

### M5 — the ladder rungs and `read` (spend: read)
- [ ] U019 `skim_documents`, `skim_sections`, and `searchable_ratio` — spend: none
- [ ] U020 `read` — the paid step, with stamped codes and a question-keyed cache — spend: paid

### M6 — the runner, the loop, the answer gate (spend: read)
- [ ] U021 Tri-state triage, the safeguards, and fetch-vs-read routing — spend: none
- [ ] U022 The loop, the six correction loops, the answer gate, and `POST /ask` — spend: paid

### M7 — operator console (spend: none, fixture-backed)
- [ ] U023 The operator console — viewer, agent panel, trust badges
- [ ] U024 The Playwright replay suite and `scripts/test-e2e.sh`

### M8 — revisions, resumable ingest, scale-out (spend: ingest)
- [ ] U025 Revisions, resumable ingest, and graceful shutdown — spend: none
- [ ] U026 `vsir eval corpus` — the §12.6 report and the D11 gates — spend: paid

---

## Unit detail

### U001 — Runtime skeleton, pins, and `vsir doctor`

**Milestone:** M0 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-09

**Demo output** — `vsir doctor && VSIR_VLM_MODEL=gemini-pro-latest vsir doctor; echo "exit=$?"`
(run after `set -a && . ./.env && set +a`; key lines, the full stream is 6 JSON events per
invocation):

```json
{"event": "doctor_ok", "failed_checks": [], "release_id": "dev-0", "python": "3.11.15",
 "models": {"VSIR_VLM_MODEL": "gemini-3.8-flash-001", "VSIR_EMBED_MODEL": "gemini-embedding-2"},
 "fingerprint": {"embed_model": "gemini-embedding-2", "dim": 1536, "distance": "cosine",
                 "composition_version": "d4-fused-v1"},
 "fingerprint_id": "45a09c588c25422c", "pages_collection": "vsir_pages_1536",
 "runs_collection": "vsir_runs", "dpi_index": 150, "dpi_answer": 220, "vlm": "stub", "level": "info"}
first-exit=0
```

```json
{"event": "boot_check_failed", "check": "model_ids_pinned", "level": "error", "release_id": "dev-0",
 "detail": "model id ends in -latest: VSIR_VLM_MODEL=gemini-pro-latest — pin the version (§4.3, F11)",
 "floating": {"VSIR_VLM_MODEL": "gemini-pro-latest"}, "suffix": "-latest"}
exit=1
```

`VSIR_EMBED_MODEL=gemini-embedding-latest` refuses identically. `bash scripts/test-unit.sh` →
**69 passed**, Layer 1 PASSED.

Container facts (`docker build -t vsir:dev-0 -f backend/Dockerfile backend`):

```
id            -> uid=10001(vsir) gid=10001(vsir)
--read-only   -> touch: cannot touch '/srv/x': Read-only file system
image config  -> user=10001 entrypoint=[vsir] cmd=[doctor]
in-image      -> python 3.11.16, doctor_ok, exit 0; with no env, doctor_refused, exit 1
```

**Invariants / failure rows closed:** **F11 (boot half)** — a resolved model id ending `-latest` is
refused at boot, named, non-zero (`test_doctor_refuses_latest_model_alias`, both model variables).
Spec §20.1 register item **B6** closed. No invariant is asserted at M0 (Spec §9 assigns none).

**Notes**

- **The three live-collection refusals of §4.3 are not here, by design.** Payload schema vs
  `INDEXED`, the collection fingerprint and `phrase_matching` on `text`/`vlm_codes` all read a live
  collection, and `core/indexed.py` is U003's deliverable — plan U003 says so explicitly
  ("`doctor.py` — **extended**: the `--create-collection` flag and the live-schema assertion").
  `doctor.BOOT_CHECKS` is the extension point: one ordered check list, run identically by the CLI
  and by server start (U014), so the two cannot drift.
- **All twelve Factor III variables are required, with no code-side default** — including
  `VSIR_PORT`, which §15 describes as "default 8000". U001's acceptance criterion is that unsetting
  any one of the twelve makes `doctor` exit non-zero naming it, and a default would defeat that. The
  port number itself is documented in `.env.example`.
- **The app does not read `.env`.** Loading a file from the working directory is the shape §15.2
  bans, so the operator loads it (`set -a && . ./.env && set +a`) and `docker run --env-file` does
  the same. `.env` was committed (empty) at init; it is now gitignored and untracked.
- **`VSIR_VLM_KEY`** is the VLM credential's variable name, required only when `VSIR_VLM=gemini` so
  replay mode (D10) runs in CI with no key. Named `VSIR_VLM_KEY` rather than `GEMINI_API_KEY` to keep
  the interface provider-agnostic and to keep the literal `api_key=` out of the tree, which is one
  of the §12.5 cloud-native greps U002 writes.
- **`VSIR_VLM_MODEL=gemini-3.8-flash-001` in `.env.example` is a shape, not a verified id.** §4.2
  names "the pinned id for Gemini 3.8 Flash" without giving the literal. Confirm the exact dated
  suffix against Google's model list before U013's paid ingest. Boot refuses a `-latest` escape
  hatch, so an operator cannot dodge the pin.
- **Two extra optional variables** beyond the spec's named set, both documented in `.env.example`:
  `VSIR_EMBED_DIM` (feeds the collection name and the fingerprint — §6.6) and
  `VSIR_RUNS_COLLECTION` (the D9 control plane).
- **`pytest-cov` added to `backend/requirements-dev.txt`** — test-only, and only because the
  existing `scripts/test-unit.sh` passes `--no-cov`, which pytest rejects as an unknown flag
  without it. Coverage stays off.
- **`scripts/test-unit.sh` does not forward `"$@"`,** so the plan's
  `bash scripts/test-unit.sh -k "doctor or json_log or sigterm_boot"` silently runs the whole
  suite. Harmless here (69/69 green, strictly stronger than the filter) — **U002 owns the fix**
  when it extends the script.
- **`impl` is at `/Users/sabesonk/Documents/VisionRag/dilmah-engineering-solutioning/poc/vision_segmentation_index_and_retrieval/impl`** —
  four levels up from this repo, not the three the build prompt states. U002 records it in
  `AGENTS.md`.
- **Local toolchain:** the machine's Python is 3.14 and the pin is 3.11, so the venv is
  `backend/.venv` built by `uv venv --python 3.11`. Activate it before the test scripts, which call
  a bare `python`. U002 records this in `AGENTS.md`.

---

### U002 — Qdrant test harness, probes, and conformance greps

**Milestone:** M0 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-09

**Demo output** — the plan's command, run in full:

```
$ docker compose -f docker-compose.test.yml up -d --build --wait test-qdrant backend-test
 Container ...-test-qdrant-1   Healthy
 Container ...-backend-test-1  Healthy
$ bash scripts/test-unit.sh
92 passed in 0.34s
Layer 0/1 PASSED
$ curl -s -o /dev/null -w "health=%{http_code}\n" localhost:8001/health
health=200
$ docker compose -f docker-compose.test.yml stop test-qdrant
 Container ...-test-qdrant-1 Stopped
$ curl ... /health   -> health=200          # liveness survives the outage
$ curl ... /ready    -> ready=503           # readiness does not
$ curl -s localhost:8001/ready
{"status":"not_ready","release_id":"test","reason":"qdrant_unavailable",
 "checks":{"required_env":"ok","model_ids_pinned":"ok","config_valid":"ok",
           "python_runtime":"ok","dependencies":"ok","qdrant_reachable":"fail"}}
```

`bash scripts/test-api.sh` → **8 passed** (L2, against `qdrant/qdrant:v1.19.0` on 6335 and the
image on 8001).

Gate proofs, run at the shell as the acceptance criteria word them:

```
inject `entity_keys` in backend/vsir/serve/_scratch.py -> test-unit.sh exit=1 (5 rules fired)
remove it                                              -> test-unit.sh exit=0
inject `logging.FileHandler` in backend/vsir/          -> exit=1, test_the_app_never_opens_a_log_file
add every banned string to backend/vsir/NOTES.md       -> exit=0   (markdown is out of scope)
bash scripts/test-paid.sh                              -> exit=1, "REFUSED: VSIR_ALLOW_PAID is not 1"
VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh            -> exit=1, "REFUSED: VSIR_VLM_KEY is not set"
```

**Invariants / failure rows closed:** none owned (this unit is the mechanism by which others stay
closed). Spec §20.1 register item **E6** — *no tests at all* — closed: 92 L0/L1 + 8 L2, and the
§12.5 conformance set is executable.

**Notes**

- **The conformance suite is 24 tests, not a shell script.** Each rule names the invariant it
  protects, so a failure explains itself. Three deliberate strengthenings beyond §12.5's literal
  list, each commented in the file: `requirements.lock` is scanned as well as `requirements*.txt`
  (a fuzzy library would arrive transitively, and the lock is the only file that would show it);
  `difflib`/`SequenceMatcher`/`get_close_matches` are banned in code because the stdlib needs no
  requirement; and an **untagged** image is treated as `latest`, because it is.
- **The `score` grep is declaration-shaped** (`score:`, `score =`, `score = Field(`, `"score"`),
  not the bare word — otherwise no docstring could explain why the field is banned. Same reasoning
  for the `-latest` pattern, which requires a quoted *model id*, so `doctor.py`'s
  `FLOATING_SUFFIX = "-latest"` (the constant that implements the refusal) is not a violation of it.
- **`/health` and `/ready` are in `serve/app.py`, adapted from `impl/app/main.py`.** What survived
  is that module's discipline of keeping distinct failures distinct; what did not is the `200`-empty
  abstention, the combined `/api/health`, the HTML UI and the unauthenticated surface.
  `create_app(env)` is a factory, so importing the module has no side effect and a test can point
  an instance at a different Qdrant without touching `os.environ`.
- **The app does not wait for Qdrant at start-up.** `impl` blocked for up to 60 s. Readiness is
  what gates traffic, so the process starts immediately and reports itself unready until Qdrant
  answers — which is also what makes start-up have no warm-up requirement (§15.2).
- **`doctor.py` gained `BootRefused` + `assert_boot_ok`** so `vsir doctor` (exit code) and server
  start (exception, before the port is bound) run the identical `BOOT_CHECKS`. A configuration the
  CLI refuses cannot be one the server accepts.
- **U003 must add a third check status.** When the live-collection checks join `BOOT_CHECKS`,
  "Qdrant unreachable" must not read as "the schema is wrong": a refusal on unreachability turns an
  outage into a restart loop, which is the exact failure §15.1 forbids. So `CheckResult.status`
  needs `unavailable` alongside `ok`/`fail`, with **boot refusing on `fail` only** and **`/ready`
  red on either**. `serve/app.py::ready` already has the comment marking where it lands.
- **`vsir serve` is U014's**, so the test stack's `backend-test` overrides the entrypoint to
  `uvicorn --factory vsir.serve.app:create_app`. Same image, same release, same code path — only
  the command differs, and U014 replaces it with the subcommand.
- **`frontend-test` is behind the compose `profiles: ["e2e"]`** until M7 creates `frontend/`:
  `docker compose up -d` must not fail on a build context that does not exist.
  `scripts/test-e2e.sh` passes `--profile e2e`.
- **`pyproject.toml` now discovers packages with `include = ["vsir*"]`.** The explicit
  `packages = ["vsir"]` shipped an image without `vsir.serve` — the editable install hid it, the
  container found it. Every later subpackage is covered.
- **`scripts/test-unit.sh` forwards `"$@"`** (the gap noted in U001), prefers `backend/.venv`, and
  exports `VSIR_VLM=stub VSIR_ALLOW_PAID=0` so no test can reach a paid API. `test-api.sh` passes
  `VSIR_TEST_QDRANT_URL`/`VSIR_TEST_BASE_URL` to the host-side tests.
- **`/metrics` is not here.** §7.4 lists it and §11.4 defines it, but the plan scopes this unit to
  health/ready; it belongs with U014's audit and observability work.

---

### U003 — Page record, identifiers, and the `INDEXED` schema

**Milestone:** M1 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-09

**Demo output** — `docker compose -f docker-compose.test.yml up -d test-qdrant && vsir doctor
--create-collection && vsir doctor` (with `VSIR_QDRANT_URL=http://localhost:6335`):

```json
{"event": "collection_created", "collection": "vsir_pages_1536", "dim": 1536,
 "fingerprint_id": "45a09c588c25422c",
 "vectors": {"dense": {"size": 1536, "distance": "Cosine"}},
 "sparse_vectors": {"lexical": {"modifier": "idf"}, "captions": {"modifier": "idf"}},
 "payload_indexes": {"text":      {"type": "text", "phrase_matching": true,
                                   "tokenizer": "word", "lowercase": true, "min_token_len": 1},
                     "vlm_codes": {"type": "text", "phrase_matching": true,
                                   "tokenizer": "word", "lowercase": true, "min_token_len": 1},
                     ... 16 payload indexes in all}}
create-exit=0

{"event": "boot_check_ok", "check": "collection_schema", "collection": "vsir_pages_1536",
 "detail": "vsir_pages_1536 matches INDEXED (16 keys)", "dim": 1536}
doctor-exit=0
```

Then the refusal the plan's demo asks for — drop the `text` payload index and re-run:

```json
{"event": "boot_check_failed", "check": "collection_schema",
 "detail": "live schema disagrees with INDEXED: payload index missing: 'text' (text)"}
doctor-exit=1
```

`bash scripts/test-unit.sh` → **153 passed**. `bash scripts/test-api.sh` → **28 passed**, script
exit 0, stack torn down and volume wiped.

**Invariants / failure rows closed:** **I6** asserted — one `INDEXED` dict creates the payload
indexes, gates every filter (`reject_unknown_keys`) and is asserted against the live collection at
boot (`check_collection_schema`), by both `vsir doctor` and server start. Spec §20.1 register items
**A5** (there is no `image_path` field) and **B1/B4** (provenance is a first-class field group)
closed. F10 stays open until U004's filter gate consumes the dict, as the plan says.

**Notes**

- **This unit closes M0's acceptance gap.** Spec §13 M0 requires "doctor refuses … a missing
  payload index, naming the reason", but the refusal needs `INDEXED`, which the plan assigns to
  U003 in M1 — and Spec §13 M0 simultaneously forbids creating a module before the milestone that
  implements it. The M0 verification subagent confirmed the miss against commit `922bc3f`. Rather
  than tag a milestone whose acceptance list was not met, `cr1-m0` is tagged **after** this unit,
  and the M0 demo was re-run against the finished check. Recorded as a milestone-boundary
  correction, not a spec change: no requirement was weakened.
- **The check has three statuses, and that is the design, not a hedge.** `ok` / `fail` /
  `unavailable`, with **boot refusing on `fail` only** and **`/ready` red on either**. §15.1 lists
  readiness as "boot self-check passed **and** Qdrant reachable **and** the pinned index schema
  present" — three clauses, so schema *presence* is readiness while schema *drift* is a refusal.
  Refusing to boot because somebody else's service is down would turn their outage into a restart
  loop that outlasts it. An absent collection reports `index_not_ready`, an unreachable Qdrant
  `qdrant_unavailable`.
- **`/ready` now runs the whole check list per probe, in a worker thread.** The list is sync
  (shared with the CLI), so `starlette.concurrency.run_in_threadpool` keeps the event loop clean —
  no blocking I/O in an async handler. The async Qdrant client and the separate `probe_qdrant`
  helper from U002 are gone: one sync client on `app.state`, one round trip, and reachability is
  reported by the same check that reads the schema.
- **The model-identity half of the §6.6 fingerprint is not checked yet, and cannot be here.**
  `dim` and `distance` are read back from the live collection; `embed_model` and
  `composition_version` are not observable from Qdrant, so they need a record written beside the
  collection. **U010 owns it** (it is the unit that writes the fingerprint and refuses to upsert on
  a mismatch). `vsir doctor` prints the configured fingerprint and its digest today, and the README
  now says exactly that rather than implying the model half is verified.
- **`point_id` corrects `impl`.** `impl/app/pagemodel.py` hashed under a private namespace
  constant; §5.1 specifies `uuid.NAMESPACE_URL`, which is what ships, asserted by an explicit
  equality test and by a subprocess test proving stability across processes (I1).
- **`run_id` is a hand-written ULID** — 48-bit ms timestamp + 80 bits of randomness in Crockford
  base32. No new dependency (§4.2), it sorts in time order, and unlike `impl`'s `uuid4().hex[:8]`
  (register E1) two runs in the same millisecond still differ.
- **`series_id` carries no revision, deliberately** (F8): a scope expressed as a series survives a
  revision boundary where a `section_id` cannot. This unit fixes the id's *grammar* only — the
  canonical section key it is built from comes from stitching (U009) and is asserted across
  revisions by U025.
- **The 16 flat payload keys are exactly the 16 `INDEXED` keys**, asserted both ways
  (`test_the_flat_payload_is_exactly_the_indexed_keys`). A filterable field hiding in `content`
  would be filterable-but-unindexed, which is F10 with no error message.
- **The conformance gate caught my own prose.** A docstring in `core/indexed.py` named a struck
  legacy identifier while explaining that it had been removed; the grep fired, and the docstring
  was rephrased to describe the field rather than spell it. Working as designed — the rule has no
  docstring exemption, and that is the right trade.
- **`INDEXED` is a `MappingProxyType`**, so nothing can add a seventeenth key at runtime — a key
  the creation loop never indexed and the boot assertion never checked.

**Fixes from the M0 verification pass** (all in this commit):

- **`scripts/test-api.sh` teardown never ran, and then swallowed the exit code.** The `EXIT` trap
  invoked `docker compose -f docker-compose.test.yml` *after* `cd backend`, so teardown silently
  did nothing and the script exited 1 on a fully green run, leaving the stack and volume up. Fixed
  with an absolute `$COMPOSE`. Fixing that exposed a second, worse bug: a successful `docker
  compose down` in the trap replaced pytest's status, so a **failing suite reported success**. The
  trap now captures `$?` first and exits with it. Verified both ways: green → 0 with nothing left
  running, non-green → the real code. `scripts/test-e2e.sh` had the same two bugs.
- **The serving process's stdout was a mixed stream.** uvicorn keeps its own plain-text handlers,
  so ~10 of 18 lines were not JSON — §15 Factor XI was not true of the stream the platform
  actually collects. `logging.capture_stdlib_loggers()` drops their handlers and lets the records
  propagate to the one formatter. `httpx`/`httpcore`/`urllib3` are floored at WARNING in the same
  pass: one event per HTTP request is the transport's business, and our own audit line (§7.4) is
  the record that matters.
- **`README.md` overstated the implementation** — it claimed `vsir doctor` verified the collection
  fingerprint. Corrected to name what is checked, and to state that unreachable ≠ wrong.
- **`data/source/` and `data/fixtures/` did not exist**, and `.gitignore` referenced a
  `data/source/.gitkeep` that was missing, so neither directory would survive a clone. Both now
  carry a `.gitkeep`. `backend/tests/paid/` is left to **U013**, its owner — `test-paid.sh` already
  handles its absence, and an empty test directory is exactly the placeholder M0 forbids.

---

## Milestone demos (Spec §0 — a milestone with no runnable demo is not complete)

| M | Demo command | Status | Evidence |
|---|---|---|---|
| M0 | `vsir doctor && bash scripts/test-unit.sh` | ✅ | see below |
| M1 | `vsir demo exact --synthetic` | ⬜ | |
| M2a | `vsir ingest data/source/synthetic_3window.pdf --vlm stub` | ⬜ | |
| M2b | `VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf` | ⬜ | |
| M3 | `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` | ⬜ | |
| M4 | `vsir demo narrow` | ⬜ | |
| M5 | `VSIR_ALLOW_PAID=1 vsir read --pages … --question …` | ⬜ | |
| M6 | `VSIR_ALLOW_PAID=1 vsir ask "carton discharge won't restart after an E-stop reset"` | ⬜ | |
| M7 | `bash scripts/test-e2e.sh` then browse `http://localhost:5174` | ⬜ | |
| M8 | `vsir ingest --resume <run_id>` and `vsir eval corpus` | ⬜ | |

### U004 — Tokenisation, variants, the exact filter, and both envelopes

**Milestone:** M1 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — `vsir demo exact --synthetic --only primitives` (abridged; all five sections
print, every line PASS, exit 0):

```
1. variants(label) — three spellings of the SAME characters (§5.6, I3)
   SF 1.1A          SF 1.1A · SF1.1A · SF 1.1 A                  PASS
   84-5140.0020     84-5140.0020                                 PASS
   X20SI4100        X20SI4100 · X 20 SI 4100                     PASS

2. exact_filter(label, scope) — the ONLY exact-match code path (§5.6, F1)
   should[
     must[ MatchPhrase(text='SF 1.1A'), doc_id='TC1E-SF', is_current=True ]
     must[ MatchPhrase(text='SF1.1A'),  doc_id='TC1E-SF', is_current=True ]
     must[ MatchPhrase(text='SF 1.1 A'), doc_id='TC1E-SF', is_current=True ]
   ]
   one phrase per variant, scope ANDed into every branch          PASS

3. tok() mirrors Qdrant's WORD tokenizer, not impl's TOKEN_RE (§5.6, §2.4)
   84-5140.0020     ['84', '5140', '0020']             PASS
   84-5140.0020 -> three tokens, which is why phrase matching is the mechanism  PASS

4. §7.3 caps — each a typed 400 naming its bound, never a clamp (F18)
   read, 4 pages          -> 400 read_page_cap_exceeded   {'limit': 3, 'requested': 4}          PASS
   fetch, 6 pages         -> 400 fetch_budget_exceeded    {'bound': 'pages', 'limit': 5, ...}   PASS
   dpi=100                -> 400 dpi_not_allowed          {'allowed': [36, 72, 150, ...]}       PASS
   dpi=300, no region     -> 400 dpi_requires_region      {'region_required_above': 220}        PASS
   scope={'bogus': 1}     -> 400 filter_unknown_key       {'keys': ['bogus']}                   PASS
   reads_remaining=0      -> 429 budget_exhausted         {'reads_remaining': 0}                PASS

ALL ASSERTIONS PASSED
demo-exit=0
```

`bash scripts/test-unit.sh` → **409 passed**. `bash scripts/test-api.sh` → **84 passed**, exit 0.

**Invariants / failure rows closed:** **I3** — one `exact_filter`, and an **AST scan** (not a grep)
proves `MatchPhrase` has exactly one call site in the package; the property test asserts every
variant of every corpus label equals the label with whitespace stripped, so `K73` cannot yield
`K78`. **I5** — `SearchResponse.empty_is_never_ok` makes an empty `ok` a validation error.
**F10** — an unknown scope key is a typed `filter_unknown_key` 400 naming the keys, from `core`
and from `serve`. Spec §20.1 register item **D3** closed: `sparse.dedupe(against=text)` is ported,
so U010 can populate the `captions` surface that `impl` declared, weighted, and never wrote.

**Notes**

- **The tokenizer differential is at L2, not L0.** The plan lists this unit as `[L0]` while its own
  fixtures row says "an ephemeral Qdrant for the tokenizer differential test only" — and a test
  that needs Docker cannot be in the no-Docker layer. Split: L0 pins `tok()` against a frozen
  golden table of the corpus's shapes; `tests/api/test_tokenizer_differential.py` (51 assertions)
  proves that table is what a live `qdrant/qdrant:v1.19.0` actually produces. Qdrant has no
  "tokenize this" endpoint, so the comparison is **behavioural**: each label is indexed, and a
  phrase built from `tok()`'s output is asked of the real index. That is stronger than a string
  comparison — it also proves order matters (`"1a 1 sf"` does not match a page printing `SF 1.1A`)
  and that Qdrant really does split `84-5140.0020`, which is the evidence that the phrase mechanism
  is required rather than merely chosen. A Qdrant bump that changed the tokenizer now fails L2.
- **`variants()` de-duplicates, so the count is *at most* three.** The plan's AC says
  `len(variants(label)) == 3` while its own Edge Cases row says a whitespace-free label "collapses
  to fewer than three distinct strings — assert de-duplication, not a crash". De-duplication wins;
  the invariant that carries the weight is the character-preserving one, which holds for every
  label. `variants("SF 1.1A")` is 3; `variants("K158")` is 2; `variants("84-5140.0020")` is 1.
- **`rrf()` breaks ties deterministically**, which `impl` did not. It sorted on the fused total
  alone and left equal rows in dictionary insertion order; §16 requires the same query to return
  the same rows *in the same order*. The tiebreak is best per-surface rank, then the point id. The
  fused total is computed by a private function and **never returned** — `impl` carried it to the
  API as `Hit.fused`, and a fused float is a similarity score under another name (§7.6). The
  §12.5 grep would now fail the build on the field name, which is how the port was caught.
- **`region_invalid` is an error code §7.3 does not enumerate.** §7.3 tabulates *bounds*; a
  malformed normalised region has no row. Rather than clamp `[0, 0, 2, 2]` to the page — which
  would return a different crop and call it success — it is a typed 400 in the same family. Flagged
  as an addition to the error vocabulary, not a spec change.
- **The demo prints a human-readable report, not JSON**, like its ancestor
  `impl/scripts/interfaces_demo.py`. `vsir doctor` and the server emit the JSON event stream;
  a one-off demo's output *is* the artefact a reviewer reads (§4.4).
- **`vsir demo exact --only` accepts only `primitives` at this milestone.** U005 adds the
  seeded-corpus sections and changes the default; until then any other value is an argparse usage
  error listing the valid choices, not a stub that prints "not implemented".
- **Carry-forward for U007:** `ids.slug()` is lossy, so `TC1E-SF`, `TC1E_SF`, `TC1E SF` and
  `TC1E.SF` all produce the same `doc_id` — and therefore the same `point_id`s. That is correct for
  a slug, but it means I1's idempotent overwrite would fire on two *different* documents, erasing
  one instead of doubling totals. The manifest step must assert `doc_id` uniqueness at ingest
  rather than trusting the uploader. Found by the U003 re-verification pass.

**Fixes from the U003 re-verification pass** (all in this commit):

- **`point_id` hashed the raw page-id string, and `parse_page_id` accepted spellings `page_id()`
  can never emit.** `TC1E-SF@1.3#p0001` parsed to page 1 but hashed to a different uuid5 than
  `#p001` — one page, three point ids — and `#p000` parsed to page 0, which the constructor refuses
  outright. Left in place, any future `resolve` doing `point_id(citation)` would address a point
  that does not exist: **a silent miss, which is the failure class this module exists to prevent**
  (I1, F12). Fixed both ends: the regex now admits only canonical spellings (exactly three digits,
  or four-plus with no leading zero), page 0 is refused, and `point_id` canonicalises through
  `parse_page_id` + `page_id` so a non-canonical string cannot reach the hash at all. Canonical
  point ids are unchanged — `TC1E-SF@1.3#p001` still hashes to `82882c2a-…` — so nothing already
  written is orphaned. Regression tests added for every over-padded spelling and for page 0.
- **`event: "doctor_ok"` was emitted for runs where the collection was never checked.** An
  operator greps that event to mean "this release was verified". Now a run with any inconclusive
  check logs `doctor_inconclusive` at `warning`, and `doctor_ok` is reserved for a run where every
  check concluded.
- **A boot refusal escaped uvicorn as a 42-line traceback.** §4.3's refusal is a designed
  behaviour whose reason is already on the stream as JSON, so the traceback was redundant non-JSON
  noise on a stream whose contract is one JSON object per line. Added
  `serve.app:app_factory` — the process entry point — which turns `BootRefused` into `exit 1` after
  logging it. `create_app` still raises, because a library that calls `sys.exit` is untestable and
  a test asserting *which* check refused is worth more than a tidy exit code.
- **The mixed-stream fix had no regression guard.** Nothing in the tests mentioned uvicorn, so a
  bump would silently reinstate plain-text access logs. `tests/api/test_log_stream.py` now drives
  the **container** through a 404 and a 405 and asserts every line of its stdout parses as JSON
  with `release_id` and `level` — and that the access log is still *there*, since folding uvicorn's
  loggers in must not mean silencing them.
- **Two stale doc claims corrected.** `config.fingerprint_id` said boot "compares" it (nothing
  does — the model half is U010's), and `/ready`'s docstring said a drifted schema makes the
  process exit (true at start-up; at runtime it goes red, which is the case that docstring is
  about).

**Correction to the U003 record:** that commit message says the `test-api.sh` teardown bug was that
"a successful `docker compose down` in the trap replaced pytest's status". The re-verification could
not reproduce that in isolation — a bash `EXIT` trap does not normally override the triggering
status — and identified the primary cause as the **relative compose path**: after `cd backend` the
teardown command failed, and `set -e` inside the trap exited the script with docker's status, which
is exactly "no teardown, and exit 1 on a green run". The observed exit-0-with-a-failing-test on this
machine is consistent with a shell-version-dependent variant of the same area. The explicit
`local status=$?; … exit $status` is therefore belt-and-braces rather than the load-bearing fix, and
both behaviours are now asserted in both directions.

---

### U005 — Synthetic exact surface, `lookup`, and `vsir demo exact`

**Milestone:** M1 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — `vsir demo exact --synthetic` (sections 6–13; 1–5 are U004's primitives,
unchanged and still green):

```
6. the §13 M1 corpus — hand-written page text, no PDF, no VLM, no spend
   source .../data/fixtures/synthetic_pages
   SYN-M1@1.0, pages seeded                 31 points, 30 current                    PASS
   pages with no text layer (§5.7)          1                                        PASS
   pages unsearchable for lookup (§5.7)     2                                        PASS
   superseded revision 0.9 kept, not deleted 1 page, is_current=False                PASS

7. lookup(label) — exact, phrase-only, a SET not a ranking (§7.2.2, F1)
   lookup("SF 1.1A")                        ok total=1 p001                          PASS
   the token-decoy page is NOT returned     p008 absent from hits                    PASS
   every hit carries an image REFERENCE     /pages/SYN-M1@1.0#p001/image?dpi=150     PASS
   no hit carries image bytes (P2, D12)     no bytes_b64 field                       PASS

8. the eight compact labels each resolve to the page that prints them (F3)
   lookup("SF 1.1A") → printed SF 1.1A      ok total=1 p001 [as given]               PASS
   lookup("SF 5.5b") → printed SF5.5b       ok total=1 p014 [whitespace removed]     PASS
   lookup("SF 121.1") → printed SF121.1)    ok total=1 p003 [whitespace removed]     PASS
   lookup("K 158") → printed K158           ok total=1 p001 [whitespace removed]     PASS
   lookup("K 78") → printed K78             ok total=1 p006 [whitespace removed]     PASS
   lookup("SI 3") → printed SI3             ok total=1 p017 [whitespace removed]     PASS
   lookup("Q25") → printed Q 25             ok total=1 p023 [letter-digit boundary]  PASS
   lookup("EAO84-5140.0020") → printed EAO 84-5140.0020 ok total=1 p021 [boundary]   PASS
   lookup("SF 5.5b") ≠ SF 5.5c              ok total=1 p014                          PASS
   lookup("K 73") ≠ K78                     not_found total=0 —                      PASS

9. a model-invented code is unfindable in the exact surface (I2, F14, D3)
   lookup("K999")                           not_found total=0 —                      PASS
   lookup("K999", include_unverified=True)  not_found hits=0 unverified=1            PASS
   the unverified hit is on the claiming page, verified=False  p004 verified=False    PASS
   the two lists are never merged           hits ∩ unverified_hits = ∅               PASS

10. an unsearchable page is `not_searchable`, never `not_found` (F4, §5.7)
   lookup("SF 9.9", scope={'page_no': 5})   not_searchable pages=1 no_text=1         PASS
   lookup("SF 9.9") unscoped                not_found total=0 —                      PASS
   lookup("K404", scope={'page_no': 10})    not_searchable pages=1 no_text=0         PASS
   lookup("K404") unscoped                  not_found total=0 —                      PASS

11. `weak` is the server's signal, and `cap` cannot move it (§7.1)
   lookup("3", cap=5)                       total=26 hits=5 capped=True weak=True    PASS
   lookup("3", cap=20)                      total=26 hits=20 capped=True weak=True   PASS
   lookup("3", cap=200)                     total=26 hits=26 capped=False weak=True  PASS

12. typed absence, and the affordance that keeps it honest (I5, §7.1)
   lookup("alarm 152")                      not_found suggest=['skim_pages']         PASS
   lookup("SF1.1A")                         not_found suggest=['skim_pages']         PASS
   lookup("SF 1.1A", scope={'doc_id': 'NO-SUCH-DOC'})  out_of_scope pages=0          PASS
   lookup("SF 7.7A") — is_current injected (I7)  not_found total=0 —                 PASS
   lookup("K 158") — is_current injected (I7)    ok total=1 p001                     PASS
   effective_scope is echoed back (F8, C11) {'is_current': True}                     PASS

13. the observed-token inventory (§6.8) — display-only, and never a match
   tokens observed in SYN-M1                57 tokens                                PASS
   every code-like token of the text, and nothing else  text ∩ has-a-digit            PASS
   nothing that is not in the text surface  no model claim leaks in                  PASS
   a prefix lookup, not a distance (F16)    starting_with('k7') = ['k78']            PASS
   lookup.py cannot reach the inventory     vsir.core.observed_tokens not imported   PASS

ALL ASSERTIONS PASSED
demo-exit=0
```

`bash scripts/test-unit.sh` → **474 passed** (409 → 474; +65). `bash scripts/test-api.sh` →
**130 passed** (84 → 130; +46), exit 0. The demo also runs green **from the production image**
with the corpus mounted read-only, which is the §15 Factor XII claim made good:

```
docker run --rm --read-only --tmpfs /tmp --env-file .env --network <test-net> \
  -e VSIR_QDRANT_URL=http://test-qdrant:6333 -e VSIR_SYNTHETIC_PAGES=/corpus \
  -v "$PWD/data/fixtures/synthetic_pages:/corpus:ro" vsir:<release> demo exact --synthetic
→ ALL ASSERTIONS PASSED
```

**Invariants / failure rows closed:** **I2 (M1 half)** — `lookup("K999")` on the code p004's
`content.codes` claims and its text does not contain is `not_found`, and reachable *only* through
`unverified_hits` with `verified: false`; the page itself stays findable by what its text does say
(`X7`), so the claim is quarantined and the page is not. **F1** — `test_lookup_sf_1_1a_returns_exactly_one`:
`total == 1`, and the decoy page carrying `sf`, `1` and `1a` non-adjacently is not returned.
**F3** — `test_all_eight_compact_labels_found`: eight labels, three variant kinds, each resolving
to the page that prints it. **F14** — `test_hallucinated_code_never_findable`. Also asserted here,
without claiming the rows their owning milestones hold: `is_current` is injected server-side so the
superseded revision 0.9 page is in the collection and mute (I7's mechanism; F9's
`found_only_in_superseded` upgrade is M8's), a re-seed does not double the count (I1's mechanism),
and every one of the twelve `INDEXED` scope keys filters for real against a live collection (I6).

**Notes**

- **The corpus is 31 pages, not four.** The plan's Deliverables say "four hand-written page
  records" and its own acceptance criteria say `lookup("3")` must be `weak` at `cap=5` *and*
  `cap=200`. `weak = total > max(WEAK_ABS, 0.25 × pages)` with `WEAK_ABS = 20` (§7.1), so a
  four-page corpus can never be weak at any cap — the signal needs more than twenty matching
  pages to exist at all. The corpus is therefore one 30-page document plus one superseded page:
  the six load-bearing pages the plan names (the literal `SF 1.1A`, the scattered-token decoy,
  `SF121.1)`, the `K999` claim, plus a no-text page and a `K78` page for U006), seven more that
  carry the labels the F3 table needs, and seventeen ordinary sheets. 26 of the 30 carry the token
  `3` — two sign-off pages deliberately do not, so the assertion is a filter and not a tautology.
- **The fixture is a *page*, not a record.** Each file carries only what a human can supply — the
  page's text and the codes an extraction would have claimed — and `vsir.eval.synthetic` derives
  the §5.3 record from it. A hand-written record could contradict itself (`has_text: true` with
  empty text, a `codes_in_text` that is not a subset of `codes`); a hand-written page cannot.
  `expected.json` beside it holds the §12.3 table, so no number lives in a test file where it
  could be quietly re-baselined (C10).
- **`variants()` is asymmetric, and that is a recorded recall gap.** A caller typing `SF1.1A`
  against a corpus printing `SF 1.1A` gets `not_found`: the three spellings of `SF1.1A` are
  `SF1.1A` ([sf1, 1a]) and `SF 1.1 A` ([sf, 1, 1, a]), and neither is [sf, 1, 1a] — re-spacing a
  bare label spaces **every** letter↔digit boundary and can never space just one. This is exactly
  what §5.6 specifies, so it is not a defect against the spec, and it is not fixable without
  either an identifier grammar (§5.2 prohibits one) or an exponential variant set. It is R1
  ("recall is not guaranteed"), and what makes it survivable is that it degrades to an honest
  abstention **carrying a next move** — never to a wrong page. Asserted in both layers
  (`test_the_compact_spelling_of_a_spaced_label_abstains_with_an_affordance`) and recorded in
  `expected.json` under `asymmetric_variant` so it is a known property rather than a surprise.
- **`next.suggest` is gated on observed words, and the words themselves are not in the envelope.**
  §7.1 says a `not_found` a different move could answer returns `suggest: ["skim_pages"]` "and the
  tokens that did occur" — but §7.1's own `NextMoves` model has `expand`, `neighbours`,
  `references` and `suggest`, and none of them is a list of words. Inventing a fifth field is a
  change to the response contract, so the words gate the suggestion (no word occurred ⇒ no
  suggestion, which is why `K999` carries none and `alarm 152` does) and ride on the event stream
  instead. **If a caller needs the list, that is a §7.1 spec change, not a tool change.**
- **The probe set is the union over the *variants*, minus one-character words.** Probing only the
  typed spelling would learn nothing about `X20SI4100` (one token); probing single characters would
  fire a suggestion on almost every abstention, because `min_token_len=1` means the index really
  does contain `3` and `k`. A word that is itself a one-word variant is not probed either — `total
  == 0` over the OR of the variants has already answered it. Bounded at eight probes.
- **`text_trust: untrusted` is excluded from `hits`, not just from the count.** §5.7 says both
  `untrusted` and `no_text` "count as unsearchable for `lookup`", so p010's garbled text layer
  really does contain the phrase `K404` and really is not a verified hit; scoped to that page alone
  the answer is `not_searchable`. The model's claim about the same page is still disclosed through
  `unverified_hits`, which is the honest shape: *something* says `K404` is there, and it is not the
  text layer.
- **`cap < 1` is a typed `cap_out_of_range` 400** — added to `serve/caps.py`, an error code §7.3
  does not enumerate, on the same reasoning U004 recorded for `region_invalid`: §7.3 tabulates the
  bounds that cost money and this is the same rule applied to a parameter it left implicit. Zero
  cannot be allowed through, because every alternative is a lie — `ok` with no hits is impossible
  (I5), and any of the four absences reported beside `total: 26` says "nothing is there" about a
  set whose size the same response is reporting. There is no upper bound: §12.3 requires `weak` to
  hold at `cap=200`.
- **`lookup` logs at `debug`, not `info`.** §7.4 requires one audit line per `read` and per
  `fetch` — the two tools that spend — and §11.4 asks for nothing per call from a free one. It
  also keeps the demo's report readable at the default log level, since both share stdout.
- **The log redactor hides a field called `tokens_*`.** `logging.redact` matches
  credential-shaped field *names* and `token` is one of the hints, so the first version of the
  event arrived as `"tokens_observed": "***"` — the redactor working exactly as designed on a name
  that has nothing to do with a secret. Renamed to `words_observed`, which is also the more
  accurate noun (`tok()` mirrors Qdrant's **WORD** tokenizer). Worth knowing before somebody logs
  `input_tokens` in U014's audit line — **that** field is required by §7.4 and will be redacted
  unless the redactor learns about it.
- **`backend/vsir/eval/` is a new package, beyond the unit's Deliverables list.** The synthetic
  corpus loader and seeder are needed by both the CLI and the L2 suite, so they cannot live in
  either; plan §8 SA-5 already records `eval/` as a sanctioned extension of §4.1's layout (owned
  by U016, which adds the `vsir eval` commands to it). Nothing about correctness lives there —
  the rules stay in `core/`.
- **Points are seeded with no vectors.** `vector={}` is legal in Qdrant and honest: there is no
  embedder at M1 and this milestone spends nothing, so the dense and the two sparse surfaces are
  empty in this corpus and nothing here can exercise them. That is what M1 *is* — the exact
  surface, proved on its own, before a cent is spent.
- **`VSIR_SYNTHETIC_PAGES` is a new optional env var** (`.env.example`, AGENTS.md). The image's
  build context is `backend/`, so the checked-in corpus is not in the image; a container running
  the demo mounts it and points the variable at the mount, exactly as `VSIR_FIXTURE` does for
  replay mode (D10). A missing corpus is a named `FixtureMissing` refusal and a non-zero exit, not
  a traceback and not an empty corpus — an empty corpus would answer `out_of_scope` to everything,
  which reads as a green run of a suite that tested nothing.
- **Seven Qdrant round trips for a hit**: three counts and two facets for `scope_stats`, then one
  count and one scroll for the set — six where the scope holds no `has_text: false` page, since
  that facet is skipped — plus up to eight probes on a `not_found`, and one more scroll when
  `include_unverified` is on.
  Every one is an indexed filter, and the whole 46-test L2 suite runs in 1.4 s, so this is
  recorded rather than optimised. `scope_stats` is a required envelope field (§7.1) and `weak`
  needs `scope_stats.pages`, so the denominator is not optional.
- **Carry-forward for U009 (`core/health.py`) and U011 (the §11.1 gates):** §5.7's
  `have = token_set(page.text)` cannot ground a **multi-token** code. `SF 1.1A` is [sf, 1, 1a] in
  the text and `sf 1.1a` as a claimed code, so they never intersect, and p001 — where all four
  codes are plainly printed — derives `grounded_rate: 0.5` and a `codes_in_text` holding only the
  two single-token codes. §2.4 forbids porting `impl`'s adjacent-token joins, and says why: they
  are "superseded by `phrase_matching` + `variants()`". So the phrase-aware replacement is the one
  §2.4 points at — a code is grounded when `exact_filter(code)` matches the page — and it belongs
  in U009's derivation, not here. The synthetic records compute the formula §5.7 states, verbatim,
  so that the gap is visible in the fixture rather than hidden by a local fix. **Left unfixed, a
  document whose codes are printed with spaces would fail the `grounded_rate ≥ 0.8` publish gate
  (§11.1) for a reason that is entirely an artefact of set intersection.**
- **Fixed while here:** a pre-existing `DeprecationWarning: invalid escape sequence '\ '` from
  `core/ids.py`'s `parse_page_id` docstring (an RST `\ ` continuation in a non-raw string, which
  becomes a `SyntaxWarning` on a later Python). The docstring is now raw.

---

### M0 milestone gate — closed 2026-09-09, tagged `cr1-m0`

**Demo** (Spec §0): `vsir doctor && bash scripts/test-unit.sh`

Re-run at `afeca46`, after U004 renamed the summary event for an unchecked run:

```json
{"event": "boot_check_unavailable", "check": "collection_schema", "level": "warning",
 "reason": "index_not_ready",
 "detail": "collection 'vsir_pages_1536' does not exist yet — create it with `vsir doctor --create-collection`"}
{"event": "doctor_inconclusive", "level": "warning", "failed_checks": [],
 "unavailable_checks": ["collection_schema"], "release_id": "dev-0", "python": "3.11.15",
 "models": {"VSIR_VLM_MODEL": "gemini-3.8-flash-001", "VSIR_EMBED_MODEL": "gemini-embedding-2"},
 "fingerprint": {"embed_model": "gemini-embedding-2", "dim": 1536, "distance": "cosine",
                 "composition_version": "d4-fused-v1"},
 "fingerprint_id": "45a09c588c25422c", "pages_collection": "vsir_pages_1536"}
```
```
409 passed in 1.43s
Layer 0/1 PASSED
M0-demo-exit=0
```

With no Qdrant running, the live-collection check is honestly reported as inconclusive
(`doctor_inconclusive`, `reason: index_not_ready`) and boot proceeds — not a check that passed
vacuously.

**Spec-conformance ledger for §4.3 — 4 of the 5 refusals ship, and one is narrowed by choice:**

| §4.3 refusal | Status |
|---|---|
| a model id ending `-latest` | **ships** (U001) |
| a missing required env var | **ships** (U001) |
| `text`/`vlm_codes` not text indexes with `phrase_matching=True` | **ships** (U003) |
| the live payload schema lacks any `INDEXED` key | **ships, narrowed** — see below |
| the collection fingerprint ≠ the configured embedding model | **not implemented — U010 owns it.** `dim` and `distance` are read back from the live collection; `embed_model` and `composition_version` are not observable from Qdrant, so the model half of §6.6 needs a record written beside the collection |

**The narrowing, stated plainly.** A collection that *exists and disagrees* with `INDEXED` refuses
the boot, by name — that is the M0 acceptance item and it is closed. A collection that is **absent**
does not refuse; it reports `index_not_ready` and `GET /ready` goes 503. §4.3's literal text covers
the absent case (a nonexistent collection's schema lacks every key), and the re-verification pass
was right that reachable-and-absent is a *conclusion* rather than an inability to conclude — so this
is a **deliberate deviation, not a reading**. Two things justify it and both are recorded here
rather than argued away: §15.1 lists "the pinned index schema present" as a **readiness** condition,
separately from "boot self-check passed"; and because `/ready` is red for the whole time the
collection is absent, **no instance can ever serve without the pinned schema** — which is the
guarantee §4.3 exists to provide ("never degrade to a partial service"). An unreachable Qdrant is
inconclusive for the stronger reason that refusing to boot on a backing-service outage is a restart
loop that outlasts the outage.

**Acceptance verified by subagent** against Spec §13 M0. First pass (at commit `922bc3f`) returned
✓ on 8 of 11 acceptance rows and 9 of 11 deliverable rows, and **✗ on the payload-index refusal**
plus five defects. All six are fixed in `5163ab4` and re-verified. The gate is recorded as closed
**after U003**, because the payload-index refusal needs `INDEXED`, which the plan assigns to U003 —
a milestone-boundary correction, documented under U003, with no requirement weakened.

---

---

## Notes

Record gaps, ambiguities and assumptions here as they are resolved.

### Open at planning time
- **OQ-1** pilot PDF location — blocks only U013's re-bill. Default: the operator places it at
  `data/source/TC1E-SF.pdf`; `data/source/` stays gitignored.
- **OQ-2** Gemini project/key — blocks the L4 halves of U013, U020, U022 and U026's real numbers.
  Default: replay mode (`VSIR_VLM=stub` + `VSIR_FIXTURE`), paid paths behind `VSIR_ALLOW_PAID=1`.
- **OQ-3 / OQ-7** Part A export hand-off (HTTP vs files on disk) — resolve before M8 (U011, U025).
- **OQ-5** one collection at 5,505-page scale — default one collection with `doc_id` scoping (U025).

### Stale spec text adjudicated during planning
See plan §8 SA-1…SA-12. The load-bearing ones: **SA-1** the dense vector **does** include the page
raster (C12/D4 win over §4.2's "Text only" row); **SA-2/SA-3** the sparse surfaces and RRF **ship**
(D2 wins over §2.2's out-of-scope row and §7.2.1's "there is no sparse vector" parenthetical);
**SA-4** the default answer route is `fetch`, not `read`.

### Spec changes made
None. Gap analysis found no true blocker — every apparent contradiction is resolved by Spec §2.3,
§3 or §17.
