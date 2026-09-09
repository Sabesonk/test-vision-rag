"""L0 — sparse vectors (D2). Raw term frequencies, and `dedupe` so nothing counts twice."""
from __future__ import annotations

from vsir.ingest import sparse


def test_values_are_raw_term_frequencies():
    """Qdrant applies IDF at query time, so ingesting a document must not stale existing vectors."""
    indices, values = sparse.build("K158 K158 K158 SI3")

    assert sorted(values) == [1.0, 3.0]
    assert len(indices) == len(values) == 2


def test_indices_are_sorted_as_qdrant_requires():
    indices, _ = sparse.build("the quick brown fox jumps over the lazy dog")

    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)


def test_the_slot_is_stable_across_processes():
    """A slot that moved between releases would make every stored vector mean something else."""
    assert sparse.slot("k158") == sparse.slot("k158")
    assert sparse.slot("k158") != sparse.slot("k159")
    assert 0 <= sparse.slot("k158") < (1 << 31)


def test_empty_text_is_an_empty_vector_not_a_crash():
    assert sparse.build("") == ([], [])
    assert sparse.build("   ...   ") == ([], [])


def test_tokenisation_agrees_with_the_phrase_index():
    """§5.6 — the lexical surface must not find pages the exact surface cannot confirm."""
    from vsir.core.tok import tok

    indices, _ = sparse.build("84-5140.0020")

    assert len(indices) == len(set(tok("84-5140.0020"))) == 3


def test_dedupe_strips_what_the_verbatim_text_already_carries():
    """Register D3 — without this, one piece of evidence enters fusion twice, the generated copy
    weighted like printed text."""
    caption = "Emergency stop circuit for K158 with reset"
    text = "K158 emergency stop"

    assert sparse.dedupe(caption, against=text) == "circuit for with reset"


def test_dedupe_is_case_insensitive_because_the_index_is_lowercased():
    assert sparse.dedupe("K158 RESET", against="k158") == "reset"


def test_a_caption_that_adds_nothing_dedupes_to_nothing():
    assert sparse.dedupe("K158 emergency", against="emergency K158 stop") == ""
    assert sparse.build(sparse.dedupe("K158", against="K158")) == ([], [])
