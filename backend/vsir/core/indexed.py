"""``INDEXED`` — one dict, three jobs (Spec §5.4, I6), and the collection it creates (§5.5).

The same module-level dict **creates** the payload indexes, **gates** every filter, and is
**asserted** against the live collection at boot. One dict, because two would drift: a filter on a
field that was never indexed does not fail in Qdrant, it runs an unindexed scan and skips the
filterable-HNSW path. The result is a smaller answer that looks like a complete one — F10, silent
recall loss — which is why filtering on anything absent from this dict is a typed ``400`` and never
a slow path.

Adapted from ``impl/app/segstore.py``, and its single most load-bearing comment is carried across
verbatim in :func:`create_collection`: **the payload indexes must exist before the first point**.
Filterable HNSW builds extra graph edges from indexed payload values as points arrive; index
afterwards and those edges are simply not there.

Two changes from `impl`: its curated exact-match keyword index — a payload field holding
model-derived identifier keys — is **gone**, replaced by the phrase-matching ``text`` index over
extracted text (C2, §5.5); and ``is_current`` is added, because a run that has not passed its gates
must not be able to answer (I7). The struck field's name is one of the §12.5 conformance greps, so
it is described here rather than spelled.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Iterable

from qdrant_client.http import models as qm

from vsir.config import DISTANCE

#: Spec §5.4, verbatim. Immutable: a seventeenth key added at runtime would be a field that the
#: creation loop never indexed and the boot assertion never checked.
#:
#: ``keyword[]`` marks an **array** field. Qdrant needs no separate array type — a keyword index
#: matches any element — but the suffix is a standing warning: a single scalar in `section_id` or
#: `series_id` is exactly how F8 happens (§5.3).
INDEXED: MappingProxyType = MappingProxyType({
    "doc_id": "keyword", "revision": "keyword", "is_current": "bool", "doc_type": "keyword",
    "subjects": "keyword", "tags": "keyword", "page_kind": "keyword", "lang": "keyword",
    "page_no": "integer", "section_id": "keyword[]", "series_id": "keyword[]",
    "has_text": "bool", "text_trust": "keyword", "run_id": "keyword",
    "text": "text", "vlm_codes": "text",
})

#: The two text surfaces. Reachable only through `lookup` and `verify` — never as a caller filter.
TEXT_FIELDS = ("text", "vlm_codes")

#: The named vectors of §5.5. `dense` is the one fused image+text embedding per page (D4); the two
#: sparse surfaces store BM25 term weights — tf saturation and length normalisation, applied at
#: index time — and let Qdrant supply the IDF factor at query time (D2).
DENSE_VECTOR = "dense"
SPARSE_VECTORS = ("lexical", "captions")

_PAYLOAD_SCHEMA = {
    "keyword": qm.PayloadSchemaType.KEYWORD,
    "keyword[]": qm.PayloadSchemaType.KEYWORD,
    "integer": qm.PayloadSchemaType.INTEGER,
    "bool": qm.PayloadSchemaType.BOOL,
}

#: §5.5 — `phrase_matching` is what makes the whole design viable: `"SF 1.1A"` becomes the phrase
#: `[sf, 1, 1a]`, which is precise, where any-order matching returns every page carrying `sf` and
#: `1`. `min_token_len=1` keeps `SI3`, `84` and `0020`.
TEXT_INDEX_PARAMS = qm.TextIndexParams(
    type="text",
    tokenizer=qm.TokenizerType.WORD,
    lowercase=True,
    phrase_matching=True,
    min_token_len=1,
)


def scope_keys() -> frozenset[str]:
    """The filterable keys: ``INDEXED`` minus the two text surfaces (§5.4).

    `text` and `vlm_codes` are reachable only through `lookup` and `verify`, which own the one
    exact-match code path. Exposing them as caller-supplied filters would be a second one.
    """
    return frozenset(INDEXED) - set(TEXT_FIELDS)


def reject_unknown_keys(keys: Iterable[str]) -> list[str]:
    """The unfilterable keys in ``keys``, sorted. Empty means every key is indexed (I6)."""
    return sorted(set(keys) - scope_keys())


def vectors_config(dim: int) -> dict[str, qm.VectorParams]:
    return {DENSE_VECTOR: qm.VectorParams(size=dim, distance=qm.Distance.COSINE)}


def sparse_vectors_config() -> dict[str, qm.SparseVectorParams]:
    # IDF is computed by Qdrant across the collection at query time. Storing only the tf half is
    # what keeps a new document from staling every vector already in the index (D2). The modifier
    # must stay IDF: the stored values are BM25's tf component and are not a ranking without it.
    return {name: qm.SparseVectorParams(modifier=qm.Modifier.IDF) for name in SPARSE_VECTORS}


def create_collection(client: Any, name: str, dim: int, *, recreate: bool = False) -> bool:
    """Create the collection and all of its indexes. Returns False if it already existed.

    Ordering is not cosmetic: **the payload indexes are created before the first point**, because
    filterable HNSW builds its extra graph edges from indexed payload values as points arrive. Add
    an index after the data and those edges are simply not there — the filter still answers, just
    from a worse graph, and nothing tells you (ported from `impl/app/segstore.py`).
    """
    if recreate and client.collection_exists(name):
        client.delete_collection(name)
    if client.collection_exists(name):
        return False

    client.create_collection(
        collection_name=name,
        vectors_config=vectors_config(dim),
        sparse_vectors_config=sparse_vectors_config(),
    )
    for field, kind in INDEXED.items():
        if kind == "text":
            client.create_payload_index(name, field_name=field, field_schema=TEXT_INDEX_PARAMS)
        else:
            client.create_payload_index(name, field_name=field,
                                        field_schema=_PAYLOAD_SCHEMA[kind])
    return True


def schema_problems(client: Any, name: str, dim: int) -> list[str]:
    """Every way the live collection disagrees with ``INDEXED``. Empty means it agrees (§4.3).

    This is the assertion half of I6, and it is why the dict is the only source: a field that
    stopped being indexed — a dropped index, a hand-edited collection, a half-finished migration —
    turns into a named boot refusal instead of a quietly narrower answer.
    """
    problems: list[str] = []
    if not client.collection_exists(name):
        return [f"collection {name!r} does not exist"]

    info = client.get_collection(name)
    schema = info.payload_schema or {}

    for field, kind in INDEXED.items():
        present = schema.get(field)
        if present is None:
            problems.append(f"payload index missing: {field!r} ({kind})")
            continue
        if kind == "text":
            problems.extend(_text_index_problems(field, present))
        else:
            expected = _PAYLOAD_SCHEMA[kind].value
            actual = getattr(present.data_type, "value", str(present.data_type))
            if actual != expected:
                problems.append(f"payload index {field!r} is {actual!r}, expected {expected!r}")

    problems.extend(_vector_problems(info, dim))
    return problems


def _text_index_problems(field: str, present: Any) -> list[str]:
    """`text` and `vlm_codes` must be text indexes with phrase matching (§4.3 refusal 4)."""
    problems: list[str] = []
    actual_type = getattr(present.data_type, "value", str(present.data_type))
    if actual_type != "text":
        return [f"payload index {field!r} is {actual_type!r}, expected 'text'"]

    params = present.params
    if params is None:
        return [f"payload index {field!r} reports no text index parameters"]
    checks = (
        ("phrase_matching", True),
        ("lowercase", True),
        ("min_token_len", TEXT_INDEX_PARAMS.min_token_len),
    )
    for attribute, expected in checks:
        actual = getattr(params, attribute, None)
        if actual != expected:
            problems.append(
                f"payload index {field!r}: {attribute}={actual!r}, expected {expected!r}"
            )
    tokenizer = getattr(getattr(params, "tokenizer", None), "value", None)
    if tokenizer != qm.TokenizerType.WORD.value:
        problems.append(
            f"payload index {field!r}: tokenizer={tokenizer!r}, expected "
            f"{qm.TokenizerType.WORD.value!r} — tok() mirrors Qdrant's WORD tokenizer (§5.6)"
        )
    return problems


def _vector_problems(info: Any, dim: int) -> list[str]:
    """The observable half of the §6.6 fingerprint: the dim and the distance the vectors declare.

    ``embed_model`` and ``composition_version`` are not observable from Qdrant, so the model half
    of the fingerprint is checked against the record written beside the collection (U010). The dim
    is also carried in the collection name, so a dim change is already a different collection.
    """
    problems: list[str] = []
    params = info.config.params
    vectors = params.vectors if isinstance(params.vectors, dict) else {}
    dense = vectors.get(DENSE_VECTOR)
    if dense is None:
        problems.append(f"named vector missing: {DENSE_VECTOR!r}")
    else:
        if dense.size != dim:
            problems.append(f"vector {DENSE_VECTOR!r} has size {dense.size}, expected {dim}")
        distance = getattr(dense.distance, "value", str(dense.distance))
        if distance.lower() != DISTANCE:
            problems.append(f"vector {DENSE_VECTOR!r} distance is {distance!r}, expected "
                            f"{DISTANCE!r}")

    sparse = params.sparse_vectors or {}
    for name in SPARSE_VECTORS:
        declared = sparse.get(name)
        if declared is None:
            problems.append(f"sparse vector missing: {name!r}")
            continue
        modifier = getattr(getattr(declared, "modifier", None), "value", None)
        if modifier != qm.Modifier.IDF.value:
            problems.append(
                f"sparse vector {name!r}: modifier={modifier!r}, expected "
                f"{qm.Modifier.IDF.value!r} — the stored values are BM25's tf component and "
                f"need Qdrant-side IDF to be a ranking at all (D2)"
            )
    return problems
