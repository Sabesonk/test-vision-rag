"""L2 — step 10 against a real ``qdrant/qdrant:v1.19.0`` (Spec §6.1 step 10, §6.6, I1, I7).

What needs a live store rather than a fake: the payload indexes that exist on the collection, the
three named vector surfaces, whether an omitted sparse surface is really absent, and that a point
written ``is_current=False`` is genuinely unreachable through the filter every tool injects. All
four are properties of Qdrant, not of our code, and a fake would only restate our belief about
them.

The collection here is this module's own, created and dropped around the suite, so nothing it
writes can be read by another L2 suite — and the control plane it fingerprints is its own too.
"""
from __future__ import annotations

import ast
import math
import uuid
from pathlib import Path

import pytest
from qdrant_client.http import models as qm

from vsir.core.indexed import INDEXED, schema_problems
from vsir.core.record import PageRecord
from vsir.core.tok import tok, token_set
from vsir.eval import synthetic
from vsir.ingest import fingerprint as fingerprint_module
from vsir.ingest import index as index_module
from vsir.ingest.fingerprint import Fingerprint, FingerprintMismatch

EMBED_DIM = 8
COLLECTION = f"vsir_pages_upsert_{EMBED_DIM}"
RUNS = "vsir_runs_upsert"
MODULE = Path(index_module.__file__)


def fingerprint(embed_model: str = "gemini-embedding-2") -> Fingerprint:
    return Fingerprint(embed_model=embed_model, dim=EMBED_DIM)


def as_stored(vector: list[float]) -> list[float]:
    """What Qdrant gives back for a cosine vector: the **normalised** one.

    Qdrant normalises on write for `Distance.COSINE`, because cosine similarity of unit vectors is
    a dot product and pre-normalising makes every query cheaper. So a round trip is not the
    identity, and a test that expected it to be would be asserting something Qdrant never
    promised. The direction is preserved, which is the whole content of a cosine vector.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else list(vector)


@pytest.fixture(scope="module")
def records() -> tuple[PageRecord, ...]:
    """The §13 M1 corpus, forced back to ``is_current=False`` — which is what step 10 writes.

    The corpus is checked in with the flag already flipped, because M1 seeds a collection that has
    to answer. Step 10 is the other side of that: nothing is queryable until the gates run (I7),
    so a record arriving here still claiming to be current is refused, and the corpus is put back
    into the state the pipeline would actually hand over.
    """
    corpus = synthetic.load()
    return tuple(record.model_copy(update={"is_current": False})
                 for record in corpus.records(release_id="test-0"))


@pytest.fixture(scope="module")
def vectors(records: tuple[PageRecord, ...]) -> dict[str, list[float]]:
    """One distinct unit-ish vector per page. The values do not matter; the wiring does."""
    return {record.page_id: [float((index + position) % 7) / 7.0 for position in range(EMBED_DIM)]
            for index, record in enumerate(records)}


@pytest.fixture(scope="module")
def collection(qdrant, records, vectors) -> str:
    for name in (COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    index_module.ensure_collection(qdrant, name=COLLECTION, dim=EMBED_DIM,
                                   fingerprint=fingerprint(), runs_collection=RUNS)
    index_module.upsert(qdrant, COLLECTION, records, vectors, fingerprint=fingerprint(),
                        runs_collection=RUNS)
    try:
        yield COLLECTION
    finally:
        for name in (COLLECTION, RUNS):
            if qdrant.collection_exists(name):
                qdrant.delete_collection(name)


# ── the collection this module writes into (§5.4, §5.5, C2) ─────────────────────────────────────

def test_the_collection_agrees_with_indexed_before_the_first_point(qdrant, collection):
    """I6 — one dict creates the indexes, gates every filter, and is asserted against the live
    collection. The assertion is the same function `vsir doctor` runs at boot (§4.3)."""
    assert schema_problems(qdrant, collection, EMBED_DIM) == []


def test_the_payload_indexes_are_exactly_indexed_and_nothing_else(qdrant, collection):
    """C2 — `impl`'s curated model-derived keyword index is gone, not merely unused.

    An extra index is not harmless: it is a second surface a filter could reach, and the whole
    exact-match argument rests on there being one (I3). So the live schema is compared for
    equality, which fails on an addition as well as on a removal.
    """
    schema = qdrant.get_collection(collection).payload_schema or {}

    assert set(schema) == set(INDEXED)


def test_the_write_path_has_no_keyword_equality_lookup_at_all(qdrant, collection):
    """The struck index was read by a `MatchValue` on a model-derived key; there is no such call.

    An AST scan rather than a grep, so a name inside a comment or a docstring cannot fail it and
    a call cannot hide behind one. `MatchValue` is legitimate elsewhere (`core/exact.py` builds
    scope conditions with it) — the claim is specifically that **this module** never looks a page
    up by an exact keyword, because the exact surface is the phrase index (§5.5).
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}

    assert "MatchValue" not in called
    assert "MatchAny" not in called


