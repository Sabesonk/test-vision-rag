"""L0 — `variants()` (Spec §5.6) and the I3 property.

The property test is the whole point of this file: **a variant may only re-space characters.** If
it could add, drop or change one, `K73` could produce `K78` and the system's one guarantee — a code
it returns is a code printed on the page — would rest on nothing.
"""
from __future__ import annotations

import pytest

from vsir.core.tok import tok
from vsir.core.variants import preserves_characters, variants

#: Every shape the corpus prints, plus the adversarial near-misses of §12.4.
LABELS = [
    "SF 1.1A", "SF1.1A", "SF 1.1 A", "SF 330.1", "SF121.1",
    "84-5140.0020", "84-5140.0021", "X20SI4100", "X20SI4101",
    "SI3", "SI4", "K158", "K159", "K73", "K78", "K700", "K7",
    "0020", "84", "3", "alarm 152", "alarm 153", "Q25", "K153",
    "B221", "PL d", "Cat. 3", "  padded  ", "MULTI  SPACE  LABEL",
]


@pytest.mark.parametrize("label", LABELS)
def test_a_variant_only_ever_re_spaces_the_label(label):
    """I3, as a property over every label — the test the spec says must catch a character change."""
    bare = "".join(label.split())

    assert {v.replace(" ", "") for v in variants(label)} == {bare}
    assert preserves_characters(label)


@pytest.mark.parametrize("label", LABELS)
def test_no_variant_is_empty_or_untrimmed(label):
    for variant in variants(label):
        assert variant == variant.strip()
        assert variant


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("SF 1.1A", ["SF 1.1A", "SF1.1A", "SF 1.1 A"]),
        ("SF1.1A", ["SF1.1A", "SF 1.1 A"]),
        ("K158", ["K158", "K 158"]),
        ("SI3", ["SI3", "SI 3"]),
        ("84-5140.0020", ["84-5140.0020"]),
        ("X20SI4100", ["X20SI4100", "X 20 SI 4100"]),
        ("0020", ["0020"]),
    ],
)
def test_the_three_spellings_are_as_documented(label, expected):
    """As given · whitespace removed · a space at every letter↔digit boundary."""
    assert variants(label) == expected


def test_at_most_three_variants_and_they_are_de_duplicated():
    """The plan's edge case: a whitespace-free single-shape label collapses, it does not crash.

    Returning the same phrase twice would just make the filter do identical work twice; the
    invariant that matters is the character-preserving one above, not the count.
    """
    for label in LABELS:
        generated = variants(label)
        assert len(generated) <= 3
        assert len(generated) == len(set(generated))
    assert len(variants("SF 1.1A")) == 3


def test_internal_whitespace_is_collapsed_not_multiplied():
    assert variants("MULTI  SPACE  LABEL")[0] == "MULTI SPACE LABEL"


def test_a_near_miss_can_never_be_generated():
    """F16 — the one thing that must be impossible: `K73` producing `K78`."""
    assert "K78" not in variants("K73")
    assert "K7" not in variants("K73")
    assert "K738" not in variants("K73")
    for label in LABELS:
        for other in LABELS:
            if "".join(other.split()) != "".join(label.split()):
                assert other not in variants(label), f"{label!r} generated {other!r}"


def test_a_variant_tokenises_the_way_the_phrase_index_will_read_it():
    """The variants exist so that a differently-spaced printing still matches as a phrase."""
    assert tok("SF1.1A") == ["sf1", "1a"]
    assert tok("SF 1.1A") == ["sf", "1", "1a"]
    assert tok("SF 1.1 A") == ["sf", "1", "1", "a"]
    # Three genuinely different token sequences for one code: that is exactly why three phrases
    # are tried, and why one of them alone would abstain on a printed label (F3).
    assert len({tuple(tok(v)) for v in variants("SF 1.1A")}) == 3


@pytest.mark.parametrize("label", ["", "   ", "...", "-", "  -  "])
def test_a_label_with_no_content_produces_no_usable_variant(label):
    generated = variants(label)

    assert all(variant.strip() for variant in generated)
    assert generated in ([], [label.strip()], ["".join(label.split())], [label.strip(), "".join(label.split())])
