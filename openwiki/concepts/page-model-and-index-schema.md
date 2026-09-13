---
type: concept
title: Page Model and Index Schema
description: The page as the addressable unit — deterministic identifiers that make a re-ingest overwrite rather than double, the two-zone page record, the single INDEXED dict that creates gates and asserts the payload schema, and the text-trust ladder.
tags: [page-model, identifiers, schema, payload, text-trust, invariants]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-2e29a3912ba2bec50c00c705
    resource: repo://backend/tests/unit/test_ids.py
  - id: openwiki-source-7a8d2200cd17fb807402df9b
    resource: repo://backend/vsir/core/health.py
  - id: openwiki-source-b5dd6b5257694a6c233ede00
    resource: repo://backend/vsir/core/ids.py
  - id: openwiki-source-7431613dae8f0b1de9c39510
    resource: repo://backend/vsir/core/indexed.py
  - id: openwiki-source-d572197da3841e3aa4058b71
    resource: repo://backend/vsir/core/record.py
  - id: openwiki-source-6f5751f3f39cb35acb313461
    resource: repo://backend/vsir/ingest/index.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Page Model and Index Schema

The unit of everything is the **page**. Documents, revisions, pages and runs are the nouns;
there is no chunk. This page covers the three things that make a page addressable, storable
and filterable, and the fourth that says how much of it may be believed.

## Identifiers, and the invariants they buy

```
page_id     TC1E-SF@1.3#p001          {doc_id}@{revision}#p{NNN}
section_id  TC1E-SF@1.3#s007          the section's ordinal after stitching
series_id   TC1E-SF#s:emergency-stop  the same section across revisions — no revision in it
run_id      01J8...                   a ULID
point_id    uuid5(NAMESPACE_URL, page_id)
```

**`point_id` is deterministic.** It is a UUIDv5 of the page id rather than a fresh random id,
so a re-ingest of the same page *overwrites* its point instead of adding a second one. That is
what makes doubled totals impossible rather than merely unlikely.

**Only the canonical page-id spelling parses.** `#p0001` and `#p001` are the same page to a
human and to `int()`, but they are different strings and would hash to different point ids. A
lenient parse plus a string-keyed hash is one page with several point ids: a re-ingest would add
a point instead of overwriting it, and a citation with an extra zero would address a point that
does not exist — a silent miss rather than an error. So over-padding is refused by the parse,
and `point_id()` canonicalises *through* that parse so a non-canonical string cannot reach the
hash at all.

**The UUID namespace is pinned** to `uuid.NAMESPACE_URL` and asserted by a test, because the
namespace is part of the id: changing it would orphan every point in the collection.

**`series_id` deliberately omits the revision.** That is its whole purpose — a scope expressed
as a `series_id` survives a revision boundary, where a `section_id` cannot.

**`run_id` is a ULID**: 48 bits of millisecond time then 80 bits of randomness, in Crockford
base32 (no I, L, O or U, so a transcribed id cannot become a different one). Lexically sortable,
so listing runs in id order lists them in time order with no index, and two runs started in the
same millisecond still differ.

## The page record, in two zones

The record is validated with `extra="forbid"` and splits deliberately into a **flat** zone and a
**nested** one, following one rule: a field belongs in the flat facets only if its values form a
small closed set — something a user could pick from a dropdown; if you need it to rebuild the
row it is provenance; if nobody narrows or finds by it, it is content.

The zones look different on purpose. Qdrant *can* filter a nested key — it just runs unindexed
and skips the filterable-HNSW path, which is a silent recall loss rather than an error — so
keeping the two zones visibly distinct is what makes that mistake reviewable.

**Flat facets**: `doc_id`, `revision`, `is_current`, `doc_type`, `subjects`, `tags`, `page_kind`,
`lang`, `page_no`, `section_id`, `series_id`, `has_text`, `text_trust`, `run_id`.

`section_id` and `series_id` are **arrays**. A page straddling two sections carries both ids and
a scope matches if any element matches; a single scalar per page is exactly how a scope silently
excludes a page it should have contained.

`is_current` defaults to **False**. A record is not queryable until the publish gates flip it,
and a default of True would make that a matter of remembering rather than a property of the type.

**Flat full text**: `text` and `vlm_codes`, the two indexed text surfaces. `text` is PyMuPDF's
extraction of the **full** page, and the ingest probe is its *only* writer — it never reads from
a crop. That single-writer rule is what makes "the code was printed on the page" a property of
the schema rather than a hope about the model: model output can only reach a lexical index
through `vlm_codes`, which is opt-in and whose hits are permanently labelled unverified.

