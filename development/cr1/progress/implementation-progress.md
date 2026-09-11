# CR1 Implementation Progress

**Plan:** `development/cr1/plan/cr1-implementation-plan.md`
**Release tag:** (pending — set when all units are [x])

## Rollup

| | |
|---|---|
| **Complete** | **32 / 33 units (97%)** — 25 of the planned 26 (every one but **U013**), plus U027, U028, U029, U030, U031 and U032 added after the plan was written (plan §4b) and the `fixes/` bundle |
| **Current milestone** | **M8 is closed, and so is the plan.** U025 closed revisions, resume and graceful shutdown; **U026** closes the last one — `vsir eval corpus`, §12.6's report and the D11 gates. **Every milestone M0-M8 is now closed.** The only unit that is not `[x]` is **U013**, whose paid re-bill waits on OQ-1 |
| **Latest** | **The completion gate ran — 15 of 16 ACs closed with evidence, all 19 §10 rows closed by the milestone that owns them, and `v0.1.0` deliberately NOT tagged.** It closed two criteria that were open and found three bad pointers in this file. **AC-012** was missing §4.3's third refusal: `fingerprint.require` guards the *write*, but a process that only ever **reads** embeds the query with one model and compares it against vectors made by another — no guard fires and the only symptom is worse neighbours, which is indistinguishable from a thin corpus. `doctor.check_collection_fingerprint` now refuses that boot. **AC-013**'s `summaries[]` was on Part A's wire and off the test: the field set was asserted against the export module's **own constant**, so deleting the field from both left the suite green. **AC-014 is 8 of 9** — M2b's demo cannot run without OQ-1's PDF, so the tag waits on a decision that is the project owner's. See **Completion gate** at the foot of this file |
| **Previously** | **U026 — the catalogue, measured rather than asserted.** `vsir eval corpus` prints §12.6's five metrics against D11's gates, exits non-zero on any failure, and stops with a named **P0 STOP** on a `code_precision` under 1.00. Three findings the build produced: **(1)** `0/0` is the one arithmetic accident that turns an absent corpus into a perfect safety score, so a zero denominator is `None` and a named skip, never `1.00`; **(2)** the document-wide `lookup` status explains a recall miss *wrongly* — a code printed on an untrusted page inside a searchable document answers `not_found`, and a report echoing that would send a reader hunting a tokenisation bug that is not there, so a miss is explained from the page's own record; **(3)** a ground-truth file is found by the `doc_id` it **declares**, not by its directory name — fixture directories are named after the corpus (`synthetic_pages` holds `SYN-M1`), so the obvious `data/fixtures/<doc_id>/` path finds nothing for most of them. The report also prints `1/denominator` and marks a set **underpowered** when one miss costs more than its gate's whole tolerance |
| **Next unit** | **None — the plan and the completion gate are both done.** The only work left is not a unit: it is the **`v0.1.0` decision**, which needs an input this build cannot produce |
| **Then** | **`v0.1.0` is blocked on one thing, twice.** **U013** is `[!]` and **AC-014** is ⚠ for the same reason — OQ-1's `data/source/TC1E-SF.pdf` was never delivered, so M2b's paid ingest and M2b's demo command have both never run. Either the pilot PDF lands (and one paid run closes both), or the owner decides to ship v0.1.0 with the M2b slice **explicitly waived**. Tagging while a top-level criterion is knowingly unmet would put the untrue claim in the one place nobody re-reads |
| **Read first** | **Plan §4c — six open defects found by running the system.** None breaks a build; all of them mislead somebody who trusts the output. P1 (a live run records no cost) and P2 (no VLM cache store, so a re-ingest re-bills) both land on U013 |
| **Blocked** | **U013** — the paid re-bill only, and now on **OQ-1 alone**: `data/source/TC1E-SF.pdf` is still not present. **OQ-2 is closed** — a key is configured and was exercised live on 2026-09-10, ingesting a real 4-page datasheet to `published` through `POST /documents`. The ladder is no longer a blocker either: the shipped `plan()` refused the 55-page pilot at **step 05**, one step before the spend everyone thought it was waiting on a credential for, and `fixes/001` now folds it to `[[1, 30], [31, 55]]` — byte-for-byte what its own acceptance table declared. Nothing downstream is blocked (§17) |

---

## Running what exists

The system is runnable end to end today, and this is how to see it rather than infer it:

```bash
bash scripts/stack.sh up          # Qdrant, the collection, the API, a seeded document
bash scripts/stack.sh status      # mode, probes, tools served, documents, the working token
bash scripts/stack.sh up --live   # the same, against real Gemini — this bills money
```

| | |
|---|---|
| Console | <http://localhost:8055/console> — upload, watch a run, search, verify |
| Swagger UI | <http://localhost:8055/docs> — *Authorize* with the token, then `Try it out` |
| Qdrant | <http://localhost:6353/dashboard> — the payloads and vectors as written |
| token | `VSIR_API_TOKENS` from `.env`; `stack.sh status` prints the one the container has |

**Replay is the default and spends nothing** (`VSIR_VLM=stub` + a fixture, D10). `--live` sets
`VSIR_VLM=gemini` and `VSIR_ALLOW_PAID=1`, refuses without a credential, and seeds nothing.

Two things a later unit should not have to rediscover:

- **A green suite says nothing about the live path.** U028 is five defects that 1149 passing tests
  could not see, because the stub never builds a request, loads a prompt or opens an SDK client. A
  model id, a packaged file, an object's lifetime and a provider's schema dialect are all unverified
  until a real call is made.
- **`scripts/sweep-corpus.py <root>`** puts every PDF of a corpus through the shipped `plan()` with
  no key, no Qdrant and no spend, and reports refusals and coverage violations. It is how `fixes/001`
  was measured rather than argued.

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
- [x] **U027 `POST /documents` — ingestion over HTTP** — added after the plan; a transport for
      `vsir ingest`, never a second pipeline (§15 Factor XII, register E1)
- [x] **U030 `/console`, the OpenAPI security scheme, and the local stack** — added after the plan;
      **not** M7's console, which replaces it

### Corrections to shipped units (spend: paid — the run that found them)
- [x] **U028 The five defects between `VSIR_VLM=gemini` and a published document** — a model id that
      does not exist, prompts missing from the wheel, an SDK client closed mid-request, a response
      schema the API rejects, and a live run inheriting the replay fixture's acceptance table.
      **Every one was invisible to 1149 green tests**, because the stub never builds a request,
      loads a prompt or opens a client
- [x] **fixes/001, 002, 003** — the window ladder refused 48% of the real corpus including the
      pilot; §6.4 check (2) raised on one witness with 22 measured false positives; `label_verified`
      contradicted the page's own text. See `fixes/README.md` for the two measured deviations

### Surface work added after the plan (spend: none)
- [x] **U031 The typed API surface: eight named routes, the corpus, and MCP resources** — added
      after the plan (§4b). One model module and one error model; `POST /tools/{name}` for each of
      the eight beside the generic route it keeps; `GET /documents`, `/documents/{doc_id}`,
      `/documents/{doc_id}/pages` and `GET /runs`; `vsir://corpus` and two resource templates on
      MCP. **No new tool, no second dispatcher, and no second validator**

- [x] **U032 The live path: the schema `title` bug, the client race, and the retry ladder** —
      added after the plan (§4b). Three defects that only a **paid** run could expose, all found
      by ingesting one real 56-page manual: a field named `title` deleted from every response
      schema, a lazy SDK client raced by its own thread pool, and transient transport failures
      refused at the first attempt. Prompt released as **s2-v2**

### M4 — `skim_pages`, `fetch`, `resolve` (spend: none)
- [x] U017 `skim_pages`, deterministic fusion, image queries, and `resolve`
- [x] **U029 The document store — `page_id` → bytes** — new (plan §4b); **U018's blocker, cleared**
- [x] U018 The page-image endpoint, the raster cache, and `fetch` — **M4 closes here**

### M5 — the ladder rungs and `read` (spend: read)
- [x] U019 `skim_documents`, `skim_sections`, and `searchable_ratio` — spend: none
- [x] U020 `read` — the paid step, with stamped codes and a question-keyed cache — spend: paid


### M6 — the runner, the loop, the answer gate (spend: read)
- [x] U021 Tri-state triage, the safeguards, and fetch-vs-read routing — spend: none
- [x] U022 The loop, the six correction loops, the answer gate, and `POST /ask` — spend: paid — **M6 closes here**


### M7 — operator console (spend: none, fixture-backed)
- [x] U023 The operator console — viewer, agent panel, trust badges
- [x] U024 The Playwright replay suite and `scripts/test-e2e.sh` — **M7 closes here**

### M8 — revisions, resumable ingest, scale-out (spend: ingest)
- [x] U025 Revisions, resumable ingest, and graceful shutdown — spend: none
- [x] U026 `vsir eval corpus` — the §12.6 report and the D11 gates — spend: none in the end (the report reads the index; no set it could measure needed a live call) — **M8 closes here, and so does the plan**

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
| M1 | `vsir demo exact --synthetic` | ✅ | see the M1 milestone gate below |
| M2a | `vsir ingest data/source/synthetic_3window.pdf --vlm stub` | ✅ | see the M2a milestone gate below |
| M2b | `VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf` | ⬜ **blocked, OQ-1** | never run, and it cannot be: `data/source/TC1E-SF.pdf` does not exist. The pilot PDF was never delivered (OQ-1) and `data/source/*` is gitignored, so this demo is unrunnable on a clean checkout by anyone. **This is the one reason AC-014 is not green** — see the completion gate |
| M3 | `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` | ✅ | see the M3 milestone gate below |
| M4 | `vsir demo narrow` | ✅ | exit 0; see the M4 milestone gate below |
| M5 | `VSIR_ALLOW_PAID=1 vsir read --pages … --question …` | ✅ | ran live against Gemini; see the M5 milestone gate below |
| M6 | `VSIR_ALLOW_PAID=1 vsir ask "carton discharge won't restart after an E-stop reset"` | ✅ *(substituted question)* | run in replay on the OQ-1 fallback corpus, **both branches**; see the M6 milestone gate below. **§0's literal question is about `TC1E-SF`**, which OQ-1 never delivered, so it was asked of the fallback corpus as *"why won't the guard door interlock release when K119 is monitored"*. The command shape, the loop, the answer gate and the abstention branch are all exercised; the *wording* is not §0's |
| M7 | `bash scripts/test-e2e.sh` then browse `http://localhost:5174` | ✅ | 22 Playwright assertions green against the shipped image, `GET http://localhost:5174 → 200`; see the U024 entry and the M7 milestone gate below |
| M8 | `vsir ingest --resume <run_id>` and `vsir eval corpus` | ✅ | `--resume` after a SIGTERM kill → `exit=0`, 3 windows cached / 2 bought; `vsir eval corpus` prints §12.6's five metrics against D11's gates. See the U025 and U026 entries and the M8 milestone gate below |

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

### M4 milestone gate — closed 2026-09-10, tagged `cr1-m4`

**Demo** (Spec §0 and §13): `vsir demo narrow` — **exit 0, ALL ASSERTIONS PASSED**, run as a
one-off container of the same image against the stack `scripts/stack.sh up` seeds. The full
transcript is in the U018 entry below; the seven steps are: narrow to five triage rows carrying
only `ImageRef`s, dereference the first row's URL to bytes, `fetch` two pages with the pixels,
the same `fetch` with `inline=false`, a 400 dpi region crop, the four bounds, and the cache
proved evictable and byte-identical when cold.

**Verified against the running container over real HTTP**, not only through the test client —
because a green suite said nothing about the live path once before (U028):

```
GET /pages/synthetic-3window@1.0%23p019/image?dpi=150
  with a bearer token   200  image/png  74,076 bytes  (PNG 1240x1755, 8-bit RGB)
  without a token       401
  ?dpi=400 (no region)  {"error":"dpi_requires_region","requested":400,"region_required_above":220}
  ?dpi=100              {"error":"dpi_not_allowed","allowed":[36,72,150,220,300,400]}
  #p999                 404

POST /tools/skim_pages → the row's own url and thumb_url, dereferenced verbatim
  /pages/synthetic-3window@1.0%23p019/image?dpi=150   200  PNG 1240x1755  74,076 bytes
  /pages/synthetic-3window@1.0%23p019/image?dpi=72    200  PNG  595x842   27,862 bytes

POST /tools/fetch
  inline=false          status ok · url present · bytes_b64 null · 1240x1755
  6 pages               {"error":"fetch_budget_exceeded","bound":"pages","limit":5,"requested":6}
  5 pages at dpi 220    {"error":"fetch_budget_exceeded","bound":"megapixels","limit":12.0,
                         "requested":23.4}
```

Both bounds distinguish themselves by `bound`, which is what §11.3 means by *naming* the bound: a
caller told only `fetch_budget_exceeded` after five pages would retry with five pages again.

`bash scripts/test-unit.sh` → **1216 passed** (31 of them the §12.5 conformance greps) ·
`bash scripts/test-api.sh` → **1277 passed, 13 skipped**. The 13 are M2b's, blocked on OQ-1 and
skipping by name — unchanged since M3.

**Acceptance verified by subagent** against Spec §13 M4, adversarially and with `file:line`
evidence per clause. Result: **✓ on five of the six acceptance clauses and on every Deliverable
row**; one clause is **✗ and could not have been anything else** — see below. Five findings, all
dispositioned:

| finding | disposition |
|---|---|
| **✗ "every aggregate row a `preview.thumb_url`" — no implementation, no test, and none possible at M4.** `DocHit`, `SectionHit` and `Preview` are declared in `serve/envelope.py:170/186/105` and constructed **nowhere** in production code; the only `Preview(...)` in the tree is a model-shape unit test. The rungs that emit aggregate rows are `skim_documents`/`skim_sections`, which §13 **M5** lists as its own deliverable | **spec corrected, not signed off.** §13 M4's Acceptance sentence had inherited D12's phrasing wholesale, and D12 (*"every page-level hit carries an `ImageRef` and every aggregate row a `preview` thumbnail"*) is a **design decision and is right** — the milestone assignment was wrong. A milestone cannot be gated on a property of rows it does not produce. The clause moves to §13 M5 where the rungs live, recorded as a new correction row in §2.3. **Not claimed as met here**, because it is vacuous rather than satisfied |
| **No end-to-end dereference of a `ResolveHit.image.url`** (moderate). `test_an_image_reference_out_of_a_real_envelope_dereferences_to_a_png` was parametrised over `skim_pages` and `lookup` only; resolve hits were asserted in *shape* alone. One shared builder is an argument, not a proof — `image_ref` is called from three modules and the third had never had a reference dereferenced | **fixed** — `resolve` added to the parametrize, with a real printed label off the ingested corpus (`{"printed_label": "17"}` → `synthetic-3window@1.0#p019`). All three page-level rungs now take their own URL verbatim and get a 200 PNG back |
| **The milestone-demo ledger contradicted the unit entries** (low): M4's row read `⬜` with no evidence while the U018 entry held the full green transcript — and M1's and M2a's rows read `⬜` too, although both milestones are tagged and both gates are recorded below | **fixed** — all three rows now carry ✅ and point at their gate section. M2b stays `⬜`; it is blocked on OQ-1 and that is the honest state |
| **The plan file still said `🔵 Not Started` for U017 and U018**, with every acceptance checkbox unticked, four and one commits after they shipped | **fixed** — both statuses and every acceptance / DoD checkbox updated to match what the tests and the demo actually prove |
| ~ **`next.references` ships permanently empty** (informational). §7.2.1 declares it as *"[printed labels]"* and `skim.py:347` never populates it | **already recorded, no action.** U017's notes below carry it as a closed deviation with §2.5 **B**'s reasoning — refs[] is struck, and the empty list is the declared shape rather than a gap. Re-raised here only because a reviewer reading the envelope and not the ledger would read it as a bug |

**One property worth stating because it is the whole point of the milestone.** `serve/raster_cache.py`
holds **no cache** despite its name: the LRU is `ingest/render.py::_cached`, keyed by the source
file's content hash. A second cache keyed by `page_id` is the obvious optimisation and is a
correctness bug — a `(doc_id, revision)` re-ingested from corrected bytes keeps its page ids, so
it would serve the superseded pixels for the life of the process. Asserted by
`test_the_serving_cache_is_the_renderers_cache`.

**M3's one deferred obligation is discharged.** The M3 gate recorded that *"the audit line is
exercised only through a test-registered spy tool … `AUDITED_TOOLS` and the emit site get their
first real exercise at **M4**"*. They do: `fetch` is the first real audited tool, and
`test_one_fetch_writes_one_audit_line_with_exactly_ten_fields` pins all ten §7.4 fields on a real
call, with `cache_hit` asserted in **both** states and `test_no_page_text_or_image_bytes_reach_the_event_stream`
holding §15.1's retention row.

**Invariants asserted from M4 (Spec §9):** none newly — §9 assigns no invariant to M4. What M4
does is put M1's four through two more surfaces: I2 holds because `fetch`'s `text` is the payload
`ingest/probe.py` wrote and nothing re-extracted, and I6 holds because `exclude` filters on
**point ids** rather than on a payload field, so it needs no `INDEXED` key.

**Failure rows closed at M4 (Spec §10):** **F5 (M4 half)** — an ambiguous printed label returns
every candidate, never a silent pick (U017); **F8 (stateless half)** — no server session,
`effective_scope` echoed on every Family A response, and two processes return the identical
ordered list (U017); **F18 (`fetch` half)** — the §7.3 caps, each a typed 400 naming its bound
(U018). `read`'s share of F18 is M5's and `series_id` is M8's; neither is claimed.

**M4's units:** U017 (`skim_pages`, deterministic fusion, image queries, `resolve`), U029 (the
document store — `page_id` → bytes, added after the plan and the unit that unblocked U018), U018
(the page-image route, the raster cache, `fetch`).

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
| the collection fingerprint ≠ the configured embedding model | **not implemented at M0 — U010 owns it.** `dim` and `distance` are read back from the live collection; `embed_model` and `composition_version` are not observable from Qdrant, so the model half of §6.6 needs a record written beside the collection. **Now ships** — `doctor.check_collection_fingerprint` reads U010's control-plane record and refuses the boot on a disagreement; closed at the completion gate, 2026-09-11, where AC-012's audit found it was the one §4.3 refusal still missing |

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

---

### U017 — `skim_pages`, deterministic fusion, image queries, and `resolve`

**Milestone:** M4 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

The page rung of the narrowing ladder, and the first thing in this system that reads a **vector**.
U010 has been writing three surfaces per page since M2a and nothing had ever queried them; this
unit makes them load-bearing. `resolve` lands beside it because it is the other free move that
turns something a *person* reads — a printed page label — into a `page_id`.

**Demo output** — the plan's demo command, adapted to the corpus that exists. `TC1E-SF` is still
absent (OQ-1), so the demo runs against the 42-page generated corpus that `bash scripts/stack.sh up`
ingests through the real pipeline. Replayed, free, and it is the same code path `POST /tools/skim_pages`
runs (§7.5, asserted byte-for-byte in `test_ordering_determinism.py`).

```
$ vsir skim pages "emergency stop reset" --scope doc_id=synthetic-3window --limit 3

status       ok · total 42 · capped true · weak true · needs_scope true
scope        {'doc_id': 'synthetic-3window', 'is_current': True} · searched 42 page(s), 2 with no text layer

rank  page_id                       printed   why                   grounded  trust       image
1     synthetic-3window@1.0#p031    29        dense,lexical         1.00      ok          /pages/synthetic-3window@1.0#p031/image?dpi=150
      Page 29 covers light curtain muting stage 29 within the light curtain muting section. It names K [en]
      next: expand {'section_id': ['synthetic-3window@1.0#s007']} · neighbours ['synthetic-3window@1.0#p030', 'synthetic-3window@1.0#p032'] · references []
2     synthetic-3window@1.0#p013    11        dense,lexical         1.00      ok          /pages/synthetic-3window@1.0#p013/image?dpi=150
3     synthetic-3window@1.0#p036    34        dense,lexical         1.00      ok          /pages/synthetic-3window@1.0#p036/image?dpi=150

P2           no row carries page text or image bytes: confirmed
reads_left   50 · release dev-0 · schema 1

$ vsir skim pages "emergency stop reset" --scope doc_id=synthetic-3window --limit 3 --json   # again
rows   ['synthetic-3window@1.0#p031', 'synthetic-3window@1.0#p013', 'synthetic-3window@1.0#p036']
why    [['dense', 'lexical'], ['dense', 'lexical'], ['dense', 'lexical']]

$ vsir skim pages --image /tmp/panel.png --scope doc_id=synthetic-3window --limit 3   # D12
rank  page_id                       printed   why                   grounded  trust       image
1     synthetic-3window@1.0#p019    17        dense                 1.00      ok          /pages/…/image?dpi=150
2     synthetic-3window@1.0#p040    38        dense                 1.00      ok          /pages/…/image?dpi=150
3     synthetic-3window@1.0#p031    29        dense                 1.00      ok          /pages/…/image?dpi=150

$ vsir skim pages "wiring K131" --scope doc_id=synthetic-3window --limit 3   # the code is a filter
status       ok · total 1 · capped false · weak false · needs_scope false
1     synthetic-3window@1.0#p031    29        dense,lexical         1.00      ok          /pages/…/image?dpi=150

$ vsir resolve "Page 8 of 55" --doc-id synthetic-3window
status       ok · candidates 1 · total 1 · capped false
  CANDIDATE  synthetic-3window@1.0#p010 · printed 8 · label_verified true · interpolated false · image /pages/…

$ vsir resolve "40"                                        # unscoped: two binders number a page 40
status       ok · candidates 2 · total 80 · capped false
  CANDIDATE  synthetic-3window@1.0#p042 · printed 40 · label_verified true · interpolated false
  CANDIDATE  via-docker@3.0#p042 · printed 40 · label_verified true · interpolated false
             ambiguous — every candidate is returned, never a pick (F5)

$ vsir resolve "999"
status       not_found · candidates 0 · total 0 · capped false
next         suggest ['skim_pages', 'lookup']
```

And over HTTP, through the same dispatcher (`POST /tools/skim_pages`, bearer-authenticated):

```json
{"status": "ok",
 "hits": [{"page_id": "synthetic-3window@1.0#p031", "printed_page_no": "29",
           "summary": "Page 29 covers light curtain muting stage 29 …", "summary_lang": "en",
           "why": ["dense", "lexical"], "rank": 1, "grounded_rate": 1.0, "text_trust": "ok",
           "image": {"url": "/pages/synthetic-3window@1.0#p031/image?dpi=150",
                     "thumb_url": "/pages/synthetic-3window@1.0#p031/image?dpi=72",
                     "dpi": 150, "width": 0, "height": 0},
           "next": {"expand": {"section_id": ["synthetic-3window@1.0#s007"]},
                    "neighbours": ["…#p030", "…#p032"], "references": []}}]}
```

**Tests** — L0/L1 `1155 passed`; L2/L3 `1158 passed, 13 skipped`. New: `test_skim_pages.py` (25),
`test_ordering_determinism.py` (8), `test_image_query.py` (13), `test_resolve.py` (28),
`test_stateless_scope.py` (11).

**Invariants / failure rows closed**

- **F5 (M4 half)** — an ambiguous printed label returns **every** candidate, never a silent pick:
  `test_an_ambiguous_label_returns_every_candidate`, and the citation case beside it.
- **F8 (stateless half)** — no server session; `effective_scope` echoed on every response, and a
  narrow call does not narrow the next one: `test_stateless_scope.py`.
- **D2** — three surfaces fused by RRF at `k=60`, weights `1.0 / 1.0 / 0.4`, ranks only. The
  arithmetic is checked against a hand-computed `Σ w/(k+rank)` in
  `test_the_fused_order_matches_the_hand_computed_sum`.
- **D12** — image queries: one `types.Content`, **no instruction prefix** when multimodal (asserted
  on the SDK request payload), an image-only query runs the dense branch alone (asserted with a
  call spy on the store, not just on the rows), and no image parameter exists on `lookup` or
  `verify`.
- **P2** — no page text and no `bytes_b64` in a triage row, asserted over the serialised response.
  Made structural as well: `ROW_PAYLOAD` omits `text`, so the page's text is never loaded into the
  serving process at all.
- **E9** — `resolve` never scrolls; a call spy asserts `facet` and `query_points` and the absence of
  `scroll`.

**Decisions worth keeping**

- **`decompose` splits on §6.8's code-like rule** — a word containing a digit — imported from
  `core/observed_tokens.py` rather than restated, so there is one definition of *code-like*. It is
  safe in this direction for a different reason than it is for `present_instead`: a word wrongly
  called an identifier goes to the **exact** surface, which is stricter, not looser, so the failure
  is a narrower answer that says so (`total`, `weak`) and never a wrong page. Adjacent words are
  **not** joined (§5.6, §2.4).
- **The identifiers are a hard filter, not a fourth branch.** §7.2.1 says the code goes to the
  phrase filter; a fourth surface would need a fourth weight, which is a pin. When the narrowing
  empties the rung the response is `not_found` with `next.suggest: ["lookup"]` — the move that
  answers *"is this code printed anywhere at all"*.
