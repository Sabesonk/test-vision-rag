# CR1 Implementation Progress

**Plan:** `development/cr1/plan/cr1-implementation-plan.md`
**Release tag:** (pending — set when all units are [x])

## Rollup

| | |
|---|---|
| **Complete** | 15 / 26 units (58%) |
| **Current milestone** | **M3 closed and tagged `cr1-m3`** (3 / 3 units); M0, M1 and M2a closed and tagged before it, M2b's non-paid half shipped. Next milestone: **M4** — `skim_pages`, `fetch`, `resolve` |
| **Next unit** | U017 — `skim_pages`, deterministic fusion, image queries, and `resolve` (**Spend: none**, M4, P0-Critical). The page rung of the narrowing ladder with §7.2.1's score-free ordering, `exclude`, the `next` affordances and D12's image queries, plus `resolve` with `interpolated`. It is the first unit that reads a *vector*, so the three fused surfaces U010 wrote become load-bearing |
| **Blocked** | **U013** — the paid re-bill only, on **OQ-1** (no `data/source/TC1E-SF.pdf`) and **OQ-2** (`VSIR_VLM_KEY` empty). Everything in the unit that does not need the PDF or the key shipped on 2026-09-10 and is green; see the unit's entry for what remains and how it unblocks. Nothing downstream is blocked (§17) |

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
- [x] U006 `verify_claims`, `present_instead`, and the L3 abstention eval

### M2a — ingest a generated PDF with a stubbed VLM (spend: none)
- [x] U007 Manifest, probe, render, S1 facts, and the windowing ladder
- [x] U008 The VLM boundary, cache keys, replay mode, and S2 extraction
- [x] U009 Derivation, health signals, label attribution, and stitching
- [x] U010 Embedding, the three surfaces, the fingerprint, and indexing
- [x] U011 Gates, publish, retirement, the run control plane, and exports

### M2b — ingest the pilot PDF; freeze the fixture (spend: S2 + embed, once)
- [x] U012 Port the paid-for `impl` fixtures and the parity / negative sets — spend: none
- [!] U013 The one paid `TC1E-SF` ingest and the `grounded_rate` baseline — spend: paid — **blocked on OQ-1/OQ-2 for the re-bill only**; the recorder, the report, the acceptance table and all three test files shipped 2026-09-10

### M3 — `lookup` + `verify` over HTTP and MCP (spend: none)
- [x] U014 The serving app — auth, audit, budget, and degradation
- [x] U015 `lookup` and `verify` over HTTP and MCP
- [x] U016 `vsir eval acceptance` and `vsir eval abstention`

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
| M3 | `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` | ✅ | see the M3 milestone gate below |
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
  **Resolved in U009** — the spec's §5.7 snippet and §2.3 C8 now ask the phrase question, and
  `core/health.py` implements it through `core/exact.py::printed_in`. The M2a corpus's median went
  from 0.6 to 1.0. The M1 seed here still computes the literal formula on purpose: it is a
  *fixture*, and its `expected.json` is the absolute acceptance table of C10.
- **Fixed while here:** a pre-existing `DeprecationWarning: invalid escape sequence '\ '` from
  `core/ids.py`'s `parse_page_id` docstring (an RST `\ ` continuation in a non-raw string, which
  becomes a `SyntaxWarning` on a later Python). The docstring is now raw.

---

### U006 — `verify_claims`, `present_instead`, and the L3 abstention eval

**Milestone:** M1 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — `vsir demo exact --synthetic --verify "SF 1.1A,K73,SF 9.9" && bash scripts/test-api.sh -k near_miss`
(sections 14–15; 1–13 are U004's and U005's, unchanged and green):

```
14. verify_claims(claims, page_ids) — three states, per (claim, page) (§7.2.4, F2)
   verify("SF 1.1A", [p001])                present on p001                          PASS
   verify("SF 1.1A", [p008])                absent                                   PASS
   verify("K158", [p001 p002])              present on p001                          PASS
   verify("K73", [p006])                    absent · different part: ['k78']         PASS
   verify("K999", [p004])                   absent                                   PASS
   verify("SF 9.9", [p005])                 unverifiable (no_text)                   PASS
   verify("K404", [p010])                   unverifiable (untrusted)                 PASS
   verify("SF 7.7A", [p001])                unverifiable (not_current)               PASS
   every claim absent is still a Family B `ok`  status=ok ['absent', 'absent']        PASS
   the matrix is per (claim, page), never collapsed  p001=present p002=absent        PASS

15. near_misses(n=100) — one character off a real code (§12.4, F16)
   100 fabricated codes, deterministic      100 from 21 real codes                   PASS
   each differs by exactly one character    0020→0000 150→100 152→102 380→300 …      PASS
   no fabricated code is a real one         no fake is printed, in any spelling      PASS
   every source is an observed token        21 sources, all from the inventory       PASS
   a near miss is never its own disclosure (F16)  different part ≠ the claim, cap 5  PASS
   the eval that asserts none of them can ANSWER runs at L3, on every commit:
     bash scripts/test-api.sh -k near_miss

ALL ASSERTIONS PASSED
demo-exit=0
```

```
bash scripts/test-api.sh -k near_miss  →  6 passed, 130 deselected, exit 0
```

`bash scripts/test-unit.sh` → **538 passed** (474 → 538; +64). `bash scripts/test-api.sh` →
**136 passed** (130 → 136; +6), exit 0.

**Invariants / failure rows closed:** **F2 (core half)** — the one `exact_filter`, per
`(claim, page)`: `test_verify_claims_sf_1_1a_absent_on_p008` is §12.3's row, and because `verify`
and `lookup` share the filter the two cannot disagree about the same page. **F16** —
`test_k73_absent_with_present_instead_k78`, plus a property test asserting every disclosure is a
**prefix extension** of the claim, and the L3 eval asserting on all 100 near misses that the fake
never appears in its own `present_instead`. The mechanism I8 gates on at M6 is built here
(`page_checks` returns the whole matrix); I8 itself is asserted by U022, per Spec §9.

**The eval failed on its first run, twice, and both were real.** That is the unit working.

1. **`sf5` → `sf1` returned `ok` on p001.** Not a defect in `lookup`: `variants("sf1")` includes
   the boundary-spaced `sf 1`, and `sf 1` **is** printed on p001, inside `SF 1.1A`. A phrase match
   is a match on a contiguous run of tokens, so a shorter label whose spelling re-spaces into a
   prefix of a longer printed one is found — and the characters really are on the page. Telling
   `SF 1` apart from the start of `SF 1.1A` needs to know where a code ends, which is an identifier
   grammar, and §5.2 prohibits one. So the defect was in the **generator's premise**: "absent from
   the token inventory" is weaker than "not printed". `near_misses(..., texts=…)` now rejects any
   candidate the corpus prints in **any** spelling, and the behaviour itself is recorded as
   `expected.json`'s `phrase_prefix` row with an explicit L2 test
   (`test_a_shorter_label_can_phrase_match_inside_a_longer_printed_one`) so it is a known property
   rather than a hidden exclusion. **This is a real precision limit of phrase matching and it is
   now written down.**
