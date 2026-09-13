---
type: subsystem
title: Ingestion Pipeline
description: The eleven ordered steps that turn a PDF into indexed pages — identity, text probe, rasters, document facts, windows, extraction, derivation, stitching, embedding, indexing and publish — with each step's inputs, refusals, and whether it needs a store or can spend money.
tags: [ingestion, pipeline, pdf, extraction, text-layer, rasters, steps]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-04b6ef6d0488cd1cd6abc2fe
    resource: repo://backend/vsir/cli.py
  - id: openwiki-source-52848e8010ea3472eb7de90c
    resource: repo://backend/vsir/ingest/derive.py
  - id: openwiki-source-6c1e45e5527ebc9f0c17419c
    resource: repo://backend/vsir/ingest/manifest.py
  - id: openwiki-source-022f381bb65b8c85735aa114
    resource: repo://backend/vsir/ingest/probe.py
  - id: openwiki-source-5aea2d2911922a9bb1fc7f6b
    resource: repo://backend/vsir/ingest/render.py
  - id: openwiki-source-4dbd538b1f35bfa33f6f8f72
    resource: repo://backend/vsir/ingest/stitch.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Ingestion Pipeline

`vsir ingest` drives eleven named steps in order. `--until` stops after any of them, which is
what makes each step reviewable on its own.

```
01 manifest → 02 probe → 03 render → 04 facts → 05 window → 06 extract
→ 07 derive → 08 stitch → 09 embed → 10 index → 11 publish
```

| | Needs a store | Can spend |
|---|---|---|
| 01–03 | no (step 01 claims a run point when a store is available) | no |
| 04–06 | no | **yes** — the document-facts call and one call per window |
| 07–08 | no | no |
| 09 | **yes** — reads the embedding cache | **yes** — one call per page |
| 10–11 | **yes** | no |

Steps 01–08 are pure functions of the PDF and the model responses, which is what lets derivation
and stitching be asserted with no Qdrant at all. The three store-backed steps refuse with a named
store error rather than running without one — step 09 reads the embedding cache off the index,
step 10 writes to it, step 11 flips visibility, so running them blind would re-bill every vector
the index already holds.

A store-backed run **claims its run point at step 01**, before the first model call, so an
unreachable store is named before anything is spent and a run that dies mid-flight is a run that
exists. Resuming a run against a different document is refused by name: it would write this
document's pages under that run's id, and publish would then flip a set of points nobody meant.

## 01 · manifest — identity

Nothing is extracted, nothing costs money, and it is still the step that cannot be fixed later
without re-billing the document, because it decides **identity**: a wrong `doc_id` attaches
entities to the wrong node or mints a duplicate, and a wrong `revision` lets one revision's page
silently overwrite another's.

The rule is narrow and absolute: facets come from the **filename, the file's own metadata and the
uploader** — never from the content. There is no grammar in this module: no regex, no taxonomy, no
keyword list. A classifier here would be invisible, unversioned corpus knowledge sitting in front
of every later step. What the *model* thinks the document is arrives at step 04 as a cross-check,
and the operator's declaration wins where there is one.

Two failure modes are closed by shape rather than care. A facet that was not declared is recorded
as *not declared* rather than as its truthy default, so a later step can fill it without having to
distinguish "the operator said unknown" from "nobody said anything" — the previous implementation
threw away the model's classification because a dropdown defaulted to a truthy `"unknown"`.
Likewise the declared-flag on the revision is what makes "unread" distinguishable from "genuinely
read as 1.0" in the one report whose disagreement mints a duplicate document.

Document metadata lists are *cut* on a separator convention, never interpreted.

## 02 · probe — the text layer

This module is the **only writer of the `text` payload field**, and three properties follow:

- **Text always comes from the full page, never a crop.** There is no clip argument anywhere in
  it, and a conformance grep keeps the extraction call out of every other module so a second
  extractor cannot appear. A code near the foot of the sheet is in the text even when the raster
  a reader is looking at was cropped above it.
- **Extraction is unconditional.** The previous implementation guarded it on a document-level
  "has text layer" sample, and that one `else` destroys the text of every *mixed* document — a
  scanned cover over a born-digital body averages below the threshold on an eight-page sample, so
  dozens of extractable pages come back empty with nothing raising. Per-page extraction already
  returns an empty string for a page with no text layer, so the guard never saved anything it did
  not also cost.
- **`has_text` is per page**, and a page without text is `no_text` trust. The document-level
  sample decides nothing except what gets reported.

**There is no OCR, deliberately.** In this corpus the text layer is not a convenience, it is
*evidence* — its whole job is to answer "is this code really printed on this page?". An OCR layer
answers with a guess, and in a corpus of thousands of one-character-apart codes a misread would
"verify" a hallucinated one. A scanned page yielding nothing is worse in coverage and better in
truthfulness: it comes back as a typed not-searchable absence that the tools disclose.

The PDF library version is recorded on every page, because it is the single point of truth for
exact search and a version bump is a re-run of the crop and offset fixtures rather than a silent
change.

**The document is deposited into the document store here and nowhere else**, and the position is
the whole reason there is one writer: `doc_id` and `revision` are only authoritative after step 01
and the content hash only exists after step 02. Because the HTTP upload route runs this same
subcommand, an upload deposits through exactly this line — the failure it replaces was two code
paths for one operation, one of which silently did less than the whole job.

