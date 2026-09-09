# PLAN-ONLY Implementation Planning Prompt — CR1 (Vision Segmentation, Index & Retrieval)
(Spec-driven, unit-based, deliverable-first)

You are operating in PLAN-ONLY mode.

Do NOT implement any code. This prompt turns the CR1 specification into a unit-based
implementation plan in which **every unit ships something a reviewer can run**.

---

## 📝 Input parameters

### Required
1. **SPEC_FILE**: `development/cr1/spec/spec.md` — **authoritative**
2. **IMPLEMENTATION_TYPE**: `backend+frontend` (backend-dominant; the frontend is Spec §13 M7 only)
3. **OUTPUT_PATH**: `development/cr1/plan/cr1-implementation-plan.md`
4. **SPECIAL NOTES**:
   - This is a **restructured port of a working implementation**, not a greenfield build
     (Spec §2.3 C1). Spec **§2.4** is the port ledger — per `impl` module: port as-is / port with
     changes / do not port — and Spec §4.1 maps new module → old module. Every unit that builds a
     `←` or `≈` module must list **"read `impl/app/<module>.py` first"** as its first step, and its
     Deliverables must say what is ported versus written.
   - Some fixtures and the `lookup` **parity baseline already exist** in `impl/data/` (Spec §12.1,
     §12.3). Plan units to port them before planning any paid work.
   - `plan2/` is **background only**. Where it disagrees with the spec, the spec wins (Spec §2.3).
     Never plan a unit from a `plan2/` passage the spec corrected.
   - Spec §13 milestones **M0–M8 are authoritative and ordered**. Units may not cross a milestone
     boundary and may not reorder milestones.
   - Spec §0 is the deliverable ledger: **a milestone with no runnable demo is not complete.**
   - Spec §15 is the **cloud-native / twelve-factor contract** and it is normative. It is not an M8
     concern: the runtime skeleton (config from env, `/health` + `/ready`, JSON logs to stdout,
     `SIGTERM` handling, one image for every process type, `release_id` stamping) is an **M0
     deliverable**, and every later unit inherits it.

### Optional
- **EXISTING_CODE**: `false` **in this repository** (so Phase 4 foundation units still apply), but a
  working reference implementation exists **outside** it at `impl/` (Spec §2.4). Both facts hold at
  once: the scaffolding is new, the behaviour is largely ported. Every unit that builds a module
  Spec §4.1 marks `←` or `≈` must name its `impl` source in Deliverables.

---

## Core objectives

- Produce a unit-based implementation plan from SPEC_FILE.
- Every unit must be independently buildable, reviewable, testable **and demonstrable**.
- Testing is first-class work, planned per unit against the Spec §12 pyramid.
- Every invariant (Spec §9, I1–I8) and every failure row (Spec §10, F1–F19) must be owned by at
  least one unit and closed by at least one named test.
- Use only Sonnet subagents for extraction and synthesis. The main agent merges and writes.

---

## Token-efficiency rules

- Sonnet subagents extract and synthesise in parallel; outputs are structured lists only.
- Never quote spec text. Use pointers: "Spec §7.3", "Spec §13 M4", "I4", "F16", "AC-007".
- One concern per subagent. The main agent only merges summaries and writes the plan file.

---

## Phase 0: Input discovery (main agent)

1. **Validate inputs** — SPEC_FILE readable; OUTPUT_PATH's directory exists.
2. **Read context**
   - `SPEC_FILE` in full. Note: §0 ledger, §2.3 corrections, §3 decisions, §4.1 layout, §5 data
     contracts, §7 tool surface, §9 invariants, §10 failure catalogue, §12 test strategy,
     §13 milestones, §14 acceptance criteria, §15 cloud-native contract, §17 open questions.
   - `AGENTS.md` — extract the run/build/test commands and pass them to Synthesis Agent S3. If
     `AGENTS.md` is still a template, plan a unit in M0 that fills it, and use the commands the
     spec names (`scripts/test-unit.sh`, `scripts/test-api.sh`, `scripts/test-e2e.sh`,
     `scripts/test-paid.sh`, `vsir doctor`).
   - `CLAUDE.md` — project standards.
   - **Spec §20 — the document map.** Do not read the ~9,600 lines of `impl` prose or the `plan2/`
     set into context. Instead, **every unit must name the Tier 2 document its step maps to** (Spec §20)
     as required reading, so detail is loaded at build time, not planning time.
   - `plan2/*.md` — background only, subject to Spec §2.3.
