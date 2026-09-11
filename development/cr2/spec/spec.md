# CR2 Specification — `POST /search`, the flat retrieval surface

**Status:** Ready for planning — **written from the implementation, not before it** (§2.4)
**Created:** 2026-09-11
**Implementation Type:** backend (one server-rendered console tab; no React work)
**Parent CR:** [development/cr1/spec/spec.md](../../cr1/spec/spec.md) — authoritative for everything
this spec does not say
**Parent POC doc:** [vision_segmentation_index_and_retrieval.md](../../../vision_segmentation_index_and_retrieval.md) §4a
**Branch of record:** `feat/search-surface-and-document-store`
**Seed commit:** `c1d3100` — *"POST /search: the flat surface an external system consumes"*

> **This spec is authoritative for `POST /search`, the keyword filters, and the document store's
> location.** Everything else — the eight tools, the ingestion pipeline, the runner, the invariants
> I1–I8 and the failure catalogue F1–F19 — stays CR1's, unchanged. Where this spec is silent, CR1
> governs. Where the two disagree, **CR1 wins on the tool surface and this one wins on `/search`**,
> and §2.3 lists every place they touch.

---

## 0. Deliverable ledger

Same rule as CR1 §0: **a milestone with no runnable demo is not complete.**

| M | Working deliverable | Demo command (must succeed in front of a reviewer) | Spend | Status |
|---|---|---|---|---|
| **S1** | `POST /search` — ranked pages with their content, a typed `status`, the query interpretation, assembled next operations | `bash scripts/test-api.sh -k search_surface` | none¹ | ✅ shipped 2026-09-11 |
| **S2** | Keyword filters (`require_phrases` / `exclude_phrases`) through the one exact-match path, with the exclusion disclosed | `bash scripts/test-api.sh -k keyword` | none¹ | ✅ shipped 2026-09-11 |
| **S3** | The operator's view of it: the console's Search tab, and the document store on a host directory a person can `ls` | `bash scripts/stack.sh up` then browse `http://localhost:8055/console` → **Search** | none | ✅ shipped 2026-09-11 |
| **S4** | The **supported** operational surface: `vsir search` on the CLI (CR1 §4.4, §15 Factor XII) | `vsir search "safety output" --doc SICK-DETECTOR-BOX --require "safety output"` | none¹ | ⬜ not built |
| **S5** | The consumer's proof: a Playwright replay spec over the Search tab, and the surface measured rather than asserted | `bash scripts/test-e2e.sh` and `vsir eval search` | none | ⬜ not built |

¹ **"none" means no vision call.** A text query still embeds through the embedding model, exactly
as every `skim_*` rung does — see D-S10. There is no release in which `/search` is free of a
network call to a model provider, and calling it "free" without that qualifier is how a cost model
ends up wrong.

---

## 1. Overview

### 1.1 The guarantee — inherited whole from CR1 §1.1

> **No failure may present itself as a correct answer.**

This surface is the one place in the service where that guarantee is *delegated*: `/search` hands
a consuming system the data and lets it reason. Everything normative below is a consequence of
that. A consumer cannot inherit a guarantee it cannot see, so every row states how far its own
text may be believed, every empty result states which kind of empty it is, and every code arrives
labelled a claim.

### 1.2 The one rule for this surface

> **Data out, never an answer. `POST /ask` is the only surface in this service that may answer.**

`/search` calls no vision model, composes no prose, and makes no judgement about whether the rows
it returns answer anything. Asking for `include: ["text"]` does not make it a `read`: nothing is
interpreted and nothing is billed.

### 1.3 What this CR builds

One free HTTP call that returns **ranked pages with their content** for a consumer that will do
its own reasoning — the non-agentic counterpart to CR1's eight-rung ladder. The ladder charges a
caller one inference turn per rung, which is the right trade for an agent that is *deciding* and
pure waste for a system that has already decided it will reason for itself.

**It is not:** a ninth tool (D-S1), a second retrieval implementation (D-S3), a ranking with
scores (D-S2), or an answer surface of any kind (§1.2).

---

## 2. Scope

### 2.1 In scope

- `POST /search` — the request (§4.1), the response (§4.2), the bounds and their typed codes (§4.3).
- `require_phrases` / `exclude_phrases` as **branch** filters through `core/exact.exact_filter`,
  and the disclosure of what an unreadable page costs them (§4.4).