def test_the_dim_is_in_the_collection_name(collection):
    """§5.5 — comparing two dims is two collections, never two named vectors in one."""
    assert collection.endswith(f"_{EMBED_DIM}")


# ── I1: one page, one point ─────────────────────────────────────────────────────────────────────

def test_one_point_per_page_and_the_id_is_uuid5_of_the_page_id(qdrant, collection, records):
    assert qdrant.count(collection, exact=True).count == len(records)

    for record in records:
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, record.page_id))
        found = qdrant.retrieve(collection, ids=[expected], with_payload=True)
        assert found, f"no point at uuid5(NAMESPACE_URL, {record.page_id})"
        assert found[0].payload["provenance"]["page_id"] == record.page_id


def test_re_upserting_the_same_records_overwrites_and_the_total_does_not_double(
        qdrant, collection, records, vectors):
    """F12 — `point_id` is derived from the page id, so a re-ingest overwrites in place."""
    before = qdrant.count(collection, exact=True).count

    written = index_module.upsert(qdrant, collection, records, vectors,
                                  fingerprint=fingerprint(), runs_collection=RUNS)

    assert written.count == len(records)
    assert qdrant.count(collection, exact=True).count == before


def test_the_stored_payload_round_trips_back_into_a_page_record(qdrant, collection, records):
    """The payload is the only place the two streams live joined; a lossy write loses evidence."""
    target = records[0]
    stored = qdrant.retrieve(collection, ids=[str(uuid.uuid5(uuid.NAMESPACE_URL,
                                                             target.page_id))],
                             with_payload=True)[0]

    assert PageRecord.from_payload(stored.payload) == target


def test_no_payload_names_a_file(qdrant, collection):
    """Register A5 — a stale `image_path` made `read()` return 503 for every page in `impl`."""
    points, _ = qdrant.scroll(collection, limit=512, with_payload=True)

    for point in points:
        for key in index_module.FORBIDDEN_PAYLOAD_KEYS:
            assert key not in point.payload


# ── I7: nothing is queryable until the gates pass ───────────────────────────────────────────────

def test_every_point_is_written_is_current_false(qdrant, collection, records):
    points, _ = qdrant.scroll(collection, limit=512, with_payload=True)

    assert len(points) == len(records)
    assert all(point.payload["is_current"] is False for point in points)


def test_the_filter_every_tool_injects_finds_nothing_at_all(qdrant, collection):
    """I7 — step 11 is the only thing that flips `is_current`, so this collection cannot answer."""
    current = qm.Filter(must=[qm.FieldCondition(key="is_current",
                                                match=qm.MatchValue(value=True))])

    assert qdrant.count(collection, count_filter=current, exact=True).count == 0


def test_a_record_that_arrives_already_current_is_refused(qdrant, collection, records, vectors):
    presumptuous = records[0].model_copy(update={"is_current": True})

    with pytest.raises(index_module.PublishedBeforeGates) as refusal:
        index_module.upsert(qdrant, collection, [presumptuous], vectors,
                            fingerprint=fingerprint(), runs_collection=RUNS)

    assert refusal.value.code == "is_current_before_gates"


# ── the three surfaces (D2, register D3) ────────────────────────────────────────────────────────

def test_all_three_surfaces_are_declared_on_the_collection(qdrant, collection):
    params = qdrant.get_collection(collection).config.params

    assert set(params.vectors) == {"dense"}
    assert set(params.sparse_vectors) == {"lexical", "captions"}
    assert all(declared.modifier == qm.Modifier.IDF
               for declared in params.sparse_vectors.values())


