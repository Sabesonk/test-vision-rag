"""L0 — tokenisation (Spec §5.6).

`verify` reasons in Python about what the index matched, so `tok()` and Qdrant's WORD tokenizer
must agree. This layer pins `tok()` against a frozen table of the shapes the corpus actually
prints; `tests/api/test_tokenizer_differential.py` proves that same table is what a live
`qdrant/qdrant:v1.19.0` produces, which is the half that needs Docker.
"""
from __future__ import annotations

import pytest

from vsir.core.tok import MIN_TOKEN_LEN, tok, token_set

#: The shapes this corpus prints: safety functions, part numbers, IO channels, relays, alarms.
GOLDEN = {
    "SF 1.1A": ["sf", "1", "1a"],
    "SF1.1A": ["sf1", "1a"],
    "SF121.1)": ["sf121", "1"],
    "84-5140.0020": ["84", "5140", "0020"],
    "X20SI4100": ["x20si4100"],
    "SI3": ["si3"],
    "K158": ["k158"],
    "K73": ["k73"],
    "0020": ["0020"],
    "84": ["84"],
    "alarm 152": ["alarm", "152"],
    "B221 --> K158 - SI3": ["b221", "k158", "si3"],
    "Q25/K153": ["q25", "k153"],
    "  leading and trailing  ": ["leading", "and", "trailing"],
    "": [],
    "...": [],
    "E-stop": ["e", "stop"],
    "PL d / Cat. 3": ["pl", "d", "cat", "3"],
}


@pytest.mark.parametrize(("text", "expected"), sorted(GOLDEN.items()))
def test_tok_matches_the_golden_table(text, expected):
    assert tok(text) == expected


def test_a_dotted_part_number_is_three_tokens_not_one():
    """The §2.4 porting hazard, asserted.

    `impl`'s `TOKEN_RE` deliberately kept this as **one** token to make its deleted curated-keyword
    gate work. Qdrant's WORD tokenizer splits it, and porting the regex would make `verify`
    disagree with the index it is checking.
    """
    assert tok("84-5140.0020") == ["84", "5140", "0020"]


def test_no_adjacent_tokens_are_joined():
    """`impl`'s `token_set()` also emitted joins like `84 5140`. That is a match we must not make."""
    assert token_set("84-5140.0020") == {"84", "5140", "0020"}
    assert "845140" not in token_set("84-5140.0020")
    assert "84 5140" not in token_set("84-5140.0020")


def test_tokens_are_lowercased():
    assert tok("SF 1.1A") == tok("sf 1.1a") == ["sf", "1", "1a"]


def test_order_is_preserved_because_a_phrase_is_about_order():
    """A set would match a page carrying `sf`, `1` and `1a` anywhere on it (F1)."""
    assert tok("1a 1 sf") == ["1a", "1", "sf"]
    assert tok("sf 1 1a") != tok("1a 1 sf")


@pytest.mark.parametrize("short", ["3", "a", "84", "SI3", "0020"])
def test_nothing_is_dropped_for_being_short(short):
    """`min_token_len=1` on the index is what keeps `SI3`, `84` and `0020` findable (§5.5)."""
    assert MIN_TOKEN_LEN == 1
    assert tok(short) == [short.lower()]


def test_accented_text_is_one_token_not_two():
    """The corpus is Italian and English; a byte-oriented `[A-Za-z0-9]+` would split `però`."""
    assert tok("però") == ["però"]
    assert tok("EMERGENZA però") == ["emergenza", "però"]


def test_unicode_is_normalised_before_tokenising():
    """The same character composed two ways must produce the same token, or a lookup misses."""
    assert tok("però") == tok("però")


def test_token_set_is_the_distinct_tokens():
    assert token_set("K158 K158 SI3") == {"k158", "si3"}


def test_tok_is_pure():
    """Called twice on the same input, it returns the same list — no state, no caching surprise."""
    assert tok("SF 1.1A") == tok("SF 1.1A")