- `Candidates` gaining `branch_must` / `branch_must_not` — the one change to shared retrieval code.
- The console's **Search** tab: a purpose-built form, not a generated one (§8 S3, FS12).
- The document store as a **host directory** (`VSIR_DOCUMENTS_DIR`) rather than a named volume,
  and `stack.sh down --wipe` emptying it with the index (D-S9, FS13).
- `vsir search` on the CLI (S4) and the e2e/evaluation proof (S5) — **not built**.

### 2.2 Out of scope

| Out | Why |
|---|---|
| A ninth tool, or `/search` on MCP | D-S1 — the eight are *moves*; this is a knob, and an agent choosing among nine is choosing worse |
| Any score, threshold or magnitude in the response | D-S2, CR1 §7.6, and the conformance grep that fails the build on a field named `score` |
| Answer composition, summarisation, re-ranking by a model | §1.2 — `POST /ask` owns that, alone |
| A second fusion, a second scope filter, a second absence rule | D-S3 — `/search` and `skim_pages` must not be able to disagree |
| Server-held scope, sessions, cursors backed by state | CR1 §7.5, §15 Factor VI — `offset` pages a deterministic ordering, it does not resume a session |
| OCR, or any repair of an unreadable page | disclosed through `text_trust` and `not_searchable`, never patched |
| The React operator console (`frontend/`) | it is M7's console and it does not consume this surface; S5 covers only the e2e proof over the tab that does |

### 2.3 Where this CR touches CR1 (normative)

| # | CR1 says | This CR says | Why |
|---|---|---|---|
| **X1** | §7.2 fixes the agent's surface at **eight tools** | **Unchanged — eight.** `/search` is off the tool table, absent from MCP, and has no `ToolSpec` row | it is not a move an agent chooses between; see D-S1. `test_mcp_resources.py` still asserts eight |
| **X2** | §7.1's six-value status enum belongs to the two tool envelope families | **`/search` has a third envelope shape and the same enum**, computed by the same `lookup.absence()` the three `skim_*` rungs call | a second opinion about what an empty result means would drift from the first, and the drift would be invisible. `test_search_surface.py::test_the_absence_rule_is_the_one_the_rungs_use` pins the agreement |
| **X3** | **P2** — *cheap to triage, expensive to consume* (CR1 §7.1; plan2 `AGENTIC-RETRIEVAL` §P2) — keeps page text **off** a triage row, so an agent cannot answer from a search result instead of choosing a page and paying for it | **`/search` serves page text** under `include`, capped by `text_chars` | P2's argument is about an agent that might skip the paid step. A caller on this path has declared it is doing its own reasoning; withholding the text would not make it safer, it would make it call `fetch` twenty-five times for the same bytes. The bound that remains is **size, not trust** |
| **X4** | §7.4's audit line covers `read` and `fetch` — the two tools that move bytes or money | **`/search` writes no audit line**, exactly as the three `skim_*` rungs write none | widening `AUDITED_TOOLS` is a CR1 decision and this CR does not make it. Disclosed here so nobody reads the absence of a line as an oversight — see OQ-S3 |
| **X5** | §4.4: **the `vsir` CLI is the only supported operational surface** (§15 Factor XII) | **Currently violated by this surface** — `/search` is reachable over HTTP and from the console and **from no `vsir` subcommand** | stated as a defect rather than an exception. S4 (U037) closes it; until it does, an operator's only supported path to the flat surface is `curl` |
| **X6** | §6.7: a retired revision stays in the index and is still fetchable | **`/search` reports `found_only_in_superseded`** through `envelope.SupersededIn` and `lookup.absence(..., superseded=)` | those three came from U025's revision work on a parallel branch, and `/search` did not build them. This CR **depends on** them and claims none of them |

### 2.4 This spec is retrospective, and says so

The implementation landed first, in one commit, on a branch, with **no CR describing it**. That is
the defect this CR exists to close, and pretending otherwise would make the document less useful
than the code it describes.

So every normative statement below carries one of two marks:

- **as-built** — it is true of `backend/vsir/serve/retrieval.py` today and a named test asserts it.
  Changing it is a breaking change to a published contract.
- **required** — it is not built. It is a gate on S4 or S5 and nothing in the repository asserts it.

A reader who needs to know which parts of this document are evidence and which are intent should
read those marks and nothing else. §7 lists what the 56 shipped tests actually cover, and — more
usefully — what they do not.

