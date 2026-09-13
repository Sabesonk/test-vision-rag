---
type: subsystem
title: Embedding and the Three Retrieval Surfaces
description: How one page becomes one fused image-plus-text dense vector and two BM25 sparse surfaces, why the collection is its own embedding cache, and which fingerprint changes refuse a collection versus the one that has an in-place migration.
tags: [embeddings, bm25, sparse-vectors, fingerprint, caching, migration, cost-control]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-12T16:01:50.652Z
sources:
  - id: openwiki-source-94974397b90495200dfe11e5
    resource: repo://backend/vsir/ingest/embed.py
  - id: openwiki-source-edda12bbc1d03e82a24c567a
    resource: repo://backend/vsir/ingest/fingerprint.py
  - id: openwiki-source-6f5751f3f39cb35acb313461
    resource: repo://backend/vsir/ingest/index.py
  - id: openwiki-source-2b5725350422240a04759331
    resource: repo://backend/vsir/ingest/resparse.py
  - id: openwiki-source-17ca9a48741fa48ab4a2d3de
    resource: repo://backend/vsir/ingest/sparse.py
generated: { by: "claude-code", at: "2026-09-12T16:01:50.652Z" }
---

# Embedding and the Three Retrieval Surfaces

Each page point carries three vectors: one **dense** fused image-and-text embedding, and two
**sparse** BM25 surfaces — `lexical` over the extracted text, and `captions` over the model's
generated summaries and topics.

## The dense vector: one page, one fused embedding

Three API facts drive the design and would not be re-derived by anyone rewriting this from
scratch:

1. **There is no document/query task mode** for this embedding model, so the asymmetry between
   a short question and a whole page cannot be steered by a flag. It is closed on the *index*
   side instead, by interleaving the page's own text into its vector — which is what the
   composition is for.
2. **A bare list in `contents` returns one aggregated embedding for the whole list.** Send
   eight pages that way and you get one blended vector instead of eight, silently. Each page is
   therefore wrapped in its own `Content`, the returned count is verified, and there is a
   per-item fallback if that behaviour ever changes. The aggregation is used deliberately
   *within* a page — several parts become one position — and refused *between* pages.
3. **`output_dimensionality` is MRL truncation.** A wrong dimension raises rather than being
   quietly stored, and the dimension is carried in the collection name and the fingerprint:
   comparing two dimensions is two collections, never two vectors in one.

### The composition

```
doc_title · section_titles · summaries[] (one per language) · topics · codes
          · text[:VSIR_EMBED_TEXT_CHARS] · the page raster @ dpi 150   ← last
```

Each text part is its **own** `Part`, never a concatenated blob: a two-language page gets two
summary parts rather than one blended string, so the model fuses structured parts rather than a
pre-blended one. Empty and whitespace-only parts are dropped — an empty part is a token spent on
nothing.

`Composition` is a value object rather than something built inline, for two review reasons: the
part order is a specification clause and belongs where a test can read it, and the cache key is a
digest of exactly this object, so the thing that is keyed and the thing that is sent cannot drift
into describing different requests.

That key's canonical form is **JSON, not a joined string**, because a separator is ambiguous: two
different part lists could concatenate to one string and a key they collided on would serve one
page's vector as another's. The raster enters by digest, so a re-render at a different dpi or a
corrected page misses the cache. `dpi` is deliberately excluded — it cannot change without
changing the pixels, so it is already carried by the digest, and an input that cannot change the
answer only re-bills.

Truncation is **counted**: the composition records how many characters of page text were carried
and how many were dropped, so a corpus that starts losing page tails is visible rather than
silent. Rasters are normalised to RGB PNG with a bounded long edge, because an image part is
billed by area.

The printed page label is deliberately *not* a part: a printed label is the `resolve` tool's
question, answered from an indexed facet rather than by nearest neighbour.

### Where money is spent, and what makes a re-run free

