# CR1 Build Prompt — Vision Segmentation, Index & Retrieval (POC Part B)

> **Loop state:** The `## Loop State` block prepended above this prompt is auto-injected fresh each
> iteration by the loop runner. Read it before anything else — progress %, units in progress
> (resume those first), the next unit to start, and blocked units to re-evaluate.

## 0. Sources of truth

Read before each unit; **the spec wins on every behavioural conflict**:

- **Spec:** [development/cr1/spec/spec.md](development/cr1/spec/spec.md) — authoritative
- **Plan:** [development/cr1/plan/cr1-implementation-plan.md](development/cr1/plan/cr1-implementation-plan.md)
- **Operational:** [AGENTS.md](AGENTS.md) — run/build/test commands
- **Project standards:** [CLAUDE.md](CLAUDE.md)
- **Everything else is progressive disclosure — Spec §20 is the map.** Do not read it up front;
  open the one document the current step needs:
  - building a pipeline step → the matching `impl/pipeline-guide/NN-*.md` (Spec §20 Tier 2 maps
    step → file, and flags which ones describe **superseded** behaviour);
  - **before porting anything → `impl/pipeline-guide/IMPROVEMENTS.md`** and Spec §20.1. That is the
    previous implementation's own defect register. **Never port a known defect** — most are already
    closed by the spec's design, and §20.1 says which;
  - a spec decision looks arbitrary → the matching `plan2/` document (Tier 1).
  Where any of it disagrees with the spec, **the spec wins** (Spec §2.3). Never implement from a
  `plan2/` passage the spec corrected.

**There is a working previous implementation, and you must read it before writing the equivalent
module.** It lives at
`../../../VisionRag/dilmah-engineering-solutioning/poc/vision_segmentation_index_and_retrieval/impl`
— 16 modules, 3,268 lines, 7 documents ingested, **no tests**. Spec §2.4 is the port ledger: every
module says **port as-is / port with changes / do not port**, and Spec §4.1 maps new module → old
module (`←` port, `≈` adapt, `+` net new).

Before writing any module marked `←` or `≈`: **open the `impl` module it descends from**, and keep
its behaviour and its reasoning unless the spec says otherwise. Those files carry hard-won detail —
layout-mode text extraction, the embedding batch-count fallback, `Modifier.IDF` so no corpus
statistic is held locally, `sparse.dedupe` so a generated caption cannot double-count. Re-deriving
them from scratch loses that. Equally: **do not port anything §2.4 marks "do not port"** — the
identifier grammar, the allowlist gate, `token_set()`'s adjacent-token joins, `withheld.jsonl`.

## 1. Task

Implement CR1 unit-by-unit per plan §"Implementation Order". Each unit's Goal / Working Deliverable
/ Demo Command / Requirements / Acceptance Criteria / Test Plan / DoD are binding.

- Pick the highest-priority unit whose dependencies are met and which is not yet complete. **Never
  start a unit from a later milestone while an earlier milestone has an incomplete unit.**
- Before writing any file: (1) confirm the commands in `AGENTS.md`, (2) read the spec sections the
  unit points to, (3) **if Spec §4.1 marks the module `←` or `≈`, read the `impl` module it
  descends from first**, (4) find at least 2 existing files using the pattern you are about to
  write and match their structure — do not invent new patterns. In M0/M1 there may be none yet:
  then follow Spec §4.1 layout exactly.
- Implement fully — no placeholders, no TODOs, no stubs. (The **VLM stub** of Spec §12.2 is a
  required deliverable, not a placeholder.)
- Write the unit's tests in the same change. Tests are part of the deliverable.
- Run the layers in §4; fix every failure, including unrelated pre-existing ones you uncover.
- **Run the unit's Demo Command and paste its output into the progress file.** A unit without a
  green demo is not complete, no matter what the tests say (Spec §0).

You may use up to 6 parallel Sonnet subagents for read-only search and reading, and 1 subagent for
build/test execution.