---

## 3. Closed decisions

| # | Decision | Consequence if reversed |
|---|---|---|
| **D-S1** | **Not a ninth tool.** `/search` is off the tool table, absent from MCP, has no `ToolSpec` row and is not dispatched through `dispatch` | an agent offered nine moves where one is *"the same search, with the lexical branch off"* is being offered a knob. §7.2's eight stay eight, and `test_mcp_resources.py` fails if they do not |
| **D-S2** | **No score. Ordinals only.** `rank` is a 1-based position; `surface_ranks` publishes each branch's own position; `best_rank` the best of them. `_total()`'s RRF magnitude stays private in `skim.py` | a magnitude invites a threshold, a threshold turns *"ranked ninth"* into *"no results"*, and a fabricated absence is the one failure this system is built to make impossible. A field named `score` fails `test_conformance.py::test_no_field_named_score_in_any_model` |
| **D-S3** | **The same retrieval.** `_candidates()` is called directly, with the same `weights`, `k`, scope filter and absence rule the three `skim_*` rungs use | if `/search` ranked differently from `skim_pages`, one of the two would be lying about what the index does — and a tuning surface whose results differ from production tunes nothing |
| **D-S4** | **`include` omitted returns all six parts; `[]` is an explicit none; every unrequested field is `null`** | `text: ""` means the extraction is empty and `text: null` means you did not ask. One falsy default for both is how a consumer concludes a scanned page is blank |
| **D-S5** | **Keyword filters reach the branch filter only**, never the scope denominator (`branch_must` / `branch_must_not`, distinct from `extra_must`) | a content filter that matched nothing has *searched* the scope. Routing it through the denominator reported that as `out_of_scope`, which sends the caller to widen a scope that was never the problem |
| **D-S6** | **Content is served here though a `skim_*` row withholds it** | X3. The bound that remains is size (`text_chars`), stated per row as `text_truncated` |
| **D-S7** | **Actions are assembled, not described.** Each row carries `open_page_image`, `fetch_material`, `check_codes`, optionally `expand_section`, and `comprehend` — arguments already built, `spends` true on exactly one | a `page_id` carries `@` and `#`; a consumer building its own URL eventually encodes one wrong and gets a request that addresses nothing and **looks like an empty result** |
| **D-S8** | **The body is validated in the handler, not by FastAPI** | §7.3's bounds carry their own codes — `unknown_branch`, `offset_out_of_range`, `page_range_inverted` — and a `422` with a JSON pointer is not one |
| **D-S9** | **The document store is a host directory** (`VSIR_DOCUMENTS_DIR`, default `./var/documents`), git-ignored; `stack.sh down --wipe` empties it in the same breath as it drops the index | on macOS and Windows a named volume lives inside the Docker VM: *"where did my document go?"* had no answer a person could `ls`, and replacing a corrupt PDF meant `docker cp`. A wipe that dropped the index and left the documents would leave a store describing a corpus that is no longer indexed |
| **D-S10** | **"Free" means no vision call.** A text query embeds through the embedding model on every request, exactly as `skim_pages` does; `read` remains the only operation that bills a *vision* call | a cost model that reads "free" as "no provider call" is wrong per request at corpus scale, and `503 vlm_unavailable` on a `/search` with no credential is otherwise inexplicable |
| **D-S11** | **Bounds are refused, never clamped** — `limit`, `offset`, `text_chars`, `k`, phrase counts, image counts | a caller handed 25 of the 100 rows it asked for believes it has seen 100. Silent truncation is the same failure as a fabricated absence, one level down |

---

## 4. The surface contract

### 4.1 Request — `SearchRequest` (as-built)

`extra="forbid"`. A misspelt parameter names itself in a `400`; it is never ignored.

