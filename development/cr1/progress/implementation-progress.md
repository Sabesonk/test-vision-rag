# CR1 Implementation Progress

**Plan:** `development/cr1/plan/cr1-implementation-plan.md`
**Release tag:** (pending — set when all units are [x])

## Rollup

| | |
|---|---|
| **Complete** | 3 / 26 units (12%) |
| **Current milestone** | M1 — `core/` and the exact surface (1 / 4 units); M0 closed and tagged |
| **Next unit** | U004 — Tokenisation, variants, the exact filter, and both envelopes |
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
- [ ] U004 Tokenisation, variants, the exact filter, and both envelopes
- [ ] U005 Synthetic exact surface, `lookup`, and `vsir demo exact`
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
| M0 | `vsir doctor && bash scripts/test-unit.sh` | ⬜ | U001 half green (see unit detail); pending U002 |
| M1 | `vsir demo exact --synthetic` | ⬜ | |
| M2a | `vsir ingest data/source/synthetic_3window.pdf --vlm stub` | ⬜ | |
| M2b | `VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf` | ⬜ | |
| M3 | `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` | ⬜ | |
| M4 | `vsir demo narrow` | ⬜ | |
| M5 | `VSIR_ALLOW_PAID=1 vsir read --pages … --question …` | ⬜ | |
| M6 | `VSIR_ALLOW_PAID=1 vsir ask "carton discharge won't restart after an E-stop reset"` | ⬜ | |
| M7 | `bash scripts/test-e2e.sh` then browse `http://localhost:5174` | ⬜ | |
| M8 | `vsir ingest --resume <run_id>` and `vsir eval corpus` | ⬜ | |

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
