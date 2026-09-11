# PLAN-ONLY Prompt — CR2 (`POST /search`, the flat retrieval surface)
(Spec-driven, unit-based, deliverable-first)

You are operating in PLAN-ONLY mode.

Do NOT implement any code. This prompt turns the CR2 specification into a unit-based
implementation plan in which **every unit ships something a reviewer can run**.

---

## 📝 Input parameters

### Required
1. **SPEC_FILE**: `development/cr2/spec/spec.md` — **authoritative for `/search`**
2. **PARENT_SPEC**: `development/cr1/spec/spec.md` — authoritative for everything CR2 is silent on
3. **IMPLEMENTATION_TYPE**: `backend` (one server-rendered console tab; no React work)
4. **OUTPUT_PATH**: `development/cr2/plan/cr2-implementation-plan.md`
5. **SPECIAL NOTES**:
   - **This CR is retrospective in part.** Spec §2.4 marks every normative statement *as-built* or
     *required*. A unit for an *as-built* statement is a **record** — its acceptance criteria are
     checked against the shipped code, its test evidence is real and verified, and its disclosed
     limitations are the real ones. Never plan work that already exists.
   - **Unit ids continue CR1's sequence from U033.** CR1 plan §4b set the precedent and the reason:
     unit ids are referenced across the progress record, the commit history and `fixes/`, so a
     restart would make `U005` mean two things. No existing unit id moves.
   - Spec §0 is the deliverable ledger: **a milestone with no runnable demo is not complete.**
   - Spec §2.3 (X1–X6) is where this CR touches CR1. **X5 is a defect, not an exception** — the
     flat surface has no `vsir` subcommand and CR1 §4.4 says the CLI is the only supported
     operational surface. Any plan that does not carry a unit for it is wrong.
   - Spec §7.2 lists what the shipped tests do **not** cover. Those gaps are the S5 units; do not
     let a green suite talk the plan out of them.

### Optional
- **EXISTING_CODE**: `true` — `backend/vsir/serve/retrieval.py` (1,157 lines) and 56 passing tests
  exist. Every unit that extends or consumes that module must name it as required reading.

---

## Core objectives

- Produce a unit-based implementation plan from SPEC_FILE.
- Every unit independently buildable, reviewable, testable **and demonstrable**.
- Testing is first-class work, planned per unit.
- Every invariant (Spec §5, I-S1…I-S8) and every failure row (Spec §6, FS1…FS15) owned by at least
  one unit and closed by at least one **named** test.
- A shipped unit's evidence must be **verified, not quoted** — run the suite and record what it says.

---

## Token-efficiency rules

- Never quote spec text. Use pointers: "Spec §4.2", "D-S5", "FS11", "AC-S07", "CR1 §7.1".
- One concern per subagent; structured lists only. The main agent merges and writes.

---

## Phase 0: Input discovery

1. **Validate inputs** — SPEC_FILE readable; OUTPUT_PATH's directory exists.
2. **Read**
   - `SPEC_FILE` in full. Note §0 (ledger), §2.3 (X1–X6), §3 (D-S1…D-S11), §4 (the contract),
     §5 (invariants), §6 (failure catalogue), §7 (what is and is not tested), §8 (milestones),
     §9 (acceptance), §12 (open questions).
   - `backend/vsir/serve/retrieval.py` — the module docstring carries the reasoning the spec
     compressed. Read it before planning any unit that touches the surface.
   - `AGENTS.md` for the run/build/test commands; `CLAUDE.md` for standards.
   - **CR1's spec only where CR2 points at it.** Do not read it whole.
3. **Check existing plan** — if OUTPUT_PATH exists this is an update: preserve unit ids already in
   use and any `🟢 Complete` status recorded in `development/cr2/progress/implementation-progress.md`.
4. **Test types for this CR:** L0 pure-function, L2 index contract (Qdrant), L3 adversarial
   absence, L5 manual canary (the compose wiring), Playwright E2E, and the §12.5 conformance greps.
   **There is no L4 here — no unit in CR2 is paid.**

---

## Phase 1: Requirement extraction

Spawn up to **4** Sonnet subagents over disjoint spec regions — one each:

1. §3–§4 — the closed decisions and the request/response contract, every bound and its code
2. §5–§6 — invariants and the failure catalogue, with the test that closes each
3. §2.3, §7 — where CR2 touches CR1, and the declared coverage gaps
4. §8–§12 — milestones, acceptance criteria, NFRs, risks and open questions

Each declares its focus in one line and outputs structured lists only.

---

## Phase 2: Synthesis

- **S1 Gap analysis** — every *required* statement with no unit, every *as-built* statement with no
  named test, every failure row with no owner.
- **S2 Unit decomposition** — atomic, PR-sized, one milestone each; shipped units recorded rather
  than planned.
- **S3 Test strategy** — per unit, against the levels above; **name the test file and the test**.
- **S4 Dependencies and risks** — including the ones this CR does not own (CR1 U025's
  `SupersededIn`, CR1 OQ-1).
- **S5 Traceability** — AC-S01…AC-S11 → units → evidence, with ⬜ where there is none.

---

## Phase 3: Write the plan

Merge into OUTPUT_PATH using CR1's plan structure (Overview, Scope, Milestone Map, Units,
Dependency Graph, Test Strategy, Invariant & Failure Coverage, Assumptions and Risks, Traceability,
Implementation Order, Parallel Bundles) and the unit template in
[development/templates/implementation-planning.md](../../templates/implementation-planning.md).

For each unit state: **Status · Milestone · Priority · Type · Size · Spend**, Goal, Working
Deliverable, Deliverables (files, marked *written* / *extended*), Requirements (with pointers),
Dependencies, Acceptance Criteria, Test Plan, Definition of Done, Risks and Mitigations, Rollback
Plan.

---

## Phase 4: Quality validation

- [ ] Every spec section maps to at least one unit
- [ ] Every unit has acceptance criteria and named tests
- [ ] Unit ids unique, continuing from U033, and no CR1 id reused
- [ ] Dependencies valid, no cycles
- [ ] Every *as-built* claim carries verified evidence, not a quoted number
- [ ] Every declared coverage gap in Spec §7.2 has a unit

---

## Output constraints

**Do NOT:** implement code, paste spec text, restate CR1, invent a ninth tool, plan a score or a
threshold, or plan work that already ships.
**Do:** use section pointers, keep units atomic, plan tests as first-class work, and say plainly
where there is no evidence.

---

**END OF PROMPT**
