"""JUMP — ``lookup(label, scope?, include_unverified=False, cap=20)`` (Spec §7.2.2).

Ported with changes from ``impl/app/retrieve.py::lookup`` and **rewritten as a phrase filter**
(C2). What is kept from the original is its judgement, which was right and is stated in its own
docstring:

    Exact label → the segments that verifiably contain it. A SET, not a ranking. […] filters
    default to NONE, because a component's footprint across the diagram AND the manual needs
    corpus-wide pinning; […] it is capped and says so, rather than dumping 200 segments for a
    common tag.

What is replaced is the mechanism. `impl` had **no text index at all** — no `MatchPhrase`, no
`TextIndexParams`, no `phrase_matching` anywhere in it — so its exact surface was a curated
keyword payload field built from a model-derived identifier grammar, matched with `MatchValue`.
That grammar is struck (C1), and with it the property that a code had to be *recognised* before it
could be *found*. Here the surface is the extracted text itself: `ingest/probe.py` is the only
writer of ``text`` (I2), so a hit on it is verified by construction and a code the model invented
is not merely unlikely to be found — it is **unfindable** (F14).

Three things this module does not do, each one a wrong answer if it did:

* **It does not rank.** No score, no ordering by relevance, no fusion (§7.6). The result is a set,
  returned in reading order, and ``total`` is the size of the set rather than ``len(hits)`` — a
  caller paging a capped result must be able to tell *"20 of 400"* from *"20 of 20"*, because the
  first is a scoping problem and the second is an answer.
* **It does not let `cap` touch `weak`.** ``cap`` bounds the page of the set that comes back and
  nothing else. A trust signal a client could flip by passing ``cap=200`` would be worse than no
  signal at all (§7.1), so `weak` is computed from ``total`` against the **server** constant
  ``WEAK_ABS``.
* **It does not merge the two surfaces.** ``include_unverified`` repeats the same phrase query
  against ``vlm_codes`` and returns those separately, every one ``verified: false`` and permanently
  so (D3). They are the only recall there is on a scanned page, and they are never evidence.

**`present_instead` is not reachable from here, by construction.** This module does not import
`core/observed_tokens.py`, and an import-graph test asserts that it never will (§6.8, F16). The
code-like heuristic behind that inventory is display-only; a `lookup` that consulted it could
return a near-miss code as a match, which is the injury the whole design exists to prevent.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.config import DPI_INDEX, LOOKUP_CAP
from vsir.core.exact import UnknownScopeKey, exact_filter, phrases_of, scope_conditions
from vsir.core.record import UNSEARCHABLE_TRUST
from vsir.core.tok import tok
from vsir.core.variants import variants
from vsir.serve.caps import as_tool_error, validate_cap
from vsir.serve.envelope import (
    DocScopeStat,
    ImageRef,
    LookupHit,
    NextMoves,
    Provenance,
    ScopeStats,
    SearchResponse,
    Status,
    weakness,
)

# §5.7's two unsearchable trust levels come from `core/record.py`, where `TextTrust` is declared:
# `no_text` has nothing to match and `untrusted` has a text layer nobody should be told is
# evidence. A phrase that matches inside a garbled extraction is not a verified hit, so those
# pages are excluded from ``hits``, and they are what turns an all-unsearchable scope into
# `not_searchable` rather than `not_found` (F4).

#: The thumbnail tier behind ``thumb_url`` (§7.3). 36 and 72 are the two triage tiers; 72 is the
#: one a list of page thumbnails renders at.
DPI_THUMB = 72

#: How many of a label's words are probed to decide whether a `not_found` carries a suggestion.
#: A label is a code, not a sentence; the bound exists so a pathological "label" cannot turn one
#: refusal into hundreds of counts.
SUGGEST_WORD_PROBES = 8

#: A one-character word does not earn a suggestion. ``min_token_len=1`` on the **index** is
#: load-bearing — it is what keeps `SI3`, `84` and `0020` findable (§5.5) — but *"the letter `k`
#: appears somewhere in this corpus"* is not evidence that a different move could find `K999`.
#: Two characters is the floor for a word that justifies an affordance.
SUGGEST_MIN_WORD_LEN = 2

#: The per-document rows in ``scope_stats``. A scope spanning more documents than this still
#: reports exact ``pages`` and ``pages_no_text`` — the breakdown is a display, the totals are not.
SCOPE_STAT_DOCS = 64

_log = vsir_logging.get_logger(__name__)


def effective_scope(scope: Mapping[str, Any] | None) -> dict:
    """The caller's scope with ``is_current=True`` injected — server-side, always (I7).

    A run that has not passed its gates cannot answer, and a superseded revision cannot answer as
    the current one (F9). The caller does not get a vote: an explicit ``is_current: False`` is
    **overridden**, not honoured, and the override is visible because the result echoes this exact
    dict back as ``effective_scope`` (F8, C11). Nothing is hidden; the caller is told what was
    searched.
    """
    return {**(scope or {}), "is_current": True}


def searchable(query: qm.Filter) -> qm.Filter:
    """``query`` restricted to pages whose text layer is searchable (§5.7).

    A top-level ``must_not`` beside the nested phrase filter: Qdrant ANDs the clauses of one
    filter, so this is one condition on top of the exact surface rather than a second code path.
    """
    return qm.Filter(
        must=[query],
        must_not=[qm.FieldCondition(key="text_trust",
                                    match=qm.MatchAny(any=list(UNSEARCHABLE_TRUST)))],
    )


def _scope_filter(scope: Mapping[str, Any]) -> qm.Filter:
    """The scope alone, as a filter — the denominator behind `weak` and `scope_stats`."""
    return qm.Filter(must=scope_conditions(scope))


def _count(client: Any, collection: str, query: qm.Filter) -> int:
    """An **exact** count. `weak` and `total` are contracts, not estimates (§7.1)."""
    return client.count(collection, count_filter=query, exact=True).count


def _with(query: qm.Filter, *conditions: qm.Condition) -> qm.Filter:
    return qm.Filter(must=[query, *conditions])


def _no_text() -> qm.Condition:
    return qm.FieldCondition(key="has_text", match=qm.MatchValue(value=False))


def _scope_stats(client: Any, collection: str, scoped: qm.Filter) -> tuple[ScopeStats, int]:
    """``(scope_stats, searchable_pages)`` — what was actually searched (§7.1, §5.7).

    Takes the **built** scope filter rather than the scope dict, so the `INDEXED` gate runs exactly
    once per call and every refusal leaves this function before a round trip is spent.

    ``pages_no_text`` is why F4 cannot happen quietly: a scope of 40 pages of which 40 have no text
    layer is not *"nothing matched"*, it is *"nothing was searchable"*. It counts ``has_text``
    exactly, because that is what ``searchable_ratio`` is defined on (§5.7); ``searchable_pages``
    is the wider notion that also excludes ``untrusted``, and it is what chooses the status.
    """
    pages = _count(client, collection, scoped)
    pages_no_text = _count(client, collection, _with(scoped, _no_text()))
    searchable_pages = _count(client, collection, searchable(scoped))

    per_doc = {hit.value: hit.count for hit in
               client.facet(collection, key="doc_id", facet_filter=scoped,
                            limit=SCOPE_STAT_DOCS, exact=True).hits}
    no_text_per_doc = {hit.value: hit.count for hit in
                       client.facet(collection, key="doc_id",
                                    facet_filter=_with(scoped, _no_text()),
                                    limit=SCOPE_STAT_DOCS, exact=True).hits} if pages_no_text else {}
    docs = [
        DocScopeStat(doc_id=str(doc_id),
                     searchable_ratio=(count - no_text_per_doc.get(doc_id, 0)) / count)
        for doc_id, count in sorted(per_doc.items())
        if count
    ]
    return ScopeStats(pages=pages, pages_no_text=pages_no_text, docs=docs), searchable_pages


def image_ref(page_id: str) -> ImageRef:
    """The page raster as a **reference** — ~60 bytes, and it renders nothing (§7.1, D12, P2).

    ``GET /pages/{page_id}/image?dpi=`` is §7.4's path and the dpi tiers are §7.3's, so the caller
    never constructs a URL and a UI renders thumbnails straight out of a `lookup`. ``width`` and
    ``height`` stay 0 until something actually renders: reporting a size here would mean rendering
    the page to answer a search, which is exactly the cost this indirection exists to avoid.
    """
    return ImageRef(url=f"/pages/{page_id}/image?dpi={DPI_INDEX}",
                    thumb_url=f"/pages/{page_id}/image?dpi={DPI_THUMB}",
                    dpi=DPI_INDEX)


def hit_from_payload(payload: Mapping[str, Any], *, verified: bool) -> LookupHit:
    """One page's payload → a :class:`LookupHit`.

    ``verified`` is a boolean **about the surface the hit came from** and nothing else — ``text``
    is true, ``vlm_codes`` is false (§7.1). It is not a claim about the page, the code or the
    model, and the three-state `present | absent | unverifiable` vocabulary of a per-claim check is
    deliberately not spelled here.

    ``next`` is left unset. The navigation affordances of P4 — ``expand`` into the section,
    ``neighbours`` on either side — need the document's page count to avoid offering a page id that
    does not exist, which is a fact this tool never loads; `skim_pages` has it, and fills them in
    (U017).
    """
    content = payload.get("content") or {}
    provenance = payload.get("provenance") or {}
    page_id = str(provenance.get("page_id") or "")
    return LookupHit(
        page_id=page_id,
        page_no=int(payload.get("page_no") or 0),
        printed_page_no=str(content.get("printed_page_no") or ""),
        page_kind=str(payload.get("page_kind") or "prose"),
        verified=verified,
        text_trust=payload.get("text_trust") or "no_text",
        image=image_ref(page_id) if page_id else None,
    )


def _page_of_the_set(client: Any, collection: str, query: qm.Filter, cap: int,
                     *, verified: bool) -> list[LookupHit]:
    """``cap`` hits, in reading order.

    Ordered by ``page_no`` in Qdrant rather than in Python: with ``total > cap`` the order decides
    *which* page of the set comes back, so doing it here makes a capped result the **first** pages
    of the set instead of an arbitrary sample of it — and makes the same query return the same rows
    in the same order (§16). ``page_no`` is an indexed integer, so this is not a scan.

    ``cap`` is already known to be at least 1: `validate_cap` refused anything lower before the
    first round trip, so there is no second, quieter handling of the same bound here.
    """
    points, _ = client.scroll(collection_name=collection, scroll_filter=query, limit=cap,
                              with_payload=True, with_vectors=False, order_by="page_no")
    hits = [hit_from_payload(point.payload or {}, verified=verified) for point in points]
    return sorted(hits, key=lambda hit: (hit.page_id.split("#")[0], hit.page_no))


def _words_observed(client: Any, collection: str, label: str,
                    scope: Mapping[str, Any]) -> list[str]:
    """Which of the label's words occur in the scope's text at all (§7.1's `next.suggest`).

    The union over the label's **variants**, not just the spelling as typed, because the case where
    a suggestion is worth most is exactly the case a single spelling misses: ``X20SI4100`` is one
    token, so probing only the typed form asks *"does `x20si4100` occur?"* and learns nothing,
    while the boundary-spaced variant asks about ``20`` and ``4100`` and finds the page a skim
    would have returned.

    Two rules keep the affordance honest rather than reflexive, and both also make it cheaper:

    * words shorter than :data:`SUGGEST_MIN_WORD_LEN` are not probed — *"the letter `k` is in this
      corpus"* is not a reason to believe another move could find ``K999``;
    * a word that is **itself** one of the variants is not probed, because a one-word phrase *is*
      a token match, so ``total == 0`` has already proved that word does not occur.

    So ``lookup("K999")`` costs one probe (``999``), finds nothing, and honestly carries no
    suggestion, while ``lookup("alarm 152")`` finds both words and says a `skim_pages` could still
    answer.
    """
    answered = {tok(spelling)[0] for spelling in variants(label) if len(tok(spelling)) == 1}
    ordered: list[str] = []
    for spelling in variants(label):
        for word in tok(spelling):
            if (word not in ordered and word not in answered
                    and len(word) >= SUGGEST_MIN_WORD_LEN):
                ordered.append(word)
    return [
        word for word in ordered[:SUGGEST_WORD_PROBES]
        if _count(client, collection, searchable(exact_filter(word, scope))) > 0
    ]



def _absence(scope_pages: int, searchable_pages: int) -> Status:
    """Which of the four absences this is (§7.1) — never an empty ``ok``, never a bare ``200``.

    Order matters: an empty scope is `out_of_scope` (the corpus was never asked) before it is
    `not_searchable` (asked, and nothing was readable). `found_only_in_superseded` is F9's, closed
    at M8 by the revision-aware probe of U025; until then a label printed only on a superseded
    revision is honestly `not_found`, because that is what the current corpus says.
    """
    if scope_pages == 0:
        return Status.OUT_OF_SCOPE
    if searchable_pages == 0:
        return Status.NOT_SEARCHABLE
    return Status.NOT_FOUND


def lookup(client: Any, collection: str, label: str, *,
           scope: Mapping[str, Any] | None = None,
           include_unverified: bool = False,
           cap: int = LOOKUP_CAP,
           provenance: Provenance,
           reads_remaining: int = 0) -> SearchResponse[LookupHit]:
    """The exact surface: every page whose text verifiably contains ``label``.

    Pure in the sense that matters: it holds no state between calls, reads no configuration and
    keeps nothing in process memory (§15 Factor VI). ``client`` and ``collection`` are the store,
    ``provenance`` and ``reads_remaining`` come from the request context the caller owns — so the
    HTTP and MCP wrappers of U015 add transport, auth and the budget, and **not one line of
    behaviour**. That is the point: M1's proof has to still apply at the tool boundary.

    Every refusal is a **typed** :class:`~vsir.serve.caps.ToolError` naming its bound: a ``cap``
    below 1, and a filter key absent from ``INDEXED`` — ``filter_unknown_key``, a 400 rather than
    an unindexed scan and never a silently narrower answer (I6, F10). The `INDEXED` gate itself
    stays in `core/`, which knows nothing about HTTP; this is the one translation
    (:func:`~vsir.serve.caps.as_tool_error`), so there is one check and not two.
    """
    validate_cap(cap)
    scope_in_force = effective_scope(scope)
    try:
        phrase_query = exact_filter(label, scope_in_force, field="text")
        codes_query = exact_filter(label, scope_in_force, field="vlm_codes")
        scoped = _scope_filter(scope_in_force)
    except UnknownScopeKey as refusal:
        raise as_tool_error(refusal) from None

    stats, searchable_pages = _scope_stats(client, collection, scoped)

    text_query = searchable(phrase_query)
    total = _count(client, collection, text_query)
    hits = _page_of_the_set(client, collection, text_query, cap, verified=True)

    unverified_hits: list[LookupHit] = []
    if include_unverified:
        # No trust condition on this branch, deliberately: `vlm_codes` is the only recall there is
        # on a page with no text layer, which is the reason D3 ships it at all. Its hits are
        # labelled `verified: false` and are never merged into `hits`.
        unverified_hits = _page_of_the_set(client, collection, codes_query, cap, verified=False)

    # §7.1 spells these as one assignment — `weak = needs_scope = total > max(...)` — so they are
    # computed once here rather than twice in the constructor, where they could drift apart.
    is_weak = weakness(total, stats.pages)
    status = Status.OK if hits else _absence(stats.pages, searchable_pages)
    observed: list[str] = []
    next_moves: NextMoves | None = None
    if status == Status.NOT_FOUND:
        observed = _words_observed(client, collection, label, scope_in_force)
        if observed:
            # A `not_found` that a different *move* could still answer says so, rather than
            # inventing a seventh status (§7.1). The status stays honest; the affordance is what
            # stops the agent abstaining on a phrasing accident — and `tokens_observed` is the
            # evidence behind it, which §7.1 asks for in the same sentence: the caller can see
            # that both words of "alarm 152" really are in the corpus and the phrase is not.
            next_moves = NextMoves(suggest=["skim_pages"], tokens_observed=observed)

    response = SearchResponse[LookupHit](
        status=status,
        hits=hits,
        unverified_hits=unverified_hits,
        total=total,
        capped=total > cap,
        weak=is_weak,
        needs_scope=is_weak,
        next=next_moves,
        effective_scope=scope_in_force,
        scope_stats=stats,
        reads_remaining=reads_remaining,
        provenance=provenance,
    )
    # `debug`, not `info`. §7.4 requires one audit line per `read` and per `fetch` — the two tools
    # that spend — and §11.4 asks for nothing per call from a free one. A per-`lookup` line at
    # INFO would be volume nobody asked for on the stream that carries the lines that matter.
    _log.debug(
        "lookup",
        tool="lookup",
        label=label,
        # Read off the filter that was actually built, not re-derived from the label: the log
        # line's job is to say what was asked of the index.
        phrases=phrases_of(phrase_query),
        status=response.status.value,
        total=total,
        hits=len(hits),
        unverified=len(unverified_hits),
        cap=cap,
        capped=response.capped,
        weak=response.weak,
        scope_keys=sorted(scope_in_force),
        pages=stats.pages,
        pages_no_text=stats.pages_no_text,
        # The tokens that did occur, on the event stream as well as in `next.tokens_observed`:
        # an operator reading why a label abstained should not have to correlate a response body
        # back to the line that produced it.
        #
        # Named `words_observed` rather than `tokens_observed` on purpose: the log redactor matches
        # credential-shaped field *names*, and "token" is one of them (`logging.redact`). A field
        # called `tokens_*` arrives on the stream as `***`, which is the redactor working correctly
        # on a name that has nothing to do with a secret. `word` is also the exactly right noun —
        # `tok()` mirrors Qdrant's WORD tokenizer (§5.6).
        words_observed=observed,
    )
    return response


def label_variants(label: str) -> Sequence[str]:
    """The spellings this tool will ask the index for — for the demo and for an audit line.

    Exposed so a reviewer can see what was asked without reading the filter, and so nothing has to
    re-derive it: it is :func:`~vsir.core.variants.variants`, unchanged.
    """
    return variants(label)
