"""L0 — sparse vectors (D2). BM25 term weights, and `dedupe` so nothing counts twice."""
from __future__ import annotations

import math

import pytest

from vsir.config import (
    BM25_AVG_LEN_CAPTIONS,
    BM25_AVG_LEN_LEXICAL,
    BM25_B,
    BM25_K1,
    SPARSE_VERSION,
)
from vsir.ingest import sparse

#: A length that makes the normaliser exactly 1, so a weight can be read by eye.
AVERAGE = 4.0

#: The lexical branch of `SICK-DETECTOR-BOX@3.0`, reduced to what it scores:
#: ``(page_no, |D|, tf(safeguard) == tf(detector), tf(individual), tf(sensors))``.
#:
#: Token counts through the shipped :func:`vsir.core.tok.tok` over the frozen page text of the one
#: real 56-page ingest. The two brand tokens share a column because they are equal on all 56
#: pages — the document never says one without the other — so their df, and therefore their idf,
#: are equal too and one column scored twice is exact rather than an approximation.
LEXICAL_BRANCH: tuple[tuple[int, int, int, int, int], ...] = (
    (1, 28, 1, 0, 0), (2, 146, 2, 0, 0), (3, 263, 1, 0, 2), (4, 205, 3, 0, 1),
    (5, 282, 4, 0, 3), (6, 160, 1, 0, 0), (7, 475, 8, 0, 5), (8, 397, 2, 0, 1),
    (9, 290, 4, 0, 0), (10, 423, 5, 0, 4), (11, 377, 8, 1, 8), (12, 59, 2, 0, 1),
    (13, 419, 2, 0, 3), (14, 454, 1, 0, 9), (15, 472, 1, 0, 4), (16, 219, 1, 0, 0),
    (17, 256, 1, 0, 13), (18, 397, 1, 0, 7), (19, 118, 1, 0, 0), (20, 103, 1, 0, 0),
    (21, 120, 1, 0, 0), (22, 512, 2, 1, 3), (23, 155, 1, 0, 0), (24, 358, 3, 0, 6),
    (25, 223, 1, 0, 1), (26, 64, 1, 0, 0), (27, 399, 2, 0, 4), (28, 73, 1, 0, 0),
    (29, 503, 2, 0, 9), (30, 62, 1, 0, 0), (31, 377, 4, 0, 1), (32, 599, 1, 0, 0),
    (33, 558, 1, 0, 1), (34, 84, 1, 0, 0), (35, 154, 1, 0, 1), (36, 369, 1, 0, 0),
    (37, 70, 1, 0, 0), (38, 287, 3, 0, 3), (39, 320, 1, 0, 0), (40, 216, 1, 0, 0),
    (41, 239, 1, 0, 0), (42, 111, 1, 0, 0), (43, 88, 1, 0, 0), (44, 67, 1, 0, 0),
    (45, 213, 11, 0, 1), (46, 254, 2, 1, 1), (47, 141, 1, 0, 0), (48, 485, 1, 0, 1),
    (49, 423, 1, 0, 0), (50, 478, 1, 0, 0), (51, 204, 2, 0, 1), (52, 179, 5, 0, 1),
    (53, 40, 1, 0, 0), (54, 40, 1, 0, 0), (55, 40, 1, 0, 0), (56, 514, 0, 0, 1),
)

#: `tok("Safeguard Detector individual sensors")`, as columns of :data:`LEXICAL_BRANCH`.
QUERY_COLUMNS = (2, 2, 3, 4)        # safeguard, detector, individual, sensors

#: The only page of the 56 that prints `individual sensors` — the page the query is about.
PRINTS_THE_PHRASE = 46


def _idf(column: int) -> float:
    """Qdrant's ``Modifier.IDF``: ``ln(1 + (N − n + 0.5) / (n + 0.5))``.

    Computed here from the same table the weights are, so the test holds one corpus rather than a
    corpus and a remembered number about it. This is the half of the score that stays Qdrant's —
    :mod:`vsir.ingest.sparse` never computes it, which is the whole of D2's anti-staleness argument.
    """
    total = len(LEXICAL_BRANCH)
    carrying = sum(1 for page in LEXICAL_BRANCH if page[column])
    return math.log(1 + (total - carrying + 0.5) / (carrying + 0.5))