3. **Check existing plan** — if OUTPUT_PATH exists, this is an update: preserve unit IDs already in
   use and any `🟢 Complete` status recorded in
   `development/cr1/progress/implementation-progress.md`.
4. **Test types for this CR** (Spec §12.2): L0 pure-function, L1 fixture-derivation, L2 index
   contract (Qdrant), L3 adversarial abstention, L4 paid end-to-end, L5 manual canary, plus
   Playwright E2E for M7 and the §12.5 conformance greps.

Do not summarise the spec here. Only identify structure.

---

## Phase 1: Parallel requirement extraction (Sonnet subagents)

Spawn up to **9** Sonnet subagents over disjoint spec regions. Suggested split — one each:

1. §1–§2.5 — scope, corrections C1–C12, **the port ledger and the feature-exclusion ledger**, closed decisions D1–D12
2. §4 — layout, pins, boot self-check, the `vsir` CLI surface (§4.4)
3. §5 — data contracts: ids, S2 schema, record, `INDEXED`, index config, tokenisation, health
4. §6 — ingestion steps 01–12, windowing, cache keys, offset proof, publish gating, exports
5. §7 — envelope, the eight tools, caps, auth/audit, MCP, refusals
6. §8 — the runner: loop, triage, correction loops, answer gate, abstention wording
7. §9–§11 — invariants, failure catalogue, gates, degradation, observability
8. §12–§14 — test pyramid, acceptance table, conformance greps, milestones, ACs
9. §15–§16 — the twelve-factor / cloud-native contract and the NFRs

Each subagent must declare its focus in one line and output structured lists only.

### Extraction output format (strict)

```markdown
### Agent N: [Focus Area]

Focus:
- <one line>

Requirements Extracted:
- [Category] Requirement description (Spec §X.Y)

Invariants / Failure Rows Touched:
- I<n>, F<n> — <one line each>

Dependencies Identified:
- Depends on <other spec sections or external systems>

Technical Constraints:
- <technology, performance, security constraints — from the spec, never invented>

Spec References:
- Spec §<pointers>
```

---

## Phase 2: Distributed synthesis (Sonnet subagents S1–S6)

### Agent S1: Gap analysis and validation

Find missing, ambiguous or contradictory requirements. **Before reporting a gap, check Spec §2.3
and §3** — most apparent contradictions with `plan2/` are already resolved there, and Spec §17
already carries the open questions with default assumptions. Report only true blockers.

```markdown
### Synthesis Agent 1: Gap Analysis

Spec Gaps (Blockers Only):
- Gap: <description> | Impact: <what cannot be implemented> | Location: <spec section>
  Proposed Addition: <minimal text>

Ambiguities (Require Clarification):
- Item / Interpretations / Recommendation / Rationale

Assumptions (Unavoidable):
- Assumption / Reason / Validation / Risk
- (Prefer the default assumption already recorded in Spec §17 over inventing a new one.)
```

### Agent S2: Unit decomposition

Break requirements into atomic units. **Rules specific to this CR:**

- Every unit belongs to **exactly one milestone** (M0–M8) and inherits that milestone's spend
  class: `none` | `paid`. Do not merge units across milestones.
- Every unit must have a **Working Deliverable** — a runnable artefact (CLI subcommand, endpoint,
  MCP tool, script, page) — and a **Demo Command** whose output a reviewer can read.
  A unit whose only output is a document, a schema file or a refactor is invalid: fold it into the
  unit that makes it runnable.
