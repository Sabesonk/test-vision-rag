"""L0 — the embedding fingerprint (Spec §6.6): five fields, one gate, and a refusal that explains.

The failure here is the quietest one in the system. Two families of vector in one cosine space
produce worse neighbours and nothing else: no error, no log line, and afterwards no way to tell
which points belong to which family. So every one of these tests is about the gate *refusing*
rather than about it agreeing.
"""
from __future__ import annotations

from typing import Any

import pytest
from qdrant_client.http import models as qm

from vsir.config import COMPOSITION_VERSION, DISTANCE, load_config
from vsir.ingest import fingerprint as fingerprint_module
from vsir.ingest.fingerprint import Fingerprint, FingerprintMismatch

from conftest import SYNTHETIC_ENV

RUNS = "vsir_runs"
PAGES = "vsir_pages_1536"


class FakeControlPlane:
    """The three calls the control plane makes, and a record of every write.

    Deliberately small: the questions here are *whether* a write happened and what the refusal
    said, so a fake that can be read in one screen is a better witness than a container. The live
    behaviour — a payload-only collection, a keyword index, an idempotent upsert — is asserted
    against `qdrant/qdrant:v1.19.0` by `tests/api/test_index_upsert.py`.
    """

    def __init__(self, existing: dict[str, dict] | None = None) -> None:
        self.collections: dict[str, dict[Any, dict]] = {}
        self.upserts = 0
        self.created: list[str] = []
        self.indexes: list[tuple[str, str]] = []
        if existing is not None:
            self.collections[RUNS] = dict(existing)

    def collection_exists(self, name: str) -> bool:
        return name in self.collections

    def create_collection(self, collection_name: str, **_: Any) -> None:
        self.collections.setdefault(collection_name, {})
        self.created.append(collection_name)

    def create_payload_index(self, collection: str, field_name: str, **_: Any) -> None:
        self.indexes.append((collection, field_name))

    def retrieve(self, collection: str, ids: list[Any], **_: Any) -> list[Any]:
        held = self.collections.get(collection, {})
        return [qm.Record(id=identifier, payload=held[identifier])
                for identifier in ids if identifier in held]

    def upsert(self, collection_name: str, points: list[Any], **_: Any) -> None:
        self.upserts += 1
        held = self.collections.setdefault(collection_name, {})
        for point in points:
            held[point.id] = dict(point.payload or {})


def configured(**overrides: str):
    return load_config({**SYNTHETIC_ENV, **overrides})


def stored(fingerprint: Fingerprint, *, collection: str = PAGES) -> dict[str, dict]:
    return {fingerprint_module.point_id(collection): {
        fingerprint_module.KIND_KEY: fingerprint_module.KIND, "collection": collection,
        "digest": fingerprint.digest, **fingerprint.as_dict()}}


# ── the five fields (§6.6) ───────────────────────────────────────────────────────────────────────

def test_the_fingerprint_is_exactly_the_fields_the_recipe_names():
    """`sparse_version` is the fifth: how the two sparse surfaces are weighted.

    A BM25 collection and a raw-term-frequency one are byte-identical in shape, declare the same
    `Modifier.IDF`, and pass every schema check — they differ only in what the stored floats mean.
    """
    assert fingerprint_module.FIELDS == ("embed_model", "dim", "distance", "composition_version",
                                         "sparse_version")
    assert set(Fingerprint.of(configured()).as_dict()) == set(fingerprint_module.FIELDS)


def test_the_sparse_recipe_moves_the_fingerprint_without_the_model_moving():
    """The same model, the same composition, a different sparse weighting — a different collection."""
    now = Fingerprint.of(configured())
    was = Fingerprint(embed_model=now.embed_model, dim=now.dim, distance=now.distance,
                      composition_version=now.composition_version, sparse_version="tf-v0")

    assert now.digest != was.digest
    assert now.differences(was) == {"sparse_version": ("tf-v0", "bm25-v1")}


def test_a_collection_built_before_the_sparse_recipe_was_recorded_is_refused():
    """The migration behaviour, asserted rather than discovered in production."""
    stored = Fingerprint.of(configured()).as_dict()
    del stored["sparse_version"]

    with pytest.raises(FingerprintMismatch) as refusal:
        Fingerprint.from_mapping(stored)

    assert refusal.value.details["missing"] == ["sparse_version"]


def test_it_is_single_sourced_from_the_configuration():
    """Two places computing the fingerprint is two fingerprints; `doctor` prints this one."""
    cfg = configured()

    assert Fingerprint.of(cfg).as_dict() == cfg.fingerprint
    assert Fingerprint.of(cfg).digest == cfg.fingerprint_id


def test_the_dim_is_in_the_collection_name_and_in_the_fingerprint():
    """§5.5 — comparing two dims is two collections, never two named vectors in one."""
    cfg = configured(VSIR_EMBED_DIM="3072")

    assert cfg.pages_collection.endswith("_3072")
    assert Fingerprint.of(cfg).dim == 3072
    assert Fingerprint.of(cfg).digest != Fingerprint.of(configured()).digest


@pytest.mark.parametrize("override", [
    {"VSIR_EMBED_MODEL": "some-other-embed-model"},
    {"VSIR_EMBED_DIM": "768"},
])
def test_changing_a_configured_input_changes_the_fingerprint(override):
    assert Fingerprint.of(configured(**override)) != Fingerprint.of(configured())


def test_changing_the_composition_changes_the_fingerprint_without_the_model_moving():
    """The field that is easy to leave out is the one this system needs most.

    The vector is a *fused* image+text embedding, so reordering the parts or dropping the raster
    changes every vector while the model id stays put (§5.3, D4). A fingerprint without
    `composition_version` would agree with a collection it no longer describes.
    """
    current = Fingerprint.of(configured())
    reordered = Fingerprint(embed_model=current.embed_model, dim=current.dim,
                            distance=current.distance, composition_version="d4-fused-v2")

    assert reordered.embed_model == current.embed_model
    assert reordered.digest != current.digest
    assert current.differences(reordered) == {
        "composition_version": ("d4-fused-v2", COMPOSITION_VERSION)}