def _ranked(weight) -> list[int]:
    """Page numbers best-first, scoring ``Σ idf(t) · weight(tf(t,D), |D|)`` over the query's terms.

    ``weight`` is what the two sides disagreed about: the shipped document vector supplies
    :func:`~vsir.ingest.sparse.saturated`, the version this fix replaced supplied ``tf`` itself.
    The query side contributes ``q(t) = 1`` and so does not appear.
    """
    idf = {column: _idf(column) for column in set(QUERY_COLUMNS)}
    scored = [
        (sum(idf[column] * weight(page[column], page[1])
             for column in QUERY_COLUMNS if page[column]), page[0])
        for page in LEXICAL_BRANCH
    ]
    return [page_no for _, page_no in sorted(scored, key=lambda row: (-row[0], row[1]))]


def test_the_pinned_bm25_parameters():
    """These four numbers are the recipe `sparse_version` names.

    Changing one without bumping `SPARSE_VERSION` would leave the §6.6 fingerprint agreeing with a
    collection it no longer describes — the exact silent failure the fingerprint exists to prevent.
    """
    assert BM25_K1 == 1.2
    assert BM25_B == 0.75
    assert BM25_AVG_LEN_LEXICAL == 256.0
    assert BM25_AVG_LEN_CAPTIONS == 16.0
    assert SPARSE_VERSION == "bm25-v1"


def test_a_term_once_in_an_average_length_document_weighs_exactly_one():
    """The anchor the rest of the suite is read against."""
    assert sparse.saturated(1, int(AVERAGE), avg_len=AVERAGE) == pytest.approx(1.0)


def test_three_occurrences_are_worth_less_than_three_times_one():
    """The defect this module was rewritten for: raw counts let repetition buy rank.

    Under raw term frequency these values were `[1.0, 3.0]`, so a page saying `sensors` thirteen
    times beat a page printing the phrase that was actually asked for.
    """
    indices, values = sparse.build_document("K158 K158 K158 SI3", avg_len=AVERAGE)

    assert len(indices) == len(values) == 2
    assert sorted(values) == [pytest.approx(1.0), pytest.approx(3.0 * 2.2 / (3.0 + 1.2))]
    assert max(values) < 3.0


def test_a_long_document_is_penalised_and_a_short_one_is_not():
    """Length normalisation — what lets a compact table page compete with a page of prose."""
    short = sparse.saturated(1, 2, avg_len=AVERAGE)
    average = sparse.saturated(1, 4, avg_len=AVERAGE)
    long = sparse.saturated(1, 16, avg_len=AVERAGE)

    assert short > average > long


def test_the_weight_is_bounded_by_k1_plus_one():
    """Saturation: the thousandth occurrence is worth almost nothing over the tenth."""
    assert sparse.saturated(1000, 4, avg_len=AVERAGE) < BM25_K1 + 1.0
    assert sparse.saturated(10, 4, avg_len=AVERAGE) < sparse.saturated(1000, 4, avg_len=AVERAGE)


def test_the_page_that_prints_the_phrase_loses_to_pages_that_repeat_a_common_word():
    """The reported failure, re-measured over the document that produced it.

    Page 46 of the UE410 operating instructions — 1,390 characters, 254 tokens — is the **only**
    page in 56 that prints `individual sensors`, and under raw term frequency the query
    *"Safeguard Detector individual sensors"* ranked it **9th**, behind prose pages repeating
    `sensors` 13, 9, 9 and 8 times. Rare terms already carried the IDF; what was missing was any
    reason for one occurrence on a short page to outweigh thirteen on a long one.

    `LEXICAL_BRANCH` is that document, reduced to what the branch actually scores. It is the
    measurement rather than the text because the S2 receipts it came from are a paid artefact and
    are not in the repository — :doc:`fixes/005 <../../../fixes/005-the-lexical-surface-ranks-by-repetition>`
    records the one-liner that re-derives it.
    """
    ranked = _ranked(lambda tf, length: tf)          # raw term frequency, as shipped before
    assert ranked.index(PRINTS_THE_PHRASE) + 1 == 9, "the defect, so the fix cannot regress"
    assert ranked[:4] == [17, 11, 29, 14], "and the pages that beat it, by repetition alone"

    ranked = _ranked(lambda tf, length: sparse.saturated(
        tf, length, avg_len=BM25_AVG_LEN_LEXICAL))
    assert ranked.index(PRINTS_THE_PHRASE) + 1 == 2


