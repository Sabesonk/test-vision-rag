"""``variants()`` (Spec §5.6, I3) — exactly three spellings of the **same characters**.

A printed code appears with inconsistent spacing: ``SF 1.1A`` in the safety-function list,
``SF1.1A`` in a schematic callout, ``SF 1.1 A`` in a table cell. All three are the same code, and a
`lookup` that finds only one of them abstains on a label that *is* printed — F3.

The rule that makes this safe is the whole of I3: **a variant may only re-space characters.** It
may not add one, drop one, or change one. So ``K73`` can never produce ``K78``, no matter what the
corpus looks like, and the property test asserts exactly that — every variant, with its spaces
removed, is the label with its spaces removed. A variant that changes a character is a bug, and the
test is what makes it a caught bug rather than a confident wrong answer.

This is also the **only** permitted string normalisation in the codebase (§5.2): whitespace
collapsing and letter↔digit boundary spacing, here and nowhere else. There is no identifier
grammar, no normalisation table and no per-corpus regex — `impl` had nine such regexes and they are
struck (C1).
"""
from __future__ import annotations


def _bare(label: str) -> str:
    """The label with every whitespace character removed — the identity a variant preserves."""
    return "".join(label.split())


def _boundary_spaced(bare: str) -> str:
    """A space at every letter↔digit boundary. ``SF1.1A`` → ``SF 1.1 A``."""
    out: list[str] = []
    for index, char in enumerate(bare):
        if index and _crosses_boundary(bare[index - 1], char):
            out.append(" ")
        out.append(char)
    return "".join(out)


def _crosses_boundary(previous: str, char: str) -> bool:
    """True where a letter meets a digit, in either direction."""
    return (previous.isalpha() and char.isdigit()) or (previous.isdigit() and char.isalpha())


def variants(label: str) -> list[str]:
    """The label as given, with whitespace removed, and with letter↔digit boundaries spaced.

    De-duplicated, order preserved: for a label that is already whitespace-free and single-shape
    (``SI3``) two of the three coincide, and returning the same phrase twice would just make the
    filter do the same work twice. The count is therefore *at most* three, never a crash.
    """
    collapsed = " ".join(label.split())
    bare = _bare(label)
    ordered = [collapsed, bare, _boundary_spaced(bare)]

    seen: dict[str, None] = {}
    for candidate in ordered:
        if candidate:
            seen.setdefault(candidate, None)
    return list(seen)


def preserves_characters(label: str) -> bool:
    """The I3 property, callable: every variant is the label, re-spaced and nothing else.

    Exposed rather than left in the test file so the same predicate can be asserted at a call site
    — a variant list that fails this must never reach a filter.
    """
    bare = _bare(label)
    return all(_bare(variant) == bare for variant in variants(label))