| Field | Type | Default | Bound / code |
|---|---|---|---|
| `query` | str | `""` | required unless an image is given → `query_required` |
| `image` | str (b64) | `""` | with `images` → `image_and_images` |
| `images` | str[] | `[]` | ≤ 4 → `too_many_query_images` |
| `scope` | object | `{}` | keys ⊆ `INDEXED` minus the two text surfaces → `filter_unknown_key`; `is_current: true` injected unless overridden |
| `exclude_scope` | object | `{}` | same vocabulary, negated → `filter_unknown_key` |
| `exclude` | str[] | `[]` | page ids to suppress |
| `page_from` / `page_to` | int? | `null` | inverted → `page_range_inverted` |
| `require_phrases` | str[] | `[]` | ≤ 10 → `too_many_phrase_terms`; empty member → `phrase_empty` |
| `exclude_phrases` | str[] | `[]` | as above |
| `include` | str[]? | `null` = all six | ⊆ `summary·text·topics·codes·labels·sections` → `unknown_content_part` |
| `text_chars` | int | 2000 | 1…20000 → `text_chars_out_of_range` |
| `limit` | int | 10 | 1…25 → `limit_out_of_range` |
| `offset` | int | 0 | 0…200 → `offset_out_of_range` |
| `weights` | object? | release defaults | names ⊆ `dense·lexical·captions` → `unknown_branch`; negative → `weight_negative`; all zero → `no_branch_enabled` |
| `k` | int | `RRF_K` | 1…1000 → `rrf_k_out_of_range` |

**The filter vocabulary excludes `text` and `vlm_codes` deliberately** — the two text surfaces are
reachable through `query` and through `lookup`, never as a facet.

### 4.2 Response — `SearchResult` (as-built)

**Read `status` first.** It is the field to branch on, and it is one of five:

| `status` | What it means | The consumer's next move |
|---|---|---|
| `ok` | rows were ranked | use them |
| `not_found` | the scope was searched and nothing matched | safe to abstain — **after** checking `query_interpretation.identifiers`, because a typo in a lifted identifier empties the result |
| `not_searchable` | pages were in scope and **none had usable text** | escalate to vision. **Do not** conclude the content is absent |
| `out_of_scope` | no page matched the filters at all | the corpus was never really asked — widen `scope`, drop `exclude_scope`, check the page range |
| `found_only_in_superseded` | nothing current matched; a retired revision has it | re-ask with that `revision` (named in `superseded`, with no page content) |

`error` never appears in this body: a failure is a typed HTTP refusal, because an outage rendered
as an absence becomes the caller's fabricated confidence.

**Per row:** `rank`, `page_id`, `doc_id`, `revision`, `page_no`, `printed_page_no`, `page_kind`,
`why`, `surface_ranks`, `best_rank`, `text_trust`, `text_usable`, `has_text`, `grounded_rate`,
`section_id`, `image` (a reference, never bytes), `image_url`, `next`, `actions`, and `content`
when `include` asked for it.

- **`text_usable` is the single flag to gate on.** True for `ok` and `degraded`; false for
  `untrusted` and `no_text`. **Not the same as `has_text`** — an `untrusted` page *has* text that
  may not be believed.
- **`has_text` is derived from `text_trust`**, not read from the payload. `ROW_PAYLOAD` does not
  project `has_text`, and reading it there returned `false` for every row.
- A stored `text_trust` outside the four values is reported as `no_text` — the conservative
  direction. An unknown state is never rendered as trust.
- **`content.codes` are claims; `content.codes_in_text` is the subset the page's own text backs**,
  lowercased and whitespace-collapsed per CR1 §6.8. **Compare the two case-insensitively** — an
  exact comparison finds nothing and reads as *"the text backs none of these codes"*.

**Counts, and what separates them:** `total` (pages the branches were allowed to rank),
`returned`, `offset`, `available` (the end of the pageable list — a property of the candidate
pool, not of the corpus), `pages_searched` (the scope denominator; `0` is exactly `out_of_scope`),
`searchable_pages` (`0` with `pages_searched > 0` is exactly `not_searchable`), `pages_without_text`.

**`query_interpretation` explains the row set** — the identifiers lifted out and required as an
exact phrase, `embedded_text` left for the vector, `branches_run`, and every branch that did not
run **with its reason** (`weighted_zero`, `nothing_left_to_embed`, `no_query_text`).

### 4.3 Refusals (as-built)

Every bound above is a `400` naming itself, never a clamp (D-S11). Beyond them:
`invalid_json`, `invalid_request` (with a per-field `problems` list), `401` unauthenticated,
`503 vlm_unavailable` when the embedding backend cannot be built — an outage, never an empty
result — and `500` for anything unmapped.

### 4.4 Keyword filters and the disclosure they owe (as-built)

`require_phrases` and `exclude_phrases` are **filters, not query terms**: a phrase here is a hard
requirement, matched as an **ordered phrase** through `core/exact.exact_filter`, so `variants()`
applies (`"SF 1.1A"` finds `"SF1.1A"`) and there is no second matcher in `serve/` (CR1 I3, F1).