2. **`k404` and `rai1` were "no longer findable".** They are printed only on p010, whose
   `text_trust` is `untrusted` — a page `lookup` deliberately excludes from `hits` (§5.7). The
   near-miss sources were being drawn from a page nothing may be found on. The fix is the rule
   §5.7 already implies and nothing had yet applied to the inventory: **an unsearchable page does
   not volunteer codes**. `observed_tokens.is_searchable` is the predicate, applied at every call
   site (the demo, both evals, `verify`'s local inventory), and the inventory of the synthetic
   corpus is 55 tokens from 28 searchable pages rather than 57 from 30. Left unfixed, a garbled
   extraction's debris — `rai1`, for *"rail"* — would have come back beside an `absent` verdict as
   a *"different part"*: noise presented as knowledge, about a page nobody may be told is evidence.

**Notes**

- **`UNSEARCHABLE_TRUST` now lives in `core/record.py`,** beside `TextTrust`, because three modules
  need the same §5.7 rule: `lookup` filters `hits` on it, `verify` returns `unverifiable` for it,
  and the inventory refuses to take codes from it. It was declared in `serve/tools/lookup.py`
  (U005) and is imported from `core/` now — one definition, or the three drift.
- **A page that is not current is `unverifiable`, with `reason: not_current`.** I7 is absolute — a
  run that has not passed its gates cannot answer — and `absent` would be a **false** statement
  about the revision 0.9 page, which really does print `SF 7.7A`. `unverifiable` is also the only
  reading that lets the answer gate tell a superseded citation from a scanned page, since both then
  arrive as "not verified" with different reasons. Note the consequence: `verify` addresses pages
  by their exact `page_id`, which already carries the revision, so nothing is injected into a
  filter — publication state is read off the retrieved payload, which is a fact about the page
  rather than a filter that would make a page the caller explicitly named unaddressable.
- **The fold is `present` > `absent` > `unverifiable`, and `page_ids` says what the verdict is
  about.** `present` names the pages that carry the code — which is I8's mechanism, since a draft
  citing p002 cannot borrow p001's evidence. `absent` names the pages actually **checked**, so a
  caller can see that an absence asserted over a set containing a scanned page is not asserted
  about that page. `unverifiable` names none, because nothing was checked. `page_checks` returns
  the whole matrix uncollapsed, and that is what the answer gate will consume (U022).
- **`present_instead` is lowercase.** The plan's AC and §7.2.4 both write `["K78"]`; the inventory
  is lowercase because the text index is (`lowercase=True`, §5.5) and because §6.8's own
  `codes_in_text` export is lowercase (`["k158", "q25", "sf 1.2a"]`). Read as prose casing, not as
  a second normalisation — and re-casing a token would be a guess, since the printed form of
  `sf121` is `SF121.1)`.
- **`present_instead` reads the inventory of the pages named in the call**, not the whole document,
  unless a document-level `Inventory` is passed in. That is the tighter and more honest reading of
  *"instead"*: `k78` is disclosed for a `K73` claim checked against p006 and **not** for the same
  claim checked against p002, because it is not "instead" on a page that does not carry it. §6.8's
  document-level inventory on the run's control point is the `inventory=` parameter, and U011 will
  pass it.
- **Truncation is bounded at two characters and floored at a two-character prefix.** Without the
  floor, `K73` falls back to the prefix `k` and discloses every contactor in the document; without
  the bound, a long claim eventually shares two characters with anything. Neither is an edit
  distance in disguise: a prefix can only reach tokens that agree with the claim from the first
  character onwards, which is exactly why `K73` can surface `K78` and can never surface `Q78`.
- **§12.4's snippet reads `r.present_instead` off a `lookup` response, and Family A has no such
  field** (§7.1 — the disclosure belongs to a per-claim check). The assertion is made where the
  field actually lives: every fake also goes through `verify_claims`, and no verdict may name it.
  That is strictly stronger than the sketch, because it exercises the code path that could leak.
- **`near_misses` returns `NearMiss(source, fake, position)`, not bare strings.** §12.4's
  pseudo-code iterates strings; a near miss without the real code it came from is unauditable, and
  the first question when this eval fails is *"one character off what?"*. No RNG and no seed
  either: the same corpus produces the same 100 fakes in the same order, because a safety test that
  samples differently each run turns a reproducible defect into an intermittent build.
- **The mutation order is character-major, positions last-to-first.** The last character first is
  the realistic misread (`K73` for `K78`) **and** the case where the fake shares the longest prefix
  with the real code — which is precisely where `present_instead` has something to say and
  therefore where F16 could be violated. Character-major then spreads the sample across every
  position the corpus's codes have: 100 fakes from 21 sources at positions 0–4.
- **The eval has a control test.** `test_the_real_codes_the_fakes_came_from_are_all_findable`
  asserts every source is still findable, because a suite made only of absence assertions is green
  on an index that answers nothing at all — the one failure mode a safety test cannot afford. That
  control is what caught finding 2.
- **One inverted import, deliberately.** `core/verify.py` imports `ClaimVerdict` and `VerifyResult`
  from `serve/envelope.py`, which is the only place `core/` reaches into `serve/`. §7.1 owns those
  models and §4.1 keeps the response models under `serve/`; declaring the three-state vocabulary a
  second time in `core/` would give *two* sources of truth to the one vocabulary whose entire
  purpose is that `unverifiable` and `absent` never blur. Recorded rather than hidden.
- **`tests/unit/fake_store.py` is now shared** by the `lookup` and `verify` L0 suites (it was
  private to the former). It answers `count`, `scroll`, `retrieve` and `facet` over payloads in
  memory, implements a phrase as *"`tok(phrase)` contiguous in `tok(text)`"* — the behaviour the L2
  tokenizer differential measured against a live Qdrant — and **raises** on any match type it does
  not implement, so it cannot silently pass a `MatchText` that I3 forbids.
- **A `verify` costs one `retrieve` plus one count per checkable pair**, asserted
  (`test_verify_costs_one_retrieve_and_one_count_per_checkable_pair`). Uncheckable pages cost
  nothing beyond the retrieve, which is why the 100-claim L3 eval runs in ~4 s.

---

### U007 — Manifest, probe, render, S1 facts, and the windowing ladder

**Milestone:** M2a · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — `vsir ingest data/source/synthetic_3window.pdf --vlm stub --until window`
(after `set -a && . ./.env && set +a` and `export VSIR_FIXTURE=data/fixtures/synthetic_3window`;
the JSON event lines and 36 of the 42 per-page rows are elided):

```
vsir ingest — release dev-0 · run 01M23Y0764NYS8YCWJW7SH3TS2 · until window

01 manifest — identity, from the filename, the metadata and the uploader ─────
   doc_id       synthetic-3window
   revision     1.0   (undeclared — the default, and recorded as such (register A4))
   doc_type     unknown   (undeclared — the default, and recorded as such (register A4))
   subjects     C24
   tags         synthetic, m2a, fixture, 3window
   source       data/source/synthetic_3window.pdf  ·  87,741 bytes

02 probe — the text layer, and the only writer of `text` (I2) ────────────────
   page_count 42 · pymupdf-1.28.2 · content_hash 4c9b4585d8f9922e…
   pages with text 40/42 (searchable_ratio 0.95) · s2_input_mode render@220
   front sample (8 pages) 92 chars/page vs a 150 threshold — extraction happened anyway,
   which is register A1: one `else` there throws away a mixed document's whole text

03 render — page rasters at dpi 220, in memory, never written down ───────────
   42 rasters at dpi 220, 1819x2573 px, 4.0 MB held in memory
   raster cache: 42 rendered, 0 served from the LRU (max 96)
   0 bytes written to the filesystem

   page  label  has_text  text_trust   chars  raster sha256 @220
      1  i      false     no_text          0  041713c55ab0d2e7b94f5382…
      2  ii     false     no_text          0  3896ef676d5e5487fb3430be…
      3  1      true      ok             123  11eba1fa15f6fe3ac0b997bf…
      …
     20  18     true      ok             522  51785438fe16681fd7d363c7…
      …
     42  40     true      ok             526  7860bc69aaa3c8d56f4302f1…

04 S1 document facts — cached per document, because the ladder rides on them ─
   facts_key    93061d0ce0b453e1…  (content hash ‖ gemini-3.8-flash-001 ‖ s2-v1)
   replay HIT   data/fixtures/synthetic_3window/facts/93061d0c….json
   title "C24 SYNTHETIC SAFETY MANUAL" · lang en · effectivity "from batch 68"
   toc          3 entries, 3 usable chapter range(s) — this is what picks the ladder
                p1    Front matter and general information
                p15   Safety functions of the C24 cell
                p29   Electrical references and part numbers
   the model disagrees with a DECLARED facet: nothing

05 window — the ladder, and the receipt that stops the pipeline paying twice ─
   level 1 · chapter-aligned · parallel=True
   #   pages       n  extract_key
   1   1-14       14  77cc653385accd4b3859dc07…
   2   15-28      14  02acdaa8b97c4ca41c83b1f7…
   3   29-42      14  3185733c74030a45860448a4…
   coverage: pages 1-42, each exactly once — True
   distinct keys: 3/3

assertions — data/fixtures/synthetic_3window/expected.json
   PASS  42 pages, as the fixture declares
   PASS  3 windows at level 1 — 1-14 · 15-28 · 29-42
   PASS  each window's extract_key is distinct — 3 distinct of 3
   PASS  coverage is the whole document, once
   PASS  has_text == false implies text_trust == no_text (§5.7) — pages [1, 2]
   PASS  the mixed-document trap is armed (register A1)
         the front sample averages 92 chars/page, under 150 — and all 40 text pages
         were still extracted
   PASS  the printed labels are the fixture's, offset and all (I4, F7)
         PDF page 3 prints "1" — label = index -2
   PASS  the crop trap: text comes from the FULL page, never a crop (F15)
         page 20's raster region [0.0, 0.0, 1.0, 0.55] keeps 1416/2573 px of the sheet
         and cuts off at 0.55; "EAO 84-5140.0020" sits at 0.965 — outside it, and in
         the extracted text
   PASS  the dpi 220 rasters are byte-identical to the fixture's — 42/42 hashes match

ALL ASSERTIONS PASSED
```

The two refusals, both non-zero and named — neither is a live call, and neither fabricates:

```
VSIR_PROMPT_VERSION=s2-v2 vsir ingest … --until facts
   REFUSED  fixture_miss: no frozen S1 response for facts_key 52426cd7… under
            data/fixtures/synthetic_3window/facts                              exit=1

vsir ingest … --vlm gemini --until facts
   REFUSED  vlm_backend_unavailable: step 04 needs S1 document facts and
            VSIR_VLM=gemini has no client at M2a                               exit=1
```

`bash scripts/test-unit.sh` → **630 passed**, Layer 0/1 PASSED (was 539).
`bash scripts/test-api.sh` → **137 passed** (unchanged; U007 adds no L2).

**Invariants / failure rows closed:** **F13** (a window truncates and loses 30 pages) — the
bisection ladder: each of §6.2's four triggers splits and re-bills, the union of the halves is the
original with no gap and no duplicate, and one page still over budget is typed
`window_unsplittable` (`test_oversized_window_bisects`, `test_window_unsplittable`,
`test_every_documented_trigger_bisects`). **F15** (a code is invisible because it was cropped away)
— `text` always comes from the full page (`test_crop_trap_full_text_extracted`,
`test_page_texts_never_clips`), backed by the existing `get_text(` conformance grep, which stops
being vacuous with this unit. No invariant is asserted here: I4 is U011's per Spec §9, and this
unit supplies the window boundaries its two checks use (`Window.absolute`).

**Register items closed:** **A1** (extraction is unconditional — the corpus is built so `impl`'s
eight-page sample would have thrown away 40 extractable pages), **A3** (`s2_input_mode` describes
the call that actually happens), **A4** (an undeclared facet is recorded as undeclared, so a
default and a declaration are tellable apart), **E3** (rasters are never persisted, asserted by a
filesystem-write spy plus a directory snapshot). **B2** is *prepared* here — `facts_key` exists and
the CLI reads S1 through it — and closed at U008, which owns the cache.

**The corpus.** `data/source/synthetic_3window.pdf`, 42 pages, 87,741 bytes, generated by
`python -m vsir.eval.synthetic_pdf` and reproducible byte for byte (`no_new_id=True`, fixed
metadata dates), with four hazards wired into the page geometry rather than described in prose:
three chapter starts at 1/15/29 so Level 1 answers and two sections straddle a fold (13-17, 27-31);
a `/PageLabels` table that restarts at "1" on PDF page 3, so *printed label = index − 2*; page 20's
`EAO 84-5140.0020` below the footer, outside a top-55 % crop; and pages 1-2 rasterised over six
short pages, so the front sample averages 92 chars/page. A test asserts every page's extracted text
line-for-line against what the generator says it printed — which is what would catch a layout mode
that silently reorders a table.

**Notes**

- **Two deliberate deviations from the plan's file list, both recorded rather than argued away.**
  (1) `backend/vsir/ingest/extract.py` is added, carrying **only** the §5.2 response schema and
  `S2_SCHEMA_HASH`. `extract_key` cannot be computed without a schema hash (§6.3) and Spec §4.1's
  normative layout puts the S2 schema in `extract.py`, so the alternative was a placeholder
  constant. U008 extends the same file with the call, as its Deliverables say. (2)
  `backend/vsir/eval/synthetic_pdf.py` is the generator the plan asks for; §4.1 has no home for a
  corpus builder and `eval/` is where the corpora live. `backend/tests/unit/conftest.py` and
  `test_ingest.py` are new tests, so the unit's `-k` slice widens to
  `"manifest or probe or render or window or ingest"` — `bash scripts/test-unit.sh` runs all of it
  either way.
- **`extract_key` follows §6.3, not `impl`.** It is keyed on the **ordered page image hashes**
  rather than `content_hash ‖ plan_hash`, which is strictly stronger (the key depends on the pixels
  the model will actually see), and `s2_input_mode` is out of it while `dpi` is in it — `impl`
  recorded a mode no code path implemented, inside a cache key (A3). `chain()` and `plan_hash()`
  are **not** ported: both exist to thread Level 2's carry chain, which §2.5 B excludes.
- **`Probe.has_text` is per page and is `bool(text.strip())`, with no threshold.** §6.1 step 02 and
  §5.3 both make `has_text` page-level, so the eight-page sample now decides nothing except what
  gets reported. There is no OCR anywhere, so every character in the layer came from the file and a
  sparse but genuinely born-digital page must not be made unsearchable by a minimum. §20.1 leaves
  register **A2** open at the *document* level; that document-level branch is simply gone here,
  because there is nothing left for it to gate.
- **`text_trust` from the probe is provisional and only ever `no_text` or `ok`.** `degraded` and
  `untrusted` are a judgement about how well the layer matches the page, which needs
  `grounded_rate` — U009's `core/health.py` demotes. Nothing ever promotes `no_text`.
- **`Probe.page_labels` reads the PDF's own `/PageLabels` table.** A mechanical readout of a
  structure the file carries — not a grammar, not a model reading — and the strongest form of
  §6.5's "text-layer-confirmed label". It is what makes the demo's printed-label column, and the
  off-by-one trap, real rather than notional.
- **Register A6 stays open, deliberately.** `plan()` ports `impl`'s all-or-nothing chapter check,
  so one over-cap chapter drops the whole plan. What changes is the consequence: the fall-through
  is a named `ladder_level_2_required`, not a blind fold. Sub-dividing an over-long chapter would
  be a blind cut inside it — F8's failure, wearing Level 1's name.
- **The raster cache is a `functools.lru_cache`, not a module-level dict**, so it cannot trip
  §12.5's module-level-mutable-store grep and cannot become the session store C11 struck. It is
  keyed on the file's content digest; the ingest path passes the probe's `content_hash` straight
  through, so a run hashes the file once.
- **`impl`'s `render_image` is not ported.** The standalone-image door resized with Pillow and
  saved a PNG; the corpus is PDFs (§2.1) and every line of it was about writing files.
- **Left for U008:** the S1 *call*. Step 04 here is a read of the content-addressable cache, and at
  M2a the replay fixture is the only backend that can fill it — `--vlm gemini` refuses
  `vlm_backend_unavailable` by name. The fixture reader (≈15 lines in `cli.py`) moves to
  `vlm/cache.py` with U008.

---

### U008 — The VLM boundary, cache keys, replay mode, and S2 extraction

**Milestone:** M2a · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — the unit's Demo Command, both halves (after `set -a && . ./.env && set +a`):

```
VSIR_VLM=stub VSIR_FIXTURE=data/fixtures/synthetic_3window \
  vsir ingest data/source/synthetic_3window.pdf --until extract
```
```
04 S1 document facts — cached per document, because the ladder rides on them ─
   backend      stub  (VSIR_VLM=stub, chosen by configuration — never by a code branch)
   facts_key    933fef7b9bfe5bd0…  (content hash ‖ gemini-3.8-flash-001 ‖ s2-v1)
   replay       data/fixtures/synthetic_3window/facts/933fef7b….json  (1,036 bytes, verbatim)
   title "C24 SYNTHETIC SAFETY MANUAL" · lang en · effectivity "from batch 68"

06 S2 extraction — the call that spends the money, and the receipt that avoids it
   schema       WindowOut · hash 585223c18e56d074a708294b… — computed from the schema,
                never a hand-bumped integer
   #   pages     origin   forms  sect  codes    bytes  extract_key
   1   1-14      replay      14    14     72   10,937  8c0238bce17af70b0b1fb528…
   2   15-28     replay      14    14    142   14,162  b5286f8c6ee00f5fdcc676ab…
   3   29-42     replay      14    14    141   13,987  b340f016d6b7ae33db4e4baa…
   42 page forms over 3 window(s); bisections this run: none
   the model returned 0 characters of page text: `text` has exactly one writer,
   ingest/probe.py (I2)

   window 1 (1-14) — the verbatim response, page_index 1 of 14
     {
       "codes": [],
       "lang": ["en"],
       "page_index": 1,
       "page_kind": "cover",
       "printed_page_no": "",
       "sections": [{"is_start": true, "title": "Front matter"}],
       "summaries": [{"lang": "en", "text": "This is the scanned cover sheet of the manual.
                       It shows the title, the revision and the validity statement, and it
                       carries no text layer at all."}],
       "topics": ["cover sheet", "revision"]
     }
     … 13 more page form(s); --raw prints the whole body
     page_index 1 is PDF page 1: abs = window.start + page_index - 1, computed in one place (§6.4)
```

(the JSON is printed indented and key-sorted; re-flowed here only for width). Step 06's six new
assertion rows, on top of U007's ten:

```
   PASS  42 page forms over 3 window(s)
         42 forms, 3 window(s), origins ['replay']
   PASS  page_index is window-local, and the offset resolves each form once (§6.4)
         window 2 starts at PDF page 15 and its page_index 1 is PDF page 15;
         42 distinct absolute pages of 42
   PASS  every page_kind is one of §5.2's eight, and matches the fixture
         ['cover', 'prose', 'schematic', 'table']
   PASS  one summary per language on every page, never a blended one (D5)
         42 pages, 42 summaries, 0 page(s) missing one
   PASS  the reattribution trap: a code reported on the page beside the one that prints it (F6)
         page 21 reports K122, which is absent from its own text and present in page 22's;
         both are inside window 15-28
   PASS  the ungrounded code: reported by the model, printed on no page (I2, F14)
         page 30 reports K999; it appears in 0 page texts
   PASS  no field in which the model could claim how far a section reaches (§5.2)
         SectionRef carries ['is_start', 'title']

ALL ASSERTIONS PASSED
first-exit=0
```

The second half — the prompt version bumped, so every key moves:

```
VSIR_PROMPT_VERSION=v2 VSIR_VLM=stub VSIR_FIXTURE=data/fixtures/synthetic_3window \
  vsir ingest data/source/synthetic_3window.pdf --until extract; echo "exit=$?"
```
```
04 S1 document facts — cached per document, because the ladder rides on them ─
   backend      stub  (VSIR_VLM=stub, chosen by configuration — never by a code branch)
   facts_key    e620476f383b869f…  (content hash ‖ gemini-3.8-flash-001 ‖ v2)

   REFUSED  fixture_miss: no frozen facts response for key e620476f383b869f… under
            data/fixtures/synthetic_3window/facts: replay mode never makes a live call and
            never invents one (D10)
exit=1
```

`bash scripts/test-unit.sh` → **730 passed**, Layer 0/1 PASSED (was 630).
`bash scripts/test-api.sh` → **137 passed** (unchanged; U008 adds no L2).

**Acceptance criteria — all eight met, with the test that proves each:**

| AC | Evidence |
|---|---|
| `extract_key` moves on prompt version, model id, dpi, any page image hash; identical otherwise | `test_extract_key_changes_with_every_input` (7 cases, incl. page **order** and page **count**), `test_extract_key_changes_with_prompt_version`, `test_extract_key_is_stable_for_identical_inputs` |
| unchanged when only `VSIR_VLM_TIER` flips | `test_the_tier_is_not_an_extract_key_input` — asserted on the *signature* of all four keys, so a key that cannot be given the tier cannot be keyed on it |
| `read_key` differs for a different question | `test_read_key_for_the_same_pages_but_a_different_question_differs`, plus `test_read_key_carries_every_extract_key_input_too` |
| a network spy records **zero** outbound calls across a full `--until extract` run | `test_a_full_until_extract_run_makes_zero_outbound_calls` — and the spy has its own negative control, `test_the_network_spy_would_notice_a_call` |
| a key absent from `VSIR_FIXTURE` is typed `fixture_miss`, no call, no fabrication | `test_a_miss_mid_run_refuses_without_calling_anything` (S1 present, S2 absent — the miss lands *at step 06*), `test_a_key_the_fixture_does_not_hold_is_a_typed_miss` |
| `WindowOut` validates against §5.2 exactly | `test_the_models_carry_exactly_the_fields_the_spec_lists`, `test_page_index_is_required_and_window_local`, `test_the_page_kinds_are_the_eight_of_the_spec_and_a_stray_one_normalises`, `test_a_bilingual_page_gets_one_summary_per_language`, `test_codes_and_topics_are_lists_of_strings`, `test_the_frozen_corpus_validates_against_the_schema` |
| an AST scan finds no regex taxonomy, no classification enum, no per-corpus keyword list | `test_no_regex_taxonomy_in_extraction_or_at_the_boundary`, `test_no_classification_enum_…`, `test_no_per_corpus_keyword_list_…` (scans every string collection in `extract.py` and `vlm/` for corpus vocabulary), `test_the_struck_names_of_the_old_shape_are_gone` |
| no test-only branch; the backend is one config lookup with no conditional import | `test_no_test_only_branch_in_the_production_path` (§12.5 grep), `test_both_backends_are_imported_unconditionally_at_module_scope` (AST), `test_the_backend_is_selected_by_configuration_alone` |

**Invariants / failure rows closed:** **F11 (key half)** — every cache key carries the resolved
model id and the prompt version, so a cache cannot serve output from a different model or a
different prompt (`test_extract_key_changes_with_prompt_version`, and the corpus-level proof that
bumping `VSIR_PROMPT_VERSION` makes the whole fixture unfindable rather than stale). F11's boot
half was closed at U001. No invariant is asserted here (Spec §9 assigns none to this unit).

**Register items closed:** **B2** (S1 is cached, per document, under `facts_key` — `impl` re-bills
it on every run and its contents list is what picks the window ladder, so a different answer
silently re-cuts the document and re-bills all of S2 behind it), **B6** (the pinned model is
re-verified at the point of spend, not only at boot). **B1**'s provenance concern is addressed by
the `Entry` sidecar: `finish_reason` and `usage` travel with every frozen response, so a bare
`{"pages": […]}` is never an unidentifiable orphan.

**Notes**

- **A real defect was found and fixed while testing the client.** The pin check (`_pinned`) was
  inside `_call`, which is inside the retry loop's `try`, so a floating model id was **retried
  three times** — `VlmUnavailable`'s own class name contains `unavailable`, which is one of
  `impl`'s `RETRYABLE` markers — and then surfaced as `vlm_call_failed` rather than the named
  refusal F11 asks for. The pin is now resolved once, before the rate-limit token is spent and
  before the loop; and the loop re-raises any `VlmError` of ours ahead of the retry test, because
  a typed refusal is the answer, not a failure to get one
  (`test_a_floating_model_id_is_refused_at_the_point_of_spend` asserts the call was never made).
- **`facts_key` and `extract_key` moved out of `ingest/window.py` into `vlm/cache.py`**, which is
  where the plan's Deliverables put them, and every frozen response's name moved with them: the
  digest is now over **length-prefixed** inputs. That is not cosmetic — with a plain separator
  `("a|b", "c")` and `("a", "b|c")` collide, and one of those inputs (`prompt_version`) is
  operator-supplied (`test_two_different_input_splits_cannot_share_a_key`). The committed fixture
  is regenerated under the new names; `data/fixtures/synthetic_3window/facts/93061d0c….json` is
  replaced by `933fef7b….json`.
- **The demo's second half refuses at step 04, not step 06.** `prompt_version` is an input to
  `facts_key` as well as `extract_key`, so the earliest key that moves refuses first. That is the
  correct behaviour — the run never proceeds without document facts — and the *extract*-side miss
  is proved separately, at the step where it bites, by
  `test_a_miss_mid_run_refuses_without_calling_anything`.
- **The prompt digest is a second guard the cache key cannot provide.** `prompt_version` is a
  label, and a label describes the text only while the two move together; editing `s2.md` without
  releasing a new version fails `prompt_unavailable` by name rather than serving cached output
  produced by instructions that no longer exist. `PROMPT_DIGESTS` is the published digest per
  version, and the two prompts are asserted to still carry §5.2's binding rules — the summary rule
  verbatim, "presence, never extent", and all eight `page_kind` values.
- **`VSIR_VLM_TIER=batch` is refused by name, not silently downgraded.** The Batch API submission
  path is not built; serving a batch request from the standard endpoint would bill a full-corpus
  run at twice the rate the programme's cost basis assumes and report success. Because the tier is
  **not** a key input, a run started on `standard` can be finished on `batch` for free when that
  path lands.
- **`VSIR_VLM_RPM` is new configuration** (default 60), added to `.env.example`: the client's token
  bucket, in calls a minute. It bounds the burst, never the total — `impl` rate-limits nothing, so
  a full-corpus run's opening move is to fire every window at once and then serve out its own 429s
  at exponentially increasing delay, one wasted round trip per window in the stage that is 99 % of
  spend.
- **One test file beyond the plan's three:** `backend/tests/unit/test_vlm_client.py` (24 tests). The
  plan lists `test_extract_schema.py`, `test_cache_keys.py` and `test_replay.py`, and all three are
  here; the client's own guarantees — the pin at the point of spend, the prompt digest, the token
  bucket, the retry ladder, the truncation refusal, the credential never in a `repr` — needed a
  home, and each injects the transport or the clock, so nothing in it opens a socket. It is what
  caught the defect above.
- **The S2 fixture is a transcript, not a rule.** `vsir.eval.synthetic_pdf` writes one frozen
  `WindowOut` per window, deterministic in the page number so the corpus stays reproducible byte
  for byte, and wires in two hazards the next unit needs: page 21 reports **K122**, which is
  printed on page 22 and inside the same window (the F6 reattribution trap), and page 30 reports
  **K999**, which is printed on no page at all (the I2/F14 ungrounded code). The generator computes
  the keys with the pipeline's own functions, so a change to any key input rewrites the fixture
  under new names on the next run rather than leaving a stale hit.
- **Left for U009:** every one of those two traps is only *armed* here. The move itself, the
  `moved_from` record, `grounded_rate` and the offset proof's second check (an independent
  observation that a model-read `printed_page_no` phrase-matches **this** page's text) are
  derivation's, and so is `core/health.py`.

---

### U009 — Derivation, health signals, label attribution, and stitching

**Milestone:** M2a · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — `vsir ingest data/source/synthetic_3window.pdf --vlm stub --until stitch`
(after `export VSIR_FIXTURE=data/fixtures/synthetic_3window`):

```
07 derivation — the claim beside the evidence, and both checks of the offset proof
   §6.4 check (1) structural: every window returned page_index 1..N, so abs = window.start +
   page_index - 1 resolves each form once
   §6.4 check (2) independent observation: 40 model-read label(s) phrase-match their OWN page's
   text; a match on a neighbour raises OffsetError
   grounded_rate median 1.0 over the 40 page(s) that have text — the 2 that do not rate None and
   are ignored by the aggregate (§5.7)
   text_trust ok · searchable_ratio 0.95 · no allowlist gate, no identifier grammar, no keyword
   list (§2.4, §2.5 B)
   reattributed K122: page 21 -> 22, inside window 15-28 (F6)
   ungrounded K999 on page 30: printed on no page, so it stays put, counts against that page's
   grounded_rate and never enters `text` (I2)

   page  page_id                      label  ver  grounded  codes in_text  moved_from / flags
      1  synthetic-3window@1.0#p001   i      true        —      0       0  no_text
      2  synthetic-3window@1.0#p002   ii     true        —      0       0  no_text
      3  synthetic-3window@1.0#p003   1      true     1.00      2       2
     …
     21  synthetic-3window@1.0#p021   19     true     1.00     10      10
     22  synthetic-3window@1.0#p022   20     true     1.00     10      10  K122<-p021,codes_reattributed
     30  synthetic-3window@1.0#p030   28     true     0.91     11      10  ungrounded_codes

08 stitching — the window folds deleted again, and section extent created once
   9 section(s) from 42 per-page sighting(s) — extent is (min, max) over sightings and is created
   here, nowhere else (§5.2)
   section_id and series_id are keyword ARRAYS: a straddling page carries both, and a scope
   matches on any element (§5.3, F8)

   section_id                   pages     start  obs  folds   series_id / title
   synthetic-3window@1.0#s004   13-17        13    5  [14]    …#s:emergency-stop-chain
   synthetic-3window@1.0#s007   27-31        27    5  [28]    …#s:light-curtain-muting
   "Emergency stop chain" crosses the window fold at 14|15 and carries ONE section_id on all 5 of
   its pages: [13, 14, 15, 16, 17]
   "Light curtain muting" crosses the window fold at 28|29 and carries ONE section_id on all 5 of
   its pages: [27, 28, 29, 30, 31]

assertions — data/fixtures/synthetic_3window/expected.json
   … 16 rows from steps 01-06 …
   PASS  every record's `text` is the probe's, character for character (I2, §12.5)
         42/42 pages match probe_text[page_no]; ingest/probe.py is the only writer
   PASS  abs_page == window.start + page_index - 1 on every emitted page (§6.4)
         pages 1-42, 42 record(s), each page_id built from its own absolute page
   PASS  the off-by-one trap: a window shifted by one page is caught by the independent
         observation, not by luck (I4, F7)
         window 15-28 shifted to 16-29 raises offset_check_failed: label "13" is printed on page
         [15], not on 16
   PASS  grounded_rate is None exactly where has_text is false, and the median ignores those
         pages (§5.7)
         pages [1, 2] rate None; the median over the remaining 40 is 1.0
   PASS  every printed label is the one the page carries, and none was picked silently (§6.5, F5)
         42/42 labels confirmed against the page itself; 0 ambiguous, 0 interpolated
   PASS  the reattributed code moved to the page whose text prints it, and said where it came
         from (F6)
         K122 left page 21 and arrived on 22 as
         [{'code': 'K122', 'from_page_id': 'synthetic-3window@1.0#p021'}]
   PASS  the ungrounded code stayed put, cost its page grounded_rate, and is in no page's
         codes_in_text (I2, F14)
         K999 is still on page 30, whose grounded_rate is 0.909; it appears in 0 codes_in_text
         list(s) and 0 page text(s)
   PASS  9 sections with the extent the fixture declares
         9 section(s): 1-2 · 3-8 · 9-12 · 13-17 · 18-22 · 23-26 · 27-31 · 32-36 · 37-42
   PASS  a section cut by a window fold is ONE section, on both sides (F8)
         ['Emergency stop chain', 'Light curtain muting'] cross the fold(s) at [14, 28]
   PASS  every page of a straddling section carries the same section_id, as an array (§5.3)
         one id across each fold; series_id carries no revision, so a scope on it survives one

ALL ASSERTIONS PASSED
```

`bash scripts/test-unit.sh` → **835 passed** (was 761) including the §12.5 conformance greps.
`bash scripts/test-api.sh` → **137 passed**, the §12.4 abstention eval among them.

**Invariants/failure rows closed:** F5 (M2a half — label precedence, `label_verified`, ambiguity →
a list) · F6 (per-page `grounded_rate` + reattribution recording `moved_from`) · F8 (stitching half
— canonical section key + carry-in across the fold, `series_id` written). I4's two checks are
**implemented** here and asserted by U011's gate, per Spec §9. I2's structural half — the §12.5 L1
assertion `record.text == probe_text[page_no]` — now exists and passes on all 42 pages.

**Notes**

- **A spec correction was required before the unit could be written, and it was load-bearing.**
  §5.7 defined `codes_in_text` as `seen & have` with `have = token_set(page.text)` — a whole-token
  set intersection. That cannot see a multi-token code, and three other passages of the same spec
  require that it can: §6.8's own worked export row contains `"sf 1.2a"`, and §5.6 says `impl`'s
  adjacent-token joins are **not** ported because "multi-token labels are handled by phrases plus
  `variants()`". Measured on this corpus, the set intersection grounds 6 of a typical page's 10
  codes — `SF 1.3A`, `EAO 84-5140.1003`, `LC1-D38BL` and `ZB4-BS844` all fail — for a document
  median of **0.6**, under §11.1's 0.8 blocking gate. A healthy document would have been
  quarantined. §5.7's snippet and §2.3's C8 row now ask the phrase question, which is the one
  `exact_filter` asks the index (I3). No other section changed.
- **`core/exact.py` gained the Python spelling of that question** — `contains_phrase`,
  `printed_in`, `printed_on` — rather than derivation growing a matcher of its own. It is one
  function family beside the filter it mirrors, and `core/nearmiss.py::is_printed` now delegates
  to it instead of carrying a second copy. A deliberate extension of the unit's file list, for
  I3's sake: two implementations of "is this printed here?" is exactly the drift `impl`'s guide
  records having had once already.
- **`content.moved_from` was `list[str]` and is now `list[MovedCode]`** (`{code, from_page_id}`),
  which is what §6.5 and the unit's AC specify. A bare code records that something moved and loses
  the one fact a reviewer needs. `content.label_candidates: list[str]` is new for the same reason:
  F5's ambiguity has to land somewhere, and `printed_page_no` stays **empty** when it fires —
  putting a candidate there is the silent pick the row is about.
- **The off-by-one check looks at the immediate neighbours only, which is §6.4's rule verbatim.**
  The argument for why that is sufficient is now asserted rather than assumed: a shift larger than
  one makes two windows claim the same pages, and `derive` refuses on a derived page set that is
  not exactly `1..page_count` (`check="coverage"`). Widening the band to a document-wide search
  was considered and rejected — it would raise on any page whose printed label happens to be
  mentioned elsewhere in the binder, and the repair for a false positive is a re-billed window.
- **Two `impl` defects were not ported.** Guide 07 §7.1's contested-head bug — `head_page_uncertain`
  fired only when *no* page claimed the head, so a unit with four competing claims came out
  certain — is fixed as the guide asks: the declaring pages are counted and anything other than
  exactly one is uncertain. And `to_pages`'s *"log a warning and drop the page"* on an out-of-range
  index is gone; that path is now a typed `offset_check_failed` that bisects.
- **A code printed on *both* neighbours does not move.** §6.5 says a sighting moves "to the page
  whose text contains it", singular. Where two adjacent pages qualify, the page keeps the sighting,
  flags `ambiguous_reattribution` and pays for it in `grounded_rate` — resolving the tie by picking
  a side is the shape of F5.
- **Page-level trust thresholds are pins, not configuration:** `ok >= 0.8` (the same number §11.1
  gates the median on, deliberately one number and not two), `untrusted < 0.2`. Both are marked
  provisional pending the M2b distribution (R4). §11.3's document-level collapse reaches the pages
  through `health.demote`, and never overwrites `no_text`.
- **Follow-up for U017:** `resolve` must read `content.label_candidates` as well as
  `printed_page_no`, or an ambiguous page becomes unresolvable by any label. F5's M4 half already
  requires *"ambiguity → **every** candidate at `resolve`"*, so this is where the candidates come
  from.
- **Left for U011:** `safety_flag` (§6.8) is computed from `doc_type` + `topics`, both present on
  the record now, but it belongs to the export and is not written here. The §11.1 gates read
  `Derivation.health` — `grounded_median`, `fully_scanned`, `searchable_ratio` — which this unit
  produces and nothing yet enforces.

---

### U010 — Embedding, the three surfaces, the fingerprint, and indexing

**Milestone:** M2a · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — the plan's Demo Command, against the test stack's Qdrant on 6335:

```
$ vsir ingest data/source/synthetic_3window.pdf --vlm stub --until index && \
  VSIR_EMBED_MODEL=some-other-embed-model \
    vsir ingest data/source/synthetic_3window.pdf --vlm stub --until index; echo "exit=$?"

09 embedding — one page, one fused vector, and the receipt that avoids the re-bill
   backend      stub  (VSIR_VLM=stub selects the embedding backend too: one switch for
                'does this release spend')
   model        gemini-embedding-2 · dim 1536 · composition d4-fused-v1 · task_type is never
                sent (D4)
   fingerprint  45a09c588c25422c  {'embed_model': 'gemini-embedding-2', 'dim': 1536,
                'distance': 'cosine', 'composition_version': 'd4-fused-v1'}
   collection   vsir_pages_1536 (created) · control plane vsir_runs · the §6.6 fingerprint is
                settled BEFORE a single vector is bought
   42 page(s) · 42 embedded, 0 reused from the index by embed_key (register B5) · 0 character(s)
   of page text dropped by the 2000-char cap, counted rather than silently cut

   the composed Content for synthetic-3window@1.0#p042 — 6 text Part(s), then the raster, all in
   ONE types.Content (D4, D8)
   #    chars  part
   1       27  'C24 SYNTHETIC SAFETY MANUAL'
   2       26  'Part numbers and suppliers'
   3      336  'Page 40 covers part numbers and suppliers stage 40 within the pa…'
   4       51  'part numbers and suppliers · wiring · stop category'
   5       78  'SF 3.42B B242 K142 SI3 X20SI4100 Q92 LC1-D38BL S342 EAO 84-5140.…'
   6      526  'Electrical references and part numbers Part numbers and supplier…'
   7   125655  the page raster @ dpi 150 (dpi_index), long edge bounded to 1568 px — the LAST Part
   1 summary Part(s), one per language: a two-language page is never one blended string (D5, D8)
   embed_key    27da2d92c63e711e09652989…  (composition version ‖ gemini-embedding-2 ‖ the
                composed string)

10 indexing — one point per page, three surfaces, every one is_current=False
   42 point(s) upserted into vsir_pages_1536 · 40 carry the `lexical` surface · 42 carry
   `captions`, which impl declares, weights 0.4 and never writes (register D3)
   page_id                    is_current  point_id = uuid5(NAMESPACE_URL, page_id)
   synthetic-3window@1.0#p001 false       91e615c7-f4da-57bd-b422-c757ca693321
   synthetic-3window@1.0#p002 false       bedb39d2-6c27-5abd-a45e-98fd8d9d7299
   …
   synthetic-3window@1.0#p042 false       (42 rows, each id recomputed independently below)
   nothing is queryable yet: step 11 is the only thing that flips is_current, and every tool
   injects is_current=True server-side (I7, §6.7)

assertions — data/fixtures/synthetic_3window/expected.json
   … 26 rows from steps 01-08, all PASS …
   PASS  one page, one fused vector — 42 pages, 42 vectors (I1, D4)
         42 composition(s), 42 vector(s), dim [1536]
   PASS  every text part is its own Part, and the raster is the last one (D4, D8)
         248 text Part(s) over 42 page(s); 40 carry page text, and every composition ends with
         the dpi 150 raster
   PASS  embed_key is per composition, so an unchanged page is free next run (B5)
         42 distinct key(s) for 42 page(s); 0 reused this run
   PASS  42 point(s) written, one per page (I1)
         42 upserted into vsir_pages_1536
   PASS  point_id == uuid5(NAMESPACE_URL, page_id), recomputed independently (§5.1)
         42/42 match; a re-ingest therefore overwrites rather than doubling (F12)
   PASS  every point is is_current=False until the gates pass (I7, §6.7)
         42/42 read back false
   PASS  no payload names a file — there is no image_path (§5.3, register A5)
         forbidden keys present in 42 payload(s): none
   PASS  the stored dense vector is the one step 09 composed, unchanged
         42/42 vectors of dim 1536 read back; largest component drift 3.68e-09 — float32
         storage, not a different vector
   PASS  the `captions` surface is written, and shares no token with `lexical` (D3)
         42/42 page(s) with summaries or topics carry a non-empty captions vector;
         dedupe(against=text) left 0 already-printed token(s) in it
   PASS  re-running the same write overwrites in place: the count is unchanged (I1)
         upserted 42 again, and the collection still holds 42 point(s) for this (doc_id, revision)

ALL ASSERTIONS PASSED

  ── then, with the embedding model changed ──────────────────────────────────────────────────

09 embedding — one page, one fused vector, and the receipt that avoids the re-bill
   model        some-other-embed-model · dim 1536 · composition d4-fused-v1
   fingerprint  97cd85691bdaf6fa  {'embed_model': 'some-other-embed-model', …}

   REFUSED  embed_fingerprint_mismatch: vsir_pages_1536 was embedded under a different recipe
   (embed_model: stored 'gemini-embedding-2' != configured 'some-other-embed-model'). Refusing to
   upsert: a vector made one way cannot be compared with one made another, so the remedy is a NEW
   collection, a full re-embed of every document into it, and an alias swap — never an in-place
   mix (§6.6). Nothing was written
exit=1
```

The refusal lands **before any vector is bought** and the collection is untouched: 42 points, the
original `embed_key`, and the stored fingerprint still `gemini-embedding-2`. Re-running the first
command reports `0 embedded, 42 reused` — register B5, closed with the index as the store.

`bash scripts/test-unit.sh` → **898 passed** (was 835) including the §12.5 conformance greps.
`bash scripts/test-api.sh` → **165 passed** (was 137), the §12.4 abstention eval among them.

**Invariants/failure rows closed:** none is *asserted* here by Spec §9 — I1's post-publish count
and I7's publish gate are U011's. What lands here is the half each rests on: `point_id =
uuid5(page_id)` and `is_current=False` on every write, both asserted by the demo and by
`tests/api/test_index_upsert.py`. Register items closed: **B5** (embeddings cached by `embed_key`)
· **D3** (the `captions` surface is finally written) · **E7's idempotent half** (a re-ingest
overwrites; the retirement rule that removes a *vanished* page is U011's) · **A5** (no payload
names a file, asserted on the live payload) · **B6/F11** (the embedding pin is re-checked at the
point of spend, not only at boot).

