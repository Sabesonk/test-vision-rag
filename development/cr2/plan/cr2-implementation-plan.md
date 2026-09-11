# Implementation Plan: CR2 — `POST /search`, the flat retrieval surface

**Source Specification:** `development/cr2/spec/spec.md`
**Implementation Type:** backend (one server-rendered console tab; no React work)
**Status:** In Progress — **4 of 7 units shipped before the plan was written** (§1.3)
**Created:** 2026-09-11
**Last Updated:** 2026-09-11

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

Seven units across five milestones (S1–S5). Every unit ships a runnable artefact and a demo
command; **a milestone with no runnable demo is not complete** (Spec §0, inherited from CR1 §0).

### 1.1 Key deliverables
- `POST /search` — one free call returning ranked pages **with their content**, a typed `status`,
  the query interpretation, and each row's next operations already assembled — Spec §4.
- Keyword filters through the **one** exact-match code path, with the pages they could not reach
  disclosed rather than silently dropped — Spec §4.4.
- The operator's view of both: the console's Search tab, and the ingested documents on a host
  directory a person can `ls` — Spec §8 S3, D-S9.
- The CLI subcommand that makes this surface *supported* under CR1 §4.4 — **not built**.
- The browser proof and the measurement — **not built**.

### 1.2 Unit numbering
Units continue CR1's sequence from **U033** rather than restarting at U001. CR1's plan §4b set the
precedent and gave the reason: unit ids are referenced across the progress record, the commit
history and the fixes bundle, so a second CR that restarted the numbering would make `U005` mean
two different things depending on which document you were holding. No existing unit id moves.

### 1.3 Nature of the work — read this first
**Four of the seven units shipped before this plan existed**, in one commit (`c1d3100`) on
`feat/search-surface-and-document-store`. This plan is therefore part record and part plan, and
each unit says which it is:

- **U033–U036** are recorded as built, with their real test evidence and their real disclosed
  limitations. Their "Acceptance Criteria" are checked against the shipped code, not against intent.
- **U037–U039** are planned in the ordinary way and nothing in the repository implements them.

The most consequential finding of writing this plan is **U037's**: CR1 §4.4 makes the `vsir` CLI
*the only supported operational surface*, and the flat surface has no subcommand — so the newest
surface in the service is, by CR1's own definition, unsupported (Spec X5, FS14).