The asymmetry is deliberate and both halves are the safe direction:

- a page with **no readable text** carries nothing for a phrase to match, so `require_phrases`
  **excludes** it — silently, because it was never a candidate;
- the same page is **kept** by `exclude_phrases`, because it cannot be shown to carry the phrase.

**The disclosure is therefore mandatory**: `pages_searched`, `searchable_pages` and
`pages_without_text` are on every response, and a large gap between the first two is the reason an
empty keyword result must not be read as *"the corpus does not contain this"*. This is the same
disclosure CR1 §12.6's evaluation depends on, applied to a filter that can silently remove half a
scanned binder.

---

## 5. Invariants (each with a test)

| # | Invariant | Enforced by |
|---|---|---|
| **I-S1** | `/search` and `skim_pages` never disagree about what an empty result means | one `lookup.absence()`; `test_the_absence_rule_is_the_one_the_rungs_use` |
| **I-S2** | No response field named `score`, anywhere | `test_conformance.py::test_no_field_named_score_in_any_model`; `test_rank_is_a_one_based_ordinal_and_no_row_carries_a_score` |
| **I-S3** | One exact-match code path — keyword filters build no `MatchPhrase` of their own | `phrase_conditions()` delegates to `exact_filter`; `test_the_keyword_filters_use_the_one_exact_match_code_path` |
| **I-S4** | Asking for content does not change the ranking | `test_asking_for_content_does_not_change_the_ranking` |
| **I-S5** | An unrequested part is `null`; a requested empty one is not | `test_an_unrequested_part_is_null_and_a_requested_empty_one_is_not` |
| **I-S6** | Every row's assembled `actions` are accepted verbatim by the surface they target, and exactly one has `spends: true` | `test_the_assembled_arguments_are_never_refused_as_malformed`, `test_the_assembled_fetch_call_actually_works`, `test_the_expand_scope_can_be_posted_straight_back` |
| **I-S7** | Every bound, and the filter vocabulary, is in the published OpenAPI document | `test_every_bound_and_vocabulary_is_in_the_published_schema` |
| **I-S8** | A required phrase can never match a page whose text could not be read | `test_a_required_phrase_can_never_reach_a_page_with_no_readable_text` |

---

## 6. Failure catalogue — **this table is the definition of done**

| # | Failure | Guard | Closed by |
|---|---|---|---|
| **FS1** | An empty `rows` read as *"not in the documents"* when nobody could read the pages | the five-value `status`, from the rungs' own rule | U033 · `test_status_is_the_field_to_branch_on_and_never_error` |
| **FS2** | A consumer composes from `content.text` without checking trust, and cites a wrong part number | `text_usable` on every row, and `text_trust` beside it | U033 · `test_text_usable_is_the_gate_and_is_not_has_text` |
| **FS3** | A keyword filter silently removes every scanned page and the result reads as absence | the three disclosure counts on every response | U034 · `test_a_required_phrase_can_never_reach_a_page_with_no_readable_text` |
| **FS4** | A hand-built URL mis-encodes `@` or `#` and the 404 looks like an empty result | assembled `actions` | U033 · `test_the_assembled_fetch_call_actually_works` |
| **FS5** | A misspelt parameter is ignored and the caller is told the corpus lacks what it asked for | `extra="forbid"` + named refusals | U033 · `test_an_unknown_content_part_is_refused_and_not_ignored` |
| **FS6** | Truncated page text is reasoned over as if whole | `text_truncated` + `text_chars_total` per row | U033 · `test_text_is_capped_and_says_when_it_truncated` |
| **FS7** | An offset past the candidate pool is read as corpus exhaustion | `available` on every response; `offset_out_of_range` past 200 | U033 · `test_available_reports_the_end_of_the_pageable_list` |
| **FS8** | An unknown key in `exclude_scope` is dropped, returning a **larger** set that looks filtered | `reject_unknown_keys` on the negation too | U033 · `test_an_unknown_key_in_the_negation_is_refused` |
| **FS9** | A model-claimed code is cited as verified | `codes` vs `codes_in_text`, and `check_codes` on every row | U033 · `test_codes_are_claims_and_codes_in_text_is_the_backed_subset_of_them` |
| **FS10** | `has_text` read off an unprojected payload field, reporting `false` for every row | derived from `text_trust` | U033 · `test_a_row_carrying_text_states_the_trust_that_qualifies_it` |
| **FS11** | An unmatched content filter reported as `out_of_scope`, sending the caller to widen a scope that was never the problem | `branch_must` / `branch_must_not`, separate from the denominator | U034 · `test_an_unmatched_keyword_filter_is_not_found_and_not_out_of_scope` |
| **FS12** | The console's parameter list falls behind `retrieval.PARTS` | `test_console.py` pins the one list that is written out by hand | U036 |
| **FS13** | An operator cannot find, replace or back up an ingested PDF | the host directory, and `stack.sh down --wipe` emptying it with the index | U035 |
| **FS14** | *(open)* An operator reaches the flat surface only through `curl`, so the supported surface (CR1 §4.4) does not cover it | — | **U037, not built** |
| **FS15** | *(open)* The surface a consuming system uses has no browser-level regression proof | — | **U038, not built** |