## 2. Critical rules — read before every unit

**Process**

- After completing each unit, re-read the spec sections and the plan before picking the next.
- Do not mark a unit `[x]` until every test in its Test Plan passes unmodified **and** its Demo
  Command runs green.
- Never skip, xfail, or comment out a failing test — fix the root cause or mark the unit blocked.
- If stuck on one blocker for more than 3 tool-call rounds, mark the unit `[!] Blocked` with a
  clear reason and move on.
- No new dependency outside Spec §4.2 without user confirmation. No feature flags — the unit
  sequencing is the rollout.

**The one rule (Spec §1.2, I2)**

- `ingest/probe.py` is the **only** writer of the `text` payload field. Model output never reaches
  a lexical index except through `vlm_codes`, which is opt-in and permanently `verified: false`.

**Exactness (I3, F1, F3, F16)**

- One exact-match code path: `core/exact.py::exact_filter` using `MatchPhrase` over
  `variants(label)`. `MatchText`/`MatchTextAny` are banned in `serve/`.
- `variants()` may only re-space characters; a variant that changes a character is a bug that the
  property test must catch.
- No fuzzy matching, no edit distance, no similarity library. `present_instead` is a capped prefix
  lookup over observed tokens (Spec §6.8, §7.2.4) and can never be returned as the match.

**Contracts (I5, I6, §7)**

- **Two envelope families, §7.1.** Family A (`skim_*`, `lookup`, `resolve`) uses `SearchResponse`
  where an empty `ok` is impossible; Family B (`fetch`, `read`, `verify`) uses `ToolEnvelope` where
  `status` says whether the **call** ran and the verdicts live in `result`. A `verify` with every
  claim `absent` is `ok` — do not force it through Family A.
- The status enum has six values: `ok`, four distinct absences, `error`. A `not_found` that a
  different move could still answer carries `next.suggest`. A backend failure is a 5xx, never an
  empty result.
- **One vocabulary for checks:** `present | absent | unverifiable`, in both `verify` and `read`'s
  per-code stamps. `verified` stays a boolean and only ever describes which surface a `lookup` hit
  came from (`text` = true, `vlm_codes` = false).
- One `INDEXED` dict creates the payload indexes, gates every filter, and is asserted at boot.
  An unknown scope key is a typed `400`.
- No `score` field in any response model. The four refusals of Spec §7.6 hold.

**Caps and money (F18, F19, §7.3)**

- `read` ≤ 3 pages and renders at the **pinned dpi 220** (a caller cannot change it — it is a
  `read_key` input); `fetch` ≤ 5 pages and ≤ 12 MP, `dpi ∈ {150,220,300,400}`, `dpi > 220` requires
  `region`. Each violation is a **typed 400 naming its bound** — never a clamp, never a truncation.
- The runner's ceiling is `VSIR_READS_PER_QUESTION` (default 3), surfaced as `reads_remaining` and
  exhausted as `429 budget_exhausted`.
- `weak`/`needs_scope` use the server constant `WEAK_ABS = 20`, **never the caller's `cap`** — a
  trust signal that a client parameter can flip is worse than none (§7.1).
- Cost goes to the audit log, not the response body; the caller gets `reads_remaining`.
- Cache keys include the resolved model id and prompt version; `read_key` also includes the
  question. A model id ending `-latest` refuses to start.

**Correctness of the page itself (I1, I4, I7, I8)**

- `point_id = uuid5(page_id)`; re-ingest overwrites, totals never double.
- **Retirement is scoped (§6.7):** delete only prior runs of the **same `(doc_id, revision)`**; set
  the previously current *other* revision to `is_current=False` and **keep** it. A blanket
  delete-by-`run_id` would satisfy F12 by destroying F9's evidence.
- `grounded_rate` is `None` where `has_text` is false, and every aggregate ignores those pages
  (§5.7). A fully scanned document **publishes** and answers `not_searchable` — never quarantined.