- **A branch runs when it has an input.** One rule, applied twice: an image-only query skips the two
  sparse branches (D12 rule 2), and a query that decomposes to identifiers only (`"K158"`) skips the
  dense branch, because embedding the code after splitting it out would be the blurring rule 1
  exists to prevent. `why` states which branches ran, so neither is silent.
- **`BRANCH_DEPTH` is a constant (50), not a multiple of `limit`.** Found by running the demo: with
  a depth of `5 × limit`, `limit=3` read a different candidate pool from `limit=10` and fused it
  into a different order, so the first three rows of a ten-row skim were **not** the three rows of a
  three-row skim. An agent narrowing its list would have seen the ranking move under it for no
  observable reason. `test_a_shorter_limit_is_the_prefix_of_a_longer_one` guards it.
- **`total` on a skim is the size of the set the branches were allowed to rank** — the scope,
  narrowed by the identifiers and by `exclude` — and not `len(hits)`. That is what keeps
  `weak`/`needs_scope` meaningful on a rung where the dense branch always has something to return:
  an unscoped skim of 42 pages says `needs_scope`, and `"wiring K131"` inside one document does not.
- **`resolve` pages through the matched set rather than looking at a window of it.** Also found by
  running the demo: `resolve("40")` returned `not_found` with `total: 80, capped: true`, because
  the page whose *footer* prints 40 was outside the first 64 candidates sorted by `page_no` — E9's
  injury in a new costume. It now scans up to 8 × 64 candidates, stops as soon as the counted set is
  exhausted, and reports `capped` when the budget binds instead of reporting an absence it did not
  establish. `test_a_confirmation_past_the_first_window_is_still_found` builds a 130-page document
  for it.
- **A citation is not a label.** `resolve("Page 8 of 55")` first asks the index for the citation as
  typed (which no footer prints), then for the digit-bearing words of it — `8`, then `55` — always
  confirming a candidate against the **whole** citation. That the second probe can find the page
  numbered 55 is not a defect to tune away: the citation really is ambiguous evidence for it, and
  F5's answer to ambiguity is every candidate.
- **U009's recorded follow-up is closed: `resolve` reads `content.label_candidates` as well as
  `printed_page_no`.** §6.5 leaves `printed_page_no` **empty** where two readings cannot be
  arbitrated, so a resolver that read only that field would make exactly the pages a citation is
  most likely to be wrong about the pages no citation could open. A page answers to every reading of
  itself (`labels_of`), and `printed_page_no` is still echoed as stored — writing the candidate that
  matched would claim the page prints a reading it could not arbitrate. **The other half of that
  ambiguity is a documented limit**: `attribute_label` also produces candidates for a page that
  prints *neither* reading, and no phrase query can reach that page by either — a typed absence with
  `next.suggest`, asserted rather than left to be discovered.
- **The bracket, at query time.** A phrase query can only find a label a page *prints*, so it is
  structurally blind to an `interpolated` label — which is exactly what §7.2.3 asks `resolve` to
  disclose. When nothing is confirmed and the label is a plain integer, §6.5's own rule runs: if
  *n−1* and *n+1* are printed on two pages of one document two apart, the page between them comes
  back `interpolated: true, label_verified: false`. Never from one neighbour and a delta — §6.5 is
  explicit that no `printed + offset = pdf` formula exists in this corpus.
- **`next.references` ships empty, deliberately.** §7.2.1 declares it as *"[printed labels]"* and
  there is no field on the §5.3 record to read them from: `refs[]` was measured at zero reads in
  `impl` and §2.5 B struck it. The only alternative is a cross-reference grammar scraped out of page
  text at query time, which is what §5.2 refuses and what F5 is about. The field stays in the
  contract; a caller that read a label itself can still `resolve` it. **Open for U019/U023 if a
  source for it is ever agreed.**
- **Four helpers in `serve/tools/lookup.py` were made public** (`scope_filter`, `count_exact`,
  `scope_stats`, `absence`) so `skim` and `resolve` reuse them rather than re-deriving `scope_stats`
  and the four absences. No behaviour changed; the rename is the whole diff.
- **The embedder is a factory on the runtime**, not an instance and not per request. A `lookup` must
  not pay for a model client it never uses, and a release configured for Gemini with no credential
  must still serve every free tool that does not embed — so a missing credential is a
  `503 vlm_unavailable` on the one rung that needs it, at call time, not a boot refusal.

**Pre-existing defect found and fixed: every frozen fixture key was stale.**

`bash scripts/stack.sh up` — the documented way to run this system — refused at step 04 with
`fixture_miss`, and had done since U028. U028 corrected `VSIR_VLM_MODEL` from `gemini-3.8-flash-001`
(a 404 from the API) to `gemini-3.8-flash`; `facts_key` and `extract_key` are keyed on the resolved
model id (§6.3), so every committed fixture for `synthetic_3window` was filed under a name the
release no longer computes. **1155 green tests could not see it**, because the test environments
carried the old id — the suites and the shipped configuration disagreed about which model this
release runs, which is the same class of defect U028 itself was about.

Fixed by re-keying rather than re-recording: `python -m vsir.eval.synthetic_pdf` regenerates the
fixture under the current id, the four files under the old keys are deleted, and the responses are
byte-identical (verified by hash before the delete). The PDF and `expected.json` did not move, so no
acceptance number was re-baselined (C10). Every test environment now uses the same model id as
`.env` (§15 Factor X), and AGENTS.md records the rule: **a model-id change is a fixture re-key.**

**Notes**