---

## 7. Test strategy

### 7.1 What is asserted today (as-built)

```
backend/tests/api/test_search_surface.py   56 passed   (verified 2026-09-11)
backend/tests/api/test_console.py          38 passed   (18 of them added by U036)
```

Grouped by what they pin: ordinals and the absent score · content parts and their null discipline ·
trust and truncation · paging determinism and `available` · page ranges and negations · every
refusal code · the status rule shared with the rungs · the query interpretation and skipped
branches · typed section rows · the published schema and its four named examples · row identity,
thumbnails and `next` · assembled actions actually working · and eleven tests over the keyword
filters, including phrase semantics, `variants()` spellings, and the unreadable-page exclusion.

### 7.2 What is **not** asserted — read this before trusting the suite

- **No e2e.** `e2e/` has no spec that opens the Search tab. The 38 console tests are Python
  assertions over the served HTML, not a browser driving the form (FS15, U038).
- **No live-path coverage.** Every test runs against the stub backend. CR1's U028 and U032 are the
  standing evidence that a green suite says nothing about a real provider call, and `/search`
  embeds a query on the live path (D-S10) exactly where those defects lived.
- **No measurement.** Nothing states how often a keyword filter's unreadable-page exclusion changes
  an answer on the real corpus, and nothing compares `/search`'s ranking to the evaluation sets
  (U039, and OQ-1 gates it).
- **No React client.** `frontend/src/api/types.ts` gained `SupersededIn` and nothing else; the M7
  console does not call `/search`.

### 7.3 Required (S4/S5)

- `vsir search` covered at L0 for argument mapping and at L2 against a seeded collection, asserting
  the CLI's output and `POST /search`'s body describe the same result.
- A Playwright replay spec: a typed status rendered with its next action, a row expanded, an
  assembled operation followed, and the scope builder refusing a facet the server would refuse.
- `vsir eval search`: `/search` and `skim_pages` agreeing on the evaluation sets, and the keyword
  filters' exclusion reported as a rate rather than a property.

---

## 8. Milestones

### S1 · The flat surface — *spend: none¹* — ✅ shipped
- **Deliverable:** `serve/retrieval.py`, `POST /search`, the published schema with four named examples.
- **Acceptance:** the five-value `status` computed by `lookup.absence()`; no field named `score`;
  `include` omitted returns six parts and `[]` returns none; every bound refused with its own code;
  every row's assembled actions accepted verbatim by their targets; `test_search_surface.py` green.

### S2 · Keyword filters — *spend: none¹* — ✅ shipped
- **Deliverable:** `require_phrases` / `exclude_phrases`, `branch_must` / `branch_must_not` on `_candidates`.
- **Acceptance:** phrase matching with `variants()` through `exact_filter` and no second matcher in
  `serve/`; an unmatched filter is `not_found` and never `out_of_scope`; a required phrase never
  reaches an unreadable page, and the response discloses how many pages that removed.

### S3 · The operator's view, and the store on the host — *spend: none* — ✅ shipped
- **Deliverable:** the console's Search tab; `VSIR_DOCUMENTS_DIR` bind mount; `stack.sh down --wipe`.
- **Acceptance:** the tab renders the status with its next action, the interpretation panel,
  per-row thumbnails fetched with the bearer token an `<img>` cannot carry, and a scope builder
  whose keys come from `/openapi.json`; `PARTS` pinned against `retrieval.PARTS`; an ingested PDF
  is visible on the host and a `--wipe` leaves neither index nor store behind.

