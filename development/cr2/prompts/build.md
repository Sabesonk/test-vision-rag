# CR2 Build Prompt — `POST /search`, the flat retrieval surface

> **Loop state:** The `## Loop State` block prepended above this prompt is auto-injected fresh each
> iteration by the loop runner. Read it before anything else — units in progress (resume those
> first), the next unit to start, blocked units to re-evaluate.
>
> Run with: `./loop_cr.sh development/cr2/prompts/build.md`

## 0. Sources of truth

Read before each unit; **the spec wins on every behavioural conflict**:

- **Spec:** [development/cr2/spec/spec.md](development/cr2/spec/spec.md) — authoritative for
  `POST /search`, the keyword filters and the document store's location
- **Plan:** [development/cr2/plan/cr2-implementation-plan.md](development/cr2/plan/cr2-implementation-plan.md)
- **Parent spec:** [development/cr1/spec/spec.md](development/cr1/spec/spec.md) — authoritative for
  **everything else**: the eight tools, ingestion, the runner, I1–I8, F1–F19, §15's twelve factors.
  Where CR2 is silent, CR1 governs
- **Operational:** [AGENTS.md](AGENTS.md) — run/build/test commands
- **Project standards:** [CLAUDE.md](CLAUDE.md)

**Read the implementation before extending it.** `backend/vsir/serve/retrieval.py` is 1,157 lines
and its module docstring carries the reasoning for every decision in it — why there is no score,
why `include` defaults to everything, why the keyword filters go to the branch filter and not the
scope. CR2's units are extensions of that module or consumers of it; re-deriving its reasoning from
the spec alone loses the parts the spec compressed.

## 1. Task

Three units remain: **U037** (`vsir search` on the CLI), **U038** (the Playwright spec), **U039**
(`vsir eval search`). U033–U036 shipped on 2026-09-11 — **do not rebuild them**; if one needs a
correction, record it as a defect in the progress file's "Defects found" table and fix it as a
named follow-up.

- Pick the highest-priority unit whose dependencies are met and which is not yet complete.
  **U037 first** — until it lands, CR1 §4.4 is violated and the flat surface is unsupported.
- Before writing any file: (1) confirm the commands in `AGENTS.md`, (2) read the spec sections the
  unit points to, (3) **read `serve/retrieval.py` and the existing `vsir` subcommand nearest to
  what you are adding**, (4) find at least 2 existing files using the pattern you are about to
  write and match their structure — do not invent new patterns.
- Implement fully — no placeholders, no TODOs, no stubs.
- Write the unit's tests in the same change. Tests are part of the deliverable.
- **Run the unit's demo command and paste its output into the progress file.** A unit without a
  green demo is not complete (Spec §0).

## 2. Critical rules — read before every unit

**The one rule for this surface (Spec §1.2)**

- **Data out, never an answer.** `/search` and anything built on it calls no vision model, composes
  no prose and makes no judgement about whether the rows answer the question. `POST /ask` is the
  only surface in this service that may answer. A CLI that summarised its rows would break this.

**No magnitude, ever (D-S2, CR1 §7.6)**

- `rank`, `surface_ranks`, `best_rank` — ordinals only. No score in a model, a CLI column, a report
  or the DOM. `test_conformance.py::test_no_field_named_score_in_any_model` fails the build on a
  field named `score`, and a rendered magnitude in U038's browser assertions is a failure too.
- Never introduce a threshold, a cutoff or a "minimum relevance". A threshold turns *"ranked
  ninth"* into *"no results"*, and a fabricated absence is the failure this system exists to prevent.

**Typed absence is the product (Spec §4.2, FS1)**

- Five values: `ok`, `not_found`, `not_searchable`, `out_of_scope`, `found_only_in_superseded`.
  Every consumer you build — CLI, browser assertion, report — must **print or assert the status and
  the action it implies**, never render four different facts as one empty table.
- The status comes from `lookup.absence()`. Do not compute one anywhere else (I-S1).

**One implementation per operation (register E1, CR1 U027)**

- `vsir search` builds a `SearchRequest` and calls the same code path the route calls. No second
  assembly of the filter, no second validator, no second absence rule. A parity test asserts the
  two surfaces agree — if it cannot, the subcommand is doing too much.

**Exactness (CR1 I3, F1, and I-S3)**

- One exact-match code path: `core/exact.py::exact_filter` over `variants(label)`. `MatchText` is
  banned in `serve/`. A keyword filter never builds its own matcher.
- No fuzzy matching, no edit distance, no similarity library anywhere.