## 03 · render — rasters, in memory

The rendering is kept and the disk is deleted. The previous implementation rendered every page at
both dpi values unconditionally and wrote megabytes of PNGs before anything had been validated,
which produced a stale path on the record that made page reads fail for every page, and an
instance whose answers depended on files another instance did not have.

Two dpi values serve three uses: **150** is the raster that gets embedded; **220** is pinned and
shared by extraction (where the ordered page image hashes build the extraction cache key) and by
`read` (where the dpi is a key input a caller cannot change); and `fetch` plus the thumbnail tiers
render at six tiers that feed no key and are cache-only.

## 04–06 · facts, windows, extraction

The document-facts call is cached per document; the window ladder turns the document into page
ranges; extraction is one call per window and is where the money goes. These are covered in
[Windowing and VLM Extraction](vlm-extraction-and-windows.md).

## 07 · derive — the claim beside the evidence

Two streams have been running since step 02 and neither has seen the other: the PDF library has
each page's **text**, and the model has its **reading**. This step puts the claim next to the
evidence.

**The offset is the most dangerous line in the pipeline** — get it wrong and every page number,
page id, citation and summary shifts, and nothing else errors. The previous implementation
computed it correctly and then logged a warning and dropped the page when an index fell outside
the window, which is a silent one-page hole in a manual. Two independent checks run instead:

1. **structural** — the window returned exactly the indices it was given, decided by the same
   function step 06 uses so one function owns it;
2. **independent observation** — a model-read printed page number on a page that has text must be
   printed on *this* page; if it is printed on a neighbour's instead, that is the off-by-one
   signature, and the run bisects rather than emitting a record for a window whose pages it cannot
   place.

One observation is deliberately not enough to raise. The neighbour check reads the **whole
document**, so the predicate is invariant under bisection and a false positive would reach the
same verdict all the way down — one bare numeral would cost the document plus roughly eight paid
windows on the way. Measured across the real corpus, a single witness fires on 22 pages across 11
of the 98 documents that declare page labels, and every one is a false positive. What replaces it
is the argument stated exactly: a genuine shift moves every page of the window, so under a real
shift **no page can confirm its own label**. The check refuses on two witnesses, **or** on one
when nothing in the window confirms itself — which keeps sensitivity even for a window carrying
only one legible label.

**The allowlist gate is gone.** There is no identifier grammar, no classification, no keyword
list, and no merging of text-harvested identifiers into the model's. A code is findable because it
is *in* the page's `text`, which only the probe writes, and nothing the model says can put it
there. What survives of the gate's purpose is a number — the grounded rate — plus the list of
codes the text actually backs.

**Reattribution.** Attention bleeds across a fold: a code the model reports on page *i* sometimes
belongs to *i±1*. Where the code is absent from *i*'s text and present in exactly one adjacent
page's text **within the same window**, the sighting moves there and records where it came from.
Where it is printed nowhere it stays put, counts against that page's grounded rate, and never
enters the exact surface.

## 08 · stitch — the folds deleted again

This is the only place section **extent** is created, and that is structural rather than stylistic:
a window fold can cut through a section, and the call on one side cannot see the other, so any span
it gave would be a confident guess. Presence per page is a thing a model can actually see; extent
is the min and max over sightings and cannot be computed until every window has returned. Two calls
that never saw each other are reassembled by sorting page numbers — which is what makes cutting the
document safe, and its absence is how an agent scopes a search to a chapter and gets the half of it
that fell inside one window.

Two earlier defects are not carried over: an uncertainty flag that fired only when *no* page
claimed a section head and never when several did — the counted version treats anything other than
exactly one as uncertain — and the conflation of a page *range* with the observed page *set*, where
a section observed on 17–20 and 22–25 would claim page 21. Both are kept, and the gap is disclosed
as a non-contiguous section rather than smoothed over.

`series_id` is written here too: `section_id` carries the revision, so a scope expressed with one
dies at the next revision, while the series id is the same section across revisions. Both are
keyword arrays, so a page straddling two sections carries both ids.

## 09–10 · embed and index

One page becomes one fused dense vector plus two sparse surfaces, and one Qdrant point. Every
point is written not-current. See
[Embedding and the Three Retrieval Surfaces](embedding-and-sparse-surfaces.md).

## 11 · gates and publish

The five publish gates run, then the visibility flip and retirement. The gate table is printed
*before* anything acts, because the gates are the reviewable part: a document held here is held
for a named reason with its worst pages listed, and a document published is published with every
number that decided it on screen. Run cost — embeddings billed and reused, model calls, cache hits
— is recorded onto the run record at this point. See
[Run Lifecycle, Gates and Publication](run-control-plane-and-publishing.md).

## Related pages

- [Windowing and VLM Extraction](vlm-extraction-and-windows.md) — steps 04–06 in detail
- [Embedding and the Three Retrieval Surfaces](embedding-and-sparse-surfaces.md) — steps 09–10
- [Run Lifecycle, Gates and Publication](run-control-plane-and-publishing.md) — step 11 and resumability
- [Page Model and Index Schema](../concepts/page-model-and-index-schema.md) — the record these steps build
- [The vsir Command Line](../interfaces/cli.md) — the flags that drive the pipeline