Only the live backend bills, and it bills **one call per page**. `embed_document` composes every
page, computes each `embed_key`, and reuses a stored vector only when its key matches *and* its
length matches the configured dimension — which means the composition, the composition version
and the embedding model all agree. Anything else is a miss and is re-billed.

The cache is the index itself: the stored vector and its `embed_key` are read back off the page's
own point, so caching adds no state anywhere. Dropping the pages collection therefore drops the
embedding cache with it, which is why a sparse-recipe change has a migration rather than a
re-ingest.

A batch that returns a different count than it was given raises rather than being zipped into
silence, and a vector whose length disagrees with the collection dimension raises naming the page.

## The two sparse surfaces

The document side stores **BM25's term-frequency component** and Qdrant supplies the IDF factor at
query time:

```
value(t, D) = tf(t,D) · (k1 + 1) / (tf(t,D) + k1 · (1 − b + b · |D| / avg_len))
```

Keeping IDF on the query side is what stops ingesting one document from staling every sparse
vector already in the index. Storing raw counts — the earlier approach — kept that property but
gave up the other two halves of BM25, with a measurable cost: over the 56 pages of one real
ingest, a query ranked the *only* page printing the searched phrase **9th**, behind prose pages
that merely repeated a common word 13, 9, 9 and 8 times; BM25 puts it 2nd. That is not a worse
ordering, it is the wrong page, and no branch weighting could recover it. The measurement is held
in a test so the regression cannot be quiet.

Ingesting a document still changes no stored value, because `|D|` is a property of the document
itself and `avg_len` is a **released pin** rather than a live measurement. What is given up is
that a pin drifts from the corpus it describes as the corpus grows — bounded, visible in the
config module, and corrected by a release that bumps the sparse version.

Three details:

- **There is deliberately no shared `build()`.** The document and query sides need different
  weights: a query built with document weights would apply `k1` twice, and a document built with
  query weights would lose saturation. Both mistakes present identically, as worse neighbours, so
  two names that cannot be confused is the whole point.
- **The query side is presence, 1.0 per distinct term.** With the tf component already on the
  document side, what Qdrant computes *is* BM25 — a claim a reader can check in one line.
  Counting here would let someone who wrote "the sensor and the sensor cable" weight a term double
  off filler rather than intent.
- **Tokenisation is the project's own**, not Qdrant's server-side BM25. These vectors and the
  phrase index must agree about what a token is, or the lexical surface would find pages the
  exact surface cannot confirm — and the server-side implementation brings its own tokenizer,
  stemmer, stopword list and ASCII folding.

Colliding hash slots sum their *saturated weights* rather than their counts: two distinct terms
sharing a slot are two terms each saturating on its own, and adding counts first would
over-saturate the pair. `avg_len` is checked before the empty-text shortcut, so a misconfigured
release refuses on the first page it indexes rather than on the first page that happens to have
text — on a scanned document those are different pages.

The `captions` surface is **deduped against the page's own text** before it is built. Without
that, a page enters fusion twice for one piece of evidence, with the generated copy weighted like
printed text. `avg_len` is keyword-only with no default because the two surfaces differ by an
order of magnitude in document length and a default would let a caller weight captions against the
lexical statistic without saying so.

A surface with nothing to say is **absent**, not zeroed: an all-zero sparse vector is not "no
keywords", it is a vector with no terms that Qdrant still stores, indexes and scores.

Both surfaces are derived by one function, and the migration calls that same function — a second
implementation of the recipe would agree on the day it was written and drift on the day the recipe
changed, which is the only day it is ever used.

## The fingerprint

Qdrant has no collection-level metadata, so the recipe a collection's vectors were made under is a
point in the control plane, one per pages collection, discriminated by `kind`. A sentinel point
inside the pages collection was rejected because it would put a non-page point in a collection
whose point count is an assertion.

Five fields: `embed_model`, `dim`, `distance`, `composition_version`, `sparse_version`.

