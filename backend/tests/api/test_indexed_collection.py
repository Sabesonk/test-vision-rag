"""L2 — the collection `INDEXED` creates, asserted against a real Qdrant (Spec §5.4, §5.5, I6).

These parameters cannot be checked in a unit test, because what matters is what **Qdrant** reports
back: `phrase_matching` is the mechanism the whole exact surface rests on, and a client-side
constant saying it was requested is not evidence that the index has it.
"""
from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from vsir.core.indexed import (
    DENSE_VECTOR,
    INDEXED,
    SPARSE_VECTORS,
    TEXT_FIELDS,
    TEXT_INDEX_PARAMS,
    create_collection,
    schema_problems,
)

EMBED_DIM = 1536


@pytest.fixture
def scratch(qdrant: QdrantClient):
    """A collection of this test's own, so a schema experiment cannot disturb another test."""
    name = f"vsir_pages_scratch_{EMBED_DIM}"
    create_collection(qdrant, name, EMBED_DIM, recreate=True)
    try:
        yield name
    finally:
        qdrant.delete_collection(name)


def test_the_live_collection_agrees_with_indexed(qdrant, scratch):
    """I6's assertion job: the dict that created it is the dict it is checked against."""
    assert schema_problems(qdrant, scratch, EMBED_DIM) == []


def test_every_indexed_key_has_a_live_payload_index(qdrant, scratch):
    schema = qdrant.get_collection(scratch).payload_schema

    assert set(schema) == set(INDEXED), "the live schema and INDEXED must be the same set"


@pytest.mark.parametrize("field", TEXT_FIELDS)
def test_both_text_surfaces_have_phrase_matching(qdrant, scratch, field):
    """§5.5 — `"SF 1.1A"` must become the phrase `[sf, 1, 1a]`.

    Without `phrase_matching`, any-order matching returns every page carrying `sf` and `1`: not a
    slow path, a wrong answer (F1). `min_token_len=1` is what keeps `SI3`, `84` and `0020`.
    """
    params = qdrant.get_collection(scratch).payload_schema[field].params

    assert params.phrase_matching is True
    assert params.tokenizer == qm.TokenizerType.WORD
    assert params.lowercase is True
    assert params.min_token_len == 1
    assert TEXT_INDEX_PARAMS.min_token_len == 1


def test_the_dense_vector_is_cosine_at_the_configured_dimension(qdrant, scratch):
    vectors = qdrant.get_collection(scratch).config.params.vectors

    assert vectors[DENSE_VECTOR].size == EMBED_DIM
    assert vectors[DENSE_VECTOR].distance == qm.Distance.COSINE


def test_both_sparse_surfaces_use_qdrant_side_idf(qdrant, scratch):
    """D2 — only BM25's tf half is stored, so a new document does not stale every vector.

    The modifier is what makes the stored floats a ranking at all: the idf factor is never computed
    locally, which is why ingesting a document changes no value already written.
    """
    sparse = qdrant.get_collection(scratch).config.params.sparse_vectors

    assert set(sparse) == set(SPARSE_VECTORS) == {"lexical", "captions"}
    for name in SPARSE_VECTORS:
        assert sparse[name].modifier == qm.Modifier.IDF


def test_the_collection_name_carries_the_dimension(qdrant):
    """§5.5 — comparing dims is two collections, not two named vectors."""
    name = "vsir_pages_dimcheck_768"
    create_collection(qdrant, name, 768, recreate=True)
    try:
        assert qdrant.get_collection(name).config.params.vectors[DENSE_VECTOR].size == 768
        assert schema_problems(qdrant, name, 768) == []
        # The same collection read as if it were the 1536 one is a mismatch, not a coincidence.
        assert schema_problems(qdrant, name, 1536) != []
    finally:
        qdrant.delete_collection(name)


def test_creating_an_existing_collection_is_a_no_op(qdrant, scratch):
    """`vsir doctor --create-collection` must be safe to run twice."""
    assert create_collection(qdrant, scratch, EMBED_DIM) is False
    assert schema_problems(qdrant, scratch, EMBED_DIM) == []


def test_a_missing_collection_is_reported_not_crashed(qdrant):
    problems = schema_problems(qdrant, "vsir_pages_absent_1536", EMBED_DIM)

    assert problems == ["collection 'vsir_pages_absent_1536' does not exist"]


@pytest.mark.parametrize("field", ["text", "vlm_codes", "doc_id", "page_no", "is_current"])
def test_dropping_any_payload_index_is_detected_by_name(qdrant, scratch, field):
    """I6 — the drift a half-finished migration leaves behind is named, never absorbed."""
    qdrant.delete_payload_index(scratch, field_name=field)

    problems = schema_problems(qdrant, scratch, EMBED_DIM)

    assert problems, f"dropping {field!r} went unnoticed"
    assert any(field in problem for problem in problems)


def test_a_text_field_indexed_without_phrase_matching_is_detected(qdrant, scratch):
    """The subtlest drift: the index exists, is a text index, and is still wrong."""
    qdrant.delete_payload_index(scratch, field_name="text")
    qdrant.create_payload_index(
        scratch, field_name="text",
        field_schema=qm.TextIndexParams(type="text", tokenizer=qm.TokenizerType.WORD,
                                        lowercase=True, phrase_matching=False, min_token_len=1),
    )

    problems = schema_problems(qdrant, scratch, EMBED_DIM)

    assert any("phrase_matching" in problem for problem in problems)


def test_a_text_field_indexed_as_a_keyword_is_detected(qdrant, scratch):
    """A keyword index on `text` would make `lookup` silently exact-string-only."""
    qdrant.delete_payload_index(scratch, field_name="text")
    qdrant.create_payload_index(scratch, field_name="text",
                                field_schema=qm.PayloadSchemaType.KEYWORD)

    problems = schema_problems(qdrant, scratch, EMBED_DIM)

    assert any("expected 'text'" in problem for problem in problems)


def test_the_payload_indexes_exist_before_the_first_point(qdrant, scratch):
    """Ported reasoning from `impl/app/segstore.py`, and it is not cosmetic.

    Filterable HNSW builds extra graph edges from indexed payload values *as points arrive*. Index
    after the data and those edges are simply not there: the filter still answers, from a worse
    graph, and nothing tells you. So a freshly created collection must already be fully indexed.
    """
    info = qdrant.get_collection(scratch)

    assert info.points_count == 0
    assert set(info.payload_schema) == set(INDEXED)