- Units are PR-sized, 1–3 days. Target **18–26 units** total. If a unit is under half a day, merge
  it with its neighbour **inside the same milestone**.
- Order units so that no unit needs an unbuilt paid dependency: everything provable without a model
  call is planned before anything that spends (Spec §13 preamble).
- **No unit may deliver a feature Spec §2.5 excludes.** That ledger lists what `impl` does today
  and this CR deliberately will not; `impl` has working code for most of it, so a porting unit can
  reintroduce one by accident. S1 must flag any requirement that would resurrect a §2.5 row.
- **A unit may only claim the invariants and failure rows its milestone owns.** Spec §10's
  "Closed at" column and Spec §9's "Asserted from" column are authoritative — S6 checks this.
- **Every unit that adds a process, endpoint, tool or worker must satisfy Spec §15.** Concretely:
  new config is an env var in `.env.example` (never a literal, never a committed config file); no
  unit may introduce process-local or on-disk correctness-bearing state (C11 — no `RetrievalState`);
  logs are JSON to stdout; long-running work is checkpointed so `SIGTERM` loses at most one window;
  the stub-vs-real VLM choice is config, never a code branch. A unit that would violate any of
  these is mis-scoped — re-cut it.

```markdown
### Synthesis Agent 2: Unit Decomposition

Unit ID: <U001…>
Name: <short descriptive name>
Milestone: <M0|M1|M2a|M2b|M3|M4|M5|M6|M7|M8>
Type: <core|ingest|tool|mcp|runner|frontend|harness|eval>
Priority: <P0-Critical|P1-High|P2-Medium|P3-Low>
Size Estimate: <Small|Medium|Large>
Spend: <none|paid>
Depends On: [<unit IDs>]
Enables: [<unit IDs>]
Spec References: [Spec §X.Y]
Invariants Enforced: [I<n>…]
Failure Rows Closed: [F<n>…]

Description:
- <one sentence goal>

Core Requirements:
- <bullets, spec pointers only>

Working Deliverable:
- <the runnable artefact>

Demo Command:
- <the exact command, and what a reviewer should see>

Deliverables (files):
- <concrete paths under backend/vsir/…, tests/…, frontend/…>
```

### Agent S3: Test strategy definition

For each unit, map the Spec §12 levels and name the concrete tests.

- Every unit lists its levels from {L0, L1, L2, L3, L4, L5, E2E, conformance}.
- **L0–L3 and E2E must never call Gemini** — plan the stub VLM and the frozen fixtures instead
  (Spec §12.1, §12.2). Only units with `Spend: paid` may plan an L4 test, and it must be gated
  behind `VSIR_ALLOW_PAID=1`.
- Name the fixture each test consumes and which unit produces it.
- Every unit that ports a step must cite (a) the `impl` module from Spec §4.1 and (b) the
  `impl/pipeline-guide/NN-*.md` from Spec §20, plus any **Spec §20.1 register item** it must not
  reproduce. A unit that ports step 07, 10, 11 or 12 must state in its Notes that the matching
  guide documents **superseded** behaviour (the gate, `entity_keys`, `allowlist`, `withheld.jsonl`).
- Plan the Spec §12.5 **cloud-native greps** and the §15.1 probe behaviour as real tests: `/health`
  green while Qdrant is stopped, `/ready` red, and a `SIGTERM` test for any unit that adds
  long-running work.
- Every test below L4 runs in **replay mode** (Spec D10): `VSIR_VLM=stub` + `VSIR_FIXTURE=<dir>`.
  Before M2b the fixture is `synthetic_3window`; no unit may plan a test that *requires* the real
  corpus (OQ-1) or an API key (OQ-2).
- Acceptance criteria must be executable assertions, not prose.

```markdown
### Synthesis Agent 3: Test Strategy

Unit ID: <matches S2>
Test Levels: [L0, L2, conformance]
Suites / Commands: <bash scripts/test-unit.sh -k …>
Test Coverage: Happy Path / Edge Cases / Error Cases (typed 4xx per Spec §7.3) / Degradation (Spec §11.3)
Test Data: Fixtures <path, produced by U0xx> | Stubs <stub VLM, ephemeral Qdrant>
Acceptance Criteria (Testable):
- [ ] <assertion>
```

