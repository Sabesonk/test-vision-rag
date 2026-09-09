"""L0 — the near-miss generator (Spec §12.4, OQ-4).

The generator is the input to the one test whose failure means the system produced the injury the
whole design exists to prevent, so its own properties have to be assertions rather than intentions:
exactly one character differs, no fake is a real code, every source came from the observed-token
inventory, and the same corpus always produces the same sample.

The last one is not cosmetic. A safety test that samples differently on each run turns a real,
reproducible defect into an intermittent build — and an intermittent build is one somebody
eventually re-runs until it passes.
"""
from __future__ import annotations

import pytest

from vsir.core.nearmiss import (
    ALPHABET,
    DEFAULT_SAMPLE,
    MIN_SOURCE_LEN,
    NearMiss,
    is_printed,
    mutations,
    near_misses,
)
from vsir.core.observed_tokens import Inventory, from_records, from_texts, is_searchable
from vsir.eval import synthetic


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def texts(corpus: synthetic.Corpus) -> list[str]:
    return [record.text for record in corpus.current_records() if is_searchable(record)]


@pytest.fixture(scope="module")
def inventory(corpus: synthetic.Corpus, texts: list[str]) -> Inventory:
    return from_texts(corpus.doc_id, texts)


@pytest.fixture(scope="module")
def sample(inventory: Inventory, texts: list[str]) -> tuple[NearMiss, ...]:
    return near_misses(inventory, n=DEFAULT_SAMPLE, texts=texts)


# ── the four properties §12.4 needs ─────────────────────────────────────────────────────────────

def test_a_hundred_near_misses_are_produced(sample):
    assert len(sample) == 100 == DEFAULT_SAMPLE


def test_every_element_differs_from_its_source_by_exactly_one_character(sample):
    """A substitution — never an insertion, a deletion or a transposition."""
    for miss in sample:
        assert len(miss.fake) == len(miss.source)
        assert sum(a != b for a, b in zip(miss.fake, miss.source)) == 1
        assert miss.fake[miss.position] != miss.source[miss.position]
        assert miss.fake[:miss.position] == miss.source[:miss.position]
        assert miss.fake[miss.position + 1:] == miss.source[miss.position + 1:]


def test_every_source_came_from_the_observed_token_inventory(sample, inventory):
    for miss in sample:
        assert miss.source in inventory
        assert len(miss.source) >= MIN_SOURCE_LEN


def test_no_fabricated_code_is_a_real_one(sample, inventory):
    """A mutation that lands on another real code is a code, not a near miss.

    Left in, the eval would fail on a case the corpus created rather than on a defect — which is
    the worst kind of red build, because the correct fix is to change the test.
    """
    for miss in sample:
        assert miss.fake not in inventory


def test_the_sample_is_deterministic(inventory, texts, sample):
    assert near_misses(inventory, n=100, texts=texts) == sample
    assert near_misses(inventory, n=10, texts=texts) == sample[:10]


def test_every_fake_is_distinct(sample):
    assert len({miss.fake for miss in sample}) == len(sample)


# ── the shape of the sample ─────────────────────────────────────────────────────────────────────

def test_no_fabricated_code_is_printed_in_any_spelling(sample, texts):
    """The stronger exclusion, and the reason `texts` exists.

    A candidate can be absent from the token inventory and still be **printed**: `sf5` mutates to
    `sf1`, whose boundary-spaced variant `sf 1` is printed inside `SF 1.1A`. `lookup` returns that
    page and is right to, so asserting on such a candidate would test the corpus rather than the
    system (§5.6, and the recorded `phrase_prefix` row of the fixture).
    """
    for miss in sample:
        assert not is_printed(miss.fake, [_words(text) for text in texts]), miss


def test_a_printed_phrase_is_recognised_as_printed(texts):
    """The exclusion is only worth anything if it would fire: `sf1` is the case that found it."""
    printed = [_words(text) for text in texts]

    assert is_printed("sf1", printed) is True       # `sf 1`, inside `SF 1.1A`
    assert is_printed("SF 1.1A", printed) is True
    assert is_printed("k159", printed) is False


def _words(text: str) -> list[str]:
    from vsir.core.tok import tok
    return tok(text)


def test_the_sample_spreads_across_sources_rather_than_exhausting_one(sample, inventory):
    """A hundred mutations of one code would test one code a hundred times."""
    sources = {miss.source for miss in sample}
    eligible = [token for token in inventory.tokens if len(token) >= MIN_SOURCE_LEN]

    assert len(sources) == len(eligible)
    assert max(sum(1 for miss in sample if miss.source == source) for source in sources) <= 6


def test_the_sample_mutates_more_than_one_position(sample):
    """The last character first — `K73` for `K78` — and not only the last."""
    positions = {miss.position for miss in sample}

    assert len(positions) > 1
    assert 0 in positions, "a first-character mutation is the case a prefix lookup cannot reach"


def test_the_first_mutation_of_a_token_is_at_its_last_character():
    """The realistic misread, and the case where `present_instead` has most to say (F16)."""
    first, position = next(mutations("k78"))

    assert position == 2
    assert first == "k70"


def test_the_alphabet_is_what_the_tokenizer_leaves_in_a_token():
    """Digits and lowercase letters: everything else is a separator (§5.6)."""
    assert ALPHABET == "0123456789abcdefghijklmnopqrstuvwxyz"
    assert not [character for character in ALPHABET if not character.isalnum()]


def test_a_mutation_is_never_the_token_itself():
    assert "k78" not in [fake for fake, _ in mutations("k78")]


# ── the edges ───────────────────────────────────────────────────────────────────────────────────

def test_the_weaker_token_only_exclusion_still_applies_without_texts(inventory):
    """A caller with only an inventory gets the token-level guarantee, and nothing less."""
    without = near_misses(inventory, n=100)

    assert len(without) == 100
    assert not any(miss.fake in inventory for miss in without)


def test_a_corpus_too_small_returns_what_it_can_rather_than_repeating_itself():
    """Fewer than `n` is honest; a padded sample would assert the same case twice."""
    tiny = from_texts("D", ["k78"])

    produced = near_misses(tiny, n=1000)

    assert 0 < len(produced) < 1000
    assert len({miss.fake for miss in produced}) == len(produced)


def test_an_inventory_with_no_long_enough_token_produces_nothing():
    """Better than mutating `3` into `4` and asserting the corpus does not contain a four."""
    short = from_texts("D", ["rail 3 and slot 4"])

    assert near_misses(short, n=10) == ()


def test_zero_is_a_valid_request():
    assert near_misses(from_texts("D", ["k158"]), n=0) == ()
