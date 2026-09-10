# CR1 Specification — Vision Segmentation, Index & Retrieval (POC Part B)

**Status:** Ready for planning
**Created:** 2026-09-09
**Implementation Type:** backend+frontend (backend-dominant; one operator console at M7)
**Source plan:** [plan2/](../../../plan2/) — `PLAN.md`, `GENERIC-PIPELINE-PLAN.md`, `AGENTIC-RETRIEVAL.md`, `FAILPROOF-IMPLEMENTATION-PLAN.md`, `MCP_ARCHITECTURE.md`, `UI_CONCEPT.md`
**Parent POC doc:** [vision_segmentation_index_and_retrieval.md](../../../vision_segmentation_index_and_retrieval.md)

> **This spec is authoritative.** Where it disagrees with `plan2/`, this spec wins — §2.3 lists
> every deliberate correction. Where it is silent, `plan2/` is background, not requirement.

---

## 0. Deliverable ledger

Every milestone ends in something a reviewer can run. **A milestone with no runnable demo is not
complete**, regardless of test status.

| M | Working deliverable | Demo command (must succeed in front of a reviewer) | Spend |
|---|---|---|---|
| **M0** | Repo skeleton, pinned config, test harness (Qdrant), boot self-check | `vsir doctor && bash scripts/test-unit.sh` | none |
| **M1** | Exact-match surface proved on synthetic text | `vsir demo exact --synthetic` | none |
| **M2a** | Full ingest of a **generated** PDF with a stubbed VLM | `vsir ingest data/source/synthetic_3window.pdf --vlm stub` | none |
| **M2b** | Full ingest of the pilot PDF; fixture frozen | `VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf` | S2 + embed, once |
| **M3** | `lookup` + `verify` over HTTP and MCP, typed absence | `vsir serve & vsir lookup "SF 1.1A" && vsir eval acceptance` | none |
| **M4** | `skim_pages` + `fetch` + `resolve`, caps, auth, audit | `vsir demo narrow` | none |
| **M5** | Ladder rungs + `read` (the paid step) with stamped codes | `VSIR_ALLOW_PAID=1 vsir read --pages … --question …` | read |
| **M6** | The runner: loop, tri-state triage, answer gate, abstention | `VSIR_ALLOW_PAID=1 vsir ask "carton discharge won't restart after an E-stop reset"` | read |
| **M7** | Operator console (viewer + agent console + trust badges) | `bash scripts/test-e2e.sh` then browse `http://localhost:5174` | none (fixture-backed) |
| **M8** | Revisions, resumable ingest, corpus scale-out + evaluation report | `vsir ingest --resume <run_id>` and `vsir eval corpus` | ingest |

**M0, M1, M2a, M3, M4 and M7 cost nothing** — M2b, M5, M6 and M8 are the only paid steps, and each
is gated behind `VSIR_ALLOW_PAID=1`. **M1 is the whole correctness proof and it spends zero.**

Every milestone in §13 also names what it **depends on**, so the sequence is a graph, not a wish.

---

## 1. Overview

### 1.1 The guarantee

> **No failure may present itself as a correct answer.**

In this corpus 8,414 code pairs differ by one character. Sending a technician to rewire `K78`
when the page says `K73` is the only unrecoverable failure. This CR does not promise perfect
recall or perfect transcription; it promises that **every other failure is visible, typed and
attributable** — an abstention, a flag, or a 4xx.

### 1.2 The one rule

> **Lexical surfaces index extracted text. The dense surface may include model output.**

`text` is written by the PyMuPDF probe and by nothing else. A hallucinated code therefore
*cannot* be in the exact surface — there is nothing to verify (I2, §9). Model-emitted codes reach
retrieval only through the dense vector and through the opt-in, permanently-labelled `vlm_codes`
index.

### 1.3 What this CR builds

A **document service**: it ingests PDFs page-by-page, indexes each page once, and exposes eight
tools plus a reference runner that demonstrates the retrieval loop end to end. It composes no
answer that its own gates have not verified (§8.4).

**It is not:** the correlation graph (POC Part A), an ERP integration, a multi-tenant service, or
a general chat product.

---

## 2. Scope

### 2.1 In scope

- Ingestion: manifest → probe → render → windowed VLM extraction → derivation → stitching →
  embedding → indexing → publish gates → exports (§6).
- One Qdrant collection, one point per page, two full-text indexes (§5.4–5.5).
- Eight tools over HTTP + MCP: `skim_documents`, `skim_sections`, `skim_pages`, `lookup`,
  `resolve`, `fetch`, `read`, `verify` (§7).
- The reference runner: the loop, tri-state triage, the six correction loops, the answer gate (§8).
- Invariants I1–I8 as assertions, failure catalogue F1–F19 as tests (§9, §10).
- Test pyramid L0–L5 with a frozen fixture (§12).
- One operator console (§13, M7).
- Evaluation on the corpus's own ground-truth sets (§12.6, M8).

### 2.2 Out of scope

| Out | Why |
|---|---|
| The retrieval **agent** as a product surface | POC Part A owns it; the runner here is the reference client and demo entry point |
| Correlation graph, dictionary, `resolve`/`describe`/`neighbors` over entities | Part A; this CR only *exports* to it (§6.8) |
| ERP, spare-parts capture images | deferred with their master-doc sections |
| Multi-tenancy, `tenant_id` filters | single-tenant by design; the auth boundary is the whole service (R6) |
| Sparse/lexical **vector** + RRF fusion | D2 — deferred behind a measurement |
| Bounding boxes, `around="K158"` | D6 — `region` coordinates only in v1 |
| OCR of scanned pages | disclosed via `no_text` / `not_searchable`, never silently patched |

### 2.3 Corrections to plan2 (normative)

| # | plan2 says | This spec says | Why |
|---|---|---|---|
| **C1** | Refactor `impl/` in place: delete `SCHEMA_CARD`, `classify()`, `entity_keys`, `sparse.py`; "−114 lines" (`PLAN` §2.9; `GENERIC` §8, §11) | **A restructured port, not an in-place refactor and not a greenfield build.** The working implementation is `VisionRag/…/poc/vision_segmentation_index_and_retrieval/impl` — 3,268 lines across 16 modules, 7 documents ingested, **no tests**. plan2 lives inside it (`impl/plan2/`), so it is that code's own refactor plan. CR1 builds the corrected structure **in this repository**, porting what is proven (§2.4), never porting the deleted concepts, and adding the test pyramid `impl` never had. The line-count arithmetic in `PLAN` §2.9 is therefore descriptive of `impl`, not a target here | a port lets the invariants be enforced from the first commit instead of retrofitted onto code that predates them; the deleted concepts are kept out by §12.5 greps rather than by a deletion PR |
| **C2** | `lookup()` implemented with `qm.MatchText` (`PLAN` §2.6, `GENERIC` §6) | **`MatchPhrase` over `variants(label)` only.** `MatchText` is any-order and is banned in `serve/` by a conformance grep (I3, F1) | the two plan documents contradict each other, and any-order matching is failure F1. Note `impl` has **no text index at all** — `MatchText`, `MatchPhrase`, `TextIndexParams` and `phrase_matching` appear nowhere in it; exact lookup is `entity_keys` + `MatchValue` (`impl/app/segstore.py`). The phrase index is genuinely new work, so there is no legacy call site to migrate |
| **C3** | "Seven invariants" I1–I7 (`PLAN` §5.1) | **Eight invariants I1–I8** as in `FAILPROOF` §1 — `PLAN` dropped publish-gating (I7) while still citing it in F17 | a referenced invariant must exist |
| **C4** | 17 failure rows, F17 = unbounded spend (`PLAN` §5.2) | **19 rows F1–F19** as in `FAILPROOF` §2 (F17 half-finished run, F18 spend, F19 `read` cache ignoring the question) | `PLAN` lost two rows in the merge |
| **C5** | `fetch(..., dpi=220)` default (`PLAN` §3.7) vs `dpi=150` default (`PLAN` §3.9) | **default `dpi=150`**; `dpi ∈ {150, 220, 300, 400}`; `dpi > 220` requires `region` | cheapest default, explicit escalation |
| **C6** | Five absence states (`PLAN` §5.1 I5) vs six (`FAILPROOF` §1 I5) | **a six-value enum** — `ok`, four distinct absences (`not_found`, `not_searchable`, `out_of_scope`, `found_only_in_superseded`) and `error` — declared from M1 so no later breaking change (§7.1) | a guard that hides data owns the absence it creates |
| **C7** | `present_instead` = "prefix filter on observed tokens" with no home | An **observed-token inventory** written at publish time (§6.8); prefix lookup only, capped at 5, advisory, and structurally unable to affect `lookup`/`verify` (§7.2.4) | otherwise F16's guard has nowhere to live |
| **C8** | Part A contract promises per-segment `verified_identifiers[]` from the allowlist gate (POC doc §5); plan2 deletes the gate | The export keeps the same semantics under a new name: per-page **`codes_in_text`** = the page's codes that are **printed on it as a phrase** (§5.6), a byproduct of `grounded_rate`. Records are **pages**, not segments; `page_id` replaces `segment_id` (D1) | Part A must not lose its attachment evidence because an internal gate moved |
| **C9** | "Prove `lookup` on the real corpus before deleting anything" — assumes the corpus is at hand | M2 is split: **M2a** proves ingest on a generated PDF with a stub VLM (no corpus, no spend), **M2b** ingests the pilot PDF | the corpus and API key are open questions (§17) and must not block a working deliverable |
| **C11** | A server-side `RetrievalState` holding `scope` and `exclude_list` across turns (`MCP_ARCHITECTURE` §4.4; `PLAN` §4.4) | **Struck. The service is stateless** (§7.5, §15 Factor VI): `scope` and `exclude` are parameters and `effective_scope` is echoed back | `AGENTIC-RETRIEVAL` §9 and F8 already require this — server-held scope is both a correctness failure (searching a subset while believing you searched the chapter) and a twelve-factor violation that blocks horizontal scaling |
| **C12** | *(reversed on evidence — the earlier reading of this row was wrong.)* plan2's record feeds the **page raster into the dense vector** — `dense = image + title + summary + text + codes` (`GENERIC` §5; `PLAN` §2.4) | **Confirmed and kept: the dense vector is a fused image+text embedding.** `impl/app/embedder.py::embed_page_interleaved` already does exactly this — *"One page → ONE vector, image and text interleaved in a single Content… here we WANT the raster and the page's own text fused into one vector"* — using `gemini-embedding-2`, which `impl/config.yaml` documents as *"multimodal: text + image in one space"*. See D4 for the contract | the raster is the reasoning substrate (§1.3), and for a born-digital PDF the extractor read the native text layer at a fidelity the raster never captured — interleaving puts **both** in the dense channel, which is why `impl` chose it. The one honest gap: `effort_and_llm_cost_estimation.md` §A3 budgets image embeddings only for the 764 deferred plate images, so per-page image embedding is **unbudgeted** — at $0.00012/image it is ≈ $0.66 per full 5,505-page run, worth a line in the cost model rather than a design change |
| **C10** | Acceptance-table page counts (`FAILPROOF` §3) stated as expected values | Normative for `TC1E-SF`. If the first real ingest disagrees, that is a **blocking finding** (offset/tokenisation) until proven a corpus difference; changing `expected.json` requires a recorded rationale in the run report | otherwise the safety net silently re-baselines itself |

### 2.4 Inheritance from the previous implementation

**Source:** `VisionRag/dilmah-engineering-solutioning/poc/vision_segmentation_index_and_retrieval/impl`
— 16 modules, 3,268 lines, 7 documents ingested, a working FastAPI surface and UI, **and no tests
at all**. It is the reason plan2 exists, and it is the only evidence of what actually works on this
corpus. **Nothing in the table below is re-derived from scratch: it is ported, adapted, or
deliberately dropped.**

