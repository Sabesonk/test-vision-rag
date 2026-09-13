---
type: architecture
title: External State and Storage
description: The two Qdrant collections and the record kinds inside them, the document store of source PDFs, the upload spool, the fixture directories, and the in-process raster cache that is deliberately never persisted — with the typed refusal each absence produces.
tags: [storage, qdrant, state, document-store, caching, failure-modes, twelve-factor]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-7431613dae8f0b1de9c39510
    resource: repo://backend/vsir/core/indexed.py
  - id: openwiki-source-edda12bbc1d03e82a24c567a
    resource: repo://backend/vsir/ingest/fingerprint.py
  - id: openwiki-source-5aea2d2911922a9bb1fc7f6b
    resource: repo://backend/vsir/ingest/render.py
  - id: openwiki-source-dc74b59971729a18b4bb6624
    resource: repo://backend/vsir/ingest/run.py
  - id: openwiki-source-7e3afa9d98c8d399549218dc
    resource: repo://backend/vsir/ingest/store.py
  - id: openwiki-source-852169b548961ba08154a339
    resource: repo://backend/vsir/serve/budget.py
  - id: openwiki-source-1353375d38e7b12c3339cc29
    resource: repo://backend/vsir/serve/ingest.py
  - id: openwiki-source-56c53a81146dc773b4d3a0a3
    resource: repo://backend/vsir/serve/raster_cache.py
  - id: openwiki-source-b118941ef22f6be1f794edf9
    resource: repo://backend/vsir/vlm/cache.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# External State and Storage

Everything the process does not carry in memory lives in one of five places, each named by
an environment variable and each producing a *named* refusal when it is absent rather than a
placeholder, a clamp or a 500.

| State | Named by | Holds | Absent → |
|---|---|---|---|
| pages collection | `{VSIR_COLLECTION}_{VSIR_EMBED_DIM}` | one point per page: dense + two sparse vectors + payload | boot/readiness refusal; store-backed ingest steps refuse before any model call |
| control plane | `VSIR_RUNS_COLLECTION` | runs, windows, leases, cached responses, fingerprint, budget, token inventory | same |
| document store | `VSIR_DOC_STORE` | the **source** PDFs, `<doc_id>@<revision>.pdf` | `503 document_not_stored` naming the document |
| upload spool | `VSIR_SPOOL_DIR` | an upload body, only until the pipeline reads it | falls back to platform temp |
| fixture directories | `VSIR_FIXTURE` and the eval paths | frozen model responses, read-only | `vlm_backend_unavailable` or `fixture_miss` |

## Qdrant, and nothing else

There is no relational database, no ORM and no migration framework — two collections carry
everything.

### The pages collection

One point per page. Its name carries the embedding dimension, so two dimensions are two
collections rather than two named vectors inside one. Each point holds a `dense` vector
under cosine distance plus two sparse vectors, `lexical` and `captions`.

Both sparse surfaces are declared with Qdrant's IDF modifier: the stored values are only
BM25's term-frequency half, and the inverse-document-frequency half is computed across the
collection at query time. That split is what keeps ingesting a new document from staling
every vector already in the index — and the modifier must stay IDF, because the stored
values are not a ranking without it.

`create_collection()` creates the payload indexes **before the first point**, and the
ordering is not cosmetic: filterable HNSW builds extra graph edges from indexed payload
values as points arrive, so indexing afterwards leaves those edges missing. The filter still
answers, from a worse graph, and nothing reports it.

`schema_problems()` is the assertion half of the same dict and is what the boot check calls.

### The control plane

`VSIR_RUNS_COLLECTION` (default `vsir_runs`) is created with `vectors_config={}` — payload
only. Nothing there is searched by similarity: every record is fetched by id or by an exact
filter, and declaring a vector nobody writes would only invite one.

Every point says which `kind` of control record it is:

- **`run`** — the run record (state, step, gates, overrides, lease, cost, retirement).
- **`window`** — one per-window checkpoint, which is what makes "at most one window lost"
  a fact rather than a hope.
- **`observed_tokens`** — the per-document token inventory.
- **`fingerprint`** — one record per pages collection, holding the recipe its vectors were
  made under; the boot check compares against it.
- **`budget`** — the per-caller daily read ledger, so N replicas enforce one ceiling.
- **`vlm_cache`** — the durable response cache keyed by the content-addressable cache keys.

Two payload indexes (`kind` and `collection`) are created with the collection; the rest
(`run_id`, `doc_id`, `revision`, `state`) are added by `ensure_control_plane()`, which reads
the live schema first so an index is not re-created on every run and a collection made by an
earlier release still gains the missing ones.

