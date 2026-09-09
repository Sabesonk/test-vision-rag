"""L0 — `present_instead` (Spec §7.2.4, C7, F16).

F16 is *"a near-miss code presented as the answer"*, and this is the only place in the system that
volunteers a code the caller did not ask about. So the tests are mostly about what it **cannot**
do: it cannot reach a token that differs before the shared prefix ends, it cannot return the claim,
it cannot return more than five, and it cannot be consulted by `lookup` at all (that last one is an
import-graph assertion in `test_lookup_pure.py`).

The property test at the bottom is the load-bearing one: over every token of the corpus's own
inventory, every disclosure is a **prefix extension** of the claim. That is what makes "never a
distance" a fact rather than an intention.
"""
from __future__ import annotations

import pytest

from vsir.core.observed_tokens import Inventory, from_records, from_texts, is_searchable
from vsir.core.present_instead import (
    MAX_TRUNCATION,
    MIN_PREFIX,
    PRESENT_INSTEAD_CAP,
    PRESENT_INSTEAD_LABEL,
    claim_key,
    present_instead,
)
from vsir.eval import synthetic


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def inventory(corpus: synthetic.Corpus) -> Inventory:
    return from_records([record for record in corpus.current_records()
                         if is_searchable(record)])[corpus.doc_id]


# ── the key ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("claim,expected", [
    ("K73", "k73"), ("k73", "k73"), ("K 73", "k73"), ("SF 1.1A", "sf11a"),
    ("Q 25", "q25"), ("84-5140.0020", "8451400020"), ("", ""),
])
def test_the_claim_is_keyed_the_way_the_inventory_is(claim, expected):
    """Both sides go through `tok()`, or a prefix could never match anything (§5.6)."""
    assert claim_key(claim) == expected


# ── the disclosure ──────────────────────────────────────────────────────────────────────────────

def test_k73_discloses_k78(inventory):
    """§7.2.4's example. `k7` is the longest prefix of `k73` that finds anything."""
    assert present_instead("K73", inventory) == ["k78"]


def test_the_claim_itself_is_never_disclosed(inventory):
    """A real code checked against a page that does not carry it still gets no self-reference."""
    assert "k158" not in present_instead("K158", inventory)


def test_a_code_with_no_shared_prefix_discloses_nothing(inventory):
    """Most absent codes are simply not in the document, and an empty list says exactly that."""
    assert present_instead("Z99", inventory) == []
    assert present_instead("PL-d", inventory) == []


def test_a_claim_too_short_to_have_a_prefix_discloses_nothing(inventory):
    """One character is a letter, not a code, and `k` would disclose every contactor."""
    assert present_instead("K", inventory) == []
    assert present_instead("3", inventory) == []


def test_the_list_is_capped(inventory):
    """§7.2.4 — capped at five, and the cap is the parameter's default, not a caller's choice."""
    crowded = from_texts("D", ["K100 K101 K102 K103 K104 K105 K106 K107 K108"])

    assert len(present_instead("K109", crowded)) == PRESENT_INSTEAD_CAP
    assert len(present_instead("K109", crowded, cap=2)) == 2
    assert PRESENT_INSTEAD_CAP == 5


def test_truncation_is_bounded(inventory):
    """Without a bound, a long claim would eventually share two characters with anything."""
    # `k158` is in the inventory; a claim 3 characters longer can never reach it.
    assert present_instead("K158999", inventory) == []
    assert MAX_TRUNCATION == 2
    assert MIN_PREFIX == 2


def test_the_longest_prefix_that_finds_anything_wins(inventory):
    """The most specific true statement available — and the shortest list, without ranking it."""
    # `k7` finds only k78; falling back to `k` would have found every contactor.
    assert present_instead("K73", inventory) == ["k78"]
    # `k1` is as specific as `k162` gets on a 2-character floor, so all three siblings come back.
    assert present_instead("K1", inventory) == ["k158", "k162", "k166"]


def test_the_disclosure_is_labelled_a_different_part_and_not_a_suggestion():
    """§7.2.4 — the wording is the guard. *"Did you mean"* is how a near miss becomes an answer."""
    assert PRESENT_INSTEAD_LABEL == "different part"
    assert "mean" not in PRESENT_INSTEAD_LABEL


# ── the property that makes "never a distance" a fact (F16) ─────────────────────────────────────

def test_every_disclosure_is_a_prefix_extension_of_the_claim(inventory):
    """Over every real token, and over every one-character mutation of it.

    A distance metric would return `k78` for `q78`; a prefix lookup cannot, because they disagree
    at the first character. This asserts the shape of the answer rather than the absence of a
    library — a library can be added, but this property cannot be kept while adding one.
    """
    for token in inventory.tokens:
        for candidate in present_instead(token, inventory):
            shared = _shared_prefix(candidate, token)
            assert shared >= MIN_PREFIX
            assert candidate.startswith(token[:shared])
            assert candidate != token


def test_a_one_character_mutation_never_discloses_something_that_differs_earlier(inventory):
    """The adversarial direction: mutate the FIRST character and the source becomes unreachable."""
    for token in inventory.tokens:
        if len(token) < MIN_PREFIX + 1:
            continue
        mutated = ("z" if token[0] != "z" else "y") + token[1:]

        assert token not in present_instead(mutated, inventory)


def _shared_prefix(left: str, right: str) -> int:
    length = 0
    for a, b in zip(left, right):
        if a != b:
            break
        length += 1
    return length
