"""Local sparse vectors (D2). Ported as-is from ``impl/app/sparse.py`` — term frequencies in, IDF
applied by Qdrant.

The reasoning in the original is the reason this is ported rather than rewritten, and it is
operational, not theoretical:

    Qdrant's ``Modifier.IDF`` computes inverse document frequency across the collection **at query
    time**, so we store raw term counts and never hold a corpus statistic ourselves. Otherwise
    ingesting one new document shifts the IDF of every term and silently stales every sparse vector
    already in the index.

One substitution: tokenisation is :func:`vsir.core.tok.tok`, not `impl`'s ``tokenise``. These
vectors and the phrase index must agree about what a token is, or the lexical surface would find
pages the exact surface cannot confirm (§5.6).
"""
from __future__ import annotations

import hashlib
from collections import Counter

from vsir.core.tok import tok

_MASK = (1 << 31) - 1


def slot(term: str) -> int:
    """Stable term → u32 slot. Collisions are possible and harmless at this scale."""
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big") & _MASK


def build(text: str) -> tuple[list[int], list[float]]:
    """``(indices, values)`` with values = **raw term frequency**."""
    counts = Counter(tok(text))
    if not counts:
        return [], []
    by_slot: dict[int, float] = {}
    for term, occurrences in counts.items():
        by_slot[slot(term)] = by_slot.get(slot(term), 0.0) + float(occurrences)
    indices = sorted(by_slot)
    return indices, [by_slot[index] for index in indices]


def dedupe(caption_text: str, against: str) -> str:
    """Strip from generated text any token the verbatim text layer already carries.

    Without this a page enters fusion **twice** for one piece of evidence, with the generated copy
    weighted like printed text. This is what makes the `captions` surface safe to populate — it was
    declared and weighted but never written in `impl` (register D3), and a generated page summary
    is exactly the content that surface was designed for.
    """
    have = set(tok(against))
    return " ".join(term for term in tok(caption_text) if term not in have)
