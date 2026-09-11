"""Local sparse vectors (D2). BM25 term weights in, IDF applied by Qdrant.

The original of this module stored **raw term counts**, and its reasoning for doing so was
operational and remains correct in the half that matters:

    Qdrant's ``Modifier.IDF`` computes inverse document frequency across the collection **at query
    time**, so we never hold a corpus statistic ourselves. Otherwise ingesting one new document
    shifts the IDF of every term and silently stales every sparse vector already in the index.

**That property is kept.** What raw counts also bought, and should not have, was a ranking with no
term-frequency saturation and no length normalisation — the two halves of BM25 that are not IDF. The
failure was not subtle, and it is re-measurable rather than recalled: over the 56 pages of the one
real ingest, the query *"Safeguard Detector individual sensors"* ranked page 46 — 1,390 characters,
254 tokens, and the **only** page in the document that prints ``individual sensors`` — **9th**,
behind prose pages repeating ``sensors`` 13, 9, 9 and 8 times. BM25 puts it **2nd**. That is not a
worse ordering, it is the wrong page, and no weighting of the branch could recover it;
``test_the_page_that_prints_the_phrase_loses_to_pages_that_repeat_a_common_word`` holds the whole
measurement so the regression cannot be quiet.

So the document side now stores BM25's tf component and Qdrant still supplies the idf factor::

    value(t, D) = tf(t,D) · (k1 + 1) / (tf(t,D) + k1 · (1 − b + b · |D| / avg_len))

and the anti-staleness argument survives intact, because **ingesting a document still changes no
stored value**: ``|D|`` is a property of the document itself, and ``avg_len`` is a released pin
(:data:`~vsir.config.BM25_AVG_LEN_LEXICAL`, :data:`~vsir.config.BM25_AVG_LEN_CAPTIONS`) rather than
a live measurement. What is given up is that a pin drifts from the corpus it describes as the corpus
grows. That drift is bounded — it moves every weight in the same direction and the length penalty
stays monotone — it is visible, sitting in `config.py` beside ``SURFACE_WEIGHTS``, and correcting it
is a release: bump :data:`~vsir.config.SPARSE_VERSION`, which re-keys every collection.

**There is deliberately no ``build()``.** The document and query sides need different weights — a
query built with document weights would apply ``k1`` twice, a document built with query weights
would lose saturation — and both mistakes present identically, as worse neighbours. Two names that
cannot be confused is the whole point; a surviving ``build()`` would be a correctly-spelled function
that silently produces the defect above.

One substitution kept from the port: tokenisation is :func:`vsir.core.tok.tok`, not `impl`'s
``tokenise``. These vectors and the phrase index must agree about what a token is, or the lexical
surface would find pages the exact surface cannot confirm (§5.6). It is also why Qdrant's own
server-side BM25 is not used here: it brings its own tokenizer, stemmer, stopword list and
ascii-folding, and ``però`` folding to ``pero`` would break that agreement.
"""
from __future__ import annotations

import hashlib
from collections import Counter

from vsir.config import BM25_B, BM25_K1
from vsir.core.tok import tok

_MASK = (1 << 31) - 1


def slot(term: str) -> int:
    """Stable term → u32 slot. Collisions are possible and harmless at this scale."""
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big") & _MASK


def _counted(text: str) -> tuple[Counter, int]:
    """The tokens of ``text`` counted, and ``|D|`` — the **total** count, not the distinct one.

    ``|D|`` is derived here rather than passed in by the caller, where it could drift from the text
    it claims to describe. The tokenisation happens once either way.
    """
    counts = Counter(tok(text))
    return counts, sum(counts.values())


def _packed(by_slot: dict[int, float]) -> tuple[list[int], list[float]]:
    """``(indices, values)`` with the indices sorted, as Qdrant requires."""
    indices = sorted(by_slot)
    return indices, [by_slot[index] for index in indices]


def _checked(avg_len: float) -> float:
    """``avg_len`` or a named refusal — never a division by zero in step 10."""
    if avg_len <= 0:
        raise ValueError(
            f"avg_len is a token count and must be positive, got {avg_len!r}. Left unchecked this "
            f"is a ZeroDivisionError in step 10 — after the S2 spend and after every embedding has "
            f"been bought"
        )
    return avg_len


def saturated(occurrences: int, length: int, *, avg_len: float,
              k1: float = BM25_K1, b: float = BM25_B) -> float:
    """One term's BM25 tf component: ``tf(k1+1) / (tf + k1(1 − b + b·|D|/avg_len))``.

    Three properties worth knowing, each asserted by a test: it is exactly ``1.0`` for a term
    appearing once in a document of average length; it rises with ``occurrences`` but is bounded
    above by ``k1 + 1``, which is what stops a page winning by repetition; and it falls as
    ``length`` grows, which is what lets a short page compete at all.
    """
    avg_len = _checked(avg_len)
    return occurrences * (k1 + 1.0) / (
        occurrences + k1 * (1.0 - b + b * length / avg_len)
    )


def build_document(text: str, *, avg_len: float,
                   k1: float = BM25_K1, b: float = BM25_B) -> tuple[list[int], list[float]]:
    """``(indices, values)`` with values = the **BM25 tf component**. The idf half stays Qdrant's.

    ``avg_len`` is keyword-only and has no default on purpose: the two sparse surfaces are an order
    of magnitude apart in document length, and a default would let a caller weight the captions
    vector against the lexical statistic without saying so.

    Colliding slots **sum their saturated weights** rather than their counts. Two distinct terms
    sharing a slot are two terms, each saturating on its own; adding the counts first would treat
    them as one term with ``tf₁ + tf₂`` and over-saturate the pair.

    ``avg_len`` is checked **before** the empty-text shortcut, so a misconfigured release refuses on
    the first page it indexes rather than on the first page that happens to have a text layer — on
    a scanned document those are different pages, and the second is not a diagnosis anyone would
    reach for.
    """
    counts, length = _counted(text)
    avg_len = _checked(avg_len)
    if not counts:
        return [], []
    by_slot: dict[int, float] = {}
    for term, occurrences in counts.items():
        index = slot(term)
        by_slot[index] = by_slot.get(index, 0.0) + saturated(
            occurrences, length, avg_len=avg_len, k1=k1, b=b)
    return _packed(by_slot)


def build_query(text: str) -> tuple[list[int], list[float]]:
    """``(indices, values)`` with values = **1.0 per distinct term**. Presence, never a count.

    Qdrant scores ``Σ idf(t)·q(t)·d(t)`` and the document side already carries BM25's tf component,
    so with ``q(t) = 1`` the value it computes **is** BM25 — a claim a reader can check against the
    literature in one line. Saturating here as well would apply ``k1`` twice; counting here would
    let a technician who wrote *"the sensor and the sensor cable"* weight ``sensor`` double off
    filler rather than intent.
    """
    counts, _ = _counted(text)
    if not counts:
        return [], []
    return _packed({slot(term): 1.0 for term in counts})


def dedupe(caption_text: str, against: str) -> str:
    """Strip from generated text any token the verbatim text layer already carries.

    Without this a page enters fusion **twice** for one piece of evidence, with the generated copy
    weighted like printed text. This is what makes the `captions` surface safe to populate — it was
    declared and weighted but never written in `impl` (register D3), and a generated page summary
    is exactly the content that surface was designed for.
    """
    have = set(tok(against))
    return " ".join(term for term in tok(caption_text) if term not in have)