- The plan's demo command names `TC1E-SF` and a JSON `--scope`; the shipped CLI takes repeatable
  `KEY=VALUE` (U015's convention) and the pilot is still absent (OQ-1), so the demo above is the
  same five moves against the generated corpus.
- **`skim_pages` needs a collection with vectors**, which the §13 M1 corpus deliberately has not:
  `vsir.eval.synthetic.seed` writes an empty vector map because M1 spends nothing. The L2 suites
  seed their own collection through the shipped `ingest/index.build_point`, so `lexical` and
  `captions` are the real surfaces and only the dense vector is stood in for (`seed_with_vectors`
  in `tests/api/conftest.py`).
- Nothing about `fetch`, `read` or the two aggregate rungs moved. `skim_documents`,
  `skim_sections`, `fetch` and `read` are still a typed `404` listing `["lookup", "resolve",
  "skim_pages", "verify"]`.
- **U029 (the document store) is next and blocks U018**, unchanged by this unit: `image.url` is a
  reference to a route that does not exist yet, and the L2 assertion on it is deliberately about the
  URL's shape. U018 owns the route **and** the percent-encoding of the `#` in a `page_id`.
  *(U029 shipped 2026-09-10 — see below. U018 is unblocked.)*

---

### U029 — The document store: `page_id` → bytes

**Milestone:** M4 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

The gap U018 could not be built over. Rasters are re-rendered on demand by design (§4.2) and
**nothing kept the file to render them from**: a CLI ingest happened to work because the operator's
copy was still on their filesystem, an upload spooled to `/tmp/<run_id>.pdf` and the reaper deleted
it when the run exited, and neither the page payload nor the run record named a file — register
**A5** removed `image_path` deliberately. Given `SICK-UE410-SD400@1.0#p002` there was no route from
page → document → bytes.

**Demo output** — the unit as planned had no Demo Command; this is the one added to the plan.

```
$ export VSIR_DOC_STORE=/tmp/vsir-demo-documents VSIR_FIXTURE=data/fixtures/synthetic_3window
$ vsir ingest data/source/synthetic_3window.pdf --vlm stub --until probe

01 manifest — identity, from the filename, the metadata and the uploader ─────
   doc_id       synthetic-3window
   revision     1.0   (undeclared — the default, and recorded as such (register A4))
   source       data/source/synthetic_3window.pdf  ·  87,741 bytes

02 probe — the text layer, and the only writer of `text` (I2) ────────────────
   page_count 42 · pymupdf-1.28.2 · content_hash 4c9b4585d8f9922e…
   pages with text 40/42 (searchable_ratio 0.95) · s2_input_mode render@220
   stored       /tmp/vsir-demo-documents/synthetic-3window@1.0.pdf  ·  87,741 bytes
   the source, not a raster: rasters are still never persisted (§4.2) — this is what
   `page_id` -> bytes resolves to, so a page can be rendered at query time (U029)
...
ALL ASSERTIONS PASSED

$ vsir documents
document store  /tmp/vsir-demo-documents
the SOURCE pdfs, never a raster: rasters are re-rendered on demand into an in-process
LRU cache and are never persisted (§4.2) — this is what they are re-rendered from

document                                        bytes  content_hash     stored_at
synthetic-3window@1.0                          87,741  4c9b4585d8f9922e 2026-09-10T12:37:11+00:00

1 document(s)

$ vsir documents --page 'synthetic-3window@1.0#p007'
page_id      synthetic-3window@1.0#p007
document     synthetic-3window@1.0  ·  page 7
source       /tmp/vsir-demo-documents/synthetic-3window@1.0.pdf  ·  87,741 bytes
content_hash 4c9b4585d8f9922ebaa0e2b0b17db155773f6c2d67691f569f3fb8a64b557927
rendered     595x842 px at dpi 72, 8,598 bytes, held in memory · 0 bytes written

$ vsir documents --page 'TC1E-SF@1.3#p001'                                  # exit 1
   REFUSED  document_not_stored: no source document for TC1E-SF@1.3 in the store at
   /tmp/vsir-demo-documents. The page is indexed and its image cannot be rendered:
   rasters are re-rendered on demand (§4.2), so the source has to be here. Re-ingest
   the document, or mount the volume VSIR_DOC_STORE names

$ vsir documents --page '../../../etc/passwd@1.0#p001'                      # exit 1
   REFUSED  document_id_unsafe: doc_id '../../../etc/passwd' cannot name a file in the
   document store: it must match ^[A-Za-z0-9][A-Za-z0-9._+-]*$ — alphanumeric, then any
   of . _ + -. A separator or a '..' here would be a path traversal carried by a
   citation, and mangling it instead would let two revisions share one file
```

**Tests** — L0/L1 `1191 passed`; L2/L3 `1167 passed, 13 skipped` (the 13 are U013's blocked
re-bill, unchanged). New: `tests/unit/test_store.py` (30), `tests/api/test_store_round_trip.py` (9).
Extended: `tests/unit/test_ingest.py` (+2), `tests/unit/test_upload.py` (+4).

**Acceptance criteria** — all five, each with the test that holds it:

| AC | Where |
|---|---|
| after an upload, `page_id → bytes` resolves for **every** page | `test_every_page_of_an_uploaded_document_resolves_to_bytes` — all 42, through a real upload whose spool is already deleted |
| the page payload gains no field; `INDEXED` unchanged; boot assertion passes | `test_the_page_payload_gained_no_field_and_the_boot_assertion_still_passes` — asserts the absence of `image_path`/`content_hash`/`source_path` on a real point and re-runs `schema_problems` |
| a missing document is a typed refusal naming `doc_id@revision` | `test_a_document_missing_from_the_store_is_a_typed_refusal_naming_it` (L2) and its L0 twin |
| `content_hash` on the run record; disagreeing bytes refused | `test_bytes_that_disagree_with_the_run_record_are_refused_rather_than_served` |
| *(beyond the ACs)* the deployed shape | `bash scripts/stack.sh up` seeds through the real pipeline into the volume, and a **separate one-off container** of the same image resolves `synthetic-3window@1.0#p007` to bytes and renders it — which is the property U018 actually needs: the replica that serves an image is not the process that ingested it |
| `--resume` completes an upload-started run after a restart | `test_an_upload_started_run_resumes_from_the_store_with_no_path_at_all` — a `202`, the client thrown away, then a **separate process** given nothing but the run id |

**Invariants / failure rows closed** — none newly. This unit claims no F-row: §10's *Closed at*
column gives F18's `fetch` half to U018, and nothing here is an invariant of its own. What it does
is make U018's row **reachable**.

**Decisions worth keeping**

- **Identity-addressed, integrity-checked — not content-addressed.** The plan said "content-
  addressed" and named the file `<doc_id>@<revision>.pdf` in the same sentence; those are different
  things and the second is right. `<sha256>.pdf` would need a hash *in the payload*, or a second
  index to find one — the coupling A5 removed, by another name. So the name is the document's
  identity, derivable from any `page_id`, and the hash moves to the run record where
  `locate(expect_hash=…)` checks it.
- **The deposit is step 02, not the upload route** — the one deviation from the plan's deliverable
  list, and it is amended in the plan with the reason. The route cannot know the document's
  identity: an undeclared `doc_id` is derived by step 01 from the filename and `content_hash` does
  not exist until step 02, so the route would have had to re-derive step 01's answer and drift from
  it — defect **P4** is what that drift already looks like. Because `POST /documents` *runs* the
  pipeline (§15 Factor XII), an upload deposits through the identical line a CLI ingest does. One
  writer: register **E1**'s lesson applied rather than restated. It also means the compose `seed`
  service and every existing CLI ingest populate the store with no further work.
- **A re-ingest of the same `(doc_id, revision)` overwrites, and that is safe *because* of the
  hash.** Until publish retires the previous run's pages (§6.7) the index still points at them, and
  rendering the new file for one of those pages would answer with a page nobody indexed. The run
  record's `content_hash` makes the disagreement a named refusal instead of a wrong image. This is
  the case the AC exists for and it is the only reason to store a hash at all.
- **The traversal guard is not tidiness.** `parse_page_id` accepts any revision but `@` and `#`,
  and a `page_id` arrives from a caller's saved citation (`resolve`, §7.2.3) — so
  `TC1E-SF@../../../../etc/passwd#p001` was a path traversal with a citation as its payload. Unsafe
  identifiers are **refused**, never mangled: mangling would collapse two revisions onto one file,
  and then one document's bytes would be served for the other's pages. It fires at ingest, where
  the operator can still correct what they typed.
- **`VSIR_DOC_STORE` is optional, not a thirteenth required variable.** §4.3's contract is that
  unsetting a *required* one is a named non-zero exit, and a release that never ingests must still
  boot. Unset means a directory under the platform temporary directory — honest about being
  ephemeral rather than pretending to be a volume. `docker-compose.yml` mounts the real one.
- **The upload boundary pre-flights the store.** A release with no writable store still ingests,
  indexes and publishes perfectly well, and every page of that document is then permanently
  imageless. That is a `202` that quietly buys half a document, so it is a `503` the caller reads —
  the same principle as the `fixture_not_found` refusal beside it.
- **`vsir ingest`'s PDF argument is now optional with `--resume`.** The run record names
  `doc_id@revision` and carries `content_hash`; the store holds the bytes. A resume also inherits
  the run's declared identity, because step 01 would otherwise derive `stored-over-http-3-1` from
  the store's own filename and the run would refuse itself `run_document_mismatch`. What verifies
  the *bytes* is the hash, which is the stronger of the two checks.
- **`--steal` is still needed after a restart** and that is the lease's design, not a gap here: a
  worker that dies holding a lease does not release it (D9). The test says so rather than working
  around it.

**Spec / plan changes made**

- **Spec §4.2** — a *Source documents* row beside the *Rasters* row. §4.2's *"no blob store, no
  local source of truth"* is about **rasters** and stays true; a reader of that table today would
  otherwise conclude nothing is on disk, which is now wrong.
- **Spec §7.4** — the `POST /documents` row said *"A run started this way is **not** resumable
  across an instance restart"*. It now says it is, from U029, and why.
- **Plan U027** — its first disclosed limitation is struck with the test that closes it.
- **Plan U029** — deliverables amended (above), a Demo Command added, ACs ticked.

**Two defects the tests could not see, found by running the stack**

Both are the U028 lesson again: 1,191 green tests say nothing about the deployed shape, because
no test runs as uid 10001 against a Docker named volume.

- **The volume was root-owned and the container could not write to it.** `bash scripts/stack.sh up`
  refused the seed at step 02 with `document_store_unwritable: Permission denied
  '/srv/documents/.staging'` — the refusal working exactly as designed, and useless. Docker
  initialises a fresh named volume from whatever is at its mount point *in the image*, ownership
  included; nothing was there, so it made the directory root-owned and the non-root runtime user
  was locked out of its own volume. Fixed in `backend/Dockerfile` — `mkdir -p /srv/documents &&
  chown 10001:10001` — which is also why the mount point cannot live only in the compose file.
- **A refusal detail called `reason` crashed the logger.** `StoreUnwritable` carried
  `reason=<OSError subclass>` and `cli.py` splats a refusal's details into
  `_log.error("ingest_refused", reason=refusal.code, …)` — two values for one keyword, so a clean
  named refusal came out as a traceback. The key is `os_error` now. It is the only collision in
  the package (`vlm/client.py`'s `finish_reason` is a different name), but the trap is general:
  a refusal's `details` share a namespace with the log line's own fields.

**Notes / follow-ups**

- **`docker-compose.test.yml` was not changed.** Its `backend-test` container serves; the L2 suites
  build their apps in-process and point `VSIR_DOC_STORE` at a `tmp_path`, so the container needs no
  volume. A container that *ingested* would.
- **Nothing prunes the store.** A document retired by §6.7 keeps its file, deliberately — F9's
  `found_only_in_superseded` reads from the superseded revision's pages, and those pages have
  images. A store that grew without bound at corpus scale is an M8 question, not this one.
- **U018 can now be built.** `store.for_page(page_id)` returns `(document, page_no)` and
  `render.render_page` takes it from there; the L2 test already does exactly that at dpi 72.

---

### U018 — The page-image endpoint, the raster cache, and `fetch`

**Milestone:** M4 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

The raster becomes reachable, and M4 closes. Two surfaces onto the same pixels — a
bearer-authenticated `GET /pages/{page_id}/image` a browser `<img>` can point at, and `fetch`,
which hands an agent the material instead of an answer — with every §7.3 bound in front of both as
a typed 400, and nothing written to disk on either path. `impl` had neither: its only way to see a
page was `read()`, the call that bills, and that returned 503 for every page anyway because the
raster path on the record was stale (register **A5**). **Splitting looking from comprehending is
what lets an agent choose a page before deciding it is worth money.**

**Demo output** — `vsir demo narrow`, run as a one-off container of the same image against the
stack `bash scripts/stack.sh up` seeds (§15 Factor XII). It deliberately does **not** seed a corpus
of its own: `fetch` needs the *source document* reachable through the store (U029), so a demo that
built its own would be proving that a directory it had just written to could be read back.

```
$ bash scripts/stack.sh vsir demo narrow                                    # exit 0
   collection vsir_pages_1536 · document store /srv/documents · 2 document(s) held

01 NARROW — skim_pages('guard door interlocks') ──────────────────────────────
   status ok · total 42 · weak true · scope {'is_current': True}

   rank  page_id                         why                   trust       image reference
   1     synthetic-3window@1.0#p019      dense,lexical         ok          /pages/synthetic-3window@1.0%23p019/image?dpi=150
   2     synthetic-3window@1.0#p021      dense,lexical         ok          /pages/synthetic-3window@1.0%23p021/image?dpi=150
   3     synthetic-3window@1.0#p022      dense,lexical         ok          /pages/synthetic-3window@1.0%23p022/image?dpi=150
   4     synthetic-3window@1.0#p018      dense,lexical         ok          /pages/synthetic-3window@1.0%23p018/image?dpi=150
   5     synthetic-3window@1.0#p020      dense,lexical         ok          /pages/synthetic-3window@1.0%23p020/image?dpi=150
   PASS  every row carries an image REFERENCE and no row carries bytes or text (P2)

02 the reference is dereferenceable — /pages/{page_id}/image ─────────────────
   PASS  the `#` of §5.1's page_id is percent-encoded in the URL, and round-trips
         /pages/synthetic-3window@1.0%23p019/image?dpi=150  →  page_id 'synthetic-3window@1.0#p019'
   PASS  the page resolves to the bytes it was indexed from, and renders in memory
         synthetic-3window@1.0 page 19 · synthetic-3window@1.0.pdf · 1240x1755 px at dpi 150
         · 74,076 bytes · 0 bytes written

03 LOOK — fetch(2 page(s), inline=true) ──────────────────────────────────────
status       ok — the CALL ran; the material is below (2 page(s))

  PAGE       synthetic-3window@1.0#p019 · trust ok
    image    /pages/synthetic-3window@1.0%23p019/image?dpi=150
             dpi 150 · 1240x1755 px · region full page · bytes_b64 98,768 chars
    text     506 chars · 'Safety functions of the C24 cell\nGuard door interlocks\nSF 2.19C) …'
    summary  Page 17 covers guard door interlocks stage 17 within the guard door … [en]
   PASS  every fetched page carries a URL **and** the pixels (inline defaults to true)
         2 page(s), 196,524 chars of base64

04 the same fetch with inline=false — the reference only ─────────────────────
   PASS  url present, bytes_b64 absent — the console renders from the URL instead
         2 page(s) in 2,292 bytes of JSON; bytes_b64 [None, None]

05 the crop — fetch(dpi=400, region=[0.0, 0.0, 1.0, 0.55]) ───────────────────
   /pages/synthetic-3window@1.0%23p019/image?dpi=400&region=0,0,1,0.55
   PASS  a crop, rendered on demand at 400 dpi and stored nowhere (§7.2.5, D6)
         3306x2573 px · region [0.0, 0.0, 1.0, 0.55] · 222,476 chars of base64

06 the bounds — every violation a typed 400 naming what it broke (F18) ───────
   PASS  fetch, 6 pages → fetch_budget_exceeded
         400 fetch_budget_exceeded: fetch takes at most 5 pages, got 6
   PASS  fetch, dpi=400 with no region → dpi_requires_region
         400 dpi_requires_region: dpi 400 exceeds 220 and requires a region: detail that fine
         is about part of a page, and a full page at this dpi is megapixels of raster
   PASS  fetch, 2 whole page(s) at dpi=300 — the 12 MP bound is checked before anything is rendered
         400 fetch_budget_exceeded: fetch is bounded at 12.0 MP, requested 17.4 MP
   PASS  fetch, dpi=100 → dpi_not_allowed
         400 dpi_not_allowed: dpi must be one of [36, 72, 150, 220, 300, 400], got 100

07 the raster cache — in memory, evictable, and never a source of truth ──────
   PASS  the second identical request renders nothing — it is served from memory
         cold {'hits': 0, 'misses': 1, 'size': 1, 'maxsize': 96} → warm {'hits': 1, 'misses': 1, …}
   PASS  after eviction it renders again and the image is byte-identical (a cold instance)
         74,076 bytes, sha256 d5acd3fc4a3703e6… → 74,076 bytes, sha256 d5acd3fc4a3703e6…

ALL ASSERTIONS PASSED
```

**Tests** — L0/L1 `1216 passed`; L2/L3 `1277 passed, 13 skipped` (the 13 are U013's blocked
re-bill on OQ-1, unchanged). New: `tests/api/test_page_image.py` (39), `test_fetch.py` (24),
`test_fetch_caps.py` (26), `test_raster_cache.py` (19).

**Acceptance criteria** — all eleven, each with the test that holds it:

| AC | Where |
|---|---|
| `GET …?dpi=150` with a token is a 200 PNG; without one, a 401 | `test_a_page_image_is_a_png_with_a_bearer_token` · `test_the_same_page_without_a_token_is_refused` |
| the same request twice renders **once**; after eviction it renders again, byte-identically | `test_two_identical_requests_render_once_and_a_third_after_eviction_renders_again` |
| a write spy sees no raster on the filesystem; a cold process is byte-identical | `test_serving_a_page_image_writes_nothing_to_the_filesystem` · `test_a_cold_process_returns_a_byte_identical_image` |
| 6 page ids → `fetch_budget_exceeded {limit: 5, requested: 6}`, no partial 5-page 200 | `test_six_pages_is_refused_and_there_is_no_partial_five_page_result` |
| over 12 MP names the **megapixel** bound, never a dpi clamp | `test_two_pages_at_300_dpi_exceed_the_megapixel_bound_and_name_it` |
| `dpi=100` → `dpi_not_allowed`; `dpi=36` and `72` succeed | `test_a_dpi_off_the_list_is_dpi_not_allowed` · `test_the_two_thumbnail_tiers_succeed` |
| `dpi=400` with no region → `dpi_requires_region`; with one, a crop | `test_above_the_answer_dpi_a_region_is_required` · `test_the_same_call_with_a_region_succeeds_and_returns_a_crop` |
| `inline=True` returns url **and** bytes; `inline=False` url only | `test_inline_defaults_to_true_and_the_bytes_are_a_png` · `test_inline_false_returns_the_reference_only` |
| `include=["text","summary"]` returns no image and performs **zero** renders | `test_dropping_image_makes_it_a_cheap_text_read_and_renders_nothing` |
| a region out of range is a typed 400, not a clipped guess | `test_an_out_of_range_region_is_a_typed_400_and_not_a_clipped_guess` |
| `vsir demo narrow` exits 0 with the narrowing, the crop and the typed 400s | the demo above, exit 0 |

**Invariants / failure rows closed** — **F18 (`fetch` half)**: the §7.3 caps, each a typed 400
naming its bound, held by `test_six_pages_is_refused_and_there_is_no_partial_five_page_result`,
`test_two_pages_at_300_dpi_exceed_the_megapixel_bound_and_name_it`,
`test_the_megapixel_bound_is_decided_before_a_single_render`,
`test_a_dpi_off_the_list_is_dpi_not_allowed` and
`test_above_the_answer_dpi_a_region_is_required` (all `tests/api/test_fetch_caps.py`). F18's
`read` half stays with U020 (§10 *Closed at*). No invariant is newly asserted here.
*(Citations corrected at the completion gate: this read "`test_fetch_budget_exceeded`-family and
`test_dpi_requires_region`" — both are **error codes**, not tests, and neither name exists in the
suite. The guards were real; the pointers to them were not.)*

**Decisions worth keeping**

- **`serve/raster_cache.py` holds no cache.** The name says otherwise and the module says so in its
  first paragraph: the LRU is `ingest/render.py::_cached`, keyed by the source's **content hash**.
  A second cache here keyed by `page_id` is the obvious optimisation and is a correctness bug — a
  `(doc_id, revision)` re-ingested from corrected bytes keeps its page ids, so it would serve the
  superseded pixels for the life of the process, and hold a second copy of every PNG while doing
  it. What the module owns is the four things a *request* needs: the URL grammar and its encoding,
  resolution, the integrity check, and the megapixel bound **in front of** the render.
- **The megapixel bound is predicted, never measured.** `predicted_megapixels` reads the page
  rectangle; measuring the pixmap would mean the bound that exists to cap the memory spike had
  already paid for what it refuses (§15.1). `test_the_megapixel_bound_is_decided_before_a_single_render`
  fails the run if `_render` is called at all.
- **Three refusals, kept distinct, because a caller retries them differently.**
  `page_not_found` (404) — the corpus does not hold it. `page_not_current` (404) — it does, and the
  document moved on; told *"no such page"* a caller concludes its citation was wrong, when
  `resolve` is the move that answers (F9, §6.7). `document_not_stored` (**503**) — the page is
  indexed and real and its image cannot be made, which is an operational problem and not the
  caller's mistake (§11.3).
- **The `#` encoding landed with the route, deliberately.** U014 emitted `ImageRef.url` by
  interpolation, so a `page_id`'s `#` (§5.1) made every reference undereferenceable —
  `/pages/SYN-M1@1.0` with a fragment the server never sees. `page_image_url` and
  `page_id_of_path` are now the only producer and the only reader, `@` is left literal so a
  citation stays readable, and the round trip is asserted in the demo and in
  `test_lookup_pure.py`. The three assertions that encoded the old unencoded form moved with it.

**Two defects found and fixed while closing the unit**

- **A text-only `fetch` refused `document_not_stored`.** `fetch` resolved the document store before
  it looked at `include`, so §7.2.5's *"cheap text/summary read"* was the one shape of `fetch` most
  likely to be **unavailable** — it failed on any corpus whose source PDFs are not mounted, which
  is exactly the hand-written M1 corpus. `text` and `summary` are payload fields (§5.3) and have
  nothing to do with the volume the page was rendered from. Resolution is now two functions —
  `resolve_payloads` (the index; always) and `attach_sources` (the store; only when pixels were
  asked for) — and the refusal moved behind the part that needs it rather than being removed.
  Caught by `test_mcp_parity.py::…[fetch-text]`; guarded now by
  `test_a_text_read_needs_no_document_store_at_all`, which asserts both halves on one corpus.
- **The demo's megapixel case never reached the megapixel bound.** It asked for one page named
  twice at a bare `dpi=300` — and `fetch` de-duplicates its page list, and every dpi above 220
  requires a region, so the call was refused by `dpi_requires_region` one bound early. Two distinct
  pages and an explicit full-page region now; the assertion also pins `bound == "megapixels"`, so a
  demo cannot print `PASS` for a bound it did not exercise.

**Notes / follow-ups**

- **A flaky U029 test, fixed at its root.** `test_an_upload_started_run_resumes_from_the_store_with_no_path_at_all`
  asserted the spool was gone the instant the 42 points appeared. The points land while step 10 is
  still running and `serve/ingest.py::_reap` unlinks when the **child exits**, which is strictly
  later — a race that passes on a slow machine and fails on a fast one. It polls for the reap now,
  which asserts the same fact without depending on which won. The product was correct.
- **The dpi tiers are cache-only and feed no key** (SA-12): `fetch` and thumbnails render at
  36/72/150/220/300/400, while `dpi_index=150` feeds the embedded raster and `dpi_220` feeds
  `extract_key` and `read_key`. Nothing this unit renders can change a cache key.
- **M4 is complete** — U017, U029 and U018. `skim_documents`/`skim_sections` are M5 (U019), and
  `stack.sh status` says so rather than listing them as missing.

---

### U019 — `skim_documents`, `skim_sections`, and `searchable_ratio`

**Milestone:** M5 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

The narrowing ladder is complete, and it is complete without a second search. §7.2.1's *"one
implementation, exposed three times"* is now a fact about the code: `_candidates()` runs the
branches and fuses them, and `skim_pages`, `skim_documents` and `skim_sections` are three
renderings of the one list it returns — truncated to `limit`, grouped by `doc_id`, grouped by
`section_id`. The load-bearing test is the set equality, not the shapes: the `doc_id`s
`skim_documents` returns are exactly the distinct `doc_id`s of the `skim_pages` rows for the same
`(query, scope, exclude)`, `pages_matched` is the number of those rows in the group and `best_rank`
is the smallest `rank` in it. If the aggregates ever become a second retrieval, those three fail
together.

The other half of the unit is one number. `searchable_ratio` on every document row is §5.7's blind
spot made visible, and the row that carries it is returned **even when nothing in that document
matched**. That is not a nicety: a fully scanned binder has no text surface, so a query carrying a
printed code puts every one of its pages behind a phrase filter it cannot satisfy, and the binder
does not rank low — it is *not there*. The agent reads a confident list of the binders that were
searched and concludes the part does not exist. F4, at the document level. So the binder comes back
at `0.00` with `pages_matched: 0`, `best_rank: 0`, a thumbnail of its first page and a
`next.expand` to descend into with `fetch` — sorted after every group that matched, so a disclosure
can never displace a result.

**Demo output** — the plan's demo command, adapted to the corpus that exists. `TC1E-SF` is still
absent (OQ-1), so the demo runs against what `bash scripts/stack.sh up` ingests through the real
pipeline, plus a **second document from the same bytes** (`--doc-id CELL-B-BINDER`, replayed from
the same content-hash-keyed fixture, free) — because a document rung with one document has no
grouping to show. Same code path as `POST /tools/skim_documents`, asserted byte-for-byte in
`test_mcp_parity.py`.

```
$ vsir skim documents "emergency stop reset"

status       ok · total 84 page(s) · capped false · weak true · needs_scope true
scope        {'is_current': True} · searched 84 page(s), 4 with no text layer

rank  doc_id                          matched  searchable  preview
1     synthetic-3window               39       0.95        /pages/synthetic-3window@1.0%23p031/image?dpi=72
      Page 29 covers light curtain muting stage 29 within the light curtain muting section. It names K131
      next: expand {'doc_id': 'synthetic-3window'}
3     CELL-B-BINDER                   33       0.95        /pages/CELL-B-BINDER@1.0%23p013/image?dpi=72
      Page 11 covers emergency stop chain stage 11 within the emergency stop chain section. It names K113
      next: expand {'doc_id': 'CELL-B-BINDER'}

P2           no aggregate row carries a page_id, page text or image bytes: confirmed
reads_left   50 · release dev-0 · schema 1

$ vsir skim sections "emergency stop reset" --scope doc_id=synthetic-3window

rank  section_id                      matched  pages       preview
1     synthetic-3window@1.0#s004      5        13–17       /pages/synthetic-3window@1.0%23p013/image?dpi=72
      Emergency stop chain
      next: expand {'section_id': ['synthetic-3window@1.0#s004']}
2     synthetic-3window@1.0#s003      4        9–12        /pages/synthetic-3window@1.0%23p009/image?dpi=72
      Machine layout and access points
3     synthetic-3window@1.0#s007      5        27–31       /pages/synthetic-3window@1.0%23p031/image?dpi=72
      Light curtain muting
…
35    synthetic-3window@1.0#s002      6        3–8         /pages/synthetic-3window@1.0%23p003/image?dpi=72
      General information and symbols
37    synthetic-3window@1.0#s001      2        1–2         /pages/synthetic-3window@1.0%23p001/image?dpi=72
      Front matter

$ vsir skim documents "muting K131" --scope page_no=1      # the blind spot, disclosed

status       not_searchable · total 0 page(s) · capped false · weak false · needs_scope false
scope        {'page_no': 1, 'is_current': True} · searched 2 page(s), 2 with no text layer

rank  doc_id                          matched  searchable  preview
—     CELL-B-BINDER                   0        0.00        /pages/CELL-B-BINDER@1.0%23p001/image?dpi=72  ← no text layer at all: nothing in it can be searched
      This is the scanned cover sheet of the manual. It shows the title, the revision and the validity sta
      next: expand {'doc_id': 'CELL-B-BINDER'}
—     synthetic-3window               0        0.00        /pages/synthetic-3window@1.0%23p001/image?dpi=72  ← no text layer at all: nothing in it can be searched
      This is the scanned cover sheet of the manual. It shows the title, the revision and the validity sta
      next: expand {'doc_id': 'synthetic-3window'}

next         suggest ['lookup']
```

That third call is the whole unit in one screen. The scope is the two cover sheets, both scanned;
the query carries `K131`, which `decompose()` splits out as a phrase filter over `text`; nothing
can match, so `skim_pages` returns nothing at all and the status is `not_searchable` —
*escalate to vision*. The two rows say **which binders to escalate to**, at `0.00`, with a
thumbnail each. The status is decided by the pages and not by the presence of the rows: saying `ok`
because the blind spot was disclosed would turn the disclosure into the answer.

Over HTTP, in the container, the same call:

```
$ curl -s -H "Authorization: Bearer $TOKEN" -X POST http://localhost:8055/tools/skim_documents \
       -H 'Content-Type: application/json' -d '{"query":"emergency stop reset"}'
status ok · total 84 · rows 2
  synthetic-3window 39 1 0.9523809523809523 /pages/synthetic-3window@1.0%23p031/image?dpi=72
  CELL-B-BINDER     33 3 0.9523809523809523 /pages/CELL-B-BINDER@1.0%23p013/image?dpi=72
keys ['best_rank', 'doc_id', 'doc_type', 'next', 'pages_matched', 'preview', 'searchable_ratio', 'summary', 'title']
```

**Tests:** `bash scripts/test-unit.sh` → 1216 passed. `bash scripts/test-api.sh` → 1321 passed,
13 skipped (all thirteen the pre-existing U013/OQ-1 rows of `test_acceptance_real.py`). The 43 new
rows are `test_skim_aggregates.py` (27) and `test_searchable_ratio.py` (13), plus three in
`test_mcp_parity.py` for byte identity on the three rungs against a multi-document corpus.

**Invariants / failure rows closed:** none newly, as the plan says. What this unit adds is the
surface that makes **F4**'s disclosure visible at the *document* level, and the §13 M5 acceptance
clause C13 moved here from M4 — *every aggregate row carries a `preview.thumb_url`, the group's
best-ranked matched page, falling back to page 1, a reference and never bytes* (D12).

**Notes / decisions**

- **The aggregates group the full fused candidate list, not the page rung's ten rows.** §7.2.1
  rule 4 says they *"group the same fused candidates"*, and `limit` is a property of the page
  rung's output rather than of the search. The set-equality criterion is therefore asserted with
  `skim_pages(limit=25)` on a corpus whose candidates fit inside it — otherwise the test would be
  comparing two different cuts and calling the difference a drift.
- **`DocHit` and `SectionHit` gained a `next`.** §7.1's hit-shape *list* omits it, but the prose
  three paragraphs down says their *"job is to hand back a **scope** to descend into
  (`next.expand`)"*, and the unit's AC requires that scope to reproduce the group. One field on
  each, `NextMoves` as everywhere else, and `expand` is `{"doc_id": …}` / `{"section_id": [id]}` —
  a dict the caller passes straight back rather than a string it assembles.
- **`best_rank: 0` is `envelope.UNRANKED`, a disclosure row's ordinal.** Ranks are 1-based
  everywhere in this surface, so zero cannot be read as a position; `pages_matched: 0` sits beside
  it and the row sorts after every group that matched.
- **`searchable_ratio` is the ratio over what was *searched*, and it is counted, not read off
  `scope_stats.docs`.** Two facets bounded by the ten rows, on the same `scoped` filter, so where
  a document appears in both the two numbers are the same number — asserted. Reading it off
  `scope_stats.docs` instead would have been free and wrong at the edge: that breakdown is capped
  at 64 documents because it is a display, and a matched binder outside the cap would have
  inherited the field's `0.0` default and been reported as a blind spot. The one number on the row
  an agent is meant to act on, inverted.
- **Only ratio `0.00` earns a disclosure row.** A half-scanned binder is found through the pages
  that do have text and is an ordinary group; disclosing every document that merely failed to
  match would return the corpus and undo the narrowing the rung exists to do.
- **`lookup._no_text()` became `lookup.no_text()`** — public, so `skim_documents` counts §5.7's
  *"this page has no text layer"* through the same one condition `scope_stats` counts it with.
  Two spellings in two modules is how a ratio and the `pages_no_text` beside it in one response
  come to disagree.
- **`DocHit.title` is empty, and that is a fact about the record.** §5.3 has no document-level
  title field. S1 *does* return one — `data/fixtures/synthetic_3window/facts/*.json` carries
  `"title": "C24 SYNTHETIC SAFETY MANUAL"` — and derivation drops it, because there is nowhere on
  the page record to put it. Deriving one here from the filename or the first section heading would
  be an interpretation of the kind §5.2 refuses, so the field stays in the contract like
  `next.references`, and `summary` carries the sentence a person actually needs. **Follow-up for
  whoever owns the next record-schema change:** a `title` on the run record or as a document-level
  payload facet would fill it for free, since S1 already paid for it.
- **The free stub cannot ingest a new PDF, so the demo's scanned binder is a scope and not a new
  document.** `VSIR_VLM=stub` *requires* `VSIR_FIXTURE` and refuses `vlm_backend_unavailable`
  without it (D10) — there is no generative stub — and a fixture is keyed by content hash, so any
  new PDF is a `fixture_miss`. The `0.00` rows above are therefore the two real scanned cover
  sheets of the ingested corpus, reached with `--scope page_no=1`. A fully scanned *document* is
  exercised in L2 instead, where `conftest.AGGREGATE_DOCS` seeds one (`AGG-SCAN`, three pages, no
  text) beside a half-scanned and an all-text binder.

---

### U020 — `read`, the paid step: stamped codes, a mandatory `sufficient`, and a question-keyed cache

**Milestone:** M5 · **Spend:** paid (read) · **Status:** `[x]` Complete · **Completed:** 2026-09-10

The tool that spends, and the one that still never answers. `read(page_ids, question)` renders at
most three pages the caller already chose, at the **pinned dpi 220**, asks one question about
them, and hands back a bounded `extract`, a `codes` table where every code has been phrase-checked
against that page's own text, a **mandatory `sufficient`**, `flags` and `page_provenance`. There is
no `dpi` parameter, no `region`, no ranking, no `next` and no suggestion about where else to look:
§7.6's *"retrieval judgment never happens inside `read`"* is enforced by an AST scan of the module
in the L0 suite, beside the scan that proves it builds no matcher of its own.

**The stamp is `verify`'s, and that is the whole unit.** `impl` stamped `text_layer_backed` from
its own `token_set()` over its own tokeniser, with no relationship to the index anything else
searched — so the tool that found a page and the check that confirmed it could disagree. Here every
code goes through `core/verify.py::verify_claims`, the same function `POST /tools/verify` calls,
which asks `core/exact.py::exact_filter` the question `lookup` asks, scoped to one page. One
vocabulary, `present | absent | unverifiable`; one meaning; one code path (F2). And `unverifiable`
exists, which a boolean could not say: on a page with no text layer **every** code is
`unverifiable` — including a code genuinely printed three sheets away, because the check is per
`(code, page)` and a page nobody can read cannot support a code that lives next door (R2).

**Nothing is withheld.** §2.5 B struck `withheld[]`, `id_class` and the identifier grammar: a code
that failed its check is returned *stamped*, never removed, because dropping it hides the
transcription error from the only party that can act on it.

**Demo output — the plan's demo command, against real Gemini** (`VSIR_ALLOW_PAID=1`). OQ-1 is
still open, so the pages are the generated corpus's rather than `TC1E-SF`'s — which is the
stronger fixture for what this row proves, because every line printed on every page of it is known
exactly from `vsir.eval.synthetic_pdf.expected_text`, and the assertion is against the paper rather
than against the index.

```
$ VSIR_ALLOW_PAID=1 VSIR_VLM=gemini vsir read --pages "C24-DEMO@1.0#p019,C24-DEMO@1.0#p020" \
    --question "which monitored relay and which safe input channel does each of these two sheets name?"

{"event":"vlm_call","model":"gemini-3.8-flash","stage":"read","images":2,"finish_reason":"STOP", …}
{"event":"read","origin":"model","dpi":220,"pages":2,"codes":6,"present":6,"absent":0,
 "unverifiable":0,"sufficient":true,"flags":[], "cache_key":"3106175f44ae5afc…"}
{"event":"audit","audit":{"tool":"read","dpi":220,"input_tokens":2858,"output_tokens":165,
 "cache_hit":false,"latency_ms":10290,"page_ids":["C24-DEMO@1.0#p019","C24-DEMO@1.0#p020"], …}}

status       ok — the CALL ran; the answer is below
sufficient   true — these pages answer the question on their own

extract      'For stage 17 (first sheet), the document lists relay K119 and safe input channel SI4
              ("B219 --> K119 - SI4"), with verification required after replacement of K119. For
              stage 18 (second sheet), it lists relay K120 and safe input channel SI1
              ("B220 --> K120 - SI1"), with verification required after replacement of K120.'

codes        6 stamped against the page's own text (§7.2.6, Loop 1)
  PRESENT       K119  ·  on C24-DEMO@1.0#p019
  PRESENT       SI4   ·  on C24-DEMO@1.0#p019
  PRESENT       B219  ·  on C24-DEMO@1.0#p019
  PRESENT       K120  ·  on C24-DEMO@1.0#p020
  PRESENT       SI1   ·  on C24-DEMO@1.0#p020
  PRESENT       B220  ·  on C24-DEMO@1.0#p020

flags        —
  page       C24-DEMO@1.0#p019 · text_trust ok
  page       C24-DEMO@1.0#p020 · text_trust ok

reads_left   49 · release dev-0 · schema 1
```

Six codes, all transcribed verbatim off the raster, all six genuinely printed where the stamp says
they are. **The same call again is a cache hit and bills nothing**, and the identical call from a
*second instance* is too, because the entry is a control point in `vsir_runs` and not a dict on a
process:

```
   read       origin cache · present 6
   audit      cache_hit True · input_tokens 0
```

**The failure branch, also live — R2, on the two scanned cover sheets:**

```
$ VSIR_ALLOW_PAID=1 VSIR_VLM=gemini vsir read --pages "C24-DEMO@1.0#p001,C24-DEMO@1.0#p002" \
    --question "which machine or equipment code is printed on these sheets, and which revision do they state?"

extract      'C24 SYNTHETIC SAFETY MANUAL\nRevision 1.0'
codes        2 stamped against the page's own text (§7.2.6, Loop 1)
  UNVERIFIABLE  C24  ·  no_text
  UNVERIFIABLE  1.0  ·  no_text
flags        ['no_text_layer', 'unverified_codes']
  page       C24-DEMO@1.0#p001 · text_trust no_text
  page       C24-DEMO@1.0#p002 · text_trust no_text
```

That is the whole design in six lines. The model **did** read the sheet — `C24` and `1.0` are
correct, and a person can see them — and the system says `unverifiable`, not `present`. It refuses
to convert a legible pixel into evidence, forever if need be, and the badge is the deliverable.

**The free half, replayed through the stack** (`bash scripts/stack.sh vsir read …`, spends nothing,
D10) — the case §7.2.6's own example is drawn from, with a deliberate misread:

```
codes        4 stamped against the page's own text (§7.2.6, Loop 1)
  PRESENT       K119  ·  on synthetic-3window@1.0#p019
  PRESENT       SI4   ·  on synthetic-3window@1.0#p019
  PRESENT       K120  ·  on synthetic-3window@1.0#p020
  ABSENT        K152  ·  on …#p019, …#p020  ·  different part: k119, k120
flags        ['unverified_codes']

# the same two pages, a different question — a MISS (F19), a second call, its own answer
   vlm_replay  a SECOND call — the question is on read_key
   read        origin replay · cache_key 3a5e38f4f79bfe8b…
extract      'Q69 is the contactor on the first sheet and Q70 on the second, both printed as
              TELEMECANIQUE LC1-D38BL.'

# a fourth page — a typed 400 naming its bound, zero model calls, quota untouched
   REFUSED  400 read_page_cap_exceeded: read takes at most 3 pages, got 4
```

**Invariants / failure rows closed:** **F18 (read half)** — the ≤ 3-page cap as a typed 400 naming
its bound, checked *before* the quota is charged
(`test_a_fourth_page_is_a_typed_400_naming_its_bound`,
`test_the_page_cap_does_not_cost_the_caller_a_read`).
*(Citation corrected at the completion gate: this read `test_read_page_cap_exceeded`, which is the
**error code** the test asserts on, not a test that exists. A closing citation nobody can grep is
the defect this file treated as one at the M1 gate.)* **F19** — `read_key` includes the question, so
a new question is a miss (`test_a_new_question_about_the_same_pages_makes_a_second_call`). §11.3's
two `read` rows: `429 budget_exhausted` and `503 vlm_unavailable` **while all seven free tools still
return 200**. No invariant is newly asserted here — I8 is U022's, and this unit provides one of its
inputs.

**Tests:** 43 L0 (`test_read_stamps.py`) · 44 L2 (`test_read_replay.py`, `test_read_caps.py`,
`test_read_cache.py`) · 10 L4 (`test_read_real.py`, gated). Every L0–L2 row runs with `VSIR_VLM=stub`
and no credential.

**Notes:**

- **The live run found a defect four replay suites could not.** The audit line for a **cache hit**
  reported the *original* call's `input_tokens: 2858` beside `cache_hit: true`. In replay both are
  zero, so no fixture-backed test could see it; against a real model it means an operator summing
  §7.4's token columns over a month bills every re-read at the price of the read it replaced. A
  cache hit now reports `0 / 0`, and `test_the_audit_line_says_which_call_cost_nothing` asserts it.
  This is U028's lesson recurring exactly as U028 predicted it would.
- **The first live call abstained, and it was right to.** The question originally chosen for the L4
  row — *"what must be true before the guard door interlock releases?"* — is not answerable from
  two safety-function **list** sheets, and the model returned an empty extract with
  `sufficient: false` rather than composing one. That is the behaviour §7.2.6 makes `sufficient`
  mandatory for, so it is now its own L4 row (`test_a_real_model_abstains_rather_than_composing…`)
  and the *answerable* rows ask something the sheets actually print. Worth stating plainly: a green
  L4 whose every code list was empty would assert nothing, so
  `test_the_model_actually_read_the_sheet_and_named_codes` is the row that separates *"the model
  abstained"* from *"the raster never arrived"*.
- **The `read` cache is net-new infrastructure, and plan §4c's P2 can now be closed by whoever owns
  it.** `vlm/cache.py::ControlPlaneStore` is a read/write cache keyed exactly as §6.3 says, living
  on `kind: vlm_cache` points in `vsir_runs` (D9) — not process memory, not local disk. `read` uses
  it; **ingestion does not yet**, which is P2's remaining half: `extract_window` still calls the
  backend directly, so a live re-ingest re-bills S2. The store it needs now exists and takes two
  lines to adopt.
- **A store failure on the way *into* the cache is swallowed and logged; on the way *out* it
  raises.** The model has already answered and the caller is owed that answer, so a failed cache
  write costs only the next identical call; a cache *read* that cannot reach the store is a `503`,
  because guessing *"probably not cached"* during an outage is how an outage becomes an unmetered
  afternoon.
- **`prompts/read.md` joined `s2-v1` rather than opening a version of its own.** The version labels
  the released prompt *set*; the two extraction digests under it are unchanged and `read` had no
  cached response in existence to invalidate. Opening `s2-v2` for a file no extraction call reads
  would have re-keyed every frozen S2 response in the repository and re-billed a full corpus.
- **`precheck` is a new field on `ToolSpec`, and only `read` sets one.** The budget is charged
  before the tool runs — it must be, because the money is spent inside it — so every bound that can
  be settled from the request alone is settled before that. Without it a caller that named four
  pages would have a read taken off its quota to be told it named four pages.
- **Five L2 rows used `read` as *the* example of a tool this release does not serve** and now name
  `expand` and `compare` instead — `impl` endpoints struck by §2.5 A, which is what a client
  migrating from the previous service actually reaches for. §7.2's eight are all served from here.
- **The paid demo ran against the generated corpus, not `TC1E-SF` (OQ-1).** What remains deferred
  is exactly one line of U020's acceptance: *"one real `read` against the frozen `TC1E-SF` pages …
  matches the human-verified entry in `expected.json`"*. Everything it was there to prove — the
  call is well-formed, a real transcription never lands falsely `present`, an unreadable page is
  `unverifiable`, a real model abstains — is proved above against a corpus whose printed text is
  known exactly. Point `VSIR_PILOT_PDF` at the pilot and `tests/paid/test_read_real.py` reads that
  instead, unchanged.

---

## Milestone gate — M5 (`cr1-m5`)

**Demo command (Spec §0):** `VSIR_ALLOW_PAID=1 vsir read --pages … --question …` — **run live
against `gemini-3.8-flash` on 2026-09-10**, output recorded in the U020 entry above. One real
call, 2,858 input / 165 output tokens, six codes transcribed off the raster and all six stamped
`present` against text they are genuinely printed in; a second call over the two scanned sheets
returned `C24` and `1.0` read from the image and stamped `unverifiable`, which is R2 working.

**Acceptance (Spec §13 M5), verified against the implementation by a subagent, ✓/✗ with evidence:**

| # | Clause | | Evidence |
|---|---|---|---|
| 1 | Loop 1 stamps a deliberately misread code `absent` **with** `present_instead` | ✓ | `serve/tools/read.py:161-186` (`_stamp` → `verify_claims`), fold at `core/verify.py:166-172`, disclosure at `core/present_instead.py:60-79`. `tests/unit/test_read_stamps.py:108-118` (`K73`→`["k78"]`); `tests/api/test_read_replay.py:63-77` against the checked-in table (`K152` → `absent`, `["k119","k120"]`) |
| 2 | F19 — same pages + a new question is a cache **miss** | ✓ | `vlm/cache.py:171-184`, call site `read.py:234-236`, miss branch `read.py:239-246`. `tests/api/test_read_cache.py:166-182` (same pages asserted equal, two distinct keys); identical-call half at `:107-115`; `tests/unit/test_read_stamps.py:339-342` |
| 3 | F18 for `read` — a 4-page call is a typed 400 | ✓ | `serve/caps.py:75-79`, reached from `read.py:145` (`precheck`), run **before** the charge at `serve/app.py:944-949`. `tests/api/test_read_caps.py:58-67` (400, bound named, zero model calls) and `:70-80` (quota untouched) |
| 4 | Every code on a text-free page comes back `unverifiable` | ✓ | `core/verify.py:103-109` and `:120-122`, fold `:174-176`. `tests/unit/test_read_stamps.py:121-133` (incl. a code printed elsewhere in the same document); `tests/api/test_read_replay.py:124-137` |
| 5 | Every aggregate row carries `preview.thumb_url` — best-ranked matched page, falling back to page 1, a **reference never bytes** (D12) | ✓ | `serve/tools/skim.py:655-662`, `:775`, `:901`; fallback `:725-750` + `:809-825`. `tests/api/test_skim_aggregates.py:164-177` (preview page == the `best_rank` page, `dpi=72`); `tests/api/test_searchable_ratio.py:124-145` (unranked row falls back to `#p001`) |

**P2, checked separately:** no `skim_*` row can carry image bytes *by type*, not by convention —
`Preview` and `ImageRef` both set `extra="forbid"` and have no bytes field, `FetchImage` is a
different model returned only by `fetch`, and `skim.py` base64-encodes nothing. Asserted at
`tests/unit/test_envelope.py:153-156` and `:166-180`, and over the wire at
`test_skim_aggregates.py:154` and `test_searchable_ratio.py:143`.

**Test layers at the gate:** L0/L1 `1261 passed`; L2/L3 `1365 passed, 13 skipped`; L4
`10 passed, 1 skipped` (gated, real model). No test skipped, xfailed or weakened to pass.

**One finding to carry forward (not an M5 ✗, and not U020's surface).** A blind-spot document
whose page numbering does not start at `page_no: 1` gets **no disclosure row at all** rather than
a row without a preview: `skim.py:811` filters the resolved set to the doc_ids `_first_pages`
found. For the F4 disclosure that is the wrong direction to fail in — the row exists precisely to
be seen — and no test covers it. Every document in the corpora today starts at 1, so it is latent.
Whoever next touches `_blind_spots` should fall back to the document's *lowest* current page
rather than to the literal page 1.

---

### U031 — The typed API surface: eight named routes, the corpus, and MCP resources

**Milestone:** post-plan (§4b) · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

Four things the release served correctly and **described** badly. None of them was a bug a test
could see, because in every case the code was right and the contract was invisible.

**One OpenAPI operation for eight tools.** `POST /tools/{tool_name}` is the right implementation —
one route, one table, one dispatcher — and it published a single operation with an untyped body,
so `/docs` showed one *"tool_name + JSON"* form for eight tools whose parameters have nothing in
common, and a client generated from `/openapi.json` got one `call_tool(name, dict)` with no types
on either side. An integrator had to read our source to learn that `read` takes `question`. Each
tool now has its own path, **generated in a loop from the table** — so a tool cannot get a route
without being in the table or be in the table without getting a route — and `ToolSpec` gained a
`response` column so each route publishes its §7.1 envelope as well as its body.

The load-bearing decision is that a named route **does not validate its own body**. A typed
FastAPI parameter would have been the obvious way to publish the schema, and FastAPI's failure is
a `422` with a JSON pointer where §7.3 promises a code an agent switches on. So the schema goes
out through `openapi_extra` as a `$ref`, `_described()` puts the referenced models in
`components.schemas` from the same table, and `dispatch` stays the only validator on either
transport. `test_tool_routes.py` asserts both halves: byte-identity between a named route and the
generic one, and `invalid_request` — never a `422` — for `includeUnverified`. The generic route
stays mounted beneath the eight, unpublished, still answering an unknown name with the typed `404`
that lists what *is* served.

**Per-field notes that reached Sphinx and not the wire.** The eight input schemas moved to
`serve/inputs.py`, and every `#:` comment on them became a `Field(description=...)`. That is the
real content of the change: `model_json_schema()` is what `mcp/server.py` publishes as each tool's
`input_schema`, so the notes explaining that `image` is base64, that `exclude` is pages already
rejected, that `inline=false` returns a reference rather than bytes — the things an agent needs in
order to choose a move — were legible to a developer reading our source and invisible to the model
calling the tool. There is **not one Pydantic constraint** in that module, deliberately: a
`Field(le=25)` on `limit` would turn `skim_limit_exceeded` into a generic validation error, and
`caps.py` is where a bound lives precisely so it can carry its own code.

**No typed error anywhere.** `ToolError.to_payload()` built a dict, and every `responses=` table
carried a `description` with no `model` — so a document whose whole argument is *"switch on the
code"* declared no shape for the thing carrying the code. `serve/errors.py` is now that shape, and
it is the one model in the service with `extra="allow"`, because a refusal's details name the
bound it hit (`limit`/`requested` on a cap, `retryable` on an outage) and those keys differ per
code. `ControlError` became a subclass of it rather than a second declaration of `{error, detail}`.

**A corpus you could search and not see.** `POST /documents` put documents in and nothing told you
what went in, so an operator could ingest a corpus and had no way to look at it. `serve/manage.py`
plus `GET /documents`, `GET /documents/{doc_id}`, `GET /documents/{doc_id}/pages` and `GET /runs` —
all queries over the two collections ingestion already writes (register **E1**), computing nothing
ingestion did not record and storing nothing of their own, `exact=True` throughout because an
estimated page count short by two is indistinguishable from an ingest that dropped two pages.
They show rather than tidy away: a **superseded revision is listed** with `is_current: false`
because §6.7 keeps it (F9) and its pages are still fetchable; `searchable_ratio` is on every row
and is asserted to equal what `skim_documents` reports for the same document; an unknown `doc_id`
is a typed `404` and never a zero-page row. **All read-only** — retirement is §6.7's and runs
inside a publish where the run record is its evidence, and the suite asserts the collection count
is unchanged after every route is called and that `DELETE` is a `405`.

**There is no chunk here to manage, and that is the design.** A *window* is a page range that
stitching deletes again and it never becomes a retrieval boundary (`ingest/window.py`); window
(attention), section (semantics) and page (index) stay separate throughout. So the units are
documents, revisions, pages and runs, and the addressable one is the **page** under §5.2's
`page_id` — asserted by taking a `page_id` off a listing and handing it to `verify`.

**The corpus on MCP is a resource, not a ninth tool.** §7.5 fixes the surface at *the same eight
tools*, and that is a statement about what an agent chooses between: the eight are **moves**, and
an agent picking among nine where one is "list the corpus" is choosing between a search and a
filing cabinet. `resources/list` serves one concrete `vsir://corpus` and declares
`vsir://documents/{doc_id}` and `vsir://documents/{doc_id}/pages` as **templates**, so it stays
O(1) and a thousand-binder corpus does not put a thousand rows in a client's picker. They resolve
through `serve/manage.py`, so reading `vsir://corpus` is byte-identical to `GET /documents` and the
import-graph rule still holds — no filter, no count, no scroll anywhere in `mcp/server.py`.

**Three defects this surface had before it shipped**, all found reviewing it rather than by a
failing test, and each now carrying its own regression test:

| | Defect | Why it mattered |
|---|---|---|
| 1 | `next_offset` was gated on `last + 1 <= total` — a **count** compared with an **index** | `ingest/export.py` guards against exactly the document those two disagree on: one with a hole in its page numbering, where `total` is smaller than the last `page_no`. Paging ended early and reported a **truncated inventory as a complete one** |
| 2 | With no published revision, `""` was passed as the revision to measure | Filters on `revision == ""`, matches nothing, and reports `searchable_ratio: 0.00` for a document that demonstrably has pages — the one number on the row an operator acts on, inverted, and inverted toward *"this binder is unsearchable"* about one that is merely unpublished |
| 3 | `documents()` facets for ids then reads each one, and propagated a per-row `404` | Two round trips, and a publish or delete can land between them. One document retired while we counted **failed the entire listing** — fourteen documents unreturnable because a fifteenth went away. A row that no longer exists is not a row; the `404` belongs to `GET /documents/{doc_id}`, where the caller named it |

**Tests** — four new files, 54 assertions, and the two full suites green:

```
tests/api/test_tool_routes.py        the eight paths, the schemas, byte-identity, no 422
tests/api/test_corpus_management.py  counts, the superseded revision, the ratio, read-only, x3 defects
tests/api/test_run_history.py        newest-first, `gated` is not `failed`, failed_gates named
tests/api/test_mcp_resources.py      still eight tools, templates, byte-identical to HTTP

bash scripts/test-unit.sh   ->  1321 passed · Layer 0/1 PASSED
bash scripts/test-api.sh    ->  1419 passed, 13 skipped (baseline, pre-defect-fixes)
```

**Invariants / failure rows closed:** none new — this unit changes how the surface is *described*
and what can be *read*, and asserts that neither changed how a call is answered. §7.5's
byte-identity property is extended to cover resources.

---

### U021 — Tri-state triage, the five safeguards, and the `fetch`-vs-`read` route

**Milestone:** M6 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-10

Loop 0, built as a real state machine and proved without a paid call. Three net-new modules under
`backend/vsir/runner/` and one new command: `vsir ask --explain "<question>"` descends
`skim_documents` → `skim_sections` → `skim_pages`, marks every candidate
`relevant | uncertain | irrelevant` from its **row alone**, prints the `exclude` set the next skim
would carry, chooses `fetch` or `read` per candidate, and ends with a spy proving it spent nothing.

**The mark is made from four fields and nothing else** — `summary`, `why`, `grounded_rate`,
`text_trust` — because that is all a triage row carries: a `PageHit` has no `text` field at all
(P2), which the L0 suite asserts against the model rather than against the code that reads it. The
rule ladder is short and every rung leans the same way:

| | condition | mark |
|---|---|---|
| 1 | the query names an identifier **and** `why` contains `lexical` | `relevant`, `exact_hit`, **promoted** — the summary is never read |
| 2 | the summary carries a term of the query | `relevant`, `summary_match` |
| 3 | the text matched and the summary does not show it | `uncertain`, `lexical_unshown` |
| 4 | `text_trust` is `untrusted`/`no_text`, or `grounded_rate < 0.8`, or there is no summary | `uncertain` |
| 5 | a trusted, grounded summary with nothing of the query in it | `irrelevant`, `no_overlap` |

Rows 3 and 4 are the **four ways a summary stops being evidence of absence**, and they are the
whole of the design's asymmetry: every judgement errs toward carrying a candidate forward. A
useless `uncertain` costs a place in a pool that is only drained when the answer was not found; a
wrong `irrelevant` produces an abstention on a corpus that contained the answer. Safeguard 2 is
not in the table because it is not a property of a row — with ≤ 3 candidates the whole set is
lifted to `relevant` afterwards (reason `small_set`), since *"read them all"* is what §8.2 asks
for and a set left half in the pool would still be a filtered small set.

**Demo output** — the plan's demo command, against the published 42-page generated corpus
(`bash scripts/stack.sh up`), boot-check JSON lines elided:

```
$ vsir ask --explain "the carton discharge won't restart after an E-stop reset"

vsir ask --explain — release dev-0
   question  "the carton discharge won't restart after an E-stop reset"
   prompt    runner-v1 · sha256 e1cc7b09255c · 5 safeguard(s) bound · 8 tool(s) offered

01 DESCEND — skim_documents(…, scope={})
   status ok · rows 2 · total 84 · weak true · searched 84 page(s), 4 with no text
   descend into {'doc_id': 'synthetic-3window'} → scope {'doc_id': 'synthetic-3window'}

02 DESCEND — skim_sections(…, scope={'doc_id': 'synthetic-3window'})
   status ok · rows 9 · total 42 · weak true · searched 42 page(s), 2 with no text
   descend into {'section_id': ['synthetic-3window@1.0#s004']} → scope {…, 'section_id': [s004]}

03 DESCEND — skim_pages(…, scope={'doc_id': …, 'section_id': [s004]})
   status ok · rows 5 · total 5 · weak false · searched 5 page(s), 0 with no text

04 TRIAGE — the tri-state marks (§8.2), free and before any spend
   mark       reason           page_id                       why            rank  grounded  trust  matched
   relevant   summary_match    synthetic-3window@1.0#p015    dense,lexical  1     1.00      ok     after,stop
              Page 13 covers emergency stop chain stage 13 … It names K115
   relevant   summary_match    synthetic-3window@1.0#p016    dense,lexical  2     1.00      ok     after,stop
   relevant   summary_match    synthetic-3window@1.0#p014    dense,lexical  3     1.00      ok     after,stop
   relevant   summary_match    synthetic-3window@1.0#p017    dense,lexical  4     1.00      ok     after,stop
   relevant   summary_match    synthetic-3window@1.0#p013    dense,lexical  5     1.00      ok     after,stop

   relevant 5 · uncertain 0 (the fallback pool, retained) · irrelevant 0
   telemetry 5 mark(s) written as evaluation data — no tool call, and the loop reads the marks it
             already holds (§8.2, §11.4)
   PASS  every candidate carries exactly one of relevant | uncertain | irrelevant

05 EXCLUDE — what the next skim is told not to re-offer
   nothing marked irrelevant — there is no exclusion to make

06 ROUTE — §8.1a, the deliberate choice (caller: vision-capable, 5 image slot(s),
         reads_remaining 3)
   synthetic-3window@1.0#p015    fetch   default_fetch
   …                             fetch   default_fetch   (all five)
   plan: fetch over [p015, p016, p014, p017, p013] · spends false

07 MACHINE — the transitions this question is on (§8.1, §8.3)
   descend --candidates--> triage --look_set--> look
   the fallback pool holds 0 candidate(s): —
   PASS  safeguard 1 — on `sufficient: false` the next state is the uncertain pool, not a wider scope
         (look, insufficient) → drain_uncertain; and widening is only reachable from there:
         (drain_uncertain, pool_empty) → widen

08 SPEND — the spy
   PASS  no paid tool was dispatched and the VLM backend was never reached
         dispatched ['skim_documents', 'skim_sections', 'skim_pages'] · paid [] ·
         VLM backend reached 0 time(s) (the release's spending tools: ['read'])
   PASS  the read budget is untouched: every envelope reported the same reads_remaining
         reads_remaining across 3 envelope(s): [46, 46, 46]

ALL ASSERTIONS PASSED
```

Two more paths, same command:

```
# a text-only caller (§8.1a's delegation door) — the route flips and the §7.3 cap splits the set
$ vsir ask --explain --no-vision "…"
   synthetic-3window@1.0#p015    read    caller_not_vision_capable
   synthetic-3window@1.0#p017    — none  deferred_over_cap
   plan: read over [p015, p016, p014] · deferred [p017, p013] · spends true

# an empty triage — §8.1's coverage branch, and it still proves it spent nothing
$ vsir ask --explain "where is K999 wired"
   no candidates to mark · status not_found · searched 84 page(s), 4 with no text layer
   §8.1 branch: empty_no_text → vision_first
   4 image-only page(s) in scope are unexamined: `fetch`/`read` those first.
     "Not in these documents" is forbidden until they are (§8.5)
   the rung offers another move rather than an absence: next.suggest ['lookup']
   08 SPEND … ALL ASSERTIONS PASSED
```

**Invariants / failure rows closed:** none newly, and that is the plan's own answer — I8 is U022's
and M6 owns no F-row. What this unit closes is **R1** and **R6**: R1 by the `uncertain` pool,
*"do not filter a small set"* and `why: lexical` as a floor rather than a hint; R6 by making all
five safeguards binding **in the state machine as well as the prompt**, which is what the
acceptance criteria assert — the tests read `TRANSITIONS`, not the prompt text.

**Tests:** 60 L0 (`test_triage.py` 23, `test_safeguards.py` 17, `test_route.py` 20) · 11 L2
(`test_ask_explain.py`). L0/L1 `1321 passed`; L2/L3 `1430 passed, 13 skipped`. Nothing skipped or
xfailed by this unit, and no test weakened to pass.

**One operational note for whoever runs L2 next.** `docker-compose.test.yml` publishes fixed ports
(6335, 8001) under the default project name, so **two `scripts/test-api.sh` runs on one machine
destroy each other**: the second one's `up` collides on the container name, and the first one's
`down -v` wipes the collections the second is mid-way through. That is what 214 failures and 628
errors of *"Connection refused"* looked like here before it was diagnosed — contention, not a
defect. The clean L2 numbers above were produced on an isolated stack:

```bash
printf 'services:\n  test-qdrant:\n    ports: !override\n      - "6435:6333"\n' \
  '  backend-test:\n    ports: !override\n      - "8101:8000"\n' > /tmp/override.yml
COMPOSE_PROJECT_NAME=vsir-u021 docker compose -f docker-compose.test.yml -f /tmp/override.yml \
  up -d --build --wait test-qdrant backend-test
cd backend && COMPOSE_PROJECT_NAME=vsir-u021 VSIR_TEST_QDRANT_URL=http://localhost:6435 \
  VSIR_TEST_BASE_URL=http://localhost:8101 .venv/bin/python -m pytest --no-cov tests/api/ -q
```

`COMPOSE_PROJECT_NAME` matters for the pytest run too: `test_log_stream.py` shells out to
`docker compose … logs backend-test`, and without it that reads the *other* project's container.

**Notes:**

- **Safeguard 1 is a row of a table, not an ordering between two branches.** `(look,
  insufficient) → drain_uncertain` lives in `runner/triage.py::TRANSITIONS`, and `widen` is
  reachable **only** from `drain_uncertain`. In a hand-written loop the safeguard is one line a
  later edit can reorder with no test noticing; as data, two tests read it directly and there is no
  `(look, insufficient) → widen` edge to add by accident. `next_state` raises `UnknownTransition`
  rather than defaulting — a machine that fell through to *"keep going"* is how a runner drafts
  from pages triage rejected.
- **Safeguard 3 is a floor and an ordering, not a promotion.** §8.2 says a `lexical` hit
  *"outranks"* a dense-only one, so it is the sort key's first tie-break (asserted at **equal
  rank**, which is the AC's shape) and it makes `irrelevant` unreachable for such a row — but it
  does not make it `relevant` on its own, because a prose query matches common words lexically.
  Safeguard 4 is the one that promotes, and it needs **both** halves: an identifier in the query
  *and* `lexical` in `why`.
- **A length floor (≥ 4 characters), not a stopword list.** Summaries are multilingual (§5.2, D5),
  so an English stopword list would strip nothing from a German summary while dropping words from
  the English one — the failure would be silent and one-sided. A floor is language-neutral, and a
  function word that survives it can only carry a page *forward*. It is visible in the demo:
  `matched: after,stop` includes one word that is doing no work, which is the safe direction.
- **Nothing here matches.** The overlap between a query's terms and a summary's tokens decides
  whether to *look*; it never decides whether a code is printed on a page. That question keeps its
  one code path (`exact_filter` over `variants()`, I3) and a mark can never reach a response as a
  hit, a citation or a claim. Documented in the module and re-stated here because a reviewer's
  first reaction to token overlap in this codebase should be suspicion.
- **SA-4, settled in code:** the route default is `fetch`. §8.2's *"`relevant` → `read`"* is the
  generic verb for the look step; §8.1a's bolded *"Default: `fetch`"* governs. `read` is chosen for
  exactly two reasons — the caller cannot see, or its context cannot hold another raster — and if
  delegation is needed with no read budget left there is **no route** (`budget_exhausted`) rather
  than a silent extra call or a raster handed to a caller that cannot read it.
- **The context budget is `image_slots`, not a token estimate.** §8.1a puts a raster at *"~1–2k
  tokens per image"*, and the caller is the only party that knows what that leaves; a token
  estimate here would be this service guessing at a model it does not host. `Caller` is a
  **parameter**, not configuration: whether the caller can see is a property of the caller, so no
  env var was added and §15 Factor VI is unchanged.
- **`runner/route.py` is not in Spec §4.1's `runner/` list** (`loop.py prompt.py triage.py
  answer.py`). It is the plan's deliverable for this unit, §8.1a is a section of its own, and the
  repository already carries modules §4.1 does not enumerate (`core/nearmiss.py`,
  `serve/caps.py`, `ingest/store.py`). Recorded as a deliberate, additive deviation.
- **The runner prompt's text is Python, not a packaged `.md`.** `vlm/prompts/*.md` are inputs to a
  *billed* call, pinned by digest to `VSIR_PROMPT_VERSION`; this one is composed per question from
  the tools a release serves and the budget in force, so it has no fixed bytes to pin — and
  putting it under the same label would re-key every frozen S2 response in the repository whenever
  a safeguard's wording changed. `RUNNER_PROMPT_VERSION = "runner-v1"` moves on its own, and a test
  asserts it is not a key in `PROMPT_DIGESTS`.
- **One definition of the five safeguards, two consumers.** `triage.SAFEGUARDS` is the text; the
  module enforces it and `runner/prompt.py` renders it. A test asserts the prompt carries all five
  *in the machine's own words*, so a safeguard reworded in one place fails rather than drifting.
- **Telemetry is an observation, never a step.** `record(result, sink=None)` writes nothing and
  returns 0, and the look set, the pool and the machine's next state are identical either way —
  the marks are already in the value the caller holds. One `debug` event per mark, because §8.2
  wants `query → page → relevant?` as evaluation data and an aggregate cannot be joined back to
  the page it judged.
- **The demo proves `exclude` by using it.** When triage marks anything `irrelevant`, step 05
  re-runs `skim_pages` with that `exclude` and asserts the rows do not come back; the L2 suite
  does the same over HTTP with an off-topic query, which is also where the *"a page with no text
  layer is never excluded"* row lives.
- **`vsir ask` without `--explain` is a named refusal** (`answer_not_built`, non-zero exit) naming
  U022 and the gate. An **empty** triage is not a refusal: it prints §8.1's coverage branch and
  exits 0, because an absence the corpus genuinely has is a correct answer (§7.1).
- **The L2 suite runs against the U019 multi-document corpus, not `synthetic_3window`.** The
  plan names the 3-window fixture, and it is the wrong corpus for *this* unit: the descent's
  first rung groups **documents** and that fixture is one document, so `skim_documents` would
  have nothing to choose between and the `next.expand` step would be untested. The U019 corpus
  has three manuals plus twelve leaflets, sections to descend into, and pages with no text layer
  — which is also where the *"a scanned page is never excluded"* row gets its evidence. The
  **demo** does run over the 3-window corpus, as published by `scripts/stack.sh up`.
- **What U022 inherits:** `TRANSITIONS` already declares `draft`, `verify`, `answer` and the edges
  §8.1's diagram draws (`verify` on `contradicted` → `triage`, on `cleared` → `answer`), so
  `loop.py` executes a machine it does not also design. Nothing in this unit drafts, composes or
  renders prose, and `answer.py` does not exist yet.

---

### U022 — The loop, the six correction loops, the answer gate, and `POST /ask`

**Milestone:** M6 · **Spend:** paid (read) · **Status:** `[x]` Complete · **Completed:** 2026-09-11

The loop closes and the product has an answer surface. Two net-new modules —
`backend/vsir/runner/loop.py` (§8.1's machine, executed, and §8.3's six correction loops) and
`backend/vsir/runner/answer.py` (§8.4's server-side gate and §8.5's constrained wording) — plus
`POST /ask`, the only route in this release that may return prose, and `vsir ask` without
`--explain`.

**The machine is executed, not re-designed.** `runner/triage.py::TRANSITIONS` (U021) already
declared every state and edge; `loop.py` is one method per state, each returning one of §8.1's
signals, with the successor coming from `next_state()` — which **raises** on a pair it has no edge
for. So safeguard 1 is not a line of code a later edit could reorder: there is no
`(LOOK, INSUFFICIENT) → WIDEN` transition to reach, and widening is only reachable through
`DRAIN_UNCERTAIN`.

**The gate, in the three outcomes §8.4 names, per `(claim, page)`, unconditionally:**

| verdict | what happens | badge |
|---|---|---|
| `present` | renders | `verified` |
| `unverifiable` | renders | *read from image, not text-verified* |
| `absent` | **the whole draft is rejected** — not the code, the draft | — |

Four decisions in it are worth reading before changing anything:

- **One `verify` call per `(claim, page)` pair, never one over the set.** §8.4's pseudocode is
  literal here, so the call log answers *"was this code checked against the page it is cited
  on?"* and not *"was it checked somewhere?"* — which is the question that lets a code from the
  facing sheet through. The log ships **in the response** as `checks`, so a caller can hold us to
  I8 without reading the prose.
- **A rejection never echoes the code it rejected.** `Rejection` has no field for it: the page and
  `present_instead` are enough to act on, and a body saying *"K152 is not printed on p019"* puts
  the misread code in front of the reader in the one place they are reading for an answer. The
  `(claim, page)` row survives in `checks` with its claim redacted, so the call stays auditable.
- **The claims are the union of what `read` declared and what its sentence contains.** Gating the
  model's `codes` list alone is I8 with a hole in it — a code that reached the prose and not the
  list would render unchecked. One narrowing: a token of digits alone (*"Category 3"*,
  *"stage 17"*) is not collected, because it is `present` on essentially any page of a technical
  document and would put `3 — verified` beside a real part number. A **declared** code is checked
  exactly as the model spelled it.
- **A check that could not run is not a verdict** (`GateUnavailable`). Read as `absent` it would
  reject good drafts during an outage; read as `unverifiable` it would badge an unchecked code as
  *read from image* and render it. So the loop ends as the tool's own refusal — §7.1's *"`error`
  means retry or report, and never abstain"* applied at the last possible moment.

**Where the answer comes from, and why `/ask`'s route is always `read`.** §8.1a's default is
`fetch` *"when the runner is itself a vision-capable model"* — and this runner is Python holding an
envelope, so the default's own condition is false and `route.decide()` reports
`caller_not_vision_capable`. The `fetch` route is not dead: a vision-capable caller takes it in
**its own** context and posts the draft back as `{"draft": {...}}`, where the identical gate runs
on it for free (`loop.gate_submitted`). That is what makes §8.4's *unconditional* mean something
rather than being a claim about a branch nothing takes — Loop 1's automatic stamp lives inside
`read`, so on the `fetch` route nothing checked those codes at all.

**Demo output** — the plan's demo command is the pilot question (`TC1E-SF`, **OQ-1 still open**),
so this is §17's documented fallback: the generated 42-page corpus, replayed, with the question
the frozen `read` was recorded for. Boot-check JSON elided.

```
$ vsir ask "why won't the guard door interlock release when K119 is monitored"

vsir ask — release dev-0
   question  "why won't the guard door interlock release when K119 is monitored"
   prompt    runner-v1 · sha256 e1cc7b09255c · 5 safeguard(s) bound · 8 tool(s) offered

01 THE LOOP — §8.1, through the release's own dispatcher ─────────────────────
    1  descend         lookup          --candidates-->
       handle 'K119' → status ok · 1 page(s) print it · total 1
    2  triage          triage          --look_set-->
       1 candidate(s) → relevant 1 · uncertain 0 (the pool, retained) · irrelevant 0 · safeguard 2: ≤3 candidates, none filtered
    3  look            route
       read over ['synthetic-3window@1.0#p019'] · caller_not_vision_capable
    4$ look            read            --sufficient-->
       1 page(s) at the pinned dpi · sufficient true · 3 code(s) stamped · flags [] · 0 page(s) image-only
    5  draft           draft           --candidates-->
       218 character(s) from 1 page(s) · 3 claim(s) to check (3 declared by `read`)
    6  verify          gate            --cleared-->
       3 (claim, page) check(s) · rendered 3 · rejected 0 · badges ['verified']

   tools called: ['lookup', 'read', 'verify', 'verify', 'verify']
   correction loops fired: ['loop2_verify'] (of six)

   ANSWER — route read · 1 paid read(s) · reads_remaining 49
   citing synthetic-3window@1.0#p019

   The guard door interlock stage releases only once B219 has closed and K119 is monitored on the
   safe input channel SI4. The stop category is verified at commissioning and after every
   replacement of that monitored relay.

   code                badge                                 page
   B219                verified                              synthetic-3window@1.0#p019
   K119                verified                              synthetic-3window@1.0#p019
   SI4                 verified                              synthetic-3window@1.0#p019

02 THE GATE — every rendered code, checked against the page it is cited on (I8)
   PASS  every code in the answer has a (claim, page) verification behind it
         3 rendered · 3 check(s) made · missing —
   PASS  no code the gate rejected appears anywhere in the output
   PASS  the read budget was respected
         1 read(s) against a ceiling of 3 (VSIR_READS_PER_QUESTION)

ALL ASSERTIONS PASSED
```

**The failure branch, same corpus, same instance** — and it is the more important of the two,
because it is I8 catching a real misread rather than clearing three good ones:

```
$ vsir ask "which contactor does the interlock relay K120 switch"

    4$ look            read            --sufficient-->
       1 page(s) at the pinned dpi · sufficient true · 3 code(s) stamped · flags ['unverified_codes']
    6  verify          gate
       5 (claim, page) check(s) · rendered 4 · rejected 1 · badges ['verified']
    7  verify          gate            --contradicted-->
       draft rejected — 1 claim(s) the check would not clear. Excluding the page(s) they were
       cited on and trying a different page; not one word of that draft renders
   …
   15  vision_first    vision          --candidates-->
       escalating to vision on ['…#p002', '…#p001'] — the pages the text search could not read
   17$ look            read            --insufficient-->
       2 page(s) at the pinned dpi · sufficient false · 0 code(s) stamped · flags ['no_text_layer']
   20  descend         skim_pages      --empty_searchable-->
       zoom 0 · scope {} → status not_found · 0 row(s) · total 0

   correction loops fired: ['loop1_read_stamp', 'loop2_verify', 'loop4_different_page',
                            'loop3_soft_rejection', 'loop5_vision_escalation']

   ABSTAINED — rejected · 2 paid read(s) · reads_remaining 47

   A draft answer was written from synthetic-3window and rejected: the codes it cited are not
   printed on the pages it cited them from. 42 page(s) searched across 1 document(s). All 2
   image-only page(s) in scope were examined, so this is not in these documents.

   searched ['synthetic-3window'] · 42 page(s) · pages_no_text 2 · read 2 · unexamined 0
   1 claim(s) were rejected by the gate — the codes they named are not printed on the pages they
   were cited from, and neither the draft nor the codes appear above (§8.4)

   PASS  the abstention names the coverage numbers and does not claim the corpus is exhausted
         while image-only pages are unread (§8.5)
         unexamined 0 · forbidden wording present: True
```

**Read that last line the right way round.** The sentence *"not in these documents"* is present and
that is correct here: the loop rejected the draft, widened twice, and then **went and looked at
both image-only pages** before concluding anything (Loop 5, two paid reads of the three it is
allowed). §8.5 forbids the sentence while `pages_no_text_read < scope_stats.pages_no_text`; here
they are equal, so the corpus really was searched. Ask the same question with those two pages in
`exclude` and the same code composes the other wording instead — *"2 image-only page(s) in
synthetic-3window were not examined"* — which is what `test_ask_replay.py`'s pair of abstention
rows asserts.

The model really did emit `K152` (a plausible misread of `K120`, and the ordinary way a vision
model gets a character on a schematic wrong); `read` stamped it `absent` inside the tool (Loop 1),
the gate rejected the draft that carried it (Loop 4), and the two codes the gate *had* cleared are
not rendered either — the draft dies whole.

**The milestone gate found one more, and it was the blocking kind.** M6's acceptance was
verified against the implementation by a subagent before this unit was marked complete (plan §5),
and it reported a hole in I8 on the one route the gate exists for. On the submitted-draft path
`POST /ask` built the `Draft` from the caller's `claims` list **as given**, so a draft whose prose
named a code its own claim list omitted was rendered with **zero** `verify` calls — on precisely
the `fetch` route where §8.1a says Loop 1's automatic stamp never ran. The union of declared codes
and prose codes (`claims_from`) was being applied after a `read` and nowhere else. It is now
applied in `gate_submitted`, so both routes derive the claim set from the draft rather than
accepting it, and `test_ask_replay.py::test_a_submitted_draft_is_gated_on_the_codes_in_its_prose…`
submits a draft declaring **no** claims at all and asserts the gate still finds and rejects the
misread. *A caller declaring its own claim set would have made the gate's coverage the caller's
choice.*

Three smaller findings from the same review, all fixed:

- **§8.1's second empty branch was reachable from a descent and not from the end of the ladder.**
  A question whose widest descent returned rows that triage rejected wholesale abstained while an
  image-only page sat unexamined — honest in its wording (the abstention named the gap) and a
  missed correction all the same. One edge added to §8.2's table,
  `(WIDEN, EMPTY_NO_TEXT) → VISION_FIRST`, fires it once from the ladder's end; the demo's failure
  branch now reads both scanned sheets before it concludes anything, which is why it is allowed to
  say *"not in these documents"* at all.
- **An abstention over a coverage that counted nothing claimed completeness.** §8.5's rule is an
  inequality, and `0 < 0` is false, so a scope that searched no page passed it while asserting the
  strongest thing this surface can say. It now says what is true — *"No page was searched, so
  nothing follows about the corpus"*.
- **A `500` on the `/ask` path reported `reads_remaining: 0`**, which is a plausible-looking lie
  about the caller's quota on the one path where the loop did not get far enough to read it. It
  asks the ledger, and omits the field if that fails too.

Two of the review's ⚠ rows are **deliberate readings** rather than defects, and are recorded here
so the next reader does not re-litigate them:

- **`reads_remaining` is the per-caller quota of §7.3, not the per-question remainder.** §8.4 says
  `VSIR_READS_PER_QUESTION` is *"reported as `reads_remaining`"* and §7.1 says the field is the
  caller's quota; one name for one thing wins (the field means the same thing on all nine
  surfaces), and the `429` body carries `reads` and `reads_per_question` beside it so the refusal
  explains exactly which ceiling was hit.
- **`reads_remaining` is absent from the `400`/`401` bodies.** A malformed request and a missing
  credential are refused before the loop exists, and reading a budget for them would mean a store
  call on an unauthenticated request. Every response the *loop* produces carries it.

**One defect found by running it, before any test could.** The first implementation widened by
dropping a key out of the scope dict, and the next descent asked the section rung for the same
best row and put it straight back: a machine that narrowed exactly as fast as it widened, which
`LoopBounded` caught after 32 moves on the first off-topic question. Widening is now a **zoom
level** — both aggregate rungs, then the binder alone, then the caller's scope searched flat —
and the caller's own scope is never widened away, because the caller asked for it (F8, C11).
Three descents is the whole ladder, so termination is structural rather than hoped for.

**Test evidence**

| Layer | Command | Result |
|---|---|---|
| L0/L1 | `bash scripts/test-unit.sh` | **1365 passed** (+44: `test_answer_gate.py` 15, `test_abstention_wording.py` 18, and the conformance greps still green) |
| L2/L3 | `bash scripts/test-api.sh -k "ask_replay or correction_loops or ask_near_miss"` | **36 passed** — 22 + 10 + 4 |
| L2/L3 | `bash scripts/test-api.sh` (whole suite) | **1503 passed, 13 skipped** |
| L4 | `VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh -k ask_real` | written, **skipped without the opt-in** (module-level `pytest.skip`, §12.2) |

The L2 suites in detail, because what they assert is the deliverable:

- **`test_ask_replay.py`** — the worked trace in **exactly one paid read**, cross-checked against
  the audit ledger's own `read` line; the trace's move order (`draft` before `verify`); the
  `unverifiable` badge on a page with no text layer; a rejected draft rendering nothing and
  leaking no code; the same claim gated identically on both routes; `429 budget_exhausted` at
  `VSIR_READS_PER_QUESTION=1` **with the control that the same question answers at 3**; a mid-loop
  store outage as `503 qdrant_unavailable` and never as an abstention; and
  **`/ask` is the only route that may return prose**, asserted by resolving every operation's
  published 200 schema and finding `Answer` in exactly one.
- **`test_correction_loops.py`** — six independently named tests, one per loop of §8.3, each
  firing from a crafted corpus state and each asserted to terminate well inside `MAX_MOVES`. Loop
  3's *"pool before widening"* is asserted **on the call order**: the drain produced the second
  look and no widening happened at all, because the pool answered.
- **`test_ask_near_miss.py`** — all 100 `near_misses(n=100)` asked as questions: none answered,
  none cited, and none disclosed as its own `present_instead` (F16). Two controls keep the row
  from being green by paralysis — the real question still answers, and the one fake that a `read`
  really did emit is stopped by the gate rather than by the fixture.

**Fixture additions** (`vsir.eval.synthetic_pdf.READ_CASES`, regenerated with
`python -m vsir.eval.synthetic_pdf`; the PDF's bytes and every pre-existing key are unchanged and
`expected.json`'s diff is purely additive): seven frozen `read` responses for page sets the **loop
chooses on its own** —

| case | pages | why the loop asks for exactly these |
|---|---|---|
| `ask_answer` | 19 | `K119` is printed there and nowhere else: the worked trace, one read |
| `ask_insufficient` | 3, 7, 11 | `SI4`'s first three pages, which do not answer — Loop 3's trigger |
| `ask_pool` | 15, 19, 23 | the three the read cap deferred, drained **before** widening |
| `ask_widened` | 2 | the only candidate left after two widenings: a page with no text layer |
| `ask_widened_cover` | 1 | the last unexamined image-only page, looked at before concluding |
| `ask_rejected` | 20 | a sufficient read naming `K152`, which the gate rejects (I8) |
| `ask_vision` | 2, 1 | Loop 5's escalation, in the dense order the blind-spot skim returns |

Each question names a printed code, so the handle branch settles the page set on the **exact
surface** rather than on a dense ranking — which is the only reason a whole-loop test can be free
and reproducible. Reword one and replay is a typed `fixture_miss`, which is D10 working. The two
image-only cases are the ones worth reading: they are what makes the abstention able to say the
corpus was *searched*.

**Invariants / failure rows closed:** **I8** — the server-side answer gate, per `(claim, page)`,
on both routes, asserted by
`test_a_draft_carrying_an_unverified_code_is_rejected_and_not_rendered` and
`test_the_gate_runs_on_the_fetch_route_exactly_as_it_does_on_the_read_route`. M6 owns no failure
row (§10's *"Closed at"* column); it owns the invariant that makes every earlier guard reach the
answer.

**Notes and deviations**

- **The demo question is not the plan's.** OQ-1 is still open, so `TC1E-SF` and *"the carton
  discharge won't restart after an E-stop reset"* have no corpus behind them. §17's fallback is
  the generated corpus, and on it the question has to name a code the corpus prints — otherwise
  the page set comes from a dense ranking and no frozen `read` can be keyed to it. The plan's
  question runs unchanged the day the pilot PDF lands, with a fixture case recorded from that
  ingest.
- **`POST /ask` accepts a `draft`, which the plan does not mention.** It is the shipped form of
  §8.1a's `fetch` route: without it, the *"the agent looks"* half of the spec has no way to reach
  the gate, and an agent that looked at a raster itself would have to render its own codes with
  nothing checking them — the exact failure §8.4 is server-side to prevent. It searches nothing
  and spends nothing.
- **The eight MCP tools are still eight** (§7.5). `ask` is deliberately **not** an MCP tool: an
  MCP client *is* the agent, so it drives the ladder with the system prompt and brings its draft
  back through `POST /ask` to be gated.
- **`vsir ask --explain` is unchanged** and still spends nothing; the answer path is the same
  command without the flag.
- **§11.2's *"zoom-and-re-read"* is a `fetch`-route affordance, and the loop does not have it.**
  `read` renders one pinned dpi and has no `region` (§7.2.6), so nothing the server-side loop can
  do amounts to a zoom. What it does instead is exactly §8.4's pseudocode: a code on a page whose
  `text_trust` is not `ok` comes back `unverifiable` and renders **with the badge**, which is the
  clause §11.2's own row ends on. A caller that wants the zoom takes the `fetch` route, crops at
  300/400, and posts the draft back to be gated.
- **Follow-up (not blocking):** a refusal body carries `reads_remaining` and the typed error but
  **not** the trace, so a caller that hits a mid-loop outage cannot see how far the loop got. The
  moves are on the event stream (§11.4) and the console will read them from there; putting them
  in the refusal body would widen `ErrorResponse` for every surface, so it is a deliberate
  omission rather than an oversight.

---

## Milestone gate — M6 (`cr1-m6`)

**Demo command (Spec §0):** `VSIR_ALLOW_PAID=1 vsir ask "<question>"` — run twice, on the answer
branch and the failure branch, output recorded in the U022 entry above. **The question is not the
spec's**: `TC1E-SF` and *"the carton discharge won't restart after an E-stop reset"* have no corpus
behind them while OQ-1 is open, so this is §17's documented fallback — the generated 42-page
corpus, replayed, asked a question that names a code the corpus prints. Nothing else about the
demo is substituted: the loop, the paid step, the gate and the abstention are the shipped ones,
and the run spends nothing because `read` is served from a response frozen under exactly the key
the call was made with (D10).

**Acceptance (Spec §13 M6), verified against the implementation by a subagent, ✓/✗ with evidence:**

| # | Clause | | Evidence |
|---|---|---|---|
| 1 | On the worked trace the loop completes in **exactly one paid `read`** | ✓ | Budget decremented in one place (`runner/loop.py::look`), ceiling at `budget_left`. Asserted two independent ways: `payload["reads"] == 1` **and** one `spends` move in the trace (`tests/api/test_ask_replay.py::test_the_worked_trace_answers_in_exactly_one_paid_read`), cross-checked against §7.4's audit ledger (`::test_the_read_call_count_is_one_in_the_audit_log_too`) |
| 2 | …and cites `p001–p002` | ⚠ **substituted** | The worked trace runs on `synthetic_3window` and cites `p019`: `K119` is printed there and nowhere else, which is what makes the page set a function of the corpus rather than of a ranking. The literal `p001–p002` belongs to `TC1E-SF` and lands with OQ-1 (plan §"Risk (OQ-1/OQ-2)") |
| 3 | `VSIR_READS_PER_QUESTION` (default 3) is the hard ceiling for the general case | ✓ | `config.py` default `"3"`, `minimum=1`; `loop.py::budget_left` takes the **lower** of it and the caller's quota, so no route exists past it and the refusal is `429 budget_exhausted` — never a silent extra call. `test_ask_replay.py::test_the_per_question_ceiling_refuses_rather_than_answering_from_pages_that_did_not_answer`, with the control that the same question answers at 3 |
| 4 | The failure branch abstains **with coverage numbers** and never says *"not in these documents"* while unread image-only pages remain | ✓ | `runner/answer.py::abstention` composes three clauses and calls `assert_wording` on **every** path; the guard raises rather than asserting, so `python -O` cannot strip it. Both directions asserted over HTTP: `test_the_abstention_names_the_coverage_numbers` (both blind pages read → the sentence is available and earned) and `test_the_abstention_cannot_claim_the_corpus_is_exhausted_while_a_page_is_unexamined` (the same question with those pages excluded → the sentence is absent) |
| 5 | A draft containing an unverified code is **rejected, not rendered** (I8) | ✓ *after a fix* | `answer.py::gate` rejects and `Gated.answer()` raises rather than rendering; one rejection discards the whole draft. **The gate review found this held only for declared codes on the submitted-draft route** — see the U022 entry: the claim set is now re-derived from the draft on both routes, and `test_a_submitted_draft_is_gated_on_the_codes_in_its_prose_not_on_the_ones_it_declared` submits a draft with an empty claim list and asserts the misread is still found and refused |

**The seven invariants and refusals checked separately, all ✓:** I8 is per `(claim, page)` with one
`verify` call per pair and no flag, no config key and no parameter that could bypass it; an error
is never an abstention (`abstained` requires `refusal is None`, and the loop breaks on any
refusal); §7.6's four refusals hold (no `score` in any response model, no tool picks the document,
only the runner composes and only behind the gate, no fuzzy matching anywhere in `runner/`); the
suite's own AST scan finds **no** module-level mutable state in `runner/`, no local-disk state, no
`if TESTING`, no test-only import and no session store — `Loop` is constructed at exactly two
sites, both per call; and **the MCP surface is still exactly the eight tools of §7.2** — the runner
is a *caller* of them and not a ninth, asserted as a set equality rather than a count.

**Three further findings from the review, fixed in this unit** (the missing
`(WIDEN, EMPTY_NO_TEXT) → VISION_FIRST` edge, an abstention claiming completeness over a coverage
that counted nothing, and a `500` reporting `reads_remaining: 0`) and **two deliberate readings
recorded rather than changed** (`reads_remaining` is §7.3's per-caller quota on all nine surfaces;
it is absent from the `400`/`401` bodies, which are refused before the loop exists). All five are
written up in the U022 entry.

---

### U032 — The live path: the schema `title` bug, the client race, and the retry ladder

**Milestone:** post-plan (§4b) · **Spend:** paid (four ingests of one 56-page manual) · **Status:** `[x]` Complete · **Completed:** 2026-09-11

Three defects, none of which a test could have found, all of which one real document found in an
hour. They belong together because they share a cause: **the stub never builds a request, never
opens a client and never crosses a network**, so everything between our types and the provider was
unverified until a paid run went through it. That is U028's lesson, and this is its second half.

**1. A field called `title` was deleted from every schema we send.** `response_schema()` strips
`UNSUPPORTED_SCHEMA_KEYS` — which contains `title`, because a schema's own `title` keyword is a
`400` from the API — and it stripped it at **every level of the tree, including inside
`properties`**, where the keys are the model's own field names. `SectionRef.title` is named
`title`. So the model was asked for

```json
"sections": {"items": {"properties": {"is_start": {"type": "boolean"}}}}
```

a list of objects with nowhere to put a section's name, and it correctly returned `[]` — on every
page of every live document. Two ingests came back with sections on **0 of 58** pages while the
frozen fixtures, recorded before, had them on 42/42. The whole of `next.expand` (§7.2.1 P4) is a
`section_id` scope, so **the expand affordance was inert on everything really ingested**, and
`skim_sections` had nothing to group. A keyword and a field name are different namespaces;
`resolve()` now walks them separately.

**The test required the bug.** `test_the_schema_that_is_sent_carries_nothing_the_api_has_no_field_for`
walked every key at every depth and asserted none was a keyword — which is precisely the demand
that `title` be stripped from `properties`. It was not blind to the defect, it enforced it.
Corrected in place, so its provenance survives, and it now asserts both halves: keywords gone,
field names kept.

**2. The SDK client was raced by the pool that uses it.** `GeminiEmbedder._client()` was a plain
`if self._sdk_client is None`, and `embed_pages` fans batches over a `ThreadPoolExecutor` of
:data:`EMBED_CONCURRENCY` = 8. A 56-page document is 7 batches, so seven threads reached that check
together, all saw `None`, all built a client, and the last assignment orphaned the rest — collected,
`httpx` transport closed underneath the threads still using it:

```
embed_pages: RuntimeError: Cannot send a request, as the client has been closed.
```

Structurally invisible below `EMBED_BATCH_SIZE`: one batch is one worker, so the two-page datasheet
that was ingested successfully an hour earlier could not have shown it. Double-checked lock, and the
same fix on `GeminiBackend._client`, which is the identical shape reached by the identical window
fan-out and had simply not met a document with enough windows yet.

**The first regression test for it was worthless and passed either way** — a trivial `FakeClient.__init__`
makes check-and-assign effectively atomic under the GIL. Only reverting the fix and re-running
exposed that. With 20 ms in the constructor it fails honestly: **8 clients without the lock, 1 with.**

**3. A connection that never answered was not worth retrying.** `RETRYABLE` was ported from `impl`
as HTTP **statuses** — replies the server sent. An `httpx` transport error carries none of those
words, so it raised at `attempts: 1`. Three live runs died that way in an hour:
`RemoteProtocolError: Server disconnected` on an S2 window, then twice
`ConnectError: [Errno -2] Name or service not known`. The second shape is the expensive one — S2
was already paid for and the run threw that spend away over a DNS blip a single retry would have
ridden out. The transport classes are now in the list, with a test on **both** sides so widening it
cannot start retrying a genuine rejection.

**Prompt s2-v2.** Released while chasing (1) on a hypothesis that turned out to be wrong: the
s2-v1 text did contain a real contradiction — *"list a section on every page it merely continues
on"* against *"do not add a section that is not on the page in front of you"* — and the
clarification stands on its own, but it was **not** the cause and it did not fix anything on its
own. Recorded here rather than quietly, because a version bump attributed to the wrong defect is
how the next person concludes the prompt is the lever when it is not.

The frozen fixtures are untouched and still key on `s2-v1`: :func:`prompt` is reached only on the
**live** path, so replay never loads the text and never checks a digest. `docker-compose.yml` now
interpolates `VSIR_PROMPT_VERSION` the way it already interpolated `VSIR_VLM`, and
`scripts/stack.sh up --live` exports the released version — replay keeps the one its fixtures were
frozen under, which is the honest arrangement and is now written down in `.env` beside the variable.

**Verified on the document that exposed all three** — `data/source/SICK-DETECTOR-BOX.pdf`, 56 pages,
ingested live:

| | before | after |
|---|---|---|
| pages carrying a section | 0 / 56 | **53 / 56** |
| distinct sections | 0 | **68** |
| `next.expand` | `{}` | `{"section_id": [...]}` |

And the affordance round-trips, which is the point of it: take `next.expand` off a `skim_pages`
hit, hand it back **verbatim** as the next call's `scope`, and page 40 becomes pages **38–44** —
its whole section, no string assembly. `skim_sections` now returns *"4.4 Response time"* and
*"4.6 Testing plan"* instead of nothing.

**Tests:** `bash scripts/test-unit.sh` → **1424 passed**; `bash scripts/test-api.sh` → **1513
passed, 13 skipped**.

**Invariants / failure rows closed:** none new. What changed is that three things the contracts
already promised are now true on the paid path as well as the replayed one.

**Notes**

- **§4c P2 is not open.** `serve/tools/read.py` builds a `ControlPlaneStore` and both `get`s and
  `put`s on it, and the live control plane holds 11 `vlm_cache` entries under namespace `read`.
  The re-bill the plan describes does not happen. What does happen, and is by design, is that the
  per-caller quota is charged **before** the call (`app.py`, *"Before the charge, never after"*),
  so a cache hit still costs a quota unit while costing no money — worth a decision, not a defect.
- **The remaining live-path unknown is `/ask`'s budget.** A question against this manual spent its
  three-read per-question ceiling without answering. That is the runner's, and it is U022's.

---

### U023 — The operator console: viewer, agent panel, trust badges

**Milestone:** M7 · **Spend:** none (fixture-backed replay) · **Status:** `[x]` Complete ·
**Completed:** 2026-09-11

The console is the first thing in this project a person looks at rather than reads, and its job is
narrow: make the loop legible without becoming a second place where the contract is declared. Two
zones. **Left** is the zoom ladder — `corpus → binder → chapter → page`, then a normalised crop at
escalated dpi, which §7.3 makes the *same* gesture as escalating rather than a second control.
**Right** is the agent — collapsible moves, the tri-state triage table, the badged draft, and the
gate's own call log.

**The backend half shipped with it**, because plan §4c **P7** found U023's triage requirement
unsatisfiable by a frontend-only change: before this unit the only triage a caller could see was
one prose sentence inside a trace `Move.detail`, and the `exclude` set's page ids were not in the
response body at all. A console that regexed that sentence would be a second declaration of §8.2's
contract in a language that cannot fail a test when the sentence is reworded. So `Outcome` now
carries a typed `TriageTable` / `TriageRow` and `AskResponse` an additive `triage` field — no new
tool, no second dispatcher, no change to any existing field, and no `score` (§7.6).

**Demo output** — the plan's demo command is
`VSIR_VLM=stub VSIR_FIXTURE=… vsir serve & npm --prefix frontend run dev`. Port 8000 was occupied
by an unrelated process on this machine, so the dev server was pointed at the replay-mode stack on
8055 instead — `VITE_API_URL=http://localhost:8055 npm --prefix frontend run dev`. That is the
same arrangement, and it is the one §15 Factor III makes configuration rather than a literal.

Everything below went **through the console's own origin on `:5173`**, i.e. through the Vite proxy
the app actually uses, not directly to the API:

```
$ curl -s http://localhost:5173/health                     # same-origin, no CORS boundary
{"status":"ok","release_id":"dev","version":"0.1.0"}

$ POST /tools/skim_documents  {"query":"pressure sensor"}  # the binder rung
status: ok | hits: 3
  SICK-DETECTOR-BOX   matched=47 ratio=1.00 thumb=/pages/SICK-DETECTOR-BOX@1.0%23p024/image?dpi=72
  BES0068-LIVE        matched=2  ratio=1.00 thumb=/pages/BES0068-LIVE@1.0%23p002/image?dpi=72
  BES0068-Datasheet   matched=2  ratio=1.00 thumb=/pages/BES0068-Datasheet@2.0%23p002/image?dpi=72
bytes_b64 anywhere in payload: False

$ GET /pages/SICK-DETECTOR-BOX@1.0%23p024/image?dpi=72     # the card's one extra call
HTTP 200  image/png  70702 bytes   -> PNG image data, 596 x 792, 8-bit/color RGB
  ... the same GET with no bearer token                    -> HTTP 401

$ GET /pages/SICK-DETECTOR-BOX@1.0%23p024/image?dpi=400    # the request the console cannot make
{"error":"dpi_requires_region","detail":"dpi 400 exceeds 220 and requires a region: detail that
 fine is about part of a page, and a full page at this dpi is megapixels of raster",
 "tool":"page_image","requested":400,"region_required_above":220}
```

And one question end to end, replayed, through the same proxy:

```
$ POST /ask {"question":"why won't the guard door interlock release when K119 is monitored",
             "scope":{"doc_id":"synthetic-3window"}}

status: answered | route: read | reads: 1 | remaining: 42 | loops: ['loop2_verify']

--- trace: the collapsible moves the right zone renders ---
  01 descend   lookup                 -> candidates
  02 triage    triage                 -> look_set
  03 look      route                  ->
  04 look      read            SPENDS -> sufficient
  05 draft     draft                  -> candidates
  06 verify    gate                   -> cleared

--- triage: the typed table this unit added (the field was absent before it) ---
  query = "why won't the guard door interlock release when K119 is monitored"   small_set = True
    synthetic-3window@1.0#p019  relevant  exact_hit  rank=1  why=lexical  matched=['k119']
  exclude (0) = []
  exclude == the `irrelevant` ids     : True
  the `uncertain` pool is not excluded: True

--- the badged draft the left zone links to ---
  The guard door interlock stage releases only once B219 has closed and K119 is monitored on the
  safe input channel SI4. The stop category is verified at commissioning and after every
  replacement of that monitored relay.
    B219  present  'verified'  -> synthetic-3window@1.0#p019
    K119  present  'verified'  -> synthetic-3window@1.0#p019
    SI4   present  'verified'  -> synthetic-3window@1.0#p019
  warnings: (none — every rendered code was text-verified)

--- the gate call log ---
    claim='B219'  page=synthetic-3window@1.0#p019  present
    claim='K119'  page=synthetic-3window@1.0#p019  present
    claim='SI4'   page=synthetic-3window@1.0#p019  present

no "score" in body : True
no bytes_b64       : True
```

`npm --prefix frontend run build` → `tsc --noEmit` clean, then `86 modules transformed`,
`dist/assets/index-*.js 285.13 kB │ gzip: 87.36 kB`, built in 317 ms.

**Tests.** `bash scripts/test-unit.sh` → **1413 backend passed**, **158 frontend passed (16
files)**, `tsc --noEmit` clean, **Layer 0/1 PASSED**. `bash scripts/test-api.sh` → **1513 passed,
13 skipped** in 6:27, including `test_ask_triage_table.py`'s six cases: the rows agree with the
counts the trace's own move printed, every row carries the §8.2 rule and the terms it was matched
on, `exclude` is the `irrelevant` ids and never the `uncertain` pool, the page the `read` was spent
on is a `relevant` row, a submitted draft has `null` rather than an empty table, and the table
carries no page text and no image bytes.

**Invariants / failure rows closed:** none — M7 asserts no invariant and closes no failure row
(Spec §9, §10). The console **renders** I8's outcome; it does not enforce it.

**What is where**

| Path | What |
|---|---|
| `frontend/src/api/{types,requests,client}.ts` | the wire, typed; every tool under its U031 route; `inline:false` pinned in one place |
| `frontend/src/lib/badges.ts` | the badge mapping — the file the console exists for |
| `frontend/src/lib/{dpi,ladder,strip,citations,window}.ts` | §7.3's bounds, the ladder, strip rows, the citation target, the windowing maths — all pure |
| `frontend/src/lib/source-scan.ts` | the lexical scanner the §16 conformance test uses |
| `frontend/src/components/Viewer/*` | breadcrumbs, the raster + region zoom, the virtualized strip |
| `frontend/src/components/AgentPanel/*` | moves, the triage table, the badged draft, the abstention |
| `frontend/src/hooks/*` | the raster's object-URL lifetime, the ask mutation, the three rung queries |
| `frontend/src/styles.css` | **the only file allowed to name a colour** |
| `backend/vsir/runner/loop.py` | `TriageRow` / `TriageTable` on `Outcome` (the backend half of P7) |
| `backend/vsir/serve/app.py` | the additive `triage` field on `AskResponse` |
| `backend/tests/unit/test_frontend_client_contract.py` | 33 response models + 8 request bodies, compared field for field |

**Notes**

- **Two defects found by running it, and neither was visible to a green suite.** The first is the
  interesting one. `GET /documents`' row type was declared in `client.ts` instead of `types.ts` —
  *outside* the file the contract test reads — and every field of it was wrong: a `title` and a
  `grounded_rate` the route has never sent, and no `revisions` array, which is the one thing that
  row exists to carry (§6.7 **keeps** superseded revisions rather than deleting them). Nothing
  consumed it yet, so nothing broke. The lesson is structural rather than local: *a type outside
  the checked file is an unchecked type*, so both shapes moved into `types.ts` and the contract
  test's ledger is now exhaustive at 33 models. The second: `tsc --noEmit` had been failing on
  `vite.config.ts` (`Cannot find name 'process'`) since the scaffold landed, and `vitest` was
  exiting 1 with *"No test files found"* — `scripts/test-unit.sh` had been reporting **Layer 0/1
  FAILED** for both. Fixed without adding `@types/node`: one ambient `declare const process` for
  the single global that file touches.

- **The contract test is a substitution for the code generator the plan's risk register asked
  for**, and a deliberate one. A generator copies the service's shape into the client, so it can
  only ever catch a field the service *added*; it is blind to a field the console believes in that
  the service has never sent — which is precisely the defect above. Comparing the two shapes fails
  on either side. The limit is honest: it is a **field-name** comparison, not a type one, because
  `tsc` already holds the frontend to its own declarations.

- **The `any` scan is a lexical scan, not an AST walk.** TypeScript 7 is the native compiler and no
  longer ships the JavaScript `createSourceFile` API; its replacement (`typescript/unstable/ast`)
  is unstable and, at 7.0.2, hangs when driven from Node here. ESLint is not a dependency (§4.2),
  and there is no compiler flag that bans a *written* `any`. So `lib/source-scan.ts` strips
  comments and literals and looks for the keyword in what is left — which is exactly the
  discrimination the rule needs, since half the files in `lib/` discuss "any" in prose. It is
  tested in both directions, because a conformance check that quietly stops finding things is
  worse than none.

- **A raster is fetched, never `<img src>`-ed.** Every route is bearer-authenticated including the
  page images (demonstrated above: `401` without a token), and an `<img>` sends no `Authorization`
  header. The alternative would be a token in the query string, which lands in every access log
  and every referrer. `hooks/useRaster.ts` fetches with the header and mints an object URL; React
  Query holds the `Blob` and the effect owns the `URL`, so neither half outlives the other.

- **`trust` is left `null` on a cited page rather than guessed.** `AskResponse` carries page ids
  and no `text_trust`, and the tempting inference — *"this claim came back `unverifiable`, so the
  page must be a scan"* — is very often true and still an invention: `unverifiable` has three
  causes (§5.7), and the body did not say which. A missing badge says *"not known here"*; a
  guessed one would say *"scan"* about a page that may simply be superseded.

- **The dpi resets when you climb.** `climbTo` clears the crop **and** the escalated dpi along with
  the page they were made on. Carrying them would render the next page's corner at 400 dpi
  successfully — a failure that looks like a success, which is the class this project spends most
  of its effort on. It is the same defect U022 recorded in the runner ("widening by dropping a
  scope key was undone by the next descent") with a mouse attached.

- **Replay is keyed on the question *and* the page set.** Three of the demo questions came back
  `fixture_miss`, which is correct behaviour, not a gap in this unit: `read_key` includes the
  question verbatim and the pages the read was spent on, and the local stack has since been seeded
  with `CELL-B-BINDER` and `SICK-DETECTOR-BOX` alongside `synthetic-3window`, so an unscoped skim
  now ranks pages the fixture was never frozen against. Scoping to `doc_id: synthetic-3window` with
  a frozen question replays. **U024 should scope its Playwright fixtures the same way** rather than
  relying on an unscoped question, or its assertions will drift the next time the demo corpus
  changes.

- **Deferred to U024, correctly:** `frontend/Dockerfile` and the Playwright specs are U024's
  deliverables. `docker-compose.test.yml` already declares `frontend-test` (`5174 → 5173`) behind
  the `e2e` profile, pointing at the Dockerfile U024 writes, so `docker compose up -d` does not
  fail on a build context that does not exist yet.

---

### U024 — The Playwright replay suite, `frontend/Dockerfile`, and `scripts/test-e2e.sh`

**Milestone:** M7 (closes it) · **Spend:** none · **Status:** `[x] Complete` · **Date:** 2026-09-11

The console, driven by a browser, against the same backend image production runs — 22 assertions,
zero model calls, `down -v` at the end whatever happens.

**Demo command and its output**

```
$ bash scripts/test-e2e.sh
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  E2E tests (Playwright — full Docker stack, replayed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Stack (backend 8001 · Qdrant 6335 · console 5174) ────
 Image vsir:test Built · Image vsir-console:test Built
── Collection and corpus (one-off admin, same image) ────
   PASS  42 page(s) queryable after publish, one per PDF page (I1)
  GET /ready → 200
── Console ──────────────────────────────
  GET http://localhost:5174 → 200

── Playwright ───────────────────────────
Running 22 tests using 1 worker
  ✓   1 badges.spec.ts › a code read off an image-only page renders with the *read from image* badge
  ✓   2 badges.spec.ts › a code the page really prints renders as `verified`, and carries no warning
  ✓   3 badges.spec.ts › a code the gate rejected is absent from the rendered answer
  ✓   4 badges.spec.ts › the abstention names the unread image-only pages and will not claim the corpus is exhausted
  ✓   5 badges.spec.ts › an empty rung names which absence it is, never a bare "no results"
  ✓   6 network.spec.ts › the console never reaches a paid endpoint, even across a whole question
  ✓   7 network.spec.ts › nothing the console consumed carried image bytes
  ✓   8 network.spec.ts › a binder card shows its thumbnail from the row, with no extra endpoint call
  ✓   9 network.spec.ts › a raster is fetched with the bearer token, never with a token in the URL
  ✓  10 network.spec.ts › an unauthenticated console says so rather than showing empty panels
  ✓  11 outage.spec.ts  › the store going down mid-session renders a banner, never a blank page
  ✓  12 outage.spec.ts  › liveness stays green while readiness goes red — a restart would not fix the store
  ✓  13 outage.spec.ts  › the store comes back and the console answers again
  ✓  14 outage.spec.ts  › a refusal from a tool reaches the operator as a typed banner
  ✓  15 stack.spec.ts   › declares the three ports §4.2 pins, and not the dev instance's
  ✓  16 stack.spec.ts   › runs tagged images and never `latest`
  ✓  17 stack.spec.ts   › is in replay mode: the stub VLM, a fixture, and no credential
  ✓  18 stack.spec.ts   › serves all eight tools of §7.2 and a corpus to ask about
  ✓  19 worked-trace.spec.ts › answers with a badge on every code, and the gate checked each one
  ✓  20 worked-trace.spec.ts › clicking a cited code takes the viewer to the page it was checked against
  ✓  21 worked-trace.spec.ts › the triage panel renders the typed table, including the excluded set
  ✓  22 worked-trace.spec.ts › the moves are collapsible and the spending one is marked as such

  22 passed (12.0s)

Tearing down test stack (wiping volumes)...
```

Non-zero on failure, proved rather than asserted: `bash scripts/test-e2e.sh --grep "a test name that
does not exist"` → `exit=1`, stack still torn down.

**Invariants / failure rows closed:** none — M7 asserts none. The suite *renders* I8's outcome and
§8.5's constraint; it does not enforce them.

---

#### The blocker this unit hit, and what it cost

**M7's three acceptance assertions were not reachable from the shipped console**, and finding that
out took most of the unit. Written down so nobody re-derives it:

1. **`unverifiable` cannot arise from the question box on this corpus.** A rendered claim is badged
   *read from image* only when the gate's verdict is `unverifiable`, which needs a code cited on a
   page with no text layer. The loop only drafts from a `sufficient: true` read, and the only frozen
   case over the image-only pages (`scanned`) is `sufficient: false` — deliberately, because those
   two sheets do not answer the question. So no sequence of clicks could produce the badge.
2. **`exclude` is what leaves an image-only page unexamined**, and the console never sent one. The
   L2 row that asserts `image_only_unexamined == 2` passes `exclude` explicitly.
3. **The rejected-draft trace is platform-dependent** — see the finding below.

The fix is **§8.1a's `fetch` route, given to the operator**: a *"what do you read on this page?"*
form under the viewer, whose text goes to `POST /ask` as a `draft` and through the identical
server-side gate. That is not a workaround, it is the route the console is the literal client of —
§8.1a's default is *"the calling agent looks at the page"*, and here a person is looking at the
raster on the left of the screen. On an image-only page every code in what they wrote comes back
`unverifiable` and renders with the badge; on a page whose text extracted cleanly the same gesture
comes back `verified`; a code the page does not print rejects the draft **whole**. Three of M7's
badges, one gesture, **zero spend** (`reads: 0` on this route).

Two smaller console additions came with it and are listed in the deliverables below: the page rung
is addressable (`#/page/<page_id>`), so a test — or an operator sharing a link — can land on a
chosen page without repeating the search that found it; and a check row carries `data-page-id`
beside `data-status`, as the triage rows already did.

#### The finding: the stub embedding is platform-dependent, so a replayed *ranking* is not

`read_key` is over the dpi-**220** rasters and the question, and those renders are byte-identical
on macOS and in the Linux container — every frozen `read` is reachable from both. The dpi-**150**
raster that feeds the *embedding* is not: `ingest/embed.py::prepare_image` re-encodes it through
Pillow, whose PNG bytes differ between the macOS wheel and the Linux one, so `image_sha256` differs,
so `Composition.canonical` differs, so the stub vector differs. Measured on the same 42-page corpus,
same `doc_id`, same collection contents:

| | host (L2 suite) | container (E2E) |
|---|---|---|
| `embed_key` of page 1 | `5fc4428c6f366cf0` | `bad69e4ab2ed4902` |
| `skim_pages(has_text=False)` | `[p002, p001]` | `[p001, p002]` |

That near-tie is enough to send Loop 5's vision escalation at a page set nobody froze:
`ASK_REJECTED_QUESTION` replays to an abstention on the host and refuses `fixture_miss` in Docker.
**Nothing shipped is wrong** — a `fixture_miss` is D10 working, and no *answer* depends on a dense
ranking (every path to one goes through the exact surface, I2/I3). What is affected is which frozen
response a replayed trace reaches, so:

- the E2E suite depends on **one** frozen page set, in `worked-trace.spec.ts`, and that read is a
  single page;
- everything else spends nothing: the gate-only route reads no page, and the abstention test asks a
  question that is *nothing but a code no page prints*, which reaches Loop 5 with no prose to skim
  and therefore no read at all;
- **a future unit that wants a multi-page replayed trace in CI should freeze both page orders**, or
  make `prepare_image` byte-reproducible across platforms. Recorded here rather than fixed: it is an
  ingest change and U024 owns neither `embed.py` nor the fixture generator.

#### How the assertions stay fixture-independent

M7 requires that they hold on `TC1E-SF` too, so nothing in `e2e/tests/` names a page, a code or a
page number. Every input is derived, by one of three routes, and the invented one is **checked**:

| input | where it comes from |
|---|---|
| the document, an image-only page, a page with clean text | `GET /documents`, `GET /documents/{doc}/pages` (paged at the route's 200-row cap) |
| a code the corpus prints | the page's own `fetch` text, then `verify` until one comes back `present` |
| a code it does not print | invented (`ZQ7731`), then **`lookup` with `include_unverified` until one returns `total: 0`** |
| the worked trace's question | the fixture's own `expected.json`, by the *shape* of the case (`sufficient`, every stamp `present`) rather than by its name |

#### Deliverables

| file | what |
|---|---|
| `frontend/Dockerfile`, `frontend/.dockerignore` | **written** — two stages on a digest-pinned `node:22-bookworm-slim`, `npm ci`, `tsc --noEmit && vite build`, then `vite preview` as `node` on 5173 |
| `docker-compose.test.yml` | **extended** — `test-init` and `test-seed` behind the `e2e` profile, the data mount and document-store volume, `VSIR_FIXTURE` / `VSIR_DOC_STORE`, a node healthcheck for the console, `vsir-console:test` |
| `scripts/test-e2e.sh` | **rewritten** — up → seed → wait for `/ready` → wait for the console → Playwright → `down -v`, with the status captured before teardown |
| `e2e/package.json` | **written** — `@playwright/test` pinned |
| `e2e/playwright.config.ts` | **extended** — no `webServer` (the container is the thing under test), `workers: 1`, CI reporter, pinned viewport |
| `e2e/tests/console.ts` | **written** — the harness: corpus derivation, the fixture's table, `openConsole`, `readOff`, `openCallLog` |
| `e2e/tests/{badges,worked-trace,network,outage,stack}.spec.ts` | **written** — 22 tests |
| `frontend/src/components/Viewer/ReadOff.tsx` + its test | **written** — §8.1a's `fetch` route for the operator |
| `frontend/src/lib/ladder.ts`, `App.tsx`, `Viewer.tsx`, `Moves.tsx`, `api/{requests,client}.ts`, `hooks/useAsk.ts`, `styles.css` | **extended** — the deep link, `draftQuestion`, `draft` on the ask body, `data-page-id` on a check row |
| `backend/tests/unit/test_frontend_client_contract.py` | **extended** — `DraftBody` → `SubmittedDraft` and `ClaimBody` → `answer.Claim` in the ledger |
| `AGENTS.md` | **extended** — the E2E section, the three env vars, and the platform finding |

#### Notes, and things a later unit should not have to rediscover

- **`VSIR_TEST_CONSOLE_PORT` exists because 5174 was taken on the development machine** by an
  unrelated container. 5174 is still §4.2's pin and still the compose default; `stack.spec.ts`
  asserts the *declared default*, and the script threads an override through the mapping, its own
  readiness wait and `PLAYWRIGHT_BASE_URL`. The recorded run above used 5194 for that reason.
- **`@playwright/test` is pinned to `1.62.0`, not the newest at time of writing.** 1.62.0 is the
  version whose Chromium revision (1234) was already in the machine's browser cache; 1.58.2 wanted
  revision 1208 and spent forty minutes not downloading it. Any version works — this one starts.
- **`vite preview` needs `node_modules/.vite-temp` writable**, because Vite bundles a *TypeScript*
  config before loading it. The image creates and chowns that one directory rather than the whole
  of `/app`. Found by running the container, which exited `EACCES` on a path no test could name.
- **The E2E stack seeds through compose services, not an ad-hoc `docker compose run`.** The first
  attempt did both — `frontend-test` depends on `test-seed: service_completed_successfully`, so
  compose ran the declared seed as well and the corpus went into the index twice under two doc ids.
- **`/tools/__list__` answers `404`, and that is the contract.** The body carries `available`,
  because *"a tool that is not here is absent, not empty"*. A `200` there would mean the release had
  grown a `__list__` tool.
- **A badge inside a closed `<details>` is in the DOM and not on the screen.** The gate's call log
  is collapsed by default and rightly so; `openCallLog` opens it, so an assertion that means *"an
  operator can see this"* is about visibility rather than attachment.

#### The M7 gate, and the one thing it changed

The §13 M7 acceptance list and both units' plan criteria were verified by a subagent against the
implementation: **PASS, no failing items.** It raised two carry-forward caveats, both now closed:

- the plan file still said U024 was `🔵 Not Started` — fixed;
- **`corpus()` picked `documents[0]`**, so a release whose first document happened to be
  born-digital would have failed at the derivation step with *"no image-only page"* while another
  published document had one. `data/fixtures/TC1E-SF/expected.json` predicts exactly that shape
  for the pilot (born-digital, **0** image-only pages expected), so this was the concrete way the
  fixture-independence criterion could still have broken on the second fixture. It now searches
  every published document for one that has **both** page kinds, and when none does it says so and
  stops rather than skipping — on a corpus with no scanned page, *"an `unverifiable` code renders
  with its badge"* is not a UI regression, it is a state that corpus cannot produce. Re-ran green:
  22 passed.

One caveat stays open and belongs to OQ-1, not here: **the suite has never actually been run
against `TC1E-SF`**, because that fixture is `expected.json` alone — no source PDF, no frozen
`read` responses, nothing to ingest. `worked-trace.spec.ts` would refuse it by name
(`read.cases` is absent, and `readCases()` says so), which is the right failure. The code carries
no fixture literal; what is unverified is the second fixture's *shape*.

---

### U025 — Revisions, resumable ingest, and graceful shutdown

**Milestone:** M8 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-11

Four things ship together because they are one property seen from four sides: **a run can be
interrupted, and the index can be told what is true now.** `--resume` finishes a killed run
without buying it twice, step 06 checkpoints per window so a kill loses at most one,
`found_only_in_superseded` finally answers F9, and `vsir retire` lets an operator withdraw a
document without deleting the evidence.

**Demo output** — the plan's command, on the corpus this unit generates
(`VSIR_FIXTURE=data/fixtures/synthetic_large`, `VSIR_VLM=stub`, kill after the second window):

```
=========== 1. ingest, killed with SIGTERM mid-extraction ===========
run_id = 01M27VCHX3CBEA0N6VA0FZ40T8
{"event": "s2_window", "origin": "replay", "page_forms": 30, "window": [1, 30], ...}
{"event": "s2_window", "origin": "replay", "page_forms": 30, "window": [31, 60], ...}
{"event": "sigterm", "action": "checkpoint_and_exit", "signal": 15, "run_id": "01M27VC..."}
{"event": "run_stopped", "published": false, "reason": "sigterm", "step": "extract"}

   STOPPED  sigterm: SIGTERM: the run is checkpointed as `stopped` and nothing was published
   (I7, F17). Continue it with `vsir ingest --resume <run_id>` - the windows it finished are in
   the 6.3 cache and will not be bought again

=========== 2. runs show - stopped, and where it got to ===========
state        stopped · step extract · windows 3/5 · pages_indexed 0 of 150
lease        - until - (not live)
published_at - · flags -
failed       step extract: sigterm - stopped in flight; nothing was published
--- window checkpoints in vsir_runs ---
     1-30   done     checkpoint=extract   pages=30  extract_key=6a62aff3e9ff8408
    31-60   done     checkpoint=extract   pages=30  extract_key=cd3e949ae22e18c5
    61-90   done     checkpoint=extract   pages=30  extract_key=aff9843892ad7132
    91-120  queued   checkpoint=window    pages=0   extract_key=84a1de9a1d26d71b
   121-150  queued   checkpoint=window    pages=0   extract_key=d36980956a1bdbe1
  queryable pages: 0

=========== 3. --resume: finishes, and buys nothing twice ===========
exit=0
windows served from the durable cache (no model call):  3   <- 1-30, 31-60, 61-90
windows the backend was actually asked for:             2   <- 91-120, 121-150
ALL ASSERTIONS PASSED

=========== 4. runs show - published ===========
state        published · step publish · windows 5/5 · pages_indexed 150 of 150
published_at 2026-09-11T09:05:24.241082+00:00 · flags -
retired      {'deleted_stale_points': 0, 'superseded_demoted': 0, 'other_revision_points_kept': 0}
window_coverage  PASS              1  150/150 page(s) carry an S2 record
(no `failed` line: `claim` cleared the stop when the resume took the run over)

=========== 5. the document answers ===========
status ok · hits [75] · total 1
```

The kill landed after the **third** window: three are `done` with the `extract_key` each was
billed under, two are still `queued`, and the resume calls the backend for exactly the two it had
not bought. `windows 3/5` on a stopped run and the absent `failed` line on the published one are
both fixes this demo produced — findings 4 and 5 below.

`found_only_in_superseded`, the other half of the demo command, over two real published
revisions (`test_revision_lifecycle.py`):

```
lookup("K913")  -> status found_only_in_superseded · hits [] · superseded [("REV-DOC","1.3",1)]
lookup("K102")  -> status ok · hits from REV-DOC@1.4 only · superseded []
count(REV-DOC@1.3)              = 6   (unchanged after 1.4 published)
count(REV-DOC@1.3, is_current)  = 0
```

**Test results**

| Suite | Result |
|---|---|
| `bash scripts/test-unit.sh` | **1447 backend + 166 frontend passed**, conformance green |
| `test-unit.sh -k "series_id or ladder_level_2"` | 28 passed (13 ladder + 15 series_id) |
| `test-api.sh -k "revision_lifecycle"` | 15 passed |
| `test-api.sh -k "retire"` | 11 passed |
| `test-api.sh -k "sigterm_checkpoint"` | 7 passed |
| `test-api.sh -k "resume"` | 12 passed |
| `bash scripts/test-api.sh` (the whole L2/L3 suite) | **1636 passed, 13 skipped, 0 failed** |

**Invariants / failure rows closed**

- **F9** — `is_current` injected by default plus the `found_only_in_superseded` status, with the
  revision surfaced (`test_lookup_only_in_superseded_returns_typed_status`).
- **F9, continued — §6.7 clause 2** — publishing 1.4 retires 1.3's points to `is_current=false`
  **without deleting them** (`test_publishing_new_revision_keeps_prior_points`), beside clause 1's
  delete and clause 3's payload-hash isolation, all three in one file so no one of them can pass
  alone. *(Corrected at the completion gate: this bullet read **"F12 (revision half)"**. §10 gives
  F12 exactly one closing milestone — **M2a** — and no halves; keeping the prior revision's points
  is what makes `found_only_in_superseded` answerable at all, so it is **F9's** guard, and F9 is
  the row §10 closes here. Claiming it as F12 would have let a row look closed twice and let M2a's
  genuine F12 evidence hide behind an M8 label.)*
- **F8 (`series_id` half)** — stable across revisions, pure (`test_series_id_stable_across_revisions`)
  and in an index (`test_series_id_stable_across_revisions_in_the_index`).
- **AC-016** re-exercised: `test_sigterm_checkpoint_loses_at_most_one_window`,
  `test_resume_completes_without_rebilling`.
- I1 and I7 re-exercised under interruption and across revisions; register **E2** (run state on a
  daemon thread) and **E7** (a resumed run leaving duplicates) both asserted; **E9** re-verified
  at 150 pages by call spy.

**What was built**

- **`backend/vsir/vlm/cached.py` — net new.** The read/write cache in front of the boundary, and
  the reason a resume is free. `ControlPlaneStore` has existed since U020 and only
  `serve/tools/read.py` used it; step 06 needed the identical three lines, so it is a
  `Backend` wrapper rather than a second copy. **It wraps the stub too**, deliberately: a cache
  that is only in the path when the expensive backend is selected is a code path the free levels
  never exercise, and the resume it exists for would then be provable only by a run nobody can
  afford. `origin` tells them apart — `replay` the first time, `cache` the second, exactly as
  `read` has always reported. This also closes plan §4c **P2** (*no VLM cache store, so a
  re-ingest re-bills*), which was filed against U013.
- **`ingest/extract.py` — `WindowProgress`.** `extract()` reports each window twice, as it goes
  out and as it comes back. Before this the window points were written **in bulk after step 06
  returned**, so a kill during extraction left five `queued` points and no record of what had
  been bought — a checkpoint written after the loop is one that never survives the event it
  exists for. The bulk write at the end of step 06 is gone; steps 05 and 07 keep theirs.
- **`ingest/run.py`** — `RunNotResumable` and the state check in `claim()`; `retire_document()`;
  `claim()` clears a stale `failed`. `RESUMABLE` was `(STOPPED, GATED, FAILED, QUEUED)` and is
  now `(STOPPED,)`, which is what §6.9 says in one sentence: *"`stopped` … is the only state
  `--resume` accepts without `--steal`."* It was a declared constant nothing read.
- **`cli.py`** — `vsir retire <doc_id> [--revision]`; `_window_progress`; `_backend(client=…)`
  wiring the cache; **`--resume` now always opens the control plane**; `_assertions` made
  tolerant of a corpus that declares no M2a trap.
- **`serve/tools/lookup.py`** — `published_revisions`, `superseded_in`, `superseded_probe`, and
  `absence(..., superseded=…)`. **`serve/tools/skim.py`** — the same status where the *scope*
  holds no current page. **`serve/envelope.py`** — `SupersededIn` and `SearchResponse.superseded`.
- **`vsir/eval/synthetic_large.py` + `data/source/synthetic_large.pdf` (200 KB, committed) +
  `data/fixtures/synthetic_large/` (128 KB).** 150 pages, **no contents page**, so the ladder has
  nothing to cut on and folds at the cap: Level 2, five windows of thirty. Areas run in
  contiguous blocks of **17** pages, coprime with the 30-page cap, so four of the nine sections
  straddle a window fold and F8 is exercised at the rung that needs it.
- Tests: `tests/unit/test_ladder_level_2.py`, `tests/unit/test_series_id_revisions.py`,
  `tests/api/test_revision_lifecycle.py`, `test_resume.py`, `test_sigterm_checkpoint.py`,
  `test_retire.py`.

**How `found_only_in_superseded` avoids becoming a disclosure — the one real design decision**

In the pages collection, `is_current: False` means **two different things**: a revision that was
published and has since been superseded (§6.7 clause 2 — F9's evidence), *or* a run that wrote its
points and never passed its gates. They are indistinguishable there, and §5.4's `INDEXED` is
sixteen keys with no seventeenth to spare.

Answering `found_only_in_superseded` off `is_current: False` alone would therefore surface a
**half-ingested revision** through the one status that is supposed to be about the past — and it
would do so while a document is mid-ingest, which is precisely when an operator is least able to
tell the report is wrong. That is I7 with the sign flipped.

So `lookup` reads the control plane: `published_revisions()` scrolls `vsir_runs` for runs in state
`published`, and only those `(doc_id, revision)` pairs can ever be named. It runs **on the absence
path only** — one facet plus one count per naming revision, and nothing at all on an `ok`.
`test_an_unpublished_revision_is_never_surfaced_as_superseded` and
`test_a_gated_run_is_not_superseded_either` are the two that would catch the leak.

The cost is that `lookup` takes a `runs_collection`, and without one it answers `not_found` as it
always did. Every production caller passes it (`app.py` from `ToolContext.cfg`, so HTTP, MCP, the
CLI one-shot and the runner all inherit it). `eval/acceptance.py` and `eval/abstention.py` do not,
and that is correct — see the next note.

**Deviations and findings**

1. **Spec §13 M8's `ladder_level_2_required` clause is superseded, by Spec §6.2.** §13 still reads
   *"attempting a Level-2 document fails with a typed `ladder_level_2_required`"*; §6.2, rewritten
   by `fixes/001`, says *"`ladder_level_2_required` is **retained as a code and no longer
   raised**"* — because the exclusion refused 14 documents and 2,719 pages, 48 % of the real
   corpus, including the pilot. The spec wins over the plan and the more specific, later section
   wins within the spec, so `test_ladder_level_2.py` asserts §6.2's behaviour: the document
   **plans**, at Level 2, five windows, covering 150 pages once; the class is still in the
   taxonomy with its code; and nothing in `backend/vsir/**` raises it (asserted by source scan).
   **§13 M8's sentence should be amended to match §6.2** — flagged, not edited here.
2. **Spec §13 M8 asks for "≥ 700 windows"; this corpus has five.** 700 windows at a 30-page cap is
   ~21,000 pages and a PDF nobody would commit. The plan's own acceptance criterion is the
   operational one — *"large enough to force at least three window checkpoints in a single
   run"* — and five gives a kill somewhere with finished windows behind it and unstarted ones in
   front, which is the shape the measurement needs. OQ-5's real scale-out stays with U026.
3. **The M1 corpus's `superseded` row still answers `not_found`, and that is the correct
   outcome.** `data/fixtures/synthetic_pages/expected.json` predicted *"F9's
   `found_only_in_superseded` upgrade is closed at M8"*. It is closed — but that corpus is seeded
   by `vsir.eval.synthetic.seed`, which `ingest/run.py` already calls *"a fixture loader, not a
   run"*: there is **no `vsir_runs` record** behind `SYN-M1@0.9`, so there is no fact that it was
   ever published, and writing one would be inventing the fact the probe exists to check. The row's
   `why` now says so and `test_status_enum_end_to_end.py`'s docstring explains it. F9's positive
   case is proved in `test_revision_lifecycle.py`, over two revisions that really published —
   which is what Spec §13 M8's acceptance actually asks for.
4. **Two defects the demo found, both fixed.** Neither breaks a build; both mislead somebody
   reading the output.
   - `runs show` on a killed run printed **`windows 0/5`** while `vsir_runs` held two `done`
     window points. `windows_done` was only written at step 07, so the number an operator reads
     when deciding whether to resume was the one number that had not been updated. The per-window
     checkpoint now advances it — which also renews the lease per window, so a document whose
     windows take longer than `LEASE_SECONDS` can no longer let its own lease expire under it.
   - A **published** run still reported `failed: step window: sigterm` after a successful resume:
     the record told an operator two contradictory things about one run. `claim()` now clears
     `failed` when it takes over; the stop stays on the event stream as `run_stopped`, which is
     where history belongs (§11.4).
5. **The `SIGTERM` handler raced the write it was trying to make — the unit's most important
   finding, and it was invisible until the per-window lease renewal made it likely.** The handler
   called `run_module.stop()` itself and then raised `SystemExit`. A signal handler runs *between
   two bytecodes of whatever is executing*, and in a run that now renews its lease after every
   window that is very often an in-flight `save()` to the same run point. Both writes target
   `run_point_id(run_id)`; if the handler's `stopped` landed first and the interrupted `renew`
   then completed on top of it, the run was left **`running` with a live lease** — so `--resume`
   refused `lease_held`, and an operator was told a dead worker held a run that had shut down
   cleanly. That is precisely the failure U025 exists to remove, reintroduced by U025.

   It reproduced roughly one run in three across the suite, and only when a full ingest followed
   a killed one. **The fix is the shape §15 Factor IX actually asks for** — *"stop accepting
   work, drain in flight, checkpoint"* is a cooperative shutdown, and a handler that writes is
   not one. `_on_sigterm` now sets `handle.stopping` and logs, and nothing else;
   `_RunHandle.drain()` does the write and raises `IngestStopped` at a **safe point**, where no
   other write is in flight. There are two: inside the per-window checkpoint (before the next
   call goes out, and after the window in flight is recorded) and inside `_progress`, which every
   step calls as it finishes. *"At most one window"* is therefore a property of where those calls
   are rather than of when the signal happens to arrive. `IngestStopped` exits **0** — an
   orchestrator that sent the signal is not owed a non-zero status for having been obeyed.

   Two smaller things fell out of chasing it. `ControlPlaneStore.put` called `_ensure()` on
   **every** response — a live payload-schema read plus four index creations per cached entry,
   which on a 700-window run is 700 schema reads and, on a collection that does not exist yet,
   two concurrent puts each creating the same four indexes. It now ensures only when the
   collection is missing. And `test_resume.py`'s `drain()` ignored the subprocess exit code, so
   *"the run refused at step 01"* surfaced three assertions later as *"the index has 0 of 150
   pages"* — every full-ingest drain now asserts `expect=0`, and the `killed` fixture asserts the
   kill really left `stopped` before the test built anything on top of it.

6. **`--resume` silently did nothing without a store-backed `--until`.** `vsir ingest other.pdf
   --resume <run_id> --until manifest` exited 0 having ignored the flag entirely: the control
   plane was only opened for `STORE_BACKED_STEPS` or for a resume with no path, so there was no
   lease to claim, no checkpoint to read, and — the reason the test caught it — **no
   `run_document_mismatch` check**. A resume now always opens the control plane.
7. **`_assertions` asserted M2a's traps against every corpus.** The crop trap, the label offset,
   the mixed-document sample and the raster hashes are properties of
   `data/fixtures/synthetic_3window/`, and a `KeyError` was what a second corpus got for not
   having them. Each block is now conditional on its key being present — a missing key is *this
   corpus does not make that claim*, and every key a table does declare is still checked, so the
   M2a table is asserted exactly as before.
8. **`window.LEVEL_NAMES`.** `vsir ingest` printed *"level 2 · chapter-aligned"* — a two-branch
   conditional (`'chapter-aligned' if plan.level else 'whole document'`) that had never seen a
   Level 2 document. One table, indexed by level.
9. **The new corpus's `revision` is `1.0`, not the `1.3` its footers print.** §6.1 step 01 takes
   facets from the filename, the file's metadata and the uploader — never from content — and this
   corpus declares none in its filename. `expected.json` records both (`printed_revision` and
   `revision`) so the gap is visible rather than surprising.

10. **This unit makes the L2 suite heavy, and that exposed a pre-existing fragility in
   `tests/api/conftest.py` — flagged, not fixed here.** `test_resume.py` and
   `test_sigterm_checkpoint.py` drive **real `vsir` subprocesses over a 150-page document**: each
   run renders 150 rasters at dpi 220 and writes 150 points across three surfaces. Under that
   sustained churn the test Qdrant intermittently fails a `create_payload_index`, and because
   `served_collection` / `skim_collection` are **session-scoped**, one transient failure in
   `create_collection(recreate=True)` poisons **every** test that wants that fixture for the rest
   of the run. Observed across four full-suite runs on this tree: 0, 39, 91 and 313 failures,
   every one of them `Not found: Collection vsir_pages_u014_1536 / vsir_pages_u017_1536 doesn't
   exist`, and each individual file green when run on its own.

   What was done here: the ingest count in `test_resume.py` was cut roughly in half. A test that
   asserts numbers from `expected.json` no longer ingests to read a file; the two `claim()` tests
   seed a `stopped` run record instead of killing a real one (a real kill is proved next door);
   and the read-only tests share one module-scoped `published` corpus. 441 s → 360 s for the file.

   **The previous commit's message is stale on this point.** `c1d3100` records *"`test_resume.py`
   fails 5 of its tests … its fixture deletes the collection its own subprocess ingest created"*.
   That was the symptom, not the cause, and the cause was the `SIGTERM` race of finding 5: a run
   left `running` with a live lease made every resume after it refuse, and the collection was
   missing because the ingest had refused rather than because a fixture removed it. With the
   cooperative shutdown in place the whole L2/L3 suite is green — **1636 passed, 13 skipped, 0
   failed** — measured after that commit, on the same tree.

   What is left for somebody: the session fixtures have **no retry around collection creation**,
   so a single transient Qdrant error is unrecoverable for the session. A `_retry` around
   `create_collection` — the ingest path already has one (`run._retry`) — would make the suite
   tolerant of exactly this. It is conftest-wide and touches every suite, so it does not belong
   in U025's diff.

**Notes**

- **No new dependency.** `vlm/cached.py` is 85 lines over `ControlPlaneStore`, which shipped at
  U020.
- **The durable cache changes what a second ingest costs, everywhere.** Any store-backed run of an
  already-ingested document now reports `vlm_cache_hit` instead of calling the backend, including
  `POST /documents`. `test_a_second_clean_ingest_of_the_same_document_buys_nothing` is the
  statement of that property.
- **`vsir retire` demotes and never deletes**, and no route anywhere offers a delete — asserted
  against the OpenAPI document rather than by calling the verb, because a 405 on an unrouted path
  proves nothing about the surface.
- Still open for M8: **U026** (`vsir eval corpus`, the §12.6 report and the D11 gates, paid), then
  the completion gate — AC-001…AC-016 with evidence, and `v0.1.0`. *(U026 shipped on 2026-09-11;
  see its entry below. M8 is closed.)*

---

### U026 — `vsir eval corpus`, the §12.6 report and the D11 gates

**Milestone:** M8 · **Spend:** none in the end (see the notes) · **Status:** `[x]` Complete ·
**Completed:** 2026-09-11

The last unit in the plan, and the only one whose deliverable is a **number**. Everything before it
asserts the catalogue; this measures it. §12.6 names four ground-truth sets and five metrics, D11
fixes a gate for each, and one sentence of §12.6 decides the shape of the whole module —
*"Precision is a safety property and must be perfect; recall is a measured target."* So two gates
are **stops** and three are targets, and the difference shows in the output, in the exit code, and
in what a re-baseline is allowed to touch.

**Demo output** — `vsir eval corpus` (the plan's command, and M8's second §0 demo beside U025's
`--resume`), against the §13 M1 corpus seeded into a collection of its own and dropped:

```
vsir eval corpus — release u026-dev, §12.6, corpus synthetic

CORPUS — SYN-M1@1.0 in vsir_pages_u026_eval_corpus_synthetic_1536, 30 current page(s)
  ground truth: /Users/sabesonk/Documents/DILMAH/dilmah-engineering-solutioning/poc/vision_segmentation_index_and_retrieval/data/fixtures/synthetic_pages/corpus_truth.json
  held out: NO — §12.2 L5 asks for a document nobody tuned against
  The M1 corpus is NOT the held-out canary §12.2 L5 asks for — it is the corpus M1 was written
  against, so a green run here evidences the gate arithmetic and the exact surface, not
  generalisation. The §12.6 sets it stands in for are one and two orders of magnitude larger:
  2,053 register rows, ~494 alarm records and 6,880 cross-reference tokens against 20, 0 and 4
  here.

METRIC                   SET                  MEASURED             D11 GATE             VERDICT
  component_register · every code printed on a current page of SYN-M1@1.0, with the page that
  prints it — the analogue of the real corpus's component register at E pp. 59-125 (2,053 rows ·
  748 tags · 484 codes). Codes are listed in their canonical spelling and `as_printed` records
  the spelling the page actually carries, so the rows exercise `variants()` exactly as §12.3's
  table does.
code_precision           component_register   1.0000  19/19        = 1.00               PASS
  one register row is one (code, page) pair: a code returned on the right page and a wrong one
  is a precision miss, not a found code
code_recall              component_register   0.9500  19/20        ≥ 0.95, block <0.90  PASS
  - missed K404 → SYN-M1@1.0#p010
             the page's text layer is untrusted (§5.7), so it is excluded from the exact surface. A
             recall miss the corpus caused, not the index: the code is reachable through `vlm_codes`
             (D3) or a `read`
abstention_correctness   near_miss            1.0000  100/100      = 1.00               PASS
  derived from the observed-token inventory of 55 token(s) (§6.8), so OQ-4's 8,414-pair list is
  not required
alarm_label_hit          alarm_catalogue      —                    ≥ 0.99               SKIP
  SKIP · SYN-M1 prints no alarm numbers at all — p024 is the alarm list and it says in so many
  words that the alarm texts are held in the HMI project and are not reproduced. There is no
  numbers 0-539 catalogue here to measure `alarm_label_hit` against, so the set is SKIPPED by
  name rather than scored over an empty denominator.
  cross_references · every citation one current page makes to another page of the same document,
  as the citing page prints it. The real corpus's set is 6,880 tokens at 99.97% resolvable; this
  one is four, which is stated beside the metric because four tokens can fail a 0.99 gate and
  cannot evidence it.
xref_resolve             cross_references     1.0000  4/4          ≥ 0.99               PASS
  underpowered · one miss costs 0.2500 against a tolerance of 0.0100: this set can FAIL the gate
  and cannot evidence it

R4 — the grounded_rate publish bar, re-validated against this corpus (pin: 0.8)
  30 page(s), 29 with text, median 1.0000, searchable_ratio 0.9667
  SYN-M1@1.0: median 1.0000, but the text layer behind it was not written by the pinned
  extractor (probe_version: hand-written-m1). R4 asks for the distribution of a real ingest, and
  a constructed corpus reports its own construction: the M1 pages are hand-written, and the
  `impl` baseline's text is the projection of codes the old gate had already proved printed, so
  every page rates 1.0 by definition. This sets no threshold — run the report over a `pymupdf-…`
  ingest.
  recommendation: no change — the pin stays where the release ships it

RE-BASELINE — none in force. §12.6 permits one, from the M2b measurement, with a recorded rationale; M2b's re-bill is U013 and is blocked on OQ-1, so every gate above is D11's own number.

NO LEGACY COVERAGE — 14 area(s) the ported baseline says nothing about (R7). A green report above is not sign-off on these
  - §7.1 the six-value status enum — `impl` returned bare empty lists, so no absence is distinguished and `next.suggest` has no baseline at all
  - §7.1 `weak` / `needs_scope` against the server constant, and `scope_stats` — neither exists in `impl`
  … 12 more (the full list is U012's `NO_LEGACY_COVERAGE`, recorded there)

corpus: 4 measured, 0 failed, 1 skipped — PASS
exit=0
```

**What ships**

- `backend/vsir/eval/corpus.py` — net new. `D11` (the spec's five bounds, transcribed), `gates()`
  and the C10 re-baseline rule, `Truth`/`load()` over a checked-in ground-truth file, the four
  set measurements, the R4 re-validation, and `print_report`.
- `data/fixtures/synthetic_pages/corpus_truth.json` — net new. The §12.6 sets for the M1 corpus,
  authored **from the page text**: 20 printed component-register rows, 4 cross-reference tokens,
  and an `alarm_catalogue` marked `unavailable` with the reason. The same C10 direction
  `expected.json` points in — no measurement is written in the module, and nothing in the file
  can be edited to make a red row green without changing what the corpus is claimed to print.
- `backend/vsir/cli.py` — `eval corpus`, with `--corpus synthetic|indexed`, `--collection`,
  `--doc-id`, `--truth` and `--sample`.
- `backend/vsir/eval/__init__.py` — `current_payloads()` split out of `searchable_payloads()`;
  the R4 distribution needs the pages with no text layer, which the searchable reading drops.
- `backend/tests/api/test_eval_corpus_gates.py` — 48 tests.
- `.github/workflows/ci.yml` — `eval_corpus` joins the named §12.4 step: two of these five gates
  are P0 stops, so the arithmetic between a measurement and that verdict runs on every commit.

**Three findings the build produced**

1. **`0/0` is the one arithmetic accident that turns an absent corpus into a perfect safety
   score.** A metric with a zero denominator returns `None` and reports `SKIP`, never `1.00` —
   and `code_precision` over *zero returned pairs* is a **named** skip rather than a bare one,
   because "the surface answered nothing at all" and "everything it answered was right" must not
   print the same. A report where every set skipped is red for the same reason (`Report.ok`
   requires something measured).
2. **The document-wide `lookup` status explains a recall miss wrongly.** `K404` is printed on
   p010, whose text layer is `untrusted`. Scoped to the document, `lookup` answers `not_found` —
   correctly, because 29 of the 30 pages *are* searchable — and the first draft echoed that
   status into the miss line as *"the page is searchable and does not contain the phrase"*, which
   would send a reader hunting a tokenisation bug that is not there. A miss is now explained from
   the **page's own record** (`has_text`, `text_trust`) and the query's status second.
3. **A ground-truth file is found by the `doc_id` it declares, not by its directory name.** The
   first `--corpus indexed` run refused with *"no ground truth at data/fixtures/SYN-M1/"*: fixture
   directories are named after the **corpus** (`synthetic_pages` holds `SYN-M1`, `legacy` holds
   seven documents), so the obvious path finds nothing for most of them. Resolution now falls back
   to matching `corpus.doc_id` across the checked-in fixtures, and two files claiming one document
   is a refusal rather than a sort-order pick.

**Two judgement calls, stated because they are readings of §12.6 rather than transcriptions**

- **Both register ratios are counted over (code, page) pairs**, not per code. §12.6 words them per
  code, but §1.1's injury is *the wrong page*: a code returned on its right page **and** a wrong
  one would score as a found code under a per-code reading, and `code_precision = 1.00` would stop
  meaning what §12.6 says it means.
- **`xref_resolve` asks whether the right page is *among* the candidates**, not whether it is the
  only one. F5 makes ambiguity return every candidate, so a metric demanding a single hit would
  score the refusal-to-pick as a miss and reward exactly the silent pick F5 forbids.

**The C10 re-baseline rule, as code**

`REBASELINED` is empty in this release and the report says so. A `Rebaseline` carries the corpus it
was measured on, the measurement, and a rationale, and `gates()` refuses five ways: a missing
rationale / measurement / corpus, a record that lands on D11's own number and moves nothing, one
that drops under D11's blocking floor, a metric §12.6 does not have, and **any lowering of a
safety floor** — no rationale buys a `code_precision` under 1.00, because §12.6 calls precision a
safety property and the permission to re-baseline is the permission to move a *target*. Each is a
test.

**Honesty the report prints about itself**

- `held out: NO` — §12.2 L5 asks for a document nobody tuned against, and the M1 corpus is the
  corpus M1 was written against. The line says so above every metric.
- `1/denominator` per set, and **underpowered** where one miss costs more than the gate's whole
  tolerance: four cross-reference tokens can fail a 0.99 gate and cannot evidence it.
- The real-corpus scale beside the stand-in: 2,053 register rows / ~494 alarm records / 6,880
  cross-reference tokens against 20 / 0 / 4.
- R7's `NO LEGACY COVERAGE` list, printed beside the metrics so a green report is never read as
  sign-off on the §7/§8 paths the ported baseline never exercised.

**Test results**

| Suite | Result |
|---|---|
| `bash scripts/test-unit.sh` | **1447 backend + 166 frontend passed**, conformance green |
| `test-api.sh -k eval_corpus` | **48 passed** — the plan's automated command |
| `bash scripts/test-api.sh` (the whole L2/L3 suite) | **1685 passed, 13 skipped, 0 failed**, and re-run green on the final tree |

The 48 are the gate arithmetic at 1.00 / 0.95 / 0.90 / 0.99 and one step either side of each, the
five re-baseline refusals, and a **negative control for every green row** — the ground-truth file
is mutated the way a real disagreement would arrive (a register row moved to the wrong page, one
unprinted code, four unprinted codes, a citation pointed at a page it does not open) and the
command has to find it, print the P0 STOP or the BLOCKED block, and exit non-zero.

**Invariants / failure rows closed**

- **None newly, by design** — the plan says so. This unit is the *measured proof* that the
  catalogue holds, not a new guard. What it does close is **D11**, the last of Spec §3's closed
  decisions to have an owner (plan §"§3 decisions D1–D12": *D11 → U026*), and §12.6's row of the
  traceability table.
- Re-exercised end to end: **I2/I3** (only `text` answers a `lookup`; `include_unverified` stays
  false, so no `vlm_codes` hit can enter a recall number), **I5** (every absence typed), **I7**
  (`is_current` injected server-side — the superseded 0.9 page is not a register row and cannot
  become one), **F1/F3** (the whole register measured through `MatchPhrase` over `variants()`),
  **F4** (`K404`'s miss is disclosed as unsearchable, not as absent), **F5** (the bracketed
  citation resolves `interpolated` and ambiguity is not scored as a miss).

**Notes**

- **The unit is classed `Spend: paid` in the plan and cost nothing.** The spend was for *"the
  scale-out corpus the report measures"* — the real corpus of OQ-1. The report itself is a read:
  §11.4 asks for a report over the gauges the pipeline already emits, `vsir.vlm` is not in
  `corpus.py`'s import graph, and both halves are asserted (a spy on `vlm.backend` and both
  backends' `generate`, plus a spy on `probe.page_texts` / `extract.extract` /
  `embed.embed_document` / `index.upsert`). Nothing here can bill.
- **Two of §12.6's four sets have no ground truth on any corpus that exists here, and they say
  so.** The alarm catalogue skips by name; the component register and cross-reference sets are
  stand-ins at 1% and 0.06% of the real sets' size. Those are OQ-1's, and the report's job is to
  make the gap legible rather than to score around it.
- **`code_recall` lands on exactly 0.95** — 19 of 20 printed codes, the twentieth on the
  photocopied insert. That is the gate's own boundary, reached by measurement and not by
  construction, and the report names the miss and why the exact surface cannot reach it.
- The **R4 re-validation** is `grounded_rate.recommend`'s judgement, not a second one: on a
  hand-written corpus it refuses to propose a threshold at all and says why. Pointed at a
  `pymupdf-…` ingest it will do what R4 asks. That path is exercised by
  `--corpus indexed`; the number it will produce is U013's.

---

## M8 milestone gate (2026-09-11)

Every unit in M8 is `[x]`. The gate was run as §5 of the build prompt prescribes: both §0 demo
commands, then an independent subagent verifying Spec §13's M8 Acceptance list against the
implementation with file-and-line evidence.

**Demo commands (Spec §0, M8):** `vsir ingest --resume <run_id>` — recorded in the U025 entry —
and `vsir eval corpus`, recorded in the U026 entry above. Both green.

**Acceptance, verified item by item**

| # | §13 M8 acceptance item | Verdict | Evidence |
|---|---|---|---|
| 1 | F9 — a lookup only a superseded revision satisfies returns `found_only_in_superseded` | ✓ | `test_revision_lifecycle.py::test_lookup_only_in_superseded_returns_typed_status`; `serve/tools/lookup.py` `superseded_probe` / `superseded_in` / `published_revisions` |
| 2 | F12's revision half — 1.4 retires 1.3 to `is_current=false` **without deleting** | ✓ | `ingest/run.py` uses `set_payload({"is_current": False})`, never a delete; `test_revision_lifecycle.py` asserts `count(revision=OLD)` unchanged, `count(revision=OLD, is_current=True) == 0`, `deleted_stale_points == 0` |
| 3 | F8's `series_id` half — stable across revisions | ✓ | `test_series_id_revisions.py` (pure) and `test_revision_lifecycle.py::test_series_id_stable_across_revisions_in_the_index` |
| 4 | A `SIGTERM` mid-window loses at most one window and publishes nothing partial | ✓ | `test_sigterm_checkpoint.py::test_the_run_publishes_nothing_partial` (`queryable == 0`, no `is_current` point for the run); `test_resume.py::test_sigterm_checkpoint_loses_at_most_one_window` |
| 5 | A generated large PDF survives a kill and resumes without re-billing completed windows | ✓ **as amended by C15** | `test_resume.py::test_resume_completes_without_rebilling` — the windows already `done` are exactly the ones the resumed run never calls the backend for; `::test_the_corpus_forces_at_least_three_window_checkpoints` is the precondition. **The "≥ 700 windows / kill at window 700" figure was not met and was never buildable** — see below |
| 6 | Attempting a Level-2 document fails with a typed `ladder_level_2_required` | ✓ **as amended by C14** | Superseded by §6.2 (rewritten by `fixes/001`): the code is retained in the `WindowError` family and never raised, and a Level-2 document **plans**. `ingest/window.py` keeps the code string; `test_ladder_level_2.py` asserts `raise LadderLevel2Required` appears nowhere under `backend/vsir/` |
| 7 | The evaluation report states code exactness and abstention correctness per set | ✓ | `eval/corpus.py::D11` transcribes §12.6/D11 and is cross-checked against `abstention.CORRECTNESS_GATE` at import; `print_report` emits `METRIC / SET / MEASURED / D11 GATE / VERDICT` per metric; `test_eval_corpus_gates.py` asserts the printed table covers every D11 metric and every §12.6 set |

**Two spec corrections the gate produced.** Both are stale §13 text, not implementation defects,
and both were applied to the spec's own corrections table (§2.3) rather than worked around:

- **C14** — §13 M8 gated the milestone on a refusal §6.2 forbids. `fixes/001` rewrote §6.2 after
  measuring the old ladder against the real corpus (48% of pages refused, the pilot among them);
  §13's sentence was left behind. Between two sections of one spec the later and more specific
  one wins, and the implementation already followed §6.2.
- **C15** — §13 M8 sized the resume proof by absolute scale (≥ 700 windows). 700 windows at the
  30-page cap is ≈21,000 pages: a PDF nobody would commit, and a D10 replay fixture would need
  700 frozen S2 responses. The figure is replaced by the **operational criterion the property
  actually needs** — a corpus large enough to force at least three window checkpoints, so a kill
  leaves completed windows behind it and uncompleted ones in front. **This reduces the evidenced
  scale and C15 says so:** lease renewal over hours, Qdrant at ≈21,000 points and the cost line
  are *not* evidenced, and stay with **OQ-5**, which C15 explicitly does not close.

**What a green M8 does not evidence.** The `vsir eval corpus` report is honest about this in its
own output and it belongs in the gate record too: `alarm_label_hit` is a named SKIP because the
M1 corpus prints no alarm numbers; the component register is 20 rows against §12.6's 2,053 and
the cross-reference set is 4 tokens against 6,880 (printed `underpowered`); and `held out: NO` —
§12.2 L5 asks for a document nobody tuned against. §12.6's gates are therefore **exercised, not
evidenced**, until OQ-1's corpus lands. That is U013's, and U013 stays `[!]`.

**Tag:** `cr1-m8`.

---

## Completion gate — AC-001…AC-016 and §10's "Closed at" column (2026-09-11)

The gate the build prompt §5 defines: every acceptance criterion of Spec §14 verified **with
evidence**, every failure row of §10 checked against the milestone that owns it, and only then the
release tag. Four read-only audits ran it — three over the AC list, one over F1…F19 — and each was
told a docstring or a markdown claim is not evidence: a criterion counts as closed only if a
deterministic check **fails when the guard is removed**.

### The suite, on today's HEAD

| Layer | Command | Result |
|---|---|---|
| L0/L1 + conformance | `bash scripts/test-unit.sh` | **1459 passed** (backend) · **166 passed** (frontend, 17 files) · TypeScript clean |
| L2/L3 | `bash scripts/test-api.sh` | **1688 passed, 13 skipped, 0 failed** (22m47s) |
| E2E | `VSIR_TEST_CONSOLE_PORT=5199 bash scripts/test-e2e.sh` | **22 passed**, exit 0 |
| L4 (paid) | not run | no `Spend: paid` unit ran; U013 stays blocked |

**A red run that was not the build's fault, recorded so nobody re-debugs it.** The first L2/L3 run
of this gate came back **182 failed, 1506 passed** — 1688 collected either way, and every failure
in the *tail* of the run. The cause was contention, not code: four audit subagents were running
against the same machine while `scripts/test-api.sh` owned the Docker test stack, and that stack is
a singleton (fixed ports 8001/6335, `down -v` on teardown). Re-run alone, the identical tree is
green. **The L2/L3 suite owns the test stack exclusively — never run anything that can touch Docker
beside it.**

### AC-001…AC-016

| AC | Verdict | The check that fails if the property breaks |
|---|---|---|
| **AC-001** hallucinated code unfindable via `lookup` | ✓ | `test_lookup_pure.py::test_a_hallucinated_code_is_only_ever_an_unverified_hit`; `test_i2_text_provenance.py::test_derivation_assigns_text_from_the_probe_and_from_nothing_else` (AST walk — a literal assigned to `text=` fails) |
| **AC-002** phrase-only; variants re-space only | ✓ | `test_variants.py::test_a_variant_only_ever_re_spaces_the_label`; `test_exact.py::test_exact_filter_is_the_only_call_site_of_match_phrase` (AST scan over the package) |
| **AC-003** six statuses, no empty `ok` in Family A | ✓ | `test_envelope.py::test_an_empty_ok_is_impossible` + `::test_the_validator_survives_optimisation` (a `raise`, not an `assert`, so `python -O` cannot strip it) |
| **AC-004** scanned → `not_searchable`, never `not_found` | ✓ | `test_status_enum_end_to_end.py::test_not_searchable_is_never_not_found`; `::test_an_untrusted_text_layer_is_also_not_searchable` |
| **AC-005** `present`/`absent`/`unverifiable` per `(claim, page)` | ✓ | `test_verify_tool.py::test_a_verdict_is_per_claim_and_page_not_per_claim`; `::test_the_three_states_never_collapse_into_two` |
| **AC-006** two page-number checks; offset bisects and re-bills | ✓ | `test_derive_offset.py::test_an_offset_failure_bisects_the_window_and_re_derives_the_halves`; `test_offset_repair.py::test_no_page_is_derived_from_the_response_that_failed_the_check` |
| **AC-007** ungated run → zero queryable pages | ✓ | `test_publish_and_retire.py::test_unpublished_run_zero_queryable_pages`; `test_index_upsert.py::test_a_record_that_arrives_already_current_is_refused` |
| **AC-008** every §7.3 cap a typed 400 naming its bound | ✓ | all eight caps carry their own test; the two that matter most are `test_fetch_caps.py::test_the_megapixel_bound_is_decided_before_a_single_render` and `test_read_caps.py::test_the_page_cap_does_not_cost_the_caller_a_read` — the bound is decided **before** the work, so no clamp can hide |
| **AC-009** worked trace = one paid `read`, with citations | ✓ | `test_ask_replay.py::test_the_worked_trace_answers_in_exactly_one_paid_read`, corroborated independently by `::test_the_read_call_count_is_one_in_the_audit_log_too` |
| **AC-010** abstains with coverage numbers | ✓ | `test_abstention_wording.py::test_the_composer_cannot_emit_a_sentence_the_rule_forbids`; `test_ask_replay.py::test_the_abstention_cannot_claim_the_corpus_is_exhausted_while_a_page_is_unexamined` |
| **AC-011** L3 abstention eval, 100 near-misses, in CI | ✓ | `test_near_miss_codes_never_answer.py` (`assert len(sample) == 100`), with the anti-vacuity control `::test_the_real_codes_the_fakes_came_from_are_all_findable`; `.github/workflows/ci.yml` runs it `on: push` |
| **AC-012** boot refuses on drift, fingerprint, `-latest` | ✓ | **closed at this gate** — see below |
| **AC-013** `labels.jsonl` delivers the five Part A fields | ✓ | **closed at this gate** — see below |
| **AC-014** every §0 demo runs green on a clean checkout | ⚠ **8 of 9** | **M2b cannot run: OQ-1** — see below |
| **AC-015** one image, env config, no local state | ✓ | `test_conformance.py::test_one_image_runs_every_process_type`; `::test_no_module_level_mutable_session_store` with the planted-violation control `::test_the_ast_scan_catches_a_planted_session_store` |
| **AC-016** SIGTERM leaves no half-document; probes per §15.1 | ✓ | `test_resume.py::test_resume_completes_without_rebilling`; `test_probes.py::test_health_stays_green_and_ready_goes_red_when_qdrant_is_unreachable` |

### The two the gate closed, and the one it could not

**AC-012 — the fingerprint refusal was the one §4.3 refusal still missing.** §4.3 names five
conditions that must refuse to start. Four shipped at M0; the third — *the collection fingerprint ≠
the configured recipe* — was deferred to U010 because `embed_model` and `composition_version` are
not observable from a Qdrant collection, and then never came back. `ingest/fingerprint.require`
guarded the **write**, which is what keeps two families of vector out of one cosine space. It says
nothing about a process that only ever **reads**: that one embeds the query with this release's
model and compares it against vectors made by another, no guard fires, and *the only symptom is
worse neighbours* — indistinguishable from a thin corpus. `doctor.check_collection_fingerprint`
now reads U010's control-plane record and refuses the boot, and `/ready` goes 503 if the recipe
starts disagreeing under a running instance. Demonstrated, not merely asserted:

```
$ vsir doctor
{"check": "collection_fingerprint", "collection": "vsir_pages_1536",
 "detail": "vsir_pages_1536 was embedded under this release's recipe (45a09c588c25422c)",
 "event": "boot_check_ok", "stored_digest": "45a09c588c25422c"}
{"event": "doctor_ok", "failed_checks": [], "fingerprint_id": "45a09c588c25422c"}
exit=0

$ VSIR_EMBED_MODEL=some-other-embed-model vsir doctor
{"check": "collection_fingerprint",
 "detail": "vsir_pages_1536 was embedded under a different recipe (embed_model: stored
   'gemini-embedding-2' != configured 'some-other-embed-model'). Refusing to serve: a query
   embedded by this release cannot be compared with vectors made by another … The remedy is a NEW
   collection, a full re-embed and an alias swap — never an in-place mix (§6.6)",
 "differences": {"embed_model": ["gemini-embedding-2", "some-other-embed-model"]},
 "event": "boot_check_failed"}
{"event": "doctor_refused", "failed_checks": ["collection_fingerprint"]}
exit=1
```

Three outcomes are deliberately **not** refusals, on the same policy as the schema check: an
unreachable Qdrant is inconclusive (an outage must not become a fleet-wide restart loop, §15.1); a
configuration that does not parse belongs to `config_valid`; and **a collection nobody has ingested
into yet has no record to disagree with** — refusing there would mean a fresh deployment could
never boot far enough to run the ingest that writes one. A stored record that exists but *cannot
say* whether it matches — wrong `kind`, or one of §6.6's four fields missing — **is** a failure.
That is drift, not absence.

**AC-013 — `summaries[]` was on the wire and off the test.** Four of the five fields AC-013 names
were pinned by a test that indexes them literally. `summaries` was pinned only by
`sorted(row) == sorted(LABEL_FIELDS)` — a comparison against *the export module's own constant*.
Deleting `"summaries"` from `LABEL_FIELDS` and from `label_row` left the entire suite green, and
Part A would have lost the field in silence. The test file's own docstring claimed the field set was
"asserted as an equality against §6.8's list"; it was not. §6.8's fourteen keys are now transcribed
into the test as an independent literal, `summaries[]` is read by key the way `page_range` already
was, and the mutation is caught: **deleting the field from both the constant and the row now fails
3 tests** (it failed 0 before).

**AC-014 — eight of nine, and the ninth is OQ-1.** M0, M1, M2a, M3, M4, M5, M6, M7 and M8 all have
recorded green demo output; M0, M1, M8's `eval corpus` and M7's E2E were re-run at this gate and are
green on today's HEAD. **M2b's demo has never run and cannot:** it is
`VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf`, the pilot PDF was never delivered, and
`data/source/*` is gitignored — so it is unrunnable on a clean checkout by anyone, not just here.
Two further honesty corrections the gate made to this file's own ledger, which read *worse* than the
build actually is in one direction and *better* in another:

- the ledger still showed **M7 and M8 as ⬜** although both record green demo output — corrected to ✅;
- **M6 is marked ✅ *(substituted question)***: §0's literal question is about `TC1E-SF`, so it was
  asked of the OQ-1 fallback corpus instead. The loop, the answer gate and the abstention branch are
  all exercised; §0's *wording* is not.

**AC-014 is therefore not ticked.** One milestone's demo has never been executed, and a criterion
that reads "every milestone's demo command runs green" cannot be signed off on eight of nine.

### Spec §10 — F1…F19 against the "Closed at" column

**All nineteen rows are closed, each by the milestone §10 names, each by a test that inverts when
its guard is deleted.** The rows with two closing milestones (F2, F4, F5, F8, F11, F18) were checked
as two halves and both hold. The four rows singled out as easy-to-claim turned out to be the
best-evidenced in the build: F7 has both §6.4 checks in one function plus an end-to-end
bisect-and-re-bill through a real replay backend; F13's `MAX_TOKENS` path is exercised as an actual
`finish_reason`, not a string handed to `bisect_window`; F9's retirement is filter-scoped to
`(doc_id, revision)` in both clause 1 and `retire_document`, and **a blanket delete-by-`run_id`
appears nowhere in the tree** — which is what keeps F12's guard from destroying F9's evidence.

Three defects, all in *this file* rather than in the code — a pointer that does not resolve is how a
future reader concludes a guard is missing and rewrites one that already exists:

1. **F12 was claimed twice.** The U025 entry read "**F12 (revision half)**". §10 gives F12 exactly
   one closing milestone (M2a) and no halves; what M8 evidences there — keeping the prior revision's
   points while demoting them — is §6.7 clause 2, which is **F9's** guard. Relabelled.
2. **Three closing citations for F18 were error codes, not tests.**
   `test_read_page_cap_exceeded`, `test_fetch_budget_exceeded` and `test_dpi_requires_region` return
   zero hits across `backend/tests/`. The guards are real and so are the tests; the pointers to them
   were not. Replaced with the names that exist.
3. **F8's "carry-in" is narrower than §10's guard text.** `stitch.py` merges sightings on the
   canonical section key but never *carries* a section into a page that reported none — the gap is
   disclosed as `noncontiguous_section` rather than smoothed over. The M2a gate recorded this as a
   deliberate reading, so it is disclosed rather than hidden, but **§10's wording and the code no
   longer say the same thing** and one of them should be changed. Left as found: narrowing a
   disclosed guard at the completion gate would be the wrong moment, and widening it is a spec edit.

### Hardening the gate found but did not apply

Neither is a failing criterion; both are one regression away from becoming one, and both are
recorded rather than silently fixed because they sit outside the ACs' wording.

- **`POST /search`'s `SearchResult` carries no `empty_is_never_ok` validator.** The five Family A
  tools each get the invariant from a model validator that raises; the flat surface added after the
  plan holds it with a conditional plus one test
  (`test_search_surface.py::test_a_scope_matching_nothing_is_out_of_scope_and_not_an_empty_ok`).
  Lifting the same `model_validator` onto `SearchResult` would make it structural. AC-003 is about
  Family A and passes as written.
- **`preserves_characters()` is never asserted at a call site.** `exact_filter` builds variants
  without checking them; the I3 property is table-driven over 29 labels rather than generated. One
  `if not preserves_characters(label): raise` in `core/exact.py` would close the gap by construction.

### Verdict

**15 of 16 acceptance criteria are closed with evidence. AC-014 is 8 of 9.** All 19 failure rows of
§10 are closed by the milestone that owns them. Every test layer that can run without spending money
is green.

**`v0.1.0` is not tagged.** Two things block it and they are the same thing: **U013** is `[!]` and
**AC-014** is ⚠, both because OQ-1's pilot PDF (`data/source/TC1E-SF.pdf`) was never delivered.
Tagging a release while a top-level criterion is knowingly unmet would put the untrue claim in the
one place nobody re-reads. The tag needs either the pilot PDF — after which U013's paid ingest and
M2b's demo close both rows together — or an explicit decision to ship v0.1.0 with the M2b slice
excluded and AC-014 recorded as waived. **That is a call for the project owner, not for the build.**