**Notes**

- **Where the §6.6 fingerprint lives, and why.** Qdrant has no collection-level metadata and §4.2
  allows exactly two collections, so the record is a point in the **control plane** — `vsir_runs`,
  payload-only, one point per pages collection, discriminated by `kind: "fingerprint"`. U011 will
  add `kind: "run"` and `kind: "window"` beside it. The alternative — a sentinel point inside
  `vsir_pages` — was rejected: that collection's point count is what I1 asserts. `dim` and
  `distance` are still checked the other way too, read back off the live collection by
  `core.indexed.schema_problems` at boot; `embed_model` and `composition_version` are not
  observable from Qdrant at all, which is why the record exists.
- **`VSIR_VLM` selects the embedding backend as well as the VLM.** No new environment variable:
  one switch for *"does this release make live model calls"*, so a run that replays S2 from a
  fixture cannot quietly spend on 42 embeddings. Two switches would let `VSIR_VLM=stub` plus a
  live embedder past every guard the first one exists to provide.
- **The stub embedder computes rather than replays, and that is a deliberate difference from the
  S2 stub.** There is nothing worth freezing in 1,536 floats — a fixture of them is unreviewable
  and no more truthful than a hash — and the property the tests need is that the *same composition
  always gives the same vector* and a changed one does not. That is what proves the composition is
  what gets embedded, which is the one thing about this step the spec constrains. Safe here and
  not for S2 because nothing downstream asserts what a vector *means*: it orders candidates, and
  every path that can reach an answer goes through the exact surface (I2, I3). A fabricated
  `WindowOut`, by contrast, would put invented codes into records the whole system then treats as
  observations — which is why D10 refuses one.
- **The embedding cache is the index itself.** `ingest/index.py::cached_vectors` reads the dense
  vector and the `embed_key` already on a page's point; step 09 reuses it when the key matches and
  re-bills otherwise. That closes B5 with **no new store, no local disk and no extra collection**
  (§15 Factor VI) — and it is safe by construction, because a reused vector can only come from a
  collection whose fingerprint already matched and whose key already encodes the model, the
  composition version and the composed string.
- **Two new store-backed steps, and they refuse rather than degrade.** `embed` and `index` are the
  first `--until` targets that need Qdrant (`cli.STORE_BACKED_STEPS`), and with no store both exit
  `qdrant_unavailable` (§11.3). Running anyway would be wrong in both directions: it would re-bill
  every vector the index already holds, then report a document that was never written.
- **The two L0 environment blocks now point at `127.0.0.1:6399`, a port nothing serves.** They
  said `localhost:6333`, which on this machine is a *live* Qdrant belonging to another project.
  Nothing at L0/L1 reached it before, and the two new steps would have. `test_doctor.py` and
  `test_replay.py` already used 6399; the unit layer is now uniformly unable to touch a store, and
  the two store-backed steps are asserted at L0 by their refusal instead.
- **The printed page label is not a composition part.** `impl` prefixes `page ` onto a label that
  already reads `Page 1 of 55` and embeds the result on every page of the corpus (guide 08 §5.4).
  §5.3's order does not carry the label at all, and a printed label is `resolve`'s question,
  answered from an indexed facet rather than by nearest neighbour — so the part goes and the
  cosmetic defect goes with it.
- **Truncation is counted.** `impl` cuts `text[:4000]` and `units[:6]` and counts neither, so
  nothing would tell you when a corpus started losing page tails. `Composition.text_dropped`
  records it per page and the CLI prints the document total (0 on this corpus, whose longest page
  is under the 2,000-char cap).
- **Qdrant normalises a cosine vector on write, and keeps float32.** Both had to be discovered:
  the first makes a round trip preserve direction and not magnitude, the second puts a component
  ~1e-9 from what was sent. The read-back assertion therefore compares the *unit* vector within a
  stated tolerance (`cli.VECTOR_STORAGE_TOLERANCE`, 1e-6) rather than by rounded equality — with
  1,536 components, some value always lands next to a rounding boundary. A rounded check passed on
  the stub's already-normalised vectors and would have failed on the first real Gemini ingest.
- **Deliberate extension of the unit's file list:** `cli.py` (steps 09-10 and their assertion
  rows — the unit's Demo Command is `--until index`, which cannot exist without it), plus the two
  L0 environment blocks above and `test_ingest.py`'s step parametrisation. Nothing in `core/` or
  in another unit's module changed.
- **Cost line for M8 (plan R9):** per-page image embedding is unbudgeted — ≈ $0.66 for a full
  5,505-page run at $0.00012/image (Spec §2.3 C12). It is a cost-model line, not a design change;
  recorded here so U026's scale-out costing includes it.
- **Left for U011:** the gates and the `is_current` flip, the three-clause retirement rule, and
  the run/window points that will share `vsir_runs` with the fingerprint record written here.
  `index.count(client, name, scope)` is in place for I1's post-publish `count(doc, rev) ==
  pdf.page_count` assertion.

---

### U011 — Gates, publish, retirement, the run control plane, and exports

**Milestone:** M2a · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — the plan's and Spec §13's Demo Command, against the test stack's Qdrant on 6335:

```
$ vsir ingest data/source/synthetic_3window.pdf --vlm stub && vsir runs show <run_id>