| `impl` module | Lines | Verdict | Notes |
|---|---:|---|---|
| `app/render.py` | 94 | **port as-is** | raster rendering; `dpi_index=150` (embedded) / `dpi_answer=220` (read) is the split the new spec adopts (§4.2) |
| `app/windows.py` | 99 | **port as-is** | windowing + `extract_key`; plan2 §2.1 marks step 04 unchanged. Add the bisection ladder (F13, §6.2), which `impl` lacks |
| `app/stitch.py` | 126 | **port, retarget** | same algorithm, now grouping **sections** instead of units (plan2 §2.1 step 07); add `series_id` (F8) |
| `app/embedder.py` | 241 | **port as-is — load-bearing** | `gemini-embedding-2`, interleaved image+text (D4). Keep the retry/backoff, `prepare_image` (`max_edge_px=1568`), the batch-count verification and the per-item fallback |
| `app/sparse.py` | 42 | **port as-is** | raw term frequencies + Qdrant `Modifier.IDF`; keep `dedupe()` (D2) |
| `app/segstore.py` | 219 | **port with changes** | Qdrant collection + upsert. **Add** the two text indexes with `phrase_matching` (§5.5) and the `is_current` publish flag (I7); **remove** the `entity_keys` payload index and its `MatchValue` lookup |
| `app/retrieve.py` | 430 | **port selectively** | keep `rrf()` (ranks-only), `decompose()` (splits identifiers out of the query before embedding — this is what §8.2's *auto-promote exact hits* rests on), `resolve()` and its `interpolated` disclosure. **Rewrite** `lookup()` as a phrase filter (C2); **replace** `search()` with the three `skim_*` rungs; **replace** `expand()` with `next.expand` + a re-scoped skim; **supersede** the `/compare` endpoint with `fetch` (plan2 §3.3) |
| `app/textlayer.py` | 139 | **port partially** | keep `probe()`, `page_texts()` (layout mode is not cosmetic — default order flattens the safety-list column structure), `content_hash()`, `Probe.s2_input_mode`. **Do not port** `gate()`, `backs()`, `identifiers_from_text()` (I2 makes them unnecessary) or `token_set()`'s adjacent-token joins (superseded by `phrase_matching` + `variants()`) |
| `app/pagemodel.py` | 306 | **do not port the identifier machinery** | `SCHEMA_CARD`, `IdClass`, `classify()`, `normalise()`, `Identifier`, `backed_keys()`, `entity_keys_for()` all go (§12.5 greps keep them out). Keep only the record/page-id shape, restated in §5.1–5.3 |
| `app/segment.py` | 341 | **rewrite** | the S2 schema changes (§5.2): `units[]` → `sections[]`, `identifiers[]` → `codes[]`, plus `summaries`/`topics`. Drop `_is_safety()`'s keyword list and the identifier merge |
| `app/pipeline.py` | 334 | **rewrite** | same step order, but the `allowlist` / `class_totality` gates and the `withheld.jsonl` export are replaced by `grounded_rate` (§5.7) and the gates of §11.1 |
| `app/segjobs.py` | 110 | **port with changes** | job tracking moves into the `vsir_runs` control collection with a lease (D9) instead of process-local state |
| `app/config.py` | 96 | **port, restructure** | keep the shape; **config comes from the environment only** (§15 Factor III) — `config.yaml` becomes `.env.example` defaults, and no model id may end in `-latest` (below) |
| `app/main.py` | 293 | **port with changes** | FastAPI surface → §7.4's paths; add bearer auth, the audit log, `/ready`, and `/runs/{run_id}` |
| `app/api_models.py` | 398 | **port with changes** | the typed response models are a good base; re-shape to the two envelope families of §7.1 and delete every `entity_keys` field |
| `app/embedder.py::embed_query_image` | — | **port and wire it** (D12) | An **image query** — a photo of a panel, optionally with text fused into the same `Content` — lands in exactly the space the indexed pages occupy. Nothing in §7.2 accepts an image as a query today (every `skim_*` takes `query: str`), so this capability would be silently lost. Now wired: `image` is an optional parameter on all three `skim_*` rungs (§7.2.1), and an image-only query runs the dense branch alone |
| `scripts/interfaces_demo.py` | — | **port as the demo spine** | it is the ancestor of `vsir demo` (§4.4) |
| — | — | **net new** | the text index (§5.5), `verify` (§7.2.4), `fetch` (§7.2.5), the three `skim_*` rungs, the runner (§8), the invariants as assertions (§9), **the entire test pyramid (§12)**, the twelve-factor runtime (§15) |

**Three corrections `impl` forces on this spec, all adopted:**

1. **`-latest` model ids are in use today** — `impl/config.yaml` sets `extract: gemini-pro-latest`
   and `read: gemini-pro-latest`, and warns in its own comment that *"Model IDs move."* That is
   exactly F11, so §4.3's boot refusal is a correction **of `impl`**, and the ported config must
   resolve those aliases to pinned ids before first run.
2. **`impl`'s tokeniser is not Qdrant's.** `TOKEN_RE = [A-Za-z0-9]+(?:[./\-_][A-Za-z0-9]+)*` keeps
   `84-5140.0020` as **one** token, while Qdrant's `WORD` tokenizer splits it into
   `[84, 5140, 0020]`. The new `tok()` must mirror **Qdrant** (§5.6), not `impl` — porting the
   regex unchanged would make `verify` disagree with the index it is checking.
3. **`max_read_pages` is 4 in `impl`; plan2 and §7.3 say 3.** The spec keeps **3** — the tighter
   bound is the one plan2 argues for — and the change is deliberate, not a porting slip.

**What `impl` already paid for, and this CR reuses for free:** `impl/data/raw/<doc_id>/<sha256>.json`
holds the content-addressable S2 responses for 7 documents (`TC1E-SF` is 2 windows / 64 KB — the
pages 1-30 and 31-55 split §12.1 describes), and `impl/data/exports/r-poc-*/` holds real
`labels.jsonl`, `withheld.jsonl` and `manifest.json`. See §12.1 and M2b for how these become the
frozen fixtures and the `lookup` parity baseline.

### 2.5 Features in the first implementation that this CR does **not** include

§2.4 is the module ledger. This is the **feature** ledger — everything `impl` can do today that the
new build will not, so nothing is dropped by accident and nobody is surprised at integration.
Read it as a checklist before declaring parity.

**A · Retrieval and API features that go away**

| `impl` feature | What it did | Status | What replaces it |
|---|---|---|---|
| **`200`-empty as the abstention path** | `main.py`'s own docstring: *"nothing matched → 200 empty. The agent's designed abstention path."* | **removed — deliberately** | Four typed absences (§7.1, I5). **This is a breaking change for any existing caller**: an empty `200` is now impossible |
| `POST /api/v1/compare` | compared two segments in one call | **removed** | `fetch` — the agent holds both pages in its own context and compares them itself (plan2 §3.3) |
| `POST /api/v1/expand` | *"the rest of this unit, by key lookup. A JOIN, never a second search"* | **removed as an endpoint** | `next.expand` on every hit + a re-scoped `skim` (§7.2.1 P4). The capability survives; the endpoint does not |
| `DELETE /api/v1/documents/{doc_id}` | removed a document from the index | **not in the HTTP surface** | `vsir retire <doc_id> [--revision]` — a one-off admin process (§4.4, §15 Factor XII), because deletion is an operator action, not a caller's |
| **The HTML UI at `/`** | upload, search and view, served by `main.py` | **not ported** | M7's console is a different product (two-zone agentic workspace, §13). Between M0 and M7 there is **no UI at all** — the CLI (§4.4) is the only surface |
| `GET /api/health` (combined) | one endpoint mixing liveness and readiness | **split** | `/health` + `/ready` (§15.1) — a Qdrant outage must not restart-loop the process |
| Unauthenticated everything | *no auth on any endpoint, including the two that spend money* (`IMPROVEMENTS` E5) | **removed** | bearer on every tool (§7.4). Any script calling `impl` today needs a token |
| `/api/v1/*` path prefix | the five interfaces | **changed** | `POST /tools/{tool_name}` + `POST /ask` (§7.4). Every client path changes |

**B · Ingestion features that go away**

| `impl` feature | Status | Note |
|---|---|---|
| `entity_keys` curated exact-match index | **removed** | the phrase-matching `text` index (C2, §5.5) |
| The allowlist **gate** (`gate()`, `backs()`) and `withheld.jsonl` | **removed** | `grounded_rate` + `codes_in_text` (§5.7); verification becomes structural (I2) and an agent move (§7.2.4) |
| Identifier grammar — `SCHEMA_CARD`, `IdClass`, `classify()`, `normalise()`, nine regexes | **removed** | no grammar at all (§5.2 *Prohibited*) |
| Unit grammar — `STRICT_KINDS`, `key_for_unit`, `Unit.kind`, `attrs` | **removed** | `sections[]` = title + `is_start` only (§5.2) |
| `_is_safety()`'s hardcoded keyword list | **removed** | see the safety-flag rule in §6.8 — derived from `doc_type` + model `topics`, never a keyword list |
| `refs[]` in the S2 schema | **removed** | measured at **0 reads** anywhere in `impl` (`GENERIC` §2.3); cross-references live in `next.references` |
| `class_totality` publish gate | **removed** | `window_coverage` + `grounded_rate` (§11.1) |
| The **Level 2 window ladder** and its carry chain | **not included in v1** | see §6.2 — this is the one exclusion that changes what the POC can ingest |
| `config.yaml` / `corpus.yaml` as runtime config | **removed** | env-only (§15 Factor III). `corpus.yaml`'s *content* survives as §12 fixture metadata, not as config |
| Phase-1 `pages` collection and the phase-1 image-only app | **not ported** | only the page-record design is carried over. (`IMPROVEMENTS` E8 notes the container on `:8100` still runs the phase-1 app) |

**C · Operational behaviour that goes away**

| `impl` behaviour | Status |
|---|---|
| Job state as a dict on daemon threads (`IMPROVEMENTS` E2) | **removed** — `vsir_runs` + lease (D9) |
| `uuid4().hex[:8]` upload directories (`IMPROVEMENTS` E1) | **removed** — deterministic `run_id` (ULID) and `doc_id` |
| On-disk exports at `data/exports/{run_id}` (Leaf contract Channel A) | **changed** — streamed from HTTP (§6.8). ⚠ **see OQ-7** |
| Rendered pages persisted under `/data/pages/<doc_id>/` | **removed** — rasters are re-rendered on demand (§4.2, closes `IMPROVEMENTS` E3) |
| `max_read_pages: 4` | **tightened to 3** (§7.3, deliberate — §2.4) |
| `captions` weighted 0.4 but never written (`IMPROVEMENTS` D3) | **changed** — now populated (D2) |

**D · ⚠ The five exclusions somebody will notice**

Everything above is a design choice; these five are the ones that break something outside this
service, and each needs a conversation, not just a spec line:

1. **`200`-empty → typed absence.** Any existing caller that treats an empty `200` as "no results"
   must learn four new statuses. This is the point of the whole design (I5), and it is still a
   breaking change.
2. **`segment_id` → `page_id`, `verified_identifiers[]` → `codes_in_text[]`** (C8, D1). Part A's
   attachment evidence keeps its meaning under a new name and a new granularity.
3. **Exports move from disk to HTTP** (§6.8). If Part A reads files from `data/exports/{run_id}`,
   this breaks it — **OQ-7**.
4. **Bearer auth everywhere.** Every existing script and notebook needs a token.
5. **No UI until M7.** If anyone is using `impl`'s upload-and-search page as their working tool,
   they lose it for the duration.

---

## 3. Closed decisions

`plan2` left three decisions open (`GENERIC` §9), left four more implicit, and four more surfaced
during review. All eleven are closed here so no unit begins with a guess.

> **Three were re-decided against the working implementation** (`impl`, §2.4) after it came to
> light: **D2** (sparse + RRF are ported, not dropped), **D4/D8** (the dense vector is a fused
> image+text embedding, so the multivector workaround is withdrawn) and **C12** (the raster *is*
> embedded). Evidence beats inference, and the code is the evidence.

| # | Decision | Ruling | Rationale |
|---|---|---|---|
| **D1** | Is the graph team still a consumer of the export? | **Yes.** Export stays, shape changes: page-level `labels.jsonl` with `page_range`, `sections[]`, `summary`, `codes_in_text[]`, `safety_flag` (§6.8) | POC doc §5 makes it a contract, not a refactor |
| **D2** | Does the sparse/lexical **vector** earn its place? | **Yes — ported, and the third surface finally populated.** `impl` declares three fused surfaces but runs **two**: `page` (dense, 1.0) and `lexical` (sparse over the extracted text, 1.0) are live; `captions` (0.4) is declared on the collection and weighted in config while **nothing ever writes it** — `IMPROVEMENTS.md` §D3, confirmed in `segstore.py::upsert` where `caption_text` defaults to `{}`. This spec keeps all three and **writes the captions surface from the new S2 output** — `summaries[]` + `topics`, run through the ported `sparse.dedupe(against=text)` so no token the verbatim text already carries is counted twice. Fusion stays `impl/app/retrieve.py::rrf` at `rrf_k=60`. plan2 §9.2's *measurement* becomes an M8 evaluation, not a v1 deletion | RRF is **ranks-only** — *"no similarity score enters the arithmetic"* — so it satisfies the no-score refusal by construction (§7.6). And the reason `captions` never earned its weight is that it never had content: the new schema's page summary is exactly the generated description that surface was designed for (`GENERIC` §4), which closes a register item instead of deleting a channel |
| **D3** | Does `vlm_codes` ship in v1? | **Yes, opt-in, always `verified: false`.** It is the only recall on the 2 scanned pages and 7 zero-text vendor files, and correction Loop 5 depends on it | disclosed and separable; withholding it makes scanned pages silently unfindable |
| **D4** | Dense vector composition | **`gemini-embedding-2`, one page → one fused vector, image and text interleaved in a single `types.Content`** — ported from `impl/app/embedder.py`. Text parts (doc title, section titles, the page summaries, topics, codes, the extracted text) are **separate `Part`s**, never a concatenated blob, followed by the page raster as an image `Part`. Three API constraints are load-bearing and must survive the port: (1) `task_type` is **rejected** by this model — asymmetric retrieval is steered by an optional query instruction, empty by default because Google advises against prefixing when the corpus side is multimodal; (2) a **bare list** in `contents` returns ONE aggregated embedding, so each page must be wrapped in its own `types.Content` and the returned count verified with a per-item fallback; (3) `output_dimensionality` is MRL truncation — 768 → 1536 → 3072, with the dim recorded in the collection name and in the fingerprint (§6.6) | it is the design plan2 asked for, it is already written and reasoned about in `impl`, and it removes the need for the multivector workaround that D8 previously invented |
| **D5** | Per-language summaries (POC doc §2) | **`lang[]` per page; one summary per page in the page's dominant language(s).** A page whose `lang` has >1 entry gets one summary per language under `content.summaries[]` | one blended IT/EN summary poisons the embedding |
| **D6** | Bounding boxes / `around="K158"` | **Deferred.** `region=[x0,y0,x1,y1]` normalised only | no storage exists for boxes; `region` already delivers the zoom move |
| **D7** | Is the MCP surface or the runner the supported entry point? | **Both ship; only the runner may compose an answer.** Every safety rule that matters is enforced server-side (I5, I7, I8, caps). Prompt-level rules on the raw MCP surface are advisory and documented as R6 | an MCP client brings its own prompt |
| **D8** | How does a multi-language page get a vector without blending summaries (D5) or a second point (I1)? | **Superseded by D4 — no multivector, no second point, no blending.** Each language's summary is its **own `types.Part`** inside the one `Content` that also carries the raster, so the model fuses structured parts rather than a pre-blended string. `dense` stays a single ordinary vector. *(The earlier ruling here — a Qdrant multivector with `max_sim` — was invented to solve a problem the interleaved embedding does not have, and is withdrawn as unnecessary complexity.)* | D5's objection is to blending summaries **into one string**; separate Parts are exactly what the multimodal embedding is designed to take. One vector per page keeps I1, the fingerprint and the ordering rule all simpler |
| **D9** | Where does ingest run/window state live, given "Qdrant only" (§4.2) and "no local state" (§15.2)? | **A control-plane collection `vsir_runs`** holding one point per run and per window: `{state, step, attempts, checkpoint, lease_owner, lease_expires_at}`, plus the observed-token inventory per document. **One worker owns one run under a lease; there is no window-level work queue.** Qdrant has no compare-and-swap, so the lease is advisory — safety comes from I1 (idempotent `point_id`) and I7 (publish gating): a duplicated worker wastes money, it **cannot** corrupt the index | keeps one store, removes a distributed-claim protocol the POC does not need, and states the guarantee honestly instead of implying atomicity Qdrant does not offer |
| **D10** | How do CI, the E2E suite and the console run the whole loop with no Gemini? | **Deterministic replay.** `VSIR_VLM=stub` + `VSIR_FIXTURE=<dir>` replays frozen S2 and `read` responses keyed by `extract_key` / `read_key`; a miss is a typed `fixture_miss`, **never** a live call. The runner is therefore fully replayable, and M7 runs on whichever fixture exists (`TC1E-SF` once OQ-1 is answered, else `synthetic_3window`) | one code path (Factor X), zero spend in CI, and the loop is testable end to end before an API key exists |
| **D12** | Should the tool surface accept an **image query**, and should triage rows carry an image reference? *(was OQ-6)* | **Both, yes.** (a) `image` is an optional parameter on all three `skim_*` rungs, using `impl`'s ported `embed_query_image` (§7.2.1); (b) every page-level hit carries an `ImageRef` and every aggregate row a `preview` thumbnail — **references, never bytes** (§7.1) | (a) the capability is already written and paid for in `impl`, and a photographed panel is the technician's real starting point; (b) a reference is ~60 bytes and renders nothing until dereferenced, so it gives the UI and the agent the handle without touching P2's "enough to choose, never enough to answer" |
| **D11** | What are §12.6's "hard gate" numbers? | **`code_precision` = 1.00** (a single wrong code is a P0 stop), **`abstention_correctness` = 1.00**, **`code_recall` ≥ 0.95** (block below 0.90), **`alarm_label_hit` ≥ 0.99**, **`xref_resolve` ≥ 0.99**. Re-baselined once after M2b under the C10 rule | a gate without a number is a report. Precision must be perfect because §1.1 is about wrong answers; recall is a measured target, not a safety property |

---

## 4. Repository and runtime

### 4.1 Layout (normative)

Each module names the `impl` module it descends from, so a builder always knows whether to **port,
adapt or write** (§2.4). `←` = port, `≈` = port with changes, `+` = net new.

```text
backend/
  vsir/
    core/      record.py    ≈ pagemodel.py (record shape only)
               ids.py       ≈ pagemodel.py::make_page_id
               tok.py variants.py exact.py       + net new (the phrase surface)
               verify.py status.py indexed.py    + net new
               health.py                          + net new (grounded_rate)
    ingest/    manifest.py  ≈ pipeline.py
               probe.py     ← textlayer.py::probe/page_texts/content_hash
               render.py    ← render.py
               window.py    ← windows.py  (+ bisection ladder, F13)
               extract.py   ≈ segment.py  (new S2 schema)
               derive.py    ≈ segment.py  (no gate)
               stitch.py    ← stitch.py   (sections, + series_id)
               embed.py     ← embedder.py (interleaved, D4)
               sparse.py    ← sparse.py   (D2)
               index.py     ≈ segstore.py (+ text indexes, is_current)
               gates.py     ≈ pipeline.py (grounded_rate, not allowlist)
               export.py run.py  ≈ pipeline.py / segjobs.py
    vlm/       client.py cache.py stub.py  ≈ segment.py's Gemini calls
               prompts/ (s1.md s2.md read.md)
    serve/     app.py       ≈ main.py
               envelope.py  ≈ api_models.py
               auth.py audit.py budget.py        + net new
               tools/ skim.py    ≈ retrieve.py::search + rrf + decompose
                      lookup.py  ≈ retrieve.py::lookup (rewritten as a phrase filter)
                      resolve.py ← retrieve.py::resolve
                      read.py    ≈ retrieve.py::read
                      fetch.py verify.py         + net new
    mcp/       server.py                          + net new
    runner/    loop.py prompt.py triage.py answer.py   + net new
    cli.py                  ≈ scripts/interfaces_demo.py
  tests/       unit/ (L0-L1) api/ (L2-L3) paid/ (L4)
frontend/      React + TypeScript + Vite — M7 only
e2e/           Playwright (exists)
data/
  source/      input PDFs (gitignored except generated fixtures)
  fixtures/    frozen extractions — checked in
scripts/       test-unit.sh test-api.sh test-e2e.sh test-paid.sh (exists, extend)
```

### 4.2 Pinned dependencies and configuration

| Item | Pin | Enforcement |
|---|---|---|
| Python | 3.11, exact minor pinned by the image digest | Factor II |
| Pins carried from `impl/requirements.txt` | `fastapi==0.141.1` · `uvicorn[standard]==0.52.4` · `python-multipart==0.0.32` · `google-genai==2.22.0` · `qdrant-client==1.19.0` · `PyMuPDF==1.28.2` · `pillow==12.3.0` · `PyYAML>=6.0.2` (drop PyYAML if config is env-only, §15 III) | these are the versions the working system runs on — bump deliberately, never incidentally |
| `qdrant-client` / Qdrant | `1.19.0` / `qdrant/qdrant:v1.19.0` | `phrase_matching` requires it |
| FastAPI + Pydantic v2 | current | all request/response models typed |
| PyMuPDF | pinned exact version, recorded in `probe_version` | F15, extractor is the point of truth |
| Gemini SDK | `google-genai`, pinned | — |
| VLM model id | `VSIR_VLM_MODEL` — the pinned id for **Gemini 3.8 Flash**, the model the cost basis prices for segmentation and reads (note its 1 Jan 2027 price step: $0.75/$3.75 → $1.50/$7.50; the programme prices everything at the 2027 rate) | **boot refuses any id ending `-latest`** (F11) |
| Embedding model | `VSIR_EMBED_MODEL` — **Gemini Embedding 2 (text)**, the model the programme's cost basis prices ($0.20/1M, $0.10 batch — `effort_and_llm_cost_estimation.md` §"Pricing basis"). The interface stays provider-agnostic; `dim` is recorded. **Text only** — page rasters are not embedded (C12) | collection fingerprint (§6.6); a change is a new collection, never an in-place mix; the id is pinned, never `-latest` |
| MCP | official Python SDK, stdio + SSE | — |
| Store | **Qdrant only**, two collections: `vsir_pages` (the page index) and `vsir_runs` (control plane — runs, windows, observed-token inventory; D9). No relational database, no ORM, no migrations, no queue service | conformance grep bans `alembic`, `sqlalchemy` |
| Rasters | **never persisted.** Rendered on demand into an in-process LRU **cache**; a cold instance returns identical results, only slower | §15 Factor VI; no blob store, no local source of truth |
| Render dpi | **`dpi_index = 150`** — the raster that gets **embedded**; **`dpi_answer = 220`** — the raster `read` sees, pinned and part of `read_key`. Both ported verbatim from `impl/config.yaml` | F19, §7.2.6; `fetch` defaults to 150 and escalates on request (§7.3) |
| Embedding parameters | `dim` ∈ {768, 1536, 3072} via `output_dimensionality` (MRL truncation, dim recorded in the collection name); `concurrency=8`; `batch_size=8`; `max_edge_px=1568` | all four from `impl/config.yaml`; changing `dim` is a re-embed, never in place (§6.6) |
| Fusion parameters | surface weights `page=1.0`, `lexical=1.0`, `captions=0.4`; `rrf_k=60`; `cap_pages_per_window=30`; `lookup_cap=20` | ported from `impl/config.yaml` (D2) |
| Ingest render dpi | `220`, recorded on every record | part of `extract_key` |
| Ports | backend dev `8000` / test `8001` (`impl` publishes `8100→8000`); Qdrant dev `6333` REST **and `6334` gRPC**, so the test instance takes `6335`, never 6334; frontend dev `5173` / test `5174` | `docker-compose.test.yml` must be rewritten from Postgres to Qdrant at M0 |

### 4.3 Boot self-check (`vsir doctor`, and on server start)

Refuse to start, with a named reason and non-zero exit, when: a configured model id ends in
`-latest`; the live Qdrant payload schema lacks any key in `INDEXED`; the collection fingerprint
does not match the configured embedding model; `text`/`vlm_codes` are not text indexes with
`phrase_matching=True`; or a required env var is missing. **Never degrade to a partial service.**

### 4.4 The `vsir` CLI — the only supported operational surface (§15 Factor XII)

| Command | Purpose | From |
|---|---|---|
| `vsir doctor` | the boot self-check of §4.3; prints `release_id`, resolved model ids, index fingerprint | M0 |
| `vsir demo exact --synthetic` | seed synthetic pages, run the exact-surface assertions | M1 |
| `vsir demo narrow` | the narrowing demo over the frozen fixture | M4 |
| `vsir ingest <pdf> [--vlm stub] [--resume <run_id>] [--steal]` | steps 01–12; `--steal` is required to take a live lease (D9) | M2a |
| `vsir runs show <run_id>` | the run record of §6.9 | M2a |
| `vsir gates rerun <run_id>` | re-evaluate the publish gates of §11.1 | M2a |
| `vsir retire <doc_id> [--revision]` | remove a document (or one revision) from the index — replaces `impl`'s `DELETE /api/v1/documents/{doc_id}` (§2.5 A) | M8 |
| `vsir publish <run_id> --override <gate> --reason "<text>"` | release a document a gate is holding; the reason is recorded in the run and every page is flagged `published_with_override` | M2b |
| `vsir serve` | the HTTP surface of §7.4 | M3 |
| `vsir mcp [--stdio\|--sse]` | the MCP surface of §7.5 | M3 |
| `vsir lookup` · `verify` · `resolve` · `skim` · `fetch` · `read` | one-shot tool calls for demos and scripts | M3–M5 |
| `vsir ask "<question>"` | the runner of §8 | M6 |
| `vsir eval acceptance \| abstention \| corpus` | §12.3 · §12.4 · §12.6 | M3, M8 |

---

## 5. Data contracts

### 5.1 Identifiers

```
doc_id       stable slug from the manifest, e.g. "TC1E-SF"
revision     document revision string, e.g. "1.3"
page_id      "{doc_id}@{revision}#p{NNN}"     NNN = 1-based absolute page, zero-padded to 3+
section_id   "{doc_id}@{revision}#s{NNN}"     NNN = section ordinal after stitching
series_id    stable id of a section across revisions (F8)
point_id     uuid5(NAMESPACE_URL, page_id)    idempotent: re-ingest overwrites (I1)
run_id       ULID per ingest run
```

### 5.2 The S2 response schema (the only VLM extraction schema)

```python
class Summary(BaseModel):
    lang: str                # ISO code, e.g. "it" | "en"
    text: str                # 2-3 sentences SPECIFIC to this page

class SectionRef(BaseModel):
    title:    str            # the section/procedure/topic this page belongs to
    is_start: bool = False   # true ONLY if it begins on this page

class PageOut(BaseModel):
    page_index:      int              # 1-based WITHIN THIS EXCERPT, not the book
    printed_page_no: str = ""         # the page label as printed, VERBATIM
    page_kind:       str = "prose"    # prose|table|schematic|exploded|cover|toc|index|blank
    lang:            list[str] = []
    sections:        list[SectionRef] = []
    summaries:       list[Summary]    # one per lang (D5); 2-3 sentences SPECIFIC to this page
    codes:           list[str] = []   # every code, tag, part or reference number, VERBATIM
    topics:          list[str] = []   # short lowercase labels

class WindowOut(BaseModel):
    pages: list[PageOut]
```

**Prohibited:** any identifier grammar, classification enum, regex taxonomy or per-corpus keyword
list anywhere in extraction or derivation. `sections[]` carries **presence per page, never extent**
— that is what makes stitching survive window folds.

**Prompt rule for summaries (binding):** *"2–3 sentences on what is SPECIFIC to this page. Do not
describe the document generally."* Generic description makes the dense vector less discriminative.

**Permitted string normalisation** (the only exception to "no regexes"): whitespace collapsing and
letter↔digit boundary spacing inside `variants()` — provably character-preserving by the I3
property test. Everything else is banned.

### 5.3 The page record

```
FLAT · FACETS ─────────── indexed keyword / integer / bool
  doc_id · revision · is_current · doc_type · subjects[] · tags[] · page_kind · lang[]
  page_no · section_id[] · series_id[] · has_text · text_trust · run_id

FLAT · FULL TEXT ──────── indexed text
  text        PyMuPDF extracted text of the FULL page   EXACT lookup, verified by construction
  vlm_codes   " ".join(codes)                           opt-in, always labelled verified:false

VECTORS ───────────────── one point, three surfaces, fused by RRF at query time (D2)
  dense      gemini-embedding-2, ONE fused vector per page (D4). Separate types.Part's
             in a single types.Content, in this order:
               doc_title · section_titles · summaries[] (one Part per language)
               · topics · codes · text[:N] · the page raster @ dpi_index
             N = VSIR_EMBED_TEXT_CHARS, default 2000
  lexical    sparse, raw term frequencies over `text`, Qdrant Modifier.IDF
  captions   sparse, over generated text with dedupe(against=text), weight 0.4

NESTED under `content` ── returned, never filtered
  printed_page_no · label_verified · interpolated · summaries[] · topics[] · sections[]
  codes[] · codes_in_text[] · moved_from[] · grounded_rate · flags[]

PROVENANCE ────────────── page_id · extract_key · embed_key · read_keys[] · run_id · release_id
                          schema_version · probe_version · vlm_model · prompt_version · dpi
```

`subjects` (machine/model) and `tags` (uploader/filename) are document-level; `page_kind` is the
one page-level facet and is what makes *"the wiring diagrams in this manual"* possible.

**`section_id` and `series_id` are keyword arrays.** A page that straddles two sections carries
both ids, and a scope filter matches if **any** element matches — the alternative, a single
`section_id` per page, is how F8 happens.

**There is no `image_path`.** Rasters are re-rendered on demand from the PDF (§4.2), so no record
depends on a file that may not exist on the instance serving the request (§15 Factor VI).

### 5.4 `INDEXED` — one dict, three jobs (I6)

One module-level dict **creates** the payload indexes, **gates** every filter, and is **asserted**
against the live collection at boot. Filtering on anything absent from it is a typed `400`, never a
slow scan; filtering on a nested `content.*` field is impossible by construction.

**Scope keys are `INDEXED` minus `text` and `vlm_codes`** — those two are reachable only through
`lookup` and `verify`, never as a caller-supplied filter.

```python
INDEXED = {
  "doc_id": "keyword", "revision": "keyword", "is_current": "bool", "doc_type": "keyword",
  "subjects": "keyword", "tags": "keyword", "page_kind": "keyword", "lang": "keyword",
  "page_no": "integer", "section_id": "keyword[]", "series_id": "keyword[]",
  "has_text": "bool", "text_trust": "keyword", "run_id": "keyword",
  "text": "text", "vlm_codes": "text",
}
```

### 5.5 Text index configuration

```python
client.create_collection(collection,                       # name carries the dim: pages_1536
    vectors_config={"dense": qm.VectorParams(size=EMBED_DIM,
                                             distance=qm.Distance.COSINE)},
    sparse_vectors_config={s: qm.SparseVectorParams(modifier=qm.Modifier.IDF)
                           for s in ("lexical", "captions")})   # ported from impl (D2)

for field in ("text", "vlm_codes"):
    client.create_payload_index(collection, field_name=field,
        field_schema=qm.TextIndexParams(type="text", tokenizer=qm.TokenizerType.WORD,
            lowercase=True, phrase_matching=True, min_token_len=1))
```

`phrase_matching` is what makes the design viable: `"SF 1.1A" → phrase [sf, 1, 1a]` is precise,
where any-order matching returns every page carrying `sf` and `1`. `min_token_len=1` keeps `SI3`,
`84`, `0020`.

### 5.6 Tokenisation, variants, and the single exact code path

```python
def tok(s) -> list[str]          # mirrors the Qdrant WORD tokenizer exactly: lowercase,
                                 # punctuation is a separator, min length 1
def variants(label) -> list[str] # exactly three spellings of the SAME characters:
                                 #   as given · whitespace removed · space at every
                                 #   letter<->digit boundary
def exact_filter(label, scope)   # the ONLY exact-match code path in the codebase:
                                 # should[ must[ MatchPhrase(text, v), *scope ] for v in variants ]
```

`tok()` and Qdrant's tokenizer must agree — an L0 differential test asserts it on a fixed corpus of
labels, because `verify` reasons in Python about what the index matched.

**Porting hazard (§2.4).** `impl`'s `TOKEN_RE` deliberately keeps `84-5140.0020` as **one** token
and `token_set()` additionally joins adjacent tokens, both to make the old `entity_keys` gate work.
Qdrant's `WORD` tokenizer does neither: it yields `[84, 5140, 0020]`, which is precisely why
`phrase_matching` is the mechanism (§5.5). **Do not port either behaviour** — `tok()` mirrors
Qdrant, and multi-token labels are handled by phrases plus `variants()`.

### 5.7 Health signals

```python
# "Is this code printed on this page?" is ONE question with ONE answer (§5.6, I3): a phrase over
# variants(), which on the Python side is vsir.core.exact.printed_on(code, text) — the very
# question exact_filter asks the index. A token_set() intersection is NOT that question.
seen          = list(page.codes)                               # what the model saw, verbatim
grounded      = [c for c in seen if printed_on(c, page.text)]  # ... and the text layer backs
codes_in_text = sorted({" ".join(c.split()).lower()            # the export's allowlist (C8):
                        for c in grounded})                    # normalised, e.g. "sf 1.2a"

# grounded_rate is DEFINED ONLY where there is a text layer to be grounded in:
grounded_rate = (len(grounded) / len(seen) if seen else 1.0) if page.has_text else None
```

**Why a phrase.** A `token_set(text)` intersection can only ever see single-token codes — `SF 1.3A`
and `EAO 84-5140.1003` tokenise to runs of three and four tokens, so they are never members of it,
and §5.6 dropped the adjacent-token joins that used to paper over that. Asking `printed_on()`
instead makes `codes_in_text` and what `lookup` would find on the page one and the same answer (I3).

**Why the `None`.** A scanned page has codes the model read off the raster and no text layer at
all, so a numeric 0.0 there does not mean "extraction is broken" — it means "there was nothing to
check against". Scoring it 0 would drag the document median below the §11.1 gate and quarantine
exactly the scanned documents F4 requires to be published-and-unsearchable. `grounded_rate` is
therefore `None` on `has_text == false` pages, and every aggregate over it **ignores those pages**.

| Signal | Level | Meaning / use |
|---|---|---|
| `grounded_rate` | page | `40 seen · 0 grounded` = text extraction is broken **on a page that has text**; `None` where there is no text layer |
| `text_trust` | page/doc | `ok` \| `degraded` \| `untrusted` \| `no_text`. Both `untrusted` and `no_text` pages count as **unsearchable** for `lookup`, and `verify` returns `unverifiable` for them |
| `has_text` | page | facet; drives `not_searchable` (F4). `has_text == false` ⇒ `text_trust == "no_text"` |
| `searchable_ratio` | document | `pages with has_text ÷ pages`, on every `skim_documents` row — the agent's blind spot made visible |

---

## 6. Ingestion pipeline

### 6.1 Steps

| # | Step | In → Out | Guard |
|---|---|---|---|
| 01 | manifest | file + uploader metadata → `doc_id`, `revision`, `doc_type`, `subjects`, `tags` | facets from filename/metadata/uploader only — no content sniffing grammar |
| 02 | probe + text | PDF → per-page `text`, `has_text`, `page_count`, `probe_version` | **the only writer of `text`** (I2); text always from the **full** page, never a crop (F15) |
| 03 | render | PDF → page rasters at dpi 220 | cached by page content hash |
| 04 | S1 document facts | doc head rasters → doc-level facts; picks the window ladder | prompt generalised; no per-corpus grammar |
| 05 | window + `extract_key` | pages → windows (target 30 pages) | §6.2 |
| 06 | S2 extraction | window rasters → `WindowOut` | schema §5.2; content-addressable cache §6.3 |
| 07 | derivation | `WindowOut` + probe text → page records | offset proof §6.4; `grounded_rate`; code reattribution §6.5; **no verification gate** |
| 08 | stitching | per-page `sections[]` → `section_id`, `page_range`, `series_id` | canonical key + carry-in across folds (F8) |
| 09 | embedding | record → dense vector | fingerprint §6.6 |
| 10 | indexing | records → Qdrant points, `is_current=False` | `point_id = uuid5(page_id)` (I1) |
| 11 | gates + publish | run → gate results; flip `is_current`; retire prior points | §11.1, §6.7, I7 |
| 12 | export | published run → `labels.jsonl` + observed-token inventory, both served over HTTP | §6.8 |

### 6.2 Windowing and bisection

Target 30 pages per window, subject to an output-budget ladder. On `MAX_TOKENS`, a truncated or
schema-invalid response, or an offset failure: **bisect and re-bill** — never pad, never
offset-guess, never accept a partial window (F13). A single page that still exceeds budget fails
the run with typed `window_unsplittable`.

**What is excluded, and what it costs (§2.5 B).** `impl` has a three-rung window ladder:
Level 0/1 cut on the document's own structure from the S1 table of contents and are therefore
**parallelisable**, while **Level 2 is a blind cut that must run sequentially with a carry chain** —
*"batch 2 needs to know what batch 1 ended with"* (`impl/pipeline-guide/04-windowing-and-keys.md`
§5). **v1 implements Level 0/1 plus bisection only. Level 2 and its carry chain are out of scope.**

The consequence is concrete and bounds the POC: `impl/corpus.yaml` records that the **1,440-page
manual and the 592-page E-diagram are the only two documents that need Level 2**, and excludes them
from the corpus slice for exactly that reason. So:

- every document in the POC slice (6 documents, 142 pages) ingests without Level 2;
- **the 1,440-page manual cannot be ingested by v1** — attempting it must fail with a typed
  `ladder_level_2_required`, naming the document, **never** a blind cut that silently straddles a
  safety function across a fold (which is F8's failure, one level up);
- M8's resume test therefore runs on a **generated large PDF**, not on that manual (§13 M8).

A known fragility carried with the ladder: it *"depends on an uncached model call"* — S1 — so §6.3
caches S1 per document, which `impl` does not (`IMPROVEMENTS` B2).

### 6.3 Cache keys (deterministic, content-addressable)

```
facts_key   = sha256( document content hash ‖ resolved vlm model id ‖ prompt_version )
              # S1 document facts — cached per DOCUMENT. impl does not cache these, so
              # every re-run re-bills S1 and can silently re-pick a different window
              # ladder (IMPROVEMENTS B2). Caching it makes the ladder reproducible.
extract_key = sha256( ordered page image hashes ‖ resolved vlm model id ‖ prompt_version
                      ‖ dpi ‖ schema hash )
read_key    = extract_key inputs ‖ question            # F19: a new question is a cache miss
embed_key   = sha256( composition version ‖ embed model id ‖ composed string )
```

Re-running on identical pages costs $0. The Gemini client carries a token-bucket rate limiter and
exponential backoff.

**Batch vs standard.** Ingestion has no latency requirement, so a full-corpus run uses the **Batch
API (50% discount)**, which is what the programme's cost basis assumes; interactive prompt tuning
and any single-document ingest use the standard endpoint. `VSIR_VLM_TIER ∈ {batch, standard}` — and
because the tier does not change the *output*, it is **not** part of `extract_key` (§6.3).

**Replay mode (D10).** With `VSIR_VLM=stub` and `VSIR_FIXTURE=<dir>`, both S2 extraction and `read`
are served from frozen responses keyed by exactly these hashes. A key that is not in the fixture is
a typed `fixture_miss` error — **never** a live call and never a fabricated response. This is the
same code path as production with a different attached service (§15 Factor IV, X), which is what
makes CI, the E2E suite and the console able to drive the whole loop for free.

### 6.4 The offset proof (I4)

```python
abs_page = window.start + page_index - 1
```

Two independent checks, both required:

1. **Structural** — the window returned exactly the page indices it was given:
   `sorted(p.page_index) == list(range(1, window.pages + 1))`.
2. **Independent observation** — when the page has text and the model read a `printed_page_no`,
   that label must phrase-match **this** page's text. If it matches a neighbour's text instead,
   raise `OffsetError` and bisect: that is the off-by-one signature.

A wrong offset shifts every page, citation and summary and **nothing else errors** — this is the
single most dangerous line in the pipeline.

### 6.5 Printed labels and code attribution

`printed_page_no` is model-read. Precedence: text-layer-confirmed label > model-read label >
interpolated from neighbours. `label_verified` and `interpolated` are recorded per page; an
ambiguous label resolves to a **list**, never a silent pick (F5).

**Code reattribution (F6).** Attention bleeds across a window fold: a code the model reports on
page *i* sometimes belongs to page *i±1*. When a code is absent from page *i*'s text but present in
an adjacent page's text within the same window, it is **reattributed to the page whose text
contains it**, and `content.moved_from` records `{code, from_page_id}` on the receiving page. A code
grounded in no page's text stays where the model put it, counts against that page's
`grounded_rate`, and never enters the exact surface (I2).

### 6.6 Embedding fingerprint

The collection stores `{embed_model, dim, distance, composition_version}`. On mismatch: **refuse to
upsert.** A model change is a new collection + full re-embed + alias swap, never an in-place mix.

### 6.7 Publish gating (I7)

Step 10 writes every point with `is_current=False`. Step 11 is the only thing that flips it, and
only when every blocking gate passes. Every tool injects `is_current=True` server-side, always.
The filtered `set_payload` is idempotent and retried; `published_at` is recorded only after it
returns. For full-corpus rebuilds prefer the atomic path: new collection + one alias swap.

**A crash at window 700 of a 1,440-page manual must leave 0 pages queryable** — otherwise
`searchable_ratio` lies and the loop abstains about a page that is in the document (F17).

**Retirement, and the exact scope of deletion (F12 vs F9).** After the gates pass:

1. points of the **same `(doc_id, revision)`** written by an *earlier* `run_id` are deleted by
   filter — that is what stops totals doubling and stale pages staying findable (F12);
2. points of the **previously current *other* revision** are set `is_current=False` and **kept** —
   they are what `found_only_in_superseded` reads from (F9);
3. points of any other document are never touched.

A blanket "delete every point whose `run_id` is not the current run" would satisfy F12 by
destroying F9's evidence. Both deletions are filter-based, idempotent and retried.

**Run and window state (D9).** The `vsir_runs` collection holds one point per run
(`{state, step, windows_done, windows_total, gate_results, lease_owner, lease_expires_at}`) and one
per window (`{state, attempts, checkpoint, extract_key}`). One worker owns one run under a lease;
`vsir ingest --resume` refuses a run whose lease is still live unless `--steal` is passed. The lease
is advisory (Qdrant has no compare-and-swap): a duplicated worker re-bills windows but cannot
corrupt the index, because `point_id` is idempotent (I1) and nothing is queryable until the gates
flip `is_current` (I7).

### 6.8 Exports (the Part A contract — D1, C8)

`labels.jsonl`, one line per **page**:

```json
{"page_id": "TC1E-SF@1.3#p001", "doc_id": "TC1E-SF", "revision": "1.3", "page_no": 1,
 "printed_page_no": "Page 1 of 55", "label_verified": true,
 "sections": [{"section_id": "…#s004", "title": "Emergency stop circuits",
               "page_range": [1, 30], "series_id": "…"}],
 "summaries": [{"lang": "en", "text": "…"}],
 "codes_in_text": ["k158", "q25", "sf 1.2a"], "grounded_rate": 0.95,
 "safety_flag": true, "vlm_model": "…", "prompt_version": "…", "dpi": 220}
```

**Where `safety_flag` now comes from.** `impl` sets it in `_is_safety()` from two things this CR
deletes: `Unit.kind == "safety_function"` (the unit grammar) and a hardcoded keyword list
(`"pl="`, `"performance level"`, `"safety"`, `"sicurezza"`, `"emergency"`, `"category 3"`,
`"category 2"`). Deleting both without a replacement would silently drop a **contract** item — the
POC doc §2 requires safety flagging to be exported to Part A and surfaced through `describe()`.

The replacement uses only sources that already exist, and adds no grammar:

```python
safety_flag = (doc_type in SAFETY_DOC_TYPES              # document-level, from the manifest
               or any(t in page.topics for t in SAFETY_TOPICS))   # model-emitted, not hardcoded
```

`SAFETY_DOC_TYPES` is a **manifest** facet (`safety_function_list`, …), set by the uploader — not
inferred from content. `SAFETY_TOPICS` matches against the model's own lowercase `topics[]`, which
is a *retrieval* label set, so a miss costs a flag rather than a wrong answer. **`safety_flag` is
advisory metadata for Part A's answer policy — it is never a gate, never a filter default, and
never a reason to hide a page.** If it must become load-bearing, it needs its own trust level, the
same open question as `IMPROVEMENTS` C2 (§20.1).

`codes_in_text` **is** the old `verified_identifiers[]`, computed structurally instead of by a gate.

**Where the exports live.** Nothing is written to the instance's filesystem (§15 Factor VI). Both
artefacts are generated from the index and **served over HTTP**:

```
GET /runs/{run_id}/export/labels.jsonl            streamed, one line per page
GET /runs/{run_id}/export/observed_tokens.jsonl   streamed, one line per document
```

The observed-token inventory that backs `present_instead` (C7) is stored as payload on the
document's control point in `vsir_runs` (D9) and held in an in-process LRU **cache** for the prefix
lookup. The code-like heuristic used to build it — *a token containing at least one digit* — is
**display-only**: it is unreachable from `lookup` and `verify`, enforced by module boundary and by a
test that asserts `present_instead` can never appear in `hits`.

### 6.9 Run record

`GET /runs/{run_id}` → `{run_id, doc_id, revision, release_id, state, step, windows_done,
windows_total, pages_indexed, gate_results, overrides: [{gate, reason, by}], published_at,
lease: {owner, expires_at}, failed: {step, reason},
cost: {input_tokens, output_tokens, cache_hits}}`.

`state ∈ {queued, running, stopped, gated, published, failed}`. `stopped` is what a `SIGTERM`
leaves behind (§15 Factor IX) and is the only state `--resume` accepts without `--steal`.

---

## 7. Tool surface

### 7.1 The response envelopes (I5)

There are **two response families**, because "did you find anything?" and "here is the material /
the verdict you asked for" are different questions. Collapsing them is what made the original
envelope unable to express a `verify` in which every claim is legitimately `absent`.

**Family A — search and absence: `skim_documents`, `skim_sections`, `skim_pages`, `lookup`,
`resolve`.** These can be empty, so they carry the typed-absence machinery:

```python
HitT = TypeVar("HitT", DocHit, SectionHit, PageHit, LookupHit, ResolveHit)

class SearchResponse(BaseModel, Generic[HitT]):
    status: Literal["ok", "not_found", "not_searchable",
                    "out_of_scope", "found_only_in_superseded", "error"]
    hits: list[HitT] = []
    unverified_hits: list[LookupHit] = []  # vlm_codes only, verified=False, never merged in
    total: int = 0                          # count(exact=True) — the SET size, not len(hits)
    capped: bool = False                    # total > cap: hits is a page of the set
    weak: bool = False
    needs_scope: bool = False
    next: NextMoves | None = None           # {expand, neighbours, references, suggest}
    effective_scope: dict                   # echoed back — the service is stateless (F8, C11)
    scope_stats: ScopeStats                 # {pages, pages_no_text, docs:[{doc_id, searchable_ratio}]}
    reads_remaining: int
    provenance: Provenance                  # {run_id, release_id, schema_version}

    @model_validator(mode="after")
    def empty_is_never_ok(self):
        assert self.hits or self.unverified_hits or self.status != "ok"
        return self
```

**Family B — material and verdicts: `fetch`, `read`, `verify`.** These are never "empty": the call
either ran or it did not, and the answer lives in per-item states.

```python
class ToolEnvelope(BaseModel, Generic[ResultT]):
    status: Literal["ok", "error"]          # did the CALL run — not what it found
    result: ResultT                         # FetchResult | ReadResult | VerifyResult
    reads_remaining: int
    provenance: Provenance
```

A `verify` where every claim is `absent` is `status: ok` with three `absent` verdicts — which is
the honest shape, and the reason Family B exists. A missing `page_id` is `404 page_not_found`, a
backend failure is a 5xx: **a failed call returned as an empty call turns our outage into the
agent's fabricated abstention.**

**The status enum has six values: `ok`, four distinct absences, and `error`.**

| Status | Agent action |
|---|---|
| `not_found` — searched, genuinely absent | abstain — but see `next.suggest` below |
| `not_searchable` — candidate pages have no text layer | escalate to vision (`fetch`/`read`) |
| `out_of_scope` — no document matched the filters | re-orient, widen |
| `found_only_in_superseded` | surface the revision and let the caller decide |
| `error` | retry / report — **never** abstain |

**`next.suggest`.** A `not_found` that a different *move* could still answer says so rather than
inventing a seventh state: `lookup("alarm 152")` finds no phrase, so it returns
`status: not_found` **with** `next.suggest: ["skim_pages"]` and the tokens that did occur. The
status stays honest; the affordance stops the agent abstaining on a phrasing accident (§12.3).

**`weak` does not depend on the caller.** `cap` controls how many hits come back and nothing else:

```python
WEAK_ABS = 20                                            # server constant, not a parameter
weak = needs_scope = total > max(WEAK_ABS, 0.25 * scope_stats.pages)
```

A trust signal that moved when a client passed `cap=200` would be worse than no signal.
`lookup("3")` unscoped matches most of the corpus, so it is `weak` at any `cap`.

**Hit models** (one per rung, so no field is ambiguous):

```python
ImageRef   = {url, thumb_url, dpi, width, height}      # a REFERENCE — never bytes
Preview    = {page_id, thumb_url}                      # the group's best-ranked page

DocHit     = {doc_id, title, doc_type, pages_matched, best_rank, searchable_ratio,
              summary, preview}
SectionHit = {section_id, title, page_range, pages_matched, best_rank, preview}
PageHit    = {page_id, printed_page_no, summary, summary_lang, page_kind, why, rank,
              flags, grounded_rate, text_trust, image, next}
LookupHit  = {page_id, page_no, printed_page_no, page_kind, verified, text_trust,
              image, next}
ResolveHit = {page_id, printed_page_no, label_verified, interpolated, image}
```

**Every search result carries an image reference. No search result carries image bytes.**

That is the sharpened form of P2, and it is what lets both things be true at once:

| | in a triage row | in `fetch` |
|---|---|---|
| `image.url`, `thumb_url`, `dpi`, `width`, `height` | **yes** — ~60 bytes, and **zero render cost until dereferenced** | yes |
| `bytes_b64` — the actual pixels | **never** | yes, when `inline=true` |

So `skim_pages`, `lookup` and `resolve` each hand back a `page_id` **and** a ready-made `ImageRef`:
the caller never constructs a URL, and a UI renders thumbnails straight from a skim. Because a URL
is lazy, a 10-row skim is still one small JSON response — nothing is rendered until something asks.

`DocHit` and `SectionHit` still carry no `page_id` — they answer *"which binder?"* and *"which
chapter?"*, and their job is to hand back a **scope** to descend into (`next.expand`). But they do
carry a `preview`: the `thumb_url` of the group's **best-ranked matched page**, falling back to page
1 when nothing matched. That fallback is the useful case — a `searchable_ratio: 0.00` row is the
agent's blind spot, and a thumbnail is how a person eyeballs an image-only binder without paying
for a `read`.

**Still refused: image *bytes* in a triage row.** If a skim shipped rasters the agent would answer
from the search result instead of choosing and then paying — the exact failure P2 prevents — at
1–2k tokens per row.

`verified` on a `LookupHit` is a **boolean about the surface it came from** (`text` = true,
`vlm_codes` = false). The three-state `present | absent | unverifiable` vocabulary belongs to
per-claim checks (§7.2.4, §7.2.6) and is never spelled as a boolean.

### 7.2 The eight tools

State lives in the **agent**, not the service. `scope` is a value the previous rung returned;
`exclude` is how the agent stops re-opening pages it already rejected.

#### 7.2.1 NARROW — `skim_documents` / `skim_sections` / `skim_pages` (free)

```
skim_documents(query, image=None, scope?, exclude?)          → [DocHit]
skim_sections (query, image=None, scope,  exclude?)          → [SectionHit]
skim_pages    (query, image=None, scope,  exclude?, limit=10) → [PageHit]
```

Hit shapes are in §7.1. `query` is optional **when `image` is given**, and vice versa.

One implementation, exposed three times — an agent chooses far more reliably between three names
than between three values of a `granularity` enum, and the three names make the ladder
self-documenting. All three rungs are the **same page query aggregated differently**: no second
collection, no extra storage. Aggregating by `doc_id` is also what stops one chatty document from
occupying every slot and burying the binder that answers.

- `why ∈ {"dense", "lexical"}` — `lexical` means a **text-index** phrase/token hit (there is no
  sparse vector, D2).
- `summary` in a triage row is the page's summary in the caller's requested `lang`, falling back to
  the page's dominant language (D5); the row states which language it returned.
- **No full text in a triage row** (P2). If the agent could answer from the row it would stop
  reasoning and start pattern-matching.
- `next: {expand: section_id, neighbours: [page_id, …], references: [printed labels]}` turns
  retrieval into navigation (P4).

**Ordering and aggregation (normative — and score-free).** Ported from `impl/app/retrieve.py::rrf`
(D2), which is already **ranks-only**: *"no similarity score enters the arithmetic."*

1. Three branches run inside `scope`, minus `exclude`: `page` (dense), `lexical` (sparse over the
   extracted text) and `captions` (sparse over generated text). `decompose(query)` splits exact
   identifiers out of the query first, so a code goes to `lookup`/the phrase filter rather than
   being blurred into the embedding.
2. Branches are fused client-side by **reciprocal rank fusion** at `rrf_k = 60` with weights
   `page 1.0 · lexical 1.0 · captions 0.4`. Only **ranks** enter the arithmetic; no score is
   computed, stored or returned (§7.6).
3. `rank` is the 1-based ordinal of the fused list and `why` names every branch that contributed
   (`["dense"]`, `["lexical"]`, `["dense","lexical"]`, …) — which is what makes §8.2's
   *auto-promote exact hits* and *use `why` as a signal* implementable.
4. `skim_pages` returns ≤ 10 rows (`limit`, max 25). `skim_sections` and `skim_documents` group the
   same fused candidates: `pages_matched` = group size, `best_rank` = the best page rank in the
   group, rows ordered by `(best_rank, -pages_matched)`, ≤ 10 rows.

Fusion is deterministic given the same branches, so two callers with the same
`(query, image, scope, exclude)` get the same order — which is what makes the E2E and L2 assertions
stable.

**Image queries (D12).** A technician photographs a panel and the photo searches the corpus. The
query vector comes from `impl`'s ported `embed_query_image(image, text=query)`, which puts the photo
and the words in **one `types.Content`** so the model fuses them — *"this photo, but the wiring
detail"* — landing in exactly the space the indexed page vectors occupy (D4). Three rules follow:

1. **No instruction prefix when the query is multimodal** — `impl`'s constraint, from Google's own
   guidance. The prefix applies only to a bare text query.
2. **An image-only query runs the dense branch alone.** `lexical` and `captions` are sparse vectors
   built from *text*; with no query text there is nothing to build. Those branches are skipped, RRF
   degenerates to the dense ranking, and every row's `why` is `["dense"]` — stated, not silent, so
   the agent knows the evidence is weaker than a `lexical` hit (§8.2).
3. **An image can never reach the exact surface.** `lookup` and `verify` take a text label only
   (I2, I3). A photo may *find* a candidate page; it can never *confirm* a code.

#### 7.2.2 JUMP — `lookup(label, scope?, include_unverified=False, cap=20)` (free)

Exact, phrase-only, a **set** — not a ranking. `count(exact=True)` for `total`, then `scroll` to
`cap` (`cap` bounds the returned page of the set and sets `capped`; it never affects `weak`, §7.1). `include_unverified=True` repeats the query against `vlm_codes` and returns those in
`unverified_hits` with `verified: false`; scores and lists are **never merged**. Candidate pages
with no text layer → `not_searchable`, never a bare empty set.

#### 7.2.3 FOLLOW — `resolve(printed_label, doc_id?)` (free)

→ `page_id` + `interpolated` + `label_verified`. Ambiguity returns every candidate.

#### 7.2.4 CHECK — `verify(claims, page_ids)` (free)

Per `(claim, page)` — not per claim — because a draft citing `p001–p002` must not let a code from
the neighbouring page through (I8).

`VerifyResult` is a map of claim → verdict, inside the Family B envelope (§7.1):

```json
{"status": "ok",
 "result": {"K158":   {"status": "present",      "page_ids": ["…#p001"]},
            "K73":    {"status": "absent",       "present_instead": ["K78"]},
            "SF 9.9": {"status": "unverifiable", "reason": "no_text"}}}
```

Three states. Collapsing `unverifiable` into `absent` tells the agent *"that code is not on the
page"* about a page it could not look at. `present_instead` is a **prefix lookup over observed
tokens**, capped at 5, labelled *"different part"* — never a distance, never a nearest match.

#### 7.2.5 LOOK — `fetch(page_ids, include=["image","text","summary"], dpi=150, region=None, inline=True)`

Returns **material instead of an answer**, so the caller can reason across pages, keep the
evidence, and ask a follow-up without re-billing. `region` is normalised `[x0,y0,x1,y1]`; PyMuPDF
renders the clip on demand — no new storage. Rendered rasters are cached in-process across turns
(§4.2).

**How the raster comes back** — both a reference and, optionally, the bytes:

```json
{"status": "ok",
 "result": {"pages": [
   {"page_id": "TC1E-SF@1.3#p001",
    "image": {"url": "/pages/TC1E-SF@1.3%23p001/image?dpi=150",
              "dpi": 150, "region": null, "width": 1240, "height": 1754,
              "bytes_b64": "iVBORw0KGgo…"},
    "text": "B221 --> K158 - SI3 …",
    "summary": {"lang": "en", "text": "Emergency-stop circuit …"}}]}}
```

- `url` always present — a bearer-authenticated `GET` (§7.4) that a browser `<img>` or a renderer
  can use directly. This is what M7's viewer displays.
- `bytes_b64` present when `inline=true` (**default true**, because an agent needs the pixels in
  context, and an MCP client cannot follow a URL). `inline=false` returns the reference only, which
  is what the console uses to avoid moving megabytes through JSON twice.
- `include` controls the parts: dropping `"image"` makes `fetch` a cheap text/summary read.

#### 7.2.6 COMPREHEND — `read(page_ids, question)` — **the paid step**

`ReadResult`, inside the Family B envelope, renders pages at the **pinned dpi 220** — a caller
cannot change it, because the dpi is part of `read_key` (§4.2, §6.3):

```json
{"extract": "Reset requires Q25 released and K158 energised",
 "codes": [{"raw": "Q25",  "status": "present"},
           {"raw": "K158", "status": "present"},
           {"raw": "K153", "status": "absent", "present_instead": ["K158"]}],
 "sufficient": true, "flags": [], "page_provenance": [{"page_id": "…#p001", "text_trust": "ok"}]}
```

- **Transcription correction is inside `read`, automatic, always** (Loop 1): every code the vision
  model emits is phrase-checked against that page's text and stamped with the **same three states
  `verify` uses** — `present | absent | unverifiable` (§7.2.4). One vocabulary, one meaning. On a
  page with no text layer **every** code is `unverifiable` — the honest answer.
- `sufficient` is mandatory: without it the agent cannot separate *"the answer is no"* from
  *"wrong page"*, and will compose an answer from a page that never contained one.
- **Retrieval judgment never happens inside `read`** — that would make the engine the answerer.

### 7.3 Caps and typed errors (F18)

Each is a **typed 400**, never a clamp, never a silent truncation.

| Bound | Value | Error code |
|---|---|---|
| `read` page images per call | **≤ 3** | `read_page_cap_exceeded` |
| `fetch` pages per call | ≤ 5 and ≤ 12 MP total | `fetch_budget_exceeded {limit, requested}` |
| `dpi` | ∈ {**36**, **72**, 150, 220, 300, 400} — 36/72 are the triage thumbnail tiers behind `thumb_url`, 150 is the `fetch` default, 220 is what `read` sees | `dpi_not_allowed` |
| `dpi > 220` | requires `region` | `dpi_requires_region` |
| unknown scope key | — | `filter_unknown_key {keys}` |
| per-caller `read` quota | server-side, `reads_remaining` in every envelope | `429 budget_exhausted` |

### 7.4 HTTP surface, auth, audit and cost

| Method + path | Purpose | Auth |
|---|---|---|
| `POST /tools/{tool_name}` | the eight tools of §7.2, one envelope each | bearer |
| `POST /ask` | the runner; **the only surface that may return prose** (§8.4) | bearer |
| `GET /pages/{page_id}/image?dpi=&region=` | **the page raster**, rendered on demand — the browser-renderable half of `fetch` (§7.2.5), same caps and same typed 400s as §7.3. Ported from `impl`'s `/api/v1/page-image/{page_id}` | bearer |
| `GET /runs/{run_id}` | the run record of §6.9 | bearer |
| `GET /runs/{run_id}/export/{labels,observed_tokens}.jsonl` | the streamed exports of §6.8 | bearer |
| `GET /health` | **liveness** — the process is up; MUST NOT fail on a backing-service outage (§15.1) | none |
| `GET /ready` | **readiness** — boot self-check passed, Qdrant reachable, pinned index schema present | none |
| `GET /metrics` | Prometheus (§11.4) | none (internal network) |

Bearer token required on every tool (`401` without one); identity is propagated, never
client-supplied. One append-only audit line per `read` and `fetch`:
`(user_id, run_id, session_id, tool, page_ids, dpi, input_tokens, output_tokens, cache_hit,
latency_ms)`. **Cost goes in the audit log, not the response body** — the agent gets one integer,
`reads_remaining`. A `usd_estimate` beside the verification stamps is noise next to the fields that
must not be missed.

### 7.5 MCP server

`vision-segmentation-retriever` exposes the same eight tools over stdio + SSE, calling the identical
implementations (no second code path). It is **stateless**: `scope` and `exclude` are parameters,
and `effective_scope` is echoed back.

### 7.6 Refusals (all four, enforced)

| Refused | Enforcement |
|---|---|
| returning a **similarity score** | conformance grep: no field named `score` in any response model. An **ordinal** `rank` / `best_rank` is permitted and required (§7.2.1) — a position is not a confidence |
| **routing** the query | no tool picks the document for the caller |
| composing the **answer** | only the runner composes, and only behind the answer gate (§8.4) |
| **fuzzy matching on codes** | conformance grep: no edit-distance / similarity library in `requirements.txt`; no `MatchText` in `serve/`; I3 property test |

---

## 8. The agentic runner

### 8.1 The loop

```
handle?  yes → lookup                        → TRIAGE → enough? ─┬─ fetch → the agent
         no  → skim_documents → skim_sections → skim_pages → TRIAGE │   looks at the page
                                                            ↑       └─ read  → a sub-model
                                                            │            looks and extracts
                                                            │                    ↓
                                                            │            draft the answer
                                                            │                    ↓
                                                            └── contradicted ── verify → ANSWER
TRIAGE empty · scope WAS searchable   → ABSTAIN, naming what was searched
TRIAGE empty · pages have no text     → fetch / read the image-only pages first
```

Three structural properties: narrowing is the same move repeated at three zoom levels; **the
expensive step happens once, late, after free narrowing**; verification happens **after** drafting,
not before.

### 8.1a Where the answer comes from — the image, by one of two routes

**No answer in this system is composed from text alone.** Narrowing is text-driven because triage
must be cheap (P2), but the draft is always written against a **page raster**: on a schematic there
are no sentences to reason over, only a drawing. There are two ways to put that raster in front of
a vision model, and the runner must choose deliberately:

| | `fetch` — **the agent looks** | `read` — **a sub-model looks** |
|---|---|---|
| who sees the pixels | the calling agent, at `dpi=150` by default, escalating to a `region` crop at 300/400 | Gemini, server-side, at the pinned `dpi_answer=220` |
| what comes back | the rasters themselves (≤ 5 pages, ≤ 12 MP) | a bounded extract, `sufficient`, and every code stamped `present` / `absent` / `unverifiable` |
| reason across pages | **yes** — both pages are in one context | no: one independent extract per page |
| ask a follow-up | free — the evidence is still in context | re-bills the whole vision call |
| zoom into a corner | **yes** — `region` at higher dpi | no |
| cost | the agent's own context, ~1–2k tokens per image | a Gemini call, the entire paid budget |

**Default: `fetch`.** When the runner is itself a vision-capable model, it looks at the page — that
is the human move this design is copied from (plan2 §1 move 4, *"on a schematic they look at the
PICTURE first"*), and it is why `fetch` exists at all: plan2 §3.3 calls the unreachable raster *"the
single biggest gap"*, and §12 concludes *"if you build only two things: `fetch` and `verify`."*

**`read` is for delegation, not for seeing.** Use it to buy a cheap bounded sub-answer, to keep the
agent's context small on a long trace, or when the caller is not vision-capable (an MCP client that
is text-only). The master contract's *"directed vision RAG"* (POC doc §4) is this route.

**The safety consequence, stated plainly.** Correction Loop 1 — automatic per-code transcription
stamping — lives **inside `read`** (§7.2.6). Take the `fetch` route and that automatic stamp does
not happen: the agent has read codes off a raster with nothing checking them. This is precisely why
the answer gate is **server-side and unconditional** (§8.4, I8): on either route, no code reaches a
rendered answer that `verify` did not clear for the page it is cited on. A `fetch`-first runner
without the gate would be the fastest path to the one failure §1.1 exists to prevent.

### 8.2 Tri-state triage (Loop 0 — the cheapest correction)

Every skim candidate is marked `relevant` | `uncertain` | `irrelevant` from its summary, for free,
**before any money is spent**. `relevant` → `read`; `uncertain` → the fallback pool;
`irrelevant` → `exclude` on subsequent skims.

Binary marking discards the fallback pool and forces a re-skim from scratch. Safeguards against a
summary hiding the answer, all binding on the system prompt:

| Safeguard | Rule |
|---|---|
| rejections stay soft | on `sufficient: false`, try the `uncertain` pool **before** widening scope |
| do not filter a small set | with ≤3 candidates, read them all |
| use `why` as a signal | a `lexical` hit on an exact code outranks a dense-only hit |
| auto-promote exact hits | query contains an exact identifier + hit `why` is `lexical` → bypass triage |
| tri-state is mandatory | enforced in the system prompt and in the runner's state machine |

Triage marks (`query → page → relevant?`) are written to telemetry as free evaluation data —
**never** as a mandatory tool call.

### 8.3 The six correction loops

| # | Trigger | Correction | Where |
|---|---|---|---|
| 0 | candidate looks wrong in triage | mark `irrelevant`, `exclude` it | the loop — before any spend |
| 1 | a code was misread | stamp `status: absent` on that code | **inside `read`**, automatic |
| 2 | about to assert a claim | `verify(claims, page_ids)` | after `read`, deliberate |
| 3 | `sufficient: false` | try `uncertain`, then widen and re-skim | the loop |
| 4 | `verify` contradicts the draft | try a different page | the loop |
| 5 | nothing found **and** `searchable_ratio < 1` | `fetch`/`read` the image-only pages; `lookup(include_unverified=True)` | the loop |

### 8.4 The answer gate (I8, server-side)

`POST /ask` is the only surface that may return prose, and it renders nothing a check has not
cleared:

```python
for code in codes_in_draft:
    v = verify([code], [cited_page_id]).result[code]      # Family B envelope, §7.1
    if   v.status == "present":      render(code)
    elif v.status == "unverifiable": render(code, badge="read from image, not text-verified")
    else:                            reject_draft(code, v.present_instead)
```

**The per-question read budget.** One paid `read` is the target and the worked trace achieves it,
but Loop 3 (`sufficient: false`) legitimately spends a second. The runner therefore enforces a hard
`VSIR_READS_PER_QUESTION` (default **3**), reported as `reads_remaining` and exhausted as
`429 budget_exhausted` — never a silent extra call and never an answer composed from a page the
model said did not answer.

### 8.5 Abstention wording

*"Not in these documents"* is **forbidden** while `pages_no_text_read < scope_stats.pages_no_text`
— one name for one thing, the same field the envelope reports (§7.1). The honest wording names the
gap:

> *"Not found in the searchable text of TC1E-SF and LTC1AV81. 14 image-only pages in CE-TC1AV8
> were not examined."*

---

## 9. Invariants (each enforced by an assertion, each with a test)

| # | Invariant | Mechanical enforcement | Asserted from |
|---|---|---|---|
| **I1** | One page, one point | `point_id = uuid5(page_id)`; unique `page_id` assert; `count(doc, rev) == pdf.page_count` after publish | M2a |
| **I2** | The exact surface contains only extracted text | `probe.py` is the only writer of `text`; source-scan test; `lookup("K999")` on a hallucinated code → `not_found`, and only `unverified_hits` when opted in | M1 |
| **I3** | Exact matching is phrase-only and varies only by whitespace | one `exact_filter`; no `MatchText` in `serve/`; property test: every variant equals the label with whitespace stripped, so `K73` can never yield `K78` | M1 |
| **I4** | The page offset is proved, never assumed | §6.4's two independent checks; failure bisects and re-bills | M2a |
| **I5** | Absence is typed; an empty list is never a bare `200` | the `SearchResponse` validator (Family A, §7.1) | M1 |
| **I6** | Nothing is filtered on an unindexed field | one `INDEXED` dict creates, gates and is asserted at boot | M1 |
| **I7** | A run that has not passed its gates cannot answer | `is_current=False` until gates pass; every tool injects `is_current=True` | M2a |
| **I8** | Every asserted code is verified against the page it is cited on | the answer gate, per `(claim, page)` | M6 |

---

## 10. Failure catalogue — **this table is the definition of done**

Each row names the milestone that closes it, so no milestone can claim a row another one owns.

| # | Failure | Guard | Test | Closed at |
|---|---|---|---|---|
| F1 | `lookup` returns the wrong page as exact | I3 phrase-only | `lookup("SF 1.1A")` → exactly 1 | M1 |
| F2 | `verify` confirms a code that is not on the page | the one `exact_filter` | `verify("SF 1.1A", [p008])` → `absent` | M1 (core) · M3 (tool) |
| F3 | Abstains on a label that *is* printed | I3 variants | the 8 compact labels | M1 |
| F4 | *"That part doesn't exist"* about a scanned page | `has_text` facet + I5 | scanned doc → `not_searchable` | M2a · M3 |
| F5 | Follows a cross-reference to the wrong page | label precedence, `label_verified`, ambiguity → list | misread label → flagged, never silent | M2a · M4 |
| F6 | Cites a page for a code that is on its neighbour | per-page `grounded_rate`, reattribution, I8 | code moved → `moved_from` recorded | M2a |
| F7 | Every page number shifted by one | I4 | synthetic 3-window PDF fixture | M2a |
| F8 | Searches a subset believing it searched the chapter | canonical section key + carry-in + `series_id`; stateless + `effective_scope` | straddling-section fixture | M2a (stitching) · M4 (stateless scope) · M8 (`series_id`) |
| F9 | Cites a superseded revision as current | `is_current` injected by default; `found_only_in_superseded` | two revisions indexed | M8 |
| F10 | Silent recall loss | I6 | unknown scope key → 400 | M1 |
| F11 | Cache serves output from a different model or prompt | key includes resolved model id + prompt version; aliases refused at boot | key changes when the prompt changes | M0 (boot) · M2a (key) |
| F12 | Totals double; stale pages stay findable | I1 + retirement scoped to the same `(doc_id, revision)` (§6.7) — never a blanket delete, which would destroy F9's evidence | re-ingest twice → same count | M2a |
| F13 | A window truncates and loses 30 pages | output-budget ladder; `MAX_TOKENS` → bisect | oversized window bisects | M2a |
| F14 | A model-invented code becomes findable | I2 | the hallucination test | M1 |
| F15 | A code is invisible because it was cropped away | `text` always from the **full** page | crop fixture → full text indexed | M2a |
| F16 | A near-miss code presented as the answer | `present_instead` = capped prefix lookup over observed tokens, never a distance | `K73` on a K78 page → `absent` + `present_instead` | M1 |
| F17 | A half-finished run answers queries | I7 | kill an ingest mid-run → 0 pages queryable | M2a |
| F18 | Unbounded spend | §7.3 caps, each a typed 400 | over-budget → error naming the bound | M4 (`fetch`) · M5 (`read`) |
| F19 | A second question about the same pages returns the first answer | `read_key` includes the question | same pages, new question → cache miss | M5 |

Two properties must hold of every row: it **degrades to a visible state**, and it is closed by a
deterministic check — never by "the model will get it right".

---

## 11. Gates, degradation, observability

### 11.1 Publish gates (a document is published atomically or quarantined)

| Gate | Metric | Threshold | Action |
|---|---|---|---|
| `window_coverage` | pages with an S2 record ÷ page count | must be 1.0 after retries | **block** |
| `offset_check` | windows passing I4 | all | **block** |
| `grounded_rate` | median **over pages with `has_text`** (§5.7) | ≥ 0.8 *(provisional — set from the M2b distribution, R4)* | **block**, hold for review, list worst pages. Release with `vsir publish --override grounded_rate --reason "…"` (§4.4): the reason is recorded in the run and every page is flagged `published_with_override` |
| `text_coverage` | pages with `has_text` ÷ total | — | flag `mostly_scanned`, never block. **At 0.0 the `grounded_rate` gate is skipped entirely** — a fully scanned document is published and answers `not_searchable` (F4, D3), it is not quarantined |
| `label_monotonic` | printed labels non-decreasing | — | flag `label_conflict` |

### 11.2 Answer gates

Codes only as `verify` cleared them (I8); abstention wording constrained (§8.5); a page whose
`text_trust != ok` may support an answer only after a zoom-and-re-read, and its codes carry the
*read from image* badge.

### 11.3 Runtime degradation — each row is a refusal, not a best-effort fallback

| Condition | Behaviour |
|---|---|
| Qdrant unreachable | `503 qdrant_unavailable`, retryable — **never** an empty result. `/ready` goes red, `/health` stays green (§15.1) |
| Gemini unreachable | `503 vlm_unavailable` on `read`; every free tool keeps working |
| index schema ≠ `INDEXED` | refuse to serve at boot |
| embedding model ≠ collection fingerprint | refuse to upsert; new collection + re-embed + alias swap |
| model id ends in `-latest` | refuse to start |
| a document's `grounded_rate` collapses | set `text_trust = "untrusted"` (§5.7); its pages count as unsearchable; `verify` → `unverifiable` |
| per-caller `read` quota exhausted | `429 budget_exhausted`, not silent truncation |
| over-budget `fetch` | typed 400 naming the bound — never a dpi clamp or a truncated page list |

### 11.4 Observability

Prometheus gauges `ingest_grounded_rate_median{doc_id}`, `ingest_gate_failures_total{gate}`;
`GET /runs/{run_id}` (§6.9); the audit log (§7.4); triage marks to telemetry.

---

## 12. Test strategy

### 12.1 The fixture that makes it cheap

One paid ingest buys a permanent test corpus. Everything downstream of the paid call is then
testable forever at zero cost.

**Most of this fixture is already paid for.** `impl/data/raw/<doc_id>/<sha256>.json` holds the
content-addressable S2 responses for 7 documents — `TC1E-SF` as 2 windows (64 KB), `LTC1AV81` as 12,
plus `CE-TC1AV8`, `DS-2611-SICK`, `DS-5549-EATON`, `TC1E-PERIODIC`, `TC1AV8M2-LIFTING` — and
`impl/data/exports/r-poc-*/` holds real `labels.jsonl`, `withheld.jsonl` and `manifest.json`.

| Ported artefact | What it is good for **immediately** | What still needs M2b |
|---|---|---|
| `data/raw/*/*.json` (old S2 schema) | real window structure and page counts, so **L1 derivation, the offset proof (I4/F7) and stitching are testable on real data at zero spend** | the new fields — `summaries`, `topics`, `codes`, `sections` — are not in these responses (plan2 build step 4 = one re-bill) |
| `data/exports/r-poc-*/labels.jsonl` | the **`lookup` parity baseline**: every identifier the old `entity_keys` gate accepted must still be findable through the phrase index | codes the old grammar silently dropped are expected *gains*, not regressions — record them |
| `data/exports/*/withheld.jsonl` | the negative set: model-emitted codes the text layer never backed — these must be **unfindable** in the exact surface (I2, F14) | — |

Until M2b lands, every fixture-consuming level runs against `synthetic_3window/` **and** the ported
`impl` responses; afterwards it runs against all three. No level ever *requires* a new paid call
(D10, OQ-1).

```text
data/fixtures/synthetic_3window/    generated, checked in — no PDF corpus, no spend (M2a)
data/fixtures/TC1E-SF/              raw_window_1.json  the VERBATIM WindowOut, pages 1-30
                                    raw_window_2.json  pages 31-55
                                    text.json          PyMuPDF text per page, pinned extractor
                                    expected.json      the acceptance table
```

### 12.2 Levels

| L | Tests | Needs | Runtime | Script |
|---|---|---|---|---|
| **L0** | pure functions: `tok`, `variants`, offset, label normalisation, stitching | nothing | < 1 s | `scripts/test-unit.sh` |
| **L1** | derivation over frozen `raw_window_*.json` — the synthetic fixture before M2b, `TC1E-SF`'s 55 pages after | fixture | < 5 s | `scripts/test-unit.sh` |
| **L2** | index contract: the acceptance table against an ephemeral Qdrant | docker | < 30 s | `scripts/test-api.sh` |
| **L3** | **adversarial abstention** — the safety test | docker | < 60 s | `scripts/test-api.sh` |
| **L4** | the worked trace and the failure branch, end to end | docker + Gemini | minutes | `scripts/test-paid.sh` (requires `VSIR_ALLOW_PAID=1`) |
| **L5** | canary on a held-out document nobody tuned against | full stack | manual | `vsir eval corpus` |
| **E2E** | the console drives the loop against fixture-backed data | docker | minutes | `scripts/test-e2e.sh` |

**L0–L3 and E2E must never call Gemini.** They run in replay mode (D10): `VSIR_VLM=stub` +
`VSIR_FIXTURE=<dir>`, where a fixture miss is a typed `fixture_miss` rather than a live call. L4 is
the only level that may spend, and only with `VSIR_ALLOW_PAID=1`.

### 12.3 L2 · The acceptance table (absolute, not comparative — see C10)

```
lookup("SF 1.1A")                    → exactly 1 page       (any-order matching would give 3)
lookup("SF 5.5b")                    → exactly 1 page       (any-order would give 2)
lookup("SF 121.1")                   → 1 page               (the compact-label variant)
lookup("EAO 84-5140.0020")           → total 10              (hits capped at cap, capped:true)
lookup("B&R X20SI4100")              → total 54              (capped:true at cap=20)
lookup("3")             unscoped     → weak:true, needs_scope:true    (at ANY cap — §7.1)
lookup("alarm 152")                  → not_found + next.suggest:["skim_pages"]
                                       never a wrong page, never a bare empty 200
verify("SF 1.1A", [p008])            → absent               (tokens present, phrase not)
scanned document                     → not_searchable, never not_found

PARITY, against impl/data/exports/r-poc-*/labels.jsonl:
  every identifier the old entity_keys gate accepted   → still findable by phrase
  every raw in withheld.jsonl                          → NOT findable in `text`
                                                         (only via include_unverified)
```

The parity row is plan2's build step 3 (`GENERIC` §11), which C1 had struck as impossible. It is
possible — the baseline is checked into `impl` — and it is free, so it runs from M2b onward. A code
the old grammar dropped but the phrase index finds is a **gain**: record it, do not treat it as a
diff to reconcile.

### 12.4 L3 · The adversarial abstention eval (runs in CI on every commit)

```python
def test_near_miss_codes_never_answer():
    """100 codes one character off real ones.

    near_misses() mutates one character of codes taken from the observed-token inventory
    of WHATEVER corpus is indexed (§6.8) — the synthetic seed at M1, the real fixture after
    M2b. It never needs the 8,414-pair list to exist, so this test runs in CI from M1 on.
    """
    for fake in near_misses(n=100):
        r = lookup(fake)
        assert r.hits == []
        assert r.status in ("not_found", "not_searchable")
        for n in r.present_instead.values():
            assert n != fake          # never returned AS the match
```

If one assertion here ever fails, the system has produced the injury the whole design exists to
prevent.

### 12.5 Conformance greps (the mistakes a well-meaning contributor makes)

Scope: `backend/vsir/**` and `requirements*.txt` only — never markdown, and never the conformance
test itself (it names the banned strings, so it must exclude its own file).

Fail the build on: `MatchText` or `MatchTextAny` under `serve/`; any fuzzy / similarity /
edit-distance library in `requirements*.txt`; any field named `score` in a response model; a model
id ending `-latest`; `alembic` or `sqlalchemy` anywhere; `get_text(` outside `ingest/probe.py`; and
the struck legacy names `SCHEMA_CARD`, `IdClass`, `entity_keys`, `classify(` (C1).

**I2 is enforced by a test, not by grepping for `"text"`** — `ingest/index.py` legitimately upserts
a payload containing the key, so a string grep there would be a false positive. The real check is
an L1 assertion that for every page of the fixture `record.text == probe_text[page_no]`, paired
with the `get_text(` grep above: the probe is the only module that can *derive* text, and the
pipeline may only carry it through unmodified.

**Cloud-native greps** (§15), same scope plus `Dockerfile*` and `docker-compose*.yml`: no
`logging.FileHandler`; no container image tagged `latest`; no credential literal (`api_key=`,
`token=`, `Bearer ` followed by a string literal); no test-only branch (`if TESTING`,
`if os.environ.get("TESTING")`) inside `backend/vsir/**`; no `RetrievalState`-style module-level
mutable session store (C11).

### 12.6 Corpus evaluation (M8)

| Set | Ground truth | Metric | Gate (D11) |
|---|---|---|---|
| Component register (E pp. 59–125) | 2,053 rows · 748 tags · 484 codes | `code_precision` — a code `lookup` returns is the printed code | **= 1.00**, any miss is a P0 stop |
| " | " | `code_recall` — printed codes findable by `lookup` | **≥ 0.95**; block below 0.90 |
| Near-miss sample (§12.4) | 100 mutated codes | `abstention_correctness` | **= 1.00** |
| Alarm catalogue | numbers 0–539, ~494 records | `alarm_label_hit` — each number lands its record's page | **≥ 0.99** |
| Cross-references | 6,880 tokens, 99.97% resolvable | `xref_resolve` — `resolve` returns the right page | **≥ 0.99** |

Answer similarity alone is misleading for engineering work. **Precision is a safety property and
must be perfect; recall is a measured target.** These numbers are re-baselined exactly once, from
the M2b measurement, with a recorded rationale (C10).

---

## 13. Milestones

Each milestone states its working deliverable, the demo a reviewer runs, and its acceptance.
**Ordering principle: every correctness property that can be proved without a model call is proved
first.**

### M0 · Skeleton, pins, harness — *spend: none*

- **Depends on:** nothing.
- **Deliverable:** the repo skeleton — the `backend/vsir/` package, `cli.py` wired to
  `vsir doctor`, and the directories of §4.1. **Modules are created by the milestone that
  implements them**, never as empty placeholders (this is why §4.1 is a map, not an M0 checklist);
  pinned `requirements.txt` + lock file; `docker-compose.test.yml` **rewritten from Postgres to
  Qdrant**;
  `scripts/test-*.sh` extended (`test-paid.sh` added); `AGENTS.md` filled with real commands;
  `vsir doctor` implementing §4.3; the §12.5 conformance greps as a test; and the **twelve-factor
  runtime skeleton of §15** — `Dockerfile` (non-root, base pinned by digest, read-only rootfs with a
  writable `tmpfs` raster cache), `.env.example` listing every variable of §15 Factor III,
  `GET /health` + `GET /ready` per §15.1, structured JSON logs to stdout, a `SIGTERM` handler, and
  `release_id` stamped into the run record and every response envelope.
- **Demo:** `vsir doctor && bash scripts/test-unit.sh`
- **Acceptance:** doctor refuses a `-latest` model id and a missing payload index, naming the
  reason; conformance greps (including the cloud-native set) run and pass; `/health` stays green
  while Qdrant is stopped and `/ready` goes red; `vsir doctor` prints `release_id`, the resolved
  model ids and the index fingerprint; every decision D1–D7 restated in the repo README.

### M1 · `core/` + the exact surface on synthetic text — *spend: none* — **the whole proof**

- **Depends on:** M0. Ports `sparse.py` and the `rrf()` function from `impl` (§2.4, D2).
- **Deliverable:** `record`, both envelope families (§7.1), `INDEXED`, `tok`, `variants`,
  `exact_filter`, **`core/verify.py::verify_claims`** (the same filter, per `(claim, page)` — the
  tool wrapper comes at M3), the near-miss generator of §12.4, collection + index creation, and
  `lookup` against an ephemeral Qdrant seeded with **hand-written page text — no PDF**;
  three synthetic pages: one containing `SF 1.1A`, one with the tokens `sf`, `1`, `1a` scattered,
  one printing `SF121.1)`; plus a page whose `codes` claim `K999` that its text does not contain;
  and the observed-token inventory of §6.8 built from the seeded pages, so `present_instead` works
  before any PDF exists.
- **Demo:** `vsir demo exact --synthetic` prints each acceptance assertion and its verdict.
- **Acceptance:** F1, F2 (at core level), F3, F10, F14, F16 closed; I2, I3, I5, I6 asserted; the
  §7.3 cap validators reject over-budget arguments as typed 400s; **the L3 abstention eval runs here
  already**, on synthetic near-misses; L0 + L2 + L3 green.

### M2a · Ingest a generated PDF with a stubbed VLM — *spend: none*

- **Depends on:** M1.
- **Deliverable:** steps 01–12 wired end to end, including the `vsir_runs` control collection and
  the retirement rule of §6.7; a **generated** 3-window PDF checked into
  `data/source/` with known printed labels, a deliberate off-by-one trap and a crop trap; the stub
  VLM; run record; publish gating.
- **Demo:** `vsir ingest data/source/synthetic_3window.pdf --vlm stub && vsir runs show <run_id>`
- **Acceptance:** I1, I4, I7 hold; F6, F7, F12, F13, F15, F17 closed and F8's stitching half
  (canonical key + carry-in across a straddling section); killing the ingest mid-run leaves 0
  queryable pages and the run `state: stopped`; re-running twice yields the same point count; a
  fully text-free document **publishes** and is answerable only as `not_searchable` (A1/§11.1).

### M2b · Ingest the pilot PDF; freeze the fixture — *spend: S2 + embed, once*

- **Depends on:** M2a. OQ-1/OQ-2 only for the **re-bill**; the ported `impl` responses (§12.1)
  cover everything else.
- **First, port what is already paid for:** copy `impl/data/raw/*` into `data/fixtures/` as the
  old-schema baseline, and `impl/data/exports/r-poc-*/labels.jsonl` + `withheld.jsonl` as the parity
  and negative sets (§12.1, §12.3).
- **Deliverable:** one real ingest of `TC1E-SF` (55 pages) **under the new S2 schema only** — the
  single re-bill plan2 build step 4 budgets; `data/fixtures/TC1E-SF/*` frozen from
  the verbatim responses; `grounded_rate` distribution reported and the gate threshold set from it.
- **Demo:** `VSIR_ALLOW_PAID=1 vsir ingest data/source/TC1E-SF.pdf && vsir runs show <run_id>`
- **Acceptance:** 55 points published; `window_coverage == 1.0`; `offset_check` all pass; **the
  parity check against `impl`'s `labels.jsonl` passes and every `withheld.jsonl` raw is unfindable**
  (§12.3); the acceptance table reconciled against C10 with any discrepancy recorded as a finding.

### M3 · `lookup` + `verify`, over HTTP and MCP — *spend: none*

- **Depends on:** M2a. (The real-corpus half of its acceptance additionally needs M2b.)
- **Deliverable:** the six-value status enum with all four absences, `next.suggest`,
  `present_instead`, `unverifiable`, bearer auth, the audit log, `reads_remaining`; the MCP server
  exposing both tools through the same implementations; `vsir eval acceptance` and
  `vsir eval abstention`.
- **Demo:** `vsir serve &` then `vsir lookup "SF 1.1A" && vsir verify --claims K73 --pages …` and
  the same two tools called through an MCP client.
- **Acceptance, always:** the acceptance table and the L3 eval pass **on the synthetic corpus**;
  `401` without a token; `not_found` carries `next.suggest`; a text-free page answers
  `not_searchable` (F4).
- **Acceptance, once M2b exists:** the same table passes **on real text**, reconciled per C10, and
  F16 is demonstrated on a real near-miss pair.

### M4 · `skim_pages`, `fetch`, `resolve` — *spend: none*

- **Depends on:** M3.
- **Deliverable:** triage rows (no full text, but **an `ImageRef` on every page-level hit** —
  §7.1) with the deterministic ordering of §7.2.1, `exclude`, `next` affordances, `region`/`dpi`
  budgets including the 36/72 thumbnail tiers, `GET /pages/{page_id}/image`, the in-process raster
  cache, **image queries** (D12), and `resolve` with `interpolated`.
- **Demo:** `vsir demo narrow` — one query narrows the fixture to `p001`/`p002` and then fetches a
  `region` crop at dpi 400.
- **Acceptance:** F5 closed; every page-level hit carries a dereferenceable `image.url` and every
  aggregate row a `preview.thumb_url`, while **no triage row contains `bytes_b64`** (an asserted
  test, not a convention); an image-only `skim_pages` returns rows whose `why` is exactly
  `["dense"]`; **F8's stateless half** (`effective_scope` echoed, no server session);
  **F18 for `fetch`** — an over-budget call returns `fetch_budget_exceeded` naming the bound and
  `dpi=400` without `region` is a typed 400. `read`'s share of F18 belongs to M5, and `series_id`
  across revisions to M8; neither is claimed here.

### M5 · The ladder rungs + `read` — *spend: read*

- **Depends on:** M4 (paid assertions additionally need M2b/OQ-2; the replay fixture covers the
  rest).
- **Deliverable:** `skim_documents` / `skim_sections` with `searchable_ratio` on every document row;
  `read` with per-code `verified` stamps, `sufficient`, `page_provenance`, the ≤3-page cap, and the
  question-keyed cache.
- **Demo:** `VSIR_ALLOW_PAID=1 vsir read --pages TC1E-SF@1.3#p001,…#p002 --question "…"`
- **Acceptance:** Loop 1 stamps a deliberately misread code `status: absent` with
  `present_instead`; F19 verified (same pages + new question = cache miss); **F18 for `read`** — a
  4-page call is a typed 400; every code on a text-free page comes back `unverifiable`.

### M6 · The runner, the loop, the answer gate — *spend: read*

- **Depends on:** M5.
- **Deliverable:** `runner/` implementing §8 — tri-state triage with `exclude`, the six correction
  loops, the system prompt, the server-side answer gate, the constrained abstention wording;
  `POST /ask` and `vsir ask`.
- **Demo:** `VSIR_ALLOW_PAID=1 vsir ask "the carton discharge won't restart after an E-stop reset"`
- **Acceptance:** on the worked-trace fixture the loop completes in **exactly one paid `read`**
  and cites `p001–p002`, with `VSIR_READS_PER_QUESTION` (default 3) as the hard ceiling for the
  general case;
  the failure branch abstains **with coverage numbers** and never says *"not in these documents"*
  while unread image-only pages remain; a draft containing an unverified code is rejected, not
  rendered (I8).

### M7 · Operator console — *spend: none (fixture-backed)*

- **Depends on:** M6. Runs in replay mode (D10) — **no Gemini, no key, no spend** — against
  whichever fixture exists: `TC1E-SF` if OQ-1 is answered, otherwise `synthetic_3window`.
- **Deliverable:** React + TypeScript + Vite, two zones. It consumes `image.url` / `preview.thumb_url`
  directly (§7.1), so binder and chapter cards show thumbnails with no extra endpoint and no
  base64 in the skim payload (`inline=false`). **Left:** zoom-ladder breadcrumbs,
  high-res page viewer, region zoom at escalated dpi. **Right:** collapsible agent moves
  (skim/read/verify), the tri-state triage panel, the draft answer with **trust badges**
  (`verified` / *read from image* / `unverifiable`) and amber verification warnings. Clicking a code
  in the draft scrolls the viewer to its cited page.
- **Demo:** `bash scripts/test-e2e.sh` then browse `http://localhost:5174`
- **Acceptance:** a Playwright test drives the worked trace in replay mode and asserts that an
  `unverifiable` code renders with its badge, that a rejected code is **absent from the rendered
  answer**, and that the abstention text names the unread image-only pages. The assertions are
  fixture-independent, so they pass on the synthetic fixture too.

### M8 · Revisions, resumable ingest, scale-out — *spend: ingest*

- **Depends on:** M6 (and M2b for real-corpus numbers).
- **Deliverable:** `is_current` lifecycle, `found_only_in_superseded`, `series_id` across revisions,
  resumable/`--resume` ingest with per-window checkpoints, graceful-shutdown checkpointing
  (§15 Factor IX), the corpus evaluation report of §12.6.
- **Demo:** `vsir ingest --resume <run_id>` after a deliberate kill, then `vsir eval corpus`
- **Acceptance:** F9 closed **and F12's revision half** — publishing 1.4 retires 1.3's points to
  `is_current=false` without deleting them, and a lookup that only 1.3 satisfies returns
  `found_only_in_superseded`; F8's `series_id` half; a `SIGTERM` mid-window loses at most one window
  and publishes
  nothing partial; **a generated large PDF** (≥ 700 windows — not the 1,440-page manual, which
  needs the excluded Level 2 ladder, §6.2) survives a kill at window 700 and resumes without
  re-billing completed windows; attempting a Level-2 document fails with a typed
  `ladder_level_2_required`; the evaluation report states code exactness and abstention
  correctness per set.

---

## 14. Top-level acceptance criteria

- [ ] **AC-001** A code the model claimed but the page's text does not contain is unfindable through
      `lookup`, and appears only in `unverified_hits` when explicitly opted into (I2, F14).
- [ ] **AC-002** Exact matching is phrase-only; no variant of a label ever differs from it by more
      than whitespace (I3, F1, F3).
- [ ] **AC-003** The status enum has six values — `ok`, **four distinct absences** and `error` — and
      no Family A tool can return an empty `ok` (I5, F4, §7.1).
- [ ] **AC-004** A scanned document answers `not_searchable`, never `not_found` (F4).
- [ ] **AC-005** `verify` distinguishes `present` / `absent` / `unverifiable`, per `(claim, page)`,
      and offers near-misses only as labelled different parts (F2, F16, I8).
- [ ] **AC-006** Every page number is proved by two independent checks; an offset failure bisects
      and re-bills instead of publishing (I4, F7).
- [ ] **AC-007** A run that has not passed its gates has zero queryable pages (I7, F17).
- [ ] **AC-008** Every cap in §7.3 is a typed 400 naming its bound; no silent clamp exists (F18).
- [ ] **AC-009** On the worked-trace fixture the answer costs exactly one paid `read`, with
      citations; the runner's ceiling for any question is `VSIR_READS_PER_QUESTION` (§8.4).
- [ ] **AC-010** The failure branch abstains with coverage numbers and never claims absence while
      unread image-only pages remain in scope (§8.5).
- [ ] **AC-011** The L3 abstention eval passes on 100 near-miss codes, in CI, on every commit.
- [ ] **AC-012** The boot self-check refuses to serve on schema drift, fingerprint mismatch or a
      `-latest` model id (§4.3, F11).
- [ ] **AC-013** `labels.jsonl` delivers per-page `codes_in_text`, `page_range`, `sections[]`,
      `summaries[]` and `safety_flag` to Part A (D1, C8).
- [ ] **AC-014** Every milestone's demo command in §0 runs green on a clean checkout.
- [ ] **AC-015** One image runs every process type (`web`, `ingest-worker`, one-off admin); every
      deployment-varying value comes from the environment; no correctness-bearing state lives in a
      process or on local disk (§15 Factors III, V, VI, VIII, XII; C11).
- [ ] **AC-016** `SIGTERM` at any instant leaves no queryable half-document and `--resume` completes
      the run; `/health` and `/ready` behave per §15.1 during a Qdrant outage.

---

## 15. Cloud-native delivery — the twelve factors, applied

This service runs as containers under an orchestrator, and three of the twelve factors are
**load-bearing for correctness here, not decoration**: config-as-environment is what makes F11
(a cache serving another model's output) detectable; statelessness is what makes F8 (searching a
subset while believing you searched the chapter) impossible; disposability is what stops F17 (a
half-finished run answering queries). Every row below is a MUST.

| # | Factor | The rule in this system |
|---|---|---|
| **I** | **Codebase** — one codebase, many deploys | One repository, one image; deploys differ only by environment. No per-environment branch and no per-customer fork — a deploy is single-tenant (R5) |
| **II** | **Dependencies** — declared and isolated | Everything pinned per §4.2, transitively, in a lock file; no reliance on host packages (PyMuPDF ships wheels — no host poppler, no system OCR); `vsir doctor` prints the resolved versions |
| **III** | **Config** — in the environment | Every deployment-varying value is an env var listed in `.env.example`, never a committed config file and never a literal: `VSIR_PORT`, `VSIR_QDRANT_URL`, `VSIR_COLLECTION`, `VSIR_VLM` (`gemini`/`stub`), `VSIR_VLM_MODEL`, `VSIR_EMBED_MODEL`, `VSIR_PROMPT_VERSION`, `VSIR_API_TOKENS`, `VSIR_READ_QUOTA`, `VSIR_ALLOW_PAID`, `VSIR_LOG_LEVEL`, `VSIR_RELEASE_ID`. **Model ids and prompt versions are config *and* cache-key/fingerprint inputs, so changing one is a release, not a hot edit** (§6.3, F11). Secrets arrive from the platform secret store as env at runtime — never baked into an image, never committed. Boot refuses a missing variable or a `-latest` id (§4.3) |
| **IV** | **Backing services** — attached resources | Qdrant, the Gemini endpoint, the raster cache and the audit sink are attached by URL/credential from config and swappable without a code change. Each has a typed failure (§11.3): **a backing service never degrades into an empty result** |
| **V** | **Build, release, run** — strictly separated | *Build* = the image (base pinned by digest, non-root user, read-only root filesystem, writable `tmpfs` for rasters, no build tools in the runtime layer). *Release* = image + config, identified by an immutable `release_id`. *Run* = the process. `release_id` and `schema_version` are stamped on every run record (§6.9) and every envelope's provenance, so any answer traces to the exact code + config that produced it. The image is never tagged `latest` |
| **VI** | **Processes** — stateless, share-nothing | The service holds **no session**: `scope` and `exclude` are parameters and `effective_scope` is echoed back (F8, C11). Nothing correctness-bearing lives in process memory or on local disk. Rasters are never persisted at all: they are re-rendered on demand into an in-process LRU **cache** (§4.2), so a cold instance returns identical results, only slower, and no record points at a file (§5.3). **No sticky sessions, ever** |
| **VII** | **Port binding** — self-contained service | The app binds `$VSIR_PORT` (default 8000) and exports HTTP itself; the MCP SSE transport binds the same port. MCP stdio is a one-off process (Factor XII), not a second server |
| **VIII** | **Concurrency** — scale out by process type | Three process types from **one image**: `web` (tools + runner, N replicas, scaled on RPS), `ingest-worker` (**one worker per run**, N runs in parallel — there is no window-level queue, D9), `oneoff` (CLI admin). Ingest throughput is bounded by the Gemini token bucket (§6.3), not by replica count. A run is held under an advisory lease in `vsir_runs`; because Qdrant has no compare-and-swap, a duplicated worker is a cost bug, not a corruption bug — I1 and I7 are what make that true |
| **IX** | **Disposability** — fast start, graceful shutdown | Start-up is the boot self-check plus the index assertion; no warm-up requirement. On `SIGTERM`: stop accepting work, drain in-flight requests within the grace period, and **checkpoint the ingest window in progress** so a kill loses at most one window and never publishes a partial run (I7, F17, M8 `--resume`). Any process is killable at any instant without leaving a queryable half-document |
| **X** | **Dev/prod parity** | `docker-compose.test.yml` runs the same backend image as production, differing only in env and ports; Qdrant is pinned to the same version in both (§4.2). **The stub VLM is selected by config (`VSIR_VLM=stub`), never by a code branch or a test-only import** — the path under test is the production path |
| **XI** | **Logs** — event streams | Structured JSON to stdout, one event per line, carrying `release_id`, `run_id`, `session_id`, `request_id` and `tool` for correlation. **The app never opens a log file, never rotates and never ships logs itself**; the audit stream (§7.4) goes to stdout and/or the attached sink, and the ingest exports are **streamed from `GET /runs/{run_id}/export/…`** (§6.8) rather than written to a path the service manages |
| **XII** | **Admin processes** — one-off, same release | `vsir ingest`, `vsir ingest --resume`, `vsir eval …`, gate re-runs and collection/alias swaps run as one-off processes from the **same image and release** as `web`. No laptop-only script and no live surgery on the collection: a corrective action that cannot be expressed as a `vsir` subcommand is not a supported operation |

### 15.1 What the orchestrator needs beyond the twelve

| Concern | Requirement |
|---|---|
| Liveness vs readiness | `GET /health` = **liveness**: the process is up. It **MUST NOT** fail because Qdrant or Gemini is unreachable — otherwise a backing-service outage becomes a restart loop. `GET /ready` = **readiness**: boot self-check passed **and** Qdrant reachable **and** the pinned index schema present. A red `/ready` removes the instance from the load balancer; the boot refusals of §4.3 exit non-zero instead of serving |
| Probe cost | Both probes are free: no `read`, no embedding, no vector search beyond a capped `count` |
| Resource limits | Every process type declares CPU/memory requests and limits. Raster rendering is the memory spike, and the `fetch` ≤ 12 MP cap (§7.3) is what bounds it |
| Horizontal scale | `web` scales horizontally by construction (Factor VI); ingest scales by queue claim, never by a shared file lock |
| Secrets | Platform secret store → env at runtime; rotation needs no image rebuild; `VSIR_API_TOKENS` and the VLM key never appear in a log line, a response, or an error message |
| Data gravity | Qdrant is the only durable store — `vsir_pages` plus the `vsir_runs` control plane (§4.2, D9). Rasters are reproducible from the PDF on demand, so the raster cache is a **cache and never a source of truth**, and the observed-token cache is likewise rebuildable from `vsir_runs` — that is what keeps Factor VI honest |
| Retention | Audit lines carry `user_id` (§7.4): state a retention window in deployment config, and never widen the audit schema with document content |

### 15.2 Explicitly banned

- Local disk as a source of truth — rasters, index data, run state or logs on an instance's filesystem.
- In-process mutable session state, including the `RetrievalState` singleton plan2 sketched (C11).
- Secrets or model ids as literals in code; config read from a file committed to the repo.
- A `latest`-tagged container image or a `-latest` model id (F11, §4.3).
- Test-only branches (`if TESTING:`) in the production path — config selects the stub, not an `if`.
- App-managed log files, rotation or shipping.
- Sticky sessions, instance affinity, or any warm-up requirement before a replica can serve.

---

## 16. Non-functional requirements

| Area | Requirement |
|---|---|
| Latency | free tools ≤ 300 ms p95 per call on the pilot corpus; a three-rung descent < 1 s |
| Cost | ingest re-run on unchanged pages costs $0 (content-addressable cache); full-corpus runs go through the Batch API at the 50% discount (§6.3); ≤ 1 paid `read` on the worked trace and a hard ceiling of `VSIR_READS_PER_QUESTION` (default 3) elsewhere |
| Reproducibility | the same `(query, image, scope, exclude)` returns the same rows in the same order (§7.2.1) — no score, no nondeterministic fusion |
| Laziness | an `ImageRef` in a triage row renders nothing: a 10-row skim is one small JSON response, and rasters are produced only when a `url` is dereferenced or `fetch(inline=true)` asks |
| Determinism | identical inputs + pinned model + pinned prompt ⇒ identical `extract_key` ⇒ cache hit |
| Idempotence | re-ingest overwrites by `point_id`; totals never double |
| Concurrency | the service is stateless; `scope`/`exclude` are parameters |
| Security | bearer auth on every tool; identity from the propagated header only; rasters never returned without auth |
| Async hygiene | no blocking I/O in async paths |
| Typing | Pydantic v2 for every request/response; no untyped dict passthrough; no `any` in new TypeScript |
| Frontend | colors via CSS variables or utilities, no raw hex in components; lists > 50 items virtualized |
| Deployment | twelve-factor per §15: one image, config from env, stateless `web`, one-off admin processes, JSON logs to stdout |

---

## 17. Open questions

**Nothing blocks M0, M1, M2a, M3's synthetic acceptance, M4 or M7** — replay mode (D10) covers each of
them, and every open question below has a working default rather than a hold.

| # | Question | Blocks | Default assumption if unanswered |
|---|---|---|---|
| **OQ-1** | Where does the pilot PDF (`TC1E-SF`, 55 pp) live, and may it be checked in? | **only the M2b re-bill** — the S2 responses are already in `impl/data/raw/` (§12.1) | the operator places it at `data/source/TC1E-SF.pdf`; `data/source/` stays gitignored. Until then, ingest is exercised on the generated PDF and derivation on the ported `impl` responses |
| **OQ-2** | Which Gemini project/key and quota are available? `impl/.env` expects a single `GEMINI_API_KEY` | M2b, M5, M6 | run in replay mode (D10) off the ported responses until a key is provided; paid paths stay behind `VSIR_ALLOW_PAID=1` |
| **OQ-3** | Does Part A accept the page-level export shape of §6.8 (D1/C8)? | M8 export sign-off | ship the shape in §6.8, version it with `schema_version`, and serve it over HTTP so a shape change is a new endpoint version, not a migration |
| **OQ-4** | Is the 8,414-near-pair list available, or must near-misses be derived? | nothing — **resolved by design** | `near_misses()` mutates codes from the observed-token inventory of whatever corpus is indexed (§12.4), so L3 runs from M1 onward; the real list, if it arrives, only widens the sample |
| **OQ-7** | Does Part A **read the export files from disk** (`data/exports/{run_id}`, Leaf contract Channel A), or can it fetch them over HTTP (§6.8)? | the M8 export hand-off | serve over HTTP **and** write the same bytes to an attached object store if Part A needs files — never to the instance's local disk (§15 Factor VI). Resolve before M8 |
| **OQ-5** | Full corpus size at scale-out (5,505 pages) — one collection or one per document class? | M8 | one collection, `doc_id` scoping (as specified) |

## 18. Residual risks (stated, not solved)

| # | Risk |
|---|---|
| **R1** | **Recall is not guaranteed.** A summary can omit the line that mattered. Mitigated by the `uncertain` pool, "do not filter a small set", and `why: lexical` as a hard signal — a miss surfaces as an honest abstention, never a wrong page. |
| **R2** | **A scanned page's codes are never text-verified.** They are `unverifiable` forever; the badge is the deliverable, not certainty. |
| **R3** | **The extractor is the single point of truth for exact search.** If PyMuPDF misses text, `lookup` is blind there; detection is a `grounded_rate` collapse. |
| **R4** | **`grounded_rate ≥ 0.8` is chosen, not derived.** Set it from the M2b distribution before trusting it as a gate. It is measured only over pages that have a text layer (§5.7), so it says nothing about scanned pages — those are disclosed by `text_coverage` and `not_searchable` instead. |
| **R5** | **Multi-tenancy is out of scope.** A second customer on one instance turns this into a blocking finding. |
| **R7** | **The port is a rewrite of a system with no tests.** `impl` has 3,268 lines and zero test files, so its behaviour is only observable through its outputs. The ported artefacts in §12.1 are the mitigation: parity against `labels.jsonl` and the negative set from `withheld.jsonl` turn "does the new code still do what the old code did" into an assertion instead of a hope. What they cannot cover is behaviour `impl` never exercised — which is most of §7 and §8. |
| **R6** | **Prompt-level rules are advisory on the raw MCP surface.** Only server-side gates (I5, I7, I8, the caps) survive a careless client — which is why the answer gate is behind the API, not in the prompt (D7). |

---

## 19. Traceability to plan2

| Spec | plan2 source |
|---|---|
| §1.2, §5.3–5.5, §6 | `GENERIC-PIPELINE-PLAN.md` §1–§7; `PLAN.md` Part 2 |
| §7, §8 | `AGENTIC-RETRIEVAL.md` §3–§9; `PLAN.md` Part 3 |
| §7.5 | `MCP_ARCHITECTURE.md`; `PLAN.md` Part 4 |
| §9, §10, §11, §12 | `FAILPROOF-IMPLEMENTATION-PLAN.md` §1–§6; `PLAN.md` Part 5 |
| §13 | `FAILPROOF` §5 M0–M6; `GENERIC` §11; `PLAN` Part 7 — re-cut as M0–M8 so every step ships a runnable deliverable |
| M7 | `UI_CONCEPT.md`; `PLAN.md` Part 6 |
| §15 | **not in plan2** — the deployment contract, added so every milestone's deliverable runs the same way in test and in production |
| §2.3 | corrections; supersede the cited plan2 passages |
| §2.4, §4.2 pins, §5.3 vectors, §7.2.1 fusion | `VisionRag/…/impl` — the working implementation: `embedder.py`, `sparse.py`, `retrieve.py::rrf`, `config.yaml`, `requirements.txt`, `data/raw`, `data/exports` |
| §4.2 model + tier choices, §16 Cost | `solution/Dataset Ingestion & Retrieval/effort_and_llm_cost_estimation.md` — pricing basis (3 Sep 2026), §A3 Indexing, batch discount |
| §2.3 C12 | `GENERIC` §5 line 145 and the §1 diagram (`IMG → dense`) — **superseded**: the raster reaches the dense surface through the summary, not through an image embedding |
| §3 D8–D11 | **not in plan2** — the four design calls review exposed: the multi-language vector, run/window state, replay mode, and the evaluation thresholds |
| §3 D1–D7 | `GENERIC` §9 decisions, closed |

---

## 20. Document map — progressive disclosure

**This spec is the entry point and the only normative document.** Everything below is evidence and
rationale, to be opened **when a specific step needs it** — not read up front. Where any of it
disagrees with this spec, the spec wins (§2.3).

### Tier 1 · Design rationale — `plan2/` (this repo)

| Read | When |
|---|---|
| `PLAN.md` | the unified argument; start here if a spec decision looks arbitrary |
| `GENERIC-PIPELINE-PLAN.md` | §5–§6 work — the record, the one rule, the index config |
| `AGENTIC-RETRIEVAL.md` | §7–§8 work — the tool surface, the ladder, the six correction loops |
| `FAILPROOF-IMPLEMENTATION-PLAN.md` | §9–§12 work — invariants, failure catalogue, the test pyramid |
| `MCP_ARCHITECTURE.md` · `UI_CONCEPT.md` | §7.5 · M7 |

### Tier 2 · The previous implementation — `impl/` (≈ 9,600 lines of prose)

Its `pipeline-guide/` is written **per step**, and the steps line up with §6.1. **Open the matching
guide before porting a step**, and check `IMPROVEMENTS.md` first — several of these documents
describe behaviour §2.4 marks *do not port*.

| Spec step (§6.1) | Read in `impl/pipeline-guide/` | Caveat |
|---|---|---|
| 01 manifest | `01-entry.md` | — |
| 02 probe · 03 render | `02-probe-and-render.md` | see `IMPROVEMENTS` A1 — text is currently **not** always extracted |
| 04 S1 facts | `03-document-facts.md` | — |
| 05 window + `extract_key` | `04-windowing-and-keys.md` | no bisection ladder yet (F13) |
| 06 S2 extraction | `05-extraction.md`, `../SEGMENTATION.md` | old schema — §5.2 supersedes |
| 07 derivation | `06-derivation-and-gate.md` | ⚠ **documents the deleted allowlist gate** — read for the offset and the join, not the gate |
| 08 stitching · §6.5 labels | `07-stitch-and-numbering.md` | units → sections; no `series_id` yet |
| 09 embedding | `08-embedding.md` | the interleaved contract (D4) |
| 10 indexing | `09-indexing.md` | ⚠ `entity_keys` index is deleted (C2) |
| 11 gates + publish | `10-gates-and-publish.md` | ⚠ `allowlist` / `class_totality` replaced by `grounded_rate` |
| 12 export | `11-export.md` | ⚠ `withheld.jsonl` dropped; §6.8 is the new shape |
| §6.3 keys · §6.6 fingerprint | `12-reproducibility.md` | — |
| §5.3 the record | `pipeline-guide/METADATA-CONTRACT.md` | the payload contract, field by field |
| §7.2 the tools | `impl/README.md` §3 | the five interfaces this spec restructures into eight |
| M2a/M2b debugging | `impl/INGESTION_WALKTHROUGH.md` (1,456 lines) | a real ingest, traced end to end |
| **before porting anything** | `pipeline-guide/IMPROVEMENTS.md` (500 lines) | the known-defect register — see below |

### Tier 3 · Programme context

| Read | When |
|---|---|
| `poc/…/vision_segmentation_index_and_retrieval.md` | scope, the corpus, the Part A/B contract |
| `solution/Dataset Ingestion & Retrieval/ingestion_and_retrieval.md` | the master solution document |
| `…/effort_and_llm_cost_estimation.md` | model choice, pricing basis, batch discount (§4.2, §16) |
| `VisionRag/…/Leaf contract — what this service gives the graph.md` | the export contract to Part A (§6.8, D1) |
| `VisionRag/…/Ingestion platform — runtime, data management & serving.md` | runtime and serving background (§15) |

### 20.1 The known-defect register, and what this spec does with it

`impl/pipeline-guide/IMPROVEMENTS.md` is the most load-bearing document in Tier 2: it is where the
previous implementation records what it knows is wrong. **Do not port a known defect.** Most items
are already closed by this spec's design — which is the strongest available evidence that the
design is aimed at the right problems:

| Register item | Status here |
|---|---|
| **A1** always extract text (a one-line `else` throws it away on mixed documents) | **fixed** — §6.1 step 02 extracts unconditionally; R3 names it as the single point of truth |
| **A5** `image_path` is broken, so `read()` returns 503 for every page | **fixed** — there is no `image_path` (§5.3); rasters are re-rendered on demand and served by `GET /pages/{page_id}/image` |
| **B6** pin the model version, not a floating alias | **fixed** — F11, boot refuses `-latest` (§4.3) |
| **B1/B4** provenance sidecar and derived layer per run | **fixed** — §6.3 keys, §6.9 run record, `vsir_runs` (D9) |
| **B5** cache embeddings | **fixed** — `embed_key` (§6.3) |
| **D3** `captions` declared, weighted, never written | **fixed** — populated from `summaries[] + topics` (D2) |
| **E2** job state is a dict on daemon threads; a restart strands a paid run | **fixed** — D9 lease + checkpoints, §15 Factor IX |
| **E3** rendering unconditional and never collected | **fixed** — `dpi_index=150` at ingest, 220 lazily, rasters never persisted (§4.2) |
| **E4** no cost observability | **fixed** — §7.4 audit line, §11.4 metrics |
| **E5** no auth on any endpoint, including the two that spend | **fixed** — bearer on every tool (§7.4) |
| **E6** **no tests at all** — and the offset fails *silently* | **fixed** — §12, and I4 is the offset's two independent checks |
| **E7** re-ingest leaves orphan points | **fixed** — §6.7 retirement, F12 |
| **E9** `find_by_printed_label` scrolls 4,096 points and filters in Python — *"falls over well before the 1,440-page manual"* | **fixed** — I6 forbids filtering off-index; `resolve` uses indexed facets. Re-verify at M8 scale-out |
| **D1** bounding boxes | **deferred** — D6; `region` coordinates only in v1 |
| **D2** OCR as a separate lower-trust surface | **out of scope** — §2.2; disclosed as `not_searchable` instead |
| **A2/A3** per-page text detection, truthful `s2_input_mode` | **open** — carry forward; affects one document |
| **A6** read the PDF's own bookmark table instead of asking the model | **open** — a cheap S1 saving, not required by any invariant |
| **C1/C2** corrections overlay; is a human-corrected identifier pinnable? | **open, and a real question** — a human-verified code is not text-layer-backed, so I2 would exclude it. Deliberately unresolved: it needs a trust level of its own |
| **E1/E8** HTTP never calls `export()`; `docker compose build` fails | **not applicable** — §6.8 serves exports over HTTP; M0 builds the image fresh |

---

**In one line:** *Give the agent the moves a person actually makes — orient, narrow, look, widen,
follow, check, stop — make every result say how much to trust it, make every rule an assertion and
every path to a wrong answer a row in a table with a test beside it, and prove the exact-match
surface on synthetic text before spending a cent.*