def test_differences_names_every_field_that_moved_and_which_way():
    configured_now = Fingerprint(embed_model="b", dim=768, distance=DISTANCE,
                                 composition_version=COMPOSITION_VERSION)
    was = Fingerprint(embed_model="a", dim=1536, distance=DISTANCE,
                      composition_version=COMPOSITION_VERSION)

    assert configured_now.differences(was) == {"embed_model": ("a", "b"), "dim": (1536, 768)}
    assert configured_now.differences(configured_now) == {}


def test_a_stored_record_missing_a_field_cannot_say_whether_it_matches():
    with pytest.raises(FingerprintMismatch) as refusal:
        Fingerprint.from_mapping({"embed_model": "gemini-embedding-2", "dim": 1536})

    assert refusal.value.details["missing"] == ["distance", "composition_version",
                                                "sparse_version"]


# ── the control point ────────────────────────────────────────────────────────────────────────────

def test_the_control_point_id_is_derived_from_the_collection_name():
    """Derived, so writing the fingerprint twice is an overwrite rather than a second record."""
    assert fingerprint_module.point_id(PAGES) == fingerprint_module.point_id(PAGES)
    assert fingerprint_module.point_id(PAGES) != fingerprint_module.point_id("vsir_pages_3072")

    with pytest.raises(ValueError):
        fingerprint_module.point_id("")


def test_the_control_collection_is_payload_only_and_indexes_its_discriminator():
    """`vsir_runs` holds runs, windows and this; every record says which kind it is (D9)."""
    client = FakeControlPlane()

    assert fingerprint_module.ensure_control_collection(client, RUNS) is True
    assert fingerprint_module.ensure_control_collection(client, RUNS) is False
    assert client.created == [RUNS]
    assert (RUNS, fingerprint_module.KIND_KEY) in client.indexes


def test_reading_a_collection_with_no_fingerprint_is_none_not_a_refusal():
    """The first ingest into a fresh collection has nothing to disagree with."""
    assert fingerprint_module.read(FakeControlPlane(), RUNS, PAGES) is None
    assert fingerprint_module.read(FakeControlPlane({}), RUNS, PAGES) is None


def test_a_control_point_of_another_kind_is_a_refusal_not_a_silent_none():
    client = FakeControlPlane({fingerprint_module.point_id(PAGES): {"kind": "run"}})

    with pytest.raises(FingerprintMismatch) as refusal:
        fingerprint_module.read(client, RUNS, PAGES)

    assert refusal.value.details["kind"] == "run"


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────

def test_require_writes_the_fingerprint_on_first_sight_and_then_agrees():
    client = FakeControlPlane()
    mine = Fingerprint.of(configured())

    assert fingerprint_module.require(client, runs_collection=RUNS, pages_collection=PAGES,
                                      fingerprint=mine) == mine
    assert client.upserts == 1

    assert fingerprint_module.require(client, runs_collection=RUNS, pages_collection=PAGES,
                                      fingerprint=mine) == mine
    assert client.upserts == 1, "agreeing with a stored fingerprint must not rewrite it"


def test_require_refuses_a_mismatch_writes_nothing_and_names_the_remedy():
    """§6.6 — a model change is a new collection + full re-embed + alias swap, never a mix."""
    mine = Fingerprint.of(configured())
    client = FakeControlPlane(stored(mine))

    with pytest.raises(FingerprintMismatch) as refusal:
        fingerprint_module.require(
            client, runs_collection=RUNS, pages_collection=PAGES,
            fingerprint=Fingerprint.of(configured(VSIR_EMBED_MODEL="some-other-embed-model")))

    assert refusal.value.code == "embed_fingerprint_mismatch"
    assert client.upserts == 0, "a refusal must not have updated the stored fingerprint"
    message = str(refusal.value).lower()
    assert "new collection" in message
    assert "re-embed" in message
    assert "alias" in message
    assert refusal.value.details["differences"] == {
        "embed_model": ["gemini-embedding-2", "some-other-embed-model"]}
    assert refusal.value.details["stored"] == mine.as_dict()


def test_the_refusal_carries_both_digests_so_a_log_line_identifies_the_two_recipes():
    mine = Fingerprint.of(configured())
    theirs = Fingerprint.of(configured(VSIR_EMBED_DIM="768"))

    with pytest.raises(FingerprintMismatch) as refusal:
        fingerprint_module.require(client=FakeControlPlane(stored(mine)), runs_collection=RUNS,
                                   pages_collection=PAGES, fingerprint=theirs)

    assert refusal.value.details["stored_digest"] == mine.digest
    assert refusal.value.details["configured_digest"] == theirs.digest
    assert refusal.value.to_payload()["error"] == "embed_fingerprint_mismatch"


def test_two_collections_hold_two_independent_fingerprints():
    """A 768 collection and a 1536 one coexist: the dim is in the name, so they never meet."""
    client = FakeControlPlane()
    small = Fingerprint.of(configured(VSIR_EMBED_DIM="768"))
    large = Fingerprint.of(configured())

    fingerprint_module.require(client, runs_collection=RUNS, pages_collection="vsir_pages_768",
                               fingerprint=small)
    fingerprint_module.require(client, runs_collection=RUNS, pages_collection=PAGES,
                               fingerprint=large)

    assert fingerprint_module.read(client, RUNS, "vsir_pages_768") == small
    assert fingerprint_module.read(client, RUNS, PAGES) == large
