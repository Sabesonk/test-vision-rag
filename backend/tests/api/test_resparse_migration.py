"""L2 — the `sparse_version` migration against a real ``qdrant/qdrant:v1.19.0`` (plan §4c **P10**).

What needs a live store rather than a fake, and what `tests/unit/test_resparse.py` therefore does
not claim:

* that :meth:`update_vectors` really **replaces** a named sparse vector rather than merging into it
  — a wrong answer here would leave old and new weights summed on the same slots, which is not a
  state any assertion about our own code could discover;
* that :meth:`delete_vectors` really removes one, and that the point survives it;
* that the dense vector and the payload come through a vector-only update untouched — the claim
  that makes this migration cheap is precisely that it does not re-embed;
* and the round trip that is the point of the whole exercise: a collection this release **refuses
  at boot** is accepted afterwards, with no model call in between.

The collection is this module's own, created and dropped around the suite, and its control plane
is its own too — so nothing here can restamp a collection another L2 suite is reading.
"""
from __future__ import annotations

from typing import Any, Iterator

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from vsir.config import SPARSE_VERSION
from vsir.core.indexed import DENSE_VECTOR, create_collection
from vsir.core.record import PageRecord
from vsir.eval import synthetic
from vsir.ingest import fingerprint as fingerprint_module
from vsir.ingest import index as index_module
from vsir.ingest.fingerprint import Fingerprint, FingerprintMismatch
from vsir.ingest.resparse import UnsupportedMigration, rebuild_sparse

EMBED_DIM = 8
COLLECTION = f"vsir_pages_resparse_{EMBED_DIM}"
RUNS = "vsir_runs_resparse"

CONFIGURED = Fingerprint(embed_model="gemini-embedding-2", dim=EMBED_DIM)
OLD_SPARSE = Fingerprint(embed_model="gemini-embedding-2", dim=EMBED_DIM,
                         sparse_version="raw-term-frequency")


def dense_of(record: PageRecord) -> list[float]:
    """A stand-in dense vector that is a function of the page, so a change to one is visible."""
    return [float((hash(record.page_id) >> shift) % 7 + 1) for shift in range(EMBED_DIM)]


@pytest.fixture(scope="module")
def records() -> tuple[PageRecord, ...]:
    return tuple(record.model_copy(update={"is_current": False})
                 for record in synthetic.load().records())


@pytest.fixture
def seeded(qdrant: QdrantClient, records: tuple[PageRecord, ...]) -> Iterator[QdrantClient]:
    """The collection as `fixes/005` found it: raw term counts, and the old recipe recorded.

    Built by writing the shipped points and then overwriting both sparse surfaces with raw counts
    — the pre-`fixes/005` weights. The slots are identical either way (a slot is a hash of a term),
    so this is exactly the state a real pre-BM25 collection is in: right indices, wrong values.
    """
    create_collection(qdrant, COLLECTION, EMBED_DIM, recreate=True)
    if qdrant.collection_exists(RUNS):
        qdrant.delete_collection(RUNS)

    points = [index_module.build_point(record, dense_of(record)) for record in records]
    qdrant.upsert(COLLECTION, points=points, wait=True)

    raw: list[qm.PointVectors] = []
    for point in points:
        counts = {name: qm.SparseVector(indices=list(vector.indices),
                                        values=[1.0] * len(vector.indices))
                  for name, vector in point.vector.items()
                  if isinstance(vector, qm.SparseVector)}
        if counts:
            raw.append(qm.PointVectors(id=point.id, vector=counts))
    if raw:
        qdrant.update_vectors(collection_name=COLLECTION, points=raw, wait=True)
    fingerprint_module.write(qdrant, RUNS, COLLECTION, OLD_SPARSE)
    try:
        yield qdrant
    finally:
        qdrant.delete_collection(COLLECTION)
        if qdrant.collection_exists(RUNS):
            qdrant.delete_collection(RUNS)


def surfaces_of(client: QdrantClient, point_id: str) -> dict[str, Any]:
    found = client.retrieve(COLLECTION, ids=[point_id], with_payload=True,
                            with_vectors=[DENSE_VECTOR, index_module.LEXICAL,
                                          index_module.CAPTIONS])
    assert found, point_id
    return found[0]


def migrate(client: QdrantClient, **overrides: Any):
    return rebuild_sparse(client, pages_collection=COLLECTION, runs_collection=RUNS,
                          configured=CONFIGURED, **overrides)


