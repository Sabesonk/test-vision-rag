"""An in-memory stand-in for Qdrant, understanding exactly the filter shapes `serve/` builds.

Shared by the L0 suites for `lookup` and `verify_claims`, which are pure functions over a client:
everything about *which* absence they choose, what `cap` may move, and how a `(claim, page)` matrix
folds is decidable without Docker.

**Why a fake is honest here.** The one thing it could get wrong is what a `MatchPhrase` means, and
that is pinned elsewhere: `tok()` mirrors Qdrant's WORD tokenizer (Spec §5.6) and
`tests/api/test_tokenizer_differential.py` proves it against a live `qdrant/qdrant:v1.19.0`. So a
phrase here is *"`tok(phrase)` appears contiguously in `tok(text)`"* — the behaviour that test
measured — and the L2 suites re-run the same tables against the real index. If the two ever
disagree, one of them goes red, which is the point of having both.

Any match type this does not implement **raises**: a fake that silently passed an unimplemented
condition would turn I3's one-code-path guarantee into an untested claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from qdrant_client.http import models as qm

from vsir.core.ids import point_id
from vsir.core.tok import tok


def phrase_matches(phrase: str, text: str) -> bool:
    """A phrase is its tokens, contiguous and in order — what §5.5's `phrase_matching` buys."""
    needle, haystack = tok(phrase), tok(text)
    if not needle:
        return False
    return any(haystack[at:at + len(needle)] == needle
               for at in range(len(haystack) - len(needle) + 1))


def condition_matches(payload: dict, condition: Any) -> bool:
    if isinstance(condition, qm.Filter):
        return filter_matches(payload, condition)
    value = payload.get(condition.key)
    if getattr(condition, "range", None) is not None:
        # The export walks `page_no` in bounded ranges rather than following an opaque scroll
        # cursor (§6.8), so the fake has to understand a range or the export is untestable at L0.
        bounds, number = condition.range, value
        if number is None:
            return False
        return all(check is None or test(number, check) for check, test in (
            (bounds.gte, lambda n, c: n >= c), (bounds.gt, lambda n, c: n > c),
            (bounds.lte, lambda n, c: n <= c), (bounds.lt, lambda n, c: n < c)))
    match = condition.match
    if isinstance(match, qm.MatchValue):
        return value == match.value
    if isinstance(match, qm.MatchAny):
        members = value if isinstance(value, list) else [value]
        return any(member in match.any for member in members)
    if isinstance(match, qm.MatchPhrase):
        return phrase_matches(match.phrase, str(value or ""))
    raise AssertionError(f"the fake store does not implement {type(match).__name__} — and "
                         f"nothing under serve/ or core/ must be using it (I3)")


def filter_matches(payload: dict, query: qm.Filter | None) -> bool:
    """Qdrant's rule: the three clauses are ANDed, and `should` means at least one."""
    if query is None:
        return True
    if query.must and not all(condition_matches(payload, c) for c in query.must):
        return False
    if query.must_not and any(condition_matches(payload, c) for c in query.must_not):
        return False
    if query.should and not any(condition_matches(payload, c) for c in query.should):
        return False
    return True


@dataclass
class _Count:
    count: int


@dataclass
class _Point:
    id: Any
    payload: dict


@dataclass
class _FacetHit:
    value: Any
    count: int


@dataclass
class _Facet:
    hits: list[_FacetHit]


class FakeStore:
    """The four read operations the tools use, over a list of payloads in memory."""

    def __init__(self, payloads: Iterable[dict]) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    def _matching(self, query: qm.Filter | None) -> list[dict]:
        self.calls += 1
        return [payload for payload in self.payloads if filter_matches(payload, query)]

    def _page_id(self, payload: dict) -> str:
        return str((payload.get("provenance") or {}).get("page_id") or "")

    def count(self, _collection: str, count_filter: qm.Filter | None = None,
              exact: bool = False) -> _Count:
        assert exact is True, "`total` and `weak` are contracts, not estimates (§7.1)"
        return _Count(count=len(self._matching(count_filter)))

    def scroll(self, collection_name: str, scroll_filter: qm.Filter | None = None,
               limit: int = 10, with_payload: bool = True, with_vectors: bool = False,
               order_by: str | None = None,
               offset: Any = None) -> tuple[list[_Point], Any]:
        """Paged, like the real one: a second element that is not ``None`` means *ask again*.

        The export streams a document in chunks and follows that cursor (§6.8), so a fake that
        always answered ``None`` would make a truncating export look complete.
        """
        assert with_vectors is False, "a search never loads a vector it does not use"
        found = self._matching(scroll_filter)
        if order_by:
            found.sort(key=lambda payload: payload.get(order_by) or 0)
        start = int(offset or 0)
        page = found[start:start + limit]
        following = start + limit if start + limit < len(found) else None
        return [_Point(id=point_id(self._page_id(payload)) if self._page_id(payload)
                       else str(start + index), payload=payload)
                for index, payload in enumerate(page)], following

    def retrieve(self, _collection: str, ids: list[Any], with_payload: bool = True,
                 with_vectors: bool = False) -> list[_Point]:
        """By ``point_id`` — an exact address, so a missing page comes back as a missing row.

        The keyword is ``ids`` because that is the real client's signature; `point_id` is imported
        directly so the parameter cannot shadow the module that computes it.
        """
        self.calls += 1
        wanted = {str(identifier) for identifier in ids}
        return [_Point(id=known, payload=payload)
                for payload in self.payloads
                if self._page_id(payload)
                and (known := point_id(self._page_id(payload))) in wanted]

    def facet(self, _collection: str, key: str, facet_filter: qm.Filter | None = None,
              limit: int = 10, exact: bool = False) -> _Facet:
        counts: dict[Any, int] = {}
        for payload in self._matching(facet_filter):
            counts[payload.get(key)] = counts.get(payload.get(key), 0) + 1
        ordered = sorted(counts.items(), key=lambda item: -item[1])[:limit]
        return _Facet(hits=[_FacetHit(value=value, count=count) for value, count in ordered])
