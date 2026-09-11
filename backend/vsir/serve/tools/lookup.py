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
from vsir.serve import raster_cache
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
    SupersededIn,
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

#: How many superseded revisions a `found_only_in_superseded` will name. A document has revisions,
#: not a revision history the size of a corpus; the bound is here so the facet is bounded rather
#: than because anybody expects to reach it.
SUPERSEDED_REVISIONS = 32

#: How many published run records the superseded probe reads to decide which revisions were ever
#: released. Bounded for the same reason and read only on the absence path — a scroll over the
#: control plane is cheap, a scroll over it on every `ok` would not be.
SUPERSEDED_RUN_SCAN = 4096

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


def scope_filter(scope: Mapping[str, Any], extra_must: Sequence[qm.Condition] = (),
                 extra_must_not: Sequence[qm.Condition] = ()) -> qm.Filter:
    """The scope alone, as a filter — the denominator behind `weak` and `scope_stats`.

    ``extra_must`` / ``extra_must_not`` are conditions the scope vocabulary cannot spell — a
    `page_no` range, a negated facet — and they exist for `serve/retrieval.py` for the reason
    `_candidates`'s ``weights`` does: the flat surface needs them, the eight tools must not grow
    a knob for them, and a second filter builder is how the denominator and the numerator start
    counting different pages. They default to nothing, so every tool's filter is byte-identical
    to what it was.
    """
    # ``must_not`` is passed **only when there is one**. An empty list is not the same object as
    # an omitted field — it serialises as `must_not: []` and compares unequal to the filter this
    # function used to return — so defaulting it to `[]` would change every tool's request body
    # for a feature none of them use.
    if not extra_must_not:
        return qm.Filter(must=[*scope_conditions(scope), *extra_must])
    return qm.Filter(must=[*scope_conditions(scope), *extra_must],
                     must_not=list(extra_must_not))


def count_exact(client: Any, collection: str, query: qm.Filter) -> int:
    """An **exact** count. `weak` and `total` are contracts, not estimates (§7.1)."""
    return client.count(collection, count_filter=query, exact=True).count


def _with(query: qm.Filter, *conditions: qm.Condition) -> qm.Filter:
    return qm.Filter(must=[query, *conditions])


def no_text() -> qm.Condition:
    """§5.7's *"this page has no text layer"*, as one condition.

    Public because `skim_documents` counts the same pages to put `searchable_ratio` on a document
    row (§7.2.1, U019). Two spellings of `has_text == False` in two modules is how a ratio and the
    `pages_no_text` beside it in the same response come to disagree.
    """
    return qm.FieldCondition(key="has_text", match=qm.MatchValue(value=False))


