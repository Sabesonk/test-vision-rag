"""L0 — the `sparse_version` migration (plan §4c **P10**): what it repairs, and what it refuses.

`fixes/005` versioned the sparse recipe, which refuses every older collection at boot. That is the
correct refusal and it had no matching way to say yes, so the only path was delete-and-re-ingest —
which deletes the embedding cache with the collection and turns a change that touches no embedding
into a full live re-embed.

Most of these tests are about the **refusal**, for the same reason the fingerprint suite is. A
migration that rebuilt sparse vectors under any fingerprint change would be worse than none: it
would stamp this release onto a collection whose dense vectors came from another model, and the
only symptom of that is worse neighbours. The one test that matters most is therefore
``test_a_dense_difference_is_refused_and_writes_nothing``.

The live behaviour — that Qdrant really replaces a named sparse vector and really deletes one — is
asserted against `qdrant/qdrant:v1.19.0` by `tests/api/test_resparse_migration.py`. What a fake
buys here is the two things a container makes hard to see: **what was never written**, and **the
order in which the writes happened**.
"""
from __future__ import annotations

from typing import Any

import pytest
from qdrant_client.http import models as qm

from vsir.config import SPARSE_VERSION
from vsir.core.record import PageRecord
from vsir.eval import synthetic
from vsir.ingest import fingerprint as fingerprint_module
from vsir.ingest import index as index_module
from vsir.ingest import resparse as resparse_module
from vsir.ingest.fingerprint import Fingerprint
from vsir.ingest.resparse import (
    CollectionMissing,
    PayloadUnreadable,
    UnsupportedMigration,
    plan_migration,
    rebuild_sparse,
)

PAGES = "vsir_pages_1536"
RUNS = "vsir_runs"

#: What this release would write. The migration's target in every test below.
CONFIGURED = Fingerprint(embed_model="gemini-embedding-2", dim=1536)

#: The same recipe one `SPARSE_VERSION` ago — the state `fixes/005` left every collection in.
OLD_SPARSE = Fingerprint(embed_model="gemini-embedding-2", dim=1536,
                         sparse_version="raw-term-frequency")


