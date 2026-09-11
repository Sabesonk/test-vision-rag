# POC Part B — Vision Segmentation, Index & Retrieval

Split from [`ingestion_and_retrieval.md`](../../solution/Dataset%20Ingestion%20&%20Retrieval/ingestion_and_retrieval.md) (the master solution document). Built **separately** from Part A — [`../correlation_graph_and_traversal_engine/correlation_graph_and_traversal.md`](../correlation_graph_and_traversal_engine/correlation_graph_and_traversal.md) — then combined through the integration contract in §5.

**Design decision (supersedes master §4).** Retrieval is agentic: a planning agent in **Part A** loops over tools until its evidence is sufficient. Part B is the **document service** under that agent: it segments every PDF, indexes each document as its own scope, and exposes two tools — `search` within a scope and `read` (directed vision RAG over segments). Part B answers no user queries itself. The master document is synced to this once the POC validates it.

---

## 1. POC scope

- **In:** all **PDF sources** — 5,505 pages: vendor datasheets 3,279, Use & Maintenance 1,546, diagrams E/P/L 680. Vision segmentation, per-language summaries + keywords, doc-scoped hybrid indexes with exact identifier labels, the `search` and `read` tools, ingest-side verification, component-level evaluation.
- **Out:** the retrieval agent, its loop and answer composition — **Part A** owns those. Deferred with their sections: spare-parts capture images (764 units, master §3.3) and everything ERP (master §3.2), including the spare-parts callout calibration set.
- **Order of work:** the evaluation sets in §6 run **before** scale-out to the full 5,505 pages.

## 2. Vision segmentation (Gemini)

Applies to **all** PDF sources, IMA-authored and vendor alike. One pipeline, no per-format parsers, no coordinate rules to break when IMA revises a template.

```
PDF → Gemini vision segmentation → A-Seg1.pdf, A-Seg2.pdf, …
        ↳ per segment: summary + semantic keywords + lexical keywords (Gemini)
        ↳ summaries + keywords + verified identifiers → that document's index
        ↳ segment exports (segment_id, page_range, verified_identifiers) to Part A
```

**Segment boundaries.** A segment is one semantic unit that keeps a figure with the text that references it — the case text extraction cannot serve. On the Rittal connection-accessories page, three digit roles sit at `x=36` (placed images), `x=43` (figure labels), `x=186` (table-row callouts); text extraction flattens all three into digit soup. Vision keeps them together. Figure callout numbers stay **local to the segment** — they are never identifiers.

| Source | Volume | Expected segment granularity |
|---|---|---|
| Electrical / pneumatic / lubrication | 680 pp | 1 per sheet — the sheet has its own title block and denomination |
| Manual, alarm chapter | 522 pp | 1 per alarm record (~494) |
| Manual, other chapters | ~900 pp | 1 per section; spread-level where a figure serves facing text |
| Component / I/O / cable registers | ~268 pp | 1 per page; rows are also extracted deterministically from the text layer as Part A's graph build source (component registers, PLC I/O card tables — layout-mode extraction, P/L registers) |
| Vendor datasheets | 192 files · 3,279 pp | 1 per semantic block; ≤6pp files (105 of 185) usually one segment |
| Lifting & safety attachments | 106 pp | 1 per safety function in the SF list (`TC1E Schemi funzioni di sicurezza`, 55 pp, 122 SF ids); 1 per procedure/section in the lifting and periodic-checks docs |
| Scanned attachments | 2 pp | whole page — vision is the only path |

**Two non-negotiables on identifier-dense pages.**

1. **Keep the text layer as a verification allowlist.** Any code, tag, sheet reference or alarm number a vision model emits **must appear in that segment's extracted text**, or it is flagged and withheld. This is what makes vision-first safe where a one-character error names a real different part.
2. **Per-language summaries.** IT and EN are interleaved on the same manual page. One blended summary poisons the embedding — emit one per language, tagged.

**Reproducibility.** Pin `model_version` + `prompt_version` + `dpi` on every segment record and keep `segment_id`s stable. Re-ingest only on content hash change.

**Safety flagging at ingest.** A segment carrying a safety code or a PL-rated safety function is flagged; the flag is exported to Part A and surfaced through `describe()`.

## 3. Indexes — one scope per document

- **The manual is one index scope. Each vendor datasheet is its own. Each diagram document its own.** Search always runs *inside* a scope; there is no corpus-wide similarity search. Each index scope corresponds 1:1 to a **Document** content node in Part A's graph.
- One entry per segment per language: summary + keywords, hybrid lexical + semantic, lexical weighted **≥** dense — the answer-bearing tokens are identifiers and named functions, not prose.
- **Verified identifiers are stored as exact-match keyword fields.** This is the fence against the measured failure mode: ~35% of every alarm page is boilerplate and all ~494 records are near-identical, so similarity alone drowns keyed lookups. "Alarm 152" must hit the label `alarm:152`, not a nearest neighbour.

## 4. Retrieval tools — search & directed read

Part B's retrieval is **within-document service**, called by Part A's agent; it composes no user-facing answers.

**`search(scope, query, lang?)`** — hybrid search inside one document scope. Identifier tokens in the query hit the exact-match label fields first; summaries rank the rest. Returns segment candidates with scores, labels and page ranges.

**`read(segment_ids, question)`** — directed vision RAG: Gemini reads the segment PDFs against the caller's question. Returns:

- the extract answering the question, with **page provenance** per claim;
- every identifier encountered, each flagged **text-layer-backed or not** (the caller's grounding evidence);
- **read-from-image labels** on claims no text layer can back (circuit topology, contact state as drawn);
- an honest empty result when the segments don't answer the question — `read()` never pads.

Fidelity is chosen per segment class (schematic sheets and plates render high-fidelity; prose pages flat), and repeated reads of the same segment at the same fidelity are cache hits.

### 4a. As built: the tool ladder, and a flat search surface for a non-agentic consumer

Implementation note, recorded here because it diverges from §4 above in two ways a reader of this
document would otherwise get wrong.

**The service exposes eight tools, not two.** §4's `search` and `read` became a narrowing ladder,
because an agent chooses far more reliably between named *moves* than between values of a
parameter: `skim_documents` → `skim_sections` → `skim_pages` (which binder / chapter / page),
`lookup` (exact printed code), `resolve` (a printed cross-reference → an addressable page),
`verify` (is this code actually on this page), `fetch` (the page's pixels and text, free), and
`read` — **the only one that bills a vision call**. Seven of the eight are free, so an agent
arrives at the paid step already knowing which pages it wants.

**`search` returns no scores.** §4 says *"segment candidates with scores"*; the built surface
returns an **ordinal** `rank` and nothing else, and a build-time check fails on a response field
named `score`. The reason is the failure mode: a magnitude invites a threshold, a threshold turns
*"ranked ninth"* into *"no results"*, and a fabricated absence is the one outcome this corpus
cannot afford. What a caller gets instead is `why` — which of the three retrieval branches found
the row (`dense` = the page's image+text vector, `lexical` = its extracted text, `captions` = its
generated summary) — plus each branch's own position, so a ranking is explicable without being
scored.

**`POST /search` — a flat surface for a system that is not the Part A agent.** The ladder costs
the caller one inference turn per rung, which is the right trade for an agent that is *deciding*
and pure waste for a consumer that will do its own reasoning. So one free call returns ranked
pages **with their content** — summary, extracted text, topics, model-claimed codes, printed
labels, sections — plus the page raster as a reference and, per row, the next operations with
their arguments already assembled. It calls no model and never composes an answer; `POST /ask` is
the only surface that may.

Three properties of that surface matter to the contract in §5:

- **An empty result is typed, never an empty list.** `status` is one of `ok`, `not_found`,
  `not_searchable` (pages were in scope but none had readable text — escalate to vision, do *not*
  conclude the content is absent), `out_of_scope` (the filters matched nothing, so the corpus was
  never really asked) or `found_only_in_superseded` (a retired revision has it). Four different
  next actions that an empty list collapses into one wrong one.
- **Every row states how far its text may be believed.** `text_trust` is `ok` / `degraded` /
  `untrusted` / `no_text`, and `text_usable` is the single flag to gate on — not the same as
  `has_text`, because an `untrusted` page *has* text that may not be trusted. An empty extraction
  on a scanned page means nobody could read the page, not that the page is blank.
- **Codes are claims, not verdicts.** A model-reported code arrives beside the subset the page's
  own text layer backs. `verify` is what settles one, and it is free.

Keyword filters (`require_phrases` / `exclude_phrases`) require or forbid a phrase being printed
on the page, through the same exact-match path as `lookup`. They can only ever match a page whose
text could be read, so the response reports how many pages in scope that excluded — the same
disclosure §6's evaluation depends on.

## 5. Standalone operation & integration contract

**Standalone:** Part B demos `search` and `read` with direct scripted calls over the ingested corpus — no agent required.

**Contract (identical text in both POC docs):**
- Part B mints stable `segment_id`s (doc_id + sequence, pinned to `model_version` + `prompt_version` + `dpi`; unchanged unless the content hash changes) and delivers per segment: `page_range` + `verified_identifiers[]` (text-layer allowlisted). These double as exact-match index labels and as the graph's content-attachment evidence.
- Part B exposes the document services as tools: `search(scope, query, lang?)` and `read(segment_ids, question)`; `read()` output carries page provenance and flags, per returned identifier, whether it is text-layer-backed.
- Part A delivers the graph and dictionary behind `resolve` / `describe` / `neighbors` plus the versioned schema card, and builds the **retrieval agent** that plans over all five tools.
- Until integration: Part A's agent runs against stub document services; Part B validates `search`/`read` with direct scripted calls — both parts demo standalone.
- Part B exports per-segment safety flags; `describe()` surfaces them; the agent's answer policy orders manufacturer procedures first on safety-flagged content.
- Each segment belongs to exactly one **Document** (content node) — one Part B index scope; IMA code → Document edges come from the CSV; all other entity→content attachment derives from verified identifier labels — **no per-class binding validation in the POC**.

## 6. Evaluation — the corpus is its own benchmark

Component-level, owned here (the end-to-end loop evals live in Part A §8 and run at integration):

| Set | Ground truth | Measures |
|---|---|---|
| Component register (E pp. 59–125) | 2,053 rows · 748 tags · 484 codes · 1,907/1,907 well-formed `SITO` | ingest code exactness, abstention correctness |
| Alarm catalogue | message numbers 0–539, ~494 records | record segmentation; `search` label hit: every number lands its record segment |
| Cross-references | 6,880 tokens, 99.97% resolvable | reference transcription in segment exports |

Report **code-exactness and abstention correctness** as hard gates; answer similarity alone is misleading for engineering. Where vision misses, the text-layer gate converts a silent error into a flagged one.

## 7. Risks accepted

- **Reproducibility.** Vision output varies across model versions; the register's 1,907/1,907 guarantee becomes a measured rate. Mitigated by version pinning and the evaluation sets, not eliminated.
- **Recurring cost.** ~5,505 pages per full ingest, and again on re-segmentation. Bounded by hash-based delta re-ingest and `read()` caching.
- **Allowlist gaps.** The text-layer gate cannot protect the 2 scanned attachment pages or the 7 zero-text vendor files — there is no allowlist to check against.
- **Circuit topology.** Read adequately by vision, but only ever labelled read-from-image.