def test_the_fix_is_saturation_and_length_together_not_either_alone():
    """Both halves of the tf component are load-bearing, which is why `b` is not 0 and `k1` not ∞.

    Saturation alone (`b=0`, no length normalisation) still leaves the phrase page behind three
    pages of prose; length normalisation without saturation over-rewards the repetition it is
    dividing. Neither is the reported failure fixed, and a later reader trimming one of the two
    parameters "because BM25's defaults are arbitrary" gets a red test rather than worse rank.
    """
    saturation_only = _ranked(lambda tf, length: sparse.saturated(
        tf, length, avg_len=BM25_AVG_LEN_LEXICAL, b=0.0))
    length_only = _ranked(lambda tf, length: tf / (1.0 - BM25_B + BM25_B * length / 256.0))

    assert saturation_only.index(PRINTS_THE_PHRASE) + 1 > 2
    assert length_only.index(PRINTS_THE_PHRASE) + 1 > 2


def test_the_query_side_carries_presence_and_never_a_count():
    """`q(t) = 1` is what makes what Qdrant computes exactly BM25."""
    indices, values = sparse.build_query("K158 K158 K158 SI3")

    assert len(indices) == 2
    assert values == [1.0, 1.0]


def test_the_query_side_does_not_saturate_because_qdrant_would_apply_k1_twice():
    """The document vector already carries the tf component; doing it again would double it."""
    _, short = sparse.build_query("K158")
    _, padded = sparse.build_query("K158 " + " ".join(f"w{n}" for n in range(200)))

    assert short == [1.0]
    assert set(padded) == {1.0}


def test_an_avg_len_of_zero_is_refused_rather_than_dividing_by_it():
    """Unchecked this is a ZeroDivisionError in step 10 — after the whole S2 and embedding spend."""
    with pytest.raises(ValueError, match="avg_len"):
        sparse.saturated(1, 10, avg_len=0.0)
    with pytest.raises(ValueError, match="avg_len"):
        sparse.build_document("K158", avg_len=-1.0)


def test_the_refusal_does_not_wait_for_a_page_that_has_text():
    """A scanned document's first pages have none, and that must not decide when the guard fires."""
    with pytest.raises(ValueError, match="avg_len"):
        sparse.build_document("", avg_len=0.0)


def test_build_is_gone_so_no_caller_can_pick_the_wrong_weighting():
    """A surviving `build()` would be a plausible name that silently produces the old defect.

    The document and query sides need different weights and both mistakes present identically, as
    worse neighbours. A stale call site should be an AttributeError, not a wrong float in a vector.
    """
    assert not hasattr(sparse, "build")


def test_indices_are_sorted_as_qdrant_requires():
    indices, _ = sparse.build_document(
        "the quick brown fox jumps over the lazy dog", avg_len=AVERAGE)

    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)


def test_the_slot_is_stable_across_processes():
    """A slot that moved between releases would make every stored vector mean something else."""
    assert sparse.slot("k158") == sparse.slot("k158")
    assert sparse.slot("k158") != sparse.slot("k159")
    assert 0 <= sparse.slot("k158") < (1 << 31)


def test_empty_text_is_an_empty_vector_not_a_crash():
    assert sparse.build_document("", avg_len=AVERAGE) == ([], [])
    assert sparse.build_document("   ...   ", avg_len=AVERAGE) == ([], [])
    assert sparse.build_query("") == ([], [])


def test_tokenisation_agrees_with_the_phrase_index():
    """§5.6 — the lexical surface must not find pages the exact surface cannot confirm."""
    from vsir.core.tok import tok

    indices, _ = sparse.build_document("84-5140.0020", avg_len=AVERAGE)

    assert len(indices) == len(set(tok("84-5140.0020"))) == 3


def test_every_weight_is_finite_and_positive():
    """An all-zero sparse vector is stored, indexed and scored; a NaN would rank unpredictably."""
    _, values = sparse.build_document("K158 SI3 K158 emergency stop", avg_len=AVERAGE)

    assert all(math.isfinite(value) and value > 0 for value in values)


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
    assert sparse.build_document(
        sparse.dedupe("K158", against="K158"), avg_len=BM25_AVG_LEN_CAPTIONS) == ([], [])