class FakePages:
    """A pages collection and its control plane, with a log of every mutating call in order.

    Small on purpose: the questions here are *whether* a write happened, *what order* the writes
    were in, and what a refusal said. ``calls`` is the whole answer to the second — the fingerprint
    write must be last, because that is what makes the collection servable again and it must not be
    able to run over a partial rebuild.
    """

    def __init__(self, records: tuple[PageRecord, ...] = (),
                 stored: Fingerprint | None = OLD_SPARSE) -> None:
        self.points: dict[Any, dict[str, Any]] = {}
        self.vectors: dict[Any, dict[str, qm.SparseVector]] = {}
        self.control: dict[Any, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.collections = {PAGES}
        for record in records:
            point = index_module.build_point(record.model_copy(update={"is_current": False}),
                                             [0.0] * 8)
            self.points[point.id] = dict(point.payload)
            self.vectors[point.id] = {name: value for name, value in point.vector.items()
                                      if isinstance(value, qm.SparseVector)}
        if stored is not None:
            self.collections.add(RUNS)
            self.control[fingerprint_module.point_id(PAGES)] = {
                fingerprint_module.KIND_KEY: fingerprint_module.KIND, "collection": PAGES,
                "digest": stored.digest, **stored.as_dict(),
            }

    # ── the control plane ───────────────────────────────────────────────────────────────────────

    def collection_exists(self, name: str) -> bool:
        return name in self.collections

    def create_collection(self, collection_name: str, **_: Any) -> None:
        self.collections.add(collection_name)

    def create_payload_index(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def retrieve(self, collection: str, ids: list[Any], **_: Any) -> list[Any]:
        return [qm.Record(id=identifier, payload=self.control[identifier])
                for identifier in ids if identifier in self.control]

    def upsert(self, collection_name: str, points: list[Any], **_: Any) -> None:
        assert collection_name == RUNS, "the migration never upserts a page — it updates vectors"
        self.calls.append("fingerprint")
        for point in points:
            self.control[point.id] = dict(point.payload or {})

    # ── the pages collection ────────────────────────────────────────────────────────────────────

    def scroll(self, collection_name: str, limit: int, offset: Any = None,
               **_: Any) -> tuple[list[Any], Any]:
        ordered = list(self.points)
        start = ordered.index(offset) if offset is not None else 0
        window = ordered[start:start + limit]
        following = ordered[start + limit:start + limit + 1]
        return ([qm.Record(id=identifier, payload=self.points[identifier],
                           vector=dict(self.vectors.get(identifier, {})))
                 for identifier in window],
                following[0] if following else None)

    def update_vectors(self, collection_name: str, points: list[Any], **_: Any) -> None:
        self.calls.append(f"update:{len(points)}")
        for point in points:
            self.vectors.setdefault(point.id, {}).update(point.vector)

    def delete_vectors(self, collection_name: str, vectors: list[str], points: list[Any],
                       **_: Any) -> None:
        self.calls.append(f"delete:{vectors[0]}:{len(points)}")
        for identifier in points:
            for name in vectors:
                self.vectors.get(identifier, {}).pop(name, None)

    def close(self) -> None:
        return None


@pytest.fixture(scope="module")
def records() -> tuple[PageRecord, ...]:
    return synthetic.load().records()


def migrate(store: FakePages, **overrides: Any):
    return rebuild_sparse(store, pages_collection=PAGES, runs_collection=RUNS,
                          configured=CONFIGURED, **overrides)


# ── what it refuses (the reason the module exists) ───────────────────────────────────────────────

@pytest.mark.parametrize("stored, field_name", [
    (Fingerprint(embed_model="text-embedding-004", dim=1536,
                 sparse_version="raw-term-frequency"), "embed_model"),
    (Fingerprint(embed_model="gemini-embedding-2", dim=3072,
                 sparse_version="raw-term-frequency"), "dim"),
    (Fingerprint(embed_model="gemini-embedding-2", dim=1536, distance="Dot",
                 sparse_version="raw-term-frequency"), "distance"),
    (Fingerprint(embed_model="gemini-embedding-2", dim=1536,
                 composition_version="d4-fused-v0",
                 sparse_version="raw-term-frequency"), "composition_version"),
])
def test_a_dense_difference_is_refused_and_writes_nothing(records, stored, field_name):
    """A fingerprint differing anywhere but `sparse_version` is refused — even alongside one.

    This is the whole safety argument. Every field here describes how the **dense** vector was
    made, and no stored payload can re-derive one: rebuilding the sparse surfaces and restamping
    the recipe would leave this release's name on vectors another model produced, which is the
    in-place mix §6.6 forbids. Each case carries a `sparse_version` difference *as well*, so what
    is being tested is that a repairable difference does not license an unrepairable one.
    """
    store = FakePages(records, stored=stored)
    before = {identifier: dict(surfaces) for identifier, surfaces in store.vectors.items()}

    with pytest.raises(UnsupportedMigration) as refusal:
        migrate(store)

    assert field_name in refusal.value.details["fields"]
    assert "sparse_version" not in refusal.value.details["fields"], (
        "the repairable field is not what made this refuse, and naming it would send the operator "
        "to the migration that is already refusing them")
    assert "re-embed" in str(refusal.value), "the remedy for a dense change belongs in the message"
    assert store.calls == [], "a refusal writes nothing"
    assert store.vectors == before
    assert store.control[fingerprint_module.point_id(PAGES)]["sparse_version"] == \
        stored.sparse_version, "the stored recipe is untouched, so the boot check goes on refusing"


def test_a_matching_fingerprint_refuses_rather_than_rewriting_every_vector():
    """Running against an already-current collection is a refusal, not a silent full pass.

    A migration that agreed here would rewrite every sparse vector to the value it already holds —
    a full pass over the collection to achieve nothing — and, worse, would make a real migration
    indistinguishable from a no-op in the logs.
    """
    store = FakePages(stored=CONFIGURED)
    with pytest.raises(UnsupportedMigration) as refusal:
        migrate(store)
    assert "nothing to rebuild" in str(refusal.value)
    assert store.calls == []


def test_a_collection_with_no_recorded_fingerprint_is_refused():
    """No stored recipe means nothing to migrate *from*, and adopting this one is an assumption.

    §6.6 exists to stop exactly this being assumed quietly: a collection that merely exists is not
    evidence about which model made its vectors.
    """
    store = FakePages(stored=None)
    with pytest.raises(CollectionMissing) as refusal:
        migrate(store)
    assert "records no fingerprint" in str(refusal.value)
    assert store.calls == []


def test_a_missing_collection_is_refused_rather_than_created():
    store = FakePages(stored=None)
    store.collections.discard(PAGES)
    with pytest.raises(CollectionMissing) as refusal:
        migrate(store)
    assert PAGES in str(refusal.value)
    assert store.calls == []


def test_a_payload_this_release_cannot_read_stops_the_migration(records):
    """One unreadable payload aborts, and the fingerprint is not written.

    Skipping it would leave one page on the old recipe inside a collection stamped with the new
    one — the silent mix again, one page wide, and undetectable afterwards because the stamp says
    it is fine.
    """
    store = FakePages(records)
    corrupt = list(store.points)[1]
    store.points[corrupt] = {"doc_id": "only-this", "not": "a page record"}

    with pytest.raises(PayloadUnreadable) as refusal:
        migrate(store)

    assert refusal.value.details["point_id"] == str(corrupt)
    assert "fingerprint" not in store.calls, (
        "an aborted migration must leave the OLD fingerprint, so the collection stays refused at "
        "boot rather than being published half-rebuilt")
    assert store.control[fingerprint_module.point_id(PAGES)]["sparse_version"] == \
        OLD_SPARSE.sparse_version


# ── what it repairs ──────────────────────────────────────────────────────────────────────────────

def test_the_fingerprint_is_written_last(records):
    """The ordering *is* the crash-safety argument, so it is asserted rather than described.

    Written first, a kill partway would leave a collection claiming this release over vectors half
    of which were made by the old recipe — and nothing would refuse it. Written last, a kill leaves
    the old fingerprint, the boot check goes on refusing, and re-running repairs it.
    """
    store = FakePages(records)
    report = migrate(store, batch=4)

    assert store.calls[-1] == "fingerprint"
    assert store.calls.count("fingerprint") == 1
    assert any(call.startswith("update:") for call in store.calls[:-1])
    assert report.fingerprint_written is True
    assert store.control[fingerprint_module.point_id(PAGES)]["sparse_version"] == SPARSE_VERSION


def test_every_rebuilt_vector_equals_what_a_fresh_ingest_would_write(records):
    """The migrated collection is byte-identical to a re-ingested one, which is the whole claim.

    Asserted against :func:`vsir.ingest.index.sparse_vectors` — the function the write path itself
    calls — rather than against a recomputation here. A test that re-derived BM25 in its own terms
    would pass while the two paths drifted, which is precisely the failure this shares a function
    to prevent.
    """
    store = FakePages(records, stored=OLD_SPARSE)
    # Stand the collection back up in the pre-`fixes/005` state: raw term counts, same slots.
    for record in records:
        identifier = next(key for key, payload in store.points.items()
                          if payload["provenance"]["page_id"] == record.page_id)
        store.vectors[identifier] = {
            name: qm.SparseVector(indices=list(vector.indices),
                                  values=[1.0] * len(vector.indices))
            for name, vector in store.vectors[identifier].items()
        }

    migrate(store)

    for record in records:
        identifier = next(key for key, payload in store.points.items()
                          if payload["provenance"]["page_id"] == record.page_id)
        expected = index_module.sparse_vectors(record)
        rebuilt = store.vectors[identifier]
        assert set(rebuilt) == set(expected), record.page_id
        for name, vector in expected.items():
            assert list(rebuilt[name].indices) == list(vector.indices)
            assert rebuilt[name].values == pytest.approx(vector.values)


def test_the_dense_vector_is_never_read_or_written(records):
    """No dense vector is fetched, so the migration's memory and its bill are both bounded.

    `scroll` names the two sparse surfaces explicitly. The dense vector is 1536 floats per page and
    the migration has no use for one — and a migration that pulled them back would look, in every
    log and every metric, exactly like one that was about to rewrite them.
    """
    asked: list[Any] = []
    store = FakePages(records)
    original = store.scroll

    def spy(collection_name: str, limit: int, offset: Any = None, **kwargs: Any):
        asked.append(kwargs.get("with_vectors"))
        return original(collection_name, limit, offset, **kwargs)

    store.scroll = spy                                          # type: ignore[method-assign]
    migrate(store)

    assert asked, "the collection was scrolled"
    for requested in asked:
        assert set(requested) == {index_module.LEXICAL, index_module.CAPTIONS}


def test_dry_run_writes_nothing_and_leaves_the_collection_refused(records):
    """A rehearsal reports the same counts and moves neither a vector nor the fingerprint."""
    rehearsal = FakePages(records)
    real = FakePages(records)

    planned = migrate(rehearsal, dry_run=True)
    done = migrate(real)

    assert rehearsal.calls == []
    assert planned.fingerprint_written is False
    assert rehearsal.control[fingerprint_module.point_id(PAGES)]["sparse_version"] == \
        OLD_SPARSE.sparse_version, "still refused at boot — a rehearsal is not a migration"
    assert (planned.scanned, planned.updated, planned.untouched) == \
           (done.scanned, done.updated, done.untouched)
    assert planned.lexical_written == done.lexical_written
    assert planned.captions_written == done.captions_written


def test_a_surface_the_new_recipe_scores_no_terms_for_is_deleted_not_left_stale(records):
    """`update_vectors` cannot express removal, so an emptied surface needs an explicit delete.

    Omitting a name from an update means *leave it alone*, which would strand a vector built by the
    old recipe under a collection stamped with the new one — on the one page where the migration
    looked like it had nothing to do.
    """
    store = FakePages(records)
    stranded = next(identifier for identifier, surfaces in store.vectors.items()
                    if index_module.CAPTIONS in surfaces)
    # A page whose generated text the new recipe scores nothing for: empty the source it derives
    # from, leaving the old vector behind on the point.
    store.points[stranded]["content"]["summaries"] = []
    store.points[stranded]["content"]["topics"] = []

    report = migrate(store)

    assert (str(stranded), index_module.CAPTIONS) in report.surfaces_dropped
    assert any(call.startswith(f"delete:{index_module.CAPTIONS}") for call in store.calls)
    assert index_module.CAPTIONS not in store.vectors[stranded]


def test_running_it_twice_is_the_repair_for_a_killed_run(records):
    """Idempotent, because every vector is a pure function of a payload that did not change.

    The second run refuses — the collection is current now — which is the honest outcome and the
    one that keeps a real migration distinguishable from a no-op.
    """
    store = FakePages(records)
    first = migrate(store)
    after = {identifier: {name: list(vector.values) for name, vector in surfaces.items()}
             for identifier, surfaces in store.vectors.items()}

    with pytest.raises(UnsupportedMigration):
        migrate(store)

    assert first.updated > 0
    assert {identifier: {name: list(vector.values) for name, vector in surfaces.items()}
            for identifier, surfaces in store.vectors.items()} == after


def test_every_point_is_scanned_whatever_the_batch_size(records):
    """Batching is a memory bound, never a filter: the scroll must reach the last page."""
    counts = set()
    for batch in (1, 3, len(records), len(records) * 2):
        store = FakePages(records)
        counts.add(migrate(store, batch=batch).scanned)
    assert counts == {len(records)}


def test_sparse_version_is_the_only_field_this_migration_claims():
    """The module's guard is a named constant, so a sixth fingerprint field cannot join by accident.

    If §6.6 grows a field that is *also* derivable from payload, adding it here is a deliberate
    edit with a test behind it — not something a wildcard picks up on the release it lands.
    """
    assert resparse_module.REBUILDABLE == "sparse_version"
    assert resparse_module.REBUILDABLE in fingerprint_module.FIELDS
    assert plan_migration(OLD_SPARSE, CONFIGURED) == {
        "sparse_version": (OLD_SPARSE.sparse_version, SPARSE_VERSION)}