Two of them are easy to leave out and are the ones the system needs most. `composition_version`
covers the fused vector's *meaning*: reordering the parts or dropping the raster changes every
vector without changing the model id. `sparse_version` covers the half-client-side BM25 recipe: a
BM25 collection and a raw-count collection are byte-identical in shape, declare the same modifier,
pass every schema check, and differ only in what the stored floats mean.

Two halves are checked in two places. `dim` and `distance` are observable from the live collection
and are read back at boot; `embed_model` and `composition_version` are not observable from Qdrant
at all, so they are recorded here and compared next to the write, where the money is.

`require()` is the gate: a collection with no fingerprint takes this one — the first-ingest case
and the only way a record is created — and every other disagreement is a refusal that writes
nothing. There is no path that updates a stored fingerprint in place, because that is exactly the
in-place mix the design forbids.

## The one repairable difference

`vsir migrate sparse` exists because the refusal above, though correct, had no supported way to
say *yes*. Without it the only path was delete-and-re-ingest — and deleting the collection deletes
the embedding cache with it, turning a change that touches no embedding into a full live re-embed
of every page.

Both sparse surfaces are a pure function of payload the collection already holds, so they are
re-derived by scrolling and writing back two vectors: no model call, no raster, no spend, and the
dense vector is never read.

It **refuses** (`migration_unsupported`) whenever any fingerprint field other than
`sparse_version` differs. A migration that rebuilt sparse vectors under any change would be more
dangerous than none: it would stamp the new recipe onto a collection whose *dense* vectors were
made by a different model, which is the in-place mix wearing the costume of a repair.

Ordering is the crash-safety argument. The fingerprint point is rewritten **last**, after every
page. A kill halfway leaves the *old* fingerprint over a partly rebuilt collection, so the boot
check keeps refusing, nothing serves a mixed index, and re-running is safe because deriving a
sparse vector from a payload is idempotent. The other order would publish a collection claiming to
be migrated while half of it is not.

It is a subcommand rather than a script so the repair for a bad release runs from the same image
and release as everything else.

## One recipe, two callers

What makes the repair trustworthy is not the migration's own care but that it does not own a
recipe. Both sparse surfaces come from a single function, and the ingest path and the migration
path are two callers of it: step 10 reaches it while assembling the three vectors of a new point,
and the migration reaches it while rebuilding two vectors of an existing one.

The alternative is worse than it looks. A migration with its own copy of the arithmetic would
agree with the ingest path on the day it was written, and drift from it on the day the recipe
changed — which is **the only day the migration is ever used**. A repair that is correct except
when it is needed is a repair in name, and the drift would be invisible: a collection rebuilt
under a subtly different weighting is byte-identical in shape and declares the same modifier, so
nothing fails and the neighbours are merely worse.

Sharing the recipe is what makes the migration a pure function of the payload, which is also why
it costs nothing: the surfaces are re-derived from text the collection already holds, with no
model call, no raster and no read of the dense vector.

The seam it does own is reading a payload back. Each stored point is re-validated into a page
record before it is re-derived, and a payload this release cannot validate is a typed refusal
that writes nothing and leaves the fingerprint alone. Skipping the page instead would leave one
page on the old recipe inside a collection stamped with the new one — the silent mix the
fingerprint exists to prevent, reintroduced by the tool meant to resolve it.

## Related pages

- [Ingestion Pipeline](pipeline.md) — where steps 09 and 10 sit
- [Search, Fusion and Ranking](../retrieval/search-and-fusion.md) — how the three surfaces are combined at query time
- [External State and Storage](../architecture/state-and-storage.md) — the collections and the IDF modifier
- [Page Model and Index Schema](../concepts/page-model-and-index-schema.md) — the payload these vectors are derived from
- [Replay and Live Execution Modes](../architecture/execution-modes.md) — the stub embedder and its namespaced model id