11 gates and publish — the only thing that flips is_current, and it flips nothing until the gates
   gate             verdict      metric  detail
   window_coverage  PASS              1  blocking
                     42/42 page(s) carry an S2 record
   offset_check     PASS              1  blocking
                     3 window(s) passed both §6.4 checks
   grounded_rate    PASS              1  blocking
                     median 1.0 over the 40 page(s) with a text layer (the 2 without one rate
                     None and are ignored by the aggregate, §5.7)
   text_coverage    PASS         0.9524  disclosing
                     40/42 page(s) have a text layer (searchable_ratio 0.95)
   label_monotonic  PASS              0  disclosing
                     40 page(s) carry a numeric printed label, non-decreasing across all of them

   state        published at 2026-09-10T02:26:17+00:00
   pages        42 point(s) of synthetic-3window@1.0 are is_current=True — and 42 is the PDF's
                page count (I1)
   flags        —          overrides    —
   retirement   {'deleted_stale_points': 0, 'superseded_demoted': 0,
                 'other_revision_points_kept': 0}
   exports      GET /runs/01M24J64SB8335ZW8A8AQEPYX6/export/labels.jsonl and
                /observed_tokens.jsonl — streamed from the index, 0 bytes written to disk (§6.8)

   PASS  42 page(s) queryable after publish, one per PDF page (I1)
         count(doc_id=synthetic-3window, revision=1.0, is_current=True) = 42
   PASS  every page_id is unique, so one page is one point (I1)
   PASS  the run record is in the control plane, not in this process (D9, E2)
         vsir_runs holds run 01M24J…: state published, step publish, 5 gate result(s), lease
         released (none)
   PASS  labels.jsonl streams one line per page with the §6.8 field set
         42 line(s), fields [codes_in_text, doc_id, dpi, grounded_rate, label_verified, page_id,
         page_no, printed_page_no, prompt_version, revision, safety_flag, sections, summaries,
         vlm_model]
   PASS  observed_tokens.jsonl streams one line per document (§6.8, C7)
         1 line(s); 265 code-like token(s) observed over 40 searchable page(s)

ALL ASSERTIONS PASSED

$ vsir runs show 01M24J64SB8335ZW8A8AQEPYX6
run          01M24J64SB8335ZW8A8AQEPYX6
document     synthetic-3window@1.0 · release dev-0 · schema 1
state        published · step publish · windows 3/3 · pages_indexed 42 of 42
lease        — until — (not live)
published_at 2026-09-10T02:26:17.637402+00:00 · flags —
cost         {'input_tokens': 0, 'output_tokens': 0, 'cache_hits': 0, 'vlm_calls': 3,
              'embeddings_billed': 42, 'embeddings_reused': 0}
retired      {'deleted_stale_points': 0, 'superseded_demoted': 0, 'other_revision_points_kept': 0}
[the five gate rows, as above]
```

The second run of the same command: **`0 embedded, 42 reused` · 42 points · still 42 queryable** —
`point_id` is idempotent, so re-ingest overwrites and the totals do not double (I1, F12).

`bash scripts/test-unit.sh` → **947 passed**, Layer 0/1 PASSED (conformance included).
`bash scripts/test-api.sh` → **226 passed** against `qdrant/qdrant:v1.19.0` and the container.

**Invariants / failure rows closed**

- **I1** — `count(doc_id, revision, is_current=True) == pdf.page_count` after publish, every
  `page_id` unique (`test_publish_page_count_and_unique_point_id`, L2).
- **I4** — the `offset_check` gate requires both §6.4 checks on **every** window; a window that
  failed either blocks and is named (`test_offset_check_catches_shifted_pages`, L2).
- **I7** — `is_current=False` until every blocking gate passes; a blocked or killed run leaves
  **zero** queryable pages (`test_unpublished_run_zero_queryable_pages`,
  `test_kill_mid_run_zero_queryable_pages`, L2).
- **F4 (M2a half)** — `text_coverage == 0.0` **skips** the `grounded_rate` gate entirely and the
  document publishes with `mostly_scanned` (`test_fully_scanned_document_publishes`, L2).
- **F7** — the offset proof is a blocking gate (`test_offset_check_catches_shifted_pages`, L2).
- **F12 (M2a half)** — retirement clause 1, scoped to the same `(doc_id, revision)`
  (`test_reingest_twice_same_point_count`, `test_a_shrinking_reingest_deletes_the_pages_that_are_gone`).
- **F17** — a half-finished run answers nothing (`test_kill_mid_run_zero_queryable_pages`,
  `test_sigterm_checkpoints_the_run_as_stopped_and_publishes_nothing`, L2).
- **F9's evidence preserved** (closed at M8, not claimed here): clause 2 demotes and **keeps** the
  prior revision (`test_publishing_new_revision_keeps_prior_points`, L2).
- Spec §20.1 register items **E1** (HTTP never called `export()`), **E2** (job state as a dict on
  daemon threads), **E4** (no cost observability), **E7** (orphan points on a shrinking re-ingest).
- **D1**, **D9** owned; **SA-8** (the §15.1 "queue claim" *is* the run-granularity advisory lease)
  and **SA-10** (clause 3's regression test) both discharged.

**Notes**

- **Only `grounded_rate` takes an override, and that is a decision.** §11.1 offers exactly one, and
  `gates.OVERRIDABLE` is that list. `window_coverage` failing means pages are missing from the
  index and `offset_check` failing means the pipeline cannot say which sheet a record describes —
  neither is a judgement about a threshold, so no reason an operator types makes them publishable.
  `check_override` refuses both by name and says why.
- **`skipped` is not `pass`.** A fully scanned document's `grounded_rate` result carries
  `skipped: true, metric: null` rather than a pass with a number — the same rule as §5.7's `None`,
  one level up: reporting a measurement nobody made is how the M2b threshold gets set from a
  fiction. The worst-pages list is populated **only when the gate holds the document**, because on
  a published one it is a list of its best-behaved pages presented as a warning.
- **`label_monotonic` compares only the labels that are plain integers.** The corpus runs
  `i, ii, 1 … 40`; a check that ranked `ii` against `1` would flag every document in the corpus,
  which is the fastest way to make a disclosure flag mean nothing. Unlabelled pages are skipped
  rather than compared as zero.
- **The run point is claimed at step 01, not at step 09.** A store-backed run has to be a run that
  *exists* before the first model call, or a kill at window 2 of 3 leaves nothing to resume and
  nothing to report (register E2). The visible consequence: with no reachable Qdrant,
  `--until embed|index|publish` now refuses `qdrant_unavailable` **before** S2 rather than after
  it — a strictly earlier, strictly cheaper refusal with the same typed code.
  `test_the_store_backed_steps_refuse_by_name_with_no_store` was updated to assert exactly that,
  and asserts that steps 06, 09, 10 and 11 never run. No requirement weakened.
- **The lease is advisory and the code says so where it matters.** Qdrant has no compare-and-swap,
  so `claim` cannot be mutual exclusion; what makes a duplicated worker safe is I1 and I7, and the
  `--steal` test asserts the final point count is still `pdf.page_count`. A duplicated worker is a
  **cost** bug, not a corruption bug.
- **`SIGKILL` cannot leave `state: stopped`** — no handler runs. Spec §13's M2a acceptance says
  "the run `state: stopped`"; the plan's AC reconciles it as "`stopped` (or `running` with an
  expired lease)", and both paths are tested: `SIGTERM` checkpoints `stopped` and releases the
  lease, `SIGKILL` leaves `running` with a lease that expires. **Zero queryable pages either way**,
  which is the property F17 names.
- **`published_with_override` is stamped additively**, grouped by the flag set a page ends up with:
  a single filtered write of one constant list would erase the per-page disclosures derivation put
  there (`ungrounded_codes`, `label_ambiguous`, …). Asserted by
  `test_an_override_keeps_the_flags_derivation_put_on_a_page`.
- **`safety_flag` is configuration, and the AST scan is the guard.** `VSIR_SAFETY_DOC_TYPES` and
  `VSIR_SAFETY_TOPICS`, both empty by default and both in `.env.example`. `impl`'s keyword list is
  named in the *test* and asserted absent from the module — including the stronger form, that the
  module declares no module-level collection of strings beyond the §6.8 field sets. Matching is
  membership, not substring: a substring rule is how a keyword list grows back one `in` at a time.
- **The exports touch no disk, checked twice**: an AST scan (no write call, and no `pathlib`/`os`/
  `shutil`/`tempfile` import at all) and a spy over `open` while a whole document is exported.
  `withheld.jsonl` is a typed `404`, not an empty stream — an empty `200` would let a consumer
  conclude the document withheld nothing.
- **§11.4's gauges are recomputed from `vsir_runs` per scrape.** No client library was added
  (§4.2): the Prometheus text format is ~20 lines, and what a library would buy is a process-wide
  counter registry, which is the in-process state §15 Factor VI rules out.
- **The serving process opens a second Qdrant client** (`CONTROL_TIMEOUT_S = 30`) for the run and
  export endpoints. One timeout cannot be both honest answers: a probe that waits 30 seconds fails
  to fail, and an export of a 1,440-page manual that gives up after 2 is a truncated contract
  artefact.
- **Deliberate extensions of the unit's file list:** `config.py` and `.env.example` (the two
  `safety_flag` variables — §6.8 requires them and §15 III says where they live);
  `tests/unit/fake_store.py` (`Range` conditions and real scroll paging, both of which the export
  needs and neither of which the fake had); `tests/unit/test_ingest.py` (the refusal-point change
  above); `tests/api/test_kill_mid_run.py` also drives `runs show` / `gates rerun` /
  `publish --override` as real subprocesses, because it already owns the real-CLI fixture.
- **OQ-3 / OQ-7 unchanged and still open:** exports are served over HTTP per §6.8 and nothing is
  written to local disk. If Part A needs files, the answer is an attached object store, never the
  instance's filesystem. Due before M8.
- **Post-audit fix (the milestone gate's one ✗): §6.4's repair is now wired into the CLI.**
  `derive()` has always accepted a `reextract` callable and `test_derive_offset.py` proved the
  bisection with a test-supplied one — but `cli.py` passed none, so on a real `vsir ingest` a
  check-(2) failure **re-raised** instead of bisecting. I4 as Spec §9 words it ("a failure bisects
  and re-bills") therefore did not hold end to end. The CLI now passes
  `extract_module.extract_window` as `reextract`, so each half is billed through the same door as
  a planned window and gets its own `extract_key` over the pages it covers (§6.3). New L2 suite
  `tests/api/test_offset_repair.py` proves it on a **doctored replay corpus**: the checked-in
  fixture copied to a tmp dir with window 2's labels rotated by one and both halves frozen under
  their own keys — a real ingest bisects, re-bills, publishes all 42 pages, files no page under the
  failed response's receipt, and records `bisected: true` on that window's control point.
- **And the gate's blocking path is now reachable from the pipeline.** `cli._offset_blocked` writes
  the failing window with `offset_ok=False`, evaluates §11.1 and leaves the run **`gated`** with
  the window named and zero pages queryable, instead of dying with a traceback. `_record_failure`
  will not downgrade a `gated` (or `published`) run to `failed`: a gate decision names the gate,
  and `failed` names only a category. The reachable end-to-end failures *downstream* of the repair
  are §6.2's own terminus (`window_unsplittable`) and a replay miss, both of which fail the run
  before derivation reaches a verdict — so that handler is tested directly, and its docstring says
  why.
- **Two acceptance items were proved one layer below their wording, and now are not.** *"a fully
  text-free document is answerable only as `not_searchable`"* — `test_a_published_scanned_document_answers_not_searchable`
  runs M1's unchanged `lookup` against a document this unit actually published (with a text-bearing
  control beside it). *"re-running the ingest twice yields the same point count"* —
  `test_running_the_same_ingest_twice_yields_the_same_point_count` runs two real `vsir ingest`
  invocations rather than two `publish()` calls, and asserts the second re-embeds nothing.
- **Left for later units:** `--resume` re-runs the whole pipeline under the claimed run id; the
  window-level skip that makes a resume *cheap* is U025's, and the checkpoints it will read
  (`state`, `attempts`, `checkpoint`, `extract_key`) are already written per window. The R4
  threshold stays provisional at 0.8 until U013 sets it from the M2b distribution.

---

### U012 — Port the paid-for `impl` fixtures and the parity / negative sets

**Milestone:** M2b · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — the plan's Demo Command, against the test stack's Qdrant on 6335:

```
$ bash scripts/test-api.sh -k "parity or withheld"

tests/api/test_parity_lookup.py::…_is_still_found_by_phrase[0.03]                   PASSED
tests/api/test_parity_lookup.py::…_is_still_found_by_phrase[10.2.3.1]               PASSED
tests/api/test_parity_lookup.py::…_is_still_found_by_phrase[EAO 84-5140.0020]       PASSED
tests/api/test_parity_lookup.py::…_is_still_found_by_phrase[SF 1.1A]                PASSED
tests/api/test_parity_lookup.py::…_is_still_found_by_phrase[SAPP02D-06A0001]        PASSED
   … 405 rows, one per identifier the old gate accepted (1,644 (page, identifier) pairs) …

GAINS — 63 sighting(s), 19 distinct code(s) the old grammar dropped and the phrase index finds:
  + FESTO VOFA-L26-T32C-M-G14-1C1-APP            1 page(s)   e.g. TC1E-SF@1.3#p001
  + EAO 84-5140.0020                             1 page(s)   e.g. TC1E-SF@1.3#p001
  + K640+K650+K647+K626                          7 page(s)   e.g. TC1E-SF@1.3#p003
  + B&R X20SI4100                                1 page(s)   e.g. TC1E-SF@1.3#p001
  + K644+K645+K651                               7 page(s)   e.g. TC1E-SF@1.3#p002
  + Q1-Q3-Q5                                     3 page(s)   e.g. TC1E-SF@1.3#p013
  + TELEMECANIQUE LC1-D38BL                      1 page(s)   e.g. TC1E-SF@1.3#p001
  + F300 / R130                                  1 page(s)   e.g. TC1E-SF@1.3#p028
  + S202-S203 · ZB4-BS844 · SCHNEIDER · batch 68  1 page(s) each, all TC1E-SF@1.3#p001
  + 1 · 2 · 3 · 4 · 5 · =1 · >=1                 single-token gains, 37 sightings

NO LEGACY COVERAGE — 14 area(s) parity says nothing about:
  - §7.1 the six-value status enum — `impl` returned bare empty lists, so no absence is
    distinguished and `next.suggest` has no baseline at all
  - §7.1 `weak` / `needs_scope` against the server constant, and `scope_stats`
  - §7.1 the two envelope families: `impl` has one ad-hoc dict shape and no `ToolEnvelope`
  - §7.2.1 / §7.2.5 `skim_documents`, `skim_sections`, `resolve` — no `impl` equivalent
  - §7.2.3 `verify` and the `present | absent | unverifiable` vocabulary
  - §7.2.4 `present_instead` and the observed-token inventory of §6.8 — net new
  - §7.3 every cap and its typed 400; §7.3/§8.4 `reads_remaining` and `budget_exhausted`
  - §7.4 the audit line, and cost staying out of the response body
  - §7.6 the four refusals — `impl` returned similarity values, which is what §7.6 forbids
  - §8 the whole runner: triage, the six correction loops, the answer gate, `POST /ask`
  - §5.7 `text_trust` / `grounded_rate` / `searchable_ratio` as contract fields
  - §6.7 scoped retirement and `is_current`
  - §15 the cloud-native properties: probes, structured logs, SIGTERM draining, replay mode

