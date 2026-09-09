"""L0 — the observed-token inventory (Spec §6.8, C7, F16, I2).

The inventory is the only structure in the system built with a *heuristic*, so these tests are
about the two properties that make a heuristic safe here: it can only ever be read as a prefix
lookup, and it can only ever contain tokens the text layer actually carries.

The second one is I2 at one remove. `present_instead` says *"K73 is not on this page; K78 is"*, and
if a model's claimed code could enter this inventory, a hallucinated code could be disclosed as the
thing that is really there — a wrong answer arriving through the mechanism that exists to prevent
wrong answers.
"""
from __future__ import annotations

import pytest

from vsir.core.observed_tokens import Inventory, from_records, from_texts, is_code_like
from vsir.core.tok import token_set
from vsir.eval import synthetic


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def inventory(corpus: synthetic.Corpus) -> Inventory:
    return from_records(corpus.current_records())[corpus.doc_id]


# ── the heuristic (§6.8) ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("token", ["k158", "0020", "5b", "1a", "84", "3", "si3", "x20si4100"])
def test_a_token_with_a_digit_is_code_like(token):
    assert is_code_like(token) is True


@pytest.mark.parametrize("token", ["emergency", "quantity", "sf", "eao", "pl", ""])
def test_a_token_without_a_digit_is_not(token):
    """Deliberately not a grammar (§5.2 prohibits one): a miss costs a disclosure, not an answer."""
    assert is_code_like(token) is False


# ── building ────────────────────────────────────────────────────────────────────────────────────

def test_the_inventory_is_sorted_unique_and_code_like_only():
    built = from_texts("D", ["Contactor K158 and K158 again", "emergency stop, rail 3"])

    # `K158` is one token, not `k` + `158`: the WORD tokenizer splits on punctuation, never
    # between a letter and a digit (§5.6). That is why `variants()` exists at all.
    assert built.tokens == ("3", "k158")
    assert list(built.tokens) == sorted(built.tokens)


def test_a_page_with_no_text_layer_contributes_nothing():
    """Correct rather than a gap: nothing was observed on a page nothing was extracted from."""
    assert from_texts("D", ["", "   ", "\n"]).tokens == ()


def test_from_records_groups_by_doc_id():
    records = [{"doc_id": "A", "text": "K158"}, {"doc_id": "B", "text": "Q25"},
               {"doc_id": "A", "text": "K162"}]

    built = from_records(records)

    assert sorted(built) == ["A", "B"]
    assert built["A"].tokens == ("k158", "k162")
    assert built["B"].tokens == ("q25",)


def test_from_records_accepts_a_record_or_a_payload(corpus):
    records = corpus.current_records()

    from_models = from_records(records)[corpus.doc_id]
    from_payloads = from_records([record.to_payload() for record in records])[corpus.doc_id]

    assert from_models == from_payloads


# ── the prefix lookup, and nothing but the prefix lookup (F16) ──────────────────────────────────

def test_starting_with_returns_only_prefix_matches(inventory):
    assert inventory.starting_with("k7") == ("k78",)
    assert inventory.starting_with("k1") == ("k158", "k162", "k166")
    assert inventory.starting_with("si") == ("si3",)


def test_starting_with_is_a_prefix_and_never_a_distance(inventory):
    """`K73` is one character from `K78` and is not a prefix of it, so it finds nothing.

    That is the whole of F16's guard: the only way another code can be disclosed beside an
    `absent` verdict is if the claim is a *prefix* of it. There is no edit distance in the system,
    so a near-miss cannot be returned as the match (§7.6).
    """
    assert inventory.starting_with("k73") == ()
    assert inventory.starting_with("k79") == ()
    assert "k73" not in inventory


def test_an_empty_prefix_discloses_nothing(inventory):
    """*"Every code in the document"* is not a disclosure about a claim."""
    assert inventory.starting_with("") == ()


def test_the_prefix_lookup_is_case_insensitive(inventory):
    assert inventory.starting_with("K7") == inventory.starting_with("k7")


def test_every_result_actually_starts_with_the_prefix(inventory):
    """The property, over every prefix of every token in the corpus's own inventory."""
    for token in inventory.tokens:
        for length in range(1, len(token) + 1):
            prefix = token[:length]
            found = inventory.starting_with(prefix)
            assert token in found
            assert all(candidate.startswith(prefix) for candidate in found)


# ── the corpus's inventory is exactly its text (§6.8, I2) ───────────────────────────────────────

def test_the_inventory_is_every_code_like_token_of_the_text_and_nothing_else(corpus, inventory):
    expected = corpus.expected["observed_tokens"]
    every_word = {word for record in corpus.current_records() for word in token_set(record.text)}

    assert len(inventory) == expected["count"]
    assert set(inventory.tokens) == {word for word in every_word if is_code_like(word)}
    assert all(token in every_word for token in inventory.tokens)


def test_the_declared_members_are_there_and_the_declared_absences_are_not(corpus, inventory):
    expected = corpus.expected["observed_tokens"]

    for token in expected["includes"]:
        assert token in inventory, f"{token} is printed in the corpus"
    for token in expected["excludes"]:
        assert token not in inventory, f"{token} is not a token of the text surface"


def test_a_model_claimed_code_never_enters_the_inventory(corpus, inventory):
    """I2 — the inventory is built from `text`, so `K999` cannot be disclosed as present.

    The page that claims it is in the corpus and its `vlm_codes` carries the code; only the text
    surface is read, so the claim is invisible here.
    """
    claimed = {code.lower() for record in corpus.current_records() for code in record.content.codes}

    assert "k999" in claimed
    assert "k999" not in inventory
    assert inventory.starting_with("k99") == ()


def test_an_inventory_is_frozen_and_holds_no_client(inventory):
    """§15 Factor VI — cacheable, serialisable, and carrying nothing that could go stale."""
    with pytest.raises(Exception):
        inventory.tokens = ()          # type: ignore[misc]

    assert set(vars(inventory)) == {"doc_id", "tokens"}