### S4 · `vsir search` — *spend: none¹* — ⬜ not built
- **Deliverable:** the subcommand, its arguments mapped one-to-one onto `SearchRequest`, and the
  typed status printed rather than an empty table.
- **Acceptance:** CR1 §4.4 holds again — every operation this CR added is expressible as a `vsir`
  subcommand; the CLI and the HTTP body return the same rows for the same arguments.

### S5 · The consumer's proof — *spend: none* — ⬜ not built
- **Deliverable:** `e2e/tests/search.spec.ts`; `vsir eval search`.
- **Acceptance:** the browser suite drives the tab in replay mode and fails on a status rendered
  without its next action; the evaluation reports agreement with `skim_pages` and the keyword
  filters' exclusion rate, skipping with a named reason where ground truth is absent — never
  silently passing.

---

## 9. Top-level acceptance criteria

| # | Criterion | State |
|---|---|---|
| **AC-S01** | One free call returns ranked pages **with their content**, and calls no vision model | ✅ |
| **AC-S02** | An empty result is one of four typed absences, agreeing with `skim_pages` | ✅ |
| **AC-S03** | Every row states `text_trust` and `text_usable`, and `text_usable ≠ has_text` | ✅ |
| **AC-S04** | No magnitude anywhere — ordinals only, and the build fails on a field named `score` | ✅ |
| **AC-S05** | Keyword filters run through the one exact path and disclose the pages they could not reach | ✅ |
| **AC-S06** | Every bound is refused with its own code; no clamp, no `422` | ✅ |
| **AC-S07** | Every row's next operations are assembled and accepted verbatim; exactly one spends | ✅ |
| **AC-S08** | The whole request and response are in `/openapi.json` with four named examples | ✅ |
| **AC-S09** | The document store is visible on the host, and a wipe takes index and store together | ✅ |
| **AC-S10** | Every operation this CR adds is expressible as a `vsir` subcommand (CR1 §4.4) | ⬜ U037 |
| **AC-S11** | The surface has browser-level regression proof and a measured disclosure rate | ⬜ U038, U039 |

---

## 10. Non-functional requirements

- **Determinism.** The fused ordering is stable across calls, so `offset` pages a ranking rather
  than re-running a search (CR1 §16).
- **Statelessness.** No session, no server-held scope; `effective_scope` is echoed back (§15 Factor VI).
- **Bounded work per request.** Branch depth 50 per branch, `limit` ≤ 25, one extra bounded
  `retrieve` for `text` over the rows actually returned — never a scan.
- **One writable path.** This CR adds no state: the document store is ingestion's, and `/search`
  writes nothing.

---

## 11. Risks accepted

- **A consumer can still ignore the flags.** Everything here is disclosure; nothing prevents a
  caller from concatenating `content.text` across rows and calling it an answer. The mitigation is
  that the flag is on every row and named in the schema, not that the surface withholds data.
- **`text` on twenty-five rows is a large response.** Bounded by `text_chars` (default 2000) and
  stated per row, not by refusing the request.
- **The embedding call is on the query path.** A provider outage makes `/search` a `503` rather
  than a degraded lexical-only search. Typed, not silent — but it is an availability coupling the
  ladder's free rungs share (D-S10).

---

## 12. Open questions

| # | Question | Blocks |
|---|---|---|
| **OQ-S1** | Should `/search` degrade to a lexical-only search when the embedder is unavailable, instead of `503`? It would be a different ranking answered as if it were the same one — which is why it does not today | nothing; revisit with the runner's degradation policy (CR1 §11.3) |
| **OQ-S2** | `MAX_OFFSET` is 200 while three branches at depth 50 can fuse at most 150 distinct pages, so the last stretch of the allowed range is always empty. Lower the bound, or leave `available` to report the edge? | nothing — `available` is correct either way |
| **OQ-S3** | Should the flat surface emit an audit line? It is unaudited like the `skim_*` rungs, but it is the surface an **external system** consumes, which is a different operational question (X4) | a decision belongs in CR1 §7.4, not here |
| **OQ-S4** | The keyword filters' real-corpus exclusion rate is unmeasured, and `data/source/TC1E-SF.pdf` is still absent (CR1 OQ-1) | U039 |

---

**END OF SPECIFICATION**