### 1.4 Technology stack
No addition to CR1 §4.2. `serve/retrieval.py` uses `pydantic`, `qdrant-client` and the modules
CR1 already pins; the console tab is inlined HTML/CSS/JS in the one static file the serving app
hands out — no npm, no build step, no second container (CR1 U030's argument, unchanged).

---

## 2. Scope and Objectives

### In scope (Spec §2.1)
`POST /search` and its bounds · `require_phrases` / `exclude_phrases` as branch filters ·
`branch_must` / `branch_must_not` on `_candidates` · the console's Search tab · the document store
as a host directory · `vsir search` · the e2e spec and the evaluation.

### Out of scope (Spec §2.2)
A ninth tool or MCP exposure · any score or threshold · answer composition · a second fusion or
absence rule · server-held scope · OCR · the React operator console.

### Success criteria
Spec §9's eleven acceptance criteria (AC-S01…AC-S11), mapped to units in §9 below. AC-S01…AC-S09
are met by the shipped units; AC-S10 and AC-S11 are what U037–U039 exist to close.

---

## 3. Milestone Map

| S | Units | Demo command (Spec §0) | Spend | Invariants | Failure rows |
|---|---|---|---|---|---|
| **S1** | U033 | `bash scripts/test-api.sh -k search_surface` | none¹ | I-S1, I-S2, I-S4, I-S5, I-S6, I-S7 | FS1, FS2, FS4–FS10 |
| **S2** | U034 | `bash scripts/test-api.sh -k keyword` | none¹ | I-S3, I-S8 | FS3, FS11 |
| **S3** | U035, U036 | `bash scripts/stack.sh up` then `http://localhost:8055/console` → **Search** | none | — | FS12, FS13 |
| **S4** | U037 | `vsir search "safety output" --doc SICK-DETECTOR-BOX --require "safety output"` | none¹ | — | FS14 |
| **S5** | U038, U039 | `bash scripts/test-e2e.sh` · `vsir eval search` | none | — | FS15 |

¹ No **vision** call. A text query embeds through the embedding model on every request, exactly as
every `skim_*` rung does (Spec D-S10).

---

## 4. Implementation Units

---

## Unit: `POST /search` — the flat surface (ID: U033)

**Status:** 🟢 Complete (2026-09-11)
**Milestone:** S1
**Priority:** P0-Critical
**Type:** api
**Size Estimate:** Large
**Spend:** none (no vision call; the query embeds — D-S10)

### Goal
Give a consuming system that is **not** the Part A agent one free call that returns ranked pages
with their content, so it can do its own reasoning without paying an inference turn per ladder rung.

### Working Deliverable
`POST /search` — ranked rows, a typed status, the query interpretation, and per-row assembled
operations; the whole contract published in `/openapi.json`.

### Deliverables (files)
- `backend/vsir/serve/retrieval.py` — **written**, net new (1,157 lines): the request and response
  models, the bounds and their codes, the row assembly, the interpretation.
- `backend/vsir/serve/app.py` — **extended**: the route, the `$ref` body, the four named examples.
- `backend/vsir/serve/tools/skim.py` — **extended**: `_candidates` is called with `rung="search"`
  and later gains `branch_must` / `branch_must_not` (U034). `surface_ranks` is **not** new here —
  `skim.py` has always computed it and `PageHit` has always discarded it; `/search` is the first
  surface to publish it.
- `backend/tests/api/test_search_surface.py` — **written**: 56 tests.

### Requirements
- **The same retrieval.** `_candidates()` is called directly with the same weights, `k`, scope
  filter and payload projection the three `skim_*` rungs use (Spec D-S3). No second fusion.
- **`status` from the rungs' own rule.** `lookup.absence()`, not a second opinion (Spec X2, I-S1).
- **No magnitude.** `rank`, `surface_ranks`, `best_rank` — ordinals only; `_total()`'s RRF value
  stays private in `skim.py` (Spec D-S2).
- **`include` omitted returns all six parts; `[]` is an explicit none; unrequested fields are
  `null`** (Spec D-S4). `text` costs one bounded `retrieve` over the rows actually returned — it is
  not in `ROW_PAYLOAD` and must not be added there, or all three rungs pay for a field none returns.
- **Every bound refused with its own code, never clamped** (Spec D-S11, §4.1's table), and validated
  in the handler rather than by FastAPI so a `422` can never replace a typed code (Spec D-S8).
- **`has_text` derived from `text_trust`**, never read from a payload field `ROW_PAYLOAD` does not
  project (FS10).
- **Actions assembled, not described**, with `spends` true on exactly `comprehend` (Spec D-S7).
  `expand_section` is omitted when there is no query text to carry, because the affordance's whole
  promise is that the body can be posted verbatim and `/search` refuses a body with nothing to
  search for.
- Off the tool table, absent from MCP, no `ToolSpec` row (Spec D-S1).

### Dependencies
- **Depends On:** [CR1 U017 (`_candidates`, fusion), U018 (`fetch`, the raster reference),
  U019 (`searchable_ratio`), U029 (the document store), U031 (the typed API surface and
  `serve/errors.py`), **U025** (`envelope.SupersededIn`, `lookup.absence(..., superseded=)`)]
- **Enables:** [U034, U036, U037, U038]
- **External:** none beyond CR1 §4.2.

### Acceptance Criteria
- [x] Five-value `status`, agreeing with `skim_pages` on the same scope.
- [x] No field named `score` in any model (conformance grep green).
- [x] `include` semantics as D-S4; `null` vs `""` distinguishable.
- [x] Every bound in Spec §4.1 refused by its own code.
- [x] Every row's assembled arguments accepted verbatim by their target surfaces.
- [x] `SearchRequest` and `SearchResult` in `/openapi.json`, four named examples, the fully
      populated one first.

### Test Plan
**Test Types:** L2 (index contract, real Qdrant), L3 (adversarial absence), conformance greps.
**Test Data:** the seeded replay collection the API suite already builds; no new fixture.
**Edge Cases:** a scope matching nothing · an identifier-only query · a branch weighted zero ·
an image-only query · `offset` past the pool · an inverted page range · an unknown key in the
negation · a stored `text_trust` outside the four values.

### Definition of Done
- [x] 56 tests pass (`test_search_surface.py`).
- [x] No skipped or xfailed tests in the file.
- [x] Demo command green.

### Risks and Mitigations
- **Risk:** the surface drifts from `skim_pages` as fusion changes. **Mitigation:** one
  `_candidates`, one `absence()`, and a test that asserts the agreement rather than the code path.
- **Risk:** a consumer treats `content.text` as verified. **Mitigation:** `text_usable` on every
  row and named in the schema; it cannot be prevented, only disclosed (Spec §11).

### Rollback Plan
- Remove the route and `serve/retrieval.py`; revert `skim.py`'s `branch_*` parameters and the
  `surface_ranks` publication. No stored state, no index change, no tool contract touched —
  nothing to migrate back.

---

## Unit: Keyword filters and the branch filter (ID: U034)

**Status:** 🟢 Complete (2026-09-11)
**Milestone:** S2
**Priority:** P0-Critical
**Type:** api
**Size Estimate:** Medium
**Spend:** none¹

### Goal
Let a consumer require or forbid a phrase being **printed on the page**, through the same exact
path as `lookup`, without a filter's emptiness ever being reported as the corpus's.

### Working Deliverable
`require_phrases` / `exclude_phrases` on `POST /search`, with the excluded-page count disclosed on
every response.

### Deliverables (files)
- `backend/vsir/serve/retrieval.py` — `phrase_conditions()`, `validate_phrase_terms()`.
- `backend/vsir/serve/tools/skim.py` — `_candidates` gains `branch_must` / `branch_must_not`,
  **distinct from** `extra_must` / `extra_must_not`.
- `backend/tests/api/test_search_surface.py` — 11 of the 56 tests.

### Requirements
- **One matcher.** Each term becomes a nested `core/exact.exact_filter` — an OR over that term's
  `variants()` spellings — and terms are ANDed by being separate conditions. Assembling
  `MatchPhrase` here would be a second matcher in `serve/`, which CR1 I3/F1 ban (Spec I-S3).
- **Branch filter only** (Spec D-S5). A content filter that matched nothing has *searched* the
  scope: routing it through the scope denominator answers `out_of_scope` and sends the caller to
  widen a scope that was never the problem (FS11).
- **The asymmetry is required, both halves safe:** a page with no readable text is *excluded* by
  `require_phrases` and *kept* by `exclude_phrases` (Spec §4.4).
- **The disclosure is mandatory:** `pages_searched`, `searchable_pages`, `pages_without_text` on
  every response, so a large gap is visible before an empty result is read as absence (FS3).
- An empty term is refused (`phrase_empty`), never dropped; more than ten is refused
  (`too_many_phrase_terms`), never truncated.

### Dependencies
- **Depends On:** [U033, CR1 U004 (`variants`, `exact_filter`)]
- **Enables:** [U036, U039]

### Acceptance Criteria
- [x] `"safety output"` matches the ordered phrase, not pages carrying both words apart.
- [x] `"SF 1.1A"` finds `"SF1.1A"` — `variants()` applies.
- [x] Requiring and excluding the same phrase matches nothing, and answers `not_found`.
- [x] An unmatched filter is `not_found`, never `out_of_scope`.
- [x] A required phrase never reaches a page with no readable text.
- [x] No `MatchPhrase` or `MatchText` constructed in `serve/` outside `core/exact.py`.

### Test Plan
**Test Types:** L2, L3, conformance grep (`MatchText` banned in `serve/`).
**Edge Cases:** an empty term · eleven terms · a phrase that exists only on an `untrusted` page ·
a filter that matches nothing inside a scope that matches plenty.

### Definition of Done
- [x] The eleven keyword tests pass; the conformance suite stays green.

### Risks and Mitigations
- **Risk:** a caller reads an empty keyword result as absence. **Mitigation:** the three counts,
  and the schema text on `require_phrases` that names the comparison to make.

### Rollback Plan
- Drop the two fields and the four `branch_*` parameters; `_candidates`'s existing callers pass
  none of them, so the three rungs are unaffected.

---

## Unit: The document store on the host (ID: U035)

**Status:** 🟢 Complete (2026-09-11)
**Milestone:** S3
**Priority:** P2-Medium
**Type:** config
**Size Estimate:** Small
**Spend:** none

### Goal
Make the ingested PDFs visible and manageable where the operator actually works, and make a wipe
take the index and the store together.

### Working Deliverable
`${VSIR_DOCUMENTS_DIR:-./var/documents}` bind-mounted at `/srv/documents`; `stack.sh down --wipe`
empties it.

### Deliverables (files)
- `docker-compose.yml` — the bind mount replacing the named volume, with the Linux uid note.
- `scripts/stack.sh` — `cmd_down --wipe` empties the directory after `down -v`.
- `.env.example`, `.gitignore` — the variable, documented; the directory, ignored.

### Requirements
- **Nothing was ever baked into the image** — the build context is `backend/`, so `data/` is
  unreachable at build time. What changed is only *where the volume lives*.
- A named volume on macOS and Windows lives inside the Docker VM: *"where did my document go?"*
  had no answer a person could `ls`, and replacing a corrupt PDF meant `docker cp` (Spec D-S9).
- **A wipe takes both.** `down -v` no longer reaches a host directory, so `--wipe` empties it
  explicitly — a wipe that dropped the index and left the store would leave a store describing a
  corpus that is no longer indexed, every `page_id` in it unresolvable and nothing saying why.
- `find "$documents" -mindepth 1 -delete` — the mount point itself survives, because the compose
  mount expects it to exist.
- **Page rasters are still never persisted** (CR1 §4.2). There are no image files to move.

### Dependencies
- **Depends On:** [CR1 U029 (the document store itself)]
- **Enables:** [U036]

### Acceptance Criteria
- [x] An ingested PDF appears under `var/documents/` on the host as `<doc_id>@<revision>.pdf`.
- [x] `stack.sh down --wipe` leaves neither index nor stored document behind.
- [x] `stack.sh down` (no flag) leaves both.
- [x] The path is overridable and git-ignored.

### Test Plan
**Test Types:** L5 manual canary — this is compose wiring, and a test that asserted a bind mount
would assert Docker rather than this service.
**Edge Cases:** Linux uid 10001 cannot write a bind mount the image `chown`ed at build — documented
in `docker-compose.yml` with the one-line fix rather than worked around.

### Definition of Done
- [x] `bash scripts/stack.sh up`, ingest, `ls var/documents`, `down --wipe`, `ls` again.

### Risks and Mitigations
- **Risk:** an operator edits a stored PDF in place and the bytes stop matching the run record's
  `content_hash`. **Mitigation:** CR1 U029 already refuses bytes that disagree rather than serving
  them — visibility does not weaken the integrity check.

### Rollback Plan
- Restore the named volume in `docker-compose.yml` and drop the `--wipe` branch. Existing files
  must be copied into the volume first, or the store silently starts empty.

---

## Unit: The console's Search tab (ID: U036)

**Status:** 🟢 Complete (2026-09-11)
**Milestone:** S3
**Priority:** P1-High
**Type:** component
**Size Estimate:** Medium
**Spend:** none

### Goal
Give an operator a way to turn the fusion's knobs and see what a consuming system would receive —
in the one static file the serving app already hands out.

### Working Deliverable
The **Search** tab at `/console`: status and its next action, the interpretation panel, per-row
thumbnails, click-to-expand row details, the assembled operations with the billing one marked, and
a scope builder whose keys come from `/openapi.json`.

### Deliverables (files)
- `backend/vsir/serve/console/index.html` — the tab, its form and its renderer (+548 lines).
- `backend/tests/api/test_console.py` — 18 tests added (38 in the file).

### Requirements
- **A purpose-built form, and that is the exception to this file's rule.** Every tool form is
  generated from `/openapi.json`; `/search` is not a tool, so it gets content toggles, a page-range
  pair and the fusion's weights laid out for an operator turning a knob.
- Because the parameter names are therefore **written out by hand**, `test_console.py` pins the one
  list that could silently fall behind: `const PARTS` against `retrieval.PARTS` (FS12).
- The block that draws it sits **below** the API section, so the conformance scan over that section
  is not looking at honest literals inside this one.
- Thumbnails are fetched with the bearer token an `<img>` tag cannot carry.
- The scope builder offers only facets the server would accept — its keys come from the published
  schema, so the page cannot offer a filter that would be refused.
- Still **one free path** (`auth.CONSOLE_PATHS`): no bundle, no second asset, no widening of the
  unauthenticated surface.

### Dependencies
- **Depends On:** [U033, U034, CR1 U031 (`/openapi.json`), CR1 U023/U030 (the console file)]
- **Enables:** [U038]

### Acceptance Criteria
- [x] The typed status renders with the action it implies — `not_found` as an answer, not a blank table.
- [x] `PARTS` in the page equals `retrieval.PARTS`.
- [x] The scope builder's keys are the published `FILTER_KEYS`.
- [x] A row expands to its content, and its assembled operations show which one spends.

### Test Plan
**Test Types:** L2 over the served HTML.
**Edge Cases:** a release whose corpus is empty · a row with `no_text` · a status of
`found_only_in_superseded`.
**Gap (declared):** these are Python assertions over HTML, **not a browser** — U038 exists because
of that.

### Definition of Done
- [x] `test_console.py` — 38 passed.

### Risks and Mitigations
- **Risk:** the hand-written form falls behind the schema. **Mitigation:** the `PARTS` pin catches
  the list; the scope keys are read from the schema so they cannot fall behind at all.

### Rollback Plan
- Remove the tab's markup and its script block; the file's other tabs are independent.

---

## Unit: `vsir search` — the supported operational surface (ID: U037)

**Status:** 🔵 Not Started
**Milestone:** S4
**Priority:** P1-High
**Type:** component
**Size Estimate:** Medium
**Spend:** none¹

### Goal
Make the flat surface reachable from the one place CR1 §4.4 calls supported, so an operator does
not have to hand-write `curl` bodies containing `@` and `#`.

### Working Deliverable
`vsir search "<query>" [--doc …] [--require …] [--exclude-phrase …] [--include …] [--limit …]
[--offset …] [--weights …] [--json]` — printing the typed status, the interpretation, and the rows.

### Deliverables (files)
- `backend/vsir/cli.py` — **extend**: the subcommand and its argument mapping.
- `backend/tests/unit/test_cli_search.py` — **write**: argument → `SearchRequest` mapping.
- `backend/tests/api/test_cli_search_parity.py` — **write**: the CLI and the HTTP body return the
  same rows for the same arguments.

### Requirements
- **One implementation.** The subcommand builds a `SearchRequest` and calls `retrieval.search()`
  in-process (as `vsir lookup` does), or posts to the running service — **not** a second assembly
  of the filter. Register **E1** (CR1 U027) is the standing warning: two code paths for one
  operation meant one of them silently did less than the whole job.
- **The typed status is printed, never a blank table.** `not_found`, `not_searchable`,
  `out_of_scope` and `found_only_in_superseded` each print what they mean and what to do next —
  a CLI that prints nothing for four different facts is the terminal's version of an empty list.
- `--json` emits the response body verbatim, so the CLI can be piped into the same consumer the
  HTTP surface serves.
- Every refusal keeps its code on stdout and a non-zero exit — a bound hit at the CLI must not
  become a Python traceback.
- `--require` / `--exclude-phrase` are repeatable and map one-to-one onto the phrase lists.

### Dependencies
- **Depends On:** [U033, U034]
- **Enables:** [U039]

### Acceptance Criteria
- [ ] Every field of `SearchRequest` is reachable from the CLI, or is documented as deliberately absent.
- [ ] The same arguments produce the same rows through both surfaces (asserted, not assumed).
- [ ] Each typed absence prints its next action.
- [ ] A bound violation exits non-zero with its code and no traceback.
- [ ] `AGENTS.md` and CR1 §4.4's CLI table list the subcommand.

### Test Plan
**Test Types:** L0 (argument mapping, pure), L2 (parity against a seeded collection).
**Test Data:** the API suite's seeded replay collection.
**Edge Cases:** a query that is only an identifier · repeated `--require` · `--weights dense=0`
· an empty corpus.

### Definition of Done
- [ ] Both test files pass; `bash scripts/test-unit.sh` and `bash scripts/test-api.sh` green.
- [ ] Demo command output pasted into the progress file.

### Risks and Mitigations
- **Risk:** the subcommand becomes a second assembly of the request and drifts. **Mitigation:**
  it constructs `SearchRequest` and nothing else; the parity test fails if it does more.

### Rollback Plan
- Remove the subcommand. Nothing depends on it at runtime; CR1 §4.4's gap simply reopens.

---

## Unit: The Search tab under a browser (ID: U038)

**Status:** 🔵 Not Started
**Milestone:** S5
**Priority:** P2-Medium
**Type:** test
**Size Estimate:** Small
**Spend:** none

### Goal
Prove in a browser what 38 Python assertions over HTML cannot: that the tab a consumer's operator
uses actually renders a typed absence with its next action, and that its assembled operations work
when clicked.

### Working Deliverable
`e2e/tests/search.spec.ts` in the existing Playwright replay suite.

### Deliverables (files)
- `e2e/tests/search.spec.ts` — **write**.
- `e2e/tests/console.ts` — **extend**: a helper that reaches the Search tab.

### Requirements
- Replay-backed, spending nothing, running inside `bash scripts/test-e2e.sh` with the rest.
- Asserts: a query returns rows with ranks and no score anywhere in the DOM; a scope that matches
  nothing renders `out_of_scope` **with its next action** and not an empty table; a row expands to
  its content; `comprehend` is visibly marked as the operation that spends; the scope builder
  offers only published facets.
- Picks its document by **searching the corpus for one with the properties it needs**, as
  `console.ts` already does — never `documents[0]`.

### Dependencies
- **Depends On:** [U036]
- **Enables:** none

### Acceptance Criteria
- [ ] The spec fails if a status renders without its next action.
- [ ] The spec fails if any rendered row shows a magnitude.
- [ ] `bash scripts/test-e2e.sh` green with the spec included.

### Test Plan
**Test Types:** E2E (Playwright, replay mode).
**Edge Cases:** an empty corpus (skip with a named reason, never a silent pass) · a row with no
text layer.

### Definition of Done
- [ ] The suite is green and the new spec is in it.

### Risks and Mitigations
- **Risk:** a browser test that asserts styling becomes brittle. **Mitigation:** assert the
  contract — status, next action, absence of a magnitude — never the layout.

### Rollback Plan
N/A — test-only.

---

## Unit: `vsir eval search` — the surface measured (ID: U039)

**Status:** 🔵 Not Started — **gated by CR1 OQ-1** (the real corpus is absent)
**Milestone:** S5
**Priority:** P3-Low
**Type:** test
**Size Estimate:** Medium
**Spend:** none

### Goal
Replace two asserted properties with measured ones: that `/search` agrees with `skim_pages`, and
what the keyword filters' unreadable-page exclusion actually costs on a real corpus.

### Working Deliverable
`vsir eval search` — a report, exiting non-zero on a failed gate.

### Deliverables (files)
- `backend/vsir/eval/search.py` — **write**.
- `backend/vsir/cli.py` — **extend**: the subcommand.
- `backend/tests/unit/test_eval_search.py` — **write**: the arithmetic, including the zero
  denominator.

### Requirements
- **Agreement, not similarity:** for each evaluation query, `/search` and `skim_pages` return the
  same page set at the same ranks under the same weights. A disagreement is a failure, not a delta.
- **The exclusion rate is the headline:** the share of in-scope pages a `require_phrases` filter
  can never reach, per document. This is the number Spec §4.4's disclosure exists to make visible,
  and today nothing states it.
- **`0/0` is `None` and a named skip, never `1.00`** — CR1 U026's finding, and it applies here
  verbatim: a zero denominator is the one arithmetic accident that turns an absent corpus into a
  perfect score.
- A set with no ground truth **skips with a named reason** and is counted in the summary.

### Dependencies
- **Depends On:** [U034, U037, CR1 U026 (`vsir eval corpus`'s report shape)]
- **Enables:** none

### Acceptance Criteria
- [ ] Agreement with `skim_pages` reported per query set, with any disagreement named.
- [ ] The keyword exclusion rate reported per document.
- [ ] A zero denominator never prints as a passing score.
- [ ] Non-zero exit on a failed gate.

### Test Plan
**Test Types:** L0 (the arithmetic), L2 (against the synthetic ground-truth set).
**Edge Cases:** an empty corpus · a document with no readable page at all · a set whose ground
truth exists but whose document is not ingested.

### Definition of Done
- [ ] Tests pass; the report runs against the synthetic set with no key and no spend.

### Risks and Mitigations
- **Risk (OQ-1):** the real corpus is unavailable, so the real numbers cannot be produced.
  **Mitigation:** the arithmetic ships and is tested on the synthetic set; absent sets skip with a
  named reason and are counted — never silently passed.

### Rollback Plan
N/A — a read-only evaluation command.

---

## 5. Dependency Graph

```
CR1: U004 (exact) ─┐
CR1: U017 (_candidates, fusion) ─┐
CR1: U019 (searchable_ratio)     ├─→ U033 ─┬─→ U034 ─┬─→ U036 ──→ U038
CR1: U029 (document store) ──────┤         │         │
CR1: U031 (typed API, errors) ───┤         └─────────┴─→ U037 ──→ U039
CR1: U025 (SupersededIn, absence(superseded=)) ─┘
CR1: U029 ──→ U035 ──→ U036
```

**The one dependency that is not this CR's to claim:** `found_only_in_superseded` on `/search`
works through `envelope.SupersededIn`, `lookup.absence(..., superseded=)` and
`Candidates.superseded` — all three from CR1 U025's revision work on a parallel branch. `/search`
consumes them and builds none of them (Spec X6). That is also why the seed commit is a branch and
not `main`: the two changes were not separable in the working tree.

---

## 6. Test Strategy

| Level | What it covers here | Files |
|---|---|---|
| **L0** | argument mapping, report arithmetic | `test_cli_search.py`, `test_eval_search.py` *(both unwritten)* |
| **L2** | the surface against a real Qdrant: ranking, paging, content, bounds | `test_search_surface.py` — **56 passing** |
| **L2** | the console's served HTML | `test_console.py` — **38 passing** (18 added here) |
| **L3** | adversarial absence: a scope that matches nothing, a filter that matches nothing, an unreadable scope | inside `test_search_surface.py` |
| **Conformance** | no field named `score`; no second matcher in `serve/` | `test_conformance.py` |
| **E2E** | the tab under a browser | `e2e/tests/search.spec.ts` *(unwritten — U038)* |
| **L5** | the store on the host, by hand | `stack.sh up` → ingest → `ls var/documents` → `down --wipe` |

**Declared coverage gaps** (Spec §7.2), repeated here because a plan that hides them is worse than
one that has them: no e2e, no live-path coverage, no measurement, and no React client.

---

## 7. Invariant & Failure Coverage

| Invariant | Unit | Test |
|---|---|---|
| I-S1 one absence rule | U033 | `test_the_absence_rule_is_the_one_the_rungs_use` |
| I-S2 no score | U033 | `test_rank_is_a_one_based_ordinal_and_no_row_carries_a_score` + conformance |
| I-S3 one exact path | U034 | `test_the_keyword_filters_use_the_one_exact_match_code_path` |
| I-S4 content does not move the ranking | U033 | `test_asking_for_content_does_not_change_the_ranking` |
| I-S5 null vs empty | U033 | `test_an_unrequested_part_is_null_and_a_requested_empty_one_is_not` |
| I-S6 assembled actions work | U033 | `test_the_assembled_fetch_call_actually_works` |
| I-S7 the schema carries every bound | U033 | `test_every_bound_and_vocabulary_is_in_the_published_schema` |
| I-S8 a phrase cannot reach an unreadable page | U034 | `test_a_required_phrase_can_never_reach_a_page_with_no_readable_text` |

| Failure | Unit | State |
|---|---|---|
| FS1, FS2, FS4–FS10 | U033 | ✅ closed |
| FS3, FS11 | U034 | ✅ closed |
| FS12 | U036 | ✅ closed |
| FS13 | U035 | ✅ closed |
| FS14 | U037 | ⬜ **open — the flat surface is unsupported under CR1 §4.4** |
| FS15 | U038 | ⬜ open |

---

## 8. Assumptions and Risks

| # | Assumption / Risk | Handling |
|---|---|---|
| **SA-1** | CR1 U025's `SupersededIn` / `absence(superseded=)` land on `main`. If that work is reset instead of merged, `/search` **does not import** | named in the seed commit and in §5; the branch exists for exactly this reason |
| **SA-2** | "Free" is understood as "no vision call". A cost model reading it as "no provider call" under-counts one embedding per request | Spec D-S10, and the ledger's footnote on every milestone |
| **SA-3** | `test_resume.py` fails 5 tests on this branch, and did so before the seed commit — its fixture deletes the collection its own subprocess ingest created | not this CR's work; recorded so a red suite is not attributed here |
| **SA-4** | The flat surface is unaudited, like the `skim_*` rungs — but it is the surface an *external system* consumes | OQ-S3; a decision belongs in CR1 §7.4 |
| **R-1** | A consumer ignores `text_usable` and cites a wrong code | disclosure only; the surface cannot prevent it (Spec §11) |
| **R-2** | An embedding outage makes `/search` a `503` rather than a degraded search | typed, not silent; OQ-S1 |

---

## 9. Traceability Matrix

| AC | Criterion | Unit(s) | Evidence |
|---|---|---|---|
| AC-S01 | one free call, content included, no vision model | U033 | `test_search_surface.py` |
| AC-S02 | four typed absences agreeing with `skim_pages` | U033 | `test_the_absence_rule_is_the_one_the_rungs_use` |
| AC-S03 | trust on every row, `text_usable ≠ has_text` | U033 | `test_text_usable_is_the_gate_and_is_not_has_text` |
| AC-S04 | ordinals only | U033 | conformance grep + row test |
| AC-S05 | filters through the one exact path, exclusion disclosed | U034 | 11 keyword tests |
| AC-S06 | every bound refused with its code | U033 | the refusal tests |
| AC-S07 | assembled actions, exactly one spends | U033 | `test_every_row_carries_assembled_operations_with_exactly_one_that_bills` |
| AC-S08 | published schema, four named examples | U033 | `test_the_default_request_example_shows_every_control` |
| AC-S09 | the store visible on the host; a wipe takes both | U035 | manual canary |
| AC-S10 | every operation expressible as a `vsir` subcommand | **U037** | ⬜ none |
| AC-S11 | browser proof and a measured disclosure rate | **U038, U039** | ⬜ none |

---

## 10. Implementation Order

| # | Unit | Milestone | State |
|---|---|---|---|
| 1 | U033 | S1 | ✅ shipped 2026-09-11 |
| 2 | U034 | S2 | ✅ shipped 2026-09-11 |
| 3 | U035 | S3 | ✅ shipped 2026-09-11 |
| 4 | U036 | S3 | ✅ shipped 2026-09-11 — **S3 closes here** |
| 5 | **U037** | S4 | ⬜ **next** — the flat surface is unsupported under CR1 §4.4 until this lands |
| 6 | U038 | S5 | ⬜ after U037 (independent of it, but lower value first) |
| 7 | U039 | S5 | ⬜ gated by CR1 OQ-1 — the arithmetic can ship against the synthetic set |

---

## 11. Parallel Bundles

### Layer 1 (no dependencies inside this CR)
- U033, U035

### Layer 2 (depends only on Layer 1)
- U034, U036

### Layer 3
- U037, U038 — independent of each other; U038 needs U036 only

### Layer 4
- U039 — needs U034 and U037

---

**END OF PLAN**