Because the control plane is created on demand by the first ingest, a serving-only release
never needs it.

Control-plane writes that can be repeated with no different outcome — a filtered
`set_payload` with a constant value, a filtered delete, a keyed upsert — are wrapped in a
small bounded retry. Only those: retrying anything else would turn one outage into two
writes. When the retries are exhausted the run reports itself *unpublished* rather than
half-published, because `published_at` is written only after the flip returns.

## The document store: sources, not derived artefacts

Rasters are never persisted, and for a long time nothing kept the file to render them *from*.
The document store closes exactly that gap, and the distinction is what keeps the no-blob-store
rule intact: re-rendering on demand stays true, and now has something to re-render from.

Files are **identity-addressed and integrity-checked**. A document is stored as
`<doc_id>@<revision>.pdf`, derivable from any `page_id`, so no path ever goes in a payload —
the payload names the *document* and the store resolves the *file*. A pure content-addressed
layout would have needed a hash in the payload or a second index to find one, which is the
same coupling under another name. The hash is not dropped but moved: `content_hash` lives on
the run record, and `locate()` refuses to serve bytes that disagree with the hash the caller
expects. That matters most in the case that otherwise fails silently — a `(doc_id, revision)`
re-ingested from corrected bytes, where the index still holds the previous run's pages until
publish retires them. Rendering the new file for an old page would answer with a page nobody
indexed.

Because a `page_id` can arrive from a caller's saved citation and a revision is the operator's
own string, both components are checked against a conservative pattern before they reach a
`Path`. A separator, a `..` or a leading dot is refused as `document_id_unsafe` rather than
becoming a path traversal with a citation as its payload.

Writes go to a dot-prefixed staging directory *inside* the root and are then renamed, so the
rename stays on one filesystem and is therefore atomic.

The store is a mounted volume shared by every process type of the release, and it is
deliberately not one of the required variables: a release that never ingests and never serves
an image must not be made unstartable by it. Unset means a directory under the platform
temporary directory, which is honest about being ephemeral rather than pretending to be a
volume.

## The raster cache is not external state

Page rasters are re-rendered on demand into an in-process LRU and are never written down. A
cold instance returns an identical image and only more slowly.

There is exactly **one** raster cache, `render._cached`, shared by the ingest path and the
serving path and keyed by the source file's **content hash** — so an edited PDF can never
serve a stale raster. The serving layer deliberately does not put a second cache in front of
it: a cache keyed by `page_id` could not see a re-ingest of the same `(doc_id, revision)` from
corrected bytes, so it would serve superseded pixels for as long as the process lived, while
holding a second copy of every PNG. A much larger, much cheaper memo caches page *boxes* — four
floats — because the whole point of asking for a page's rectangle is to decide whether the
raster may be made at all.

The serving layer owns the request-shaped concerns the renderer must not know about: the URL
grammar (a `page_id` contains a `#`, so it is percent-encoded in one place and read back in
one place), resolution from `page_id` through the indexed page and its run to the stored
bytes, the integrity check, and the megapixel bound checked *before* the render — because a
bound enforced after allocation has already paid for what it refuses.

Its three resolution failures stay distinct because a caller retries them differently: a page
this corpus does not hold is a `404`, a page that is not the current revision is its own
`404`, and a document whose source is missing is a `503` — the page exists and its image
cannot be made, which is an operational problem rather than the caller's mistake.

## The upload spool

`POST /documents` writes the request body to `VSIR_SPOOL_DIR` (falling back to a `vsir-spool`
directory under platform temp) because the renderer needs a file, and removes it when the
child process exits however it exits. It is a transport buffer, not state: what makes an
uploaded run resumable after the instance that accepted it is gone is the *document store*,
not the spool. Like the document store, it is deliberately not one of the required variables.

## Fixture directories

Read-only directories of frozen model responses, checked in and — because the Docker build
context is `backend/` — not present in the image. A container running a demo or an eval mounts
them and points the fixture variables at the mounts. A missing *directory* is
`vlm_backend_unavailable`; a missing *key* inside one is `fixture_miss`. See
[Replay and Live Execution Modes](execution-modes.md).

## Related pages

- [System Architecture Overview](overview.md) — how the pieces fit together
- [Run Lifecycle, Gates and Publication](../ingestion/run-control-plane-and-publishing.md) — what the `run` and `window` records carry
- [Embedding and the Three Retrieval Surfaces](../ingestion/embedding-and-sparse-surfaces.md) — what goes into the three vectors and the fingerprint
- [Page Model and Index Schema](../concepts/page-model-and-index-schema.md) — the payload the pages collection stores
- [Configuration and Boot Self-Check](configuration-and-boot.md) — the refusals these absences produce at boot