**Nested content** carries the printed page number and whether it was verified or interpolated,
per-language summaries (never a blended multi-language string), topics, the page's sections,
the model's claimed `codes`, the `codes_in_text` those of them that the text actually backs,
`moved_from` reattributions, `grounded_rate` and flags.

**Nested provenance** carries `page_id`, `run_id`, `release_id`, `schema_version`, the
`extract_key`, `embed_key` and `read_keys` receipts, the probe version, the VLM model, the prompt
version and the dpi. The page id is single-sourced there and exposed as a property.

There is deliberately **no `image_path`** anywhere in the record: rasters are re-rendered on
demand, so no record may depend on a file that might not exist on the instance serving the
request. The write path asserts that at the payload level too.

The vectors are not part of the payload — they travel beside it in the upsert, because a vector
is not something a filter or a response ever reads.

## `INDEXED`: one dict, three jobs

The same module-level mapping creates the payload indexes, gates every caller filter, and is
asserted against the live collection at boot. Two dicts would drift, and drift here is invisible:
a filter on a field that was never indexed still answers, just from an unindexed scan and a worse
graph.

`scope_keys()` is `INDEXED` minus the two text surfaces, so `text` and `vlm_codes` are reachable
only through the tools that own the exact-match path — exposing them as caller filters would be a
second such path. `reject_unknown_keys()` is what turns anything else into a typed refusal.

The `keyword[]` marker on `section_id` and `series_id` is a standing warning rather than a
distinct Qdrant type: a keyword index matches any element, and the suffix is there to stop
someone writing a scalar.

Payload indexes are created **before the first point**, because filterable HNSW builds extra
graph edges from indexed payload values as points arrive.

## The text-trust ladder

Four signals say how much of a page's text layer may be believed, computed structurally rather
than curated.

`grounded_rate` is the share of the model's claimed codes that the page's own text actually
prints, measured with the same phrase-over-variants question the index is asked — not a token-set
intersection, which could never match a multi-token code and would put a healthy document under
the publishing gate.

The `None` is the whole point of the module: `grounded_rate` is defined only where there *is* a
text layer. A scanned page has codes the model read off the raster and nothing to check them
against, so a numeric `0.0` there would say "extraction is broken" when the truth is "there was
nothing to check" — and it would drag the document median under the publish gate, quarantining
exactly the scanned documents that must be published and merely unsearchable. Every aggregate
ignores those pages rather than defaulting them.

A page with text and no claimed codes rates **1.0**: nothing was claimed, so nothing is unbacked.

`page_trust` maps the rate onto four levels via two pinned thresholds — `ok` at 0.8 and above,
`degraded` down to 0.2, `untrusted` below that, and `no_text` which is final and nothing
promotes. The thresholds are code rather than configuration deliberately: a deployment that could
re-tune what "trusted" means could re-enable the failure the signal exists to prevent.

`untrusted` and `no_text` together are `UNSEARCHABLE_TRUST`, declared once because three
components need the same rule — `lookup` excludes such pages from hits, `verify` returns
`unverifiable` for them, and the observed-token inventory takes no codes from them. `degraded` is
deliberately *not* in that tuple: a text layer with problems is not one that cannot be read.

`searchable_ratio` is the share of a document's pages that have any text layer, and `blind_spot`
marks the case that must be disclosed even when nothing matched: a document at 0.4 is still found
through the pages that do have text, but a document at 0.0 has no text surface at all, so a query
carrying a printed code excludes it from every branch and it would leave the answer set silently.

`demote()` enforces that a page is never more trusted than the document it came from — the
document-level judgement has to reach the pages, because filtering and verification act per page,
and a document-level number nothing on a page reflects would be a signal with no effect.
`no_text` is never overwritten: why *that* page is unsearchable is a fact about the page, not
about the document.

## Related pages

- [Exact Match and Claim Verification](exact-match-and-verification.md) — what the `text` surface is asked
- [External State and Storage](../architecture/state-and-storage.md) — the collections these points live in
- [Embedding and the Three Retrieval Surfaces](../ingestion/embedding-and-sparse-surfaces.md) — the vectors beside the payload
- [Search, Fusion and Ranking](../retrieval/search-and-fusion.md) — how scope filters use these facets
- [Ingestion Pipeline](../ingestion/pipeline.md) — which step writes which part of the record