def scope_stats(client: Any, collection: str, scoped: qm.Filter) -> tuple[ScopeStats, int]:
    """``(scope_stats, searchable_pages)`` — what was actually searched (§7.1, §5.7).

    Takes the **built** scope filter rather than the scope dict, so the `INDEXED` gate runs exactly
    once per call and every refusal leaves this function before a round trip is spent.

    ``pages_no_text`` is why F4 cannot happen quietly: a scope of 40 pages of which 40 have no text
    layer is not *"nothing matched"*, it is *"nothing was searchable"*. It counts ``has_text``
    exactly, because that is what ``searchable_ratio`` is defined on (§5.7); ``searchable_pages``
    is the wider notion that also excludes ``untrusted``, and it is what chooses the status.
    """
    pages = count_exact(client, collection, scoped)
    pages_no_text = count_exact(client, collection, _with(scoped, no_text()))
    searchable_pages = count_exact(client, collection, searchable(scoped))

    per_doc = {hit.value: hit.count for hit in
               client.facet(collection, key="doc_id", facet_filter=scoped,
                            limit=SCOPE_STAT_DOCS, exact=True).hits}
    no_text_per_doc = {hit.value: hit.count for hit in
                       client.facet(collection, key="doc_id",
                                    facet_filter=_with(scoped, no_text()),
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

    The URL is built by `serve/raster_cache.py`, which owns the route's grammar **and its
    percent-encoding**. That is not tidiness: a ``page_id`` contains a ``#`` (§5.1), and an
    unencoded ``#`` makes every one of these references a request for ``/pages/{doc_id}@{revision}``
    with a fragment the server never sees — a reference that is present, well-formed and not
    dereferenceable. §7.2.5's own example shows the encoded form.
    """
    return ImageRef(url=raster_cache.page_image_url(page_id, dpi=DPI_INDEX),
                    thumb_url=raster_cache.page_image_url(page_id, dpi=DPI_THUMB),
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
        if count_exact(client, collection, searchable(exact_filter(word, scope))) > 0
    ]



def absence(scope_pages: int, searchable_pages: int, *,
            superseded: Sequence[Any] = ()) -> Status:
    """Which of the four absences this is (§7.1) — never an empty ``ok``, never a bare ``200``.

    Order matters, and `found_only_in_superseded` is **first** (F9, closed at M8 by U025). It is
    the only one of the four that is not an abstention: the other three say *"the current corpus
    does not have this"*, and this one says *"a revision that is no longer current does"*. Both
    of the statuses it outranks would be wrong rather than merely less specific — `out_of_scope`
    claims no document matched the filters when one did, and `not_found` claims a search happened
    and came back empty when it came back with a revision the caller may well want.

    Then an empty scope is `out_of_scope` (the corpus was never asked) before it is
    `not_searchable` (asked, and nothing was readable).
    """
    if superseded:
        return Status.FOUND_ONLY_IN_SUPERSEDED
    if scope_pages == 0:
        return Status.OUT_OF_SCOPE
    if searchable_pages == 0:
        return Status.NOT_SEARCHABLE
    return Status.NOT_FOUND


def published_revisions(client: Any, runs_collection: str) -> set[tuple[str, str]]:
    """Every ``(doc_id, revision)`` a run actually published, off the control plane (D9, §6.9).

    **The discriminator I7 needs, and the reason this probe reads `vsir_runs` at all.** In the
    pages collection a point with ``is_current=False`` is one of two completely different things:
    a revision that was published and has since been superseded — §6.7 clause 2, which is F9's
    evidence — or a run that has not passed its gates. They are indistinguishable there, because
    the payload records the flag and not its history, and §5.4's `INDEXED` is sixteen keys with
    no seventeenth to spare.

    Answering `found_only_in_superseded` about the second kind would be the worse failure of the
    two this unit is between: it discloses a half-ingested revision through the one status that
    is supposed to be about the past, and it does so while a document is mid-ingest, which is
    exactly when an operator is least able to tell the report is wrong. So the set of revisions
    this tool will name is the set of revisions a gate let through, and nothing else (I7).
    """
    if not runs_collection or not client.collection_exists(runs_collection):
        return set()
    found, _ = client.scroll(
        collection_name=runs_collection,
        scroll_filter=qm.Filter(must=[
            qm.FieldCondition(key="kind", match=qm.MatchValue(value="run")),
            qm.FieldCondition(key="state", match=qm.MatchValue(value="published"))]),
        limit=SUPERSEDED_RUN_SCAN, with_payload=["doc_id", "revision"], with_vectors=False)
    return {(str((point.payload or {}).get("doc_id") or ""),
             str((point.payload or {}).get("revision") or ""))
            for point in found}


def superseded_in(client: Any, collection: str, runs_collection: str, query: qm.Filter,
                  ) -> list[SupersededIn]:
    """The published-but-no-longer-current revisions that satisfy ``query`` (F9, §7.1).

    ``query`` is the caller's own filter with ``is_current`` taken the other way round — the same
    phrase, the same scope, the opposite side of the publish flip. One faceted count per
    revision, which is indexed (`revision` is a `keyword` in `INDEXED`), so this is a bounded
    aggregate and never a scroll-and-filter in Python (register E9).

    Empty when the control plane names no published revision that matches, which is the honest
    answer for a run still working and for a collection with no control plane at all.
    """
    if not runs_collection:
        return []
    hits = client.facet(collection, key="revision", facet_filter=query,
                        limit=SUPERSEDED_REVISIONS, exact=True).hits
    if not hits:
        return []
    published = published_revisions(client, runs_collection)
    if not published:
        return []
    rows: list[SupersededIn] = []
    for hit in hits:
        revision = str(hit.value)
        for doc_id in sorted(doc for doc, rev in published if rev == revision):
            pages = count_exact(client, collection, _with(
                query, qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))))
            if pages:
                rows.append(SupersededIn(doc_id=doc_id, revision=revision, pages=pages))
    return sorted(rows, key=lambda row: (row.doc_id, row.revision))


def superseded_probe(client: Any, collection: str, runs_collection: str, label: str,
                     scope: Mapping[str, Any] | None, *, field: str = "text",
                     ) -> list[SupersededIn]:
    """`lookup`'s half of F9: the same phrase, asked of what is no longer current.

    Runs **only** on the absence path, and costs a facet plus one count per naming revision. The
    scope is the caller's own with `is_current` flipped rather than dropped: dropping it would
    also re-match the current pages that have already been searched and found wanting, and would
    report *"found in the revision you are already reading"*.
    """
    retired_scope = {**(scope or {}), "is_current": False}
    return superseded_in(client, collection, runs_collection,
                         searchable(exact_filter(label, retired_scope, field=field)))


def lookup(client: Any, collection: str, label: str, *,
           scope: Mapping[str, Any] | None = None,
           include_unverified: bool = False,
           cap: int = LOOKUP_CAP,
           provenance: Provenance,
           runs_collection: str = "",
           reads_remaining: int = 0) -> SearchResponse[LookupHit]:
    """The exact surface: every page whose text verifiably contains ``label``.

    Pure in the sense that matters: it holds no state between calls, reads no configuration and
    keeps nothing in process memory (§15 Factor VI). ``client`` and ``collection`` are the store,
    ``provenance`` and ``reads_remaining`` come from the request context the caller owns — so the
    HTTP and MCP wrappers of U015 add transport, auth and the budget, and **not one line of
    behaviour**. That is the point: M1's proof has to still apply at the tool boundary.

    ``runs_collection`` is the control plane, and it is what makes `found_only_in_superseded`
    answerable (F9, U025) — see :func:`published_revisions` for why the pages collection alone
    cannot tell a superseded revision from an unpublished one. It is read **only** on the absence
    path. Without it the tool is exactly as it was: a label carried only by a retired revision is
    reported `not_found`, which is honest about the current corpus and is all a caller with no
    control plane in hand can be told.

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
        scoped = scope_filter(scope_in_force)
    except UnknownScopeKey as refusal:
        raise as_tool_error(refusal) from None

    stats, searchable_pages = scope_stats(client, collection, scoped)

    text_query = searchable(phrase_query)
    total = count_exact(client, collection, text_query)
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
    # The superseded probe runs on the absence path only, and before `absence` decides, because
    # its answer outranks all three of the others (F9). A hit in the current corpus never reaches
    # it: a `lookup` that found the label has nothing to tell the caller about a retired revision
    # of it, and paying a facet on every `ok` to discover that would be the wrong trade.
    superseded = ([] if hits else
                  superseded_probe(client, collection, runs_collection, label, scope))
    status = Status.OK if hits else absence(stats.pages, searchable_pages,
                                            superseded=superseded)
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
        superseded=superseded,
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
        superseded=[f"{row.doc_id}@{row.revision}" for row in superseded],
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
