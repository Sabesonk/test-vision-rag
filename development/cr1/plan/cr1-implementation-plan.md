# Implementation Plan: CR1 — Vision Segmentation, Index & Retrieval

**Source Specification:** `development/cr1/spec/spec.md`
**Implementation Type:** backend+frontend (backend-dominant; the frontend is Spec §13 M7 only)
**Status:** Draft
**Created:** 2026-09-09
**Last Updated:** 2026-09-09

---

## Table of Contents

1. [Overview](#1-overview)
2. [Scope and Objectives](#2-scope-and-objectives)
3. [Milestone Map](#3-milestone-map)
4. [Implementation Units](#4-implementation-units)
5. [Dependency Graph](#5-dependency-graph)
6. [Test Strategy](#6-test-strategy)
7. [Invariant & Failure Coverage](#7-invariant--failure-coverage)
8. [Assumptions and Risks](#8-assumptions-and-risks)
9. [Traceability Matrix](#9-traceability-matrix)
10. [Implementation Order](#10-implementation-order)
11. [Parallel Bundles](#11-parallel-bundles)

---

## 1. Overview

26 units across ten ordered milestones (M0–M8, with M2 split per Spec §2.3 C1/C9). Every unit ships a
runnable artefact and a demo command; **a milestone with no runnable demo is not complete** (Spec §0).

### Key deliverables
- The exact-match surface (`tok` / `variants` / `exact_filter`), proved on synthetic text at zero spend — Spec §13 M1.
- The twelve-step ingestion pipeline with publish gating and the three-clause retirement rule — Spec §6.
- Eight tools over HTTP + MCP behind one implementation each — Spec §7.
- The reference runner with the server-side answer gate — Spec §8.
- Invariants I1–I8 as assertions and failure rows F1–F19 as tests — Spec §9, §10, §12.
- One operator console in replay mode — Spec §13 M7.
- The twelve-factor runtime, delivered at **M0** and inherited by every later unit — Spec §15.

### Nature of the work
This is a **restructured port** of a working implementation at `impl/` (16 modules, 3,268 lines,
7 documents ingested, **zero tests**) into a new repository — Spec §2.3 C1. It is neither a
greenfield build nor an in-place refactor. Spec §4.1 marks each new module `←` (port),
`≈` (port with changes) or `+` (net new); **every unit that builds a `←` or `≈` module lists
"read `impl/app/<module>.py` first" as its first requirement**, and its Deliverables state what is
ported versus written.

### Technology stack (Spec §4.2 — pinned, no additions)
Python 3.11 · `fastapi==0.141.1` · `uvicorn[standard]==0.52.4` · `python-multipart==0.0.32` ·
`google-genai==2.22.0` · `qdrant-client==1.19.0` · `PyMuPDF==1.28.2` · `pillow==12.3.0` ·
Pydantic v2 · MCP official Python SDK (stdio + SSE) · `qdrant/qdrant:v1.19.0` ·
React + TypeScript + Vite (M7) · Playwright (`e2e/`, exists).

**Store is Qdrant only**, two collections: `vsir_pages` and `vsir_runs`. No relational database, no
ORM, no migration tool, no queue service — a conformance grep bans `alembic` and `sqlalchemy`.

---

## 2. Scope and Objectives

### In scope (Spec §2.1)
- Ingestion steps 01–12: manifest → probe → render → S1 facts → window → S2 extraction → derivation
  → stitching → embedding → indexing → publish gates → exports.
- One Qdrant collection, one point per page, two full-text indexes with `phrase_matching=True`.
- Eight tools over HTTP + MCP: `skim_documents`, `skim_sections`, `skim_pages`, `lookup`, `resolve`,
  `fetch`, `read`, `verify`.
- The reference runner: the loop, tri-state triage, the six correction loops, the answer gate.
- I1–I8 as assertions; F1–F19 as tests; the L0–L5 + E2E + conformance pyramid.
- One operator console (M7) and the corpus evaluation report (M8).

### Out of scope (Spec §2.2)
The retrieval agent as a product surface (POC Part A) · the correlation graph and entity
`resolve`/`describe`/`neighbors` · ERP and spare-parts capture images · multi-tenancy and
`tenant_id` filters · bounding boxes and `around="K158"` (D6 — `region` only) · OCR of scanned pages
(disclosed as `not_searchable`, never silently patched) · the Level 2 window ladder and its carry
chain (Spec §6.2 — a Level-2 document must fail typed `ladder_level_2_required`).

> **§2.2's "Sparse/lexical vector + RRF fusion" row is superseded by Spec §3 D2**, which re-decided
> against the working implementation: the sparse surfaces and RRF **ship in v1**. Only plan2's
> *measurement* of their value moved to an M8 evaluation. See §8 Assumptions, item SA-2.

### Success criteria
The sixteen acceptance criteria of Spec §14 (AC-001…AC-016), each mapped to units and named tests in
§9 below. AC-014 — every §0 demo command runs green on a clean checkout — is the roll-up.

---

## 3. Milestone Map

Units may not cross a milestone boundary, and milestones may not be reordered (Spec §13).
"Spend" is the milestone's ceiling from Spec §0; per-unit spend is recorded on each unit and several
units inside a paid milestone spend nothing (see §8, assumption SA-6).

| M | Units | Demo command (Spec §0) | Spend ceiling | Invariants asserted | Failure rows closed |
|---|---|---|---|---|---|
| **M0** | U001, U002 | `vsir doctor && bash scripts/test-unit.sh` | none | — | F11 (boot half) |
| **M1** | U003, U004, U005, U006 | `vsir demo exact --synthetic` | none | I2, I3, I5, I6 | F1, F2 (core), F3, F10, F14, F16 |
| **M2a** | U007, U008, U009, U010, U011 | `vsir ingest data/source/synthetic_3window.pdf --vlm stub` | none | I1, I4, I7 | F4 (M2a), F5 (M2a), F6, F7, F8 (stitching), F11 (key half), F12 (M2a), F13, F15, F17 |
| **M2b** | U012, U013 | `VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf` | S2 + embed, once | — | — (closes the §12.3 parity and negative-set rows) |
| **M3** | U014, U015, U016 | `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` | none | — | F2 (tool half), F4 (M3 half) |
| **M4** | U017, U018 | `vsir demo narrow` | none | — | F5 (M4 half), F8 (stateless half), F18 (fetch half) |
| **M5** | U019, U020 | `VSIR_ALLOW_PAID=1 vsir read --pages … --question …` | read | — | F18 (read half), F19 |
| **M6** | U021, U022 | `VSIR_ALLOW_PAID=1 vsir ask "carton discharge won't restart after an E-stop reset"` | read | I8 | — |
| **M7** | U023, U024 | `bash scripts/test-e2e.sh` then browse `http://localhost:5174` | none (fixture-backed) | — | — |
| **M8** | U025, U026 | `vsir ingest --resume <run_id>` and `vsir eval corpus` | ingest | — | F8 (series_id half), F9, F12 (revision half) |

**M0, M1, M2a, M3, M4 and M7 cost nothing.** M1 is the whole correctness proof and it spends zero.

---

## 4. Implementation Units

## Unit: Runtime skeleton, pins, and `vsir doctor` (ID: U001)

**Status:** 🔵 Not Started
**Milestone:** M0
**Priority:** P0-Critical
**Type:** harness
**Size Estimate:** Large
**Spend:** none

### Goal
Stand up the installable `backend/vsir/` package, the pinned dependency set, the twelve-factor
container runtime, and `vsir doctor` implementing all five boot refusals of Spec §4.3.

### Working Deliverable
The `vsir` CLI with a working `doctor` subcommand, plus a Dockerfile and `.env.example` that
together satisfy Spec §15 Factors I, II, III, V, XI.

### Demo Command
```bash
vsir doctor && VSIR_VLM_MODEL=gemini-pro-latest vsir doctor; echo "exit=$?"
```
The first invocation prints `release_id`, the resolved model ids and the index fingerprint, and
exits 0. The second prints a named refusal (`model id ends in -latest`) and exits non-zero.

### Deliverables (files)
- `backend/vsir/__init__.py`, `backend/vsir/cli.py` — **ported** from `impl/scripts/interfaces_demo.py`
  (argument-parsing spine only, §2.4); `doctor` is the only subcommand registered here.
- `backend/vsir/doctor.py` — **written**, net new: the §4.3 boot self-check, shared by the CLI and by
  server start (U014). *Note:* `core/health.py` in Spec §4.1 is `grounded_rate`, not this — it is
  built by U009.
- `backend/vsir/config.py` — **ported, restructured** from `impl/app/config.py`: env-only, no
  `config.yaml` (Spec §15 Factor III).
- `backend/vsir/logging.py` — **written**: structured JSON to stdout, one event per line, carrying
  `release_id`, `run_id`, `session_id`, `request_id`, `tool`.
- `requirements.txt`, `requirements.lock` — **written**, pins from Spec §4.2 carried from
  `impl/requirements.txt`; PyYAML dropped (config is env-only).
- `Dockerfile` — **written**: non-root user, base pinned **by digest**, read-only root filesystem,
  writable `tmpfs` for the raster cache, no build tools in the runtime layer, never tagged `latest`.
- `.env.example` — **written**: every variable of Spec §15 Factor III —
  `VSIR_PORT`, `VSIR_QDRANT_URL`, `VSIR_COLLECTION`, `VSIR_VLM`, `VSIR_VLM_MODEL`,
  `VSIR_EMBED_MODEL`, `VSIR_PROMPT_VERSION`, `VSIR_API_TOKENS`, `VSIR_READ_QUOTA`,
  `VSIR_ALLOW_PAID`, `VSIR_LOG_LEVEL`, `VSIR_RELEASE_ID`.
- `README.md` — **written**: decisions D1–D7 restated (Spec §13 M0 acceptance).
- `backend/tests/unit/test_doctor.py`, `backend/tests/unit/test_logging.py` — **written**.

### Requirements
- Read `impl/scripts/interfaces_demo.py` and `impl/app/config.py` first (Spec §2.4).
- Spec §4.1 package layout. **Modules are created by the milestone that implements them** — do not
  create empty placeholders (Spec §13 M0).
- Spec §4.2 pins, transitively locked (Factor II); `vsir doctor` prints the resolved versions.
- Spec §4.3: refuse to start, with a named reason and non-zero exit, on (1) a model id ending
  `-latest`, (2) a live payload schema missing any `INDEXED` key, (3) a collection fingerprint that
  does not match the configured embedding model, (4) `text`/`vlm_codes` not being text indexes with
  `phrase_matching=True`, (5) a missing required env var. **Never degrade to a partial service.**
- Spec §15 Factors I, II, III, V, IX (SIGTERM handler), XI; §15.2 bans.
- Spec §20.1 register items closed here: **B6** (pin the model id, never a floating alias).

### Invariants Enforced
- None asserted at M0 (Spec §9 assigns nothing to M0).

### Failure Rows Closed
- **F11 (boot half)** — resolved model id is refused when it ends `-latest` — `test_doctor_refuses_latest_model_alias` (L0).

### Dependencies
- **Depends On:** []
- **Enables:** [U002, U003, U007]
- **External:** Docker, a digest-pinned Python 3.11 base image.

### Acceptance Criteria
- [ ] `vsir doctor` exits 0 with a complete `.env` and prints `release_id`, every resolved model id, and the index fingerprint.
- [ ] `VSIR_VLM_MODEL=<anything>-latest vsir doctor` exits non-zero and the message contains the literal substring `-latest`.
- [ ] `VSIR_EMBED_MODEL=<anything>-latest vsir doctor` likewise exits non-zero.
- [ ] Unsetting any one of the twelve Factor III variables makes `vsir doctor` exit non-zero naming that variable.
- [ ] Every log line emitted between process start and exit parses with `json.loads` and contains the keys `release_id` and `level`.
- [ ] `SIGTERM` sent during startup exits 0 within the grace period, leaving no orphan process.
- [ ] `.env.example` contains all twelve Spec §15 Factor III variables and no value that looks like a real secret.
- [ ] `docker build` produces an image running as a non-root UID, with a read-only root filesystem and a digest-pinned `FROM`, and the tag is not `latest`.

### Test Plan
**Levels:** [L0, conformance]
**Commands:** `bash scripts/test-unit.sh -k "doctor or json_log or sigterm_boot"`
**Fixtures/Stubs:** none — the unit is pure runtime skeleton; no Qdrant and no VLM.
**Edge Cases:** each of the five §4.3 refusals independently; SIGTERM mid-boot; a `.env` missing exactly one variable.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the digest-pinned base image drifts out of support. **Mitigation:** the digest is in the Dockerfile and in the lock file; `vsir doctor` prints resolved versions so a bump is visible in the demo output.
- **Risk:** `impl/app/config.py`'s YAML shape is ported wholesale, re-introducing a committed config file (§15.2 ban). **Mitigation:** the conformance grep in U002 fails on config read from a repo file; the port keeps the *shape*, not the loader.

### Rollback Plan
N/A

---

## Unit: Qdrant test harness, probes, and conformance greps (ID: U002)

**Status:** 🔵 Not Started
**Milestone:** M0
**Priority:** P0-Critical
**Type:** harness
**Size Estimate:** Medium
**Spend:** none

### Goal
Turn Spec §12.5's conformance rules into an executable gate, rewrite the test stack from Postgres to
Qdrant, and split liveness from readiness per Spec §15.1.

### Working Deliverable
`bash scripts/test-unit.sh` running the conformance-grep suite, and a `GET /health` / `GET /ready`
pair that behaves correctly while Qdrant is stopped.

### Demo Command
```bash
docker compose -f docker-compose.test.yml up -d && bash scripts/test-unit.sh && \
  curl -s -o /dev/null -w "health=%{http_code}\n" localhost:8001/health && \
  docker compose -f docker-compose.test.yml stop test-qdrant && \
  curl -s -o /dev/null -w "health=%{http_code}\n" localhost:8001/health && \
  curl -s -o /dev/null -w "ready=%{http_code}\n"  localhost:8001/ready
```
A reviewer sees the grep suite pass, then `health=200`, then — with Qdrant stopped — `health=200`
and `ready=503`.

### Deliverables (files)
- `docker-compose.test.yml` — **rewritten** from Postgres to `qdrant/qdrant:v1.19.0`; backend test
  port `8001`, Qdrant test port **`6335`** (never `6334`, which is dev gRPC), frontend test `5174`.
- `backend/vsir/serve/app.py` — **written** (health/ready only at this stage; the full app is U014's,
  ported from `impl/app/main.py` there).
- `scripts/test-unit.sh`, `scripts/test-api.sh`, `scripts/test-e2e.sh` — **extended** to this repo's
  real layout; `scripts/test-paid.sh` — **written**, refuses to run without `VSIR_ALLOW_PAID=1`.
- `backend/tests/unit/test_conformance.py` — **written**: the §12.5 core set and cloud-native set as
  real assertions, scoped to `backend/vsir/**` and `requirements*.txt` (plus `Dockerfile*` and
  `docker-compose*.yml` for the cloud-native set), **excluding markdown and its own source file**.
- `backend/tests/api/test_probes.py` — **written**.
- `AGENTS.md` — **filled** with the real run/build/test commands (it is currently a template).

### Requirements
- Spec §12.5 core greps: `MatchText`/`MatchTextAny` under `serve/`; any fuzzy / similarity /
  edit-distance library in `requirements*.txt`; any field named `score` in a response model; a model
  id ending `-latest`; `alembic` or `sqlalchemy`; `get_text(` outside `ingest/probe.py`; the struck
  names `SCHEMA_CARD`, `IdClass`, `entity_keys`, `classify(`.
- Spec §12.5 cloud-native greps: `logging.FileHandler`; a container image tagged `latest`; a
  credential literal (`api_key=`, `token=`, `Bearer ` + a string literal); a test-only branch
  (`if TESTING`, `if os.environ.get("TESTING")`) inside `backend/vsir/**`; a `RetrievalState`-style
  module-level mutable session store (C11).
- Spec §15.1: `/health` is liveness and **MUST NOT** fail on a backing-service outage; `/ready` is
  readiness (boot self-check passed **and** Qdrant reachable **and** the pinned index schema
  present). Both probes are free — no `read`, no embedding, no vector search beyond a capped `count`.
- Spec §20.1 register item closed here: **E6** (no tests at all).

### Invariants Enforced
- None.

### Failure Rows Closed
- None (this unit is the mechanism by which several others stay closed).

### Dependencies
- **Depends On:** [U001]
- **Enables:** [U003] and, through the greps, every later unit's Definition of Done
- **External:** Docker Compose, `qdrant/qdrant:v1.19.0`.

### Acceptance Criteria
- [ ] With Qdrant up: `GET /health` → 200 and `GET /ready` → 200.
- [ ] With Qdrant stopped: `GET /health` → 200 **and** `GET /ready` → 503 with a body naming `qdrant_unavailable`.
- [ ] Injecting the literal `entity_keys` into a scratch file under `backend/vsir/serve/` makes `bash scripts/test-unit.sh` exit non-zero; removing it makes it pass.
- [ ] Injecting `logging.FileHandler` anywhere under `backend/vsir/**` fails the cloud-native grep.
- [ ] The conformance test excludes its own file — it does not fail on the banned strings it names.
- [ ] The grep suite does not scan markdown: adding `entity_keys` to a `.md` file leaves the suite green.
- [ ] `bash scripts/test-paid.sh` exits non-zero with a named reason when `VSIR_ALLOW_PAID` is unset.
- [ ] `docker-compose.test.yml` contains no Postgres service and binds Qdrant on `6335`, never `6334`.
- [ ] `AGENTS.md` contains no template placeholder text and every command in it runs.

### Test Plan
**Levels:** [L2, conformance]
**Commands:** `bash scripts/test-unit.sh -k conformance` · `bash scripts/test-api.sh -k probes`
**Fixtures/Stubs:** ephemeral Qdrant from `docker-compose.test.yml`; no VLM.
**Edge Cases:** the grep's self-exclusion; markdown exclusion; `/health` under a Qdrant outage (Spec §11.3 row 1).

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the greps produce false positives on legitimate code (e.g. `ingest/index.py` upserting a payload key named `text`). **Mitigation:** Spec §12.5 is explicit — I2 is enforced by an L1 assertion (`record.text == probe_text[page_no]`, owned by U009), not by grepping for `"text"`; only `get_text(` is grepped.
- **Risk:** `/ready` performs an expensive check and becomes a load source. **Mitigation:** Spec §15.1 caps probe cost at a bounded `count`; asserted by a call-shape test.

### Rollback Plan
N/A

---

## Unit: Page record, identifiers, and the `INDEXED` schema (ID: U003)

**Status:** 🔵 Not Started
**Milestone:** M1
**Priority:** P0-Critical
**Type:** core
**Size Estimate:** Medium
**Spend:** none

### Goal
Port the page-record shape and identifier scheme, and stand up the one `INDEXED` dict that creates
the payload indexes, gates every filter and is asserted at boot (I6).

### Working Deliverable
`vsir doctor --create-collection` — creates the `vsir_pages` collection from `INDEXED` against an
ephemeral Qdrant, then asserts the live schema back against the same dict.

### Demo Command
```bash
docker compose -f docker-compose.test.yml up -d test-qdrant && \
  vsir doctor --create-collection && vsir doctor
```
The reviewer sees the created collection's vector configs and text-index parameters printed, then
`vsir doctor` passing its schema assertion against that live collection. Dropping the `text` payload
index and re-running `vsir doctor` prints a named refusal.

### Deliverables (files)
- `backend/vsir/core/record.py` — **ported** from `impl/app/pagemodel.py` (**record shape only** —
  none of the identifier machinery).
- `backend/vsir/core/ids.py` — **ported** from `impl/app/pagemodel.py::make_page_id`.
- `backend/vsir/core/indexed.py` — **written**, net new: the `INDEXED` dict plus the collection and
  text-index creation of Spec §5.5.
- `backend/vsir/doctor.py` — **extended**: the `--create-collection` flag and the live-schema assertion.
- `backend/tests/unit/test_ids.py`, `test_record.py` — **written**.
- `backend/tests/api/test_indexed_collection.py` — **written**.

### Requirements
- Read `impl/app/pagemodel.py` first, and `impl/pipeline-guide/METADATA-CONTRACT.md` (Spec §20).
- Spec §5.1 identifiers: `page_id = "{doc_id}@{revision}#p{NNN}"` (NNN zero-padded to 3+),
  `section_id = "…#s{NNN}"`, `series_id`, `point_id = uuid5(NAMESPACE_URL, page_id)`,
  `run_id` = ULID.
- Spec §5.3 record: facets · `text` + `vlm_codes` · three vectors (`dense`, `lexical`, `captions`) ·
  nested `content` (returned, never filtered) · provenance. `section_id` and `series_id` are
  **keyword arrays** — a single scalar per page is how F8 happens. **There is no `image_path`.**
- Spec §5.4: one `INDEXED` dict with three jobs — creates, gates, is asserted at boot (I6). Scope
  keys = `INDEXED` minus `text` and `vlm_codes`.
- Spec §5.5: `qm.TextIndexParams(type="text", tokenizer=WORD, lowercase=True, phrase_matching=True,
  min_token_len=1)` on both `text` and `vlm_codes`; sparse configs with `Modifier.IDF` for `lexical`
  and `captions`; the collection name carries the dim (`pages_1536`).
- **Do not port** (Spec §2.4): `SCHEMA_CARD`, `IdClass`, `classify()`, `normalise()`, `Identifier`,
  `backed_keys()`, `entity_keys_for()`.
- Spec §20.1 register items closed here: **A5** (`image_path` is broken — there is no such field);
  **B1/B4** (provenance is a first-class field group).

### Invariants Enforced
- **I6** — one module-level `INDEXED` dict creates the payload indexes, gates every filter and is asserted against the live collection at boot.

### Failure Rows Closed
- None (F10 is closed by U004's filter gate, which consumes this dict).

### Dependencies
- **Depends On:** [U001, U002]
- **Enables:** [U004, U007]
- **External:** Qdrant 1.19.0 (`phrase_matching` requires it).

### Acceptance Criteria
- [ ] `ids.page_id("TC1E-SF", "1.3", 1)` returns `"TC1E-SF@1.3#p001"`, and is byte-identical across two calls.
- [ ] `ids.point_id(page_id)` equals `uuid5(NAMESPACE_URL, page_id)` and is stable across processes.
- [ ] `INDEXED` has exactly the sixteen keys of Spec §5.4 with the stated types.
- [ ] The created collection reports a text payload index on `text` **and** on `vlm_codes`, each with `phrase_matching == True`, `tokenizer == WORD`, `lowercase == True`, `min_token_len == 1`.
- [ ] The created collection reports sparse vectors `lexical` and `captions`, both with `Modifier.IDF`, and a `dense` vector with `Distance.COSINE`.
- [ ] The collection name contains the configured `dim` (e.g. `pages_1536`).
- [ ] `PageRecord(**minimal).to_payload()` → `.from_payload()` round-trips with no field loss, and `"image_path" not in payload`.
- [ ] `scope_keys()` equals `set(INDEXED) - {"text", "vlm_codes"}`.
- [ ] Dropping the `text` payload index and re-running `vsir doctor` exits non-zero naming that index.

### Test Plan
**Levels:** [L0, L2]
**Commands:** `bash scripts/test-unit.sh -k "ids or record"` · `bash scripts/test-api.sh -k indexed_collection`
**Fixtures/Stubs:** ephemeral Qdrant; records built inline; no VLM.
**Edge Cases:** a page straddling two sections carries both `section_id` values; a dropped payload index; a dim change producing a different collection name.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the port drags `impl`'s identifier grammar across with the record shape. **Mitigation:** the U002 conformance greps fail the build on `SCHEMA_CARD`, `IdClass`, `entity_keys`, `classify(`.
- **Risk:** `INDEXED` and the live collection drift apart over later milestones. **Mitigation:** the boot assertion is the single check, run by `vsir doctor` and by server start (U014).

### Rollback Plan
N/A — no data is published by this unit; the collection it creates is ephemeral and carries no `is_current=True` points.

---

## Unit: Tokenisation, variants, the exact filter, and both envelopes (ID: U004)

**Status:** 🔵 Not Started
**Milestone:** M1
**Priority:** P0-Critical
**Type:** core
**Size Estimate:** Large
**Spend:** none

### Goal
Build the single exact-match code path, the six-value status enum, both response envelope families
with every hit model, and the §7.3 cap validators — and port the ranks-only fusion machinery.

### Working Deliverable
`vsir demo exact --synthetic --only primitives` — prints, for a fixed corpus of labels, the three
variants generated, the Qdrant filter built, the differential `tok()`-vs-Qdrant comparison, and each
cap validator's typed 400.

### Demo Command
```bash
vsir demo exact --synthetic --only primitives
```
The reviewer sees each label's three whitespace variants (character-identical to the label), the
`should[must[MatchPhrase…]]` filter that `exact_filter` builds, a table showing `tok()` agreeing with
Qdrant's WORD tokenizer on every label, and one line per §7.3 bound showing its error code.

### Deliverables (files)
- `backend/vsir/core/tok.py`, `core/variants.py`, `core/exact.py` — **written**, net new (the phrase surface).
- `backend/vsir/core/status.py` — **written**, net new: the six-value absence enum.
- `backend/vsir/serve/envelope.py` — **ported with changes** from `impl/app/api_models.py`: re-shaped
  into `SearchResponse[HitT]` (Family A) and `ToolEnvelope[ResultT]` (Family B), with **every
  `entity_keys` field deleted**; `DocHit`, `SectionHit`, `PageHit`, `LookupHit`, `ResolveHit`,
  `ImageRef`, `Preview`, `NextMoves`, `ScopeStats`, `Provenance`.
- `backend/vsir/serve/caps.py` — **written**, net new: the §7.3 validators as typed 400s.
- `backend/vsir/ingest/sparse.py` — **ported as-is** from `impl/app/sparse.py` (D2), keeping `dedupe()`.
- `backend/vsir/serve/tools/skim.py` — **ported** from `impl/app/retrieve.py::rrf` — **the `rrf()`
  function only** at this milestone (ranks-only, `rrf_k=60`); the three skim rungs arrive at M4/M5.
- `backend/tests/unit/test_tok.py`, `test_variants.py`, `test_exact.py`, `test_status.py`,
  `test_envelope.py`, `test_caps.py`, `test_rrf.py`, `test_sparse.py` — **written**.

### Requirements
- Read `impl/app/sparse.py`, `impl/app/retrieve.py` (`rrf`, `decompose`) and `impl/app/api_models.py` first.
- Spec §5.6: `tok()` **mirrors Qdrant's WORD tokenizer** — lowercase, punctuation is a separator,
  min length 1. **Do not port `impl`'s `TOKEN_RE`** (it keeps `84-5140.0020` as one token) or
  `token_set()`'s adjacent-token joins — both existed only for the deleted `entity_keys` gate.
  An **L0 differential test** asserts `tok()` and Qdrant agree on a fixed corpus of labels.
- Spec §5.6: `variants(label)` returns exactly three spellings of the **same characters** — as given,
  whitespace removed, a space at every letter↔digit boundary. `exact_filter(label, scope)` is the
  **only** exact-match code path: `should[ must[ MatchPhrase(text, v), *scope ] for v in variants ]`.
- Spec §5.2 permitted normalisation: whitespace collapsing and letter↔digit boundary spacing inside
  `variants()` only — proved character-preserving by the I3 property test. Everything else banned.
- Spec §7.1: the two families; the `empty_is_never_ok` validator; `total = count(exact=True)` (the
  set size, not `len(hits)`); `WEAK_ABS = 20` as a **server constant**, with
  `weak = needs_scope = total > max(WEAK_ABS, 0.25 * scope_stats.pages)` — independent of any
  caller-supplied bound. Every hit model's fields exactly as listed. `ImageRef`/`Preview` are
  **references, never bytes**; `bytes_b64` exists only on `fetch`.
- Spec §7.3: `read_page_cap_exceeded`, `fetch_budget_exceeded {limit, requested}`, `dpi_not_allowed`
  (dpi ∈ {36, 72, 150, 220, 300, 400}), `dpi_requires_region` (dpi > 220), `filter_unknown_key {keys}`,
  `429 budget_exhausted`. **Each is a typed 400, never a clamp, never a silent truncation.**
- Spec §7.6: no field named `score` anywhere in a response model; `rank` / `best_rank` are ordinals
  and are required.
- Spec §3 D2: keep `rrf()` ranks-only at `rrf_k=60`, weights `page 1.0 · lexical 1.0 · captions 0.4`.
- Spec §20.1 register item closed here: **D3** (the `captions` surface was declared and weighted but
  never written — `sparse.dedupe(against=text)` is ported here so U010 can populate it).

### Invariants Enforced
- **I3** — one `exact_filter`; no `MatchText` in `serve/`; a property test proves every variant equals the label with whitespace stripped, so `K73` can never yield `K78`.
- **I5** — the `SearchResponse` validator makes an empty `ok` impossible in Family A.

### Failure Rows Closed
- **F10** (silent recall loss) — a filter key absent from `INDEXED` is a typed `filter_unknown_key` 400, never a slow scan — `test_unknown_scope_key_returns_typed_400` (L0).

### Dependencies
- **Depends On:** [U003]
- **Enables:** [U005, U006, U010]
- **External:** Qdrant 1.19.0 (for the differential tokenizer test only).

### Acceptance Criteria
- [ ] For a fixed corpus of ≥40 labels drawn from the corpus's shapes (`SF 1.1A`, `84-5140.0020`, `X20SI4100`, `SI3`, `K158`, `0020`), `tok(label) == qdrant_word_tokens(label)` for every label.
- [ ] `tok("84-5140.0020") == ["84", "5140", "0020"]` — **not** one token.
- [ ] `len(variants(label)) == 3` and, for every label, `{v.replace(" ", "") for v in variants(label)} == {label.replace(" ", "")}` — the property test for I3.
- [ ] `exact_filter` is the only call site of `MatchPhrase` in the codebase (asserted by an AST scan, not a grep).
- [ ] `len(list(core.status.Status)) == 6` and the members are exactly `ok`, `not_found`, `not_searchable`, `out_of_scope`, `found_only_in_superseded`, `error`.
- [ ] `SearchResponse(status="ok", hits=[], unverified_hits=[])` raises a validation error; the same with `status="not_found"` validates.
- [ ] `weak` is `True` for `total=21, scope_stats.pages=80` at `cap=5` **and** at `cap=200` — it does not move with `cap`.
- [ ] `ToolEnvelope(status="ok", result=VerifyResult({...all absent...}))` validates — a verify where every claim is absent is `ok`.
- [ ] No Pydantic model in `serve/envelope.py` declares a field named `score`; `rank` and `best_rank` are present and integer.
- [ ] Cap validators: 4 pages → `read_page_cap_exceeded`; 6 pages → `fetch_budget_exceeded {limit: 5, requested: 6}`; `dpi=100` → `dpi_not_allowed`; `dpi=300, region=None` → `dpi_requires_region`, and the same with a region passes; `scope={"bogus": 1}` → `filter_unknown_key {keys: ["bogus"]}`.
- [ ] `rrf()` reproduces a hand-computed `Σ w/(k+rank)` for a fixed pair of rank lists at `k=60`, and no similarity score enters the arithmetic (asserted on the function signature and on its inputs).

### Test Plan
**Levels:** [L0]
**Commands:** `bash scripts/test-unit.sh -k "tok or variants or exact or status or envelope or caps or rrf or sparse"`
**Fixtures/Stubs:** an ephemeral Qdrant for the tokenizer differential test only; otherwise pure.
**Edge Cases:** `min_token_len=1` labels (`SI3`, `84`, `0020`); a label that is already whitespace-free (variants collapse to fewer than three distinct strings — assert de-duplication, not a crash); `total == cap` exactly; `scope_stats.pages == 0`.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** `tok()` and Qdrant's tokenizer drift on a Qdrant upgrade, silently making `verify` reason about a different token set than the index matched. **Mitigation:** the differential test runs at L0 on every commit against the pinned `qdrant/qdrant:v1.19.0`; a Qdrant bump therefore fails the build.
- **Risk:** a later contributor adds a `score` field for debugging. **Mitigation:** the §12.5 grep in U002 fails the build.

### Rollback Plan
- **If this unit must be reverted:** the envelope models are a contract change. Pin the tool contract by keeping `serve/envelope.py`'s previous module version importable under the prior `schema_version` and stamp responses with it; no index state is touched, so no collection or alias action is required.

---

## Unit: Synthetic exact surface, `lookup`, and `vsir demo exact` (ID: U005)

**Status:** 🔵 Not Started
**Milestone:** M1
**Priority:** P0-Critical
**Type:** core
**Size Estimate:** Medium
**Spend:** none

### Goal
Seed an ephemeral Qdrant with hand-written page text — no PDF, no VLM — and prove the exact surface
end to end, including that a model-claimed code the text does not contain is unfindable.

### Working Deliverable
`vsir demo exact --synthetic`, the M1 milestone demo: it seeds the pages, runs each acceptance
assertion, and prints its verdict.

### Demo Command
```bash
vsir demo exact --synthetic
```
The reviewer sees one line per assertion with PASS/FAIL: `lookup("SF 1.1A")` → 1 hit;
the compact-label variants all landing on the same page; `lookup("K999")` → `not_found`; and `K999`
appearing only in `unverified_hits` when `include_unverified=True`.

### Deliverables (files)
- `data/fixtures/synthetic_pages/*.json` — **written**: four hand-written page records —
  (1) text containing the literal `SF 1.1A`; (2) text with the tokens `sf`, `1`, `1a` scattered
  non-adjacently; (3) text printing `SF121.1)`; (4) a page whose `content.codes` claims `K999` that
  its `text` does not contain.
- `backend/vsir/serve/tools/lookup.py` — **ported with changes** from `impl/app/retrieve.py::lookup`,
  **rewritten as a phrase filter** (C2). At M1 this is a pure function; U015 adds the HTTP/MCP wrapper.
- `backend/vsir/core/observed_tokens.py` — **written**, net new: the observed-token inventory of
  Spec §6.8, built here from the seeded pages so `present_instead` works before any PDF exists.
- `backend/vsir/cli.py` — **extended**: `demo exact --synthetic`.
- `backend/tests/unit/test_lookup_pure.py`, `test_observed_tokens.py` — **written**.
- `backend/tests/api/test_acceptance_synthetic.py` — **written**.

### Requirements
- Read `impl/app/retrieve.py::lookup` first — note that `impl` has **no text index at all**; exact
  lookup there is `entity_keys` + `MatchValue`, so this is a rewrite with no legacy call site (C2).
- Spec §7.2.2: exact, phrase-only, **a set not a ranking**. `total = count(exact=True)`, then
  `scroll` to `cap`; `cap` bounds the returned page of the set and sets `capped`, and **never**
  affects `weak`. `include_unverified=True` repeats the query against `vlm_codes` and returns those
  in `unverified_hits` with `verified: false` — **never merged** into `hits`.
- Spec §1.2 / I2: `text` is written by the probe and by nothing else, so a hallucinated code cannot
  be in the exact surface. At M1 the probe does not exist yet, so I2's M1 half is the *behavioural*
  assertion (`lookup("K999")` → `not_found`) plus the `get_text(` conformance grep; the
  "probe is the only writer" structural assertion lands with U009's L1 check.
- Spec §6.8: the observed-token inventory is built from **a token containing at least one digit**,
  and that heuristic is **display-only** — unreachable from `lookup` and `verify`, enforced by module
  boundary and by a test asserting `present_instead` can never appear in `hits`.
- Spec §13 M1: `lookup` runs against an ephemeral Qdrant seeded with hand-written page text; no PDF.

### Invariants Enforced
- **I2 (M1 half)** — the exact surface contains only extracted text: a code claimed in `content.codes` but absent from `text` is `not_found`, and reachable only through `unverified_hits`.

### Failure Rows Closed
- **F1** (`lookup` returns the wrong page as exact) — I3 phrase-only — `test_lookup_sf_1_1a_returns_exactly_one` (L2).
- **F3** (abstains on a label that *is* printed) — I3 variants — `test_all_eight_compact_labels_found` (L2).
- **F14** (a model-invented code becomes findable) — I2 — `test_hallucinated_code_never_findable` (L2).

### Dependencies
- **Depends On:** [U004]
- **Enables:** [U006, U015]
- **External:** ephemeral Qdrant.

### Acceptance Criteria
- [ ] `lookup("SF 1.1A")` against the four seeded pages returns `total == 1` and `len(hits) == 1`, and the hit is page (1) — page (2), whose tokens `sf`/`1`/`1a` are all present but not adjacent, is **not** returned.
- [ ] All eight compact spellings of the M1 labels resolve to their printed page (F3), including `SF121.1)` via the letter↔digit-boundary variant.
- [ ] `lookup("K999")` returns `status == "not_found"` and `hits == []`.
- [ ] `lookup("K999", include_unverified=True)` returns `hits == []` and `len(unverified_hits) == 1` with `unverified_hits[0].verified is False`; the two lists are never merged.
- [ ] `lookup("3")` unscoped over the seeded pages returns `weak is True` and `needs_scope is True` at `cap=5` and at `cap=200`.
- [ ] The observed-token inventory built from the four pages contains every digit-bearing token in their `text` and nothing that is not in `text`.
- [ ] An import-graph assertion proves `serve/tools/lookup.py` does not import `core/observed_tokens.py` — `present_instead` is structurally unable to affect `lookup`.
- [ ] `vsir demo exact --synthetic` exits 0 and prints one PASS line per assertion above.

### Test Plan
**Levels:** [L0, L2]
**Commands:** `bash scripts/test-unit.sh -k "lookup_pure or observed_tokens"` · `bash scripts/test-api.sh -k acceptance_synthetic`
**Fixtures/Stubs:** `data/fixtures/synthetic_pages/` (produced by **this unit**); ephemeral Qdrant; no VLM.
**Edge Cases:** a page whose tokens match but whose phrase does not (page 2 — this is F1's whole point); `include_unverified` on a page with no `vlm_codes`; `cap` smaller than `total` setting `capped: true` without moving `weak`.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** hand-written fixture text is unrepresentative and the surface passes here but fails on real extraction. **Mitigation:** the same assertions re-run against the ported `impl` responses (U012) and the real fixture (U013) — Spec §12.1 requires all three.
- **Risk:** `present_instead` leaks into `hits` through a convenience import. **Mitigation:** the import-graph assertion above, plus the module-boundary rule of Spec §6.8.

### Rollback Plan
- **If this unit must be reverted:** `lookup`'s signature is a tool contract. Revert behind the previous `schema_version` stamp; the seeded collection is ephemeral and holds no published points, so no alias swap or point deletion is needed.

---

## Unit: `verify_claims`, `present_instead`, and the L3 abstention eval (ID: U006)

**Status:** 🔵 Not Started
**Milestone:** M1
**Priority:** P0-Critical
**Type:** core
**Size Estimate:** Medium
**Spend:** none

### Goal
Implement per-`(claim, page)` verification with the three-state vocabulary, the capped prefix-lookup
`present_instead`, and the adversarial near-miss eval that runs in CI from M1 onward.

### Working Deliverable
`vsir demo exact --synthetic --verify <claims>` plus the L3 abstention eval wired into
`scripts/test-api.sh` and CI.

### Demo Command
```bash
vsir demo exact --synthetic --verify "SF 1.1A,K73,SF 9.9" && \
  bash scripts/test-api.sh -k near_miss
```
The reviewer sees a `VerifyResult` map — `SF 1.1A: present`, `K73: absent` with a
`present_instead` list labelled *different part*, `SF 9.9: unverifiable` with `reason: no_text` —
followed by the 100-case near-miss eval reporting 100/100.

### Deliverables (files)
- `backend/vsir/core/verify.py` — **written**, net new: `verify_claims(claims, page_ids)`, per
  `(claim, page)`.
- `backend/vsir/core/present_instead.py` — **written**, net new: the capped prefix lookup over
  `core/observed_tokens.py`.
- `backend/vsir/core/nearmiss.py` — **written**, net new: the §12.4 generator.
- `backend/vsir/cli.py` — **extended**: the `--verify` flag on `demo exact`.
- `backend/tests/unit/test_verify_claims.py`, `test_present_instead.py`, `test_nearmiss.py` — **written**.
- `backend/tests/api/test_near_miss_codes_never_answer.py` — **written**, the §12.4 L3 eval.

### Requirements
- Spec §7.2.4: per `(claim, page)`, **not** per claim — a draft citing `p001–p002` must not let a code
  from the neighbouring page through (this is the mechanism I8 later gates on; the tool wrapper is
  U015's, per Spec §13 M1).
- Three states only — `present | absent | unverifiable` — the same vocabulary `read` reuses (§7.2.6).
  **Collapsing `unverifiable` into `absent`** tells the agent *"that code is not on the page"* about a
  page it could not look at, and is forbidden.
- `present_instead` is a **prefix lookup over observed tokens, capped at 5, labelled "different part"
  — never a distance, never a nearest match** (C7, F16).
- Spec §5.7: `text_trust ∈ {ok, degraded, untrusted, no_text}`; both `untrusted` and `no_text` pages
  make `verify` return `unverifiable`.
- Spec §12.4: `near_misses(n=100)` mutates **one character** of codes taken from the observed-token
  inventory of whatever corpus is indexed, so it never needs the 8,414-pair list to exist (OQ-4 is
  resolved by design). The eval asserts `hits == []`, `status in ("not_found", "not_searchable")`,
  and that no `present_instead` value equals the fake.
- Spec §7.6: no fuzzy matching — no edit-distance or similarity library may enter `requirements*.txt`
  (U002's grep enforces it).

### Invariants Enforced
- None directly (I8's mechanism is built here but is asserted at M6 by U022, per Spec §9).

### Failure Rows Closed
- **F2 (core half)** (`verify` confirms a code that is not on the page) — the one `exact_filter` — `test_verify_claims_sf_1_1a_absent_on_p008` (L0).
- **F16** (a near-miss code presented as the answer) — capped prefix lookup, never a distance — `test_k73_absent_with_present_instead_k78` (L0).

### Dependencies
- **Depends On:** [U004, U005]
- **Enables:** [U015, U020, U022]
- **External:** ephemeral Qdrant.

### Acceptance Criteria
- [ ] `verify_claims(["SF 1.1A"], [p_scattered])` returns `{"SF 1.1A": {"status": "absent"}}` — the tokens are present, the phrase is not.
- [ ] `verify_claims(["K73"], [p_k78])` returns `status == "absent"` with `present_instead == ["K78"]` and `len(present_instead) <= 5`.
- [ ] `verify_claims(["SF 9.9"], [p_no_text])` returns `status == "unverifiable"` with `reason == "no_text"` — never `absent`.
- [ ] `verify_claims(["K158"], [p001, p002])` returns a per-`(claim, page)` result: `present` on the page whose text has it, `absent` on the other — the two are not collapsed.
- [ ] A `ToolEnvelope` whose `VerifyResult` is entirely `absent` verdicts still has `status == "ok"`.
- [ ] `len(near_misses(n=100)) == 100`, every element differs from its source by exactly one character, and every source came from the observed-token inventory.
- [ ] `test_near_miss_codes_never_answer` passes on all 100: `hits == []`, `status in ("not_found","not_searchable")`, and `fake not in present_instead` for every claim.
- [ ] `present_instead` never returns a value it did not find by **prefix** — asserted by a property test over the inventory.
- [ ] The L3 eval is registered in CI and runs on every commit from M1 onward.

### Test Plan
**Levels:** [L0, L3]
**Commands:** `bash scripts/test-unit.sh -k "verify_claims or present_instead or nearmiss"` · `bash scripts/test-api.sh -k near_miss`
**Fixtures/Stubs:** `data/fixtures/synthetic_pages/` (produced by U005); ephemeral Qdrant; no VLM — `near_misses()` derives purely from the local inventory.
**Edge Cases:** a claim on a page with `text_trust == "untrusted"` → `unverifiable`; a claim whose prefix matches more than 5 tokens (assert the cap); an empty claim list.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** `present_instead` is quietly upgraded to a similarity ranking by a well-meaning contributor. **Mitigation:** Spec §12.5's fuzzy-library grep plus the prefix-only property test above.
- **Risk (R2, Spec §18):** a scanned page's codes are `unverifiable` forever. **Mitigation:** that is the deliverable, not a gap — the badge is what M7 renders and what §11.2 requires.

### Rollback Plan
- **If this unit must be reverted:** `verify`'s three-state verdict is a tool contract. Revert behind the previous `schema_version`; no index state is affected.

---

## Unit: Manifest, probe, render, S1 facts, and the windowing ladder (ID: U007)

**Status:** 🔵 Not Started
**Milestone:** M2a
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Large
**Spend:** none

### Goal
Port ingestion steps 01–05 and generate the checked-in 3-window synthetic PDF that carries the
off-by-one trap and the crop trap every later M2a assertion depends on.

### Working Deliverable
`vsir ingest <pdf> --vlm stub --until window` — runs steps 01–05 and prints the manifest, the
per-page probe result and the window plan.

### Demo Command
```bash
vsir ingest data/source/synthetic_3window.pdf --vlm stub --until window
```
The reviewer sees the manifest facets, a per-page table of `has_text` / `content_hash` /
`printed label`, the three-window plan with each window's `extract_key`, and a line confirming that
the crop-trap page's extracted `text` contains the full label despite the crop.

### Deliverables (files)
- `backend/vsir/ingest/manifest.py` — **ported with changes** from `impl/app/pipeline.py` (step 01 only).
- `backend/vsir/ingest/probe.py` — **ported** from `impl/app/textlayer.py::probe / page_texts /
  content_hash`, keeping `Probe.s2_input_mode` and **layout mode** in `page_texts()` (default order
  flattens the safety-list column structure). **Do not port** `gate()`, `backs()`,
  `identifiers_from_text()` or `token_set()`'s adjacent-token joins.
- `backend/vsir/ingest/render.py` — **ported as-is** from `impl/app/render.py`.
- `backend/vsir/ingest/window.py` — **ported** from `impl/app/windows.py` (windowing + `extract_key`),
  **plus the bisection ladder written net new** (F13).
- `data/source/synthetic_3window.pdf` + the generator script that produces it — **written**, checked in.
- `backend/vsir/cli.py` — **extended**: `ingest <pdf> [--vlm stub] [--until <step>]`.
- `backend/tests/unit/test_manifest.py`, `test_probe.py`, `test_render.py`, `test_window.py` — **written**.

### Requirements
- Read `impl/app/textlayer.py`, `impl/app/render.py`, `impl/app/windows.py` first, and the guides
  `impl/pipeline-guide/01-entry.md`, `02-probe-and-render.md`, `03-document-facts.md`,
  `04-windowing-and-keys.md` (Spec §20).
- Spec §6.1 step 01: facets from filename / metadata / uploader only — **no content-sniffing grammar**.
- Spec §6.1 step 02: the probe is **the only writer of `text`** (I2), and text is always taken from
  the **full page, never a crop** (F15). Extract **unconditionally** — Spec §20.1 **A1** records that
  `impl` throws text away on mixed documents via a one-line `else`; that defect must not be ported.
- Spec §6.1 step 03: render at **dpi 220** (the raster S2 sees; part of `extract_key`), cached by page
  content hash. Rasters are **never persisted** (Spec §4.2, §15 Factor VI) — Spec §20.1 **E3**.
  The `dpi_index = 150` raster consumed by the dense vector is rendered by U010.
- Spec §6.1 step 04: S1 document facts from the doc head rasters, picking the window ladder; prompt
  generalised, no per-corpus grammar. Cached by `facts_key` (Spec §6.3) — Spec §20.1 **B2**: `impl`
  does not cache S1, so every re-run re-bills it and can silently re-pick a different ladder.
- Spec §6.2: target 30 pages per window; on `MAX_TOKENS`, a truncated or schema-invalid response, or
  an offset failure — **bisect and re-bill; never pad, never offset-guess, never accept a partial
  window** (F13). A single page still over budget fails typed `window_unsplittable`.
  **v1 implements Level 0/1 plus bisection only**; a document needing Level 2 must fail typed
  `ladder_level_2_required` naming the document (the check is defined here; U025 exercises it).
- Spec §6.4: `abs_page = window.start + page_index - 1`; the two independent checks are implemented
  in U009's derivation and gated by U011 — this unit provides the window boundaries they use.

### Invariants Enforced
- None asserted here (I4 is asserted by U011 per Spec §9; this unit supplies its inputs).

### Failure Rows Closed
- **F13** (a window truncates and loses 30 pages) — the output-budget ladder; `MAX_TOKENS` → bisect — `test_oversized_window_bisects` (L1).
- **F15** (a code is invisible because it was cropped away) — `text` always from the full page — `test_crop_trap_full_text_extracted` (L1).

### Dependencies
- **Depends On:** [U001, U003]
- **Enables:** [U008, U018]
- **External:** PyMuPDF 1.28.2 (pinned exactly; recorded in `probe_version` — F15).

### Acceptance Criteria
- [ ] `manifest.build(synthetic_3window.pdf)` returns `doc_id`, `revision`, `doc_type`, `subjects`, `tags` derived only from filename/metadata/uploader, and an AST scan finds no regex taxonomy or keyword list in `manifest.py`.
- [ ] `probe.run(pdf)` returns `text`, `has_text`, `page_count` and `probe_version` for **every** page — including pages of a mixed document where `impl` would have skipped extraction (A1).
- [ ] `has_text == False` implies `text_trust == "no_text"` for that page.
- [ ] On the crop-trap page, the extracted `text` contains the full label even though the rendered raster crops it.
- [ ] `window.plan(...)` returns exactly 3 windows for `synthetic_3window.pdf`, each with a distinct `extract_key`.
- [ ] A window whose stub response reports `MAX_TOKENS` bisects into two windows and re-bills; the resulting page set is the union of the original with no gaps and no duplicates.
- [ ] A single page that still exceeds budget raises typed `window_unsplittable`.
- [ ] A document marked as needing Level 2 raises typed `ladder_level_2_required` naming the document — never a blind cut.
- [ ] `facts_key` is stable across two runs on the same PDF and changes when `VSIR_PROMPT_VERSION` changes.
- [ ] The conformance grep confirms `get_text(` appears only in `backend/vsir/ingest/probe.py`.
- [ ] No raster is written to the filesystem during the run (asserted by a filesystem-write spy over the process).

### Test Plan
**Levels:** [L0, L1, conformance]
**Commands:** `bash scripts/test-unit.sh -k "manifest or probe or render or window"`
**Fixtures/Stubs:** `data/source/synthetic_3window.pdf` and `data/fixtures/synthetic_3window/` (produced by **this unit**); stub VLM for the S1 facts call; no Qdrant needed.
**Edge Cases:** a zero-text page; a mixed document (A1); `MAX_TOKENS` bisection; `window_unsplittable`; `ladder_level_2_required`.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk (R3, Spec §18):** PyMuPDF is the single point of truth for exact search; a version quirk silently blinds `lookup`. **Mitigation:** the version is pinned exactly and recorded in `probe_version` on every record; a bump re-runs the L1 crop/off-by-one fixtures.
- **Risk:** the generated PDF's traps are too artificial to catch real off-by-one bugs. **Mitigation:** the same offset proof re-runs at L1 against the ported real `impl` responses (U012) and the frozen `TC1E-SF` fixture (U013) — Spec §12.1.

### Rollback Plan
- **If this unit must be reverted:** no points are written by steps 01–05, so nothing is queryable and no retirement is needed. Delete any `vsir_runs` control points for the affected `run_id` by filter; the index is untouched.

---

## Unit: The VLM boundary, cache keys, replay mode, and S2 extraction (ID: U008)

**Status:** 🔵 Not Started
**Milestone:** M2a
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Large
**Spend:** none

### Goal
Build the VLM abstraction — real client, stub, content-addressable cache and prompts — and step 06's
S2 extraction under the new schema, with stub-vs-real chosen by **config, never a code branch**.

### Working Deliverable
`vsir ingest <pdf> --vlm stub --until extract` and the replay contract: a fixture miss is a typed
`fixture_miss`, never a live call.

### Demo Command
```bash
VSIR_VLM=stub VSIR_FIXTURE=data/fixtures/synthetic_3window \
  vsir ingest data/source/synthetic_3window.pdf --until extract && \
VSIR_PROMPT_VERSION=v2 VSIR_VLM=stub VSIR_FIXTURE=data/fixtures/synthetic_3window \
  vsir ingest data/source/synthetic_3window.pdf --until extract; echo "exit=$?"
```
The reviewer sees the raw `WindowOut` JSON per window from the stub, then — with the prompt version
bumped — a different `extract_key` and a typed `fixture_miss` rather than a live call.

### Deliverables (files)
- `backend/vsir/vlm/client.py` — **ported with changes** from `impl/app/segment.py`'s Gemini calls:
  the pinned-model wrapper, token-bucket rate limiter and exponential backoff.
- `backend/vsir/vlm/stub.py` — **written**, net new: the fixture-replay backend, selected by
  `VSIR_VLM=stub`.
- `backend/vsir/vlm/cache.py` — **written**, net new: the four keys of Spec §6.3.
- `backend/vsir/vlm/prompts/s1.md`, `s2.md` — **written**, net new; versioned by `VSIR_PROMPT_VERSION`.
- `backend/vsir/ingest/extract.py` — **rewritten** from `impl/app/segment.py`: the S2 schema of
  Spec §5.2 (`Summary`, `SectionRef`, `PageOut`, `WindowOut`).
- `backend/tests/unit/test_extract_schema.py`, `test_cache_keys.py`, `test_replay.py` — **written**.

### Requirements
- Read `impl/app/segment.py` first, and `impl/pipeline-guide/05-extraction.md` +
  `impl/SEGMENTATION.md` (Spec §20). ⚠ Those guides document the **old schema**, which Spec §5.2
  supersedes: `units[]` → `sections[]`, `identifiers[]` → `codes[]`, plus `summaries` and `topics`.
- Spec §5.2 **Prohibited**: any identifier grammar, classification enum, regex taxonomy or per-corpus
  keyword list anywhere in extraction or derivation. `sections[]` carries **presence per page, never
  extent** — that is what lets stitching survive window folds. Drop `impl`'s `_is_safety()` keyword
  list, `STRICT_KINDS`, `key_for_unit`, `Unit.kind`, `attrs`, and `refs[]`.
- Spec §5.2 binding prompt rule: summaries are *"2–3 sentences on what is SPECIFIC to this page. Do
  not describe the document generally."*
- Spec §6.3 keys: `facts_key`, `extract_key`, `read_key`, `embed_key` exactly as specified;
  `VSIR_VLM_TIER ∈ {batch, standard}` is **not** part of `extract_key` because the tier does not
  change the output. Batch API (50% discount) for full-corpus runs; standard for prompt tuning and
  single-document ingest.
- Spec §3 D10 replay mode: `VSIR_VLM=stub` + `VSIR_FIXTURE=<dir>` serves both S2 and `read` from
  frozen responses keyed by exactly those hashes. A key not in the fixture is a typed `fixture_miss`
  — **never** a live call and never a fabricated response.
- Spec §15 Factor X and §15.2: the stub is selected by **config**, never by a code branch or a
  test-only import. `if TESTING` inside `backend/vsir/**` is banned by U002's grep.
- Spec §20.1 register items closed here: **B6** (pinned model, re-verified at the client),
  **B2** (S1 caching via `facts_key`).

### Invariants Enforced
- None asserted here.

### Failure Rows Closed
- **F11 (key half)** — the cache key includes the resolved model id and prompt version, so a cache cannot serve output from a different model or prompt — `test_extract_key_changes_with_prompt_version` (L0).

### Dependencies
- **Depends On:** [U007]
- **Enables:** [U009, U020]
- **External:** `google-genai==2.22.0` (scaffolded, not called at M2a); the stub needs no network.

### Acceptance Criteria
- [ ] `extract_key` changes when `VSIR_PROMPT_VERSION` changes, when the resolved model id changes, when the dpi changes, or when any page image hash changes — and is identical otherwise.
- [ ] `extract_key` is **unchanged** when only `VSIR_VLM_TIER` flips between `batch` and `standard`.
- [ ] `read_key` for the same pages but a different question differs (the mechanism F19 relies on; F19 itself is proved at M5).
- [ ] With `VSIR_VLM=stub`, a network spy records **zero** outbound HTTP calls across a full `--until extract` run.
- [ ] A cache key absent from `VSIR_FIXTURE` raises typed `fixture_miss`; the spy still records zero outbound calls and no response is fabricated.
- [ ] `WindowOut` validates against Spec §5.2 exactly: `page_index` is 1-based **within the excerpt**, `page_kind` is one of the eight listed values, `summaries` has one entry per `lang`, and `codes`/`topics` are lists of strings.
- [ ] An AST scan of `ingest/extract.py` and `vlm/` finds no regex taxonomy, no classification enum and no per-corpus keyword list.
- [ ] An AST scan finds no `if TESTING`-style branch; switching `VSIR_VLM` between `gemini` and `stub` selects the backend through one config lookup with no conditional import.

### Test Plan
**Levels:** [L0, L1]
**Commands:** `bash scripts/test-unit.sh -k "extract_schema or cache_keys or replay"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (produced by U007); stub VLM; no Qdrant.
**Edge Cases:** `fixture_miss`; a schema-invalid stub response triggering U007's bisection; a window whose stub response reports `MAX_TOKENS`; a page with two languages producing two `Summary` entries (D5).

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** frozen fixtures go stale relative to a prompt edit and replay tests pass against a contract a real call would fail. **Mitigation:** the cache key *includes* `prompt_version` and the schema hash, so a prompt edit forces a typed `fixture_miss` rather than a silent stale hit — this is exactly the acceptance criterion above.
- **Risk:** the port drags `impl`'s `-latest` model ids across (`impl/config.yaml` sets `gemini-pro-latest` for both extract and read). **Mitigation:** U001's boot refusal plus U002's grep; the client re-checks at call time.

### Rollback Plan
- **If this unit must be reverted:** no points are written. Purge the affected `extract_key` entries from the cache and delete the run's `vsir_runs` control points by filter; the index is untouched.

---

## Unit: Derivation, health signals, label attribution, and stitching (ID: U009)

**Status:** 🔵 Not Started
**Milestone:** M2a
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Large
**Spend:** none

### Goal
Turn `WindowOut` plus probe text into page records — with the offset proof, `grounded_rate`, label
precedence and code reattribution — and stitch per-page `sections[]` into sections that survive a
window fold.

### Working Deliverable
`vsir ingest <pdf> --vlm stub --until stitch` — prints the derived page records with `section_id`,
`grounded_rate`, `codes_in_text`, `label_verified` and `moved_from`.

### Demo Command
```bash
vsir ingest data/source/synthetic_3window.pdf --vlm stub --until stitch
```
The reviewer sees a per-page table with `page_id`, `printed_page_no`, `label_verified`,
`grounded_rate`, `codes_in_text`, and — on the reattribution fixture page — a populated `moved_from`
entry; plus a section table showing the straddling section carried across the window fold under one
`section_id`.

### Deliverables (files)
- `backend/vsir/ingest/derive.py` — **rewritten** from `impl/app/segment.py`'s derivation: the
  offset proof, `grounded_rate`, label precedence, code reattribution. **No verification gate.**
- `backend/vsir/core/health.py` — **written**, net new: `grounded_rate`, `text_trust`, `has_text`,
  `searchable_ratio` per Spec §5.7.
- `backend/vsir/ingest/stitch.py` — **ported** from `impl/app/stitch.py`, **retargeted** from units to
  sections, **plus `series_id`** written net new (populated here; asserted across revisions by U025).
- `backend/tests/unit/test_derive_offset.py`, `test_grounded_rate.py`, `test_labels.py`,
  `test_reattribution.py`, `test_stitch.py` — **written**.
- `backend/tests/unit/test_i2_text_provenance.py` — **written**: the §12.5 L1 assertion that for every
  page of the fixture `record.text == probe_text[page_no]`.

### Requirements
- Read `impl/app/segment.py` and `impl/app/stitch.py` first, and the guides
  `impl/pipeline-guide/06-derivation-and-gate.md` and `07-stitch-and-numbering.md` (Spec §20).
  ⚠ **`06-derivation-and-gate.md` documents the DELETED allowlist gate** — read it for the offset and
  the join, **never for the gate**. `07-stitch-and-numbering.md` describes units, not sections, and
  has no `series_id`.
- Spec §6.4 — both checks required: (1) **structural**, `sorted(p.page_index) == list(range(1, window.pages + 1))`;
  (2) **independent observation**, a model-read `printed_page_no` on a page with text must
  phrase-match **this** page's text — if it matches a neighbour's, raise `OffsetError` and bisect.
- Spec §6.5 label precedence: text-layer-confirmed > model-read > interpolated from neighbours;
  `label_verified` and `interpolated` recorded per page; an **ambiguous label resolves to a list,
  never a silent pick** (F5).
- Spec §6.5 code reattribution (F6): a code absent from page *i*'s text but present in an adjacent
  page's text **within the same window** moves to the page whose text contains it, and
  `content.moved_from` records `{code, from_page_id}` on the receiving page. A code grounded in no
  page's text stays put, counts against that page's `grounded_rate`, and never enters the exact
  surface (I2).
- Spec §5.7: `grounded_rate = (len(seen & have) / len(seen) if seen else 1.0) if page.has_text else None`.
  **`None` on `has_text == false`**, and every aggregate over it ignores those pages —
  scoring 0 there would quarantine exactly the scanned documents F4 requires to be
  published-and-unsearchable. `codes_in_text = sorted(seen & have)` — this **is** the old
  `verified_identifiers[]` (C8).
- Spec §6.1 step 08: canonical section key + carry-in across folds (F8); `section_id` and `series_id`
  are keyword arrays so a straddling page carries both.
- **Do not port** the allowlist gate, `class_totality`, `_is_safety()`'s keyword list, or the
  identifier merge (Spec §2.4, §2.5 B).

### Invariants Enforced
- None asserted here (I4 is asserted by U011's gate per Spec §9; this unit implements its two checks).

### Failure Rows Closed
- **F5 (M2a half)** (follows a cross-reference to the wrong page) — label precedence, `label_verified`, ambiguity → list — `test_ambiguous_label_returns_list_never_silent_pick` (L1).
- **F6** (cites a page for a code that is on its neighbour) — per-page `grounded_rate` + reattribution — `test_code_reattributed_records_moved_from` (L1).
- **F8 (stitching half)** (searches a subset believing it searched the chapter) — canonical section key + carry-in across the fold — `test_straddling_section_one_section_id_across_fold` (L1).

### Dependencies
- **Depends On:** [U008]
- **Enables:** [U010]
- **External:** none beyond the fixture.

### Acceptance Criteria
- [ ] The structural offset check rejects a `WindowOut` whose `page_index` set is not exactly `1..window.pages`, raising `OffsetError`.
- [ ] On the synthetic PDF's off-by-one trap, the independent-observation check fires: the model-read `printed_page_no` phrase-matches a neighbour's text, `OffsetError` is raised and the window bisects — **no record is emitted for the shifted window**.
- [ ] `abs_page == window.start + page_index - 1` holds for every emitted page of a passing window.
- [ ] For every page of the fixture, `record.text == probe_text[page_no]` — the L1 assertion Spec §12.5 names as I2's real enforcement.
- [ ] `grounded_rate` is `None` on every `has_text == False` page, and the document median ignores those pages.
- [ ] `grounded_rate == 1.0` on a page whose `codes` is empty and which has text.
- [ ] A code the model reports on page *i*, absent from *i*'s text and present in *i+1*'s text within the same window, appears on *i+1* with `content.moved_from == [{"code": …, "from_page_id": …#p{i}}]`.
- [ ] A code grounded in no page's text stays on its original page, lowers that page's `grounded_rate`, and `lookup` for it returns `not_found`.
- [ ] An ambiguous printed label produces a **list** of candidates with `label_verified == False`, never a single silent pick.
- [ ] A section starting in window 1 and continuing into window 2 carries **one** `section_id` on all its pages, and each straddling page's `section_id` array has both its sections.
- [ ] An AST scan of `derive.py` finds no allowlist gate, no `class_totality`, no keyword list.

### Test Plan
**Levels:** [L0, L1]
**Commands:** `bash scripts/test-unit.sh -k "derive or grounded_rate or labels or reattribution or stitch or i2_text_provenance"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007); from M2b also the ported `impl` responses (U012) and `data/fixtures/TC1E-SF/` (U013) — Spec §12.1 requires the same L1 suite to run against all three.
**Edge Cases:** a page with no text (`grounded_rate is None`); a page with codes but no text; a section straddling a fold; an ambiguous label; the off-by-one trap; a code grounded nowhere.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the guide for step 07 walks a builder straight into re-implementing the deleted allowlist gate. **Mitigation:** stated in Requirements above, and the U002 grep fails on `entity_keys` / `classify(`.
- **Risk:** `grounded_rate = 0.0` is emitted instead of `None` on scanned pages, dragging the median under the §11.1 gate and quarantining the documents F4 needs published. **Mitigation:** an explicit acceptance criterion plus an aggregate test.

### Rollback Plan
- **If this unit must be reverted:** no points are written by steps 07–08. Delete the run's `vsir_runs` control points by `run_id` filter; the index is untouched, so no alias swap is required.

---

## Unit: Embedding, the three surfaces, the fingerprint, and indexing (ID: U010)

**Status:** 🔵 Not Started
**Milestone:** M2a
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Large
**Spend:** none

### Goal
Port the interleaved dense embedding, populate all three vector surfaces, enforce the collection
fingerprint, and upsert one idempotent point per page with `is_current=False`.

### Working Deliverable
`vsir ingest <pdf> --vlm stub --until index` — writes points into the ephemeral collection, all
`is_current=False`, and refuses to upsert on a fingerprint mismatch.

### Demo Command
```bash
vsir ingest data/source/synthetic_3window.pdf --vlm stub --until index && \
VSIR_EMBED_MODEL=some-other-embed-model \
  vsir ingest data/source/synthetic_3window.pdf --vlm stub --until index; echo "exit=$?"
```
The reviewer sees N points upserted with `is_current=false` and their `point_id`s, then — with the
embedding model changed — a named refusal to upsert and a non-zero exit, with no partial write.

### Deliverables (files)
- `backend/vsir/ingest/embed.py` — **ported as-is (load-bearing)** from `impl/app/embedder.py`:
  `embed_page_interleaved`, the retry/backoff, `prepare_image` (`max_edge_px=1568`), the batch-count
  verification and the per-item fallback; **plus `embed_query_image` ported and wired** (D12, consumed
  by U017).
- `backend/vsir/ingest/index.py` — **ported with changes** from `impl/app/segstore.py`: the upsert;
  **added** the two text indexes with `phrase_matching` (via `core/indexed.py`) and the `is_current`
  publish flag; **removed** the `entity_keys` payload index and its `MatchValue` lookup.
- `backend/vsir/ingest/fingerprint.py` — **written**, net new: Spec §6.6.
- `backend/tests/unit/test_embed_composition.py`, `test_fingerprint.py` — **written**.
- `backend/tests/api/test_index_upsert.py` — **written**.

### Requirements
- Read `impl/app/embedder.py`, `impl/app/sparse.py`, `impl/app/segstore.py` first, and the guides
  `impl/pipeline-guide/08-embedding.md` and `09-indexing.md` (Spec §20).
  ⚠ **`09-indexing.md` documents the `entity_keys` index, which C2 deletes** — do not port it.
- Spec §3 D4 / §5.3: **one page → one fused dense vector**. Text parts are **separate `types.Part`s,
  never a concatenated blob**, in this order: doc_title · section_titles · `summaries[]` (one Part
  per language, D5) · topics · codes · `text[:VSIR_EMBED_TEXT_CHARS]` (default 2000) · **the page
  raster @ `dpi_index` (150)**. Three API constraints are load-bearing and must survive the port:
  (1) `task_type` is **rejected** by this model; (2) a **bare list** in `contents` returns ONE
  aggregated embedding, so each page must be wrapped in its own `types.Content` and the returned
  count verified with a per-item fallback; (3) `output_dimensionality` is MRL truncation
  (768 → 1536 → 3072), with the dim recorded in the collection name and in the fingerprint.
  *(See §8 assumption SA-1: Spec §4.2's "Text only" row and §19's C12 row are stale; C12 and D4 win.)*
- Spec §3 D2 / §5.3: `lexical` = sparse raw term frequencies over `text` with `Modifier.IDF`;
  `captions` = sparse over the generated text (`summaries[] + topics`) run through
  `sparse.dedupe(against=text)`, weight 0.4. **The captions surface must actually be written** —
  Spec §20.1 **D3** records that `impl` declares and weights it but never populates it.
- Spec §4.2: `concurrency=8`, `batch_size=8`, `max_edge_px=1568`, `dim ∈ {768, 1536, 3072}`.
- Spec §6.6: the collection stores `{embed_model, dim, distance, composition_version}`; on mismatch
  **refuse to upsert** — a model change is a new collection + full re-embed + alias swap, never an
  in-place mix.
- Spec §6.1 step 10: `point_id = uuid5(page_id)` (I1, asserted by U011); every point written
  `is_current=False`.
- Spec §20.1 register items closed here: **B5** (cache embeddings — via `embed_key`),
  **E7** (re-ingest leaves orphan points — the retirement rule is U011's, but idempotent `point_id`
  is the half that lives here).

### Invariants Enforced
- None asserted here (I1 is asserted by U011's post-publish count per Spec §9).

### Failure Rows Closed
- None.

### Dependencies
- **Depends On:** [U009, U004]
- **Enables:** [U011, U017]
- **External:** `google-genai==2.22.0` (embedding calls are stubbed at M2a and only made for real at M2b/U013); Qdrant 1.19.0.

### Acceptance Criteria
- [ ] Each page is embedded as its **own** `types.Content`; a batch of N pages returns N embeddings, and a returned count `!= N` triggers the per-item fallback rather than accepting an aggregate.
- [ ] `task_type` is never sent to the embedding model (asserted on the request payload).
- [ ] The composed `Content` for a two-language page contains **two separate summary Parts**, not one blended string (D5/D8).
- [ ] The composed `Content`'s last Part is the page raster rendered at `dpi_index == 150`.
- [ ] The `captions` sparse vector is **non-empty** for a page that has summaries or topics, and shares no token with the `lexical` vector that `dedupe(against=text)` should have removed.
- [ ] `dim` appears in the collection name and in the fingerprint; changing `VSIR_EMBED_MODEL` or `dim` makes `fingerprint()` differ.
- [ ] Upserting into a collection whose stored fingerprint differs raises a named refusal, writes **zero** points, and names the new-collection + re-embed + alias-swap remedy.
- [ ] Every upserted point has `payload["is_current"] is False`.
- [ ] `point_id == uuid5(NAMESPACE_URL, page_id)` for every point; re-running the same ingest overwrites in place and the point count is unchanged.
- [ ] No point payload contains an `image_path` key.
- [ ] `ingest/index.py` creates no payload index named `entity_keys`, and an AST scan finds no `MatchValue` lookup for one.

### Test Plan
**Levels:** [L0, L1, L2]
**Commands:** `bash scripts/test-unit.sh -k "embed_composition or fingerprint"` · `bash scripts/test-api.sh -k index_upsert`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007) with derived records from U009; a stub embedding backend selected by config; ephemeral Qdrant.
**Edge Cases:** a batch whose returned count is short (per-item fallback); a page with no summaries (empty captions surface — assert it is absent, not a zero vector); a fingerprint mismatch; a re-run producing identical `point_id`s.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the raster Part is dropped during the port because Spec §4.2's stale "Text only" row is read as normative. **Mitigation:** SA-1 in §8 records the adjudication (C12 and D4 win); the acceptance criterion above asserts the raster Part is present.
- **Risk:** per-page image embedding is **unbudgeted** — Spec §2.3 C12 notes ≈ $0.66 per full 5,505-page run at $0.00012/image. **Mitigation:** it is a cost-model line, not a design change; recorded here so M8's scale-out costing includes it.

### Rollback Plan
- **If this unit must be reverted:** points written by this run are all `is_current=False` and therefore unqueryable (I7). Delete them by `run_id` filter — never a blanket delete, which would destroy F9's superseded-revision evidence. If the embedding model changed, do **not** mutate the collection: create a new collection at the prior fingerprint, re-embed, and swap the alias back.

---

## Unit: Gates, publish, retirement, the run control plane, and exports (ID: U011)

**Status:** 🔵 Not Started
**Milestone:** M2a
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Large
**Spend:** none

### Goal
Close the pipeline: evaluate the publish gates, flip `is_current` only when they pass, apply the
three-clause retirement rule, hold run and window state in `vsir_runs`, and serve the two exports.

### Working Deliverable
`vsir ingest <pdf> --vlm stub` (the full pipeline), plus `vsir runs show`, `vsir gates rerun` and
`vsir publish --override` — the M2a milestone demo.

### Demo Command
```bash
vsir ingest data/source/synthetic_3window.pdf --vlm stub && vsir runs show <run_id>
```
The reviewer sees the run reach `state: published` with every gate result printed, `pages_indexed`
equal to the PDF's page count, and the off-by-one trap recorded as caught by `offset_check`.
Re-running the ingest yields the same point count, and killing a run mid-flight leaves
`state: stopped` with zero queryable pages.

### Deliverables (files)
- `backend/vsir/ingest/gates.py` — **rewritten** from `impl/app/pipeline.py`'s gate logic: the five
  gates of Spec §11.1. The `allowlist` and `class_totality` gates are **not ported**.
- `backend/vsir/ingest/run.py` — **ported with changes** from `impl/app/pipeline.py` and
  `impl/app/segjobs.py`: the `vsir_runs` control collection, the run and window points, the advisory
  lease, the state enum, the run record of Spec §6.9.
- `backend/vsir/ingest/export.py` — **written**, net new: `labels.jsonl` and `observed_tokens.jsonl`,
  both **generated from the index and streamed**, never written to the instance's filesystem.
- `backend/vsir/serve/app.py` — **extended**: `GET /runs/{run_id}` and
  `GET /runs/{run_id}/export/{labels,observed_tokens}.jsonl`.
- `backend/vsir/cli.py` — **extended**: `ingest` (full), `runs show`, `gates rerun`, `publish --override`.
- `backend/tests/unit/test_gates.py`, `test_export_shape.py`, `test_safety_flag.py` — **written**.
- `backend/tests/api/test_publish_and_retire.py`, `test_run_record.py`, `test_kill_mid_run.py` — **written**.

### Requirements
- Read `impl/app/pipeline.py` and `impl/app/segjobs.py` first, and the guides
  `impl/pipeline-guide/10-gates-and-publish.md`, `11-export.md`, `12-reproducibility.md` (Spec §20).
  ⚠ **`10-gates-and-publish.md` documents `allowlist` / `class_totality`, both replaced by
  `grounded_rate`**; ⚠ **`11-export.md` documents `withheld.jsonl`, which is dropped** — it survives
  only as a frozen M2b parity artefact (U012), never as an export of this pipeline.
- Spec §11.1 gates: `window_coverage` (must be 1.0 after retries — **block**); `offset_check` (all
  windows pass I4 — **block**); `grounded_rate` median **over pages with `has_text`** ≥ 0.8
  *(provisional, R4 — set from M2b)* — **block**, hold for review, list worst pages, releasable with
  `vsir publish --override grounded_rate --reason "…"` which records the reason in the run and flags
  every page `published_with_override`; `text_coverage` — flag `mostly_scanned`, **never block**, and
  **at 0.0 the `grounded_rate` gate is skipped entirely** so a fully scanned document publishes and
  answers `not_searchable`; `label_monotonic` — flag `label_conflict`.
- Spec §6.7: step 10 writes `is_current=False`; **step 11 is the only thing that flips it**, and only
  when every blocking gate passes (I7). Every tool injects `is_current=True` server-side, always. The
  filtered `set_payload` is idempotent and retried; `published_at` is recorded only after it returns.
- Spec §6.7 **three-clause retirement**, all filter-based, idempotent and retried:
  (1) points of the **same `(doc_id, revision)`** from an *earlier* `run_id` are **deleted** → F12;
  (2) points of the **previously current *other* revision** are set `is_current=False` and **kept** →
  they are what `found_only_in_superseded` reads from (F9, exercised at M8);
  (3) points of any other document are **never touched**. A blanket "delete every point whose
  `run_id` is not the current run" would satisfy F12 by destroying F9's evidence.
- Spec §3 D9 / §6.7: `vsir_runs` holds one point per run
  (`{state, step, windows_done, windows_total, gate_results, lease_owner, lease_expires_at}`) and one
  per window (`{state, attempts, checkpoint, extract_key}`), plus the observed-token inventory per
  document. One worker owns one run under an **advisory** lease (Qdrant has no compare-and-swap):
  a duplicated worker re-bills but **cannot corrupt the index**, because `point_id` is idempotent (I1)
  and nothing is queryable until the gates flip `is_current` (I7).
- Spec §6.8: `labels.jsonl` one line per page with the exact field set; `safety_flag =
  (doc_type in SAFETY_DOC_TYPES or any(t in page.topics for t in SAFETY_TOPICS))` — `SAFETY_DOC_TYPES`
  is a **manifest facet set by the uploader**, `SAFETY_TOPICS` matches the model's own lowercase
  `topics[]`; **never a keyword list**, and `safety_flag` is advisory metadata — never a gate, never a
  filter default, never a reason to hide a page. `codes_in_text` **is** the old
  `verified_identifiers[]` (C8). Both exports are **streamed over HTTP**, never written to disk.
- Spec §6.9 run record and `state ∈ {queued, running, stopped, gated, published, failed}`;
  `stopped` is what a `SIGTERM` leaves and is the only state `--resume` accepts without `--steal`.
- Spec §11.4: Prometheus gauges `ingest_grounded_rate_median{doc_id}` and `ingest_gate_failures_total{gate}`.
- Spec §20.1 register items closed here: **E2** (job state as a dict on daemon threads),
  **E7** (orphan points), **E4** (no cost observability), **E1/E8** (HTTP never calls `export()`).

### Invariants Enforced
- **I1** — one page, one point: `point_id = uuid5(page_id)`, a unique-`page_id` assert, and `count(doc, rev) == pdf.page_count` after publish.
- **I4** — the page offset is proved, never assumed: the `offset_check` gate requires both of Spec §6.4's checks on every window; a failure bisects and re-bills.
- **I7** — a run that has not passed its gates cannot answer: `is_current=False` until the gates pass, and every tool injects `is_current=True`.

### Failure Rows Closed
- **F4 (M2a half)** (*"that part doesn't exist"* about a scanned page) — the `has_text` facet plus the `text_coverage == 0.0` skip means a fully text-free document **publishes** rather than being quarantined — `test_fully_scanned_document_publishes` (L2).
- **F7** (every page number shifted by one) — I4 — `test_offset_check_catches_shifted_pages` (L2, on U007's off-by-one trap).
- **F12 (M2a half)** (totals double; stale pages stay findable) — I1 plus retirement scoped to the same `(doc_id, revision)` — `test_reingest_twice_same_point_count` (L2).
- **F17** (a half-finished run answers queries) — I7 — `test_kill_mid_run_zero_queryable_pages` (L2).

### Dependencies
- **Depends On:** [U010]
- **Enables:** [U012, U014, U025]
- **External:** Qdrant 1.19.0; `GET /runs/...` is served by the app skeleton from U002.

### Acceptance Criteria
- [ ] `window_coverage < 1.0` after retries **blocks** publish; the run record shows the gate name and zero pages are queryable.
- [ ] Any window failing either §6.4 check **blocks** publish, and the run record names the failing window.
- [ ] `grounded_rate` median below the threshold **blocks**, lists the worst pages, and `vsir publish --override grounded_rate --reason "…"` then publishes with the reason in the run record and `published_with_override == True` on **every** page.
- [ ] A document with `text_coverage == 0.0` publishes with flag `mostly_scanned` and **without the `grounded_rate` gate being evaluated at all**.
- [ ] A non-monotonic printed-label sequence publishes with flag `label_conflict` — it does not block.
- [ ] After publish, `count(doc_id, revision, is_current=True) == pdf.page_count` and every `page_id` is unique (I1).
- [ ] Before the gates pass, a query for a page of that run returns zero results — the points exist with `is_current=False` (I7).
- [ ] `SIGKILL` at window 2 of 3 leaves `state: stopped` (or `running` with an expired lease) and **zero** queryable pages for that document.
- [ ] Re-ingesting the same `(doc_id, revision)` twice yields the same point count, and the earlier run's points are deleted by filter.
- [ ] Retirement clause 2: after publishing revision 1.4, revision 1.3's points still **exist** with `is_current=False` — they are not deleted (this is what U025 later reads for F9).
- [ ] Retirement clause 3: publishing `doc_id=A` leaves every point of `doc_id=B` byte-identical (asserted by a point-count and payload-hash comparison before and after).
- [ ] `GET /runs/{run_id}` returns every field of Spec §6.9 including `gate_results`, `overrides`, `lease` and `cost`.
- [ ] `GET /runs/{run_id}/export/labels.jsonl` streams one line per page carrying `page_id`, `doc_id`, `revision`, `page_no`, `printed_page_no`, `label_verified`, `sections[]` (with `section_id`, `title`, `page_range`, `series_id`), `summaries[]`, `codes_in_text[]`, `grounded_rate`, `safety_flag`, `vlm_model`, `prompt_version`, `dpi`.
- [ ] `GET /runs/{run_id}/export/observed_tokens.jsonl` streams one line per document.
- [ ] A filesystem-write spy confirms **no** export file is written to the instance's disk during either request.
- [ ] `safety_flag` is `True` for a page whose `doc_type` is in `SAFETY_DOC_TYPES` and for a page carrying a `SAFETY_TOPICS` topic; an AST scan finds no hardcoded safety keyword list.
- [ ] Two workers taking the same run: the second refuses without `--steal`; with `--steal` it proceeds, and the final point count is still `pdf.page_count` (the lease is advisory; I1 + I7 are what make that safe).
- [ ] The Prometheus endpoint exposes `ingest_grounded_rate_median{doc_id}` and `ingest_gate_failures_total{gate}`.

### Test Plan
**Levels:** [L0, L1, L2, conformance]
**Commands:** `bash scripts/test-unit.sh -k "gates or export_shape or safety_flag"` · `bash scripts/test-api.sh -k "publish or retire or run_record or kill_mid_run"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007), plus a generated fully-scanned document and a two-revision pair; ephemeral Qdrant with both `vsir_pages` and `vsir_runs`; stub VLM.
**Edge Cases (typed 4xx / Spec §11.3):** `503 qdrant_unavailable` mid-publish (retried, never a partial flip); a blocked gate; an override; `text_coverage == 0.0`; a killed run; a stolen lease; a `set_payload` that fails and is retried before `published_at` is recorded.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** a builder implements retirement as "delete every point whose `run_id` is not the current run", which passes F12 and silently destroys F9's evidence. **Mitigation:** clause 2 and clause 3 each have their own acceptance criterion above, and clause 3's is a before/after payload-hash comparison.
- **Risk:** the advisory lease is mistaken for a mutual-exclusion guarantee. **Mitigation:** stated in Requirements (Qdrant has no compare-and-swap) and asserted by the `--steal` criterion — a duplicated worker is a **cost** bug, not a corruption bug.
- **Risk (OQ-7):** Part A reads exports from `data/exports/{run_id}` on disk today. **Mitigation:** serve over HTTP per §6.8 and, if Part A needs files, dual-write to an **attached object store** — never the instance's local disk. Resolve before M8.

### Rollback Plan
- **If this unit must be reverted:** flip `is_current` back to `False` for the run's points by `(doc_id, revision, run_id)` filter — never a blanket delete. If the prior revision was retired in clause 2, restore its `is_current=True` by the same filter. Delete this run's points by `run_id` filter and set the `vsir_runs` run point to `state: failed` with a reason. For a full-corpus rebuild, swap the collection alias back instead — **never leave a partial index state**.

---

## Unit: Port the paid-for `impl` fixtures and the parity / negative sets (ID: U012)

**Status:** 🔵 Not Started
**Milestone:** M2b
**Priority:** P1-High
**Type:** eval
**Size Estimate:** Medium
**Spend:** none — *this unit is inside a paid milestone but spends nothing; it is planned first so no paid work happens before the free baseline exists (Spec §13 M2b, "First, port what is already paid for").*

### Goal
Bring the S2 responses and exports `impl` already paid for into this repository as fixtures, and turn
the Spec §12.3 PARITY rows into a runnable suite — before a cent is spent.

### Working Deliverable
An L2 parity and negative-set suite runnable against the ported baseline with zero spend and no
API key.

### Demo Command
```bash
bash scripts/test-api.sh -k "parity or withheld"
```
The reviewer sees one PASS row per identifier the old `entity_keys` gate accepted that the phrase
index still finds, one PASS row per `withheld.jsonl` raw proved **unfindable** in `text`, and a
separate **GAINS** list of codes the old grammar dropped that the phrase index now finds.

### Deliverables (files)
- `data/fixtures/legacy/raw/<doc_id>/<sha256>.json` — **ported verbatim** from `impl/data/raw/*`
  (7 documents; `TC1E-SF` is 2 windows / 64 KB — the pages 1–30 and 31–55 split of Spec §12.1;
  `LTC1AV81` is 12 windows; plus `CE-TC1AV8`, `DS-2611-SICK`, `DS-5549-EATON`, `TC1E-PERIODIC`,
  `TC1AV8M2-LIFTING`). **Old schema, kept as-is.**
- `data/fixtures/legacy/labels.jsonl` — **ported verbatim** from `impl/data/exports/r-poc-*/`: the
  `lookup` parity baseline.
- `data/fixtures/legacy/withheld.jsonl` — **ported verbatim**: the negative set.
- `backend/tests/api/test_parity_lookup.py`, `test_withheld_negative_set.py` — **written**.
- `backend/tests/unit/test_legacy_fixture_integrity.py` — **written**: sha256 equality against source.

### Requirements
- Read `impl/data/raw/*` and `impl/data/exports/r-poc-*/{labels,withheld}.jsonl` first.
- Spec §12.1: these artefacts are **already paid for**. The old-schema raw responses give real window
  structure and page counts, so **L1 derivation, the offset proof (I4/F7) and stitching are testable
  on real data at zero spend**. They lack the new fields (`summaries`, `topics`, `codes`, `sections`)
  — that is exactly the one re-bill U013 buys.
- Spec §12.3 PARITY rows, verbatim: *every identifier the old `entity_keys` gate accepted → still
  findable by phrase*; *every raw in `withheld.jsonl` → NOT findable in `text` (only via
  `include_unverified`)*.
- Spec §12.3: **a code the old grammar dropped but the phrase index finds is a gain — record it, do
  not treat it as a diff to reconcile.**
- Spec §12.1: until M2b lands, every fixture-consuming level runs against `synthetic_3window/` **and**
  the ported `impl` responses; afterwards against all three.
- Spec §17 OQ-1: this unit is **not** blocked — the S2 responses are already in `impl/data/raw/`.
  Only U013's re-bill needs the pilot PDF.

### Invariants Enforced
- None.

### Failure Rows Closed
- None directly — this unit provides the evidence that turns R7 ("the port is a rewrite of a system
  with no tests") from a hope into an assertion.

### Dependencies
- **Depends On:** [U011]
- **Enables:** [U013, U016, U026]
- **External:** read access to the `impl/` tree; no network, no API key, no PDF.

### Acceptance Criteria
- [ ] Every file under `data/fixtures/legacy/raw/` has a sha256 identical to its `impl/data/raw/` source.
- [ ] `data/fixtures/legacy/labels.jsonl` and `withheld.jsonl` are byte-identical to their `impl/data/exports/r-poc-*/` sources.
- [ ] After indexing the legacy baseline, **every** identifier in `labels.jsonl` returns `total >= 1` from `lookup(identifier)`.
- [ ] **Every** raw in `withheld.jsonl` returns `hits == []` from `lookup(raw)`, and returns a non-empty `unverified_hits` only with `include_unverified=True`.
- [ ] The suite emits a **GAINS** list — codes findable by phrase but absent from `labels.jsonl` — and a gain does **not** fail the suite.
- [ ] The L1 derivation suite (U009's) runs green against the ported real windows for `TC1E-SF` and `LTC1AV81`, proving the offset proof and stitching on real data at zero spend.
- [ ] A network spy records zero outbound calls and the suite passes with `GEMINI_API_KEY` unset.

### Test Plan
**Levels:** [L1, L2]
**Commands:** `bash scripts/test-unit.sh -k "legacy_fixture_integrity or derive"` · `bash scripts/test-api.sh -k "parity or withheld"`
**Fixtures/Stubs:** `data/fixtures/legacy/` (produced by **this unit**); ephemeral Qdrant; stub VLM (the raw responses are replayed, never re-requested).
**Edge Cases:** an identifier in `labels.jsonl` whose page has no text layer (expect `not_searchable`, which counts as findable-in-principle and is recorded separately, not as a parity failure); a `withheld` raw that is also a legitimate token elsewhere in the corpus (scope the assertion to the page it was withheld from).

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk (R7, Spec §18):** parity covers only what `impl` actually exercised — most of Spec §7 and §8 has **zero** legacy coverage. **Mitigation:** this unit must publish an explicit list of the §7/§8 paths parity cannot cover, so nobody mistakes a green parity run for sign-off; U006's abstention eval, U016's acceptance eval and U026's D11 gates are the real safety net.
- **Risk:** the old-schema responses are silently coerced into the new schema and the baseline stops being a baseline. **Mitigation:** the sha256 integrity test above; the raw fixtures are read-only.

### Rollback Plan
- **If this unit must be reverted:** delete the legacy points by `run_id` filter (they are indexed under their own run) and remove `data/fixtures/legacy/`. No published document is affected — the legacy baseline is indexed for parity only and is never the current revision of a real document.

---

## Unit: The one paid `TC1E-SF` ingest and the `grounded_rate` baseline (ID: U013)

**Status:** 🔵 Not Started
**Milestone:** M2b
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Large
**Spend:** paid (S2 + embed, once)

### Goal
Spend once: ingest the 55-page pilot PDF under the new S2 schema, freeze the verbatim responses as
the permanent fixture, and set the `grounded_rate` gate threshold from the measured distribution.

### Working Deliverable
`data/fixtures/TC1E-SF/*` — a frozen, checked-in fixture that makes every downstream level free
forever — plus a published 55-page document.

### Demo Command
```bash
VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf && vsir runs show <run_id>
```
The reviewer sees a run reaching `published` with `pages_indexed: 55`, `window_coverage: 1.0`,
`offset_check: pass` for both windows, the `grounded_rate` distribution printed, and the four fixture
files written under `data/fixtures/TC1E-SF/`.

### Deliverables (files)
- `data/fixtures/TC1E-SF/raw_window_1.json` — **written**: the verbatim `WindowOut`, pages 1–30.
- `data/fixtures/TC1E-SF/raw_window_2.json` — **written**: pages 31–55.
- `data/fixtures/TC1E-SF/text.json` — **written**: PyMuPDF text per page, pinned extractor.
- `data/fixtures/TC1E-SF/expected.json` — **written**: the Spec §12.3 acceptance table.
- `backend/vsir/vlm/record.py` — **written**, net new: the recorder. A `Backend` that wraps the
  configured one and freezes every verbatim body under its §6.3 key, plus `freeze_text()` for
  §12.1's `text.json`.
- `backend/vsir/cli.py` — **extended**: `vsir ingest --record DIR`.
- `backend/vsir/eval/grounded_rate.py` — **written**, net new: the distribution report.
- `backend/tests/unit/test_vlm_record.py` — **written**, L0/L1, including the record→replay round
  trip.
- `backend/tests/unit/test_grounded_rate_report.py` — **written**, L0/L1.
- `backend/tests/paid/test_tc1e_sf_ingest.py` — **written**, L4, gated by `VSIR_ALLOW_PAID=1`.
- `backend/tests/api/test_acceptance_real.py` — **written**, L2, replay-only.
- `.env.example` — **updated**: `VSIR_GROUNDED_RATE_THRESHOLD` documented as *set from the M2b
  distribution, see the run report* (R4).

### Requirements
- Read `impl/INGESTION_WALKTHROUGH.md` (a real ingest traced end to end) before debugging anything.
- Spec §13 M2b: **one real ingest of `TC1E-SF` (55 pages) under the new S2 schema only** — the single
  re-bill. No new pipeline code: this runs the surface U007–U011 already built, with real credentials
  and real data.
- Spec §11.1 / R4: report the `grounded_rate` distribution over pages with `has_text` and set the gate
  threshold from it, replacing U011's provisional 0.8. Record the rationale.
- Spec §5.7: `VSIR_GROUNDED_RATE_THRESHOLD` is documented in `.env.example` as the **candidate**
  threshold the §11.1 *report* scores against, and is deliberately **not** wired into the gate. The
  number the gate uses stays the `vsir.core.health.TRUST_OK_MIN` pin, because §5.7 makes the trust
  ladder a **released decision** — a deployment that could re-tune what "trusted" means could turn
  F14 back on by editing an env var. Adopting a threshold is a release, not a hot edit.
- Spec §2.3 **C10**: the acceptance-table page counts are **normative** for `TC1E-SF`. If the first
  real ingest disagrees, that is a **blocking finding** (offset or tokenisation) until proven a corpus
  difference; changing `expected.json` requires a recorded rationale in the run report.
- Spec §12.1: once frozen, these files are replayed by `VSIR_VLM=stub` + `VSIR_FIXTURE` forever —
  no later unit may require a new paid call.
- Spec §12.1's **mechanism**, a **finding raised during U013**: `vlm/cache.py::write` documents its
  two callers as the M2a corpus generator "and the one paid ingest at M2b", but no code path ever
  called it for a live response — so `data/fixtures/TC1E-SF/raw_window_*.json` had no producer and
  §12.1's "one paid ingest buys a permanent test corpus" had no mechanism. `vlm/record.py` is that
  producer, and it is a **wrapper on the VLM boundary rather than a pipeline step**, because §6.2's
  bisection makes extra calls mid-flight: a per-step recorder would freeze the clean run's windows
  and miss exactly the bisected run whose receipts are worth having. Recording is a **flag on one
  run, never configuration** — an ambient record mode lets a fixture accumulate responses from runs
  nobody meant to freeze. The rest of this unit is blocked on OQ-1/OQ-2; the recorder ships and is
  tested at **L0/L1 against the stub, with zero spend**.
- Spec §17 OQ-1 / OQ-2 apply **only to this unit's re-bill**. Default assumptions: the operator places
  the PDF at `data/source/TC1E-SF.pdf` (which stays gitignored), and until a key exists the pipeline
  runs in replay mode off the ported `impl` responses.

### Invariants Enforced
- None newly asserted (I1, I4, I7 are U011's and are re-exercised here on real data).

### Failure Rows Closed
- None newly. It **closes the Spec §12.3 PARITY rows on real text** and re-proves F7/F13/F15 against
  a real document.

### Dependencies
- **Depends On:** [U012]
- **Enables:** [U016, U020, U026]
- **External:** **OQ-1** the pilot PDF; **OQ-2** a Gemini project/key and quota; `VSIR_ALLOW_PAID=1`.
- **OQ-2 is closed and OQ-1 is the only external blocker left.** A key is present and was exercised
  live on 2026-09-10: `gemini-3.8-flash` and `gemini-embedding-2` both answer, a real 4-page
  datasheet ingested to `published` through `POST /documents`, and the five defects that stood
  between the switch and a real document are U028.
- **The ladder is no longer a blocker either.** `TC1E-SF` is 55 pages with a single 55-page chapter,
  and the shipped `plan()` refused it at **step 05** — one step before the spend this unit was
  thought to be waiting on a credential for. `fixes/001` makes Level 2 a fold, and the pilot now
  plans to `[[1, 30], [31, 55]]`, byte-for-byte what `data/fixtures/TC1E-SF/expected.json` had
  declared all along. **This unit's own first step is still to re-check for the PDF** — but when it
  arrives, nothing else is in the way.
- ⚠ **This unit meets P1, P2, P5 and P6 of §4c first.** It is the next paid run, so it is where a
  live run's missing cost accounting, the absent cache store, the `VSIR_FIXTURE` conflation and the
  single-page `page_index` anomaly all become its problem. Read §4c before starting.

### Acceptance Criteria
- [ ] The run publishes **55** points; `count(TC1E-SF, 1.3, is_current=True) == 55`.
- [ ] `window_coverage == 1.0` and `offset_check` passes for both windows.
- [ ] `data/fixtures/TC1E-SF/{raw_window_1.json, raw_window_2.json, text.json, expected.json}` exist, are checked in, and `raw_window_1` covers pages 1–30 while `raw_window_2` covers 31–55.
- [ ] `vsir ingest --record DIR` freezes every S1/S2 body under its §6.3 key plus `text.json`, and re-running the same ingest with `--fixture DIR` replays it with `cost.vlm_calls == 0` — proven at L0/L1 against the stub, so it is green before a cent is spent.
- [ ] A call that raised (a truncation to bisect, an unreachable provider) freezes **nothing**: the fixture holds only responses the pipeline accepted (§6.2, F13).
- [ ] Re-running the identical ingest costs **$0** — every window is an `extract_key` cache hit and `cost.cache_hits` equals the window count.
- [ ] The parity check of U012 passes against `impl`'s `labels.jsonl` **on real text**, and every `withheld.jsonl` raw is unfindable in `text`.
- [ ] The Spec §12.3 acceptance table is reconciled against C10: `lookup("SF 1.1A")` → exactly 1; `lookup("SF 5.5b")` → exactly 1; `lookup("SF 121.1")` → 1; `lookup("EAO 84-5140.0020")` → `total == 10`; `lookup("B&R X20SI4100")` → `total == 54`, `capped == True` at `cap=20`; `lookup("3")` unscoped → `weak == True`, `needs_scope == True`; `verify("SF 1.1A", [p008])` → `absent`. **Any discrepancy is recorded as a blocking finding with a written rationale before `expected.json` is changed.**
- [ ] The `grounded_rate` distribution over the 55 pages is printed, and `VSIR_GROUNDED_RATE_THRESHOLD` is set from it with the rationale recorded in the run report (R4).
- [ ] Every L0–L3 test that previously ran on `synthetic_3window` also passes against `data/fixtures/TC1E-SF/` in replay mode with `GEMINI_API_KEY` unset.
- [ ] `scripts/test-paid.sh` refuses to run this test without `VSIR_ALLOW_PAID=1`.

### Test Plan
**Levels:** [L1, L2, L4]
**Commands:** `VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh -k tc1e_sf_ingest` · `bash scripts/test-unit.sh -k derive` (replay) · `bash scripts/test-api.sh -k acceptance_real` (replay)
**Fixtures/Stubs:** `data/fixtures/TC1E-SF/` (produced by **this unit**) and `data/fixtures/legacy/` (U012); real Gemini **only** in the gated L4 test; every other level replays.
**Edge Cases:** an acceptance-table count that disagrees with C10 (must halt as a finding, not re-baseline); a `MAX_TOKENS` bisection on a real window; a scanned page inside the pilot document.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk (OQ-1/OQ-2):** neither the PDF nor a key is available. **Mitigation (Spec §17 defaults):** everything upstream ships and stays green in replay mode off the ported `impl` responses; only this unit's re-bill, the C10 reconciliation and the R4 threshold are deferred. Nothing downstream is blocked — U020, U022 and U026 fall back to `synthetic_3window`.
- **Risk (R4):** 55 pages is a small sample for a threshold that gates a 5,505-page corpus. **Mitigation:** the threshold is explicitly provisional until U026 re-validates it on the full corpus; the override path (`vsir publish --override`) exists precisely so a mis-set threshold cannot strand a document silently.
- **Risk (C10):** the temptation to edit `expected.json` when reality disagrees. **Mitigation:** the acceptance criterion makes a discrepancy a blocking finding requiring a written rationale.
- **Risk:** the recorder writes to local disk, which reads like a §15 Factor VI violation. **Mitigation:** it is a build artefact of a one-off admin command that a human then commits — the same status as `python -m vsir.eval.synthetic_pdf`'s output. Nothing serving reads it, no correctness depends on it surviving the process, and the running service never records, because `--record` is a CLI flag and not a configuration value a deployment could carry.

### Rollback Plan
- **If this unit must be reverted:** delete the run's points by `(doc_id="TC1E-SF", revision, run_id)` filter and set the `vsir_runs` run point to `state: failed`. The frozen fixtures are inputs to tests, not index state — leave them; deleting them would make every downstream level require a new paid call.

---

## Unit: The serving app — auth, audit, budget, and degradation (ID: U014)

**Status:** 🟢 Complete (2026-09-10)
**Milestone:** M3
**Priority:** P0-Critical
**Type:** tool
**Size Estimate:** Medium
**Spend:** none

### Goal
Turn the health-only skeleton into the real FastAPI surface with bearer auth on every tool, the
append-only audit line, per-caller read budget, and every Spec §11.3 degradation row as a refusal.

### Working Deliverable
`vsir serve` — an authenticated app that boots behind the §4.3 self-check and refuses, never
degrades, on a backing-service outage.

### Demo Command
```bash
vsir serve & sleep 2 && \
  curl -s -o /dev/null -w "no-token=%{http_code}\n" -X POST localhost:8000/tools/lookup -d '{}' && \
  curl -s -o /dev/null -w "with-token=%{http_code}\n" -H "Authorization: Bearer $VSIR_DEMO_TOKEN" \
       -X POST localhost:8000/tools/lookup -d '{"label":"SF 1.1A"}' && \
  docker compose -f docker-compose.test.yml stop test-qdrant && \
  curl -s -H "Authorization: Bearer $VSIR_DEMO_TOKEN" -X POST localhost:8000/tools/lookup \
       -d '{"label":"SF 1.1A"}' | jq -r '.detail.code'
```
The reviewer sees `no-token=401`, `with-token=200`, then `qdrant_unavailable` (a 503) — **never** an
empty 200 — plus the ten-field JSON audit line printed to stdout.

### Deliverables (files)
- `backend/vsir/serve/app.py` — **ported with changes** from `impl/app/main.py`: the routes of
  Spec §7.4, the boot self-check on start, `/ready`, `/runs/{run_id}`.
- `backend/vsir/serve/auth.py` — **written**, net new: bearer on every tool; identity propagated,
  never client-supplied.
- `backend/vsir/serve/audit.py` — **written**, net new: one append-only line per `read` and `fetch`.
- `backend/vsir/serve/budget.py` — **written**, net new: the per-caller `read` quota and
  `reads_remaining` on every envelope.
- `backend/vsir/cli.py` — **extended**: `vsir serve`.
- `backend/tests/api/test_auth.py`, `test_audit.py`, `test_degradation.py`, `test_boot_refusals.py` — **written**.

### Requirements
- Read `impl/app/main.py` first. ⚠ Spec §2.5 A: `impl` has **no auth on any endpoint, including the
  two that spend money** (register item **E5**) — that defect is closed here.
- Spec §7.4 routes: `POST /tools/{tool_name}` (bearer) · `POST /ask` (bearer, wired at M6) ·
  `GET /pages/{page_id}/image` (bearer, wired at M4) · `GET /runs/{run_id}` (bearer) ·
  `GET /runs/{run_id}/export/…` (bearer) · `GET /health`, `GET /ready`, `GET /metrics` (none).
- Spec §7.4 audit: one append-only line per `read` and `fetch` carrying
  `(user_id, run_id, session_id, tool, page_ids, dpi, input_tokens, output_tokens, cache_hit,
  latency_ms)`. **Cost goes in the audit log, not the response body** — the agent gets one integer,
  `reads_remaining`. No `usd_estimate` in any response.
- Spec §7.3: `429 budget_exhausted` when the per-caller `read` quota is exhausted — never a silent
  truncation.
- Spec §11.3, every row as a **refusal, not a best-effort fallback**: Qdrant unreachable →
  `503 qdrant_unavailable`, retryable, **never an empty result**, `/ready` red while `/health` stays
  green; Gemini unreachable → `503 vlm_unavailable` on `read` while every free tool keeps working;
  index schema ≠ `INDEXED` → refuse to serve at boot; fingerprint mismatch → refuse to upsert;
  a `-latest` model id → refuse to start; a document whose `grounded_rate` collapses →
  `text_trust = "untrusted"`, its pages count as unsearchable and `verify` returns `unverifiable`.
- Spec §15 Factor VI: **no session**. No module-level mutable store (C11) — U002's grep enforces it.
- Spec §15 Factor XI: JSON to stdout only; the app never opens a log file.
- Spec §15.1 Secrets: `VSIR_API_TOKENS` and the VLM key must never appear in a log line, a response
  or an error message.

### Invariants Enforced
- None newly (I6's boot assertion built in U003 is wired into server start here).

### Failure Rows Closed
- None (F2 and F4's M3 halves are U015's).

### Dependencies
- **Depends On:** [U011]
- **Enables:** [U015]
- **External:** Qdrant; the app skeleton and probes from U002.

### Acceptance Criteria
- [ ] `POST /tools/lookup` without an `Authorization` header returns **401**; with a token from `VSIR_API_TOKENS` it returns 200.
- [ ] `GET /health` needs no token; `GET /pages/{id}/image` does.
- [ ] A client-supplied `X-User-Id` header is **ignored** — identity comes from the token only (asserted by an audit-line comparison).
- [ ] Every `read` and every `fetch` emits exactly one audit line with all ten fields; a `skim`/`lookup`/`verify` emits none.
- [ ] No response body from any tool contains a cost, a token count or a `usd_estimate`; `reads_remaining` is an integer on every envelope.
- [ ] With Qdrant stopped, every tool returns `503 qdrant_unavailable` — no tool returns 200 with an empty `hits` list.
- [ ] With Qdrant stopped, `/health` stays 200 and `/ready` goes 503.
- [ ] With the VLM backend raising unreachable, `read` returns `503 vlm_unavailable` while `lookup` and `verify` still return 200.
- [ ] Booting against a collection whose payload schema is missing an `INDEXED` key exits non-zero **before binding the port**.
- [ ] A caller whose `reads_remaining` reaches 0 gets `429 budget_exhausted` on the next `read`, not a truncated result.
- [ ] A document with a collapsed `grounded_rate` has `text_trust == "untrusted"`, its pages count as unsearchable for `lookup`, and `verify` on its codes returns `unverifiable`.
- [ ] A log scan across a full request cycle finds no token value and no API key.
- [ ] An AST scan finds no module-level mutable session store under `backend/vsir/serve/`.

### Test Plan
**Levels:** [L2, conformance]
**Commands:** `bash scripts/test-api.sh -k "auth or audit or degradation or boot_refusal"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` published by U011; ephemeral Qdrant that the test can stop; stub VLM that can be made to raise.
**Edge Cases (typed 4xx / §11.3):** 401; 429; 503 ×2; boot refusal on schema drift; `text_trust == "untrusted"`; a secret in an error message.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** a Qdrant outage is caught and returned as an empty result set, turning our outage into the agent's fabricated abstention. **Mitigation:** Spec §7.1 says this explicitly; the acceptance criterion asserts a 503 and forbids an empty 200.
- **Risk:** the audit line grows to carry document content. **Mitigation:** Spec §15.1 Retention forbids widening the audit schema with content; the ten fields are asserted exactly.

### Rollback Plan
- **If this unit must be reverted:** the route prefix and auth are a contract change for every caller. Pin the tool contract by `schema_version` and keep the prior route module importable; no index state is touched, so no collection or alias action is required.

---

## Unit: `lookup` and `verify` over HTTP and MCP (ID: U015)

**Status:** 🟢 Complete
**Milestone:** M3
**Priority:** P0-Critical
**Type:** mcp
**Size Estimate:** Large
**Spend:** none

### Goal
Expose M1's proven core as the first two tools — over HTTP **and** MCP, through the identical
implementations — with all four typed absences, `next.suggest` and `unverified_hits` reaching the
caller.

### Working Deliverable
`vsir serve` answering `POST /tools/lookup` and `POST /tools/verify`, plus `vsir mcp --stdio|--sse`
exposing the same two tools, plus the `vsir lookup` / `vsir verify` one-shots.

### Demo Command
```bash
vsir serve & sleep 2 && vsir lookup "SF 1.1A" && \
  vsir verify --claims K73 --pages "SYN-M1@1.0#p006" && \
  vsir lookup "alarm 152" && \
  { printf '%s\n' \
     '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"demo","version":"0"}}}' \
     '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
     '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"lookup","arguments":{"label":"SF 1.1A"}}}'; sleep 2; } \
    | vsir mcp --stdio | tail -1
```
The reviewer sees `total: 1` for the phrase; `K73: absent` with `present_instead`; `alarm 152` coming
back `not_found` **with** `next.suggest: ["skim_pages"]`; and the MCP call returning a
byte-identical envelope to the HTTP one.

**Two corrections to the command as first written, both made when U015 was built.** (1) MCP
requires the `initialize` / `notifications/initialized` handshake before `tools/call`; the SDK
refuses a bare call with `-32602`, and it cancels in-flight work when stdin reaches EOF, hence the
trailing `sleep` (a real MCP client holds the pipe open and needs neither). (2) The page id is the
synthetic corpus's — `TC1E-SF@1.3#p008` does not exist while **OQ-1** is open, and §7's documented
fallback is the generated corpus. `SYN-M1@1.0#p006` is the corpus's own `K73`-on-a-`K78`-page row.

### Deliverables (files)
- `backend/vsir/serve/tools/lookup.py` — **extended** from U005: the HTTP wrapper over the same pure
  function; the six-value status resolved end to end.
- `backend/vsir/serve/tools/verify.py` — **written**, net new: the wrapper over
  `core/verify.py::verify_claims`.
- `backend/vsir/serve/envelope.py` — **extended**: `next.suggest`, `scope_stats`, `effective_scope`.
- `backend/vsir/mcp/server.py` — **written**, net new: `vision-segmentation-retriever` over stdio and
  SSE, **calling the identical implementations** — no second code path.
- `backend/vsir/cli.py` — **extended**: `lookup`, `verify`, `mcp`.
- `backend/tests/api/test_lookup_tool.py`, `test_verify_tool.py`, `test_status_enum_end_to_end.py`,
  `test_mcp_parity.py` — **written**.

### Requirements
- Read `impl/app/retrieve.py::lookup` and `impl/app/api_models.py` first. ⚠ Spec §2.5 A: `impl`'s
  **`200`-empty abstention path is removed deliberately** — an empty `200` is now impossible, and that
  is a breaking change for any existing caller.
- Spec §7.1 six-value status with the four distinct absences, and the agent action each implies:
  `not_found` → abstain (but check `next.suggest`); `not_searchable` → escalate to vision;
  `out_of_scope` → re-orient and widen; `found_only_in_superseded` → surface the revision;
  `error` → retry/report, **never abstain**.
- Spec §7.1 `next.suggest`: a `not_found` that a different **move** could answer says so rather than
  inventing a seventh state — it returns `not_found` **with** `next.suggest: ["skim_pages"]` and the
  tokens that did occur.
- Spec §7.2.2: `include_unverified=True` returns `vlm_codes` hits in `unverified_hits` with
  `verified: false`; **scores and lists are never merged**. Candidate pages with no text layer →
  `not_searchable`, **never a bare empty set**.
- Spec §7.2.4: `verify` is per `(claim, page)`; `VerifyResult` sits inside the Family B envelope; a
  verify where every claim is `absent` is `status: ok`. A missing `page_id` is `404 page_not_found`;
  a backend failure is a 5xx.
- Spec §7.5: MCP exposes the same tools over stdio + SSE **calling the identical implementations** —
  no second code path. It is **stateless**: `scope` and `exclude` are parameters and `effective_scope`
  is echoed back.
- Spec §7.6: no field named `score`; `rank`/`best_rank` are ordinals. No fuzzy matching.
- Spec §6.7: every tool injects `is_current=True` server-side, **always**.
- Spec §13 M3 acceptance is split: the table and the L3 eval pass **on the synthetic corpus always**;
  the same table passes **on real text once M2b exists**, reconciled per C10.

### Invariants Enforced
- None newly (I2, I3, I5, I6 are M1's and are re-exercised across the HTTP and MCP boundary here).

### Failure Rows Closed
- **F2 (tool half)** (`verify` confirms a code that is not on the page) — the tool wrapper reuses the one `exact_filter`, with no independent logic — `test_verify_tool_absent_for_uncited_page` (L2).
- **F4 (M3 half)** (*"that part doesn't exist"* about a scanned page) — the `has_text` facet plus I5 surface `not_searchable` end to end — `test_lookup_scanned_page_not_searchable` (L2).

### Dependencies
- **Depends On:** [U014, U005, U006]
- **Enables:** [U016, U017]
- **External:** the MCP official Python SDK (stdio + SSE); Qdrant.

### Acceptance Criteria
- [ ] `POST /tools/lookup {"label": "SF 1.1A"}` returns `status == "ok"`, `total == 1`.
- [ ] `POST /tools/lookup {"label": "alarm 152"}` returns `status == "not_found"` **and** `next.suggest == ["skim_pages"]` and lists the tokens that did occur.
- [ ] A `lookup` whose only candidates have no text layer returns `status == "not_searchable"`, never `not_found` and never an empty `ok`.
- [ ] A `lookup` whose scope matches no document returns `status == "out_of_scope"`.
- [ ] All six status values are reachable by a crafted request (a parametrised test covers each).
      **As built, five are, and the spec is why** (§2.3 — the spec wins on a behavioural conflict).
      `ok` and the three absences a published corpus can produce are reached by a crafted body.
      `found_only_in_superseded` is **F9's row and §10 closes F9 at M8** (U025): `is_current` is
      injected today, so a superseded page cannot answer and the corpus's `expected.json` records
      the honest current answer as `not_found` — emitting the sixth value now would claim a row
      this milestone does not own. `error` is reached as a **5xx**, because §7.1 says *"a backend
      failure is a 5xx, never an empty result"*; a `200` whose body said `"error"` would be the
      empty-success shape the whole enum exists to remove.
      (`test_status_enum_end_to_end.py` asserts all of the above, including the two statements
      about the corpus, so the day U025 lands the relevant test goes red rather than staying
      quietly green.)
- [ ] No Family A response ever has `status == "ok"` with both `hits` and `unverified_hits` empty.
- [ ] `include_unverified=True` returns the `vlm_codes` match in `unverified_hits` with `verified is False`, and `hits` is unchanged.
- [ ] `POST /tools/verify` with three claims of which all are absent returns envelope `status == "ok"` and three `absent` verdicts.
- [ ] `POST /tools/verify` naming a nonexistent `page_id` returns `404 page_not_found`, not an empty result.
- [ ] Every response carries `effective_scope`, `scope_stats`, `reads_remaining` and `provenance` (with `run_id`, `release_id`, `schema_version`).
      **Read per family, per §7.1.** Family A carries all four. Family B's declared model is
      `{status, result, reads_remaining, provenance}` — there is no scope to echo, because a
      `verify` caller names the pages outright — so adding the other two to `ToolEnvelope` would
      contradict §7.1's normative shape. Asserted as: all four on `lookup`, both of Family B's on
      `verify`, and `extra="forbid"` on each so neither can grow a field by accident.
- [ ] Every query injects `is_current=True` — a point with `is_current=False` is never returned (asserted by seeding one).
- [ ] The MCP `tools/call` result for `lookup("SF 1.1A")` is **byte-identical** to the HTTP response body, over both stdio and SSE.
- [ ] An import-graph assertion proves `mcp/server.py` calls `serve/tools/*` directly — there is no second implementation.
- [ ] Two consecutive MCP calls with different `scope` values return different `effective_scope` and share no server state (asserted across two processes).

### Test Plan
**Levels:** [L2]
**Commands:** `bash scripts/test-api.sh -k "lookup_tool or verify_tool or status_enum or mcp_parity"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (always) and `data/fixtures/TC1E-SF/` (once U013 lands); ephemeral Qdrant; no VLM.
**Edge Cases (typed 4xx / §11.3):** 401 (U014); `filter_unknown_key`; `404 page_not_found`; `503 qdrant_unavailable` on both transports; a scanned page; a point with `is_current=False`.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the MCP handler re-implements validation and cap enforcement, so the two surfaces drift and a non-compliant MCP client bypasses a bound HTTP enforces (R6). **Mitigation:** the byte-identity criterion plus the import-graph assertion; **every safety rule that matters is server-side** (D7) — prompt-level rules on the raw MCP surface are advisory and documented as R6.
- **Risk:** existing callers of `impl` break on the removal of the `200`-empty path and the new bearer requirement. **Mitigation:** these are Spec §2.5 D breaking changes 1 and 4 — flagged in §8 below so the hand-off is a conversation, not a surprise.

### Rollback Plan
- **If this unit must be reverted:** the status enum and route shape are a tool contract change. Pin the contract by `schema_version` and keep the prior tool module importable; the MCP server must be reverted in the same commit so the two surfaces never diverge. No index state is touched.

---

## Unit: `vsir eval acceptance` and `vsir eval abstention` (ID: U016)

**Status:** 🔵 Not Started
**Milestone:** M3
**Priority:** P1-High
**Type:** eval
**Size Estimate:** Medium
**Spend:** none

### Goal
Make the Spec §12.3 acceptance table and the Spec §12.4 abstention eval first-class runnable
commands, so the safety net is something a reviewer executes rather than reads.

### Working Deliverable
`vsir eval acceptance` and `vsir eval abstention` — each printing a pass/fail row per case and
exiting non-zero on any failure.

### Demo Command
```bash
vsir eval acceptance && vsir eval abstention
```
The reviewer sees one row per §12.3 assertion (including the PARITY and negative-set rows once the
legacy fixture is indexed) and then `abstention_correctness: 1.00` over the 100-case near-miss set.

### Deliverables (files)
- `backend/vsir/eval/__init__.py`, `eval/acceptance.py`, `eval/abstention.py` — **written**, net new.
  *(Spec §4.1 does not enumerate an `eval/` package; it is a net-new addition required by §12.3, §12.4
  and §12.6, and is noted as such in §8, SA-5.)*
- `backend/vsir/cli.py` — **extended**: `eval acceptance`, `eval abstention`.
- `backend/tests/api/test_eval_commands.py` — **written**.

### Requirements
- Spec §12.3 rows verbatim, run **absolutely, not comparatively** (C10), against whatever corpus is
  currently published — the synthetic corpus always, `TC1E-SF` once U013 lands, plus the PARITY and
  negative-set rows once the legacy baseline (U012) is indexed.
- Spec §12.4: the L3 eval built in U006, surfaced as a command and **wired into CI on every commit**.
- Spec §12.2: both run at L2/L3 in **replay mode** — `VSIR_VLM=stub`; neither may call Gemini.
- Spec §4.4: `vsir eval acceptance | abstention | corpus` — `corpus` is U026's at M8.
- Both exit non-zero on any failing row; a failing L3 row means *the system has produced the injury
  the whole design exists to prevent* (Spec §12.4).

### Invariants Enforced
- None newly.

### Failure Rows Closed
- None newly — it is the runnable proof surface for F1, F2, F3, F4, F14 and F16.

### Dependencies
- **Depends On:** [U015, U012]
- **Enables:** [U026]
- **External:** ephemeral Qdrant; no API key.

### Acceptance Criteria
- [ ] `vsir eval acceptance` prints one row per §12.3 assertion with an explicit expected-vs-actual, and exits 0 against the published synthetic corpus.
- [ ] With the legacy baseline indexed, the PARITY rows and the `withheld.jsonl` negative rows appear in the same output, and a **GAINS** section lists codes the old grammar dropped.
- [ ] `vsir eval abstention` reports `abstention_correctness == 1.00` over `near_misses(n=100)` and exits 0.
- [ ] Mutating one near-miss assertion to fail makes `vsir eval abstention` exit non-zero and name the failing case.
- [ ] Both commands run with `GEMINI_API_KEY` unset and a network spy records zero outbound calls.
- [ ] The abstention eval is registered in CI and runs on every commit.
- [ ] Neither command mutates the index (asserted by a point-count and payload-hash comparison before and after).

### Test Plan
**Levels:** [L2, L3]
**Commands:** `bash scripts/test-api.sh -k eval_commands`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007), `data/fixtures/legacy/` (U012), `data/fixtures/TC1E-SF/` (U013, when present); ephemeral Qdrant; stub VLM.
**Edge Cases:** running before M2b (the real-text rows must **skip with a named reason**, not fail — Spec §13 M3 splits acceptance "always" from "once M2b exists"); a deliberately broken assertion.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the "skip before M2b" path becomes a permanent skip nobody notices. **Mitigation:** the skip must name the missing fixture and the command must print a summary count of skipped rows; U013's Definition of Done requires the skips to become passes.
- **Risk:** the eval is treated as sign-off for the ~70% of §7/§8 that has no legacy coverage (R7). **Mitigation:** stated in U012's risk register and in §8 below.

### Rollback Plan
N/A — read-only evaluation commands; no index state and no tool contract is changed.

---

## Unit: `skim_pages`, deterministic fusion, image queries, and `resolve` (ID: U017)

**Status:** 🟢 Complete (2026-09-10)
**Milestone:** M4
**Priority:** P0-Critical
**Type:** tool
**Size Estimate:** Large
**Spend:** none

### Goal
Build the page rung of the narrowing ladder with score-free deterministic ordering, `exclude`, the
`next` affordances and image queries — and `resolve`, which turns a printed label into a page.

### Working Deliverable
`POST /tools/skim_pages` and `POST /tools/resolve`, plus the `vsir skim` and `vsir resolve`
one-shots.

### Demo Command
```bash
vsir serve & sleep 2 && \
  vsir skim pages "emergency stop reset" --scope '{"doc_id":"TC1E-SF"}' && \
  vsir skim pages "emergency stop reset" --scope '{"doc_id":"TC1E-SF"}' && \
  vsir skim pages --image ./panel.jpg --scope '{"doc_id":"TC1E-SF"}' && \
  vsir resolve "Page 8 of 55"
```
The reviewer sees ≤10 triage rows with `rank`, `why`, `grounded_rate`, `text_trust` and an
`image.url` — **no full text and no `bytes_b64`** — the second call returning the identical order,
the image-only query returning rows whose `why` is exactly `["dense"]`, and `resolve` returning a
`page_id` with `label_verified` and `interpolated`.

### Deliverables (files)
- `backend/vsir/serve/tools/skim.py` — **extended** from U004's `rrf()`: **ported with changes** from
  `impl/app/retrieve.py::search` + `decompose`; the `skim_pages` rung, the three branches, the
  `exclude` set, the `next` affordances. The aggregate rungs arrive at M5 (U019).
- `backend/vsir/serve/tools/resolve.py` — **ported as-is** from `impl/app/retrieve.py::resolve`,
  keeping its `interpolated` disclosure.
- `backend/vsir/ingest/embed.py` — **extended**: `embed_query_image` wired to the skim path (D12).
- `backend/vsir/cli.py` — **extended**: `skim`, `resolve`.
- `backend/tests/api/test_skim_pages.py`, `test_ordering_determinism.py`, `test_image_query.py`,
  `test_resolve.py`, `test_stateless_scope.py` — **written**.

### Requirements
- Read `impl/app/retrieve.py` first (`search`, `rrf`, `decompose`, `resolve`). ⚠ Spec §2.5 A:
  `POST /api/v1/expand` is **removed as an endpoint** — the capability survives as `next.expand` plus
  a re-scoped skim. ⚠ Spec §20.1 **E9**: `find_by_printed_label` scrolls 4,096 points and filters in
  Python — *"falls over well before the 1,440-page manual"*. `resolve` must use **indexed facets**;
  I6 forbids filtering off-index.
- Spec §7.2.1 signature: `skim_pages(query, image=None, scope, exclude?, limit=10)`; `query` is
  optional **when `image` is given**, and vice versa. `limit` ≤ 10 by default, max 25.
- Spec §7.2.1 **ordering (normative and score-free)**: three branches run inside `scope` minus
  `exclude` — `page` (dense), `lexical` (sparse over the extracted text) and `captions` (sparse over
  generated text). `decompose(query)` splits exact identifiers out **first**, so a code goes to the
  phrase filter rather than being blurred into the embedding. Branches fuse by **RRF at `rrf_k=60`**
  with weights `page 1.0 · lexical 1.0 · captions 0.4`. **Only ranks enter the arithmetic; no score is
  computed, stored or returned.** `rank` is the 1-based ordinal of the fused list and `why` names
  every branch that contributed. *(See §8, SA-3: §7.2.1's "there is no sparse vector" parenthetical is
  stale — D2, §5.3 and the ordering rules all make `lexical` a sparse vector.)*
- Spec §7.2.1 **P2**: **no full text in a triage row.** Every page-level hit carries an `ImageRef`
  (`url`, `thumb_url`, `dpi`, `width`, `height`) — a **reference**, never bytes. `bytes_b64` exists
  only on `fetch`.
- Spec §7.2.1 **P4**: `next: {expand: section_id, neighbours: [page_id, …], references: [printed labels]}`.
- Spec §7.2.1 image queries (D12): the query vector comes from the ported
  `embed_query_image(image, text=query)` in **one `types.Content`**. Three rules: (1) **no instruction
  prefix when the query is multimodal**; (2) **an image-only query runs the dense branch alone** —
  `lexical` and `captions` are skipped, RRF degenerates to the dense ranking and every row's `why` is
  `["dense"]`, stated not silent; (3) **an image can never reach the exact surface** — `lookup` and
  `verify` take a text label only (I2, I3).
- Spec §7.2.3: `resolve(printed_label, doc_id?)` → `page_id` + `interpolated` + `label_verified`;
  **ambiguity returns every candidate** (F5).
- Spec §7.1 / C11: the service is **stateless**. `scope` and `exclude` are parameters and
  `effective_scope` is echoed back — this is F8's stateless half.
- Spec §16 Reproducibility: the same `(query, image, scope, exclude)` returns the same rows in the
  same order — this is what makes the E2E and L2 assertions stable.

### Invariants Enforced
- None newly.

### Failure Rows Closed
- **F5 (M4 half)** (follows a cross-reference to the wrong page) — an ambiguous printed label resolves to a **list** of candidates, never a silent pick — `test_resolve_ambiguous_returns_every_candidate` (L2).
- **F8 (stateless half)** (searches a subset believing it searched the chapter) — no server session; `effective_scope` echoed on every response — `test_effective_scope_echoed_no_server_session` (L2).

### Dependencies
- **Depends On:** [U015, U010]
- **Enables:** [U018, U019]
- **External:** Qdrant; the ported `embed_query_image` (stubbed by config at M4).

### Acceptance Criteria
- [x] `skim_pages` returns at most `limit` rows, `limit` defaults to 10 and is rejected above 25.
- [x] Two identical `(query, image, scope, exclude)` calls return the identical ordered list of `page_id`s, across two processes.
- [x] `rank` is a 1-based ordinal with no gaps, and **no response model in the fused path declares a field named `score`** (asserted by an AST scan, not a grep).
- [x] `why` on a row hit by both the dense and lexical branches is `["dense", "lexical"]`; on a lexical-only row it is `["lexical"]`.
- [x] `decompose("reset K158")` sends `K158` to the phrase filter and only `reset` to the embedding — asserted on the branch inputs.
- [x] RRF output matches a hand-computed `Σ w/(k + rank)` at `k=60` with weights `1.0 / 1.0 / 0.4` for a fixed set of branch rankings.
- [x] `exclude=[page_id_x]` never returns `page_id_x`, and the remaining order is unchanged apart from the removal.
- [x] **No triage row contains full page text, and no triage row contains `bytes_b64`** — an asserted test over the serialised response, not a convention.
- [x] Every page-level hit carries an `image.url` that returns 200 when dereferenced with a bearer token (the endpoint arrives in U018; until then, assert the URL's shape and that it names the `page_id` and a dpi from the allowed set).
- [x] Every hit carries `next` with `expand`, `neighbours` and `references`.
- [x] An **image-only** `skim_pages` (no `query`) returns rows whose `why` is exactly `["dense"]`, and the lexical/captions branches were not executed (asserted by a call spy).
- [x] A multimodal query sends **no instruction prefix** to the embedding model (asserted on the request payload).
- [x] `lookup` and `verify` reject an `image` parameter — an image can never reach the exact surface.
- [x] `resolve("<ambiguous label>")` returns **every** candidate with `label_verified` and `interpolated` per candidate.
- [x] `resolve` executes an indexed-facet query — a call spy asserts it never scrolls and filters in Python (E9).
- [x] `effective_scope` is echoed on every response and equals the requested scope after `is_current=True` injection.
- [x] `skim_pages(scope={"bogus": 1})` returns `filter_unknown_key {keys: ["bogus"]}`.

### Test Plan
**Levels:** [L2]
**Commands:** `bash scripts/test-api.sh -k "skim_pages or ordering_determinism or image_query or resolve or stateless_scope"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007) and `data/fixtures/TC1E-SF/` (U013, when present); ephemeral Qdrant; a stub embedding backend selected by config for the image-query path — **no Gemini call at L2**.
**Edge Cases (typed 4xx / §11.3):** `filter_unknown_key`; `limit=26`; an image-only query; a query that decomposes to identifiers only; an empty scope; `503 qdrant_unavailable`.

### Definition of Done
- [x] Acceptance criteria met
- [x] All planned tests implemented and passing, none skipped or xfailed
- [x] Demo command runs green and its output is recorded in the progress file
- [x] No new dependency added outside Spec §4.2
- [x] Conformance greps still pass

### Risks and Mitigations
- **Risk (R1, Spec §18):** recall is not guaranteed — a summary can omit the line that mattered. **Mitigation:** the `uncertain` pool and "do not filter a small set" (U021), `why: lexical` as a hard signal, and `searchable_ratio` (U019) — a miss surfaces as an honest abstention, never a wrong page.
- **Risk:** a builder adds a similarity score "just for debugging" and it reaches a response. **Mitigation:** Spec §7.6's grep plus the AST assertion above.

### Rollback Plan
- **If this unit must be reverted:** `skim_pages` and `resolve` are new tool contracts; revert them behind the current `schema_version` and keep `lookup`/`verify` untouched. No index state is written by this unit, so no collection, alias or point action is required.

---

## Unit: The page-image endpoint, the raster cache, and `fetch` (ID: U018)

**Status:** 🟢 Complete (2026-09-10)
**Milestone:** M4
**Priority:** P0-Critical
**Type:** tool
**Size Estimate:** Large
**Spend:** none

### Goal
Make the raster reachable — as a bearer-authenticated URL and as `fetch`'s optional bytes — with
every §7.3 bound enforced as a typed 400, and rendered on demand into an in-process cache that is
never a source of truth.

### Working Deliverable
`GET /pages/{page_id}/image`, `POST /tools/fetch`, and `vsir demo narrow` — the M4 milestone demo.

### Demo Command
```bash
vsir demo narrow
```
The reviewer sees one query narrow the fixture to `p001`/`p002` as triage rows carrying only
`ImageRef`s, then a `fetch` returning those two pages with `bytes_b64`, then a `region` crop at
`dpi=400`, then two deliberate failures: a 6-page fetch returning `fetch_budget_exceeded {limit: 5,
requested: 6}` and `dpi=400` **without** a region returning `dpi_requires_region`.

### Deliverables (files)
- `backend/vsir/serve/app.py` — **extended**: `GET /pages/{page_id}/image?dpi=&region=`, **ported**
  from `impl`'s `/api/v1/page-image/{page_id}`.
- `backend/vsir/serve/tools/fetch.py` — **written**, net new.
- `backend/vsir/serve/raster_cache.py` — **written**, net new: the in-process LRU. *(Not enumerated in
  Spec §4.1; required by §4.2 and §7.2.5 — see §8, SA-5.)*
- `backend/vsir/cli.py` — **extended**: `fetch`, `demo narrow`.
- `backend/tests/api/test_page_image.py`, `test_fetch.py`, `test_fetch_caps.py`,
  `test_raster_cache.py` — **written**.

### Requirements
- Read `impl/app/render.py` first (reused from U007's port for on-demand region rendering).
  ⚠ Spec §20.1 **A5**: `impl`'s `image_path` is broken so `read()` returns 503 for every page — there
  is no `image_path` here; rasters are re-rendered on demand. ⚠ **E3**: rendering is unconditional and
  never collected in `impl` — the cache added here must actually evict.
- Spec §7.2.5: `fetch(page_ids, include=["image","text","summary"], dpi=150, region=None, inline=True)`.
  `region` is normalised `[x0,y0,x1,y1]`; PyMuPDF renders the clip on demand — **no new storage**.
  `url` is **always present**; `bytes_b64` is present when `inline=true` (**default true**, because an
  agent needs the pixels in context and an MCP client cannot follow a URL). `inline=false` returns the
  reference only — that is what M7's console uses. Dropping `"image"` from `include` makes `fetch` a
  cheap text/summary read.
- Spec §7.3 caps, each a **typed 400, never a clamp, never a silent truncation**: `fetch` ≤ 5 pages
  **and** ≤ 12 MP total → `fetch_budget_exceeded {limit, requested}`; `dpi ∈ {36, 72, 150, 220, 300,
  400}` → `dpi_not_allowed` (36/72 are the triage thumbnail tiers behind `thumb_url`, 150 is `fetch`'s
  default, 220 is what `read` sees); `dpi > 220` requires `region` → `dpi_requires_region`.
- Spec §4.2 / §15 Factor VI: rasters are **never persisted** — an in-process LRU only, so a cold
  instance returns identical results, only slower. The cache is a **cache and never a source of
  truth**; it lives on the Dockerfile's writable `tmpfs`, never on a durable volume.
- Spec §7.4: `GET /pages/{page_id}/image` is bearer-authenticated and enforces the same caps and the
  same typed 400s as §7.3. Rasters are never returned without auth (Spec §16 Security). *(Auth is
  already in force: U014 made it default-deny middleware, so this path is refused without a token
  today, before the route exists. U018 adds the route, not the protection.)*
- **Finding from U014 — `ImageRef.url` is not percent-encoded and is therefore undereferenceable.**
  `serve/tools/lookup.py::image_ref` builds `/pages/{page_id}/image?dpi=150` by interpolation, and a
  `page_id` contains `#` (§5.1: `{doc_id}@{revision}#p{page_no}`), which a client parses as a
  fragment delimiter — so the path that actually reaches this route is `/pages/SYN-M1@1.0`. Spec
  §7.2.5's own example shows the encoded form, `/pages/TC1E-SF@1.3%23p001/image?dpi=150`. U018 owns
  the route and therefore owns the encoding: quote the `page_id` where the reference is built,
  unquote it in the path parameter, and add a round-trip assertion. Three existing assertions
  encode the current unencoded form and must move with it —
  `tests/api/test_acceptance_synthetic.py::test_every_hit_carries_an_image_reference_and_no_hit_carries_bytes`
  and `tests/unit/test_lookup_pure.py::test_a_hit_carries_an_image_reference_and_never_bytes`.
  Deliberately **not** fixed in U014: the encoding is half of a contract whose other half is this
  unit's route, and splitting it across two units would leave one release with neither.
- Spec §11.3: an over-budget `fetch` is a typed 400 naming the bound — **never a dpi clamp or a
  truncated page list**.
- Spec §15.1 Resource limits: raster rendering is the memory spike, and the ≤ 12 MP cap is what
  bounds it.

### Invariants Enforced
- None newly.

### Failure Rows Closed
- **F18 (fetch half)** (unbounded spend) — the §7.3 `fetch` caps, each a typed 400 naming its bound — `test_fetch_budget_exceeded_names_bound` and `test_dpi_requires_region` (L2).

### Dependencies
- **Depends On:** [U017, U007, **U029**]
- **Enables:** [U020, U021]
- **External:** PyMuPDF for on-demand clip rendering.
- ⚠ **This unit cannot be built until U029 exists.** The sentence that used to sit here — *"the
  source PDF must be reachable by the serving process"* — was an assumption stated as an external
  dependency, and **nothing in the system satisfied it**: a CLI ingest happens to work because the
  operator's copy is still on their filesystem, an upload's spool is deleted when the run exits, and
  neither the page payload nor the run record carries anything that names a file (register **A5**
  removed `image_path` deliberately). `page_id → bytes` is U029's one job; everything else in this
  unit — the URL shape, the `page_id` grammar and its parser, the dpi tiers, the `region` rule, the
  caps in `serve/caps.py`, the LRU renderer in `ingest/render.py` — is already decided or written.

### Acceptance Criteria
- [x] `GET /pages/{page_id}/image?dpi=150` with a bearer token returns 200 and an image payload; without a token it returns 401.
- [x] The same request twice within the cache's lifetime invokes the render function **once** (asserted by a call-count spy); after forcing eviction it renders again and returns a byte-identical image.
- [x] A filesystem-write spy confirms **no** raster is written outside the configured `tmpfs` cache path, and a cold process returns a byte-identical image for the same `(page_id, dpi, region)`.
- [x] `fetch` with 6 page_ids returns `fetch_budget_exceeded {limit: 5, requested: 6}` and **no** partial 5-page 200.
- [x] `fetch` whose resolved rasters exceed 12 MP returns `fetch_budget_exceeded` naming the megapixel bound — never a silent dpi clamp.
- [x] `fetch(dpi=100)` returns `dpi_not_allowed`; `fetch(dpi=36)` and `fetch(dpi=72)` succeed (the thumbnail tiers).
- [x] `fetch(dpi=400, region=None)` returns `dpi_requires_region`; the same call with a region succeeds and returns a crop.
- [x] `fetch(..., inline=True)` (the default) returns both `url` and `bytes_b64`; `inline=False` returns `url` and **no** `bytes_b64`.
- [x] `fetch(include=["text","summary"])` returns no image at all and performs zero renders.
- [x] `region` is normalised `[x0,y0,x1,y1]` and an out-of-range region is a typed 400, not a clipped guess.
- [x] `vsir demo narrow` exits 0 and its output contains the narrowing, the crop, and both deliberate typed 400s.

### Test Plan
**Levels:** [L2]
**Commands:** `bash scripts/test-api.sh -k "page_image or fetch or raster_cache"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007) plus its source PDF; `data/fixtures/TC1E-SF/` when present; ephemeral Qdrant; **no VLM** — `fetch` never calls a model.
**Edge Cases (typed 4xx / §11.3):** every §7.3 bound; a cold cache; an evicted entry; a region outside the page; 401; a page whose PDF is unreachable (a typed 5xx, never an empty result).

### Definition of Done
- [x] Acceptance criteria met
- [x] All planned tests implemented and passing, none skipped or xfailed
- [x] Demo command runs green and its output is recorded in the progress file
- [x] No new dependency added outside Spec §4.2
- [x] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the raster cache becomes a durable volume and quietly turns into a source of truth (§15.2 ban). **Mitigation:** the Dockerfile mounts it as `tmpfs`; the cold-process byte-identity criterion proves nothing depends on it.
- **Risk:** an over-budget request is clamped for convenience. **Mitigation:** Spec §11.3 forbids it; two acceptance criteria assert the typed 400 and the absence of a partial result.

### Rollback Plan
- **If this unit must be reverted:** `fetch` and `GET /pages/{page_id}/image` are new tool/route contracts — revert them behind the current `schema_version`; `ImageRef.url` values already emitted by `skim_pages` become dead links, so U017's `ImageRef` emission must be reverted in the same commit. No index state is written.

---

## Unit: `skim_documents`, `skim_sections`, and `searchable_ratio` (ID: U019)

**Status:** 🔵 Not Started
**Milestone:** M5
**Priority:** P0-Critical
**Type:** tool
**Size Estimate:** Medium
**Spend:** none — *inside a paid milestone but spends nothing; it is planned before U020 so the free rungs land before the paid one.*

### Goal
Complete the narrowing ladder with the two aggregate rungs — the same page query grouped differently
— and put `searchable_ratio` on every document row so the agent's blind spot is visible.

### Working Deliverable
`POST /tools/skim_documents` and `POST /tools/skim_sections`, exposed over HTTP and MCP.

### Demo Command
```bash
vsir serve & sleep 2 && \
  vsir skim documents "carton discharge" && \
  vsir skim sections "carton discharge" --scope '{"doc_id":"TC1E-SF"}'
```
The reviewer sees ≤10 document rows with `pages_matched`, `best_rank`, `searchable_ratio` and a
`preview.thumb_url` — including a `searchable_ratio: 0.00` row for an image-only binder that is
**still returned** — then ≤10 section rows with `page_range`.

### Deliverables (files)
- `backend/vsir/serve/tools/skim.py` — **extended**: the `skim_documents` and `skim_sections` rungs,
  aggregating the same fused candidates U017 already produces.
- `backend/vsir/core/health.py` — **extended**: `searchable_ratio` surfaced per document.
- `backend/vsir/mcp/server.py` — **extended**: the three skim rungs and `resolve`/`fetch` registered.
- `backend/tests/api/test_skim_aggregates.py`, `test_searchable_ratio.py` — **written**.

### Requirements
- Spec §7.2.1: `skim_documents(query, image=None, scope?, exclude?)` and
  `skim_sections(query, image=None, scope, exclude?)`. **One implementation exposed three times** —
  no second collection, no extra storage; the three rungs are *the same page query aggregated
  differently*. Aggregating by `doc_id` is also what stops one chatty document occupying every slot.
- Spec §7.2.1 aggregation: `pages_matched` = group size; `best_rank` = the best page rank in the
  group; rows ordered by `(best_rank, -pages_matched)`; ≤ 10 rows.
- Spec §7.1 hit models: `DocHit = {doc_id, title, doc_type, pages_matched, best_rank,
  searchable_ratio, summary, preview}`; `SectionHit = {section_id, title, page_range, pages_matched,
  best_rank, preview}`. **Neither carries a `page_id`** — they answer *"which binder?"* and *"which
  chapter?"* and hand back a **scope** to descend into via `next.expand`. Both carry a `preview`:
  the `thumb_url` of the group's **best-ranked matched page**, falling back to page 1 when nothing
  matched — that fallback is the useful case, because a `searchable_ratio: 0.00` row is the agent's
  blind spot and a thumbnail is how a person eyeballs an image-only binder without paying for a `read`.
- Spec §5.7: `searchable_ratio` = pages with `has_text` ÷ pages, **on every `skim_documents` row**.
- Spec §7.2.1 image queries apply to all three rungs (D12).
- Spec §7.6: no routing — the tool never picks the document for the caller; it returns the rows and
  the caller descends.

### Invariants Enforced
- None newly.

### Failure Rows Closed
- None newly (it is the surface that makes F4's disclosure visible at the document level).

### Dependencies
- **Depends On:** [U017]
- **Enables:** [U021]
- **External:** Qdrant.

### Acceptance Criteria
- [ ] `skim_documents` and `skim_sections` return ≤ 10 rows each, ordered by `(best_rank, -pages_matched)`.
- [ ] For a fixed query, the set of `doc_id`s from `skim_documents` equals the set of distinct `doc_id`s of the `skim_pages` rows for the same `(query, scope, exclude)` — proving one implementation, three aggregations.
- [ ] `pages_matched` equals the number of `skim_pages` rows in that group, and `best_rank` equals the minimum `rank` in it.
- [ ] Every `DocHit` carries a non-`None` `searchable_ratio`, and for a document with N pages of which M have text, `searchable_ratio == M / N` exactly.
- [ ] A fully scanned document has `searchable_ratio == 0.0` and is **still present** in the result set — never omitted.
- [ ] Every `DocHit` and `SectionHit` carries a `preview.thumb_url` pointing at the group's best-ranked matched page, falling back to page 1 when nothing matched.
- [ ] No `DocHit` or `SectionHit` carries a `page_id`, full text, or `bytes_b64`.
- [ ] Every row's `next.expand` returns a scope that, passed to the next rung down, reproduces exactly that group's pages.
- [ ] The same three rungs are callable over MCP and return byte-identical envelopes to HTTP.
- [ ] An image-only `skim_documents` returns rows whose contributing `why` values are all `["dense"]`.

### Test Plan
**Levels:** [L2]
**Commands:** `bash scripts/test-api.sh -k "skim_aggregates or searchable_ratio"`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/`, a generated fully-scanned document (from U011's gate fixtures), `data/fixtures/TC1E-SF/` when present; ephemeral Qdrant; no VLM.
**Edge Cases:** a fully scanned binder (`searchable_ratio == 0.0`); a group whose best-ranked page did not match (preview falls back to page 1); a scope matching no document (`out_of_scope`); more than 10 groups (assert the cut, and that `weak` is computed from `total`, not from the row count).

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the aggregates are implemented as a second query against a second collection, breaking the "same page query" guarantee and drifting from `skim_pages`. **Mitigation:** the set-equality acceptance criterion above makes divergence a test failure.
- **Risk:** an image-only binder is filtered out because it scores nothing, hiding the blind spot the row exists to expose. **Mitigation:** the `searchable_ratio == 0.0` row must still be returned — an explicit criterion.

### Rollback Plan
- **If this unit must be reverted:** two new tool contracts; revert behind the current `schema_version`, and revert the MCP registrations in the same commit. No index state is written.

---

## Unit: `read` — the paid step, with stamped codes and a question-keyed cache (ID: U020)

**Status:** 🔵 Not Started
**Milestone:** M5
**Priority:** P0-Critical
**Type:** tool
**Size Estimate:** Large
**Spend:** paid (read)

### Goal
Build the one tool that spends: a bounded, delegated vision read at the pinned dpi, with every
emitted code stamped in `verify`'s vocabulary, a mandatory `sufficient`, and a cache that a new
question always misses.

### Working Deliverable
`POST /tools/read` and `vsir read` — proved end to end in replay at zero cost, and demonstrated once
against real Gemini behind `VSIR_ALLOW_PAID=1`.

### Demo Command
```bash
VSIR_ALLOW_PAID=1 vsir read --pages "TC1E-SF@1.3#p001,TC1E-SF@1.3#p002" \
  --question "what must be true before the carton discharge restarts?"
```
The reviewer sees a `ReadResult` with a bounded `extract`, a per-code table stamped
`present`/`absent`/`unverifiable` (a deliberately misread code carrying `present_instead`),
`sufficient: true`, and `page_provenance` with each page's `text_trust`. Re-running the identical
call is a cache hit; changing the question is a **miss**; a fourth page is a typed 400.

### Deliverables (files)
- `backend/vsir/serve/tools/read.py` — **ported with changes** from `impl/app/retrieve.py::read`.
- `backend/vsir/vlm/prompts/read.md` — **written**, net new; versioned.
- `backend/vsir/vlm/cache.py` — **extended**: `read_key` (the `extract_key` inputs ‖ the question).
- `backend/vsir/cli.py` — **extended**: `read`.
- `backend/tests/unit/test_read_stamps.py` — **written**.
- `backend/tests/api/test_read_replay.py`, `test_read_caps.py`, `test_read_cache.py` — **written**.
- `backend/tests/paid/test_read_real.py` — **written**, L4, gated by `VSIR_ALLOW_PAID=1`.

### Requirements
- Read `impl/app/retrieve.py::read` first, and `impl/pipeline-guide/METADATA-CONTRACT.md` for the
  `page_provenance` shape. ⚠ Spec §20.1 **A5**: in `impl`, `read()` returns 503 for every page because
  `image_path` is broken — here the raster is re-rendered on demand (U018's path).
- Spec §7.2.6: `read(page_ids, question)` renders at the **pinned `dpi_answer = 220`** — a caller
  cannot change it, because the dpi is part of `read_key`.
- Spec §7.2.6 **Loop 1, automatic and always**: every code the vision model emits is phrase-checked
  against that page's text and stamped with the **same three states `verify` uses** —
  `present | absent | unverifiable`. One vocabulary, one meaning. On a page with **no text layer,
  every code is `unverifiable`** — the honest answer. Uses `core/verify.py` (U006), not a second
  implementation.
- Spec §7.2.6: `sufficient` is **mandatory** — without it the agent cannot separate *"the answer is
  no"* from *"wrong page"*. **Retrieval judgment never happens inside `read`** — that would make the
  engine the answerer (§7.6).
- Spec §6.3: `read_key = extract_key inputs ‖ question` — **a new question is a cache miss** (F19).
- Spec §7.3: `read` page images per call **≤ 3** → `read_page_cap_exceeded` (a deliberate tightening
  from `impl`'s 4, Spec §2.4); per-caller `read` quota → `429 budget_exhausted`.
- Spec §11.3: Gemini unreachable → `503 vlm_unavailable` on `read`; **every free tool keeps working**.
- Spec §12.2: only this unit and U013/U022/U026 may plan an L4 test, gated behind `VSIR_ALLOW_PAID=1`.
  Every other level runs in replay off `data/fixtures/synthetic_3window/`, upgrading to
  `data/fixtures/TC1E-SF/` when U013 lands.
- Spec §7.4: one append-only audit line per `read` (U014's), and cost stays in the audit log.

### Invariants Enforced
- None newly (I8 is U022's; this unit provides one of its inputs).

### Failure Rows Closed
- **F18 (read half)** (unbounded spend) — the ≤ 3-page cap as a typed 400 naming the bound — `test_read_page_cap_exceeded` (L2).
- **F19** (a second question about the same pages returns the first answer) — `read_key` includes the question — `test_new_question_is_a_cache_miss` (L2).

### Dependencies
- **Depends On:** [U018, U008, U006, **U029**]  *(read reasons over a raster, so it inherits U018's
  source-document dependency)*
- **Enables:** [U022]
- **External:** **OQ-2** a Gemini key for the L4 test only; Qdrant; the raster path from U018.

### Acceptance Criteria
- [ ] `read` renders at dpi **220** regardless of any caller-supplied dpi; passing a dpi parameter is rejected or ignored, and the rendered dpi is recorded in `read_key`.
- [ ] A code the emitted extract names that the page's text contains is stamped `present`; one the text does not contain is stamped `absent` **with** `present_instead`; on a page with `has_text == False` **every** code is stamped `unverifiable`.
- [ ] The stamping calls `core/verify.py::verify_claims` — an import-graph assertion proves there is no second phrase-check implementation.
- [ ] `sufficient` is present on every `ReadResult` and is `False` when the pages do not answer the question (asserted with a fixture whose pages are deliberately wrong).
- [ ] `page_provenance` lists every requested page with its `text_trust`.
- [ ] An AST scan finds no retrieval decision inside `read.py` — it never chooses which page to read.
- [ ] Two identical `(page_ids, question)` calls make **one** VLM call (cache hit, asserted by a call-count spy).
- [ ] The same `page_ids` with a **different** question makes a **second** VLM call — a cache miss (F19).
- [ ] `read` with 3 pages succeeds; with 4 it returns `read_page_cap_exceeded` naming the bound, and makes **zero** VLM calls.
- [ ] A caller at `reads_remaining == 0` gets `429 budget_exhausted` and makes zero VLM calls.
- [ ] With the VLM backend unreachable, `read` returns `503 vlm_unavailable` while `lookup`, `verify`, `skim_*`, `resolve` and `fetch` all still return 200.
- [ ] Every L0–L2 test above passes with `VSIR_VLM=stub` and `GEMINI_API_KEY` unset; a network spy records zero outbound calls.
- [ ] (**L4, gated**) One real `read` against the frozen `TC1E-SF` pages under `VSIR_ALLOW_PAID=1` produces stamps that match the human-verified entry in `expected.json`, and the failure branch stamps a genuinely ambiguous code `unverifiable`, never falsely `present`.

### Test Plan
**Levels:** [L0, L2, L4]
**Commands:** `bash scripts/test-unit.sh -k read_stamps` · `bash scripts/test-api.sh -k "read_replay or read_caps or read_cache"` · `VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh -k read_real`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007), `data/fixtures/TC1E-SF/` (U013) — replayed via `VSIR_VLM=stub` + `VSIR_FIXTURE` for L0–L2; real Gemini **only** in the gated L4 test.
**Edge Cases (typed 4xx / §11.3):** `read_page_cap_exceeded`; `429 budget_exhausted`; `503 vlm_unavailable`; a page with no text layer (all codes `unverifiable`); `sufficient: false`; a `fixture_miss` in replay.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk (OQ-2):** no Gemini key exists. **Mitigation (Spec §17 default):** everything but the L4 test ships and is green in replay; the paid demo is deferred and named as deferred in the progress file. The unit is code-complete without it.
- **Risk (R2, Spec §18):** on a scanned page every code is `unverifiable` forever. **Mitigation:** that is the honest answer and the badge is the deliverable; M7 renders it and §11.2 requires the zoom-and-re-read before such a page may support an answer.
- **Risk:** a caller escalates dpi to "read better" and silently changes `read_key`. **Mitigation:** the dpi is pinned server-side and not a parameter — an acceptance criterion.

### Rollback Plan
- **If this unit must be reverted:** `read` is a new paid tool contract; revert behind the current `schema_version` and purge `read_key` cache entries for the affected prompt version. No index state is written, so no collection or point action is required.

---

## Unit: Tri-state triage, the safeguards, and fetch-vs-read routing (ID: U021)

**Status:** 🔵 Not Started
**Milestone:** M6
**Priority:** P0-Critical
**Type:** runner
**Size Estimate:** Medium
**Spend:** none — *inside a paid milestone but spends nothing: triage and routing are decided before any money moves (Spec §8.2, "for free, before any money is spent").*

### Goal
Build Loop 0 — the cheapest correction — as a real state machine with all five binding safeguards,
plus the deliberate `fetch`-versus-`read` routing decision, and prove both without a paid call.

### Working Deliverable
`vsir ask --explain "<question>"` — runs the narrowing and triage and prints the plan, the tri-state
marks and the route per candidate, spending nothing.

### Demo Command
```bash
vsir ask --explain "the carton discharge won't restart after an E-stop reset"
```
The reviewer sees the descent (`skim_documents` → `skim_sections` → `skim_pages`), a triage table
marking every candidate `relevant` / `uncertain` / `irrelevant` with the reason, the `exclude` set
that would go to the next skim, and the chosen route per page — with a spy line confirming **zero**
paid calls.

### Deliverables (files)
- `backend/vsir/runner/triage.py` — **written**, net new: the tri-state marker and the five safeguards.
- `backend/vsir/runner/prompt.py` — **written**, net new: the system prompt of Spec §8, with the
  tri-state rule and the safeguards **binding**.
- `backend/vsir/runner/route.py` — **written**, net new: the §8.1a `fetch`-vs-`read` decision.
- `backend/vsir/cli.py` — **extended**: `ask --explain`.
- `backend/tests/unit/test_triage.py`, `test_safeguards.py`, `test_route.py` — **written**.
- `backend/tests/api/test_ask_explain.py` — **written**.

### Requirements
- Spec §8.2: every skim candidate is marked `relevant | uncertain | irrelevant` **from its summary,
  for free, before any money is spent**. `relevant` → proceed to the look step; `uncertain` → the
  **fallback pool**; `irrelevant` → `exclude` on subsequent skims. **Binary marking is forbidden** —
  it discards the fallback pool and forces a re-skim from scratch.
- Spec §8.2 the five safeguards, all binding on the system prompt **and** on the state machine:
  (1) **rejections stay soft** — on `sufficient: false`, try the `uncertain` pool **before** widening
  scope; (2) **do not filter a small set** — with ≤ 3 candidates, read them all; (3) **use `why` as a
  signal** — a `lexical` hit on an exact code outranks a dense-only hit; (4) **auto-promote exact
  hits** — the query contains an exact identifier **and** the hit's `why` is `lexical` → bypass triage;
  (5) **tri-state is mandatory**.
- Spec §8.1a routing: **the default is `fetch`** — when the runner is itself vision-capable it looks
  at the page. `read` is for **delegation**: a cheap bounded sub-answer, keeping the agent's context
  small, or a caller that is not vision-capable. The routing decision itself makes **no** VLM call.
  *(See §8, SA-4: §8.2's "`relevant` → `read`" is the generic verb; §8.1a's bolded "Default: `fetch`"
  governs the route.)*
- Spec §8.1a **the safety consequence**: on the `fetch` route Loop 1's automatic per-code stamping
  does **not** happen — which is exactly why U022's answer gate is server-side and unconditional.
- Spec §8.2: triage marks (`query → page → relevant?`) are written to **telemetry as free evaluation
  data — never as a mandatory tool call**.
- Spec §8.1: on an empty triage, branch on coverage — scope **was** searchable → abstain naming what
  was searched; pages have **no text** → `fetch`/`read` the image-only pages first.

### Invariants Enforced
- None newly (I8 is U022's).

### Failure Rows Closed
- None.

### Dependencies
- **Depends On:** [U019, U018]
- **Enables:** [U022]
- **External:** the free tools from U015/U017/U018/U019; no VLM.

### Acceptance Criteria
- [ ] `triage.mark(hit)` returns exactly one of `"relevant"`, `"uncertain"`, `"irrelevant"` for every candidate, and the `uncertain` pool is retained, not discarded.
- [ ] Marking is derived from the row's `summary`, `why`, `grounded_rate` and `text_trust` — **never** from full page text (a triage row has none) and never from a paid call: a call spy records zero `read` invocations across a full `--explain` run.
- [ ] Safeguard 2: with ≤ 3 candidates, triage marks **none** `irrelevant` — all are carried forward.
- [ ] Safeguard 3: given two candidates with equal rank, the one whose `why` contains `"lexical"` is ordered above the dense-only one.
- [ ] Safeguard 4: a query containing an exact identifier whose hit has `why == ["lexical"]` **bypasses triage entirely** and is marked `relevant` without evaluation.
- [ ] Safeguard 1 is representable: on `sufficient: false`, the next state is "drain the `uncertain` pool", not "widen scope" (asserted on the state machine's transition table).
- [ ] `irrelevant` candidates appear in the `exclude` argument of the next skim, and never in its results.
- [ ] The default route for a `relevant` candidate is `fetch`; `read` is chosen only when the routing inputs say the caller is not vision-capable or the context budget demands delegation — asserted with both input shapes.
- [ ] The routing decision makes zero VLM calls (call spy).
- [ ] `runner/prompt.py` produces a byte-identical prompt for identical inputs, and the prompt text contains all five safeguards.
- [ ] Triage marks are emitted to telemetry; no tool call is required to record them (asserted by running with the telemetry sink disabled — the loop still proceeds).
- [ ] `vsir ask --explain` exits 0, prints the triage table and the routes, and spends nothing.

### Test Plan
**Levels:** [L0, L2]
**Commands:** `bash scripts/test-unit.sh -k "triage or safeguards or route"` · `bash scripts/test-api.sh -k ask_explain`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007) and `data/fixtures/TC1E-SF/` (U013, when present); ephemeral Qdrant; stub VLM — **no Gemini**.
**Edge Cases:** exactly 3 candidates (safeguard 2 boundary); an exact-identifier query (safeguard 4); an empty triage with `searchable_ratio == 1` (abstain) versus `< 1` (escalate to vision); a candidate with `text_trust == "untrusted"`.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk (R1, Spec §18):** a summary omits the line that mattered and triage marks the right page `irrelevant`. **Mitigation:** the `uncertain` pool, "do not filter a small set", and `why: lexical` as a hard signal — a miss becomes an honest abstention, never a wrong page.
- **Risk (R6, Spec §18):** the safeguards live only in the prompt and a careless MCP client ignores them. **Mitigation:** Spec §8.2 makes tri-state mandatory **in the runner's state machine as well as the prompt**, and the acceptance criteria assert the state machine, not the prompt text alone.

### Rollback Plan
N/A — the runner composes nothing at this unit; no tool contract and no index state changes.

---

## Unit: The loop, the six correction loops, the answer gate, and `POST /ask` (ID: U022)

**Status:** 🔵 Not Started
**Milestone:** M6
**Priority:** P0-Critical
**Type:** runner
**Size Estimate:** Large
**Spend:** paid (read)

### Goal
Close the loop: drive triage through `fetch`/`read`/`verify`, run all six correction loops, and put
the **server-side, unconditional** answer gate in front of the only surface allowed to return prose.

### Working Deliverable
`POST /ask` and `vsir ask` — the M6 milestone demo — with the answer gate rejecting any code
`verify` did not clear for the page it is cited on.

### Demo Command
```bash
VSIR_ALLOW_PAID=1 vsir ask "the carton discharge won't restart after an E-stop reset"
```
The reviewer sees the move-by-move trace (descend → triage → look → draft → verify), then a gated
answer citing `p001–p002` with each code badged `verified` or *read from image, not text-verified* —
and, on the failure branch, an abstention that **names the coverage numbers** and never says *"not in
these documents"* while unread image-only pages remain.

### Deliverables (files)
- `backend/vsir/runner/loop.py` — **written**, net new: Spec §8.1's loop and Spec §8.3's six
  correction loops.
- `backend/vsir/runner/answer.py` — **written**, net new: the server-side answer gate and the
  constrained abstention wording.
- `backend/vsir/serve/app.py` — **extended**: `POST /ask` (bearer) — the **only** surface that may
  return prose.
- `backend/vsir/cli.py` — **extended**: `ask`.
- `backend/tests/unit/test_answer_gate.py`, `test_abstention_wording.py` — **written**.
- `backend/tests/api/test_ask_replay.py`, `test_correction_loops.py`, `test_ask_near_miss.py` — **written**.
- `backend/tests/paid/test_ask_real.py` — **written**, L4, gated by `VSIR_ALLOW_PAID=1`.

### Requirements
- Spec §8.1's three structural properties must be visible in the code: narrowing is the same move at
  three zoom levels; **the expensive step happens once, late, after free narrowing**; verification
  happens **after** drafting, not before.
- Spec §8.3, all six loops: **0** candidate looks wrong in triage → mark `irrelevant`, `exclude`
  (U021's, orchestrated here); **1** a code was misread → stamped `absent` **inside `read`**,
  automatic (U020's); **2** about to assert a claim → `verify(claims, page_ids)` after `read`,
  deliberate; **3** `sufficient: false` → try `uncertain`, then widen and re-skim; **4** `verify`
  contradicts the draft → try a different page; **5** nothing found **and** `searchable_ratio < 1` →
  `fetch`/`read` the image-only pages and `lookup(include_unverified=True)`.
- Spec §8.4 the answer gate — **server-side and unconditional**, per `(claim, page)`:
  `present` → render; `unverifiable` → render **with the badge** *"read from image, not
  text-verified"*; anything else → **reject the draft**, carrying `present_instead`.
  This is unconditional precisely because the default `fetch` route skips Loop 1's automatic stamp
  (§8.1a) — *a `fetch`-first runner without the gate would be the fastest path to the one failure
  §1.1 exists to prevent.*
- Spec §8.4 budget: `VSIR_READS_PER_QUESTION` (default **3**) is a hard ceiling, reported as
  `reads_remaining` and exhausted as `429 budget_exhausted` — **never a silent extra call and never an
  answer composed from a page the model said did not answer.** One paid `read` is the target and the
  worked trace achieves it; Loop 3 legitimately spends a second.
- Spec §8.5: *"Not in these documents"* is **forbidden** while
  `pages_no_text_read < scope_stats.pages_no_text`. The honest wording names the gap — the documents
  searched and the count of image-only pages not examined.
- Spec §7.6 / §11.2: only the runner composes, and only behind the gate. Codes appear only as
  `verify` cleared them; a page whose `text_trust != ok` may support an answer only after a
  zoom-and-re-read, and its codes carry the *read from image* badge.
- Spec §7.4: `POST /ask` is bearer-authenticated and is the only prose surface.
- Spec §12.2: L0–L3 run in replay (`VSIR_VLM=stub` + `VSIR_FIXTURE`); the single L4 test is gated
  behind `VSIR_ALLOW_PAID=1`.

### Invariants Enforced
- **I8** — every asserted code is verified against the page it is cited on: the answer gate runs per `(claim, page)` on every code in the draft, on **both** routes, before any prose is rendered.

### Failure Rows Closed
- None newly — M6 owns no failure row; it owns I8, the invariant that makes every earlier guard reach the answer.

### Dependencies
- **Depends On:** [U021, U020]
- **Enables:** [U023, U025]
- **External:** **OQ-2** a Gemini key for the L4 test only; every tool from M3–M5.

### Acceptance Criteria
- [ ] `POST /ask` requires a bearer token and is the only route in the app that returns prose (asserted by scanning every route's response model).
- [ ] For every code in a rendered answer, a `verify([code], [cited_page_id])` call was made and returned `present` or `unverifiable` — asserted by a call log, not by inspecting the prose.
- [ ] A draft containing a code that `verify` returns `absent` for is **rejected, not rendered**: the code does not appear in the response body, and the rejection carries `present_instead`.
- [ ] A code returning `unverifiable` **is** rendered, carrying the badge *"read from image, not text-verified"*.
- [ ] The gate runs on the `fetch` route as well as the `read` route (asserted by forcing each route with the same draft).
- [ ] Each of the six correction loops fires under a crafted fixture scenario and terminates within a bounded iteration count — six independently named tests.
- [ ] Loop 3 on `sufficient: false` drains the `uncertain` pool **before** widening scope (asserted on the call order).
- [ ] Loop 5 fires only when nothing was found **and** `searchable_ratio < 1`, and issues both a vision escalation and `lookup(include_unverified=True)`.
- [ ] On the worked-trace fixture the loop completes in **exactly one** paid `read` and cites `p001–p002` (asserted by a `read` call-count spy in replay).
- [ ] `VSIR_READS_PER_QUESTION=1` makes a question that needs two reads return `429 budget_exhausted` rather than composing an answer from a page that said it did not answer.
- [ ] `reads_remaining` is present and correct on every response.
- [ ] The failure branch abstains **with coverage numbers** — naming the documents searched and the count of image-only pages not examined — and the literal string *"not in these documents"* is **absent** whenever `pages_no_text_read < scope_stats.pages_no_text`.
- [ ] Feeding all 100 `near_misses(n=100)` (U006) as questions never produces an answer citing the fake code.
- [ ] Every assertion above passes with `VSIR_VLM=stub` and `GEMINI_API_KEY` unset; a network spy records zero outbound calls.
- [ ] (**L4, gated**) One real `VSIR_ALLOW_PAID=1 vsir ask` on the worked trace produces the same citations as the replay run, and one deliberately unanswerable question abstains with coverage numbers rather than fabricating.

### Test Plan
**Levels:** [L0, L2, L3, L4]
**Commands:** `bash scripts/test-unit.sh -k "answer_gate or abstention_wording"` · `bash scripts/test-api.sh -k "ask_replay or correction_loops or ask_near_miss"` · `VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh -k ask_real`
**Fixtures/Stubs:** the worked-trace fixture over `data/fixtures/synthetic_3window/`, upgraded to `data/fixtures/TC1E-SF/` when U013 lands; ephemeral Qdrant; stub VLM for L0–L3; real Gemini only in the gated L4 test.
**Edge Cases (typed 4xx / §11.3):** `429 budget_exhausted` at the read ceiling; `503 vlm_unavailable` mid-loop (must surface as `error`, **never** as an abstention); a draft whose every code is rejected; an all-`unverifiable` page; an empty triage on a fully searchable scope.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** a backend failure is turned into an abstention, converting our outage into the agent's fabricated absence. **Mitigation:** Spec §7.1 — `error` means retry/report, **never abstain**; an explicit edge case above asserts a mid-loop 503 surfaces as `error`.
- **Risk:** the gate is moved into the prompt "for latency". **Mitigation:** Spec §8.4 and D7 make it server-side and unconditional; the acceptance criteria assert the `verify` call log, which a prompt-level gate cannot produce.
- **Risk (OQ-2):** no key for the L4 test. **Mitigation (Spec §17 default):** the entire loop is provable in replay; only the paid demo defers.

### Rollback Plan
- **If this unit must be reverted:** `POST /ask` is the only prose surface — removing it removes the product's answer path, so revert the route and the CLI subcommand together behind the current `schema_version`. No index state is written; no collection or point action is required.

---

## Unit: The operator console — viewer, agent panel, trust badges (ID: U023)

**Status:** ✅ Complete (2026-09-11)
**Milestone:** M7
**Priority:** P1-High
**Type:** frontend
**Size Estimate:** Large
**Spend:** none (fixture-backed replay)

### Goal
Build the two-zone console that makes the loop legible: the page on the left, the agent's moves and
the badged draft on the right, driven entirely by replayed data.

### Working Deliverable
A running Vite app serving the two-zone console against a replay-mode backend.

### Demo Command
```bash
VSIR_VLM=stub VSIR_FIXTURE=data/fixtures/synthetic_3window vsir serve & \
  npm --prefix frontend run dev
```
Browsing `http://localhost:5173`, the reviewer sees the left zone showing a page raster with
zoom-ladder breadcrumbs and a region zoom at escalated dpi, and the right zone showing collapsible
agent moves, the tri-state triage panel, and a draft answer whose codes carry `verified` /
*read from image* / `unverifiable` badges — with an amber verification warning where one applies.
Clicking a code scrolls the viewer to its cited page.

### Deliverables (files)
- `frontend/` — **written**, net new: React + TypeScript + Vite (no `impl` ancestor; `impl`'s HTML UI
  is explicitly **not ported**, Spec §2.5 A).
- `frontend/src/components/Viewer/*` — breadcrumbs, the high-res page viewer, region zoom.
- `frontend/src/components/AgentPanel/*` — collapsible moves, the triage panel, the badged draft.
- `frontend/src/api/*` — the typed client generated from / matched to `serve/envelope.py`.
- `frontend/src/**/*.test.ts` — **written**: badge mapping and citation-scroll logic.
- **The backend half of the panel:** `backend/vsir/runner/loop.py` — **extended**: a typed
  `TriageTable` / `TriageRow` (`page_id`, `mark`, `reason`, `rank`, `why`, `matched`, `promoted`)
  carried on `Outcome`, built from the last triage pass and the loop's cumulative `excluded` list;
  `backend/vsir/serve/app.py` — **extended**: one additive `triage` field on `AskResponse`, `null`
  when nothing was triaged (the submitted-draft route, or an abstention before any candidate);
  `backend/tests/api/test_ask_triage_table.py` — **written**: the table is the marks the loop really
  made, and the `exclude` set is the `irrelevant` page ids. **Additive only** — no new tool, no
  second dispatcher, no change to any existing field, and **no `score`** (§7.6).

### Requirements
- Spec §13 M7: runs in **replay mode (D10) — no Gemini, no key, no spend** — against whichever fixture
  exists: `TC1E-SF` if OQ-1 is answered, otherwise `synthetic_3window`.
- Spec §13 M7 / §7.1: it consumes `image.url` and `preview.thumb_url` **directly**, with
  `inline=false`, so binder and chapter cards show thumbnails **with no extra endpoint and no base64
  in the skim payload**.
- Spec §13 M7 **left zone**: zoom-ladder breadcrumbs, the high-res page viewer, region zoom at
  escalated dpi (the `dpi > 220 requires region` rule of §7.3 applies to what it requests).
- Spec §13 M7 **right zone**: collapsible agent moves (skim / read / verify), the tri-state triage
  panel, the draft answer with **trust badges** (`verified` / *read from image* / `unverifiable`) and
  amber verification warnings. **Clicking a code in the draft scrolls the viewer to its cited page.**
- Spec §13 M7 / §8.2: the triage panel is driven by the typed `triage` table on the `POST /ask`
  body, **never by parsing a trace `Move.detail`** — a console that regexes prose is a second
  declaration of the contract, and the `exclude` set's page ids are not in the body at all.
- Spec §16 Frontend: colours via CSS variables or utilities, **no raw hex in components**; lists of
  more than 50 items **virtualized**; **no `any`** in new TypeScript.
- Spec §16 Security: rasters are never returned without auth — the browser must send the bearer token.
- Spec §15 Factor III: the API base URL is configuration (`VITE_API_URL`), never a literal.

### Invariants Enforced
- None (M7 asserts none; the console **renders** I8's outcome, it does not enforce it).

### Failure Rows Closed
- None.

### Dependencies
- **Depends On:** [U022]
- **Enables:** [U024]
- **External:** Node/npm, Vite; the backend's HTTP surface; the existing `e2e/playwright.config.ts`.

### Acceptance Criteria
- [ ] The console runs with `VSIR_VLM=stub` and `GEMINI_API_KEY` unset; a browser network log shows **zero** requests to any Gemini endpoint.
- [ ] Every skim response the console consumes is requested with `inline=false`, and no rendered payload contains `bytes_b64` (asserted on the network log).
- [ ] Binder and chapter cards render thumbnails from `preview.thumb_url` with no additional endpoint call beyond the image `GET`.
- [ ] A page-level hit's `image.url` renders in the viewer, and requesting a region at `dpi=400` includes a `region` parameter (a request without one is not issued).
- [ ] The draft renders a distinct badge for each of `verified`, *read from image, not text-verified*, and `unverifiable`; the badge for `not_searchable` is distinct from the badge for `not_found`.
- [ ] A code the answer gate rejected is **absent** from the rendered draft.
- [ ] An amber verification warning appears exactly when a rendered code carries the *read from image* badge.
- [ ] Clicking a cited code scrolls the left viewer to that code's cited page.
- [ ] `POST /ask` returns a typed `triage` table whose rows carry the mark, the reason it was given and the terms it was matched on, and whose `exclude` is exactly the `irrelevant` page ids.
- [ ] The console's triage panel renders all three states and that `exclude` set **from that field**, not from a trace `Move.detail`.
- [ ] A `tsc --noEmit` run passes and an AST scan finds no `any` in `frontend/src/**`.
- [ ] A style scan finds no raw hex colour in a component; a list of >50 rows is virtualized (asserted on the rendered DOM node count).

### Test Plan
**Levels:** [L0]
**Commands:** `npm --prefix frontend test` (badge mapping, citation-scroll logic, the typed client)
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007), upgraded to `data/fixtures/TC1E-SF/` when present; the replay-mode backend. Browser-level behaviour is U024's.
**Edge Cases:** a draft with zero renderable codes (all rejected); a `searchable_ratio: 0.00` binder card; a page with no text layer; a `503` from the backend (a banner, never a blank page).

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the console is the first real consumer of `inline=false`, `thumb_url` and the badge fields, built four milestones after those envelopes were frozen — contract mismatches surface only here. **Mitigation:** generate the frontend's typed client from `serve/envelope.py` and pin it by `schema_version`, so a mismatch is a compile error rather than a runtime surprise.
- **Risk:** the console silently requests `inline=true` and moves megabytes through JSON twice. **Mitigation:** the network-log acceptance criterion.

### Rollback Plan
N/A — the console consumes the API and writes no state; reverting it removes a surface without touching the index or any tool contract.

---

## Unit: The Playwright replay suite and `scripts/test-e2e.sh` (ID: U024)

**Status:** ✅ Complete (2026-09-11)
**Milestone:** M7
**Priority:** P1-High
**Type:** harness
**Size Estimate:** Medium
**Spend:** none

### Goal
Drive the worked trace through the console in replay mode with assertions that hold on **either**
fixture, and make `bash scripts/test-e2e.sh` the M7 milestone demo.

### Working Deliverable
`bash scripts/test-e2e.sh` — brings up the replay stack and runs the Playwright suite headless.

### Demo Command
```bash
bash scripts/test-e2e.sh
```
Then browsing `http://localhost:5174`, the reviewer sees the same console state the suite asserted:
an `unverifiable` code rendered with its badge, a rejected code **absent** from the answer, and an
abstention naming the unread image-only pages.

### Deliverables (files)
- `e2e/tests/*.spec.ts` — **written**, extending the existing `e2e/` directory.
- `e2e/playwright.config.ts` — **extended**: base URL `http://localhost:5174`, headless CI reporter.
- `scripts/test-e2e.sh` — **extended**: bring up `docker-compose.test.yml` (backend `8001`, Qdrant
  `6335`, frontend `5174`) in replay mode, wait for `/ready`, run Playwright, tear down with `down -v`.
- `frontend/Dockerfile` — **written**: the test image serving the built console on `5173` internally,
  published on `5174`.

### Requirements
- Spec §13 M7: a Playwright test drives the worked trace **in replay mode** and asserts that an
  `unverifiable` code renders with its badge, that a **rejected code is absent from the rendered
  answer**, and that the abstention text names the unread image-only pages.
  **The assertions are fixture-independent, so they pass on the synthetic fixture too.**
- Spec §12.2: E2E needs docker, runs in minutes, and is driven by `scripts/test-e2e.sh`.
  **E2E must never call Gemini** — `VSIR_VLM=stub` + `VSIR_FIXTURE`.
- Spec §4.2 ports: backend test `8001`, Qdrant test `6335` (never `6334`), frontend test `5174`.
- Spec §15 Factor X: the compose stack runs **the same backend image as production**, differing only
  in env and ports.

### Invariants Enforced
- None.

### Failure Rows Closed
- None.

### Dependencies
- **Depends On:** [U023]
- **Enables:** []
- **External:** Playwright, Docker Compose, the production backend image from U001.

### Acceptance Criteria
- [ ] `bash scripts/test-e2e.sh` brings up the stack, waits for `/ready`, runs the suite headless, tears down with `down -v`, and exits non-zero on any failed assertion.
- [ ] The suite passes against `VSIR_FIXTURE=data/fixtures/synthetic_3window` **and**, when present, against `data/fixtures/TC1E-SF` — with **no fixture-specific literals** in the assertions.
- [ ] A code carrying `unverifiable` renders with its badge, asserted on the DOM.
- [ ] A code the answer gate rejected is **absent** from the rendered answer, asserted on the DOM text.
- [ ] The abstention text names the unread image-only pages and does **not** contain *"not in these documents"* when unread image-only pages remain.
- [ ] A network assertion confirms **zero** requests to any Gemini endpoint for the whole suite run.
- [ ] Stopping the Qdrant container mid-session and issuing a query renders a retry banner — never a blank page and never an unhandled exception.
- [ ] The compose stack binds Qdrant on `6335`, the backend on `8001` and the frontend on `5174`, and uses the same backend image tag as production (never `latest`).

### Test Plan
**Levels:** [E2E]
**Commands:** `bash scripts/test-e2e.sh`
**Fixtures/Stubs:** `data/fixtures/synthetic_3window/` (U007) and `data/fixtures/TC1E-SF/` (U013, when present); the replay-mode backend; ephemeral Qdrant from `docker-compose.test.yml`. **No Gemini.**
**Edge Cases (§11.3):** Qdrant stopped mid-session (banner, not blank); a `429 budget_exhausted` surfaced in the UI; a `read_page_cap_exceeded` surfaced as a message rather than a crash.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the assertions bake in `TC1E-SF` content and break on the synthetic fixture, contradicting the M7 acceptance. **Mitigation:** the fixture-independence criterion runs the suite against both fixtures in CI.
- **Risk:** the E2E stack drifts from production by using a test-only image. **Mitigation:** Factor X — the compose file references the same image tag; asserted above.

### Rollback Plan
N/A — a test harness; no product surface, tool contract or index state is affected.

---

## Unit: Revisions, resumable ingest, and graceful shutdown (ID: U025)

**Status:** ✅ Complete (2026-09-11)
**Milestone:** M8
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Large
**Spend:** none — *inside a paid milestone but provable end to end with the stub VLM on a generated large PDF (Spec §6.2).*

### Goal
Make the index survive time and interruption: a second revision that supersedes without deleting,
`series_id` that holds across revisions, and a `SIGTERM` that loses at most one window.

### Working Deliverable
`vsir ingest --resume <run_id>`, `vsir retire <doc_id> [--revision]`, and the
`found_only_in_superseded` status reaching the caller.

### Demo Command
```bash
vsir ingest data/source/synthetic_large.pdf --vlm stub & sleep 20 && kill -TERM %1; wait; \
  vsir runs show <run_id> && vsir ingest --resume <run_id> && vsir runs show <run_id> && \
  vsir lookup "<a code only revision 1.3 has>"
```
The reviewer sees the killed run in `state: stopped` with zero queryable pages, the resume completing
**without re-billing** the finished windows (the stub call count is unchanged for them), the run
reaching `published`, and a `lookup` that only the superseded revision satisfies returning
`status: found_only_in_superseded`.

### Deliverables (files)
- `backend/vsir/ingest/run.py` — **extended**: `--resume`, per-window checkpoints, the `SIGTERM`
  handler that checkpoints the in-flight window, `--steal` against a live lease.
- `backend/vsir/ingest/index.py` — **extended**: the `is_current` lifecycle across revisions.
- `backend/vsir/ingest/stitch.py` — **extended**: `series_id` stability across revisions.
- `backend/vsir/serve/tools/lookup.py`, `skim.py` — **extended**: the `found_only_in_superseded` status.
- `backend/vsir/cli.py` — **extended**: `ingest --resume`, `retire <doc_id> [--revision]`.
- `data/source/synthetic_large.pdf` + its generator — **written**, checked in.
- `backend/tests/api/test_revision_lifecycle.py`, `test_resume.py`, `test_sigterm_checkpoint.py`,
  `test_retire.py`, `test_ladder_level_2.py` — **written**.

### Requirements
- Read `impl/app/pipeline.py` and `impl/app/segjobs.py` again for the resume path. ⚠ Spec §20.1
  **E2**: job state is a dict on daemon threads in `impl` and a restart strands a paid run — state
  must live in `vsir_runs`. ⚠ **E7**: a killed-and-resumed run must leave no duplicate or orphan point.
- Spec §6.7 clause 2: publishing revision 1.4 sets revision 1.3's points `is_current=False` and
  **keeps** them — they are what `found_only_in_superseded` reads from (F9). A blanket delete would
  satisfy F12 by destroying F9's evidence.
- Spec §7.1: `found_only_in_superseded` → the agent surfaces the revision and lets the caller decide.
- Spec §5.1 / §5.3: `series_id` is the stable id of a section **across revisions**, and is a keyword
  array so a straddling page carries every applicable id (F8's third part).
- Spec §15 Factor IX: on `SIGTERM`, stop accepting work, drain in-flight requests within the grace
  period, and **checkpoint the ingest window in progress** so a kill loses **at most one window** and
  **never publishes a partial run** (I7, F17). Any process is killable at any instant without leaving
  a queryable half-document.
- Spec §6.9: `stopped` is what a `SIGTERM` leaves and is the **only** state `--resume` accepts without
  `--steal`.
- Spec §6.2: the resume test runs on a **generated large PDF, not the excluded 1,440-page manual** —
  attempting a Level-2 document must fail typed `ladder_level_2_required` naming the document.
- Spec §4.4: `vsir retire <doc_id> [--revision]` is a one-off admin process (§15 Factor XII), because
  deletion is an operator action, not a caller's — it replaces `impl`'s
  `DELETE /api/v1/documents/{doc_id}` (§2.5 A).
- Spec §17 **OQ-5** default: one collection with `doc_id` scoping at 5,505-page scale. Spec §20.1
  **E9** must be **re-verified at M8 scale-out** — `resolve` must not scroll and filter in Python.

### Invariants Enforced
- None newly (I1 and I7, asserted at M2a, are re-exercised here under interruption and across revisions).

### Failure Rows Closed
- **F8 (series_id half)** — `series_id` links a section across revisions so a scope stays correct over a revision boundary — `test_series_id_stable_across_revisions` (L2).
- **F9** (cites a superseded revision as current) — `is_current` injected by default plus the `found_only_in_superseded` status — `test_lookup_only_in_superseded_returns_typed_status` (L2).
- **F12 (revision half)** — publishing 1.4 retires 1.3's points to `is_current=false` **without deleting them**, so totals do not double and F9's evidence survives — `test_publishing_new_revision_keeps_prior_points` (L2).

### Dependencies
- **Depends On:** [U022, U011]
- **Enables:** [U026]
- **External:** Qdrant; a generated large PDF; **OQ-3 / OQ-7** for the export hand-off sign-off.

### Acceptance Criteria
- [ ] `SIGTERM` mid-window leaves the run in `state: stopped`, **zero** queryable pages for that document, and a checkpoint for the in-flight window in `vsir_runs`.
- [ ] `vsir ingest --resume <run_id>` after that kill completes the run and reaches `published`; the stub-VLM call count for the **already-completed** windows is unchanged — no re-billing.
- [ ] At most **one** window's work is lost to the kill (asserted by comparing the pre-kill checkpoint's window index to the resumed run's first re-processed window).
- [ ] `--resume` on a run whose lease is still live **refuses** without `--steal`; with `--steal` it proceeds and the final point count is still `pdf.page_count`.
- [ ] `--resume` refuses a run in any state other than `stopped` without `--steal`.
- [ ] `data/source/synthetic_large.pdf` is large enough to force at least three window checkpoints in a single run.
- [ ] Publishing revision 1.4 of a document sets revision 1.3's points to `is_current=False` and **keeps every one of them** (point count for 1.3 is unchanged).
- [ ] A `lookup` satisfied only by revision 1.3 returns `status == "found_only_in_superseded"` with the revision named — not `not_found` and not a silent 1.3 hit.
- [ ] A `lookup` satisfied by 1.4 returns only 1.4's pages — `is_current=True` is injected by default.
- [ ] `series_id` for a section present in both 1.3 and 1.4 is identical, and a scope by `series_id` returns pages from both revisions while a scope by `section_id` does not.
- [ ] `vsir retire <doc_id>` sets `is_current=False` for every page of the document and is idempotent; `--revision` narrows it to one revision; neither ever touches another document (before/after payload-hash comparison).
- [ ] A document requiring Level 2 windowing fails typed `ladder_level_2_required` naming the document — never a blind cut.
- [ ] `resolve` at large-corpus scale executes an indexed-facet query and never scrolls-and-filters in Python (E9 re-verified, asserted by a call spy).

### Test Plan
**Levels:** [L0, L1, L2]
**Commands:** `bash scripts/test-unit.sh -k "series_id or ladder_level_2"` · `bash scripts/test-api.sh -k "revision_lifecycle or resume or sigterm_checkpoint or retire"`
**Fixtures/Stubs:** `data/source/synthetic_large.pdf` (produced by **this unit**); a generated two-revision document pair; `data/fixtures/synthetic_3window/`; ephemeral Qdrant with `vsir_pages` and `vsir_runs`; stub VLM — **no paid call required**.
**Edge Cases (§11.3):** `SIGTERM` exactly at a window boundary; a stale lease whose TTL expired; `--steal`; a resume after a `503 qdrant_unavailable`; a Level-2 document; a `retire` on a document that is already fully retired.

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** the resume path becomes a second, parallel code path that skips the lease renewal a fresh run uses. **Mitigation:** `--resume` must reuse the same lease-renewal code as a fresh run; asserted by the `--steal` and stale-lease criteria.
- **Risk (OQ-5):** one collection at 5,505 pages is unproven until here. **Mitigation:** load-test with the generated large PDF rather than waiting for the real corpus; the E9 re-verification criterion is the early warning.
- **Risk (OQ-3 / OQ-7):** Part A reads export **files** from disk. **Mitigation (Spec §17 default):** serve over HTTP **and**, if files are needed, dual-write to an attached object store — never the instance's local disk. This must be resolved before the M8 hand-off.

### Rollback Plan
- **If this unit must be reverted:** restore the prior revision's `is_current=True` by `(doc_id, revision)` filter and set the new revision's points to `is_current=False` — **never delete either set**, because clause 2's retained points are F9's evidence. Delete only points written by the reverted `run_id`, by `run_id` filter. Set the `vsir_runs` run point to `state: failed` with a reason. Never leave a partial index state.

---

## Unit: `vsir eval corpus` — the §12.6 report and the D11 gates (ID: U026)

**Status:** ✅ Complete (2026-09-11) — **the last unit in the plan.** Shipped at **zero spend**:
the spend class covered the scale-out corpus the report was to measure (OQ-1's), and the report
itself is a read — `vsir.vlm` is not in `eval/corpus.py`'s import graph, and both a VLM spy and
an ingest-step spy assert zero calls. The two sets with no ground truth on any corpus that exists
here (the alarm catalogue, and the real-scale register / cross-reference sets) **skip by name**
and are counted as skipped, never passed
**Milestone:** M8
**Priority:** P1-High
**Type:** eval
**Size Estimate:** Medium
**Spend:** paid (ingest, for the scale-out corpus the report measures)

### Goal
Measure the system against the corpus's own ground truth and turn Spec §3 D11's numbers into a
gate — with `code_precision` at 1.00 as a P0 stop.

### Working Deliverable
`vsir eval corpus` — the evaluation report, exiting non-zero when any D11 gate fails.

### Demo Command
```bash
vsir eval corpus
```
The reviewer sees one row per §12.6 set — component register, near-miss sample, alarm catalogue,
cross-references — each with its metric, its D11 gate and a PASS/FAIL, and an explicit **P0 STOP**
line if `code_precision` is anything other than 1.00.

### Deliverables (files)
- `backend/vsir/eval/corpus.py` — **written**, net new.
- `backend/vsir/cli.py` — **extended**: `eval corpus`.
- `backend/tests/api/test_eval_corpus_gates.py` — **written**: the gate arithmetic against a
  synthetic ground-truth set, at zero spend.
- The evaluation report itself, recorded in the progress file.

### Requirements
- Spec §12.6 sets and metrics: **Component register** (E pp. 59–125; 2,053 rows · 748 tags · 484
  codes) → `code_precision` (a code `lookup` returns **is** the printed code) and `code_recall`
  (printed codes findable by `lookup`); **Near-miss sample** (100 mutated codes, §12.4) →
  `abstention_correctness`; **Alarm catalogue** (numbers 0–539, ~494 records) → `alarm_label_hit`
  (each number lands its record's page); **Cross-references** (6,880 tokens, 99.97% resolvable) →
  `xref_resolve` (`resolve` returns the right page).
- Spec §3 **D11** gates: `code_precision` **= 1.00** — a single wrong code is a **P0 stop**;
  `abstention_correctness` **= 1.00**; `code_recall` **≥ 0.95**, block below 0.90;
  `alarm_label_hit` **≥ 0.99**; `xref_resolve` **≥ 0.99**.
- Spec §12.6: *"Precision is a safety property and must be perfect; recall is a measured target."*
  These numbers are **re-baselined exactly once, from the M2b measurement, with a recorded
  rationale** (C10).
- Spec §12.2 **L5**: a canary on a held-out document nobody tuned against, run manually via
  `vsir eval corpus`.
- Spec §11.4: the report reads the same gauges and run records the pipeline already emits; it
  triggers **no** re-ingest and no VLM call of its own.
- Spec §17 **OQ-4** is resolved by design — `near_misses()` derives from the observed-token inventory,
  so the 8,414-pair list is not required; if it arrives it only widens the sample.

### Invariants Enforced
- None newly.

### Failure Rows Closed
- None newly — it is the measured proof that the whole catalogue holds at corpus scale.

### Dependencies
- **Depends On:** [U025, U016, U013]
- **Enables:** []
- **External:** the ground-truth sets from the corpus; **OQ-1/OQ-2** for the real-corpus numbers;
  `VSIR_ALLOW_PAID=1` for any step that would trigger a live call.

### Acceptance Criteria
- [ ] `vsir eval corpus` prints one row per §12.6 set with its metric, its D11 gate and PASS/FAIL, and exits non-zero on any failure.
- [ ] `code_precision < 1.00` prints an explicit **P0 STOP** line naming every offending code and page, and exits non-zero.
- [ ] `code_recall < 0.90` marks the run **blocked**; a value in `[0.90, 0.95)` fails the gate but is not a P0 stop; `≥ 0.95` passes.
- [ ] `abstention_correctness` is computed over the 100-sample near-miss set from U006 and must be exactly 1.00.
- [ ] `alarm_label_hit ≥ 0.99` over the alarm catalogue and `xref_resolve ≥ 0.99` over the cross-reference tokens.
- [ ] The command triggers **zero** ingest steps and, unless `VSIR_ALLOW_PAID=1` is set, **zero** VLM calls (asserted by a call spy) — it reads the published index only.
- [ ] Any threshold re-baselined from the M2b measurement carries a recorded rationale in the report (C10), and a re-baseline attempt without one fails.
- [ ] The gate arithmetic itself is unit-tested against a synthetic ground-truth set at zero spend, including the exact boundaries 1.00 / 0.95 / 0.90 / 0.99.
- [ ] The report is written to the progress file as the M8 deliverable record.

### Test Plan
**Levels:** [L5] (the report itself), with the gate arithmetic covered at [L2] against a synthetic ground-truth set
**Commands:** `vsir eval corpus` (manual canary) · `bash scripts/test-api.sh -k eval_corpus_gates` (automated, zero spend)
**Fixtures/Stubs:** the real corpus ground-truth sets for the L5 report; a synthetic ground-truth set for the L2 gate arithmetic; `data/fixtures/TC1E-SF/` for the near-miss sample when present, else `synthetic_3window`.
**Edge Cases:** exactly one precision miss (must be a P0 stop, not a rounding pass); recall exactly 0.90 and exactly 0.95; a re-baseline attempt with no rationale; a set with no ground truth available (must **skip with a named reason**, never silently pass).

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk (R4, Spec §18):** the `grounded_rate` threshold set from 55 pages proves wrong at 5,505. **Mitigation:** this report re-validates it on the full corpus and is the trigger for a single, rationale-recorded re-baseline (C10).
- **Risk (R7):** a green report is mistaken for coverage of the §7/§8 paths `impl` never exercised. **Mitigation:** the report must print U012's explicit "no legacy coverage" list alongside the metrics.
- **Risk (OQ-1/OQ-2):** the real corpus and key are unavailable, so the real numbers cannot be produced. **Mitigation:** the gate arithmetic ships and is tested at L2 on a synthetic ground-truth set; sets with no ground truth **skip with a named reason** and are counted in the summary — never silently passed.

### Rollback Plan
N/A — a read-only evaluation command; no index state and no tool contract is changed.

---

---

## 4b. Units added after the plan was written

Four units the original 26 did not contain. Three of them (U027, U028, U030) **shipped on
2026-09-10** and are recorded here so the plan describes the system that exists; U029 is **not
built and blocks U018**, which is the finding that matters most in this section.

They are numbered from U027 rather than inserted, so no existing unit id moves.

---

## Unit: `POST /documents` — ingestion over HTTP (ID: U027)

**Status:** ✅ Complete (2026-09-10)
**Milestone:** M3 (after U015)
**Priority:** P1-High
**Type:** tool
**Size Estimate:** Medium
**Spend:** none to build; the route can *start* a paid run

### Goal
Let a caller hand the pipeline a PDF over HTTP, because §7.4's route table had no ingest path at
all: an operator with only the API could query documents but never add one.

### Working Deliverable
`POST /documents` — multipart in, `202` and a `run_id` out; progress on the existing
`GET /runs/{run_id}`.

### Deliverables (files)
- `backend/vsir/serve/ingest.py` — **written**, net new: the spool, the refusals, the child.
- `backend/vsir/serve/app.py` — **extended**: the route.
- `backend/vsir/cli.py` — **extended**: `--run-id`.
- `backend/tests/unit/test_upload.py`, `backend/tests/api/test_upload_route.py` — **written**.

### Requirements
- **It does not implement ingestion. It starts `vsir ingest`.** §15 Factor XII —
  *"a corrective action that cannot be expressed as a `vsir` subcommand is not a supported
  operation"* — and register **E1**, where `impl` had an upload page *and* a CLI, the exports were
  written from the CLI path only, and *"a UI ingest produced nothing for the graph team"*. Two code
  paths for one operation meant one of them silently did less than the whole job.
- `--run-id` is new on `vsir ingest` and is **not** `--resume`: resume continues a run that exists
  and refuses `run_not_found` otherwise, so it cannot start one. The id is minted at the boundary so
  the caller can poll before the child has done anything.
- Everything refusable is refused **before the child starts**: §6.9's control plane is written from
  step 09 onward, so a child that dies at step 02 leaves *no run record* and a caller handed a `202`
  polls `404` for ever. `415 not_a_pdf` (the file's own leading bytes, not its Content-Type),
  `413 upload_too_large`, `400 unknown_step` / `unknown_vlm` / `empty_upload` / `fixture_not_found`,
  `403 spend_not_permitted`, `500 ingest_unstartable`.
- **`VSIR_ALLOW_PAID` becomes load-bearing here.** It was parsed into `Config` and read by nothing —
  three lines in `config.py` were its only appearances in the backend, so the only real brake on
  spending was a shell check in `scripts/test-paid.sh`. The check reads the *effective* backend, or
  `vlm=gemini` on the form would bypass a replay-mode release.
- The child gets **this instance's** configuration, not the process's: `create_app` takes its
  environment as an argument, so a child reading `os.environ` would ingest into the collection the
  process was launched against while its parent answered about another one.

### Invariants Enforced
- None newly. I7 is what makes `until=publish` safe to default to: step 10 writes `is_current=False`
  and step 11 is the only thing that flips it, behind §11.1's gates.

### Dependencies
- **Depends On:** [U014, U011]
- **Enables:** [U030]

### Disclosed limitations
- ~~**A run started by upload is not resumable across an instance restart.**~~ **Closed by U029
  (2026-09-10).** It was true — the upload is spooled for the life of one run and the spool goes
  with the instance — and the fix is not to keep the spool: step 02 deposits the source document
  on the store volume, so `vsir ingest --resume <run_id>` resolves the bytes from the run record
  and needs no path. Asserted by
  `tests/api/test_store_round_trip.py::test_an_upload_started_run_resumes_from_the_store_with_no_path_at_all`.
- **The spend switch is per-release, not per-caller.** `serve/auth.py` has no token scopes, so a
  caller who can spend can spend everything the release allows.

---

## Unit: Live-path corrections found by the first real Gemini run (ID: U028)

**Status:** ✅ Complete (2026-09-10)
**Milestone:** M2a/M2b (corrections to shipped units)
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Small
**Spend:** paid — the run that found them

### Goal
Make `VSIR_VLM=gemini` reach a published document. Five defects sat between the switch and a real
ingest, and **every one was invisible to 1149 green tests**, because the stub backend never builds a
request, never loads a prompt and never opens a client. Only a real call could find them.

### What was wrong
1. **The pinned VLM id does not exist.** `gemini-3.8-flash-001` is a `404` from the API; the model is
   `gemini-3.8-flash`. It was in `.env`, `.env.example` and **both** compose files, so the first paid
   run of this system was always going to fail at step 04 regardless of the document.
   `gemini-embedding-2` is correct and `output_dimensionality=1536` is accepted, so the collection's
   dim was never at risk.
2. **The prompts were not in the wheel.** `[tool.setuptools.packages.find]` ships modules; `s1.md`
   and `s2.md` beside them are data. The container failed
   `prompt_unavailable: vsir/vlm/prompts/s1.md is missing from the release`.
3. **`genai.Client(...)` was constructed per call.** It owns an `httpx` transport and closes it when
   finalised, so as a temporary it could be collected while its own request was in flight:
   `RuntimeError: Cannot send a request, as the client has been closed`. Same bug in `GeminiEmbedder`.
4. **The response schema was the Pydantic class.** Every model sets `extra="forbid"`, which renders
   as `additionalProperties: false`, and `response_schema` has no such field:
   `400 INVALID_ARGUMENT: Unknown name "additional_properties"`.
5. **`VSIR_FIXTURE` does double duty in `cli.py`** — the replay directory *and* where the run's
   acceptance table is read from. For a replay both meanings describe one corpus and agree; for a
   live ingest of an arbitrary upload neither applies, and inheriting the release's value meant every
   uploaded document was checked against **another document's** expectations. A 4-page SICK datasheet
   failed the synthetic corpus's label offset and its crop trap on page 20, surfacing as
   `page_out_of_range: page 20 is outside 1..4`.

### Deliverables (files)
- `backend/vsir/vlm/client.py` — `_client()`, and `response_schema()` which inlines `$ref`/`$defs`
  and drops the keywords the API has no field for. The **strict class still parses the response**, so
  a surprise key in a paid response is still refused rather than dropped.
- `backend/vsir/ingest/embed.py` — the same client fix.
- `backend/vsir/serve/ingest.py` — a live run inherits no fixture from the release.
- `backend/pyproject.toml` — `[tool.setuptools.package-data]`.
- `backend/tests/unit/test_release_artefacts.py` — **written**: scans `vsir/` for **any** non-Python
  file not covered by `package-data`. The general form, so a data file added later is caught the day
  it is added rather than on the next paid run.

### The lesson for every later unit
A test that drives the stub proves the pipeline's logic and **nothing about the release**. Anything
that only exists on the live path — a model id, a packaged file, an SDK object's lifetime, a
provider's schema dialect — is unverified until a real call is made. U013's paid re-bill and U020's
`read` are the two remaining units that will meet this class of defect for the first time.

### Dependencies
- **Depends On:** [U007, U008, U010]
- **Enables:** [U013]

---

## Unit: The document store — the source PDF at query time (ID: U029)

**Status:** ✅ Complete (2026-09-10)
**Milestone:** M4 (must land before U018)
**Priority:** P0-Critical
**Type:** ingest
**Size Estimate:** Small
**Spend:** none

### Goal
Keep the source PDF, so a page can be rendered at query time. **Rasters are re-rendered on demand
(§4.2, §15 Factor VI) — and nothing in the system keeps the file to render them from.**

### The gap, precisely
U018's own dependency list says *"the source PDF must be reachable by the serving process"*. That is
an assumption stated as an external dependency, **with no mechanism behind it**:

- a **CLI** ingest happens to work because the operator's copy is still in their filesystem — luck,
  not architecture;
- an **upload** spools to `/tmp/<run_id>.pdf` and the reaper deletes it when the run exits;
- and nothing can even name the file: neither the page payload nor the run record carries
  `content_hash`, and there is deliberately no `image_path` (register **A5**, §5.3). Given
  `SICK-UE410-SD400@1.0#p002` there is no path from page → document → bytes.

§315's *"no blob store, no local source of truth"* was written about **rasters**, not about the source
document, so this is not a reversal of that decision.

### What it breaks while it is missing
The whole vision half of retrieval: `GET /pages/{page_id}/image` and `fetch` (U018) have nothing to
render, `read` (U020) has no raster to reason over, and **correction Loop 5** —
*"nothing found and `searchable_ratio < 1` → `fetch`/`read` the image-only pages"* — dead-ends. That
last one is load-bearing for §8.5's honest abstention: `not_searchable` tells the agent to escalate
to vision, and today the escalation has nowhere to go.

### Deliverables (files)
- `backend/vsir/ingest/store.py` — **written**, net new: a document store, one mounted volume,
  `<doc_id>@<revision>.pdf`. Derivable from any `page_id` via `ids.parse_page_id`, so **no path
  goes in a payload** and A5's fix stands: the payload names the *document*, the store resolves
  the *file*. Identity-addressed and **integrity-checked** rather than content-addressed:
  `<sha256>.pdf` would need a hash in the payload, or a second index to find one, which is the
  same coupling by another name — so the hash moves to the run record and `locate(expect_hash=…)`
  refuses bytes that disagree with it.
- `backend/vsir/cli.py` — **extended**, and this is the one deliverable that moved. *(Amended
  2026-09-10, during implementation.)* The plan put the deposit in `serve/ingest.py` — *"the upload
  writes to the store instead of deleting its spool"* — and that cannot be right: at upload time
  the route does not know the document's identity. An undeclared `doc_id` is derived by §6.1 step
  01 from the filename and `content_hash` does not exist until step 02, so the route would have had
  to re-derive step 01's answer and drift from it (defect **P4** is what that drift already looks
  like). So the deposit is **step 02 of the pipeline**, where `doc_id`, `revision` and
  `content_hash` are all authoritative — and because `POST /documents` *runs* that pipeline
  (§15 Factor XII), an upload deposits through the identical line a CLI ingest does. One writer,
  which is the register **E1** lesson applied rather than restated. Also: `vsir ingest --resume`
  takes the PDF path as **optional** and resolves it from the store, and `vsir documents` /
  `vsir documents --page <page_id>` is the operational surface for what the store holds.
- `backend/vsir/serve/ingest.py` — **extended**: `check_store` pre-flights the volume before the
  `202`, because a run that indexes and publishes into a release with no writable store buys a
  document whose every page is permanently imageless; and `child_env` passes `VSIR_DOC_STORE`, the
  same class of bug as the `VSIR_RUNS_COLLECTION` one it sits beside.
- `backend/vsir/ingest/run.py` — **extended**: persist `content_hash`. It is already computed by
  probe and logged, and never stored — so nothing can detect that the file behind
  `doc_id@revision` was swapped for different bytes.
- `backend/vsir/config.py`, `.env.example` — **extended**: `VSIR_DOC_STORE`, optional and
  defaulted. Deliberately **not** a thirteenth required variable: §4.3's contract is that unsetting
  a required one is a named non-zero exit, and a release that never ingests must still boot.
- `docker-compose.yml`, `scripts/stack.sh` — **extended**: the `document-store` named volume,
  mounted at `/srv/documents` by every process type of the release.
- `backend/Dockerfile` — **extended**: `/srv/documents`, created and owned by uid 10001. Docker
  initialises a fresh named volume from the image's mount point, ownership included — with nothing
  there the volume is root-owned and the non-root container cannot write to its own store. Found
  by running `stack.sh up`, which refused the seed `document_store_unwritable`.
- `backend/tests/unit/test_store.py`, `backend/tests/api/test_store_round_trip.py` — **written**;
  `backend/tests/unit/test_ingest.py`, `backend/tests/unit/test_upload.py` — **extended**.

### Demo Command
*(Added 2026-09-10: the unit as planned had none.)*
```bash
export VSIR_DOC_STORE=/tmp/vsir-demo-documents VSIR_FIXTURE=data/fixtures/synthetic_3window
vsir ingest data/source/synthetic_3window.pdf --vlm stub --until probe   # deposits at step 02
vsir documents                                                          # what the store holds
vsir documents --page 'synthetic-3window@1.0#p007'                      # page_id -> bytes -> raster
vsir documents --page 'TC1E-SF@1.3#p001'                                # the typed refusal, exit 1
```

### Requirements
- `page_id → doc_id@revision → bytes` and nothing else. No new payload field, no `image_path`.
- Rasters stay unpersisted: this stores the **source**, and re-render on demand remains true.
- A store miss is a typed refusal naming the document, never a placeholder image and never a 500.
- Side effect worth having: an uploaded run becomes **resumable across a restart**, which closes
  U027's first disclosed limitation.

### Acceptance Criteria
- [x] After an upload, `page_id → bytes` resolves for every page of the document.
- [x] The page payload gains **no** field; `INDEXED` is unchanged and the boot assertion still passes.
- [x] A document whose file is absent from the store gives a typed refusal naming
      `doc_id@revision`, not a 500 and not a blank image.
- [x] `content_hash` is on the run record, and a store entry whose bytes disagree with it is refused
      rather than served.
- [x] `vsir ingest --resume` completes an upload-started run after the container is restarted.

### Dependencies
- **Depends On:** [U027, U011]
- **Enables:** [U018, U020, U022]

---

## Unit: `/console`, the docs surface, and the local stack (ID: U030)

**Status:** ✅ Complete (2026-09-10)
**Milestone:** M3
**Priority:** P2-Medium
**Type:** frontend
**Size Estimate:** Small
**Spend:** none

### Goal
Make what the release serves usable and visible without a client: one page to upload, watch a run
and search, a self-describing OpenAPI document, and one command to bring the stack up.

### Working Deliverable
`bash scripts/stack.sh up` → Qdrant, the collection, the API, a seeded document, and
`http://localhost:8055/console`.

### Deliverables (files)
- `backend/vsir/serve/console/index.html` — **written**: one static page, no build step, same origin.
- `backend/vsir/serve/app.py` — **extended**: `GET /console`, and `_described()` — the OpenAPI
  document with the bearer requirement the middleware actually enforces.
- `backend/vsir/serve/auth.py` — **extended**: `PROBE_PATHS`, `DOC_PATHS`, `CONSOLE_PATHS`.
- `docker-compose.yml`, `scripts/stack.sh`, `scripts/sweep-corpus.py` — **written**.
- `backend/tests/api/test_openapi.py` — **written**.

### Requirements
- **This is not U023.** M7's console is a React + Vite app with a page viewer, region zoom and the
  agent's move-by-move trace, and it needs `fetch`, `read` and the runner. U023 **replaces** this
  page rather than growing out of it.
- Auth is **default deny by path in middleware**, which FastAPI cannot infer from the routes — so
  the generated document described an API with no security at all. Wrong in the direction that
  matters: a reader concludes no token is needed and Swagger shows no *Authorize* button. The
  requirement is now derived from the same list the middleware reads, so a route added later is
  covered without anyone remembering.
- `/openapi.json`, `/docs`, `/redoc` and `/console` are free to **read** — markup and interface
  shape, no corpus data, no run, no page, no token — because a browser cannot attach an
  `Authorization` header to a plain navigation. **Reading them authorises nothing.** The first
  attempt at this was a local proxy that injected the token, and it was the wrong answer: it put
  the credential in a second place, made the working surface something other than the shipped one,
  and left `/docs` broken for anyone not running the proxy.
- The console shows a **typed absence as an answer**, with coverage numbers, never as "0 results";
  and keeps `hits` and `unverified_hits` in **separate blocks**, because a code read off a raster is
  not a code found in the page's text (D3, I2).

### Dependencies
- **Depends On:** [U015, U027]
- **Enables:** [] — U023 supersedes it.

---

## 4c. Open defects found while running the system

Recorded here rather than in `fixes/` because each belongs to a unit that has not been built yet, or
is a follow-up the discovering unit deliberately did not take on. **None blocks a green build; all
of them mislead somebody who trusts the system.**

| # | Defect | Owner | Why it matters |
|---|---|---|---|
| **P1** | **A live run records no cost.** `input_tokens` / `output_tokens` come back `0` while `vlm_calls` is `1`: the token counts are not read off the live response. | U013 | With no cache store either (P2), a paid run leaves **no record of what it cost or what it received** — only what it concluded. For a system whose premise is provenance this is the weakest point in it. |
| **P2** | **There is no VLM cache store on the live path.** `vlm/cache.py` says *"in production the entries live beside the run in the `vsir_runs` control plane"*; only `FixtureStore` is implemented. `cache_hits` is structurally always 0 and re-ingesting an unchanged document **re-bills every window**. | U013 | It is the difference between paying once and paying every time, and it makes §6.3's four cache keys decorative outside replay. |
| **P3** | **`--record` is not exposed on `POST /documents`.** The recorder exists (`vlm/record.py`) and freezes receipts byte-for-byte under their §6.3 keys, but only `vsir ingest` can reach it — so an upload can never freeze its own receipts, and the upload is the path an operator uses. | U027 | §12.1's *"one paid ingest buys a permanent test corpus"* has no mechanism from the API. |
| **P4** | **An upload with no declared `doc_id` is named after its own run.** The route spools to `<run_id>.pdf` and §6.1 step 01 derives `doc_id` from the filename, so a Festo datasheet published as `01M25E2HPS3KSEHSX6ZNEYBG9W`. Unfindable, un-scopable, and a re-upload becomes a *different* document every time, so retirement never supersedes anything. | U027 | Observed on 2026-09-10. Fix: spool under the uploader's sanitised filename. |
| **P5** | **`VSIR_FIXTURE` means two things in `cli.py`** — the replay directory and the location of the run's acceptance table. U028 stopped a live run inheriting it, which is a guard, not the fix. | U013 | Separating them is what makes an acceptance table something a run can be checked against *deliberately*. |
| **P6** | **A single-page PDF returned `page_index: 20`.** The §6.4 structural check refused it rather than indexing garbage — correct behaviour — but the model ignoring a 1-page window looks like a real weak spot, not a one-off. | U013 | 100 documents of the real corpus are ≤ 4 pages; whatever this is, it is not rare. |
| **P7** | **The triage panel had nothing typed to render.** `AskResponse` exposed no structured triage at all: the only triage that reached a caller was one prose line inside a trace `Move.detail`, and the `exclude` set's page ids were not in the body anywhere — they lived only in `Loop.excluded`, and `effective_scope` does not carry them. U023's *"the triage panel shows all three states and the `exclude` set"* was therefore unsatisfiable by a frontend-only change. | U023 | Found 2026-09-11 while starting U023. **Amended in the plan rather than left open:** U023 now also ships a typed `TriageTable` on `Outcome` and one additive `triage` field on `AskResponse` — `triage.Mark` already keeps `matched` *"so a triage table can be reviewed rather than trusted"*, and the console **is** that table. A console that regexes a sentence is a second declaration of the contract in a language that cannot fail a test when the sentence is reworded. |
| **P8** | **A wire type declared outside `types.ts` is an unchecked wire type.** `GET /documents`' `DocumentRow` / `DocumentList` were hand-written in `client.ts`, which `test_frontend_client_contract.py` does not read, and every field of them was wrong — a `title` and a `grounded_rate` the route has never sent, and no `revisions` array, which is the one thing that row exists to carry (§6.7 keeps superseded revisions rather than deleting them). | U023 | Found 2026-09-11 by calling the running service and comparing. **Closed in U023:** both shapes moved into `types.ts` and the contract ledger is now exhaustive (33 response models, 8 request bodies, compared in both directions). The general lesson is the one worth keeping — the contract test's coverage is defined by *where a type is written*, so the guard is only as good as the ledger is complete. |
| **P9** | **`scripts/test-unit.sh` had been reporting `Layer 0/1 FAILED` on the frontend layers.** `tsc --noEmit` failed on `vite.config.ts` (`Cannot find name 'process'`) and `vitest` exited 1 with *"No test files found"*, from the moment the M7 scaffold landed and before any console code existed. | U023 | **Closed in U023** — one ambient `declare const process` rather than adding `@types/node` (§4.2), and the suite the unit was going to write anyway. Worth recording because the failure was in the *harness's own* output and was read past twice: a red layer that is red for a known, boring reason is how a red layer stops being read. |

## 5. Dependency Graph

```text
U001 ──┬── U002 ──┬── U003 ── U004 ──┬── U005 ── U006 ─────────────┐
       │          │                  │                            │
       └──────────┴── U007 ── U008 ── U009 ── U010 ── U011 ──┬─────┤
                        (U007 also needs U003)   (U010 also needs U004)
                                                             │     │
                                        U012 ── U013 ────────┤     │
                                                             │     │
                                                       U014 ─┴─ U015 ◄┘
                                                             (U015 needs U005, U006)
                                                               │
                                        U016 ◄─────────────────┤ (also U012)
                                                               │
                                        U017 ◄─────────────────┘ (also U010)
                                          │
                                        U018 (also U007)
                                       ┌──┴──┐
                                     U019   U020 (also U008, U006)
                                       └──┬──┘
                                        U021 (U019 + U018)
                                          │
                                        U022 (U021 + U020)
                                     ┌────┴────┐
                                   U023      U025 (also U011)
                                     │         │
                                   U024      U026 (also U016, U013)
```

| Unit | Depends on | Enables |
|---|---|---|
| U001 | — | U002, U003, U007 |
| U002 | U001 | U003 |
| U003 | U001, U002 | U004, U007 |
| U004 | U003 | U005, U006, U010 |
| U005 | U004 | U006, U015 |
| U006 | U004, U005 | U015, U020, U022 |
| U007 | U001, U003 | U008, U018 |
| U008 | U007 | U009, U020 |
| U009 | U008 | U010 |
| U010 | U009, U004 | U011, U017 |
| U011 | U010 | U012, U014, U025 |
| U012 | U011 | U013, U016, U026 |
| U013 | U012 | U016, U020, U026 |
| U014 | U011 | U015 |
| U015 | U014, U005, U006 | U016, U017 |
| U016 | U015, U012 | U026 |
| U017 | U015, U010 | U018, U019 |
| U018 | U017, U007 | U020, U021 |
| U019 | U017 | U021 |
| U020 | U018, U008, U006 | U022 |
| U021 | U019, U018 | U022 |
| U022 | U021, U020 | U023, U025 |
| U023 | U022 | U024 |
| U024 | U023 | — |
| U025 | U022, U011 | U026 |
| U026 | U025, U016, U013 | — |

**Validation.** The graph is acyclic — a valid topological order is
`U001, U002, U003, U004, U007, U005, U008, U006, U009, U010, U011, U012, U014, U013, U015, U016,
U017, U018, U019, U020, U021, U022, U023, U025, U024, U026`. **No edge points backwards across a
milestone boundary**; every dependency sits in the same or a strictly earlier milestone. There are no
orphans; U024 and U026 are the two intended terminal deliverables.

### Critical path
`U001 → U002 → U003 → U007 → U008 → U009 → U010 → U011 → U014 → U015 → U017 → U018 → U020 → U022 → U025 → U026`
— **16 units.** The ingest pipeline (U007→U011) is a strictly serial single-writer chain that gates
everything above it, and the retrieval stack that sits on top (U014→U022) is itself serial through
U017→U018→U020→U022. `U023 → U024` (M7) is an equal-length branch off U022.

### Integration points

| Point | Units | Risk | Mitigation |
|---|---|---|---|
| Qdrant schema vs `INDEXED` | U003, U010, U011 | the live collection and the dict drift, producing phantom or missing hits | one writer (`ingest/index.py`), gated by the §6.6 fingerprint; the boot assertion is the single check and runs on `vsir doctor` and on server start |
| The core→tool seam (M1 → M3) | U004–U006 → U015 | the wrapper re-implements status or cap logic, so M1's proof stops applying at the tool boundary | U015 imports and calls the M1 modules directly; the M1 fixture suite is replayed through HTTP as a contract test |
| The stub-VLM replay seam | U008 → U009, U020, U022 | fixtures go stale relative to a prompt edit; replay passes against a contract a real call would fail | the cache key includes `prompt_version` and the schema hash, so a prompt edit forces a typed `fixture_miss` rather than a silent stale hit |
| Fixture handoff M2a → M2b → M5 | U011, U012, U013, U020 | the old-schema legacy baseline and the new-schema `TC1E-SF` fixture diverge; the R4 threshold is baked in before parity is proven | every fixture directory carries `release_id` and `schema_version`; U012's parity suite is a hard gate **before** U013 spends |
| HTTP ↔ MCP | U015, U019 | the two transports hand-roll validation and drift, so a non-compliant MCP client bypasses a bound HTTP enforces (R6) | one shared implementation; a byte-identity test per tool; enforcement is server-side, never prompt-level (D7) |
| Backend ↔ frontend | U004/U018 → U023 | the console is the first consumer of `inline=false`, `thumb_url` and the badge fields, four milestones after the envelopes froze | generate the frontend's typed client from `serve/envelope.py`, pinned by `schema_version`, so a mismatch is a compile error |
| The ingest lease at scale | U011 → U025 | a lease proven on 55 pages leaves a stale claim or races a resumed run at 5,505 | heartbeat + expiry from U011 onward; `--resume` reuses the **same** lease-renewal path as a fresh run — no parallel resume code path |

### External-blocker units

| Unit | Blocked on | What ships anyway | Deferred |
|---|---|---|---|
| **U013** | **OQ-1** (pilot PDF) and **OQ-2** (Gemini key) | Nothing upstream is blocked: U012's ported `impl/data/raw/*` gives real window structure at zero spend, so L1 derivation, the offset proof and stitching are already proved on real data. The pipeline runs on `synthetic_3window` in replay. | the single re-bill, the C10 acceptance-table reconciliation, and the R4 `grounded_rate` threshold |
| **U020** | **OQ-2** | code-complete and fully tested at L0–L2 in replay off `synthetic_3window` (upgrading to `TC1E-SF` when it exists) | the one gated L4 real-Gemini `read` |
| **U022** | **OQ-2** | the loop, all six correction loops, the answer gate and the abstention wording are proved end to end in replay, including the one-paid-`read` worked trace via a call-count spy | the gated L4 real `vsir ask` demo |
| **U026** | **OQ-1 / OQ-2** (transitively via U013) | the gate arithmetic ships and is tested at L2 against a synthetic ground-truth set, including every D11 boundary | the real-corpus numbers; sets with no ground truth **skip with a named reason**, never silently pass |
| **U011** (`ingest/export.py` only) | **OQ-3 / OQ-7** (does Part A read files from disk?) | exports are served over HTTP per §6.8 and, if files are needed, dual-written to an **attached object store** — never local disk | the Part A hand-off sign-off, due before M8 |
| **U025** | **OQ-5** (one collection at 5,505 pages) | the default (one collection, `doc_id` scoping) ships and is load-tested against the generated large PDF | confirmation at real corpus scale |

---

## 6. Test Strategy

Levels are Spec §12.2's: **L0** pure functions (<1 s, `scripts/test-unit.sh`) · **L1** derivation over
frozen `raw_window_*.json` (<5 s, `scripts/test-unit.sh`) · **L2** the index contract against an
ephemeral Qdrant (<30 s, `scripts/test-api.sh`) · **L3** adversarial abstention (<60 s,
`scripts/test-api.sh`) · **L4** the worked trace and the failure branch, docker + Gemini, minutes,
`scripts/test-paid.sh` requiring `VSIR_ALLOW_PAID=1` · **L5** the manual canary, `vsir eval corpus` ·
**E2E** Playwright, `scripts/test-e2e.sh` · **conformance** the §12.5 greps.

### The two rules that shape every test
1. **L0–L3 and E2E must never call Gemini.** They run in replay mode (D10): `VSIR_VLM=stub` +
   `VSIR_FIXTURE=<dir>`, where a fixture miss is a typed `fixture_miss`, never a live call.
   **Only U013, U020, U022 and U026 may spend, and only behind `VSIR_ALLOW_PAID=1`.**
2. **No test may *require* the real corpus (OQ-1) or an API key (OQ-2).** Before M2b the fixtures are
   `data/fixtures/synthetic_pages/`, `data/fixtures/synthetic_3window/` and `data/fixtures/legacy/`;
   after M2b, `data/fixtures/TC1E-SF/` is added and the same suites run against all of them.

### Per-unit levels and commands

| Unit | Levels | Command selector |
|---|---|---|
| U001 | L0, conformance | `test-unit.sh -k "doctor or json_log or sigterm_boot"` |
| U002 | L2, conformance | `test-unit.sh -k conformance` · `test-api.sh -k probes` |
| U003 | L0, L2 | `test-unit.sh -k "ids or record"` · `test-api.sh -k indexed_collection` |
| U004 | L0 | `test-unit.sh -k "tok or variants or exact or status or envelope or caps or rrf or sparse"` |
| U005 | L0, L2 | `test-unit.sh -k "lookup_pure or observed_tokens"` · `test-api.sh -k acceptance_synthetic` |
| U006 | L0, L3 | `test-unit.sh -k "verify_claims or present_instead or nearmiss"` · `test-api.sh -k near_miss` |
| U007 | L0, L1, conformance | `test-unit.sh -k "manifest or probe or render or window"` |
| U008 | L0, L1 | `test-unit.sh -k "extract_schema or cache_keys or replay"` |
| U009 | L0, L1 | `test-unit.sh -k "derive or grounded_rate or labels or reattribution or stitch or i2_text_provenance"` |
| U010 | L0, L1, L2 | `test-unit.sh -k "embed_composition or fingerprint"` · `test-api.sh -k index_upsert` |
| U011 | L0, L1, L2, conformance | `test-unit.sh -k "gates or export_shape or safety_flag"` · `test-api.sh -k "publish or retire or run_record or kill_mid_run"` |
| U012 | L1, L2 | `test-unit.sh -k "legacy_fixture_integrity or derive"` · `test-api.sh -k "parity or withheld"` |
| U013 | L1, L2, **L4** | `test-paid.sh -k tc1e_sf_ingest` (gated) · `test-api.sh -k acceptance_real` (replay) |
| U014 | L2, conformance | `test-api.sh -k "auth or audit or degradation or boot_refusal"` |
| U015 | L2 | `test-api.sh -k "lookup_tool or verify_tool or status_enum or mcp_parity"` |
| U016 | L2, L3 | `test-api.sh -k eval_commands` |
| U017 | L2 | `test-api.sh -k "skim_pages or ordering_determinism or image_query or resolve or stateless_scope"` |
| U018 | L2 | `test-api.sh -k "page_image or fetch or raster_cache"` |
| U019 | L2 | `test-api.sh -k "skim_aggregates or searchable_ratio"` |
| U020 | L0, L2, **L4** | `test-unit.sh -k read_stamps` · `test-api.sh -k "read_replay or read_caps or read_cache"` · `test-paid.sh -k read_real` (gated) |
| U021 | L0, L2 | `test-unit.sh -k "triage or safeguards or route"` · `test-api.sh -k ask_explain` |
| U022 | L0, L2, L3, **L4** | `test-unit.sh -k "answer_gate or abstention_wording"` · `test-api.sh -k "ask_replay or correction_loops or ask_near_miss"` · `test-paid.sh -k ask_real` (gated) |
| U023 | L0 | `npm --prefix frontend test` |
| U024 | E2E | `bash scripts/test-e2e.sh` |
| U025 | L0, L1, L2 | `test-unit.sh -k "series_id or ladder_level_2"` · `test-api.sh -k "revision_lifecycle or resume or sigterm_checkpoint or retire"` |
| U026 | **L5**, L2 (gate arithmetic) | `vsir eval corpus` (manual) · `test-api.sh -k eval_corpus_gates` |

### Fixture producers

| Fixture | Produced by | First available | Consumed by |
|---|---|---|---|
| `data/fixtures/synthetic_pages/` (4 hand-written pages) | U005 | M1 | U005, U006, U016 |
| `data/source/synthetic_3window.pdf` + `data/fixtures/synthetic_3window/` | U007 | M2a | U008–U011, U014–U024 |
| `data/fixtures/legacy/` (ported `impl/data/raw/*`, `labels.jsonl`, `withheld.jsonl`) | U012 | M2b | U009 (L1 on real windows), U012, U016, U026 |
| `data/fixtures/TC1E-SF/` (`raw_window_1.json`, `raw_window_2.json`, `text.json`, `expected.json`) | U013 | M2b | every level from M3 onward, in replay |
| `data/source/synthetic_large.pdf` | U025 | M8 | U025 |
| the worked-trace fixture | U022 (over `synthetic_3window`, upgraded to `TC1E-SF`) | M6 | U022, U024 |

### Cross-cutting test obligations
- **Conformance greps (§12.5)** — owned by **U002**; re-run by every unit's Definition of Done.
- **The L3 abstention eval in CI from M1** — owned by **U006**; surfaced as a command by U016;
  extended to the full `/ask` loop by U022; extended to the full corpus by U026.
- **Probe behaviour (§15.1)** — owned by **U002**: `/health` green while Qdrant is stopped, `/ready` red.
- **`SIGTERM`** — smoke-tested at boot by **U001**; owned for long-running work by **U011**
  (mid-publish) and **U025** (mid-window checkpoint, at most one window lost).
- **The §12.3 acceptance table** — asserted on synthetic data by U005/U016 and on real text by U013,
  reconciled per C10.
- **Units permitted an L4 test:** exactly **U013, U020, U022**. U026's report is **L5** (the manual
  canary of §12.2) and is likewise gated behind `VSIR_ALLOW_PAID=1` for any step that would spend.

---

## 7. Invariant & Failure Coverage

Every row below was verified against Spec §9's *"Asserted from"* column and Spec §10's *"Closed at"*
column. **No unit claims an invariant or a failure row outside its milestone's ownership.**

### Invariants

| # | Owner | Milestone (spec) | Mechanical enforcement | Test (level) |
|---|---|---|---|---|
| **I1** | U011 | M2a ✓ | `point_id = uuid5(page_id)`; unique-`page_id` assert; `count(doc, rev) == pdf.page_count` after publish | `test_publish_page_count_and_unique_point_id` (L2) |
| **I2** | U005 (behavioural) + U009 (structural) | M1 ✓ | `lookup("K999")` on a hallucinated code → `not_found`, and only `unverified_hits` when opted in; the `get_text(` grep; the L1 assertion `record.text == probe_text[page_no]` | `test_hallucinated_code_never_findable` (L2) · `test_i2_text_provenance` (L1) |
| **I3** | U004 | M1 ✓ | one `exact_filter`; no `MatchText` in `serve/`; a property test that every variant equals the label with whitespace stripped | `test_variants_whitespace_only_property` (L0) |
| **I4** | U011 | M2a ✓ | the `offset_check` gate requires **both** §6.4 checks on every window; a failure bisects and re-bills | `test_offset_check_catches_shifted_pages` (L2) |
| **I5** | U004 | M1 ✓ | the `SearchResponse` `empty_is_never_ok` validator (Family A) | `test_search_response_never_empty_ok` (L0) |
| **I6** | U003 | M1 ✓ | one `INDEXED` dict creates the payload indexes, gates every filter, and is asserted against the live collection at boot | `test_boot_asserts_indexed_schema` (L2) |
| **I7** | U011 | M2a ✓ | `is_current=False` until every blocking gate passes; every tool injects `is_current=True` | `test_unpublished_run_zero_queryable_pages` (L2) |
| **I8** | U022 | M6 ✓ | the server-side answer gate, per `(claim, page)`, on **both** the `fetch` and `read` routes | `test_answer_gate_rejects_unverified_claim` (L2/L3) |

> **Note on I8 and F6.** Spec §10's F6 row cites I8 among its guards while F6 closes at M2a and I8 is
> asserted at M6. There is no ordering problem: F6's M2a closure rests on its **ingest-time**
> mechanism — per-page `grounded_rate` plus code reattribution with `moved_from` (§6.5) — which is
> complete and independently testable. I8 is the later, runtime backstop for the same failure class.

### Failure rows

| # | Owner(s) | Milestone (spec) | Guard | Test (level) |
|---|---|---|---|---|
| **F1** | U005 | M1 ✓ | I3 phrase-only | `test_lookup_sf_1_1a_returns_exactly_one` (L2) |
| **F2** | U006 (core) · U015 (tool) | M1 (core) · M3 (tool) ✓ | the one `exact_filter`, reused unchanged by the tool wrapper | `test_verify_claims_absent_on_p008` (L0) · `test_verify_tool_absent_for_uncited_page` (L2) |
| **F3** | U005 | M1 ✓ | I3 variants | `test_all_eight_compact_labels_found` (L2) |
| **F4** | U011 (M2a) · U015 (M3) | M2a · M3 ✓ | the `has_text` facet plus the `text_coverage == 0.0` gate skip; I5's typed absence at the tool | `test_fully_scanned_document_publishes` (L2) · `test_lookup_scanned_page_not_searchable` (L2) |
| **F5** | U009 (M2a) · U017 (M4) | M2a · M4 ✓ | label precedence and `label_verified` at derivation; ambiguity → **every** candidate at `resolve` | `test_ambiguous_label_returns_list_never_silent_pick` (L1) · `test_resolve_ambiguous_returns_every_candidate` (L2) |
| **F6** | U009 | M2a ✓ | per-page `grounded_rate` + reattribution recording `moved_from` | `test_code_reattributed_records_moved_from` (L1) |
| **F7** | U011 | M2a ✓ | I4, exercised on U007's off-by-one trap | `test_offset_check_catches_shifted_pages` (L2) |
| **F8** | U009 (stitching) · U017 (stateless scope) · U025 (`series_id`) | M2a · M4 · M8 ✓ | canonical section key + carry-in across the fold; no server session with `effective_scope` echoed; `series_id` stable across revisions | `test_straddling_section_one_section_id_across_fold` (L1) · `test_effective_scope_echoed_no_server_session` (L2) · `test_series_id_stable_across_revisions` (L2) |
| **F9** | U025 | M8 ✓ | `is_current` injected by default; retirement clause 2 **keeps** the prior revision's points; `found_only_in_superseded` | `test_lookup_only_in_superseded_returns_typed_status` (L2) |
| **F10** | U004 | M1 ✓ | I6 — a key absent from `INDEXED` is a typed `filter_unknown_key` 400, never a scan | `test_unknown_scope_key_returns_typed_400` (L0) |
| **F11** | U001 (boot) · U008 (key) | M0 · M2a ✓ | boot refuses a `-latest` id; `extract_key` includes the resolved model id and prompt version | `test_doctor_refuses_latest_model_alias` (L0) · `test_extract_key_changes_with_prompt_version` (L0) |
| **F12** | U011 (M2a) · U025 (revision half, per Spec §13 M8) | M2a · M8 ✓ | I1 plus retirement scoped to the same `(doc_id, revision)` — **never a blanket delete**, which would destroy F9's evidence | `test_reingest_twice_same_point_count` (L2) · `test_publishing_new_revision_keeps_prior_points` (L2) |
| **F13** | U007 | M2a ✓ | the output-budget ladder; `MAX_TOKENS` → bisect and re-bill | `test_oversized_window_bisects` (L1) |
| **F14** | U005 | M1 ✓ | I2 | `test_hallucinated_code_never_findable` (L2) |
| **F15** | U007 | M2a ✓ | `text` always from the **full** page, never a crop | `test_crop_trap_full_text_extracted` (L1) |
| **F16** | U006 | M1 ✓ | `present_instead` = a capped prefix lookup over observed tokens, **never a distance** | `test_k73_absent_with_present_instead_k78` (L0) |
| **F17** | U011 | M2a ✓ | I7 | `test_kill_mid_run_zero_queryable_pages` (L2) |
| **F18** | U018 (fetch) · U020 (read) | M4 · M5 ✓ | the §7.3 caps, each a typed 400 naming its bound | `test_fetch_budget_exceeded_names_bound` (L2) · `test_read_page_cap_exceeded` (L2) |
| **F19** | U020 | M5 ✓ | `read_key` includes the question | `test_new_question_is_a_cache_miss` (L2) |

> **F12's split is sourced from Spec §13 M8**, whose acceptance explicitly delivers *"F12's revision
> half"*; §10's row names M2a alone. Both halves have an owning unit and a named test, following the
> convention §10 already uses for F8 and F18.

### Conformance greps (Spec §12.5) — all owned by U002

Scope: `backend/vsir/**` and `requirements*.txt`, **never markdown and never the conformance test's
own file**; the cloud-native set adds `Dockerfile*` and `docker-compose*.yml`.

| Banned pattern | Test |
|---|---|
| `MatchText` / `MatchTextAny` under `serve/` | `test_no_matchtext_in_serve` |
| any fuzzy / similarity / edit-distance library in `requirements*.txt` | `test_no_fuzzy_lib_in_requirements` |
| a field named `score` in a response model | `test_no_score_field_in_response_models` |
| a model id ending `-latest` | `test_no_latest_model_id_in_source` |
| `alembic` or `sqlalchemy` anywhere | `test_no_alembic_or_sqlalchemy` |
| `get_text(` outside `ingest/probe.py` | `test_get_text_only_in_probe` |
| `SCHEMA_CARD`, `IdClass`, `entity_keys`, `classify(` | `test_no_struck_legacy_names` |
| *(cloud-native)* `logging.FileHandler` | `test_no_filehandler_logging` |
| *(cloud-native)* a container image tagged `latest` | `test_no_latest_tagged_image` |
| *(cloud-native)* a credential literal (`api_key=`, `token=`, `Bearer ` + literal) | `test_no_credential_literals` |
| *(cloud-native)* `if TESTING` / `if os.environ.get("TESTING")` in `backend/vsir/**` | `test_no_testing_only_branches` |
| *(cloud-native)* a `RetrievalState`-style module-level mutable session store (C11) | `test_no_module_level_session_store` |

> **I2 is enforced by a test, not by grepping for `"text"`** — `ingest/index.py` legitimately upserts a
> payload containing that key. The real check is U009's L1 assertion `record.text == probe_text[page_no]`,
> paired with the `get_text(` grep above.

### Publish gates (Spec §11.1) — all owned by U011

| Gate | Action | Test (level) |
|---|---|---|
| `window_coverage` = 1.0 after retries | **block** | `test_publish_blocks_on_incomplete_window_coverage` (L2) |
| `offset_check`, all windows pass I4 | **block** | `test_publish_blocks_on_offset_check_failure` (L2) |
| `grounded_rate` median over `has_text` pages ≥ 0.8 *(provisional, R4)* | **block**, releasable by `vsir publish --override … --reason`, flagging every page `published_with_override` | `test_grounded_rate_gate_blocks_and_override_flags_pages` (L2) |
| `text_coverage` | flag `mostly_scanned`, **never block**; **at 0.0 the `grounded_rate` gate is skipped entirely** | `test_fully_scanned_document_publishes` (L2) |
| `label_monotonic` | flag `label_conflict` | `test_non_monotonic_labels_flag_not_block` (L2) |

### Degradation rows (Spec §11.3)

| Condition | Owner | Behaviour | Test (level) |
|---|---|---|---|
| Qdrant unreachable | U014 | `503 qdrant_unavailable`, retryable, **never an empty result**; `/ready` red, `/health` green | `test_qdrant_down_503_ready_red_health_green` (L2) |
| Gemini unreachable | U020 | `503 vlm_unavailable` on `read`; every free tool keeps working | `test_vlm_down_503_on_read_free_tools_ok` (L2) |
| index schema ≠ `INDEXED` | U001 (check) + U014 (server start) | refuse to serve at boot, non-zero exit before binding the port | `test_boot_refuses_on_schema_drift` (L2) |
| embedding model ≠ collection fingerprint | U010 | refuse to upsert; new collection + re-embed + alias swap | `test_upsert_refused_on_fingerprint_mismatch` (L2) |
| model id ends `-latest` | U001 | refuse to start | `test_doctor_refuses_latest_model_alias` (L0) |
| a document's `grounded_rate` collapses | U009 (signal) + U014 (surface) | `text_trust = "untrusted"`; its pages count as unsearchable; `verify` → `unverifiable` | `test_collapsed_grounded_rate_sets_untrusted` (L2) |
| per-caller `read` quota exhausted | U014 (budget) + U020 (enforcement) | `429 budget_exhausted`, **not** silent truncation | `test_read_quota_exhausted_429` (L2) |
| over-budget `fetch` | U018 | a typed 400 naming the bound — never a dpi clamp or a truncated page list | `test_fetch_budget_exceeded_names_bound` (L2) |

### Uncovered
**None.** Every invariant I1–I8, every failure row F1–F19 including all seven split parts, every
conformance grep, every publish gate and every degradation row has an owning unit and a named test.

### Coverage warnings (not blockers, but stated)
- **The `grounded_rate` threshold (≥ 0.8) is provisional** until U013's M2b measurement sets it (R4).
  Until then U011's gate test runs against a placeholder on synthetic data.
- **Several M2a proofs (I4, F7, F13, F15) and every M1 proof (I2, F1, F3, F14, F16) run on synthetic
  data until M2b.** Spec §12.1 requires the same suites to re-run against the ported `impl` responses
  (U012) and the frozen `TC1E-SF` fixture (U013); those re-runs are U012's and U013's acceptance.
- **AC-014's M2b slice, and the L4 halves of U020/U022/U026, cannot be demonstrated until OQ-1/OQ-2
  are answered.** Every one of them has a replay-mode counterpart that ships and stays green.
- **R7 stands:** parity (U012) covers only what `impl` actually exercised. Most of Spec §7 and §8 has
  **zero** legacy coverage — U012 must publish that list explicitly so a green parity run is never
  mistaken for sign-off.

---

## 8. Assumptions and Risks

### Spec gaps (blockers)
**None.** Gap analysis adjudicated thirteen candidate contradictions surfaced during extraction.
Every one is resolved by Spec §2.3 (corrections), §3 (closed decisions) or §17 (open questions with
recorded defaults). **No spec change is required and none is made** (Phase 5: the spec is modified
only for a true blocker, and there is none).

### Stale spec text a builder will trip on

These are places where the spec's own corrections tables supersede text left elsewhere in the
document. In each case **§2.3 / §3 wins**; the stale text is recorded here so nobody builds from it.

| # | Location | What it says | What supersedes it | What to build |
|---|---|---|---|---|
| **SA-1** | §4.2 "Embedding model" row; §19's C12 traceability row | *"Text only — page rasters are not embedded"* / the raster reaches the dense surface *"through the summary"* | **§2.3 C12** (explicitly *"reversed on evidence"*) and **§3 D4**, corroborated by §5.3's VECTORS block and by §4.2's own "Render dpi" row calling `dpi_index=150` *"the raster that gets embedded"* | the dense vector **is** a fused image+text interleaved embedding; the page raster at `dpi_index=150` is the last `Part`. Owner: **U010** |
| **SA-2** | §2.2 out-of-scope row *"Sparse/lexical vector + RRF fusion — D2, deferred behind a measurement"* | sparse and RRF are out of scope | **§3 D2**, re-decided against the working implementation: sparse ships, `captions` is finally populated, fusion stays `rrf()` at `rrf_k=60`. Only plan2's *measurement* moves to an M8 evaluation | build all three surfaces and RRF in v1. Owners: **U004** (port), **U010** (populate), **U017** (fuse) |
| **SA-3** | §7.2.1's `why` bullet, *"(there is no sparse vector, D2)"* | `lexical` is a text-index hit only | **§3 D2**, **§5.3**'s VECTORS block and **§7.2.1's own ordering rule 1** (*"`lexical` (sparse over the extracted text)"*) | `lexical` is a sparse vector; `why` names **every** branch that contributed, so `"captions"` is a legitimate value. Owner: **U017** |
| **SA-4** | §8.2's *"`relevant` → `read`"* | every relevant candidate goes to the paid tool | **§8.1a**'s bolded *"Default: `fetch`"* and §8.1's loop diagram, which branches to `fetch` **or** `read` | "read" in §8.2 is the generic verb; the route default is `fetch`. Owner: **U021** |
| **SA-5** | §4.1's layout tree | it enumerates no `eval/` package, no `raster_cache`, no `observed_tokens`/`nearmiss`/`present_instead` module | §4.1 is *"a map, not an M0 checklist"*; §12.3/§12.4/§12.6 require the eval commands, §4.2/§7.2.5 require the LRU raster cache, §6.8/§12.4 require the inventory and the generator | add `backend/vsir/eval/` and the three `core/` modules as **net new**, recorded here as a deliberate extension of the map. Owners: **U016**, **U018**, **U005**, **U006** |
| **SA-6** | the prompt's *"a unit inherits its milestone's spend class"* | every unit in M2b/M5/M6/M8 would be marked `paid` | Spec §0's ledger is a **milestone** ceiling; §13 M2b explicitly orders the free port (U012) **before** the paid ingest | unit `Spend` records what the unit **actually** spends; the milestone ceiling is in the Milestone Map. This matters downstream: only `Spend: paid` units may plan an L4 test |
| **SA-7** | §12.3's row `lookup("EAO 84-5140.0020") → total 10 (capped:true)` | with the default `cap=20` and `total=10`, `capped` should be `False` per §7.1 | §7.1 / §7.2.2's own definition (`capped` ⇔ `total > cap`) | treat §7.1's definition as normative and the row's numbers as a table-authoring defect to reconcile under **C10** with a recorded rationale at M2b. Owner: **U013** |
| **SA-8** | §15 Factor VIII *"there is no window-level queue"* vs §15.1 *"ingest scales by queue claim"* | apparently contradictory | **D9** and Factor VIII both describe the `vsir_runs` advisory lease as the only claim mechanism | §15.1's "queue claim" **is** that lease, at **run** granularity. One worker owns one run; there is no window-level queue. Owner: **U011** |
| **SA-9** | §7.2.5's `fetch` header carries no `(free)` label, unlike §7.2.1–7.2.4 | is `fetch` metered? | §13 M4's header (*spend: none*) and §8.1a's cost table (`fetch` costs *"the agent's own context"*; `read` costs *"the entire paid budget"*) | `fetch` is **free**; the shared audit line with `read` (§7.4) tracks image-byte movement, not spend. Owner: **U018** |
| **SA-10** | §6.7 retirement clause 3 carries no failure-row number, unlike clauses 1 (F12) and 2 (F9) | is cross-document isolation unguarded? | clauses 1 and 2 are both filter-scoped to `(doc_id, revision)`, so isolation is structural | not a design gap, but it needs a **regression test**: U011's before/after payload-hash comparison over an untouched second document |
| **SA-11** | §4.1 lists both `core/verify.py` and `serve/tools/verify.py` | duplication? | §13 M1 states it: *"`core/verify.py::verify_claims` … the tool wrapper comes at M3"* | a deliberate two-layer split, matching every other `serve/tools/*` module. Owners: **U006** (core), **U015** (wrapper) |
| **SA-12** | §4.2 has two dpi-220 rows (`dpi_answer` in `read_key`; "Ingest render dpi" in `extract_key`) | two independent renders? | §6.3's `read_key = extract_key inputs ‖ question` makes the reuse explicit | **two dpi values, three uses**: `dpi_index=150` for the embedded raster (U010); `dpi_220` shared by S2 extraction (`extract_key`, U007) and `read` (`read_key`, U020); `fetch`/thumbnail renders at 36/72/150/220/300/400 are cache-only and feed no key (U018) |

### Assumptions (unavoidable — each is Spec §17's recorded default, not an invention)

| # | Assumption | Reason | Validated by | Risk if wrong |
|---|---|---|---|---|
| **A-1** | The pilot PDF is not available yet; ingest is exercised on the generated PDF and derivation on the ported `impl` responses. | Spec §17 **OQ-1** default: the operator places it at `data/source/TC1E-SF.pdf`, and `data/source/` stays gitignored. | `vsir ingest data/source/synthetic_3window.pdf --vlm stub` passes, and U012's parity suite passes, without the PDF. | §12.3's numbers stay unverified against reality; C10's reconciliation and R4's threshold never happen. |
| **A-2** | No live Gemini key through M0–M4 and M7; replay mode (D10) is the path exercised, with paid paths behind `VSIR_ALLOW_PAID=1`. | Spec §17 **OQ-2** default. | The whole pyramid runs green with `VSIR_VLM=stub` and `GEMINI_API_KEY` unset; a network spy records zero calls. | Behaviour Gemini exhibits but the stub does not model — a real schema violation, a real `MAX_TOKENS` truncation — stays undetected until M2b/M5. |
| **A-3** | Part A consumes the §6.8 export over HTTP, never from `data/exports/{run_id}` on local disk. | Spec §17 **OQ-7** default, reinforced by §15 Factor VI. | `GET /runs/{run_id}/export/…` is the only path M8's hand-off exercises; a filesystem-write spy proves nothing is written locally. | If Part A needs a filesystem path this becomes a blocking finding at the M8 hand-off. Mitigation: dual-write to an **attached object store**, never local disk. |
| **A-4** | One Qdrant collection with `doc_id` scoping at 5,505-page scale. | Spec §17 **OQ-5** default. | U025 load-tests against the generated large PDF and re-verifies §20.1 E9 (no scroll-and-filter-in-Python). | A late architecture change after most of the system is built. Mitigation: load-test early, at U025, not at real-corpus cutover. |
| **A-5** | Near-misses are derived, not supplied. | Spec §17 **OQ-4** is resolved by design — `near_misses()` mutates codes from the observed-token inventory of whatever corpus is indexed. | The L3 eval runs in CI from M1 onward without the 8,414-pair list. | None material; the real list, if it arrives, only widens the sample. |

### Risk register

| # | Risk | Units | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| **R1** | Recall is not guaranteed — a summary can omit the line that mattered. | U017, U019, U021 | a relevant page is never surfaced | the `uncertain` pool, "do not filter a small set", `why: lexical` as a hard signal, `searchable_ratio` on every document row; a miss surfaces as an **honest abstention**, never a wrong page | U026 (measures `code_recall`) |
| **R2** | A scanned page's codes are never text-verified. | U006, U020, U023 | codes on image-only pages are `unverifiable` forever | that is the deliverable, not a gap: the three-state vocabulary, the *read from image* badge, and §11.2's zoom-and-re-read requirement | U020 |
| **R3** | PyMuPDF is the single point of truth for exact search. | U007 | a version quirk silently blinds `lookup` | the version is pinned exactly and recorded in `probe_version`; detection is a `grounded_rate` collapse; a bump re-runs the crop and off-by-one fixtures | U001 (pin) + U007 (fixtures) |
| **R4** | `grounded_rate ≥ 0.8` is chosen, not derived. | U011, U013, U026 | a mis-set gate quarantines good documents or publishes bad ones | set it from the M2b distribution with a recorded rationale; the `--override` path means a mis-set threshold cannot strand a document silently; U026 re-validates at corpus scale | U013 |
| **R5** | Multi-tenancy is out of scope. | U003, U014 | a second customer on one instance is a blocking finding | state it in `.env.example` and `AGENTS.md`; the auth boundary is the whole service | U002 |
| **R6** | Prompt-level rules are advisory on the raw MCP surface. | U015, U021 | a careless MCP client ignores the safeguards | every rule that matters is **server-side** — I5, I7, I8 and the §7.3 caps; the answer gate is behind the API, not in the prompt (D7) | U015 |
| **R7** | **The port is a rewrite of a system with 3,268 lines and zero tests.** | U012, all ported units | silent regressions in paths `impl` never exercised, surfacing late against real data | parity against `labels.jsonl` and the negative set from `withheld.jsonl` turn *"does the new code still do what the old code did"* into an assertion — but they **cannot cover most of §7 and §8**. U012 must publish the explicit "no legacy coverage" list | U012 (immediate) / U026 (final) |
| **R8** | Paid-spend sequencing: a paid unit runs before its free prerequisite milestone is green. | U012, U016 | wasted Gemini spend; violates *free before paid* | a CI gate: no `Spend: paid` unit runs until every unit in its own and all prior milestones is green | U002 |
| **R9** | Per-page image embedding is **unbudgeted** — Spec §2.3 C12 puts it at ≈ $0.66 per full 5,505-page run. | U010, U026 | a small, unplanned cost line | it is a cost-model line, not a design change; record it in M8's scale-out costing | U010 |

### Breaking changes for existing `impl` callers (Spec §2.5 D — each needs a conversation)
1. **`200`-empty → typed absence.** Any caller treating an empty `200` as *"no results"* must learn
   four new statuses. An empty `200` is now impossible (I5). — U015
2. **`segment_id` → `page_id`, `verified_identifiers[]` → `codes_in_text[]`** (C8, D1). Part A's
   attachment evidence keeps its meaning under a new name and a new granularity. — U011
3. **Exports move from disk to HTTP** (§6.8). If Part A reads files from `data/exports/{run_id}`, this
   breaks it — **OQ-7**. — U011
4. **Bearer auth everywhere.** Every existing script and notebook needs a token. — U014
5. **No UI until M7.** Anyone using `impl`'s upload-and-search page loses it for the duration. — U023

---

## 9. Traceability Matrix

### A. Spec section → units

| Spec § | Units | Note |
|---|---|---|
| §0 deliverable ledger | all | one ledger line per milestone; the Milestone Map in §3 is its instantiation |
| §1.1 the guarantee · §1.2 the one rule | U005, U006, U022 | I2 + the answer gate are the mechanism |
| §1.3 what this CR builds | U001 | scope framing carried by the M0 skeleton |
| §2.1 in scope | all | realised cumulatively |
| §2.2 out of scope | U002 | enforced negatively by the conformance greps — see SA-2 for the stale sparse row |
| §2.3 corrections C1–C12 | U001 (C1 port framing), U004 (C2, C6), U005 (C2), U006 (C7), U010 (C12), U011 (C8), U013 (C10), U014 (C11), U017 (C5, C11) | distributed; SA-1…SA-12 in §8 record the adjudications |
| §2.4 the port ledger | every ported unit; U012 ports the data | each unit's Requirements name its `impl` source |
| §2.5 the feature-removal ledger | U002 (greps), U014, U015, U023 | enforced by omission plus the greps; §8's breaking-change list |
| §3 decisions D1–D12 | U011 (D1), U004+U010+U017 (D2), U005 (D3), U010 (D4, D8), U009 (D5), U018 (D6), U015 (D7), U011 (D9), U008 (D10), U026 (D11), U017 (D12) | all twelve owned |
| §4.1 layout | U001, plus every unit that creates its own modules | modules are created by the milestone that implements them |
| §4.2 pins and config | U001 | plus `dpi_index`/`dpi_answer` in U010/U007/U020 — see SA-12 |
| §4.3 boot self-check | U001, U014 | `vsir doctor` and server start share the check |
| §4.4 the CLI | U001 (doctor), U005 (demo exact), U007+U011 (ingest, runs show, gates rerun, publish), U014 (serve), U015 (lookup, verify, mcp), U017 (skim, resolve), U018 (fetch, demo narrow), U020 (read), U021+U022 (ask), U025 (resume, retire), U016+U026 (eval) | the full table |
| §5.1 identifiers · §5.3 the page record · §5.4 `INDEXED` · §5.5 text index config | U003 | |
| §5.2 the S2 schema | U008 | |
| §5.6 tokenisation / variants / `exact_filter` | U004 | |
| §5.7 health signals | U009 (produced), U019 (`searchable_ratio` surfaced) | |
| §6.1 steps 01–12 | U007 (01–05), U008 (06), U009 (07–08), U010 (09–10), U011 (11–12) | |
| §6.2 windowing and bisection | U007, U025 (`ladder_level_2_required` exercised) | |
| §6.3 cache keys and replay | U008, U020 (`read_key`) | |
| §6.4 the offset proof | U009 (implemented), U011 (gated) | |
| §6.5 labels and code attribution | U009 | |
| §6.6 embedding fingerprint | U010 | |
| §6.7 publish gating and retirement | U011, U025 (revision lifecycle) | |
| §6.8 exports | U011 (labels, observed_tokens), U005 (the inventory at M1) | |
| §6.9 the run record | U011 | |
| §7.1 envelopes, status, hit models | U004 (models), U015 (surfaced end to end) | |
| §7.2.1 the skim rungs | U017 (`skim_pages`), U019 (the aggregates) | |
| §7.2.2 `lookup` | U005 (pure), U015 (tool) | |
| §7.2.3 `resolve` | U017 | |
| §7.2.4 `verify` | U006 (core), U015 (tool) | |
| §7.2.5 `fetch` | U018 | |
| §7.2.6 `read` | U020 | |
| §7.3 caps | U004 (validators), U018 (fetch), U020 (read) | |
| §7.4 HTTP surface, auth, audit | U014, U011 (`/runs`), U018 (`/pages/{id}/image`), U022 (`/ask`) | |
| §7.5 MCP | U015, U019 (the remaining tools registered) | |
| §7.6 refusals | U004 (no `score`), U015 (no routing), U020 (no judgment in `read`), U022 (only the runner composes), U002 (greps) | |
| §8.1 the loop · §8.3 correction loops · §8.4 the answer gate · §8.5 abstention | U022 | |
| §8.1a fetch-vs-read · §8.2 triage | U021 | |
| §9 invariants | U003 (I6), U004 (I3, I5), U005 (I2), U011 (I1, I4, I7), U022 (I8) | §7 above is the full table |
| §10 failure catalogue | U001, U004, U005, U006, U007, U009, U011, U015, U017, U018, U020, U025 | §7 above is the full table |
| §11.1 publish gates | U011 | |
| §11.2 answer gates | U022 | |
| §11.3 degradation | U014 (primary), U001, U009, U010, U018, U020 | |
| §11.4 observability | U001 (JSON logs), U011 (gauges), U014 (audit), U021 (triage telemetry) | |
| §12.1 fixtures | U005, U007, U012, U013, U025 | |
| §12.2 levels | U002 (scripts), U024 (E2E) | |
| §12.3 acceptance table | U005 (synthetic), U012 (parity), U013 (real), U016 (command) | |
| §12.4 abstention eval | U006 (eval), U016 (command), U022 (extended to `/ask`) | |
| §12.5 conformance greps | U002 | |
| §12.6 corpus evaluation | U026 | |
| §13 milestones | all, grouped by the Milestone Map | |
| §14 acceptance criteria | see table C | |
| §15 twelve factors | U001 (I, II, III, V, XI), U014 (VI), U018 (VI rasters), U011+U025 (IX), U002 (X), U025 (XII) | |
| §15.1 orchestrator requirements | U002 (probes), U018 (resource limits), U025 (SIGTERM at scale) | |
| §15.2 bans | U001, U002 | |
| §16 NFRs | U017 (reproducibility, laziness), U008 (determinism), U010 (idempotence), U014 (security, async hygiene, typing), U023 (frontend), U001 (deployment) | measured by U026 for latency and cost |
| §17 open questions | U013 (OQ-1, OQ-2), U011+U025 (OQ-3, OQ-7), U006 (OQ-4), U025 (OQ-5) | defaults recorded in §8 A-1…A-5 |
| §18 residual risks | see §8's risk register | R1–R9 each have an owning unit |
| §19 traceability to plan2 | U001 (README), U002 (AGENTS.md) | rationale, not implementation; SA-1 flags its stale C12 row |
| §20 document map | every ported unit's **Required Reading** | the mechanism by which detail is loaded at build time, not planning time |
| §20.1 known-defect register | U003 (A5, B1/B4), U007 (A1, E3), U008 (B2, B6), U010 (B5, D3, E7), U011 (E1/E2/E4/E7/E8), U012, U014 (E5), U017 (E9), U025 (E2, E7, E9 at scale) | *do not port a known defect* |

### B. AC → units → tests

| AC | Units | Named test(s) | Level |
|---|---|---|---|
| **AC-001** | U005, U015 | `test_hallucinated_code_never_findable`; `test_unverified_hits_opt_in_only` | L2 |
| **AC-002** | U004, U005 | `test_variants_whitespace_only_property`; `test_all_eight_compact_labels_found` | L0, L2 |
| **AC-003** | U004, U015 | `test_status_enum_has_six_values`; `test_search_response_never_empty_ok`; `test_status_enum_end_to_end` | L0, L2 |
| **AC-004** | U011, U015 | `test_fully_scanned_document_publishes`; `test_lookup_scanned_page_not_searchable` | L2 |
| **AC-005** | U006, U015, U020 | `test_verify_claims_absent_on_p008`; `test_k73_absent_with_present_instead_k78`; `test_read_stamps_three_states` | L0, L2 |
| **AC-006** | U009, U011 | `test_offset_structural_check`; `test_offset_independent_observation_bisects`; `test_offset_check_catches_shifted_pages` | L1, L2 |
| **AC-007** | U011 | `test_unpublished_run_zero_queryable_pages`; `test_kill_mid_run_zero_queryable_pages` | L2 |
| **AC-008** | U004, U018, U020 | `test_caps_typed_400_naming_bound`; `test_fetch_budget_exceeded_names_bound`; `test_read_page_cap_exceeded` | L0, L2 |
| **AC-009** | U022 | `test_worked_trace_one_paid_read_with_citations` (replay, call-count spy); `test_reads_per_question_ceiling_429` | L2 |
| **AC-010** | U022 | `test_abstention_names_coverage_numbers`; `test_forbidden_wording_while_image_only_pages_unread` | L0, L2 |
| **AC-011** | U006, U016 | `test_near_miss_codes_never_answer` (100 cases, CI on every commit) | L3 |
| **AC-012** | U001, U014 | `test_doctor_refuses_latest_model_alias`; `test_boot_refuses_on_schema_drift`; `test_boot_refuses_on_fingerprint_mismatch` | L0, L2 |
| **AC-013** | U011 | `test_labels_jsonl_shape`; `test_safety_flag_from_doctype_and_topics` | L1, L2 |
| **AC-014** | U001+U002 (M0), U005 (M1), U011 (M2a), U013 (M2b), U015+U016 (M3), U018 (M4), U020 (M5), U022 (M6), U024 (M7), U025+U026 (M8) | each milestone's §0 demo command, recorded green in the progress file: `vsir doctor && bash scripts/test-unit.sh` · `vsir demo exact --synthetic` · `vsir ingest … --vlm stub` · `VSIR_ALLOW_PAID=1 vsir ingest … TC1E-SF.pdf` · `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` · `vsir demo narrow` · `VSIR_ALLOW_PAID=1 vsir read …` · `VSIR_ALLOW_PAID=1 vsir ask "…"` · `bash scripts/test-e2e.sh` · `vsir ingest --resume <run_id>` and `vsir eval corpus` | L0–E2E; **the M2b slice is L4** |
| **AC-015** | U001, U014, U002 | `test_env_only_config_no_committed_file`; `test_no_module_level_session_store`; `test_one_image_all_process_types`; `test_no_local_disk_state` | conformance, L2 |
| **AC-016** | U025, U002, U011 | `test_sigterm_checkpoint_loses_at_most_one_window`; `test_resume_completes_without_rebilling`; `test_qdrant_down_503_ready_red_health_green` | L2 |

### C. Unmapped items
- **Spec sections with no unit:** none. §0, §1.3, §2.1, §2.2, §2.5, §16, §17, §18, §19, §20 and §20.1
  are rationale or register tables; each is carried by a named unit's Required Reading, Definition of
  Done, or the risk register in §8, and is marked as such above.
- **Units with no spec section:** none.
- **ACs with no unit or no test:** none.
- **ACs whose only proof is paid:** **AC-014's M2b slice only** — M2b's whole purpose is the one paid
  ingest, so there is no fixture-backed substitute for that milestone's demo command. **AC-009** is a
  softer instance: it has a deterministic L2 replay proof today, but the worked-trace fixture's
  fidelity traces back to the same M2b calibration.

---

## 10. Implementation Order

Milestone order is fixed. Within a milestone, this order keeps every dependency satisfied and every
free proof ahead of every paid one.

| # | Unit | Milestone | Why here |
|---|---|---|---|
| 1 | U001 | M0 | the root of the graph; nothing starts without the runtime and `vsir doctor` |
| 2 | U002 | M0 | the greps and the test scripts must exist before any behaviour is claimed |
| 3 | U003 | M1 | the record, ids and `INDEXED` that everything reads or writes |
| 4 | U004 | M1 | the exact surface and both envelopes — the fan-out point for M1's tail **and** M2a |
| 5 | U007 | M2a | starts the ingest chain (needs only U001, U003) — runs in parallel with steps 6 and 8 |
| 6 | U005 | M1 | the synthetic seed and `lookup`; needs only U004 |
| 7 | U008 | M2a | the VLM boundary and S2 extraction, continuing the ingest chain |
| 8 | U006 | M1 | `verify_claims` and the L3 eval — closes the M1 correctness proof |
| 9 | U009 | M2a | derivation, the offset proof, stitching |
| 10 | U010 | M2a | embedding and indexing — the first join of the two streams (needs U009 **and** U004) |
| 11 | U011 | M2a | gates, publish, retirement, the run plane — closes M2a and unlocks M2b **and** M3 |
| 12 | U012 | M2b | **free** — ports the already-paid fixtures and the parity suite; the gate before any spend |
| 13 | U014 | M3 | needs only U011, so it runs in parallel with U012/U013 rather than waiting on M2b |
| 14 | U013 | M2b | **the first spend anywhere in the plan**, gated by a green parity suite and by OQ-1/OQ-2 |
| 15 | U015 | M3 | the core→tool seam: `lookup` and `verify` over HTTP and MCP |
| 16 | U016 | M3 | the acceptance and abstention commands; needs U015 and U012's parity fixtures |
| — | **U027** | M3 | ✅ *shipped 2026-09-10* — `POST /documents`, so the API can be given a document |
| — | **U028** | M2a/b | ✅ *shipped 2026-09-10* — the five corrections the first live Gemini run found |
| — | **U030** | M3 | ✅ *shipped 2026-09-10* — `/console`, the OpenAPI security scheme, the local stack |
| 17 | U017 | M4 | `skim_pages`, fusion, image queries, `resolve`. **The best next unit:** unblocked, needs no new storage, and it is the first thing to *read* the fused image+text vectors U010 has been writing all along — today they are written and never queried |
| 18 | **U029** | M4 | ✅ **shipped 2026-09-10.** the document store — `page_id → bytes`. Small, and without it the whole vision half of retrieval had nothing to render from |
| 19 | U018 | M4 | the page-image endpoint, the raster cache and `fetch` — closes M4. **Needs U029** |
| 20 | U019 | M5 | **free** — the aggregate rungs and `searchable_ratio`; parallel with U020 |
| 21 | U020 | M5 | `read` — the paid tool; parallel with U019 |
| 22 | U021 | M6 | **free** — triage and routing, provable with no paid call |
| 23 | U022 | M6 | the loop and the answer gate — closes the product's answer path |
| 24 | U023 | M7 | the console — **replaces** U030's stopgap page rather than extending it; parallel with U025 |
| 25 | U025 | M8 | revisions, resume, graceful shutdown; parallel with U023 |
| 26 | U024 | M7 | the Playwright replay suite — the M7 demo |
| 27 | U026 | M8 | the corpus evaluation report — the last unit |

---

## 11. Parallel Bundles

Grouped by dependency layer. **No layer mixes milestones.** The build loop uses this to decide what
can run concurrently.

### Layer 1 (M0, no dependencies)
- U001

### Layer 2 (M0, depends only on Layer 1)
- U002

### Layer 3 (M1, depends only on Layers 1–2)
- U003

### Layer 4 (M1, depends only on Layer 3)
- U004

### Layer 5 (M1, depends only on Layer 4)
- U005

### Layer 6 (M1, depends only on Layers 4–5)
- U006

> **Cross-milestone note (not a bundle):** U007 depends only on U001 and U003, so the M2a ingest chain
> may start as soon as Layer 3 lands and run alongside Layers 5–6. That is a **scheduling**
> opportunity for a second owner, not a bundle — the two streams belong to different milestones and
> M2a is not complete until M1 is.

### Layer 7 (M2a, depends only on Layers 1–3)
- U007

### Layer 8 (M2a, depends only on Layer 7)
- U008

### Layer 9 (M2a, depends only on Layer 8)
- U009

### Layer 10 (M2a, depends only on Layers 4 and 9)
- U010

### Layer 11 (M2a, depends only on Layer 10)
- U011

### Layer 12 (M2b, depends only on Layer 11)
- U012

### Layer 13 (M2b, depends only on Layer 12)
- U013

### Layer 14 (M3, depends only on Layer 11)
- U014

### Layer 15 (M3, depends only on Layers 5, 6 and 14)
- U015

### Layer 16 (M3, depends only on Layers 12 and 15)
- U016

### Layer 17 (M4, depends only on Layers 10 and 15)
- U017

### Layer 18 (M4, depends only on Layers 7 and 17)
- U018

### Layer 19 (M5, depends only on Layers 6, 8, 17 and 18)
- **U019, U020** — run concurrently: U019 needs only U017; U020 needs U018, U008 and U006. Neither
  depends on the other. U019 is free, U020 is the paid one.

### Layer 20 (M6, depends only on Layers 18–19)
- U021

### Layer 21 (M6, depends only on Layers 19–20)
- U022

### Layer 22 (M7 and M8 — two independent branches off U022; **do not mix them into one bundle**)
- **M7 branch:** U023, then U024
- **M8 branch:** U025 (also needs U011), then U026 (also needs U016 and U013)

The two branches can be worked concurrently by separate owners; within each branch the two units are
strictly sequential.

---

## Appendix: Quality validation (Phase 6)

- [x] Every spec section maps to at least one unit — §9 A, no unmapped rows
- [x] Every unit has a Working Deliverable **and** a Demo Command — 26 of 26
- [x] Every unit belongs to exactly one milestone; no unit crosses a boundary
- [x] Every I1–I8 and F1–F19 has an owning unit and a named test — §7 reports **no Uncovered rows**
- [x] Every AC-001…AC-016 maps to units and tests — §9 B
- [x] Unit IDs unique and sequential (U001–U026); dependencies acyclic and never backwards across a milestone
- [x] Units are atomic and PR-sized (1–3 days); total **26**, within the 18–26 target
- [x] No unit plans a Gemini call at L0–L3 or E2E — only U013, U020, U022 plan an L4 test and U026 an L5 report, all behind `VSIR_ALLOW_PAID=1`
- [x] No unit introduces a banned construct (Spec §12.5, §15.2) or a dependency outside Spec §4.2
- [x] Every unit adding a process/endpoint/worker complies with Spec §15; AC-015 and AC-016 are mapped to units and tests
- [x] No unit claims an invariant or failure row outside its milestone's ownership (§9, §10)
- [x] **Spec unchanged** — gap analysis found no true blocker; every apparent contradiction is resolved by §2.3, §3 or §17 and recorded as SA-1…SA-12 in §8
