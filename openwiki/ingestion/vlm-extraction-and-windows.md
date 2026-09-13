---
type: subsystem
title: Windowing and VLM Extraction
description: How pages are grouped into windows by a three-rung ladder, what the extraction schema may and may not ask for, and how a bad response is bisected and re-billed rather than kept — including the two independent offset checks and what a failure costs.
tags: [windows, extraction, vlm, bisection, offset-check, cost-control, schema]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-52848e8010ea3472eb7de90c
    resource: repo://backend/vsir/ingest/derive.py
  - id: openwiki-source-18346f41e2a24140473a6dd1
    resource: repo://backend/vsir/ingest/extract.py
  - id: openwiki-source-3d27a73669d9986b6d06027c
    resource: repo://backend/vsir/ingest/window.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Windowing and VLM Extraction

Steps 04–06 are where nearly all the extraction money goes: one document-facts call, then one
call per window. Step 05 costs nothing and decides what step 06 costs.

## A window is a page range, not a chunk

Its boundary is an artefact of the model's attention limit, stitching deletes it again, and it
never becomes a retrieval boundary. Three granularities stay separate throughout: **window**
(attention), **section** (semantics), **page** (index).

## The ladder

Windows target 30 pages under a three-rung ladder. Every rung produces windows of at most the cap
covering the document exactly once, and **every rung is parallel** — the rung number only records
*where the boundaries came from*.

| Level | Boundaries come from | When |
|---|---|---|
| 0 | the document itself | it fits under the cap, and under the inline byte ceiling |
| 1 | the chapter starts the document declares | it has an outline |
| 2 | the cap | there is no structure to cut on |

An inline byte ceiling rules Level 0 out for a file too large to hand over in one piece even when
its page count would fit.

### Level 2 exists because its exclusion was expensive

The fold-at-the-cap rung was originally excluded on the grounds that it had to run sequentially
with a carry chain: the second window needed to know what the first ended with. That was a correct
description of the *previous* implementation, whose model reported section **extent**, so a window
beginning mid-section had to be told where it was. Extent is no longer asked of the model —
sections are presence per page and extent is computed after the folds are gone — so the carry
chain's reason was removed while the exclusion stayed behind.

Refusing the rung cost the corpus rather than the two documents that motivated the exclusion.
Running every PDF of the working dataset — 202 files, 5,578 pages — through the shipped ladder,
giving Level 1 the best possible break by feeding it each file's own outline, **14 documents and
2,719 pages, 49% of the corpus, were refused**. Eleven of the fourteen declare no outline at all,
and one of them was the pilot document, which therefore failed one step before the spend it was
waiting on.

### A window is bounded below as well as above

Bounding chapters only from above and packing nothing together billed one call per sheet on a
densely outlined file: one document declaring 8,187 bookmarks over 592 pages cut into 592 one-page
windows where about 20 do the same work. The packer folds a chapter below a floor of a third of
the cap into its neighbour and leaves every chapter above it alone.

That is deliberately a **floor on the merge rather than a fill to the cap**: a Level 1 that packs
to the cap has taken its boundaries from the cap and is Level 2 wearing Level 1's number.

## What extraction may ask for

The schema was rewritten rather than ported, and everything that encoded knowledge of *this
particular corpus* went with the old shape: no identifier grammar, no classification enum, no
regex taxonomy and no per-corpus keyword list anywhere in extraction or derivation. The page-kind
list is the schema's own value list — it says what a *sheet of paper* is and would read the same
for a cookbook — and a model-returned kind outside it is normalised to a default rather than
re-billing thirty pages over a label.

Three rules shape the rest:

- **Presence, never extent.** A section entry says "this page belongs to the emergency stop
  chain"; it never says where that section starts and ends. A fold can cut straight through a
  section and the model on one side cannot see the other, so any span it gave would be a
  confident guess. Extent is computed after the folds are gone, which is what lets a section
  straddle a fold and survive it.
- **Verbatim structure, and the text never comes back.** The model returns structure and codes,
  never page text — the text came from the PDF library at step 02 and the probe is its only
  writer. That is what makes the next step able to *check* the model's codes against what is
  actually printed.