- The page offset is proved by both checks of Spec §6.4; on failure, bisect and re-bill — never pad,
  never guess.
- Points are written `is_current=False`; only the publish gates flip it, and every tool injects
  `is_current=True` server-side.
- The answer gate verifies per `(claim, page)` and rejects a draft carrying an unverified code.

**Cloud-native / twelve-factor (Spec §15) — applies to every unit, not just M0**

- **Config from the environment only.** Any deployment-varying value is an env var added to
  `.env.example` (Spec §15 Factor III). Never a literal in code, never a committed config file,
  never a secret in an image, a response or a log line. Changing a model id or prompt version is a
  **release**, not a hot edit — it feeds the cache key and the collection fingerprint (F11).
- **Stateless processes.** No session state, no module-level mutable store, nothing
  correctness-bearing in process memory or on local disk. `scope`/`exclude` are parameters and
  `effective_scope` is echoed back. The `RetrievalState` class plan2 sketched is **struck** (C11) —
  do not build it. Rendered rasters on disk are a cache, never a source of truth.
- **One image, many process types.** `web`, `ingest-worker` and one-off admin (`vsir …`) all run
  from the same image and release. An operational action that cannot be a `vsir` subcommand is not
  supported — no laptop-only scripts, no live collection surgery.
- **Probes.** `GET /health` is liveness and MUST stay green when Qdrant or Gemini is down;
  `GET /ready` is readiness and goes red on a boot-check failure, an unreachable Qdrant or a missing
  pinned index. Both probes are free.
- **Logs are event streams.** Structured JSON to stdout with `release_id`, `run_id`, `session_id`,
  `request_id`, `tool`. Never `logging.FileHandler`, never app-managed rotation or shipping.
- **Disposability.** Handle `SIGTERM`: stop accepting work, drain in flight, checkpoint the ingest
  window — a kill loses at most one window and publishes nothing partial (I7, F17).
- **Dev/prod parity.** The stub VLM is selected by `VSIR_VLM=stub`, **never** by a code branch or a
  test-only import. No `if TESTING:` in the production path. Image bases pinned by digest; no
  `latest` tag anywhere.
- **Replay mode (D10) is the default for every test.** `VSIR_VLM=stub` + `VSIR_FIXTURE=<dir>`
  replays frozen S2 and `read` responses keyed by `extract_key`/`read_key`; a miss is a typed
  `fixture_miss`, never a live call and never a fabricated response.
- **Run/window state lives in the `vsir_runs` Qdrant collection (D9)** — never on local disk, never
  in a queue service. One worker owns one run under an advisory lease; `--resume` refuses a live
  lease unless `--steal` is passed.

**Ported behaviour that must not be lost (Spec §2.4)**

- **Every search result carries an image reference; none carries image bytes** (Spec §7.1, D12).
  Page-level hits get an `ImageRef` (`url`, `thumb_url`, `dpi`, `width`, `height`), aggregate rows
  get a `preview.thumb_url`. `bytes_b64` appears **only** in `fetch` with `inline=true` — a
  `bytes_b64` in a skim row is a P2 violation and an asserted test failure.
- `image` is an optional query parameter on all three `skim_*` rungs (D12), served by the ported
  `embed_query_image`. No instruction prefix when the query is multimodal; an image-only query runs
  the **dense branch alone** and every row's `why` is `["dense"]`; an image can never reach
  `lookup` or `verify` (I2, I3).
- The dense vector is **one fused image+text embedding per page** via `gemini-embedding-2`
  (Spec D4): separate `types.Part`s in a single `types.Content`, raster last. `task_type` is
  **rejected** by the model; a **bare list** in `contents` returns one aggregated embedding, so wrap
  each page in its own `Content` and verify the returned count with a per-item fallback.
- Three fused surfaces, **RRF, ranks only** (Spec D2): `page` 1.0, `lexical` 1.0, `captions` 0.4,
  `rrf_k=60`. No similarity value is ever computed, stored or returned.