def test_the_captions_surface_is_actually_written(qdrant, collection, records):
    """Register D3 — `impl` declares it, weights it 0.4 in config, and never writes it."""
    generated = [record for record in records
                 if record.content.summaries or record.content.topics]
    assert generated, "the corpus must have pages with generated text for this to mean anything"

    points, _ = qdrant.scroll(collection, limit=512, with_payload=True, with_vectors=True)
    by_page = {point.payload["provenance"]["page_id"]: point for point in points}

    for record in generated:
        if not index_module.caption_text(record).strip():
            continue
        vector = by_page[record.page_id].vector
        assert "captions" in vector, f"{record.page_id} carries no captions surface"
        assert vector["captions"].values


def test_a_page_whose_generated_text_survives_nothing_has_no_captions_vector(
        qdrant, collection, records, vectors):
    """Absent, not a zero vector: an all-zero sparse vector is still stored, indexed and scored."""
    bare = records[0].model_copy(update={
        "text": "K158 emergency stop",
        "content": records[0].content.model_copy(update={"summaries": [], "topics": []}),
    })

    point = index_module.build_point(bare, vectors[records[0].page_id])

    assert index_module.caption_text(bare) == ""
    assert index_module.CAPTIONS not in point.vector
    assert index_module.LEXICAL in point.vector


def test_a_page_with_no_text_layer_has_no_lexical_vector(qdrant, collection, records, vectors):
    """A scanned page is unsearchable, and an empty surface says so by not being there (F4)."""
    scanned = records[0].model_copy(update={"text": "", "has_text": False,
                                            "text_trust": "no_text"})

    point = index_module.build_point(scanned, vectors[records[0].page_id])

    assert index_module.LEXICAL not in point.vector
    assert "dense" in point.vector


def test_the_captions_surface_double_counts_nothing_the_printed_text_already_carries(records):
    """`sparse.dedupe(against=text)` is what makes the third surface safe to populate (D2)."""
    for record in records:
        generated = index_module.caption_text(record)
        printed = token_set(record.text)

        assert not [term for term in tok(generated) if term in printed]


def test_the_dense_vector_is_stored_under_the_name_the_query_side_uses(qdrant, collection,
                                                                      records, vectors):
    points, _ = qdrant.scroll(collection, limit=8, with_payload=True, with_vectors=True)

    for point in points:
        stored = point.vector["dense"]
        expected = as_stored(vectors[point.payload["provenance"]["page_id"]])
        assert len(stored) == EMBED_DIM
        assert max(abs(a - b) for a, b in zip(stored, expected)) < 1e-6


# ── §6.6: the fingerprint, next to the write ────────────────────────────────────────────────────

def test_the_fingerprint_is_recorded_in_the_control_plane(qdrant, collection):
    stored = fingerprint_module.read(qdrant, RUNS, collection)

    assert stored == fingerprint()
    assert qdrant.get_collection(RUNS).config.params.vectors in ({}, None)


def test_upsert_refused_on_fingerprint_mismatch_writes_zero_points(qdrant, collection, records,
                                                                   vectors):
    """§6.6 — the remedy is a new collection + a full re-embed + an alias swap, never a mix."""
    before = qdrant.count(collection, exact=True).count

    with pytest.raises(FingerprintMismatch) as refusal:
        index_module.upsert(qdrant, collection, records, vectors,
                            fingerprint=fingerprint("some-other-embed-model"),
                            runs_collection=RUNS)

    assert refusal.value.code == "embed_fingerprint_mismatch"
    assert qdrant.count(collection, exact=True).count == before
    assert fingerprint_module.read(qdrant, RUNS, collection) == fingerprint()
    message = str(refusal.value).lower()
    assert "new collection" in message and "re-embed" in message and "alias" in message


def test_ensure_collection_refuses_a_mismatch_before_a_vector_is_bought(qdrant, collection):
    """The refusal has to come first: one after the spend is correct and much more expensive."""
    with pytest.raises(FingerprintMismatch):
        index_module.ensure_collection(qdrant, name=collection, dim=EMBED_DIM,
                                       fingerprint=fingerprint("some-other-embed-model"),
                                       runs_collection=RUNS)


# ── the embedding cache (register B5) and the counts (I6) ───────────────────────────────────────