def test_a_refused_collection_is_servable_afterwards_with_no_model_call(seeded, records):
    """The round trip P10 is about: refused at boot, migrated, accepted — and nothing re-embedded.

    The refusal is taken from :func:`vsir.ingest.fingerprint.require`, the gate the write path
    itself uses, rather than from a restatement of it here. Before the migration it raises; after,
    it returns the recipe this release would write.
    """
    with pytest.raises(FingerprintMismatch) as refusal:
        fingerprint_module.require(seeded, runs_collection=RUNS, pages_collection=COLLECTION,
                                   fingerprint=CONFIGURED)
    assert refusal.value.details["differences"]["sparse_version"] == \
        [OLD_SPARSE.sparse_version, SPARSE_VERSION]

    report = migrate(seeded)

    assert report.scanned == len(records)
    assert report.fingerprint_written is True
    settled = fingerprint_module.require(seeded, runs_collection=RUNS,
                                         pages_collection=COLLECTION, fingerprint=CONFIGURED)
    assert settled.sparse_version == SPARSE_VERSION
    assert settled.digest == CONFIGURED.digest


def test_update_vectors_replaces_the_sparse_weights_rather_than_merging_them(seeded, records):
    """Qdrant's own behaviour, and the one a fake cannot vouch for.

    If a named sparse vector were merged rather than replaced, the migrated weights would be the
    BM25 value *plus* the raw count on every slot — a collection that looks migrated, scores
    wrongly, and whose fingerprint says it is fine.
    """
    migrate(seeded)

    moved = 0
    for record in records:
        expected = index_module.sparse_vectors(record)
        if index_module.LEXICAL not in expected:
            continue
        stored = surfaces_of(seeded, index_module.build_point(record, dense_of(record)).id)
        lexical = stored.vector[index_module.LEXICAL]
        assert list(lexical.indices) == list(expected[index_module.LEXICAL].indices)
        assert lexical.values == pytest.approx(expected[index_module.LEXICAL].values), (
            f"{record.page_id}: the stored weights must be BM25's tf component alone — a merge "
            f"would show up here as every value being too large by exactly the old raw count")
        moved += sum(1 for value in lexical.values if abs(value - 1.0) > 1e-9)

    assert moved > 0, (
        "every migrated weight came back as the 1.0 the fixture seeded, so this test would pass "
        "against a migration that did nothing at all — the seeded state and the expected one have "
        "to differ for any of the assertions above to mean anything")


def test_the_dense_vector_and_the_payload_survive_the_migration_untouched(seeded, records):
    """The claim that makes this cheap: a vector-only update re-embeds nothing and rewrites no text.

    The dense vector is asserted as Qdrant stores it — normalised on write for `Distance.COSINE` —
    by reading it back before and after rather than by recomputing, so the comparison is of one
    stored value with another.
    """
    sampled = [index_module.build_point(record, dense_of(record)).id for record in records[:5]]
    before = {point_id: surfaces_of(seeded, point_id) for point_id in sampled}

    migrate(seeded)

    for point_id in sampled:
        after = surfaces_of(seeded, point_id)
        assert after.vector[DENSE_VECTOR] == pytest.approx(before[point_id].vector[DENSE_VECTOR])
        assert after.payload == before[point_id].payload


def test_an_emptied_surface_is_really_deleted_and_the_point_survives(seeded, records):
    """`delete_vectors` removes the named surface only — the page is still there, still findable."""
    target = next(record for record in records if index_module.CAPTIONS
                  in index_module.sparse_vectors(record))
    point_id = index_module.build_point(target, dense_of(target)).id
    seeded.set_payload(COLLECTION, payload={"content": {
        **target.content.model_dump(mode="json"), "summaries": [], "topics": []}},
        points=[point_id], wait=True)

    report = migrate(seeded)

    assert (str(point_id), index_module.CAPTIONS) in report.surfaces_dropped
    stored = surfaces_of(seeded, point_id)
    assert index_module.CAPTIONS not in stored.vector, "the stale generated surface is gone"
    assert index_module.LEXICAL in stored.vector, "and only that surface was touched"
    assert stored.payload["provenance"]["page_id"] == target.page_id
    assert seeded.count(COLLECTION, exact=True).count == len(records), "no point was lost"


def test_a_dry_run_changes_nothing_in_a_real_collection(seeded, records):
    """A rehearsal against the live store: same counts, and the collection is still refused."""
    point_ids = [index_module.build_point(record, dense_of(record)).id for record in records]
    before = {point_id: surfaces_of(seeded, point_id) for point_id in point_ids}

    planned = migrate(seeded, dry_run=True)

    for point_id in point_ids:
        after = surfaces_of(seeded, point_id)
        for name, vector in before[point_id].vector.items():
            if isinstance(vector, qm.SparseVector):
                assert after.vector[name].values == pytest.approx(vector.values)
            else:
                assert after.vector[name] == pytest.approx(vector)
    assert fingerprint_module.read(seeded, RUNS, COLLECTION).sparse_version == \
        OLD_SPARSE.sparse_version
    assert planned.updated == migrate(seeded).updated


def test_a_second_run_refuses_because_the_collection_is_already_current(seeded):
    migrate(seeded)
    with pytest.raises(UnsupportedMigration) as refusal:
        migrate(seeded)
    assert "nothing to rebuild" in str(refusal.value)