### Agent S4: Dependency and risk analysis

Dependency graph, critical path, parallel streams, integration points, recommended order.
Flag explicitly: any unit that depends on OQ-1 (pilot PDF) or OQ-2 (Gemini key) from Spec §17, and
state the fallback that keeps it deliverable (stub VLM, generated PDF).

```markdown
### Synthesis Agent 4: Dependency & Risk Analysis

Dependency Graph:
- <Unit ID> → depends on → [<Unit IDs>]

Critical Path Units / Parallel Work Streams / Integration Points (risk + mitigation)
External-Blocker Units:
- <Unit ID> — blocked on <OQ-n> — fallback: <what ships anyway>

Recommended Implementation Order:
1. <Unit ID> — <reason>
```

### Agent S5: Traceability matrix

Map every spec section to ≥1 unit, every unit to test levels, and every **AC-001…AC-016** to the
units and tests that satisfy it. Report unmapped items explicitly.

### Agent S6: Invariant and failure-mode coverage (CR1-specific, mandatory)

Prove the safety net is fully owned before the plan is written.

```markdown
### Synthesis Agent 6: Invariant & Failure Coverage

Invariants:
- I1 → owned by [U0xx] → milestone matches Spec §9 "Asserted from" → enforced by <assertion>
  → tested by <test name / level>
- (repeat I1–I8; every row must have an owner and a test)

Failure Rows:
- F1 → owned by [U0xx] → milestone matches Spec §10 "Closed at" → guard <name> → test <name / level>
- (repeat F1–F19; a row split across milestones, e.g. F8 and F18, needs one owning unit per part)

Conformance Greps (Spec §12.5):
- <grep> → owned by [U0xx]

Uncovered:
- <any I or F with no owner — a blocker, must be resolved before Phase 3>
```

---

## Phase 3: Write the implementation plan (main agent only)

Merge the synthesis outputs into `OUTPUT_PATH`.

```markdown
# Implementation Plan: CR1 — Vision Segmentation, Index & Retrieval

**Source Specification:** development/cr1/spec/spec.md
**Implementation Type:** backend+frontend
**Status:** Draft | In Progress | Complete
**Created:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DD

## Table of Contents
1. Overview
2. Scope and Objectives
3. Milestone Map (M0–M8 → units → demo commands)
4. Implementation Units
5. Dependency Graph
6. Test Strategy
7. Invariant & Failure Coverage
8. Assumptions and Risks
9. Traceability Matrix
10. Implementation Order
11. Parallel Bundles
```

Write `## Milestone Map` **before** the units: one row per milestone — units, the milestone's demo
command from Spec §0, spend class, and the invariants/failure rows it closes.

### Unit template (use exactly)

```markdown
## Unit: <name> (ID: <id>)

**Status:** 🔵 Not Started | 🟡 In Progress | 🟢 Complete
**Milestone:** <M0…M8>
**Priority:** P0-Critical | P1-High | P2-Medium | P3-Low
**Type:** <core|ingest|tool|mcp|runner|frontend|harness|eval>
**Size Estimate:** Small | Medium | Large
**Spend:** none | paid

### Goal
<one sentence>

### Working Deliverable
<the runnable artefact this unit adds>

### Demo Command
```bash
<exact command>
```
<what a reviewer should see>

### Deliverables (files)
- <paths>

### Requirements
- <spec pointers>

### Invariants Enforced
- I<n> — <how>

### Failure Rows Closed
- F<n> — <guard> — <test>

### Dependencies
- **Depends On:** [unit IDs]
- **Enables:** [unit IDs]
- **External:** [libraries, Qdrant, Gemini, fixtures]

### Acceptance Criteria
- [ ] <executable assertion>

### Test Plan
**Levels:** [L0…, E2E, conformance]
**Commands:** <scripts>
**Fixtures/Stubs:** <path, producer unit>
**Edge Cases:** <typed 4xx, degradation rows from Spec §11.3>

### Definition of Done
- [ ] Acceptance criteria met
- [ ] All planned tests implemented and passing, none skipped or xfailed
- [ ] Demo command runs green and its output is recorded in the progress file
- [ ] No new dependency added outside Spec §4.2
- [ ] Conformance greps still pass

### Risks and Mitigations
- **Risk:** … **Mitigation:** …

### Rollback Plan
<!-- Required for type: ingest (index/collection changes) and tool (contract changes).
     Write "N/A" otherwise. -->
- **If this unit must be reverted:** <collection alias swap back, delete points by run_id,
  tool contract version pin — never a partial index state>
```