def test_cached_vectors_returns_the_embed_key_and_the_vector_of_a_written_page(
        qdrant, collection, records, vectors):
    stamped = records[0].model_copy(update={
        "provenance": records[0].provenance.model_copy(update={"embed_key": "a-known-key"})})
    index_module.upsert(qdrant, collection, [stamped], vectors, fingerprint=fingerprint(),
                        runs_collection=RUNS)

    held = index_module.cached_vectors(qdrant, collection, [stamped.page_id])

    assert set(held) == {stamped.page_id}
    key, vector = held[stamped.page_id]
    assert key == "a-known-key"
    assert max(abs(a - b) for a, b in zip(vector, as_stored(vectors[stamped.page_id]))) < 1e-6


def test_a_page_with_no_embed_key_is_not_offered_as_a_cache_hit(qdrant, collection, records,
                                                                vectors):
    """An unstamped point cannot prove which recipe made its vector, so it is not reusable.

    Written here rather than read off the corpus: whether a *particular* corpus page carries a key
    depends on which other test wrote it last, and a cache test that depends on test order is not
    testing the cache.
    """
    page_id = f"{records[0].doc_id}@{records[0].revision}#p098"
    unstamped = records[0].model_copy(update={
        "page_no": 98,
        "provenance": records[0].provenance.model_copy(update={"page_id": page_id,
                                                               "embed_key": ""})})
    index_module.upsert(qdrant, collection, [unstamped],
                        {page_id: vectors[records[0].page_id]}, fingerprint=fingerprint(),
                        runs_collection=RUNS)

    assert index_module.cached_vectors(qdrant, collection, [page_id]) == {}


def test_a_missing_collection_is_an_empty_cache_not_a_refusal(qdrant):
    """The first ingest into a fresh collection has nothing to reuse, and that is not a problem."""
    assert index_module.cached_vectors(qdrant, "vsir_pages_does_not_exist", ["A@1#p001"]) == {}
    assert index_module.count(qdrant, "vsir_pages_does_not_exist") == 0


def test_count_under_an_indexed_scope_and_a_refusal_off_it(qdrant, collection, records):
    """I6 — filtering on anything absent from `INDEXED` is a typed refusal, never a slow scan.

    The assertions are relations rather than a total, because several tests in this module write
    their own pages: everything in this collection belongs to the one corpus document, and none of
    it is current. Both are true whatever order the suite runs in.
    """
    from vsir.core.exact import UnknownScopeKey

    total = index_module.count(qdrant, collection)

    assert total >= len(records)
    assert index_module.count(qdrant, collection, {"doc_id": records[0].doc_id}) == total
    assert index_module.count(qdrant, collection, {"is_current": True}) == 0
    assert index_module.count(qdrant, collection, {"doc_id": "no-such-document"}) == 0

    with pytest.raises(UnknownScopeKey):
        index_module.count(qdrant, collection, {"printed_page_no": "Page 1 of 55"})


# ── the refusals that keep a partial document out of the index ──────────────────────────────────

def test_two_records_for_one_page_are_refused(qdrant, collection, records, vectors):
    with pytest.raises(index_module.DuplicatePage) as refusal:
        index_module.upsert(qdrant, collection, [records[0], records[0]], vectors,
                            fingerprint=fingerprint(), runs_collection=RUNS)

    assert refusal.value.details["page_id"] == records[0].page_id


def test_a_record_with_no_vector_is_refused_rather_than_skipped(qdrant, collection, records):
    """`impl` skipped a record whose vector was None and reported the write as successful."""
    with pytest.raises(index_module.VectorMissing):
        index_module.upsert(qdrant, collection, [records[0]], {}, fingerprint=fingerprint(),
                            runs_collection=RUNS)


def test_a_refusal_partway_through_writes_none_of_the_batch(qdrant, collection, records, vectors):
    """Every point is built before the first one is sent, so there is no half-written document."""
    before = qdrant.count(collection, exact=True).count
    fresh = records[0].model_copy(update={
        "page_no": 99, "provenance": records[0].provenance.model_copy(
            update={"page_id": f"{records[0].doc_id}@{records[0].revision}#p099"})})

    with pytest.raises(index_module.VectorMissing):
        index_module.upsert(qdrant, collection, [*records, fresh], vectors,
                            fingerprint=fingerprint(), runs_collection=RUNS)

    assert qdrant.count(collection, exact=True).count == before


def test_an_empty_write_is_zero_points_and_no_call(qdrant, collection):
    written = index_module.upsert(qdrant, collection, [], {}, fingerprint=fingerprint(),
                                  runs_collection=RUNS)

    assert written.count == 0
    assert written.points == ()