**Bounds are refused, never clamped (D-S11)**

- Every bound in Spec §4.1 keeps its own code. At the CLI a violation exits **non-zero with the
  code on stdout** — never a traceback, never a silently clamped value.

**Trust survives every hop (FS2)**

- Any surface that shows `content.text` shows `text_usable` and `text_trust` beside it. A CLI
  column, a browser row, a report line — the flag travels with the text or the text does not travel.
- `codes` are claims; `codes_in_text` is the backed subset, and the comparison is
  **case-insensitive** (the two are stored in different forms).

**Cloud-native (CR1 §15) — unchanged and still binding**

- Config from the environment only; no literal in code, no secret in a log line.
- Stateless: `offset` pages a deterministic ordering, it does not resume a session. No cursor
  backed by server state.
- One image, many process types: every operation is expressible as a `vsir` subcommand — which is
  precisely what U037 is for.

## 3. Progress tracking

Maintain [development/cr2/progress/implementation-progress.md](development/cr2/progress/implementation-progress.md).
Keep the rollup at the top current. Per unit: ID + one line, milestone, spend, status
(`[ ]`/`[~]`/`[x]`/`[!]`), date, **demo output**, invariants/failure rows closed, notes.

Update on start, completion or block. **A defect found while building goes in the "Defects found"
table with its unit and why it misleads** — P-S1 and P-S2 are the shape to follow.

## 4. Testing — required after every unit

| Layer | Command | When |
|---|---|---|
| **L0/L1 + conformance** | `bash scripts/test-unit.sh` | always, first — fast, no Docker |
| **L2/L3 (Qdrant)** | `bash scripts/test-api.sh` | after any unit touching `serve/`, `core/` or the CLI |
| **E2E (Playwright)** | `bash scripts/test-e2e.sh` | U038, and once L2 is green |

- **Nothing in CR2 is paid.** No unit here may call a vision model. A text query still embeds
  (D-S10) — that is the stub's job in every test.
- Replay mode is the default: `VSIR_VLM=stub` + a fixture. A miss is a typed `fixture_miss`.
- `test_resume.py`'s 5 failures pre-date this CR and are CR1 U025's — do not "fix" them inside a
  CR2 unit, and do not count them against a CR2 unit's suite.
- All applicable layers green before a unit is `[x]`.

## 5. Commit cadence

1. Update the progress file (status, date, demo output, rows closed).
2. `git add -A && git commit -m "<unit ID>: <what shipped>"`
3. The loop runner pushes — do not push manually.

**Milestone gate** — when every unit in S4 or S5 is `[x]`: run that milestone's demo command from
Spec §0, record the output, verify the milestone's acceptance list in Spec §8 against the actual
implementation with a ✓/✗ checklist, fix any ✗, then `git tag cr2-s4` / `cr2-s5`.

**Completion gate** — when all seven units are `[x]`: verify **AC-S01…AC-S11** (Spec §9) with
evidence per criterion and check Spec §6's failure table row by row. Only then tag the release.

## 6. Scope guardrails

- Edits confined to the files the unit's Deliverables list, plus its tests.
- **Do not make `/search` a ninth tool** (D-S1): no `ToolSpec` row, no MCP exposure, no dispatch
  through `dispatch`. The eight stay eight and `test_mcp_resources.py` asserts it.
- Do not widen `AUDITED_TOOLS` — that is a CR1 §7.4 decision (X4, OQ-S3), not a CR2 unit's.
- Do not change a published field's name, type or semantics: the contract is in `/openapi.json` and
  a consuming system generates its client from it. An addition is additive; a rename is a break.
- Do not add a dependency outside CR1 §4.2.
- Do not weaken a bound, a refusal or a disclosure count to make a unit pass. If one blocks the
  unit, the unit is blocked — say so.
- Do not build the React console's search view: Spec §2.2 rules it out of this CR.

## 7. When something is wrong or missing

- **Spec looks wrong:** check Spec §3 (D-S1…D-S11), §2.3 (X1–X6) and §12 (OQ-S1…OQ-S4) first — it
  is probably already answered. If genuinely unresolved, propose a minimal spec update and do not
  proceed on that unit until it lands.
- **Blocked on CR1 OQ-1** (the pilot PDF is absent): ship the arithmetic against the synthetic
  ground-truth set, skip absent sets **with a named reason**, count them in the summary, and record
  what remains. Never let a zero denominator print as a passing score.
- **Operational knowledge** (new commands, env vars, Docker quirks): add it to
  [AGENTS.md](AGENTS.md), keeping that file purely operational.
