"""L2 — the differential test of Spec §5.6: does `tok()` agree with **Qdrant's** WORD tokenizer?

This is the test that stops the quietest failure in the system. `verify` reasons in Python about
what the index matched. If `tok()` and Qdrant disagree by a single token, `verify` reports *present*
where the index found nothing, or *absent* where it found the page — and neither half looks wrong on
its own.

Qdrant exposes no "tokenize this" endpoint, so the comparison is behavioural, which is stronger
than a string comparison would be: the labels are indexed, and then a phrase **built from `tok()`'s
output** is asked of the real index. If Qdrant tokenised differently, the phrase would not match.

It lives at L2 rather than L0 because it needs a live `qdrant/qdrant:v1.19.0` — which is the point:
a Qdrant upgrade that changed the tokenizer fails this build rather than silently changing what
`verify` believes.
"""
from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from vsir.core import ids
from vsir.core.indexed import DENSE_VECTOR, TEXT_INDEX_PARAMS
from vsir.core.tok import tok

#: Every shape the corpus prints, plus the near-misses the abstention eval uses.
LABELS = [
    "SF 1.1A", "SF1.1A", "SF 1.1 A", "SF121.1)", "SF 330.1",
    "84-5140.0020", "X20SI4100", "SI3", "SI4", "K158", "K73", "K78", "K700",
    "0020", "84", "alarm 152", "Q25/K153", "B221 --> K158 - SI3", "PL d / Cat. 3",
    "però EMERGENZA", "E-stop", "3",
]

COLLECTION = "vsir_tokenizer_differential"


@pytest.fixture(scope="module")
def indexed_labels(qdrant: QdrantClient) -> dict[str, str]:
    """One point per label, its `text` the label verbatim, with the real §5.5 text index."""
    if qdrant.collection_exists(COLLECTION):
        qdrant.delete_collection(COLLECTION)
    qdrant.create_collection(
        collection_name=COLLECTION,
        vectors_config={DENSE_VECTOR: qm.VectorParams(size=2, distance=qm.Distance.COSINE)},
    )
    qdrant.create_payload_index(COLLECTION, field_name="text", field_schema=TEXT_INDEX_PARAMS)

    point_ids = {}
    points = []
    for index, label in enumerate(LABELS, start=1):
        page_id = ids.page_id("TOK", "1", index)
        point_ids[label] = ids.point_id(page_id)
        points.append(qm.PointStruct(id=point_ids[label], vector={DENSE_VECTOR: [0.0, 1.0]},
                                     payload={"text": label, "page_id": page_id}))
    qdrant.upsert(COLLECTION, points=points, wait=True)
    try:
        yield point_ids
    finally:
        qdrant.delete_collection(COLLECTION)


def _matches(qdrant: QdrantClient, phrase: str) -> set[str]:
    """The point ids whose `text` matches ``phrase`` as a phrase."""
    found, offset = set(), None
    while True:
        page, offset = qdrant.scroll(
            COLLECTION,
            scroll_filter=qm.Filter(must=[qm.FieldCondition(
                key="text", match=qm.MatchPhrase(phrase=phrase))]),
            limit=64, offset=offset, with_payload=False,
        )
        found.update(str(point.id) for point in page)
        if offset is None:
            return found


@pytest.mark.parametrize("label", LABELS)
def test_a_phrase_built_from_tok_matches_the_page_that_prints_the_label(qdrant, indexed_labels,
                                                                       label):
    """The differential: our token sequence is the one Qdrant indexed, in that order."""
    phrase = " ".join(tok(label))

    assert indexed_labels[label] in _matches(qdrant, phrase), (
        f"Qdrant did not match {phrase!r} on a page whose text is {label!r}: "
        f"tok() and the WORD tokenizer disagree"
    )


@pytest.mark.parametrize("label", LABELS)
def test_the_label_itself_matches_as_a_phrase(qdrant, indexed_labels, label):
    assert indexed_labels[label] in _matches(qdrant, label)


def test_a_dotted_part_number_is_split_by_qdrant_too(qdrant, indexed_labels):
    """§2.4's porting hazard, proved against the index rather than asserted about a regex.

    `impl`'s `TOKEN_RE` kept `84-5140.0020` as one token. If Qdrant did the same, a three-token
    phrase could not match — so this passing is the evidence that the phrase mechanism is required.
    """
    assert tok("84-5140.0020") == ["84", "5140", "0020"]
    assert indexed_labels["84-5140.0020"] in _matches(qdrant, "84 5140 0020")


def test_a_reordered_phrase_does_not_match(qdrant, indexed_labels):
    """A phrase is about order. This is what makes `MatchText` unusable here (F1)."""
    assert indexed_labels["SF 1.1A"] not in _matches(qdrant, "1a 1 sf")
    assert indexed_labels["84-5140.0020"] not in _matches(qdrant, "0020 5140 84")


def test_a_phrase_with_an_extra_token_does_not_match(qdrant, indexed_labels):
    assert indexed_labels["SF 1.1A"] not in _matches(qdrant, "sf 1 9 1a")


def test_a_near_miss_code_matches_nothing_but_itself(qdrant, indexed_labels):
    """F16 — `K73` and `K78` are both indexed, and neither can be found by the other's phrase."""
    assert _matches(qdrant, "k73") == {indexed_labels["K73"]}
    assert _matches(qdrant, "k78") == {indexed_labels["K78"]}


def test_short_tokens_survive_the_index(qdrant, indexed_labels):
    """`min_token_len=1` is what keeps `SI3`, `84`, `0020` and a bare `3` findable (§5.5)."""
    for label in ("SI3", "84", "0020", "3"):
        assert indexed_labels[label] in _matches(qdrant, label.lower())


def test_an_accented_token_is_one_token_in_the_index_too(qdrant, indexed_labels):
    """The corpus is Italian: a tokenizer that split `però` would lose Italian pages."""
    assert tok("però EMERGENZA") == ["però", "emergenza"]
    assert indexed_labels["però EMERGENZA"] in _matches(qdrant, "però emergenza")


def test_the_index_is_case_folded_like_tok(qdrant, indexed_labels):
    assert indexed_labels["K158"] in _matches(qdrant, "k158")
    assert indexed_labels["K158"] in _matches(qdrant, "K158")