Then write `## Parallel Bundles` after `## Implementation Order`, grouped by dependency layer, and
**never mixing milestones inside a layer**:

```markdown
## Parallel Bundles

### Layer 1 (M0, no dependencies)
- U001, U002

### Layer 2 (M1, depends only on Layer 1)
- U003, U004
```

The build loop uses this to decide what can run concurrently.

---

## Phase 4: Foundation units (applies — EXISTING_CODE = false)

The plan must include M0 foundation units for: the `backend/vsir/` skeleton of Spec §4.1; pinned
`requirements.txt` per Spec §4.2; `docker-compose.test.yml` **rewritten from Postgres to Qdrant**;
`scripts/test-paid.sh` added and the existing scripts extended; `AGENTS.md` filled with real
commands; `vsir doctor` (Spec §4.3); the Spec §12.5 conformance greps as a runnable test; and the
**twelve-factor runtime skeleton of Spec §15** — `Dockerfile` (non-root, digest-pinned base,
read-only rootfs), `.env.example` covering every variable of §15 Factor III, `GET /health` +
`GET /ready` per §15.1, structured JSON logging to stdout, a `SIGTERM` handler, and `release_id`
stamping.

---

## Phase 5: Spec change policy

Modify SPEC_FILE **only** if Synthesis Agent S1 identifies a true blocker that Spec §2.3, §3 and
§17 do not already resolve. Changes must be minimal, justified in the plan's Assumptions section,
and must not weaken an invariant (§9), a failure guard (§10), a cap (§7.3) or a refusal (§7.6).
Never relax the spec to make a unit easier.

---

## Phase 6: Quality validation (main agent)

- [ ] Every spec section maps to at least one unit
- [ ] Every unit has a Working Deliverable **and** a Demo Command
- [ ] Every unit belongs to exactly one milestone; no unit crosses a milestone boundary
- [ ] Every I1–I8 and F1–F19 has an owning unit and a named test (S6 reports no Uncovered rows)
- [ ] Every AC-001…AC-016 maps to units and tests
- [ ] Unit IDs unique and sequential; dependencies acyclic
- [ ] Units are atomic and PR-sized (1–3 days); total 18–26
- [ ] No unit plans a Gemini call at L0–L3 or E2E
- [ ] No unit introduces a banned construct (Spec §12.5, §15.2) or a dependency outside Spec §4.2
- [ ] Every unit adding a process/endpoint/worker complies with Spec §15; AC-015 and AC-016 are
      mapped to units and tests
- [ ] No unit claims an invariant or failure row outside its milestone's ownership (§9, §10)

---

## Output constraints

**Do NOT:** implement code; paste spec text; write prose paragraphs where a list works; make
undocumented assumptions; plan a relational database, ORM or migration tool; plan fuzzy matching,
similarity scores in responses, `MatchText` in `serve/`, or a `-latest` model id; plan server-held
session state, local-disk state, app-managed log files or a `latest` image tag (Spec §15.2); plan
units that produce only documents.

**Do:** use section pointers; keep units atomic; make every unit demonstrable; plan tests as
first-class work; keep the zero-spend proof (M1) ahead of everything paid.

---

**END OF PROMPT**