- **Keep the receipt, not your summary of it.** What is cached is the verbatim response body.
  Caching the derived page record instead would look equivalent and would make every downstream
  change unreplayable, because re-deriving would mean buying the paid call again. Because the
  receipt is kept, steps 07–10 cost nothing to change and evaluating a different text extractor is
  free.

## A bad answer is bisected, never kept

Four triggers split a window and re-bill it: the output-token ceiling, an unterminated body, a
schema-invalid body, and a page-index set that is not exactly 1..N.

`parse()` tells the first three apart because they are different events and only one of them means
the prompt is wrong: an unterminated body is the provider's ceiling reached mid-JSON, a valid body
of the wrong shape is an answer to a different question, and a sound body whose indices are not
1..N is an answer about pages that were not the ones sent.

Bisection **never pads, never guesses the offset and never accepts a partial window** — a
truncated 30-page window quietly kept loses 30 pages of a manual and reports success. The floor is
one page, which raises a typed unsplittable-window refusal. There is no recursion-depth counter:
the terminus is *that page*, not a limit.

## The two offset checks

The offset is the most dangerous quantity in the pipeline: get it wrong and every page number,
page id, citation and summary shifts, and nothing else errors.

**Check 1 — structural.** The window's forms carry page indices exactly 1..N, each once. The
function that decides it is shared between step 06 and step 07 so one function owns the question.
It is also what "never accept a partial window" means in code: a 30-page window that comes back
with 22 forms has lost eight pages of a manual and nothing else in the pipeline would notice. The
report names what was missing, what was duplicated and what fell outside.

**Check 2 — independent observation.** A model-read printed page number, on a page that has a text
layer, must be printed on *this* page. Structural runs first, because an index set that is not
1..N makes the absolute page of every form meaningless and there would be nothing sound to run the
second check on.

Check 2 weighs **every** page of the window before deciding rather than raising on the first
observation. Each page with a model-read label and a text layer falls into one of three states,
and only two are evidence:

- **confirms itself** — the label is printed on this page: direct evidence the window is aligned;
- **witness** — the label is printed on a neighbour and not here: evidence of a shift;
- **printed nowhere** — a misread, and evidence of nothing either way, which must not dilute
  either side. On one legacy window 29 of 30 labels are printed nowhere in the projected text, so
  counting them as agreement would silence the one page that can see.

A window is refused when the witnesses reach **two**, **or** when there is at least one witness and
*no page confirms itself*. The second clause is the argument stated exactly — a genuine shift moves
every page of the window, so under a real shift nothing can confirm its own label — and it is what
keeps sensitivity where only one page carries a legible label. Without it, bisecting a genuinely
shifted window would terminate by *accepting* its single pages instead of reaching the unsplittable
refusal, which is the opposite of the intended terminus.

Conversely, a page that confirms its own label is direct evidence of alignment that one stray
numeral must not outvote.

### What a false positive costs

A single-witness rule was the original design on the assumption that a false positive costs one
re-billed window. It does not: the neighbour check reads the **whole document** rather than the
window, so the predicate is invariant under bisection and the repair reaches the same verdict all
the way down to the unsplittable refusal. Because the offset gate is blocking and deliberately not
overridable, one bare numeral cost the document plus roughly eight paid windows on the way down.
Measured over the real corpus, a single witness fires on 22 pages across 11 of the 98 documents
that declare page labels, and every one is a false positive.

A tolerated witness is **logged rather than swallowed** — it is the only trace that the check saw
something — and the line carries the fields the refusal would have, so a corpus sweep can count
them without re-running the check.

## Related pages

- [Ingestion Pipeline](pipeline.md) — where these steps sit and what follows them
- [Replay and Live Execution Modes](../architecture/execution-modes.md) — the extraction cache key and how a response is replayed
- [Run Lifecycle, Gates and Publication](run-control-plane-and-publishing.md) — per-window checkpoints and the blocking offset gate
- [Page Model and Index Schema](../concepts/page-model-and-index-schema.md) — what the extracted structure becomes