tests/api/test_withheld_negative_set.py::…_not_findable_in_the_text_of_the_page_it_came_from
   [TC1E-PERIODIC@1.1#p005:F302]                                                    PASSED
   … 96 rows, one per raw in withheld.jsonl, each scoped to the page it was withheld from …
tests/api/test_withheld_negative_set.py::…_opens_only_when_the_caller_opts_in[…]    PASSED (96)
tests/api/test_withheld_negative_set.py::test_opting_in_never_changes_the_verified_surface PASSED
tests/api/test_withheld_negative_set.py::…_becomes_verified_on_the_page_that_prints_it PASSED

=============== 608 passed, 226 deselected, 7 warnings in 16.97s ===============
```

```
$ cd backend && python -m vsir.eval.legacy          # what was ported, and what it is worth
"TC1E-SF":          {pages 55, windows  2, accepted 1281, withheld  0, dropped 862, gains 26}
"LTC1AV81":         {pages 34, windows 12, accepted  146, withheld  0, dropped 214, gains  4}
"TC1E-PERIODIC":    {pages 25, windows  1, accepted   82, withheld 95, dropped 118, gains  0}
"TC1AV8M2-LIFTING": {pages 24, windows  1, accepted   90, withheld  1, dropped 117, gains 32}
"DS-5549-EATON":    {pages  3, windows  1, accepted   45, withheld  0, dropped  28, gains  1}
"CE-TC1AV8":        {pages  1, windows  1, accepted    0, withheld  0, dropped  12, gains  0}
ported_files 23 · export_run r-poc-5 · 142 pages · 1,644 accepted pairs · 96 withheld
```

**Tests**

`bash scripts/test-unit.sh` → **1017 passed**, Layer 0/1 PASSED (conformance included).
`bash scripts/test-api.sh` → **834 passed** against `qdrant/qdrant:v1.19.0` and the container.
`bash scripts/test-api.sh -k "parity or withheld"` → **608 passed** in 17 s, zero spend, no key.

**Invariants / failure rows closed**

- **None newly** — the unit closes no invariant and no F-row, which is what its plan entry says.
  What it produces is the **evidence that turns R7 from a hope into an assertion**: 405 identifier
  shapes a real corpus printed, still found by `MatchPhrase` over `variants()`; 96 real
  model-emitted codes proved unfindable through `text`.
- **I2 / F14 re-exercised on real model output** — `test_no_withheld_code_reaches_the_text_of_any_
  record` (L1) and the 96-row negative suite (L2). Asked as a *phrase*, not a substring: `Q5` is a
  substring of `Q59` and the exact surface must never say so.
- **I4 / F7 re-proved on real windows at zero spend** — §6.4 check (1) over all 19 ported windows;
  check (2) over `TC1E-SF`'s two windows and `LTC1AV81`'s twelve; a one-page shift of a real window
  raises `offset_check_failed` naming the check, the page and where the label really is.
- **F8 re-proved on real folds** — two `LTC1AV81` sections straddle a single-page window boundary
  and stitch into one section carrying both pages.
- **F6 on real data** — `F302` and `F313`, withheld from `TC1E-PERIODIC` page 5, move to page 4
  (which prints them) with `moved_from` naming page 5.
- **F4** — `CE-TC1AV8` is scanned, has no text layer and answers `not_searchable`, never
  `not_found`.

**Notes**

- **The export run is `r-poc-5`, and the choice is load-bearing.** "Ported from
  `impl/data/exports/r-poc-*/`" names five different baselines. `r-poc-1`/`r-poc-2` quarantined
  `TC1E-SF` and export nothing for it. `r-poc-3`/`r-poc-4` publish it but **withhold 114 `SF`
  labels** — including `SF 1.1A`, which §12.3's acceptance table requires to return exactly one
  page. Their negative set would therefore assert the opposite of the acceptance table. `r-poc-5`
  is the last run, publishes all six documents, and is the only one whose `withheld.jsonl` is what
  §12.1 describes: every row `source: "vlm"`, *model-emitted codes the text layer never backed*.
  The reason is recorded in `data/fixtures/legacy/SOURCE.json`, not only here.
- **There is no PDF, so `text` is an "observable projection" and is never called anything else.**
  `impl`'s `data/uploads/` and `data/pages/` are empty (OQ-1: the pilot document arrives with
  U013), so the page text those runs indexed cannot be recovered. What can be is the part the
  artefacts *prove*: the identifiers the old gate found in each page's text layer — the whole
  meaning of `text_layer_backed: true` — plus the one page of verbatim extraction `impl` recorded
  (`INGESTION_WALKTHROUGH.md` §1b), lifted mechanically rather than retyped. Three rules keep it
  honest: **nothing the model said is in it** (no unit title, no summary, no `printed_page_no` —
  seeding model output into `text` would refute the very thing the negative set tests); it is a
  **floor, not a page** (so a PASS is evidence, a FAIL is a defect, and an unprovable gain is
  invisible rather than absent); and it never touches a serving collection.
- **Two readings of one window, and the difference is a parameter.** `codes_from="window"` is the
  faithful rename (`units[] → sections[]`, `identifiers[] → codes[]`, `refs[]` dropped per §2.5 B,
  `summaries`/`topics` empty because the old schema has no such field) and is what the L1 offset
  and stitching suites run on. `codes_from="export"` is the claim set the run **recorded per page**
  — backed plus withheld — and is what the L2 corpus is seeded from, because `grounded_rate` is a
  ratio and its denominator has to mean something: the window's own list also carries the strings
  the old grammar dropped *before* the gate (17 on page 1 alone, "counted nowhere" in the
  walkthrough's words), and rating a page against them measures the old grammar's drop rate rather
  than its text layer — it sinks `LTC1AV81` and `TC1AV8M2-LIFTING` to `untrusted` for a reason that
  has nothing to do with their text.
- **The windows were placed, not assumed.** An old response is a bare `{"pages": [...]}` with
  indices 1..N and no record of which absolute pages they were. `Baseline.placements` requires the
  windows to tile 1..`pages` exactly once (from `manifest.json`) and, where a document has more
  than one, requires **every** page of a placement to be positively confirmed by the `labels.jsonl`
  row for that absolute page. `LTC1AV81` is the case that could have gone wrong — eleven one-page
  windows plus one of 23, which is 12! orderings without evidence — and it resolves to exactly one
  tiling. Anything other than one solution raises rather than picking.
- **A recorded fixture limit, asserted so it stays known.** `DS-5549-EATON` is three pages of IEC
  clause numbers (`10.2.3.2`, `10.2.3.3`), and the projection joins them into one string; Qdrant's
  WORD tokenizer treats every separator alike, so page 2 ends up with the tokens `3 3` adjacent and
  the phrase for page 3's printed label `3 / 3` is exactly `[3, 3]`. §6.4 check (2) refuses, which
  is **correct on the text it was given**. The projection is what is wrong, not the check, so
  `test_the_eaton_projection_spells_a_label_the_offset_check_must_refuse` asserts the refusal by
  name; the parity corpus reads those windows through the export, where no page label was ever
  recorded and so there is nothing to check rather than something to check against a projection.
  U013's real text layer is what closes this properly.
- **The gains are reported, never reconciled** (§12.3, verbatim). Every gain is verified against the
  live index before it is called one, and checked to be absent from `labels.jsonl`. The two the
  acceptance table names are both there: `EAO 84-5140.0020` and `B&R X20SI4100`, printed on the one
  page `impl` recorded and dropped by the old grammar before the gate ever saw them — the
  walkthrough's own worked example of a technician who cannot get the part number for the
  emergency-stop button. Single-token gains (`1`, `3`) are reported too and sorted last: a
  one-token code is found wherever that token occurs, and filtering them out would be a grammar.
- **The ported bytes are read-only and provable.** `SOURCE.json` records path, source, sha256 and
  size for all 23 files; `test_legacy_fixture_integrity` asserts each file against its digest, that
  the ledger covers every file in the fixture, and — when `VSIR_IMPL_ROOT` points at an `impl`
  tree — that the digests are the source tree's. A separate test asserts the raw responses still
  carry only the old schema's seven page keys, so a future "helpful" migration is caught.
- **Zero spend, held against a socket.** `test_the_whole_baseline_is_built_with_no_network_and_no_
  api_key` deletes `GEMINI_API_KEY` and makes every outbound connection raise, then builds the
  whole baseline anyway. The raw responses are deliberately **not** a `VSIR_FIXTURE` replay
  directory: they answer the old schema under the old cache key, so serving them as replay would be
  a lie — `vsir.eval.legacy.adapt` renames them for the L1 suite instead.
- **`DS-2611-SICK` is ported and carries no parity rows.** §12.1 counts seven documents, so its
  window is in the fixture; it never published in `r-poc-5`, so the export attributes nothing to it.
  Recorded in `SOURCE.json` under `documents_without_export_rows` rather than left as a silent gap.

---

### M3 milestone gate — closed 2026-09-10, tagged `cr1-m3`

**Demo** (Spec §0 and §13): `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` —
**chain exit 0**, `health=200 ready=200`, and the acceptance table green:

```
seeded 31 pages into vsir_pages_m3_1536
health 200

status       ok · total 1 · capped false · weak false · needs_scope false
scope        {'is_current': True} · searched 30 page(s), 1 with no text layer
  HIT        SYN-M1@1.0#p001 · printed Page 1 of 30 · table · verified true · trust ok
             image /pages/SYN-M1@1.0#p001/image?dpi=150
reads_left   50 · release demo-m3 · schema 1

acceptance: 65 passed, 0 failed, 10 skipped
CHAIN EXIT=0
health=200 ready=200
```

`vsir eval abstention` on the same corpus: `abstention_correctness: 1.00 (D11 gate: 1.00) — PASS`.
The 10 skips are M2b's, named in the report with OQ-1/OQ-2 in the reason string.

`bash scripts/test-unit.sh` → **1073 passed** · `bash scripts/test-api.sh` → **1052 passed, 13
skipped**.

**Acceptance verified by subagent** against Spec §13 M3, adversarially and with `path:line`
evidence per row. Result: **✓ on every row of "Acceptance, always" and every Deliverable row**;
the three "Acceptance, once M2b exists" rows are **deferred on OQ-1/OQ-2** with the mechanism built
and skipping by name. Seven findings; all seven are dispositioned:

| finding | disposition |
|---|---|
| **The `vsir <tool>` one-shot leg of §7.5's "one dispatcher" was unproven by test** (moderate). `_one_shot` routes through `app_module.dispatch` on reading and nothing asserted it, while §4.4 calls the CLI *"the only supported operational surface"* | **fixed** — new `tests/api/test_one_shot_parity.py` (15 rows): byte-identity against `POST /tools/{name}` for six calls, the typed refusals (`filter_unknown_key`, `cap_out_of_range`) as the *same body* with a non-zero exit, object identity of the tool table (`spec.call is served_table[name].call`), and an AST assertion that `_one_shot` names `dispatch` and no tool implementation |
| **`--json` shared stdout with the event stream**, so `vsir lookup --json \| jq` — which `_one_shot`'s own docstring and AGENTS.md both promise — saw seven `boot_check_ok` objects in front of the body | **fixed** — with `--json` the event stream moves to **stderr** before the boot check runs. The rule and the reasoning are `vsir mcp --stdio`'s, verbatim: under `vsir serve` stdout *is* the event stream (§15 XI), and a flag that declares stdout the machine surface makes a perfectly good event a parse error. Separated, never silenced — both halves asserted (`test_with_json_the_event_stream_moves_to_stderr_and_is_not_silenced`), and the human rendering is unchanged (`test_without_json_stdout_is_still_the_event_stream`) |
| ~ **`eval/acceptance.py` held literals its docstring said it did not** (low): `("SF 1.1A", "TC1E-SF@1.3#p001")` and `("SF 5.5b", "TC1E-SF@1.3#p031")` were *measurements of the corpus written into code*, editable to make a row green — exactly what C10 forbids; plus a hardcoded probe label `"C24"` | **fixed** — the pages now come out of `labels.jsonl` (`accepted_pairs`), the labels alone are pinned as `PARITY_ROWS` and marked as §12.3's *text*, and the scanned-document probe is a label the baseline demonstrably prints elsewhere, with the "found on N page(s) elsewhere" control folded into the row so it cannot pass on a label nothing prints. The docstring now states the rule as a **direction**: no measurement in code, spec text asserted *against* the checked-in table |
| ~ **PARITY is a projection and its negative half is a floor** (low, disclosed): `observable_text` is one page of verbatim text plus the accepted identifier strings, so *"every withheld raw is unfindable"* is near-tautological on a corpus those strings were never seeded into | **improved** — the caveat now prints **above the rows** (`SECTION_CAVEATS`), not only in `NO_LEGACY_COVERAGE` at the bottom. A reader reaching row 1 is told what the section does and does not prove. The substance is unchanged and correct: the accepted half genuinely exercises `variants()`, `MatchPhrase` and the WORD tokenizer over 405 real identifier shapes, and the real-text row is what M2b buys |
| ~ **one conformance grep could pass vacuously** (very low): `test_no_match_text_under_serve` uses `scan_under("serve", …)` and nothing asserted the scan set was non-empty, so a package rename would silently remove I3's gate | **fixed** — `test_every_subdirectory_scan_has_something_to_scan`, parametrised over all six package directories |
| ~ **the audit line is exercised only through a test-registered spy tool** (low) | **accepted, unavoidable at M3.** §7.4 audits the two tools that spend; `fetch` lands at M4 and `read` at M5, and `lookup`/`verify` are free. `AUDITED_TOOLS` and the emit site get their first real exercise at **M4** — recorded here so it is a known M4 obligation and not a surprise |
| ~ **`found_only_in_superseded` is declared and unreachable** (informational) | **correct as claimed.** §10 closes F9 at **M8**; `test_status_enum_end_to_end.py` asserts today's honest `not_found` and names U025 as the unit that turns it red. Claiming it at M3 would claim a row this milestone does not own |

**One deviation from a literal reading of the spec, flagged for explicit sign-off rather than
inherited.** §7.4 reads *"Bearer token required on every tool (`401` without one)"*. `vsir mcp
--stdio` and the `vsir <tool>` one-shots use `auth.local_identity` (`local-mcp-stdio`, `local-cli`)
instead of a credential. U015 argued it at length (`serve/auth.py:132-156`): a one-off process of
this release is already inside the boundary — it runs from the release's image with the release's
configuration, spawned by an operator who could equally run `vsir publish`, which flips
`is_current` on a whole document and asks for nothing. The **network** transports are protected
(SSE is behind the same default-deny middleware; `test_mcp_parity.py` asserts it). It is a
defensible reading and it is the one that ships — but it is a reading, and the milestone
verification is right that a reviewer should sign it off rather than absorb it. **Raised here as
an open item for review; no code change made.**

**Invariants asserted from M3 (Spec §9):** none newly — §9 assigns I2, I3, I5, I6 to M1, I1, I4, I7
to M2a and I8 to M6. M3 re-asserts M1's four *at the tool boundary*, which is the point of the
milestone: `test_lookup_tool.py`, `test_verify_tool.py`, `test_status_enum_end_to_end.py` and
`test_mcp_parity.py` put the same table through HTTP, MCP and the CLI.

**Failure rows closed at M3 (Spec §10):** **F2 (tool half)** — `verify` over `POST /tools/verify`,
MCP and `vsir verify`, one `exact_filter` behind all three, so F2 cannot disagree with F1;
**F4 (M3 half)** — a text-free page answers `not_searchable` and never `not_found`, over every
surface, scoped and unscoped. No other row is claimed.

**M3's units:** U014 (the serving app — auth, audit, budget, degradation), U015 (`lookup` and
`verify` over HTTP and MCP through one dispatcher), U016 (the two eval commands).

---

### M2a milestone gate — closed 2026-09-10, tagged `cr1-m2a`

**Demo** (Spec §0 and §13): `vsir ingest data/source/synthetic_3window.pdf --vlm stub && vsir runs
show <run_id>` — **exit 0**, five gates PASS, `state: published`, 42 of 42 pages queryable, run
record read back out of `vsir_runs`. Output recorded under U011 above. A second run of the same
command: `0 embedded, 42 reused`, still 42 points, still 42 queryable.

`bash scripts/test-unit.sh` → **947 passed** · `bash scripts/test-api.sh` → **226 passed**.

**Acceptance verified by subagent** against Spec §13 M2a, adversarially and with file:line evidence
per row. Result: **✓ on every acceptance and deliverable row bar one**, with five items flagged as
"evidence weaker than the claim". All six are addressed:

| finding | disposition |
|---|---|
| **✗ I4's "bisects and re-bills" was not wired into the CLI** — `derive()` was called with no `reextract`, so a real run failed instead of repairing | **fixed** in the CLI, proved end to end by the new `tests/api/test_offset_repair.py` (7 rows) |
| ~ the `offset_check` gate could not fail on a real run (`offset_ok=True` hardcoded) | **fixed** — `cli._offset_blocked` records the failing window and gates the run; tested |
| ~ *"answerable only as `not_searchable`"* was unproved on a **published** scanned document | **closed** — `test_a_published_scanned_document_answers_not_searchable` (L2), plus a control |
| ~ "re-run twice" was proved at the `publish()` layer, not through `vsir ingest` | **closed** — `test_running_the_same_ingest_twice_yields_the_same_point_count` (L2) |
| ~ F8's "carry-in" is key-merge only; a page that did not report its section is disclosed as `noncontiguous_section` rather than having the section carried into it | **U009's documented decision, unchanged.** Recorded here as the reading of F8's stitching half that this milestone ships |
| ~ `eval/synthetic.py` writes `is_current=True` points directly, so "the only writer" was imprecise | **wording fixed** in `run.py`. It is a fixture loader for M1's pre-published corpus into an ephemeral collection dropped on exit — no pipeline path reaches it, and `index.build_point` still refuses a *record* that claims to be current |

**Invariants asserted from M2a (Spec §9):** I1, I4, I7. **Failure rows closed at M2a (Spec §10):**
F4 (M2a half), F5, F6, F7, F8, F11 (key half), F12 (M2a half), F13, F15, F17.

---

### M1 milestone gate — closed 2026-09-10, tagged `cr1-m1`

**M1 is the whole correctness proof and it spent nothing.**

**Demo** (Spec §0): `vsir demo exact --synthetic` — **89 PASS lines, 0 FAIL, exit 0**, across
fifteen sections: `variants` · `exact_filter` · `tok` · the nine §7.3 bounds · the `INDEXED` gate ·
the corpus · `lookup` · the eight compact labels · the hallucinated code · the unsearchable page ·
`weak` at three caps · typed absence · the observed-token inventory · `verify_claims` ·
`near_misses(100)`. Recorded per unit under U004, U005 and U006; re-run at this gate against a
fresh collection.

```
vsir demo exact --synthetic   →  89 PASS · 0 FAIL · ALL ASSERTIONS PASSED · exit 0
bash scripts/test-unit.sh     →  539 passed (L0/L1 + the §12.5 conformance greps)
bash scripts/test-api.sh      →  137 passed (L2 acceptance table + L3 abstention eval)
bash scripts/test-api.sh -k near_miss  →  6 passed, 131 deselected
```

**Acceptance verified by subagent** against Spec §13 M1's Acceptance list (13 items) and its
Deliverable list (17 items), as an adversarial audit at commit `8fec4e3`:
**every item ✓, none unsupported.** The audit read each cited test body rather than trusting its
name, and returned nine findings — no outright ✗, but four were worth fixing and one was wrong.
All are resolved below before the tag.

| Finding | Resolution |
|---|---|
| **1. F10's typed 400 had no production call site.** `lookup` raised the *core* `UnknownScopeKey` (a `ValueError`) and nothing in the shipped package converted it, while §10 claims F10 closed at M1. | **Fixed.** `lookup` now translates it once through `caps.as_tool_error` — its first production call site — and raises the typed `filter_unknown_key` 400 with the keys named. The gate stays in `core/`, which knows nothing about HTTP: one check, one translation. Both halves asserted, plus that a refused filter costs **zero** round trips (`test_unknown_scope_key_returns_typed_400`, L0 and L2). |
| **2. Five of six §7.3 validators were exercised only by tests**, and two were not in the demo at all. | **Improved, and the row's ownership restated.** The demo table now runs **all nine** bounds — read pages, fetch pages, fetch megapixels, dpi list, dpi-requires-region, region shape, cap, unknown scope key, read budget. F18 remains **M4/M5's** row (§10) and nothing here claims it: what M1 claims is that the validators refuse, which the demo now shows in full. The `ToolError → HTTP status` handler is U014's. |
| **3. There was no CI at all**, so U006's AC *"the L3 eval is registered in CI and runs on every commit"* was aspirational. | **Fixed.** `.github/workflows/ci.yml` runs `scripts/test-unit.sh` and `scripts/test-api.sh` on every push and pull request, with the §12.4 eval named as its own step so a P0 failure is legible in the run summary. It interpolates **no** secret — L0–L3 are replay-mode only (D10), L4 is not run there — and both runners are pinned (`ubuntu-24.04`, not a floating label). |
| **4. "`impl/` does not exist anywhere on disk."** | **Incorrect — the audit searched the wrong root.** `impl/` is outside this repository, at `/Users/sabesonk/Documents/VisionRag/dilmah-engineering-solutioning/poc/vision_segmentation_index_and_retrieval/impl`, exactly where AGENTS.md says; the audit searched under `~/Documents/DILMAH`, which is *this* repo. `impl/app/retrieve.py` and `impl/app/segstore.py` were read during U005 and are quoted in `serve/tools/lookup.py`'s docstring. **U012/M2b is not blocked.** |
| **5. I2's `get_text(` grep is vacuous at M1** (nothing calls it yet, because `ingest/` holds only `sparse.py`). | **By design, and already recorded.** §9 makes I2's M1 half *behavioural* — the `K999` tests — and the plan assigns the structural half to U009's L1 check. The grep is in place so it starts guarding the moment a second extractor is written. |
| **6. "L2 + L3 green" was recorded, not re-verified** (Docker was outside the audit's remit). | **Re-run at this gate:** 137 passed, exit 0, and the demo green against a fresh collection. |
| **7. F10's test name had drifted** from the plan's `test_unknown_scope_key_returns_typed_400`. | **Fixed.** Renamed in both layers, keeping the stronger assertions, so §10's F10 row and the test that closes it are greppable from each other. |
| **8. `http_status == 400` was asserted for one of the five 400s.** | **Fixed.** Asserted on all of them — `fetch_budget_exceeded` (both bounds), `dpi_not_allowed`, `dpi_requires_region`, `region_invalid`, `filter_unknown_key`. "A typed 400" is the acceptance item's own wording; relying on a constructor default is not evidence of it. |
| **9. The multi-token `grounded_rate` gap** (§5.7's set intersection cannot ground `SF 1.1A`). | **Carried forward to U009, deliberately.** Recorded under U005's notes with the phrase-aware replacement §2.4 points at. **Flagged for explicit reviewer sign-off before M2a:** left unfixed, a document printing spaced codes fails §11.1's `grounded_rate ≥ 0.8` publish gate for an artefact of set intersection, not for a defect in extraction. |

**Two additions to §7.3's error vocabulary need ratification** (both recorded when introduced, and
neither weakens a bound): `region_invalid` (U004) and `cap_out_of_range` (U005). §7.3 tabulates
*bounds*, and these are that same rule applied to the two parameters it leaves implicit — a
malformed normalised region, and a `cap` of zero, for which every alternative is a lie (an empty
`ok` is impossible under I5, and any absence reported beside `total: 26` denies a set whose size
the same response is reporting).

**One follow-up for U014, which owns auth:** §12.5's credential-literal grep is `=`-shaped
(`api_key = "…"`), so it cannot see a YAML `KEY: value`. Both `docker-compose.test.yml` and the new
CI workflow commit environment blocks, so a YAML-shaped pattern belongs in the cloud-native set.
Not added here because a naive pattern trips on the test stack's own
`${VSIR_API_TOKENS:-test-only-not-a-secret}` placeholder, and the greps must never be the reason a
file cannot explain itself.

**What M1 closed.** Invariants **I2** (behavioural half), **I3**, **I5**, **I6** asserted; failure
rows **F1**, **F2** (core), **F3**, **F10**, **F14**, **F16** closed. Nothing claims a row §10
assigns to a later milestone: F4 is disclosed but owned by M2a/M3, F9's
`found_only_in_superseded` upgrade is M8's, F18 is M4/M5's, and I8's mechanism is built but
asserted at M6.

**The audit's own summary of the evidence**, worth keeping: the strongest is I3 and F16 — I3 proved
three independent ways (a character-preservation property test over 30 corpus-shaped labels, an
**AST** scan proving `MatchPhrase` has exactly one call site, and the `MatchText` grep), and F16 by
a prefix-only implementation with a floor and a bound, a property test that every disclosure is a
prefix *extension* of the claim, an import-graph assertion that `lookup` structurally cannot reach
the inventory, and a 100-case L3 eval carrying a **control** test that stops an all-absence suite
passing on a dead index. That control is what caught both U006 findings. The weakest is I2's
`get_text(` grep, vacuous by design until U009.

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

**U009 — §5.7's `codes_in_text` / `grounded_rate` snippet, and §2.3's C8 row.** The membership
test was a `token_set(page.text)` intersection, which cannot see a multi-token code; §6.8's own
export example (`"sf 1.2a"`) and §5.6's porting-hazard note (the adjacent-token joins are dropped
*because* "multi-token labels are handled by phrases plus `variants()`") both require that it can.
Measured on the M2a corpus the intersection reading gives a median `grounded_rate` of 0.6 against
§11.1's 0.8 blocking gate — a healthy document quarantined. Both passages now ask the phrase
question, which is the one `exact_filter` asks the index (I3). Minimal: no other section touched.

Gap analysis at planning time found no true blocker — every other apparent contradiction is
resolved by Spec §2.3, §3 or §17.

---

### U013 — The one paid `TC1E-SF` ingest and the `grounded_rate` baseline

**Milestone:** M2b · **Spend:** paid · **Status:** `[!]` Blocked — **the re-bill only** · **Non-paid part completed:** 2026-09-10

**Blocker.** Both of the unit's external dependencies are open, and both were re-checked at the
start of this iteration as the unit's own first step requires:

| | |
|---|---|
| **OQ-1** | `data/source/TC1E-SF.pdf` is not present. The directory holds only the generated `synthetic_3window.pdf`. The `impl` tree the fixtures were ported from is not mounted on this machine either, so there is no second place to look. |
| **OQ-2** | `VSIR_VLM_KEY` is empty in `.env`. `scripts/test-paid.sh` refuses before pytest on exactly this. |

Spec §17's documented default was taken: *"run in replay mode off the ported responses until a key
is provided"*. **Every deliverable that does not need the PDF or the key shipped and is green.**
Nothing downstream is blocked — §17 and the plan's risk table both say so, and the plan's own
implementation order already sequences U014 ahead of U013.

**A finding raised while doing it, and closed.** `vlm/cache.py::write` documents its callers as the
M2a corpus generator *"and the one paid ingest at M2b"* — and **nothing had ever called it for a
live response**. `data/fixtures/TC1E-SF/raw_window_*.json` therefore had no producer, and §12.1's
whole economics (*"one paid ingest buys a permanent test corpus"*) had no mechanism: even with the
PDF and the key in hand, U013 could not have been completed. The recorder closes that. It ships
now, tested at L0/L1 against the stub at zero spend, so the re-bill is a command away the day the
credential arrives. The plan's U013 entry is amended with the deliverable, two acceptance criteria
and the Factor VI rationale.

**A second finding, fixed.** `eval/synthetic.py::_record` computed the M1 corpus's `grounded_rate`
and `codes_in_text` with a `token_set` intersection — the formula §5.7's *"Why a phrase"* paragraph
exists to reject, and which `core/health.py`'s docstring predicts will *"ground six of a typical
page's ten codes and put a healthy document under the 0.8 gate."* It did exactly that: `SF121.1` is
printed on p003 as `SF121.1)`, which Qdrant's WORD tokenizer reads as `[sf121, 1]`, so the code was
never a member of the page's token set even though `lookup` finds it there — the corpus disagreed
with its own index about which codes it was evidence for (I3). The fix routes it through
`core/health.py`, the module that owns the question. The corpus median moves from `1.0` with three
pages scored `0.0` to `1.0` with one page at `0.5` (p004, the deliberate `K999` hallucination —
1 of 2 codes ungrounded, which is the right answer). No test asserted the old values; all 1,065
L0/L1 and 847 L2/L3 tests pass after it.

**Demo output.** The unit's own Demo Command (`VSIR_ALLOW_PAID=1 vsir ingest
data/source/TC1E-SF.pdf && vsir runs show <run_id>`) cannot run — OQ-1. These are the demos of the
parts that shipped.

*1 — the paid layer refuses three different ways, each by name, and never spends:*

```
$ VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh
  Paid tests (Layer 4 — REAL MODEL CALLS)
REFUSED: VSIR_VLM_KEY is not set — a paid layer with no credential would fail per-call,
         after billing whatever it managed to send. See .env.example.

$ VSIR_ALLOW_PAID=0  pytest tests/paid/ -rs
SKIPPED [1] test_tc1e_sf_ingest.py:53: VSIR_ALLOW_PAID is not 1 — this module spends money
            and refuses to run without the explicit opt-in (§12.2)

$ VSIR_ALLOW_PAID=1 VSIR_VLM_KEY=… pytest tests/paid/ -rs
SKIPPED [1] test_tc1e_sf_ingest.py:56: OQ-1 is open: the pilot PDF is not at
            …/data/source/TC1E-SF.pdf. The operator places it there (data/source/ stays
            gitignored) or points VSIR_PILOT_PDF at it. Until then M2b's re-bill cannot run
            and every other level replays off data/fixtures/legacy/ and
            data/fixtures/synthetic_3window/ (§17, D10)

$ VSIR_ALLOW_PAID=1 VSIR_PILOT_PDF=…/synthetic_3window.pdf pytest tests/paid/ -rs
SKIPPED [1] test_tc1e_sf_ingest.py:61: OQ-2 is open: VSIR_VLM_KEY is unset. A paid layer with
            no credential fails per call, after billing whatever it managed to send (§17)
```

*2 — the recorder, and the round trip that proves what it writes replays (zero spend, stub VLM):*

```
$ vsir ingest data/source/synthetic_3window.pdf --vlm stub --record /tmp/rec2 --until extract
   recorded     /tmp/rec2/text.json  (42 pages, pymupdf-1.28.2)
   recorded     4 receipt(s) under /tmp/rec2 — S1 and S2, each under the §6.3 key replay reads
                it back by
                /tmp/rec2/facts/933fef7b…790920.json
                /tmp/rec2/extract/8c0238bc…912b3c.json
                /tmp/rec2/extract/b5286f8c…56b347.json
                /tmp/rec2/extract/b340f016…5cd896.json

$ vsir ingest data/source/synthetic_3window.pdf --vlm stub --fixture /tmp/rec2 --until stitch
   ALL ASSERTIONS PASSED
```

and asserted byte for byte at L0/L1 —
`test_recording_the_m2a_corpus_reproduces_its_fixture_byte_for_byte`.

*3 — the `grounded_rate` distribution report refuses to set R4's threshold off a corpus the
extractor never measured:*

```
$ python -m vsir.eval.grounded_rate --legacy
grounded_rate distribution — TC1E-SF@1.3 (Spec §11.1, §5.7, R4)

  ⚠ NOT A MEASUREMENT. The text layer behind these rates was not written by the
    pinned extractor (probe_version: legacy-projection-r-poc-5). R4 is set from a real
    ingest; a constructed corpus reports its own construction. Read on for the shape,
    not for the threshold.

  pages                55
  with a text layer    55   (searchable_ratio 1.0000)
  median  1.0000    mean 1.0000    min 1.0000    max 1.0000

  candidate thresholds — what each would have done to this document
    threshold   document   headroom   pages below
         0.80   publish      0.2000     0 (  0.0%)  ← the pin
         0.95   publish      0.0500     0 (  0.0%)

  recommendation  none   (the pin ships 0.8)   supported ceiling 0.95
    TC1E-SF@1.3: median 1.0000, but the text layer behind it was not written by the pinned
    extractor … the `impl` baseline's text is the projection of codes the old gate had already
    proved printed, so every page rates 1.0 by definition. This sets no threshold — run the
    report over a `pymupdf-…` ingest.
```

*4 — the acceptance table asserts itself today and skips the corpus rows by name:*

```
$ bash scripts/test-api.sh -k acceptance_real
ACCEPTANCE (real): 3 of 3 paid artefacts absent (raw_window_1.json, raw_window_2.json,
  text.json) — the corpus rows below are SKIPPED, not passed. OQ-1/OQ-2.
========== 13 passed, 13 skipped, 834 deselected, 7 warnings in 0.36s ==========

$ bash scripts/test-unit.sh          $ bash scripts/test-api.sh
1065 passed                          847 passed, 13 skipped
```

**Shipped**

| File | What |
|---|---|
| `backend/vsir/vlm/record.py` | **net new.** `RecordingBackend` wraps the configured backend and freezes every verbatim body under its §6.3 key with the register B1 sidecar; `freeze_text()` writes §12.1's `text.json`. A wrapper on the boundary rather than a step, because §6.2's bisection makes calls mid-flight that a per-step recorder would miss. A call that raised freezes nothing. |
| `backend/vsir/cli.py` | `vsir ingest --record DIR`. A flag on one run, never configuration. |
| `backend/vsir/eval/grounded_rate.py` | **net new.** The R4 distribution report: percentiles by nearest rank, a trust-ladder-aligned histogram, a candidate sweep, and a recommendation that may **lower** the pin on one document's evidence and may not raise it. |
| `backend/vsir/eval/synthetic.py` | the §5.7 phrase fix above. |
| `data/fixtures/TC1E-SF/expected.json` | the §12.3 acceptance table, **written from the spec before the ingest** — which is the whole of C10 — including the SA-7 reconciliation. |
| `backend/tests/paid/test_tc1e_sf_ingest.py` | L4, three named guards, and the full re-bill body written against shipped entry points. |
| `backend/tests/api/test_acceptance_real.py` | L2. 13 table-integrity assertions green today; 13 corpus rows skipping by name. |
| `backend/tests/unit/test_vlm_record.py` (11) · `test_grounded_rate_report.py` (37) | L0/L1. |
| `.env.example` | `VSIR_GROUNDED_RATE_THRESHOLD`, documented **including what it does not do**. |
| `AGENTS.md` | `--record`, the round trip, and the report's commands. |

**C10 / SA-7 — reconciled, with the rationale recorded.** §12.3 writes
`lookup("EAO 84-5140.0020") → total 10 (hits capped at cap, capped:true)`. At the default `cap=20`
that is not a response this system can build: §7.1 and §7.2.2 both define `capped` as
`total > cap`, and the model enforces it. `expected.json` records `total: 10` **unchanged** and
`capped: false` **corrected**, with the finding, the authority and the unchanged value in a
`reconciled` block beside it — and `test_no_row_claims_capped_while_its_total_fits_inside_the_cap`
asserts the property over every row, so no future row can reintroduce it.

**R4 — deliberately not an env var, and why.** The plan asks for `VSIR_GROUNDED_RATE_THRESHOLD` in
`.env.example`, and it is there. It is read **by the report only**. Wiring it into the gate would
contradict §5.7 as `core/health.py` states it — *"a deployment that could re-tune what 'trusted'
means would be a deployment that could turn F14 back on by editing an env var"* — so the gate keeps
the `TRUST_OK_MIN` pin and adopting a threshold is a release. The env var earns its place as the
candidate the report scores, which is the operator loop R4 actually needs. `.env.example` says all
of this at the variable.

**Invariants / failure rows closed:** none newly (I1, I4, I7 are U011's and are re-exercised on real
data by the re-bill, which has not run). §12.3's PARITY rows stay closed on the ported projection
(U012) and are **not** yet closed on real text.

**What remains, and exactly how it unblocks.** When the operator places the PDF at
`data/source/TC1E-SF.pdf` and a key in `VSIR_VLM_KEY`:

```bash
VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh -k tc1e_sf_ingest
```

runs the single re-bill — `vsir ingest --vlm gemini --record data/fixtures/TC1E-SF`, S2 and the
embeddings once, publishing 55 pages and freezing the fixture in the same pass. Then
`bash scripts/test-api.sh -k acceptance_real` turns its 13 skips into passes, and
`python -m vsir.eval.grounded_rate --records …` gives R4 its measurement. Three things are then
still open and are **not** shipped: the C10 reconciliation of the *measured* counts against
`expected.json` (a disagreement is a blocking finding, not a re-baseline), the `text_coverage`
measurement `expected.json` currently records as *"a measurement rather than a prediction"*, and
setting `TRUST_OK_MIN` from the distribution in a release with the rationale in the run report.

**Notes.** The paid test's *body* — everything past the three guards — has never executed, and
cannot until OQ-1/OQ-2 close. It is written against shipped entry points (`vsir.cli.main`,
`run_module.require/run_records`, `cache.FixtureStore`) to keep that unexercised surface as small
as possible, but it should be read as unproven code until the first real run. The same is true of
the 13 skipped corpus rows in `test_acceptance_real.py`.

---

### U014 — The serving app: auth, audit, budget, and degradation

**Milestone:** M3 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — the plan's demo command, run against the test stack's Qdrant on 6335 with the
§13 M1 corpus seeded. `VSIR_PORT=8010`, not 8000, because an unrelated process on this machine
already holds `127.0.0.1:8000` — the rest is the command as written:

```
seeded 31 pages into vsir_pages_demo_1536
no-token=401
with-token=200
--- the body of the authorised call ---
{"status": "ok",
 "hits": [{"page_id": "SYN-M1@1.0#p001", "page_no": 1, "printed_page_no": "Page 1 of 30",
           "page_kind": "table", "verified": true, "text_trust": "ok",
           "image": {"url": "/pages/SYN-M1@1.0#p001/image?dpi=150",
                     "thumb_url": "/pages/SYN-M1@1.0#p001/image?dpi=72", "dpi": 150,
                     "width": 0, "height": 0}, "next": null}],
 "unverified_hits": [], "total": 1, "capped": false, "weak": false, "needs_scope": false, …}
--- test-qdrant stopped ---
outage-status=503
error = qdrant_unavailable
health=200  ready=503
```

and the event stream for the same run — the 401, the outage and the drain, one JSON object a line:

```json
{"event": "unauthorized", "level": "warning", "logger": "vsir.serve.auth", "method": "POST",
 "path": "/tools/lookup", "reason": "no_authorization_header", "release_id": "demo-u014",
 "request_id": "74095dbf92df4f4081c39cc0aa2d5420"}
{"event": "tool_unavailable", "code": "qdrant_unavailable", "level": "error", "tool": "lookup",
 "detail": "ResponseHandlingException: [Errno 61] Connection refused",
 "logger": "vsir.serve.app", "request_id": "d572cb69b5f9450ba7a8a2b112c8dfbe"}
{"event": "not_ready", "reason": "qdrant_unavailable", "level": "warning",
 "checks": {"collection_schema": "unavailable", "config_valid": "ok", "dependencies": "ok",
            "model_ids_pinned": "ok", "python_runtime": "ok", "required_env": "ok"}}
{"event": "shutdown", "draining": "complete", "level": "info", "logger": "vsir.serve.app"}
```

**The audit line the demo command cannot show, and why.** §7.4 audits `read` and `fetch`; neither
is in this release's tool table (U020 and U018 build them), so a `lookup` demo emits none *by
design* — that is the rule, not a gap. The line below is real stdout from the shipped dispatcher,
driven through `POST /tools/read` with an audited tool in `app.state.tools`, exactly as
`tests/api/test_audit.py` does. The request carried `X-User-Id: root`:

```json
{"audit": {"cache_hit": false, "dpi": 220, "input_tokens": 4210, "latency_ms": 182,
           "output_tokens": 138, "page_ids": ["SYN-M1@1.0#p001", "SYN-M1@1.0#p002"],
           "run_id": "", "session_id": "sess-77", "tool": "read",
           "user_id": "caller-b4a67cd29c9a"},
 "event": "audit", "level": "info", "logger": "vsir.serve.audit", "release_id": "test",
 "request_id": "777f4753c0254e7a88644f22ccca7e0e", "session_id": "sess-77", "tool": "read"}
{"event": "client_identity_ignored", "headers": ["x-user-id"], "level": "warning",
 "user_id": "caller-b4a67cd29c9a", "path": "/tools/read", "logger": "vsir.serve.auth"}
```

Ten fields, `user_id` the token's digest and not `root`, and no cost anywhere in the response.

**Tests.** `bash scripts/test-unit.sh` → **1067 passed**, Layer 0/1 PASSED.
`bash scripts/test-api.sh` → **918 passed, 13 skipped** (the 13 are U013's real-corpus rows, still
on OQ-1). The unit's own slice, `bash scripts/test-api.sh -k "auth or audit or degradation or
boot_refusal"` → **70 passed**.

**Invariants / failure rows closed:** none newly, as the plan says. I6's boot assertion (built in
U003) is now wired into server start, and §11.3's *"Qdrant unreachable"*, *"index schema ≠
`INDEXED`"* and *"per-caller `read` quota exhausted"* rows are closed on the halves U014 owns —
`test_qdrant_down_503_ready_red_health_green`, `test_boot_refuses_on_schema_drift`,
`test_read_quota_exhausted_429`. The `grounded_rate`-collapse row's *surface* half is closed by
`test_collapsed_grounded_rate_sets_untrusted`. Register item **E5** (no auth on any endpoint,
including the two that spend) is closed. F2 and F4's M3 halves remain U015's.

**Design decisions worth stating**

- **Auth is default-deny ASGI middleware, not a per-route dependency.** A `Depends` is opt-in, and
  a route added next milestone would be unauthenticated until somebody remembered. `PUBLIC_PATHS`
  is the whole allowlist — `/health`, `/ready`, `/metrics` — so `GET /pages/{page_id}/image` and
  `POST /ask` are already refused without a token today, before either route exists. Pure ASGI
  rather than `BaseHTTPMiddleware` because that base class runs the app in a separate task, and a
  `ContextVar` set in its `dispatch` never reaches the handler — the correlation ids would not
  survive to the audit line.
- **Identity is `caller-<sha256("vsir:caller:" + token)[:12]>`.** No user list, no name embedded in
  the credential. A `name:secret` grammar was considered and rejected: a token that legitimately
  contains a colon would be silently split, and the half that then matched would be a *weaker*
  secret than the operator configured — a failure that authenticates. The digest cannot be
  mis-parsed and cannot carry the credential into a log line (§15.1). The cost is that an operator
  reads a digest, and the map back to a human lives with whoever issued the token.
- **The audit line is nested under one `audit` key.** `logging.redact` blanks a field whose *name*
  looks credential-shaped and `token` is one of its hints, so a top-level `input_tokens` would
  reach the stream as `***` — the redactor working correctly on a name that has nothing to do with
  a secret. Nesting also makes "exactly ten fields" assertable on one object. `AuditLine` is
  `extra="forbid"` and its field tuple is checked against §7.4's list at import, by a `raise` and
  not an `assert` (`python -O` strips asserts, and §15.1's *never widen the audit schema with
  document content* is not a debug-only guard).
- **The budget ledger is a `kind: budget` point in `vsir_runs`, keyed by `(caller, UTC day)`.** A
  counter in process memory is N counters under N replicas, each of which forgets on deploy: three
  replicas would turn `VSIR_READ_QUOTA=50` into 150 and a rolling restart into no quota at all.
  It is **advisory** for the same reason D9's lease is — Qdrant has no compare-and-swap, so two
  concurrent reads from one caller can both see the same `spent` — and the over-spend is bounded
  by one caller's own concurrency, is a cost bug and never a correctness bug, and the alternative
  is a fourth backing service to make a fifty-call quota exact. `test_the_ledger_survives_the_
  process_that_wrote_it` is the property a second replica needs.
- **`reads_remaining` is stamped by the dispatcher, not by each tool.** §7.1 puts it on *every*
  envelope, and a tool that forgot would return a plausible zero.
- **`vsir serve` is the one subcommand that prints nothing.** Every other command is a one-off
  admin process whose stdout a person reads; `serve` runs as the `web` process type, where stdout
  *is* the event stream and the contract is one JSON object per line. The first version printed a
  three-line banner and `tests/api/test_log_stream.py` caught it — which is exactly what that
  suite is for.
- **The boot refusal happens before uvicorn exists.** `_cmd_serve` calls `create_app()` itself and
  hands uvicorn the instance, so there is no path on which a refusing process has already bound
  the port. `test_vsir_serve_refuses_before_binding_the_port` spawns a real `vsir serve` against a
  drifted schema and asserts exit 1 *and* a closed socket.

**Deviations from the plan, stated**

- **The request models live in `serve/app.py`, not in each tool's module.** U014's Deliverables do
  not list `serve/tools/lookup.py` and U015's do, so `LookupRequest` sits beside the route with a
  comment saying which unit takes ownership of which shape. Not one line of `tools/lookup.py`
  changed: the HTTP wrapper adds transport, auth and the budget and no behaviour, which is what
  keeps M1's proof true at the tool boundary.
- **`read` and `fetch` are exercised as tools registered into `app.state.tools` by the suites.**
  The plan's AC list names `read` (`503 vlm_unavailable`, `429`, the audit line) and `fetch` (the
  audit line), and both are later units' deliverables. What U014 owns and what is asserted is the
  *dispatcher's policy* — which tools are audited, which charge the quota, and how each failure
  class maps to a status. The table is per-app (a function, not a module constant) precisely so a
  suite can hold its own; nothing under `backend/vsir/` knows the suites exist, so this is not a
  test-only branch in the production path (§15.2). U018 and U020 assert the same lines for the
  real tools.