- Sparse vectors store **raw term frequencies** with Qdrant `Modifier.IDF` — never a locally held
  corpus statistic. Keep `sparse.dedupe(caption, against=text)`.
- `page_texts()` uses **layout mode**; default text order flattens the safety-list column structure.
- `tok()` mirrors **Qdrant's WORD tokenizer, not `impl`'s `TOKEN_RE`** (Spec §5.6). Porting the old
  regex would make `verify` disagree with the index it checks.
- Resolve every `-latest` model id to a pinned id: `impl` runs `gemini-pro-latest`, which F11 and
  Spec §4.3 refuse at boot.

**Storage and stack**

- Qdrant is the only store, in two collections: `vsir_pages` and `vsir_runs` (§4.2). **No relational
  database, no ORM, no Alembic, no raw SQL** — if you see Postgres in `docker-compose.test.yml`, the
  M0 unit replaces it with Qdrant.
- Rasters are **never persisted** — re-rendered on demand into an in-process LRU cache. Exports are
  **streamed from `GET /runs/{run_id}/export/…`**, never written to the instance's filesystem.
- Python 3.11 (exact minor pinned by the image digest), FastAPI, Pydantic v2 for every
  request/response shape — no untyped dict passthrough.
- Async paths contain no sync I/O (no `requests`, no blocking client calls in async handlers).

**Frontend (M7 only)**

- React + TypeScript + Vite. Define types before implementation; no `any` in new code.
- Server state via React Query; local UI state local. Colors via CSS variables or utilities — no raw
  hex in components. Lists over 50 items (page thumbnails) virtualized.
- Trust badges are load-bearing UI: `verified`, *read from image*, `unverifiable` must be visually
  distinct and covered by the E2E assertion.

## 3. Progress tracking

Maintain [development/cr1/progress/implementation-progress.md](development/cr1/progress/implementation-progress.md).
Keep a rollup at the top: `% complete`, current milestone, next unit, blocked units. Per unit:

- **Unit ID** + one-line description (reference the plan; do not duplicate it)
- **Milestone** and **Spend** class
- **Status:** `[ ] Not Started` / `[~] In Progress` / `[x] Complete` / `[!] Blocked`
- **Date completed**
- **Demo output:** the command run and the key lines of its output
- **Invariants/failure rows closed:** `I4`, `F7`, …
- **Notes:** deviations, follow-ups, blocker reasons

Update on start, completion, or block.

## 4. Testing — required after every unit

| Layer | Command | When |
|---|---|---|
| **L0/L1 + conformance** | `bash scripts/test-unit.sh` | always, first — fast, no Docker |
| **L2/L3 (Qdrant)** | `bash scripts/test-api.sh` | after any `core`, `ingest`, `tool`, `mcp` or `runner` unit |
| **E2E (Playwright)** | `bash scripts/test-e2e.sh` | after any frontend unit, and once L2 is green |
| **L4 (paid)** | `VSIR_ALLOW_PAID=1 bash scripts/test-paid.sh` | **only** for units marked `Spend: paid` |

Rules:

- **L0–L3 and E2E must never call Gemini or any paid API.** Use the stub VLM and the frozen
  fixtures (Spec §12.1). A test that needs a real model call belongs in L4.
- Never call a paid API outside a `Spend: paid` unit, and never without `VSIR_ALLOW_PAID=1`.
- The Spec §12.5 conformance greps run in `test-unit.sh` and must stay green. They scan
  `backend/vsir/**` and `requirements*.txt` only (never markdown, never their own test file): no
  `MatchText` under `serve/`, no fuzzy/similarity library, no field named `score` in a response
  model, no `-latest` model id, no `alembic`/`sqlalchemy`, no writer of the `text` payload key
  outside `ingest/probe.py`, and none of the struck legacy names (`SCHEMA_CARD`, `IdClass`,
  `entity_keys`, `classify(`). The **cloud-native greps** run with them: no `logging.FileHandler`,
  no `latest` image tag, no credential literal, no `if TESTING` branch, no `RetrievalState`-style
  session store.
