"""Step 10 — records into Qdrant points. Ported with changes from ``impl/app/segstore.py``.

One page, one point, three surfaces (§5.3, I1)::

    dense      the fused image+text vector of step 09 (D4)
    lexical    sparse, raw term frequencies over `text`, IDF applied by Qdrant (D2)
    captions   sparse, over `summaries[] + topics`, deduped against `text`, weight 0.4 (D2)

What is ported: the two-zone payload, the deterministic ``point_id``, the sparse surfaces built
here for free from term counts, and the reason the two zones are shaped differently — Qdrant *can*
filter a nested key, it just runs unindexed and skips the filterable-HNSW path, so a filter on the
wrong zone is a silent recall loss rather than an error (F10).

Four changes, each closing something `impl` records as wrong:

* **The ``captions`` surface is actually written.** `impl` declares it on the collection, weights
  it 0.4 in configuration, and ``upsert``'s ``caption_text`` argument defaults to ``{}`` and is
  never passed — so fusion runs on two surfaces while the configuration claims three (register
  **D3**). The new S2 output is exactly the generated description that surface was designed for
  (D2), and :func:`vsir.ingest.sparse.dedupe` is what makes it safe to write: without it a page
  enters fusion **twice** for one piece of evidence, with the generated copy weighted like printed
  text.
* **The curated model-derived keyword index is gone**, replaced by the ``text`` phrase index
  (C2, §5.5). It was the only pinnable surface in `impl` and it was built from the model's
  reading; the exact surface is now text the probe extracted, and there is one code path to it
  (I3, :func:`vsir.core.exact.exact_filter`).
* **``is_current`` is written False, always.** Step 11 is the only thing that flips it (I7, §6.7).
  A run that has not passed its gates cannot answer, and this module refuses a record that arrives
  already claiming otherwise rather than trusting the caller to have remembered.
* **No ``image_path``.** Register **A5**: a relative path resolved against a different working
  directory made ``read()`` return 503 for every page in the collection. Rasters are re-rendered
  on demand (§4.2), so no payload names a file (§5.3, §15 Factor VI).

**The §6.6 fingerprint is checked here, next to the write.** Not at boot only: boot runs once per
process and a long-lived ingest worker can be handed a configuration that never went through one.
A mismatch writes **zero** points — the check is the first thing :func:`upsert` does, before a
single ``PointStruct`` is built.

**And this module is the embedding cache** (register **B5**). :func:`cached_vectors` reads the
vector and the ``embed_key`` already stored on a page's point, so a re-ingest of an unchanged page
reuses the vector instead of buying it again. The store is the index: closing B5 adds no state
anywhere, which is what §15 Factor VI asks for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.core import ids
from vsir.core.exact import scope_conditions
from vsir.core.indexed import DENSE_VECTOR, SPARSE_VECTORS, create_collection
from vsir.core.record import PageRecord
from vsir.ingest import sparse
from vsir.ingest.fingerprint import Fingerprint, FingerprintMismatch, require

_log = vsir_logging.get_logger(__name__)

LEXICAL, CAPTIONS = SPARSE_VECTORS

#: Payload keys a page record must never carry. ``image_path`` is register A5 and the reason §5.3
#: says *"there is no image_path"*: the record is validated by a model with ``extra="forbid"``, so
#: this cannot happen through the type — it is asserted at the write because the *payload* is what
#: a later reader sees, and a payload assembled any other way would still land here.
FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = ("image_path", "image_url", "render_path")


class IndexRefused(RuntimeError):
    """A typed refusal from the write path. Nothing partial is ever written behind one."""

    code = "index_refused"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


class PublishedBeforeGates(IndexRefused):
    """A record arrived with ``is_current=True`` before the gates ran (I7, §6.7)."""

    code = "is_current_before_gates"


class DuplicatePage(IndexRefused):
    """Two records claim the same ``page_id`` — one page, two points, which is not I1."""

    code = "duplicate_page_id"


class VectorMissing(IndexRefused):
    """A record has no dense vector. `impl` skipped these silently; a skipped page is a gap."""

    code = "vector_missing"


# ── the generated surface (D2, register D3) ──────────────────────────────────────────────────────

def caption_text(record: PageRecord) -> str:
    """The generated text the ``captions`` surface indexes: ``summaries[] + topics``, deduped.

    The dedupe is against the page's own ``text``, so a token the verbatim text layer already
    carries is not counted a second time in a channel that is fused alongside it. What remains is
    the part of the model's description that the printed page does **not** say — which is the only
    part that can add recall rather than double-count evidence (D2).
    """
    generated = " ".join([*(summary.text for summary in record.content.summaries),
                          *record.content.topics])
    return sparse.dedupe(generated, against=record.text)


def _vectors(record: PageRecord, dense: Sequence[float]) -> dict[str, Any]:
    """The three surfaces for one page. A surface with nothing to say is **absent**, not zeroed.

    An all-zero sparse vector is not "no keywords", it is a vector with no terms that Qdrant still
    stores, indexes and scores; omitting the name is how a page with no summaries says it has no
    generated text (which the acceptance criteria assert).
    """
    vectors: dict[str, Any] = {DENSE_VECTOR: list(dense)}
    lexical_indices, lexical_values = sparse.build(record.text)
    if lexical_indices:
        vectors[LEXICAL] = qm.SparseVector(indices=lexical_indices, values=lexical_values)
    caption_indices, caption_values = sparse.build(caption_text(record))
    if caption_indices:
        vectors[CAPTIONS] = qm.SparseVector(indices=caption_indices, values=caption_values)
    return vectors


def build_point(record: PageRecord, dense: Sequence[float]) -> qm.PointStruct:
    """One record and its vector → one point. ``point_id = uuid5(page_id)`` (I1, §5.1)."""
    if record.is_current:
        raise PublishedBeforeGates(
            f"{record.page_id} arrived with is_current=True and step 10 writes every point "
            f"is_current=False: the publish gates are the only thing that flips it, and a point "
            f"that is queryable before they run is exactly the half-finished run F17 names",
            page_id=record.page_id,
        )
    if not dense:
        raise VectorMissing(
            f"{record.page_id} has no dense vector. `impl` skipped a record whose vector was None "
            f"and reported the write as successful, so the page was simply missing from the index "
            f"with nothing to say so",
            page_id=record.page_id,
        )
    payload = record.to_payload()
    present = [key for key in FORBIDDEN_PAYLOAD_KEYS if key in payload]
    if present:
        raise IndexRefused(
            f"{record.page_id}: payload carries {present}, and §5.3 has no such field — rasters "
            f"are re-rendered on demand, so no record may depend on a file that the instance "
            f"serving the request may not have (register A5)",
            page_id=record.page_id, keys=present,
        )
    return qm.PointStruct(id=ids.point_id(record.page_id), vector=_vectors(record, dense),
                          payload=payload)


# ── the collection ───────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CollectionState:
    """What :func:`ensure_collection` found or made. Printed by the CLI; nothing branches on it."""

    name: str
    dim: int
    created: bool
    fingerprint: Fingerprint


def ensure_collection(client: Any, *, name: str, dim: int, fingerprint: Fingerprint,
                      runs_collection: str) -> CollectionState:
    """Create the collection and its indexes if absent, then agree with §6.6 or refuse.

    Ordering is load-bearing twice over. The payload indexes are created **before the first
    point**, because filterable HNSW builds its extra graph edges from indexed values as points
    arrive (:func:`vsir.core.indexed.create_collection` carries `impl`'s comment on this). And the
    fingerprint is settled **before any embedding is paid for** — a refusal after the spend is
    still correct and is much more expensive.
    """
    created = create_collection(client, name, dim)
    settled = require(client, runs_collection=runs_collection, pages_collection=name,
                      fingerprint=fingerprint)
    _log.info("collection_ready", collection=name, dim=dim, created=created,
              fingerprint=settled.digest, runs_collection=runs_collection)
    return CollectionState(name=name, dim=dim, created=created, fingerprint=settled)


# ── the write ────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Upserted:
    """Step 10's receipt: what was written, under which ids, on which surfaces."""

    collection: str
    #: ``(page_id, point_id)`` in write order — the demo prints these, and I1 is asserted on them.
    points: tuple[tuple[str, str], ...]
    with_lexical: int = 0
    with_captions: int = 0

    @property
    def count(self) -> int:
        return len(self.points)

    @property
    def page_ids(self) -> tuple[str, ...]:
        return tuple(page_id for page_id, _ in self.points)

    @property
    def point_ids(self) -> tuple[str, ...]:
        return tuple(point for _, point in self.points)


def upsert(client: Any, name: str, records: Sequence[PageRecord],
           vectors: Mapping[str, Sequence[float]], *, fingerprint: Fingerprint,
           runs_collection: str) -> Upserted:
    """Write one point per record, all ``is_current=False``. Idempotent by ``point_id`` (I1).

    The fingerprint is checked first and everything else is validated before anything is sent, so
    a refusal writes **zero** points rather than a prefix of them: a half-written document is the
    state F12 and F17 are both about, and the only way to be sure there is no such state is to
    have built every point before the first one is transmitted.
    """
    require(client, runs_collection=runs_collection, pages_collection=name,
            fingerprint=fingerprint)

    seen: dict[str, int] = {}
    for position, record in enumerate(records):
        if record.page_id in seen:
            raise DuplicatePage(
                f"{record.page_id} appears at positions {seen[record.page_id]} and {position}: "
                f"one page is one point (I1), so two records for it would silently overwrite one "
                f"another and the totals would not add up",
                page_id=record.page_id,
            )
        seen[record.page_id] = position

    points = [build_point(record, vectors.get(record.page_id, ())) for record in records]
    if not points:
        return Upserted(collection=name, points=())

    client.upsert(collection_name=name, points=points, wait=True)
    written = Upserted(
        collection=name,
        points=tuple((record.page_id, str(point.id)) for record, point in zip(records, points)),
        with_lexical=sum(1 for point in points if LEXICAL in point.vector),
        with_captions=sum(1 for point in points if CAPTIONS in point.vector),
    )
    # A domain event, not `ingest_step`: §6.1's step stream is the CLI's, and this function is
    # called more than once per run — by the idempotence check, and by U011's retry.
    _log.info("index_upsert", collection=name, points=written.count,
              with_lexical=written.with_lexical, with_captions=written.with_captions,
              is_current=False, fingerprint=fingerprint.digest)
    return written


# ── reading back: the embedding cache (register B5) and the counts ───────────────────────────────

def cached_vectors(client: Any, name: str,
                   page_ids: Iterable[str]) -> dict[str, tuple[str, list[float]]]:
    """``{page_id: (embed_key, dense vector)}`` for the pages already in the collection.

    This is the embedding cache of §6.3, and the index is the store. A page whose composition has
    not changed has the same ``embed_key``, so step 09 reuses the vector on its point instead of
    re-billing it — which is register B5, closed without adding a cache anywhere.

    A missing collection is an empty result, not a refusal: the first ingest into a fresh
    collection has nothing to reuse and that is not a problem to report.
    """
    wanted = list(page_ids)
    if not wanted or not client.collection_exists(name):
        return {}
    by_point = {ids.point_id(page_id): page_id for page_id in wanted}
    found = client.retrieve(name, ids=list(by_point), with_payload=["provenance"],
                            with_vectors=[DENSE_VECTOR])
    held: dict[str, tuple[str, list[float]]] = {}
    for record in found:
        page_id = by_point.get(str(record.id))
        provenance = (record.payload or {}).get("provenance") or {}
        key = str(provenance.get("embed_key") or "")
        held_vectors = record.vector if isinstance(record.vector, dict) else {}
        vector = held_vectors.get(DENSE_VECTOR)
        if page_id and key and vector:
            held[page_id] = (key, list(vector))
    _log.info("embed_cache_probe", collection=name, asked=len(wanted), held=len(held))
    return held


def count(client: Any, name: str, scope: Mapping[str, Any] | None = None) -> int:
    """An exact count under an indexed scope (I6). An unindexed key raises rather than scanning."""
    if not client.collection_exists(name):
        return 0
    conditions = scope_conditions(scope)
    return client.count(name, count_filter=qm.Filter(must=conditions) if conditions else None,
                        exact=True).count


__all__ = [
    "CAPTIONS", "FORBIDDEN_PAYLOAD_KEYS", "LEXICAL", "CollectionState", "DuplicatePage",
    "FingerprintMismatch", "IndexRefused", "PublishedBeforeGates", "Upserted", "VectorMissing",
    "build_point", "cached_vectors", "caption_text", "count", "ensure_collection", "upsert",
]