- **`verify`'s `unverifiable` verdict is asserted at `core.verify`, not over HTTP.** §11.3's
  collapsed-`grounded_rate` row names `verify`, and `serve/tools/verify.py` is U015's file. The
  verdict U015 will wrap is the one asserted here, unchanged.
- **The demo ran on port 8010.** An unrelated process on this machine holds `127.0.0.1:8000`, and
  because the server binds `0.0.0.0` both can listen at once — the first run of the demo silently
  curled the *other* process and reported `404` for everything. Worth knowing: it is a plausible
  way to get a confusing demo, and the port is configuration (`VSIR_PORT`), not a flag.

**Findings recorded rather than fixed**

- **`ImageRef.url` is not percent-encoded, so it cannot be dereferenced.**
  `serve/tools/lookup.py::image_ref` interpolates the `page_id` into `/pages/{page_id}/image`, and
  a `page_id` contains `#` (§5.1), which a client reads as a fragment delimiter — the path that
  arrives is `/pages/SYN-M1@1.0`. Spec §7.2.5's example shows the encoded form
  (`…@1.3%23p001…`). Surfaced by this unit's demo, which prints the URL. **Not fixed here**: the
  encoding is half of a contract whose other half is U018's `GET /pages/{page_id}/image` route,
  and splitting it across two units would ship one release with neither half. Recorded as a
  requirement on U018 in the plan, naming the two existing assertions that must move with it.