- The L3 adversarial abstention eval (Spec §12.4) must pass on every commit once M3 lands. A
  failure there is the injury the whole design exists to prevent — treat it as P0.
- All applicable layers must be green before a unit is `[x]`.

## 5. Commit cadence

When a unit's tests pass, its demo runs green and its acceptance criteria are met:

1. Update the progress file (status, date, demo output, invariant/failure rows).
2. `git add -A && git commit -m "<unit IDs>: <what shipped>"`
3. Git push is handled by the loop runner — do not push manually.

**Milestone gate** — when every unit in a milestone is `[x]`:

1. Run that milestone's Demo Command from Spec §0 and record the output in the progress file.
2. Spawn a subagent to verify the milestone's Acceptance list in Spec §13 against the actual
   implementation and produce a ✓/✗ checklist with evidence.
3. Fix any ✗ before moving to the next milestone. Then tag: `git tag cr1-<milestone>` (e.g.
   `cr1-m1`).

**Completion gate** — when all units are `[x]`:

1. Subagent verifies **AC-001…AC-016** (Spec §14) with evidence per criterion, and checks the
   §10 "Closed at" column: every F-row must be closed by the milestone that owns it.
2. Fix any failing AC.
3. Only then: `git tag v0.1.0`.

## 6. Scope guardrails

- Edits confined to the files the unit's Deliverables list, plus its tests.
- Do not implement a later milestone's tool while an earlier one is incomplete.
- Do not weaken an invariant (Spec §9), a failure guard (§10), a cap (§7.3) or a refusal (§7.6) to
  make a unit pass. If one of them blocks the unit, the unit is blocked — say so.
- Do not add OCR, bounding boxes, a sparse vector, RRF fusion, or multi-tenancy: Spec §2.2/§3 rule
  them out of v1.
- **Spec §2.5 is the feature-exclusion ledger — do not re-implement anything on it.** It is the
  companion to §2.4: §2.4 says which *modules* to port, §2.5 says which *features* are gone.
  `impl` has working code for several of them, so porting a module without checking §2.5 is how a
  deleted feature comes back. The five in §2.5 **D** are visible outside this service — if a unit
  would change one of them further, stop and say so rather than deciding alone.
- Do not add anything on the Spec §15.2 banned list — server-held session state, local-disk state,
  app-managed log files, a `latest` tag, a test-only code branch, or a sticky-session requirement.
- Do not claim a failure row your milestone does not own: Spec §10's **"Closed at"** column is
  authoritative, and Spec §9 names the milestone each invariant is asserted from.

## 7. When something is wrong or missing

- **New requirement or contradiction:** update the plan via a subagent (new unit, or amend the
  affected unit's Requirements/ACs) and reflect it in the progress file.
- **Spec looks wrong or contradicts observed behaviour:** check Spec §2.3 (corrections C1–C11), §3
  (closed decisions D1–D11) and §17 (open questions) first — it is probably already answered. If it is
  genuinely unresolved, propose a minimal spec update via a subagent and do not proceed on that
  unit until the spec is updated.
- **Blocked on OQ-1 (pilot PDF) or OQ-2 (Gemini key):** use the documented fallback — the generated
  PDF and the stub VLM — and ship the unit's non-paid part. Record what remains.
- **Blocked unit in the loop state header:** re-read its Notes. If the blocker is resolved, flip
  `[!]` back to `[ ]` and implement it. Only skip if the blocker is still live.
- **Operational knowledge** (new commands, env vars, Docker quirks): add it to
  [AGENTS.md](AGENTS.md), keeping that file purely operational.

## 8. Special notes

- M1 is the whole correctness proof and it costs nothing. Do not let it slip behind ingestion work.
- The measured page counts in Spec §12.3 are normative: if the first real ingest disagrees, record
  it as a blocking finding (Spec §2.3 C10) — do not re-baseline `expected.json` silently.
