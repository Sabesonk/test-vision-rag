"""``exact_filter()`` (Spec §5.6, I3, F1) — the **only** exact-match code path in the codebase.

Everything about exactness funnels through this one function, on purpose. `lookup` uses it,
`verify` uses it, the answer gate uses it through `verify`, and the ingest-time
``codes_in_text`` derivation asks the same question of the same index. One code path means one
place where "is this code printed on this page?" is decided, so the answer cannot differ between
the tool that found the page and the check that confirms it.

The mechanism is ``MatchPhrase`` over :func:`~vsir.core.variants.variants`, against the ``text``
index built with ``phrase_matching=True`` (§5.5):

* **a phrase, not a token match.** ``MatchText`` would match ``sf`` and ``1`` in any order, so
  ``"SF 1.1A"`` would return every page mentioning safety functions. That is not a slow path, it is
  a wrong answer, which is why ``MatchText``/``MatchTextAny`` are banned under ``serve/`` by a
  conformance grep;
* **variants, not fuzz.** The three spellings are the same characters re-spaced (I3). There is no
  edit distance anywhere in the system, so a near-miss code cannot be returned as a match — the
  most a near miss can produce is a `present_instead` disclosure beside an `absent` verdict (F16).

``is_current`` is **not** added here. Every tool injects it server-side (I7), and burying it in the
filter builder would make it invisible at the one place a reader needs to see it.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from qdrant_client.http import models as qm

from vsir.core.indexed import TEXT_FIELDS, reject_unknown_keys
from vsir.core.tok import tok
from vsir.core.variants import variants


class UnknownScopeKey(ValueError):
    """A filter key absent from ``INDEXED`` (I6, F10).

    Never absorbed and never degraded to an unindexed scan: `serve/caps.py` turns this into a typed
    ``filter_unknown_key`` 400 naming the keys, because a filter that quietly did not apply returns
    a smaller answer that looks like a complete one.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        super().__init__(f"not filterable (see INDEXED): {list(keys)}")
        self.keys = list(keys)


def scope_conditions(scope: Mapping[str, Any] | None) -> list[qm.Condition]:
    """The scope as indexed field conditions. Raises :class:`UnknownScopeKey` on anything else.

    A list value matches **any** element (``MatchAny``), which is what makes `section_id` and
    `series_id` arrays work: a page straddling two sections is in scope for either (F8).
    """
    if not scope:
        return []
    unknown = reject_unknown_keys(scope)
    if unknown:
        raise UnknownScopeKey(unknown)

    conditions: list[qm.Condition] = []
    for key, value in scope.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            members = [member for member in value if member is not None]
            if members:
                conditions.append(qm.FieldCondition(key=key, match=qm.MatchAny(any=list(members))))
        else:
            conditions.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=value)))
    return conditions


def exact_filter(label: str, scope: Mapping[str, Any] | None = None, *,
                 field: str = "text") -> qm.Filter:
    """``should[ must[ MatchPhrase(field, v), *scope ] ] for v in variants(label)``.

    ``field`` is one of the two text surfaces. ``text`` is verified by construction — only
    `ingest/probe.py` writes it (I2) — while ``vlm_codes`` is the opt-in surface whose hits are
    permanently ``verified: false`` (D3). Same code path, same phrase semantics, different trust:
    that is the entire difference between the two, and it is a parameter rather than a second
    function so it cannot drift into one.
    """
    if field not in TEXT_FIELDS:
        raise ValueError(f"not a text surface: {field!r} (expected one of {list(TEXT_FIELDS)})")
    spellings = variants(label)
    if not spellings:
        raise ValueError("label is empty after whitespace collapsing")

    scoped = scope_conditions(scope)
    return qm.Filter(
        should=[
            qm.Filter(must=[qm.FieldCondition(key=field, match=qm.MatchPhrase(phrase=spelling)),
                            *scoped])
            for spelling in spellings
        ]
    )


def phrases_of(query_filter: qm.Filter) -> list[str]:
    """The phrases a filter from :func:`exact_filter` will match on.

    For the demo and for `verify`'s disclosure: what was actually asked of the index, rather than
    what the caller typed.
    """
    found: list[str] = []
    for branch in query_filter.should or []:
        for condition in getattr(branch, "must", None) or []:
            match = getattr(condition, "match", None)
            phrase = getattr(match, "phrase", None)
            if phrase is not None:
                found.append(phrase)
    return found


# ── the same question, asked locally ────────────────────────────────────────────────────────────
#
# `exact_filter` asks the index. Derivation (§6.1 step 07) and the near-miss generator (§12.4) have
# to ask the identical question of a string in hand, before the page has been indexed at all — so
# the predicate lives here, beside the filter, rather than growing a second time somewhere else.
# It is the same mechanism in the other spelling: `variants()` for the spellings, `tok()` for the
# tokens, and contiguity for the phrase. `tok()` mirrors Qdrant's WORD tokenizer (§5.6) and
# `tests/api/test_tokenizer_differential.py` measures that against a live `qdrant/qdrant:v1.19.0`,
# which is what makes "locally" and "of the index" the same answer rather than two nearby ones.


def contains_phrase(tokens: Sequence[str], phrase: str) -> bool:
    """Whether ``tok(phrase)`` occurs as a **contiguous run** of ``tokens``, in order.

    Contiguity and order are the whole content of ``phrase_matching=True`` (§5.5): a set
    membership test would match ``sf`` and ``1`` anywhere on the page, which is F1.
    """
    needle = tok(phrase)
    if not needle:
        return False
    haystack = list(tokens)
    width = len(needle)
    return any(haystack[at:at + width] == needle
               for at in range(len(haystack) - width + 1))


def printed_in(tokens: Sequence[str], label: str) -> bool:
    """Whether **any** spelling of ``label`` is printed in an already-tokenised page.

    Takes tokens rather than text so a caller checking many labels against one page tokenises that
    page once — derivation checks every code the model reported on a page, and the near-miss eval
    checks a hundred candidates against the whole corpus.
    """
    return any(contains_phrase(tokens, spelling) for spelling in variants(label))


def printed_on(label: str, text: str) -> bool:
    """Whether any spelling of ``label`` is printed in ``text``. The one-shot form."""
    return printed_in(tok(text), label)