**Pre-existing defects fixed while running the layers**

- **The test stack's bearer token was coming from `.env`.** `docker-compose.test.yml` interpolated
  `${VSIR_API_TOKENS:-test-only-not-a-secret}`, and Compose loads `.env` for interpolation — so on
  any machine with a `.env` the container's credential was the developer's, and
  `test_log_stream.py::test_no_credential_appears_on_the_stream` was asserting the absence of a
  string the container had never been given. The substitution now reads `VSIR_TEST_API_TOKENS`,
  `tests/api/conftest.py::CONTAINER_TOKEN` resolves the same name, and that suite asserts against
  the resolved value.
- **`tests/api/test_run_record.py` drove `/runs` unauthenticated.** A consequence of this unit's
  contract change, not a bug in that suite; its `get()` helper now sends the container token and
  it gained `test_the_run_surface_is_behind_the_token_and_the_gauges_are_not`.

**Notes**

- The conformance suite gained an **AST** scan for module-level state (U014 AC): the existing regex
  only sees an *empty* literal, so it would miss `CACHE = {"seed": 1}`. The AST version flags a
  module-level container only when something **writes** to it — `X[k] = v`, `X.setdefault(…)`,
  `X.add(…)` — because a dict that is only read is a lookup table and banning those would ban every
  constant in the package. It scans `serve/` first and then the whole package, and a companion test
  plants a store to prove the scanner fires.
- `docker-compose.test.yml` now runs `command: ["serve"]` instead of invoking `uvicorn` directly, so
  the L2 stack exercises the shipped `web` entry point and its boot self-check.

---

### U015 — `lookup` and `verify` over HTTP and MCP

**Milestone:** M3 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — the §4.4 chain, against the M1 synthetic corpus seeded into the serving
collection (the **OQ-1 fallback**: `data/source/TC1E-SF.pdf` does not exist, so the demo's page id
is the corpus's own `K73`-on-a-`K78`-page row). `VSIR_PORT=8010`, for the reason U014 recorded.

```
$ vsir serve & sleep 2 && vsir lookup "SF 1.1A" && \
    vsir verify --claims K73 --pages "SYN-M1@1.0#p006" && \
    vsir lookup "alarm 152" && <the MCP handshake + tools/call>

status       ok · total 1 · capped false · weak false · needs_scope false
scope        {'is_current': True} · searched 30 page(s), 1 with no text layer
  HIT        SYN-M1@1.0#p001 · printed Page 1 of 30 · table · verified true · trust ok · image /pages/SYN-M1@1.0#p001/image?dpi=150
reads_left   10 · release dev-0 · schema 1

status       ok — the CALL ran; the verdicts are below (1 claim(s))

claim           verdict       pages / why
K73             absent        SYN-M1@1.0#p006
                              different part: ['k78']

status       not_found · total 0 · capped false · weak false · needs_scope false
scope        {'is_current': True} · searched 30 page(s), 1 with no text layer
next         suggest ['skim_pages'] · tokens that did occur ['alarm', '152']

chain exit=0

MCP  tools/call content[0].text : 630 bytes, sha b62b884ecd9157ae
HTTP POST /tools/lookup body    : 630 bytes, sha b62b884ecd9157ae
byte-identical                  : True
```

The SSE half of the same demo, on the **serving port** (§15 Factor VII — `vsir mcp --sse` is
`vsir serve`, and there is no second socket):

```
$ vsir mcp --sse &   # then an MCP client against http://127.0.0.1:8010/sse
server         vision-segmentation-retriever 0.1.0
tools/list     ['lookup', 'verify']
tools/call     630 bytes, sha b62b884ecd9157ae isError False
refusal        True {"error":"filter_unknown_key","detail":"not filterable (see …
```

Same 16-hex digest on all three surfaces, and the typed refusal reaches MCP under the same code
it reaches HTTP under.

The one-shots' four other statuses and two refusals, for the record:

```
$ vsir lookup "SF 1.1A" --scope doc_id=NO-SUCH-DOC   → out_of_scope, searched 0 page(s)   exit 0
$ vsir lookup "SF 9.9" --scope page_no=5 --include-unverified
                                                     → not_searchable, 1 UNVERIFIED row   exit 0
$ vsir lookup "SF 1.1A" --scope nope=1                → 400 filter_unknown_key            exit 1
$ vsir verify --claims K73 --pages "SYN-M1@1.0#p999"  → 404 page_not_found                exit 1
```

**Tests**

`bash scripts/test-unit.sh` → **1067 passed**, Layer 0/1 PASSED (conformance 25/25).
`bash scripts/test-api.sh` → **1011 passed, 13 skipped** (the 13 are M2b's paid-gated rows, as
before). The unit's own slice, `-k "lookup_tool or verify_tool or status_enum or mcp_parity"`:
28 + 24 + 15 + 23 = **90** new L2 assertions.

**Invariants / failure rows closed**

- **F2 (tool half)** — `verify` cannot confirm a code that is not on the page, because the wrapper
  has no matcher: it calls `core/verify.py`, which calls the one `exact_filter` scoped to one page
  (`test_the_decoy_page_is_absent_not_present`, `test_a_verify_uncited_page_reports_absent`).
- **F4 (M3 half)** — a page with no text layer answers `not_searchable` end to end, and an
  untrusted extraction does too (`test_not_searchable_is_never_not_found`,
  `test_an_untrusted_text_layer_is_also_not_searchable`). The scoped/unscoped pair is the whole
  distinction: the same label is honestly `not_found` over the 28 pages that *were* searchable.
- Re-exercised across the new boundary, not newly closed: **I2/F14** (a hallucinated code is
  unfindable over HTTP and only ever in `unverified_hits`), **I3/F1** (the decoy page), **I5/AC-003**
  (no empty `ok`, on the wire, re-validated through the declared model), **I6/F10**
  (`filter_unknown_key` on both transports), **I7** (`is_current` injected server-side, and a
  caller's explicit `false` overridden *and echoed*), **F16** (`present_instead` inside an `absent`
  verdict), **D7/R6** (every safeguard below the transport), **D12/P2** (an `ImageRef` on every hit,
  `bytes_b64` nowhere).

**What was built**

- `serve/tools/verify.py` — net new. The Family B wrapper: `page_not_found` is a `404`, a
  malformed citation is a `400 page_id_invalid`, and every verdict is `core.verify`'s, unchanged.
- `serve/app.py` — the tool surface became **transport-neutral**. `ToolRuntime` (config + store +
  the release's table), `ToolOutcome` (an HTTP status and a payload, no transport in it) and
  `dispatch(runtime, name, arguments, …)`, which does the name lookup, the validation, the budget,
  the call and the audit line. `POST /tools/{name}` is now a shell around it, and so are the MCP
  server and the CLI one-shots. `runtime_from_env` builds the same runtime for a process with no
  ASGI lifespan.
- `serve/envelope.py` — `wire()`, the one serialiser (Starlette's `JSONResponse.render` settings,
  verbatim, because the HTTP half is the surface that already exists), and
  `NextMoves.tokens_observed`.
- `mcp/server.py` — net new, and it holds **no tool logic**. `tools/list` publishes each tool's own
  Pydantic model as its input schema; `tools/call` is `dispatch` plus a `CallToolResult`. SSE is
  mounted on the serving app; stdio is a one-off process.
- `serve/auth.py` — `local_identity(process)`, and `serve/caps.py` — `validate_verify_pairs`.
- `cli.py` — `vsir lookup`, `vsir verify`, `vsir mcp [--stdio|--sse]`.
- `requirements.txt` / `requirements.lock` — `mcp==2.2.0`, the §4.2 row *"MCP | official Python
  SDK, stdio + SSE"*. It is a **runtime** dependency (the image serves §7.5), and `vsir doctor`
  now prints its resolved version with the other eight.

**Decisions, stated**

- **`next.tokens_observed` is new, and §7.1 asked for it.** The sentence is *"it returns
  `status: not_found` **with** `next.suggest: ["skim_pages"]` and the tokens that did occur"*, and
  `expected.json` has named the field `tokens_observed` since M1 with nothing asserting it. U014
  put the words on the log line instead, reasoning that §7.1's inline `{expand, neighbours,
  references, suggest}` comment enumerated the model. That comment is a shorthand, not a class
  definition, and the AC (*"and lists the tokens that did occur"*) is binding — so the field is
  now on `NextMoves`, defaulted, and the corpus's row is asserted end to end.
- **Two ACs are narrowed by the spec, and the plan now says so inline** (§2.3 — the spec wins).
  (1) *All six statuses reachable*: five are. `found_only_in_superseded` is **F9's row and §10
  closes F9 at M8**; claiming it here would claim a row this milestone does not own, and
  `expected.json` records the honest current answer as `not_found`. `error` is reached as a
  **5xx**, because §7.1 says a backend failure is a 5xx and never an empty result. Both are
  asserted, so U025 landing turns the relevant test red rather than leaving it green.
  (2) *Every response carries `effective_scope` and `scope_stats`*: Family A does. §7.1's
  `ToolEnvelope` is `{status, result, reads_remaining, provenance}` and a `verify` caller names its
  pages outright, so there is no scope to echo; adding the fields would contradict the normative
  model.
- **MCP SSE is mounted on the serving app, not run as a second server.** §15 Factor VII: *"the MCP
  SSE transport binds the same port."* `vsir mcp --sse` therefore *is* `vsir serve`, and the help
  text says so. One socket, one readiness probe, one middleware stack.
- **stdio needs no bearer token; SSE does.** The socket is the boundary, and register E5 is about
  an unauthenticated *network* surface. A `vsir mcp --stdio` process runs from the release's own
  image with the release's own configuration, spawned by an operator who could equally run
  `vsir publish` — a credential it would read from the same environment the server reads is
  ceremony, not authentication. What it does get is a stable identity for the audit line and the
  quota: `local-mcp-stdio`, beside `local-cli` and `caller-<digest>`. `local_identity` names the
  **process type** and never the host or the user, so a `local-` line carries no personal
  identifier into a stream whose retention policy was written for digests (§15.1).
- **Sticky sessions, §15.2.** An SSE session is a *connection*: the POST must reach the replica
  holding the stream. That is transport affinity. The ban is on **state** affinity — the
  server-held retrieval session C11 strikes — and there is none: `scope` and `exclude` are
  parameters, `effective_scope` is echoed back, and a client that reconnects to another replica
  gets identical answers. Asserted across two processes
  (`test_two_processes_share_no_state`). Stated as a residual: an SSE deployment behind a load
  balancer needs connection affinity for the channel; `stdio` and `POST /tools/{name}` do not.
- **A typed absence is exit 0 from a one-shot.** `vsir lookup "alarm 152"` searched and correctly
  found nothing — §7.1's whole argument is that this is a successful call, and it is what lets the
  demo chain with `&&`. Only a refusal is non-zero.
- **`validate_verify_pairs` is a new bound and it is not in §7.3's table.** `verify` costs
  `len(claims) × len(page_ids)` index counts, so the bound is on the product, at 200 — far beyond
  the largest legitimate call (the answer gate checking one draft against the ≤ 3 pages a `read`
  saw). Same family as `cap_out_of_range` and `region_invalid`, which are also §7.3's rule applied
  to a parameter it left implicit. An empty `claims` or `page_ids` is a typed `400 verify_empty`
  rather than an `ok` with no verdicts: *"nothing to answer for"* is the one thing an answer gate
  must never conclude by accident.

**Deviations from the plan, stated**

- **The demo command needed two corrections, now made in the plan.** MCP requires the
  `initialize` / `notifications/initialized` handshake — the SDK answers a bare `tools/call` with
  `-32602` — and it cancels in-flight work on stdin EOF, so a heredoc that closes the pipe while
  the tool is running in a worker thread gets the frames before the answer. The demo holds stdin
  open with a trailing `sleep 2`; a real MCP client needs neither. Second, the page id is the
  synthetic corpus's, per §7's OQ-1 fallback.
- **`serve/app.py`, `serve/auth.py`, `serve/caps.py` and `doctor.py` were edited beyond the
  Deliverables list.** Each is the minimal correct home: the tool table and the dispatcher already
  live in `app.py` and §7.5 forbids a second one; `local_identity` belongs beside `caller_id` or it
  is duplicated in `mcp/server.py`; the `verify` bound belongs with the other bounds; and Factor II
  says `vsir doctor` prints the resolved version of every §4.2 pin, which now includes the SDK.
- **`tests/api/test_auth.py` gained `verify`, `/sse` and `/messages/`.** Its `available == ["lookup"]`
  assertion is a statement about *this release's* surface, so a milestone that adds a tool updates
  it deliberately. The docstring now says so, and the test also cross-checks the literal against
  the live table.
- **The import cycle is broken by one function-level import**, and it is the only one in the
  package. `mcp/server.py` imports `dispatch` and `ToolRuntime` from `serve/app.py` because §7.5
  requires it to call the identical implementations; `create_app` imports `vsir.mcp.server` inside
  the function to mount the SSE routes. The dependency is one-directional at import time with the
  MCP surface as the leaf, which is the shape the rule describes, and the comment says so.

**Notes**

- The `ImageRef.url` percent-encoding finding U014 recorded is **still open and still U018's** —
  the demo output above prints the unencoded `/pages/SYN-M1@1.0#p001/image?dpi=150`. Nothing in
  this unit dereferences it.
- `mcp==2.2.0` brings 12 transitive packages into the runtime image (`sse-starlette`, `httpx2`,
  `jsonschema`, `pyjwt`, `opentelemetry-api`, …). The image still builds and runs read-only as
  uid 10001 — `scripts/test-api.sh` rebuilds it every run and the container suites are green.
- **Nothing about `read` or `fetch` moved.** They are still absent from the table and still a typed
  `404` listing what is served — now `["lookup", "verify"]` — on both transports.

---

### U016 — `vsir eval acceptance` and `vsir eval abstention`

**Milestone:** M3 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

**Demo output** — the plan's demo command, against the test stack's Qdrant on 6335. Both sections
of §12.3 that have a corpus, then §12.4's metric. Abridged: the 47 SYNTHETIC rows are the same
table `test_acceptance_synthetic.py` asserts and are elided here after the first few.

```
$ vsir eval acceptance && vsir eval abstention

vsir eval acceptance — release dev-0, §12.3, section all

SYNTHETIC — 47 assertion(s)
  SYN-M1@1.0 current pages indexed              30                        30                       PASS
  pages with no text layer (§5.7)               1                         1                        PASS
  pages unsearchable for lookup (§5.7)          2                         2                        PASS
  searchable_ratio of SYN-M1                    0.9667                    0.9667                   PASS
  superseded revision 0.9 kept, not deleted     1 page(s) is_current=False 1 page(s) …=False        PASS
  lookup("SF 1.1A") → printed SF 1.1A           total=1 p001              total=1 p001             PASS
  lookup("SF 5.5b") → printed SF5.5b            total=1 p014              total=1 p014             PASS
  lookup("SF 1.1A") never returns the token …   without p008              p001                     PASS
  lookup("3", cap=5) is weak at any cap         weak total=26 capped=True weak=True total=26 …     PASS
  lookup("alarm 152") → not_found + next.sug…   not_found ['skim_pages']  not_found ['skim_pages'] PASS
  …and lists the tokens that did occur (§7.1)   ['alarm', '152']          ['alarm', '152']         PASS
  lookup("K999") — claimed by the model, abs…   not_found, 0 hits         not_found, 0 hits        PASS
  verify("SF 1.1A", [p008])                     absent present_instead=[] absent present_instead=[]PASS
  verify("K73", [p006])                         absent present_instead=['k78']  …=['k78']          PASS
  verify("SF 9.9", [p005])                      unverifiable reason=no_te unverifiable reason=no_t PASS
  observed-token inventory size (§6.8)          55                        55                       PASS
  … 31 further rows, all PASS

PARITY — 9 assertion(s)
  the parity set r-poc-5 recorded               1644 pairs / 405 identif  1644 pairs / 405 identif PASS
  every identifier the old gate accepted is …   405 of 405                405 of 405               PASS
  …on the pages the old run recorded it on      388 uncapped identifiers  388 agree                PASS
  every raw in withheld.jsonl is unfindable …   0 of 96 findable          0 of 96 findable         PASS
  …and reachable only when the caller opts in   96 under include_unverif  96 disclosed             PASS
  lookup("SF 1.1A") on the ported baseline      total=1 TC1E-SF@1.3#p001  total=1 TC1E-SF@1.3#p001 PASS
  lookup("SF 5.5b") on the ported baseline      total=1 TC1E-SF@1.3#p031  total=1 TC1E-SF@1.3#p031 PASS
  the scanned document CE-TC1AV8 → not_searc…   not_searchable            not_searchable           PASS
  every code reported as a GAIN is genuinely…   63 sighting(s)            63 findable              PASS

REAL — 19 assertion(s)
  the table names the pilot document at §12.…   TC1E-SF 55 pages / 2 win  TC1E-SF 55 pages / 2 win PASS
  every lookup row of §12.3 is in the table…    7 rows: SF 1.1A … alarm   7 rows                   PASS
  no row claims `capped` while its total fit…   0 rows                    0 rows                   PASS
  the SA-7 reconciliation is recorded, not s…   finding SA-7, total unch  SA-7, total: 10          PASS
  the weak row is a server constant and hold…   weak_abs=20, no per-row   weak_abs=20, caps=[5,20, PASS
  the absent row suggests a move rather than…   not_found + ["skim_pages"]not_found + ['skim_pages']PASS
  §12.3's verify row is `absent` where the t…   SF 1.1A on p008 → absent  SF 1.1A → absent         PASS
  the PARITY and negative sets point at the …   labels.jsonl + withheld.j labels.jsonl + withheld. PASS
  … and 3 more, all PASS
  lookup("SF 1.1A") on real text                total=1 capped=False      —                        SKIP
  lookup("EAO 84-5140.0020") on real text       total=10 capped=False     —                        SKIP
  lookup("B&R X20SI4100") on real text          total=54 capped=True      —                        SKIP
  … 7 more corpus rows                                                                             SKIP
  SKIP · raw_window_1.json, raw_window_2.json, text.json absent from data/fixtures/TC1E-SF: OQ-1
         (the pilot PDF) and OQ-2 (a Gemini key) are open, so the one M2b re-bill has not run.
         These rows assert real text and cannot be faked; §12.3's PARITY rows run meanwhile on
         data/fixtures/legacy/. U013's DoD is that this skip becomes a pass.

GAINS — 19 code(s) the old grammar dropped and the phrase index finds (§12.3: record it, do not
        reconcile it)
  + FESTO VOFA-L26-T32C-M-G14-1C1-APP      1 page(s)   e.g. TC1E-SF@1.3#p001
  + EAO 84-5140.0020                       1 page(s)   e.g. TC1E-SF@1.3#p001
  + K640+K650+K647+K626                    7 page(s)   e.g. TC1E-SF@1.3#p003
  + B&R X20SI4100                          1 page(s)   e.g. TC1E-SF@1.3#p001
  + TELEMECANIQUE LC1-D38BL                1 page(s)   e.g. TC1E-SF@1.3#p001
  … 14 more

NO LEGACY COVERAGE — 14 area(s) parity says nothing about (R7)
  - §7.1 the six-value status enum · §7.2.1 the skim rungs · §7.3 every cap · §8 the whole runner …

acceptance: 65 passed, 0 failed, 10 skipped
{"event": "eval_acceptance", "failed": 0, "gains": 19, "ok": true, "passed": 65,
 "release_id": "dev-0", "section": "all", "skipped": 10}

vsir eval abstention — release dev-0, §12.4, corpus synthetic

CORPUS — SYN-M1 in vsir_pages_eval_abstention_synthetic_1536
  55 observed token(s) (§6.8), 100 fabricated code(s), each one character off a real one
  21 distinct source code(s): 0020→0000, 150→100, 152→102, 380→300 …

LEAKS — a fabricated code that reached a caller on any surface (§12.4)
  none: 100 of 100 abstained on every surface

CONTROL — the real codes the fakes were mutated from are still findable
  21 of 21 findable

abstention_correctness: 1.00 (D11 gate: 1.00) — PASS
{"abstention_correctness": 1.0, "corpus": "synthetic", "doc_id": "SYN-M1",
 "event": "eval_abstention", "gate": 1.0, "leaks": 0, "sample": 100, "ok": true}

DEMO EXIT=0
```

The negative control, because a report that cannot fail proves nothing. Two of them, and both are
asserted (`test_a_failing_row_makes_the_command_exit_non_zero`,
`test_a_leaking_near_miss_exits_non_zero_and_names_the_case`):

```
# one row broken at the index boundary: `lookup("K 158")` asked as `K 159`, which nothing prints
  lookup("K 158") → printed K158                total=1 p001              total=0 —                FAIL
  lookup("K 158") — is_current injected serv…   1 hit(s)                  0 hit(s) —               FAIL
acceptance: 45 passed, 2 failed, 0 skipped        → exit 1

# one "fabricated" code that is really printed, handed to the eval by the generator
LEAKS — a fabricated code that reached a caller on any surface (§12.4)
  ! k158 → k158 (char 1): lookup returned ['SYN-M1@1.0#p001']
  ! k158 → k158 (char 1): verify present on ['SYN-M1@1.0#p001']
abstention_correctness: 0.99 (D11 gate: 1.00) — FAIL        → exit 1
```

**Test evidence**

```
bash scripts/test-unit.sh                  1067 passed        (conformance greps green)
bash scripts/test-api.sh                   1036 passed, 13 skipped   (240s)
bash scripts/test-api.sh -k "near_miss or eval_commands"   32 passed   (the CI step)
```

The 13 skips are M2b's, unchanged: `test_acceptance_real.py`'s corpus rows and the paid suite.

**Invariants/failure rows closed:** none newly, by design — the unit is the **runnable proof
surface** for F1, F2, F3, F4, F14 and F16, and §10's "Closed at" column assigns each of those to an
earlier milestone. What is new is that the proof is a command rather than three pytest files.

**What shipped**

- `vsir/eval/acceptance.py` — net new. Three sections, one `Row` per §12.3 assertion
  (`section, assertion, expected, observed, outcome, reason`), a `Report` that counts them and
  distinguishes **a skipped row from a refused section**, and `print_report`. Every expectation is
  read out of a checked-in `expected.json`; the module holds exactly one literal of its own —
  §12.3's seven lookup labels in §12.3's order, which is the spec's *text* and not a measurement.
- `vsir/eval/abstention.py` — net new. `evaluate()` reads one collection and returns a `Report`
  carrying `abstention_correctness`, every `Leak` by name, and the **control** (the real codes the
  fakes were mutated from, which must still be findable). `CORRECTNESS_GATE = 1.00` is a pin in
  code, for the same reason `TRUST_OK_MIN` is: relaxing D11's gate has to be a reviewable release.
- `vsir/eval/__init__.py` — gained `searchable_payloads(client, collection, doc_id="")`, the one
  reading of *"what is actually in the index"* both evals need. §6.8's rule (build the inventory
  from what was **indexed**, not from the records) and §5.7's (drop the pages `lookup` cannot
  search) live in one place instead of two.
- `vsir/cli.py` — `vsir eval acceptance [--only synthetic|parity|real|all] [--tc1e-fixture DIR]`
  and `vsir eval abstention [--corpus synthetic|indexed] [--collection NAME] [--doc-id DOC]
  [--sample N]`, both through `_with_store` so a configuration error and an unreachable Qdrant are
  the same named non-zero exit every other store-backed command gives.
- `.github/workflows/ci.yml` — the named §12.4 step now runs
  `-k "near_miss or eval_commands"`, so the **shipped subcommand** is exercised on every commit
  and not only the library behind it.
- `backend/tests/api/test_eval_commands.py` — 26 tests over the commands' own properties.

**Decisions, stated**

- **Three sections, and the `real` one splits along C10's seam.** §12.3's rows need a corpus, and
  there are three: the M1 synthetic pages (always), the ported `impl` baseline (always — `impl`
  paid for it), and the pilot document (not until the M2b re-bill). The pilot section therefore
  runs *the rows that assert `expected.json`'s faithfulness to §12.3* — all seven labels present in
  order, no row claiming `capped` while its total fits the cap, SA-7's reconciliation recorded
  rather than applied — and emits the corpus rows as named `SKIP`s. That is the same split
  `tests/api/test_acceptance_real.py` already makes, and it is the honest one: the table is checked
  in *ahead* of the ingest, so its integrity is assertable today and its numbers are not.
- **The command does not rebuild the frozen fixture, and that is deliberate.** Making the SKIP rows
  into measurements needs `derive`+`stitch` over `raw_window_*.json`, which cannot be exercised
  until the artefacts exist — writing it now would ship a path no test can reach. U013's Definition
  of Done already owns *"these skips become passes"*, the skip names the three files and both open
  questions, and `test_the_real_section_skips_by_name_rather_than_failing` flips to a `pytest.skip`
  the moment the fixture lands, so the day it arrives the suite says so instead of staying green.
  **Recorded as U013's remaining work**, beside the re-bill.
- **A skipped row is not a failure; a refused section is.** `Report.ok` is `failed == 0 and not
  refusals`. A row that cannot run yet is visible, counted in the summary line and on the event
  stream, and does not fail the command (the plan's Edge Cases require exactly this). A section
  whose *fixture* is missing produced no evidence at all, and calling that a pass would be the C10
  failure one level up — so it is a refusal and a non-zero exit.
- **GAINS is a report and can never be a verdict.** §12.3 is explicit: *"a code the old grammar
  dropped but the phrase index finds is a **gain**: record it, do not treat it as a diff to
  reconcile."* So the 19 codes print in their own section with no `PASS`/`FAIL` column, and
  `test_the_gains_section_lists_the_codes_the_old_grammar_dropped` asserts that section carries no
  verdict at all. What *is* a row is *"every code reported as a GAIN is genuinely findable"* — a
  gain that is not in the index is a reporting bug, not a gain.
- **`--corpus indexed` is §12.4's own wording, and it only reads.** *"near_misses() mutates one
  character of codes taken from the observed-token inventory of **whatever corpus is indexed**."*
  That path never creates, upserts or deletes: it is how the metric gets measured on a real
  document after an ingest, and it is the M1-available half of §12.6's D11 gates. Asserted by a
  point-count and payload-digest comparison either side of the run
  (`test_neither_command_mutates_the_index`, parametrised over all three code paths).
- **A collection holding more than one document refuses until `--doc-id` names one.** A near miss
  is one document's code mutated; a safety metric measured over an unnamed corpus is not a
  measurement. The refusal lists the documents it found.
- **0 of 0 is never 1.00.** `abstention_correctness` of an unmeasured run is `0.0`, the report
  prints `not measured`, and the exit is non-zero. A refusal that scored itself perfect is the one
  way this eval could fail silently.
- **`WEAK_ABS`-style pinning for the gate.** `CORRECTNESS_GATE = 1.00` is not an env var and not a
  flag. §12.6 fixes it and calls a single miss a P0 stop; a deployment that could re-tune it could
  turn F16 back on by editing a variable.
- **The commands cannot reach a model, structurally and at runtime.** `vsir.vlm` is absent from
  both modules' import graphs (`test_no_eval_module_can_reach_a_model_at_all`), the `run` fixture
  deletes `VSIR_VLM_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY` before every invocation, and a
  socket spy records every address the process connects to and asserts the store's port is reached
  and 80/443 are not. The import-graph half is the total claim; the spy is the evidence about the
  run.
- **Ephemeral collections are namespaced per command.** `{VSIR_COLLECTION}_eval_acceptance_…` and
  `{VSIR_COLLECTION}_eval_abstention_…`, through `synthetic_collection`/`legacy_collection` so
  neither can ever *equal* the serving collection — and so neither collides with
  `test_acceptance_synthetic.py`'s or `test_near_miss_codes_never_answer.py`'s own corpora. All of
  them are dropped in a `finally`, asserted after every run.
- **`vsir eval corpus` is refused by name.** §4.4's row is `acceptance | abstention | corpus` and
  `corpus` is §12.6's, at M8. Asking for it now is argparse's own usage error listing the two that
  are served — the CLI analogue of the typed 404 `POST /tools/{name}` gives for `read` and `fetch`.

**Deviations from the plan, stated**

- **`vsir/eval/__init__.py` was edited beyond a docstring.** It is on the Deliverables list, and
  `searchable_payloads` is the one thing both evals need identically; putting it in either module
  would have made the other import a private name across a module boundary.
- **`.github/workflows/ci.yml` was found EMPTY in the working tree** — 0 bytes, uncommitted, so CI
  ran nothing at all. Restored from `HEAD` and then extended. Recorded here because it is a
  pre-existing defect this unit uncovered rather than one it introduced, and because an empty
  workflow file is invisible: GitHub reports no failure for a workflow it cannot parse.
- **`ASSERTION_WIDTH` / `VALUE_WIDTH` are public.** A row that rendered its two sides into one
  column would satisfy every other assertion in the suite, so
  `test_every_printed_row_shows_the_expectation_beside_the_measurement` slices the columns apart at
  the module's own widths. A whitespace split cannot tell one padded column from two.
- **The parity section is a module-scoped fixture in the L2 suite.** 660 index reads over 405
  identifiers, 96 withheld codes and 63 gains is a few seconds, and four assertions are about one
  report rather than four. Nothing in it is mutated by a test.

**Notes**

- **The 10 skipped rows are the M2b hole, and they are the only one.** `--only real` exits 0 with
  9 passes and 10 skips today; when `raw_window_1.json`, `raw_window_2.json` and `text.json` land,
  U013 turns them into measurements and the L2 test that guards the skip inverts.
- The parity section's `derive`/`stitch` event lines interleave with the report on stdout. That is
  §15 Factor XI working as specified — stdout *is* the event stream — and `vsir demo exact` has the
  same property. A reader who wants only the report has `2>/dev/null | grep -v '^{'`.
- `NO_LEGACY_COVERAGE` prints beside every parity run (R7). A green 405-row parity report is not
  sign-off for the ~70% of §7/§8 `impl` never exercised, and the list says which parts.
- Nothing about `read`, `fetch`, `skim_*` or `resolve` moved. They are still absent from the tool
  table and still a typed `404` listing `["lookup", "verify"]`.
- **Two things changed outside this unit's scope, at the M3 gate rather than in the unit**, and
  both are recorded in the gate entry below: `tests/api/test_one_shot_parity.py` closes §7.5's
  third surface, and `--json` moved its event stream to stderr so AGENTS.md's `| jq` promise is
  true. `test_conformance.py` gained a positive control for `scan_under`.
