"""NARROW — the three rungs and the deterministic fusion behind them (Spec §7.2.1, D2, D12).

Ported with changes from ``impl/app/retrieve.py``: `rrf()` as-is (it was already ranks-only),
`decompose()` for its judgement, and `search()` replaced by the rung this module serves. The
original's `rrf` docstring states the property that makes fusion acceptable at all:

    Reciprocal-rank fusion. RANKS ONLY — no similarity score enters the arithmetic.

That is what satisfies §7.6's refusal by construction rather than by policy. The inputs are
per-surface *positions*; a cosine distance never enters, so there is nothing to leak into a
response, and no caller can mistake a fused number for a confidence. The one thing this module
returns about ordering is an **ordinal** `rank`: a position is not a confidence.

Two changes to the fusion itself, from `impl`:

* the accumulator is not called ``score`` and the total is **never returned**. `impl` carried it out
  to the API as ``Hit.fused``; a fused float is a similarity score under another name, and the
  §12.5 conformance grep now fails the build on the field name;
* ties break deterministically. `impl` sorted on the total alone, leaving equal rows in dictionary
  insertion order. The NFR is that the same query returns the same rows **in the same order**
  (§16), so the tiebreak is explicit: best per-surface rank, then the point id.

Per-surface ranks are kept, not just which surfaces hit: they are what the fusion actually
consumed, so they are what makes a weight change explicable — and they are what `PageHit.why`
reports.

**The rungs themselves.** Three branches run inside the scope, minus `exclude`: `page` (the fused
image+text dense vector of D4), `lexical` (sparse over the extracted text) and `captions` (sparse
over generated text, weighted 0.4). :func:`decompose` splits exact identifiers out of the query
**first**, so a printed code becomes a phrase filter over the one exact code path
(:func:`~vsir.core.exact.exact_filter`) instead of being blurred into an embedding, and only the
prose is embedded. The three rankings fuse at ``rrf_k=60`` and the fused ordinal is the row's
``rank``.

**One implementation, exposed three times** (§7.2.1), and here that is a fact about the code and
not a description of it: :func:`_candidates` is the search, and `skim_pages`, `skim_documents` and
`skim_sections` are three renderings of the one list it returns — truncated to ``limit``, grouped
by ``doc_id``, grouped by ``section_id``. No second collection, no second filter, no extra
storage. An agent chooses far more reliably between three names than between three values of a
`granularity` enum, and grouping by `doc_id` is also what stops one chatty document occupying
every slot and burying the binder that answers.

`DocHit` and `SectionHit` carry **no `page_id`**: they answer *"which binder?"* and *"which
chapter?"* and hand back a scope to descend into (``next.expand``). What they do carry is a
`preview` — the thumbnail of the group's best-ranked matched page — and, on a document row,
`searchable_ratio`. That number is the point of the rung: a binder nothing can be found in by
text is **returned anyway**, at ``0.00`` with ``pages_matched: 0``, because the alternative is
that it disappears from the answer set in silence and the agent concludes the part is not in a
binder nobody looked in (§5.7, F4).

Three rules for an image query (D12), each of them stated in the response rather than implied:

1. **No instruction prefix when the query is multimodal** — applied in
   :func:`~vsir.ingest.embed.query_vector`, where the choice between the two embedding calls lives.
2. **An image-only query runs the dense branch alone.** `lexical` and `captions` are sparse vectors
   built from *text*; with no query text there is nothing to build. They are skipped, RRF
   degenerates to the dense ranking, and every row's ``why`` is ``["dense"]`` — so the agent can
   see that the evidence is weaker than a `lexical` hit (§8.2).
3. **An image can never reach the exact surface.** There is no image parameter on `lookup` or
   `verify`, and there is none here on the identifier path either: a photograph may *find* a
   candidate page, it can never *confirm* a code (I2, I3).

**What a triage row is not.** No full text and no ``bytes_b64`` (P2). Every page-level hit carries
an :class:`~vsir.serve.envelope.ImageRef` — a URL, a thumbnail URL and the dpi, about sixty bytes,
rendering nothing until something dereferences it. If a skim shipped rasters the agent would answer
from the search result instead of choosing and then paying, which is the failure P2 prevents.

**And no state.** ``scope`` and ``exclude`` are parameters, ``effective_scope`` is echoed back, and
this module holds nothing between calls (C11, F8, §15 Factor VI). Two processes given the same
``(query, image, scope, exclude)`` return the same rows in the same order, which is what makes the
L2 and E2E assertions stable (§16).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.config import RRF_K, SURFACE_WEIGHTS
from vsir.core import health, ids
from vsir.core.exact import UnknownScopeKey, exact_filter, scope_conditions
from vsir.core.indexed import DENSE_VECTOR, SPARSE_VECTORS
from vsir.core.observed_tokens import is_code_like
from vsir.core.tok import tok
from vsir.ingest import sparse
from vsir.ingest.embed import query_vector
from vsir.serve.caps import ToolError, as_tool_error, validate_skim_limit
from vsir.serve.envelope import (
    UNRANKED,
    DocHit,
    NextMoves,
    PageHit,
    Preview,
    Provenance,
    ScopeStats,
    SearchResponse,
    SectionHit,
    Status,
    weakness,
)
from vsir.serve.tools.lookup import (
    absence,
    count_exact,
    effective_scope,
    image_ref,
    no_text,
    scope_filter,
    scope_stats,
)

#: The dense branch is named ``page`` in :data:`~vsir.config.SURFACE_WEIGHTS` (§7.2.1 ordering rule
#: 1) and reported as ``dense`` in ``why`` (rule 3). One mapping, in one direction, so the weight a
#: reviewer reads in the config and the word an agent reads in a row cannot drift apart.
WHY = {"page": "dense", "lexical": "lexical", "captions": "captions"}

#: ``why`` is emitted in this order whatever order the branches ran in — a row is a value a caller
#: compares between two calls, and ``["lexical", "dense"]`` on one and ``["dense", "lexical"]`` on
#: the next would be a difference that means nothing (§16 reproducibility).
WHY_ORDER = ("dense", "lexical", "captions")

#: §7.2.1: ten rows by default, twenty-five at most.
SKIM_LIMIT = 10

#: How deep each branch reads before fusion — a **constant**, and deliberately not a multiple of
#: ``limit``. Two reasons, and the second is the one that bites.
#:
#: Fusion can only order what the branches handed it, so a branch that returned exactly ``limit``
#: rows would make the fused list the dense list whenever the other two disagreed with it. Fifty is
#: far enough down for the weights in play: a row one branch ranked 50th contributes ``1/(60+50)``
#: and cannot reach the top ten on that alone.
#:
#: And if the depth moved with ``limit``, ``limit=3`` would read a *different* candidate pool from
#: ``limit=10`` and could fuse it into a different order — so the first three rows of a ten-row
#: skim would not be the three rows of a three-row skim. An agent narrowing its list would see the
#: ranking move under it for no reason it could observe. With a fixed depth, ``limit`` truncates
#: the fused list and changes nothing else.
BRANCH_DEPTH = 50

#: The payload fields a triage row is built from. **`text` is not among them**, which makes P2
#: structural rather than careful: the page's text is never loaded into this process at all, so
#: there is no path by which it could reach a row. It also keeps a three-branch skim to a bounded
#: response from the store instead of 150 full pages of prose.
#:
#: ``doc_id`` and ``doc_type`` are here for the two aggregate rungs, which group these very rows
#: (§7.2.1) — one payload list for all three, because "the same page query aggregated differently"
#: has to be true of the *query*, and a second `with_payload` list is the first step towards a
#: second query.
ROW_PAYLOAD = ("doc_id", "doc_type", "page_no", "page_kind", "text_trust", "section_id",
               "content", "provenance")

#: The page numbers a hit offers as ``next.neighbours`` — the page before and the page after.
NEIGHBOUR_OFFSETS = (-1, 1)


_log = vsir_logging.get_logger(__name__)


@dataclass(frozen=True)
class FusedRow:
    """One fused result. Carries positions and provenance of positions — never a magnitude."""

    point_id: Any
    #: The surfaces that found this point, in the order they were fused — `PageHit.why`.
    surfaces: tuple[str, ...]
    surface_ranks: dict[str, int]
    #: The ordinal position after fusion, 1-based.
    rank: int

    @property
    def best_rank(self) -> int:
        """The best position any single surface gave this point — `DocHit.best_rank`'s input."""
        return min(self.surface_ranks.values())

    @property
    def why(self) -> list[str]:
        """The branches that contributed, named as §7.2.1 names them and always in one order."""
        found = {WHY[surface] for surface in self.surfaces if surface in WHY}
        return [name for name in WHY_ORDER if name in found]


def _total(surface_ranks: Mapping[str, int], weights: Mapping[str, float], k: int) -> float:
    """``Σ w / (k + rank)`` — private, and the only place the arithmetic lives.

    Kept off :class:`FusedRow` deliberately: it is an ordering device, not a property of a result,
    and a number that escapes into a response is a score somebody eventually displays.
    """
    return sum(weights.get(surface, 1.0) / (k + rank)
               for surface, rank in surface_ranks.items())


def rrf(branches: Mapping[str, Sequence[Any]],
        weights: Mapping[str, float] | None = None,
        k: int = RRF_K) -> list[FusedRow]:
    """Fuse per-surface result lists into one ordered list.

    ``branches`` maps a surface name to that surface's results **in rank order** — the position in
    the list is the rank, which is the whole input. A surface weighted ``0`` is switched off and
    contributes nothing, not even its presence in ``surfaces``.
    """
    weights = dict(SURFACE_WEIGHTS if weights is None else weights)

    ranks: dict[Any, dict[str, int]] = {}
    order: list[Any] = []
    for surface, results in branches.items():
        if weights.get(surface, 1.0) == 0:
            continue                       # weight 0 = the surface is switched off
        for rank, result in enumerate(results, start=1):
            point_id = getattr(result, "id", result)
            if point_id not in ranks:
                ranks[point_id] = {}
                order.append(point_id)
            ranks[point_id].setdefault(surface, rank)

    ordered = sorted(
        order,
        key=lambda point_id: (-_total(ranks[point_id], weights, k),
                              min(ranks[point_id].values()),
                              str(point_id)),
    )
    return [
        FusedRow(point_id=point_id,
                 surfaces=tuple(ranks[point_id]),
                 surface_ranks=dict(ranks[point_id]),
                 rank=position)
        for position, point_id in enumerate(ordered, start=1)
    ]


# ── the query, split before anything is embedded (§7.2.1 ordering rule 1) ────────────────────────

@dataclass(frozen=True)
class Decomposed:
    """A query, split into the part that is matched and the part that is embedded.

    Both halves are kept verbatim rather than as tokens: ``identifiers`` go to
    :func:`~vsir.core.exact.exact_filter`, which owns `variants()` and the phrase, and ``prose``
    goes to the embedding, which reads words.
    """

    identifiers: tuple[str, ...]
    prose: str
    #: The query as the caller typed it — what the sparse branches are built from.
    text: str

    @property
    def embedded(self) -> str:
        """What actually reaches the embedding model. Empty is legal: an image can carry a query."""
        return self.prose


def decompose(query: str) -> Decomposed:
    """Split the exact identifiers out of a query **before** anything is embedded.

    ``decompose("reset K158")`` sends ``K158`` to the phrase filter and only ``reset`` to the
    embedding. That is §7.2.1's ordering rule 1 and it is what §8.2's *auto-promote exact hits*
    rests on: a printed code blurred into a 1,536-dimensional average is a code that ranks pages
    which merely *resemble* the one printing it, and the whole guarantee of §1.1 is that a code
    this service returns is a code printed on a page.

    **The rule is §6.8's, not a grammar.** A word is an identifier if it contains a digit —
    :func:`~vsir.core.observed_tokens.is_code_like`, imported rather than re-stated so there is one
    definition of *code-like* in the codebase. §5.2 prohibits an identifier grammar anywhere in
    extraction or derivation and the same argument applies here: no per-corpus regex decides which
    shapes of code a caller is allowed to search for. The crudeness is affordable in **this**
    direction, too, but for a different reason than it is for `present_instead`: a word wrongly
    called an identifier is asked of the exact surface, which is stricter, not looser — the failure
    is a narrower answer that says so (`total`, `weak`), never a wrong page.

    **Adjacent words are not joined.** `impl`'s ``token_set()`` joined neighbouring tokens so its
    curated-keyword gate could see ``84-5140.0020`` as one key; §5.6 struck that and §2.4 says not
    to port it. So ``"SF 1.1A"`` decomposes to the identifier ``1.1A`` and the prose ``SF``, and
    the phrase ``[1, 1a]`` — contiguous, in order — is what the index is asked for. That is the
    same phrase `lookup("SF 1.1A")` would match with, one token shorter.
    """
    words = [word for word in (query or "").split() if word.strip()]
    identifiers = tuple(word for word in words if any(is_code_like(token) for token in tok(word)))
    prose = " ".join(word for word in words if word not in identifiers)
    return Decomposed(identifiers=identifiers, prose=prose, text=" ".join(words))


# ── the branches ────────────────────────────────────────────────────────────────────────────────

def branch_filter(scope: Mapping[str, Any], identifiers: Sequence[str],
                  exclude: Sequence[str]) -> qm.Filter:
    """The filter every branch runs inside: the scope, the identifiers, minus ``exclude``.

    The identifiers are **nested `exact_filter` calls**, not phrase conditions built here. There is
    one exact-match code path in this codebase (I3, F1) and `serve/` does not get a second one: a
    `MatchPhrase` assembled in this module would be a place where `variants()` could be forgotten,
    and a forgotten spelling is a page that silently stops being findable. Two identifiers are
    ANDed, and each one's three spellings are ORed inside it, which is exactly what
    `lookup("K158")` asks and what the answer gate will later confirm.

    **No trust condition, and that is the difference between triage and evidence.** `lookup`
    excludes `untrusted` and `no_text` pages from its hits, because a phrase matching inside a
    garbled extraction is not a verified hit (§5.7, F4). A skim row is not a hit on the exact
    surface — it is a page worth looking at — so an `untrusted` page that carries the code is a
    candidate, and the row reports ``text_trust`` so the caller can see what it is being handed.
    Filtering it out here would be the silent recall loss R1 is about, on exactly the pages vision
    exists to read.

    ``exclude`` is a ``must_not`` over **point ids**, not over a payload field. ``page_id`` is not
    in `INDEXED` and must not become a caller-supplied filter (I6, §5.4); the point id is
    ``uuid5(page_id)`` (I1), so excluding by identity is both indexed by construction and exactly
    what the agent means — *"I have already looked at this page"*.
    """
    must: list[qm.Condition] = [*scope_conditions(scope),
                                *(exact_filter(identifier) for identifier in identifiers)]
    must_not = [qm.HasIdCondition(has_id=[ids.point_id(page_id) for page_id in exclude])] \
        if exclude else []
    return qm.Filter(must=must, must_not=must_not)


def _points(client: Any, collection: str, *, query: Any, using: str,
            query_filter: qm.Filter, limit: int) -> list[Any]:
    """One branch's ranking. The list position **is** the rank — nothing else is read off it."""
    response = client.query_points(collection, query=query, using=using,
                                   query_filter=query_filter, limit=limit,
                                   with_payload=list(ROW_PAYLOAD), with_vectors=False)
    return list(response.points)


def _sparse_query(text: str) -> qm.SparseVector | None:
    """The query's sparse vector — raw term frequencies, IDF applied by Qdrant at query time (D2).

    ``None`` when the query has no tokens at all, which is what makes an image-only query skip the
    two sparse branches rather than send an empty vector Qdrant would happily score nothing with.
    """
    indices, values = sparse.build(text)
    return qm.SparseVector(indices=indices, values=values) if indices else None


# ── the candidate set the three rungs share (§7.2.1: "the same page query") ─────────────────────

@dataclass(frozen=True)
class Candidates:
    """One page query, run once — and the only thing any of the three rungs ever ranks.

    §7.2.1's *"one implementation, exposed three times"* is this object. `skim_pages` truncates
    :attr:`fused` to ``limit`` and renders a row per page; `skim_documents` and `skim_sections`
    group the very same list and render a row per group. There is no second collection, no second
    filter and no second `with_payload`, so the three rungs cannot drift apart into three
    retrievals that happen to be described by one paragraph.
    """

    #: The caller's scope with ``is_current=True`` injected — echoed back as `effective_scope`.
    scope: dict
    #: The same scope, built once and gated by `INDEXED` once — the denominator every count in
    #: this module is taken against, so no rung rebuilds it and risks building it differently.
    scoped: qm.Filter
    split: Decomposed
    #: Every fused candidate, in rank order and **untruncated**. `limit` is a property of the page
    #: rung's output, not of the search.
    fused: tuple[FusedRow, ...]
    payloads: Mapping[Any, Mapping[str, Any]]
    stats: ScopeStats
    #: Pages of the scope with a text layer that may be believed — what chooses the absence (§5.7).
    searchable_pages: int
    #: ``count(exact=True)`` over the narrowed filter: the size of the set the branches were
    #: allowed to rank. Pages, on every rung — `weak` means the same thing on all three.
    total: int
    branches: tuple[str, ...]

    def payload(self, row: FusedRow) -> Mapping[str, Any]:
        return self.payloads[row.point_id]

    def page_id(self, row: FusedRow) -> str:
        return str((self.payload(row).get("provenance") or {}).get("page_id") or "")


def _candidates(client: Any, collection: str, *, rung: str, query: str, image: bytes | None,
                scope: Mapping[str, Any] | None, exclude: Sequence[str],
                embedder: Any) -> Candidates:
    """Run the three branches inside the scope and fuse them. The whole of §7.2.1's ordering.

    Every refusal is a typed :class:`~vsir.serve.caps.ToolError` naming its bound and it happens
    here, before a round trip is spent: a query that is neither words nor a photograph, and a
    filter key absent from `INDEXED` — ``filter_unknown_key``, a `400` rather than an unindexed
    scan (I6, F10). ``rung`` names the tool in the refusal, because an agent that asked
    `skim_sections` for nothing should be told about `skim_sections`.
    """
    has_query = bool((query or "").strip())
    if not has_query and image is None:
        raise ToolError(
            "query_required",
            f"{rung} takes a query, an image, or both (§7.2.1) — neither is not a search, and "
            "an empty query embedded as the empty string still returns ten confident-looking rows",
            requested={"query": bool(has_query), "image": image is not None},
        )

    scope_in_force = effective_scope(scope)
    split = decompose(query or "")
    try:
        scoped = scope_filter(scope_in_force)
        narrowed = branch_filter(scope_in_force, split.identifiers, exclude)
    except UnknownScopeKey as refusal:
        raise as_tool_error(refusal) from None

    stats, searchable_pages = scope_stats(client, collection, scoped)
    total = count_exact(client, collection, narrowed)

    # **A branch runs when it has an input, and says so in `why` when it did.** One rule, applied
    # twice. An image-only query has no text to build a sparse vector from, so `lexical` and
    # `captions` are skipped and RRF degenerates to the dense ranking (D12 rule 2). A query that
    # decomposes to identifiers only — `"K158"` — has nothing left to embed once the code has gone
    # to the phrase filter, so the dense branch is skipped for the same reason and in the same
    # spelling: embedding the code anyway would be the blurring rule 1 exists to prevent, and
    # inventing a query for it would be worse. Every query reaches at least one branch, because
    # the two conditions are exhaustive over "words, a photograph, or both".
    branches: dict[str, list[Any]] = {}
    if split.embedded.strip() or image is not None:
        branches["page"] = _points(client, collection, query=query_vector(
            embedder, text=split.embedded, image=image),
            using=DENSE_VECTOR, query_filter=narrowed, limit=BRANCH_DEPTH)
    sparse_query = _sparse_query(split.text) if has_query else None
    if sparse_query is not None:
        for surface in SPARSE_VECTORS:
            branches[surface] = _points(client, collection, query=sparse_query, using=surface,
                                        query_filter=narrowed, limit=BRANCH_DEPTH)

    return Candidates(
        scope=scope_in_force,
        scoped=scoped,
        split=split,
        fused=tuple(rrf(branches)),
        payloads={point.id: (point.payload or {})
                  for points in branches.values() for point in points},
        stats=stats,
        searchable_pages=searchable_pages,
        total=total,
        branches=tuple(sorted(branches)),
    )


def _absence_moves(found: bool, split: Decomposed) -> NextMoves | None:
    """The affordance an empty rung owes its caller — the same one on all three (§7.1).

    The narrowing is what emptied it, and the caller cannot see that from `effective_scope`: the
    identifiers are a filter, not a scope key. `lookup` is the move that answers *"is this code
    printed anywhere at all"*, so the affordance names it rather than leaving the agent to abstain
    about a code that may simply not be in this document.
    """
    return None if found or not split.identifiers else NextMoves(suggest=["lookup"])


# ── the rung ────────────────────────────────────────────────────────────────────────────────────

def _summary(content: Mapping[str, Any], scope: Mapping[str, Any]) -> tuple[str, str]:
    """``(text, lang)`` — the summary in the caller's requested language, or the dominant one (D5).

    The requested language is ``scope["lang"]``, because `lang` is an indexed facet and the scope
    is where a caller says which one it wants; there is no second parameter for it. The fallback is
    the page's **first** summary, which is its dominant language (§5.2), and the row states which
    language it returned rather than leaving the caller to guess from the words.
    """
    summaries = content.get("summaries") or []
    if not summaries:
        return "", ""
    wanted = scope.get("lang")
    wanted = [wanted] if isinstance(wanted, str) else list(wanted or ())
    for summary in summaries:
        if summary.get("lang") in wanted:
            return str(summary.get("text") or ""), str(summary.get("lang") or "")
    first = summaries[0]
    return str(first.get("text") or ""), str(first.get("lang") or "")


def _page_counts(client: Any, collection: str,
                 documents: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """``(doc_id, revision) → page count`` for the documents the rows came from.

    Needed for ``next.neighbours``: offering ``#p000`` or a page past the end of the document is an
    affordance that 404s, and a caller that trusted it would read the miss as *"the page is not in
    the corpus"*. One exact count per distinct document in ≤ 10 rows — indexed, and almost always
    one call. The count is of the **document**, not of the caller's scope: a neighbour exists
    whether or not the current filter would have returned it.
    """
    return {
        (doc_id, revision): count_exact(
            client, collection,
            scope_filter({"doc_id": doc_id, "revision": revision, "is_current": True}))
        for doc_id, revision in sorted(set(documents))
    }


def _next_moves(payload: Mapping[str, Any], pages: int) -> NextMoves:
    """P4's affordances on one row: expand into the section, step to a neighbour.

    ``expand`` is a **scope**, not an id: it is handed straight back as `skim_pages`' ``scope``
    argument, so *"the rest of this section"* costs the caller no string assembly and cannot be
    spelled wrong. A page straddling two sections offers both (§5.3, F8).

    ``references`` is deliberately **empty, not omitted**. §7.2.1 declares it as *"[printed
    labels]"* — the cross-references printed on the page, for `resolve` to follow — and there is no
    field on the §5.3 record to read them from: `refs[]` was measured at zero reads anywhere in
    `impl` and §2.5 B struck it. The alternative is a cross-reference grammar scraped out of the
    page text at query time, which is the one thing §5.2 refuses and F5's injury. So the field
    stays in the contract, empty, and a caller that reads a label itself can still `resolve` it.
    """
    provenance = payload.get("provenance") or {}
    page_id = str(provenance.get("page_id") or "")
    sections = [str(section_id) for section_id in (payload.get("section_id") or [])]
    neighbours: list[str] = []
    if page_id:
        doc_id, revision, page_no = ids.parse_page_id(page_id)
        neighbours = [ids.page_id(doc_id, revision, page_no + offset)
                      for offset in NEIGHBOUR_OFFSETS
                      if 1 <= page_no + offset <= pages]
    return NextMoves(expand={"section_id": sections} if sections else {},
                     neighbours=neighbours)


def hit_from(row: FusedRow, payload: Mapping[str, Any], *, scope: Mapping[str, Any],
             pages: int) -> PageHit:
    """One fused row and its payload → one triage row (§7.1, §7.2.1).

    **No full text and no bytes.** ``summary`` is the page's summary, ``image`` is a reference, and
    ``text`` never appears — an agent that could answer from the row would stop reasoning and start
    pattern-matching (P2). ``grounded_rate`` is passed through as it is stored, including the
    ``None`` on a page with no text layer: there was nothing to be grounded in, and a ``0.0`` there
    would read as *"extraction is broken"* (§5.7).
    """
    content = payload.get("content") or {}
    provenance = payload.get("provenance") or {}
    page_id = str(provenance.get("page_id") or "")
    summary, lang = _summary(content, scope)
    return PageHit(
        page_id=page_id,
        printed_page_no=str(content.get("printed_page_no") or ""),
        summary=summary,
        summary_lang=lang,
        page_kind=str(payload.get("page_kind") or "prose"),
        why=row.why,
        rank=row.rank,
        flags=[str(flag) for flag in (content.get("flags") or [])],
        grounded_rate=content.get("grounded_rate"),
        text_trust=payload.get("text_trust") or "no_text",
        image=image_ref(page_id) if page_id else None,
        next=_next_moves(payload, pages),
    )


def skim_pages(client: Any, collection: str, *,
               query: str = "",
               image: bytes | None = None,
               scope: Mapping[str, Any] | None = None,
               exclude: Sequence[str] = (),
               limit: int = SKIM_LIMIT,
               embedder: Any,
               provenance: Provenance,
               reads_remaining: int = 0) -> SearchResponse[PageHit]:
    """The page rung of the narrowing ladder: ≤ ``limit`` triage rows, score-free and repeatable.

    ``limit`` outside 1…25 is a typed refusal naming its bound; the rest of the refusals belong to
    :func:`_candidates`, which is the search all three rungs run.

    ``total`` is the size of the set the branches were allowed to rank — the scope, narrowed by the
    identifiers and by ``exclude`` — and not the length of the fused list. That is what makes
    `weak`/`needs_scope` mean something on a rung where a dense branch always has *something* to
    return: an unscoped skim of a 1,440-page manual reports 1,440 and says `needs_scope`, while
    ``skim_pages("reset K158")`` inside one document reports the two pages that print `K158` and
    does not. The formula is §7.1's, against the server constant :data:`WEAK_ABS`, so no caller
    parameter can flip it.
    """
    validate_skim_limit(limit)
    found = _candidates(client, collection, rung="skim_pages", query=query, image=image,
                        scope=scope, exclude=exclude, embedder=embedder)

    rows = found.fused[:limit]
    counts = _page_counts(client, collection,
                          [ids.parse_page_id(page_id)[:2]
                           for page_id in (found.page_id(row) for row in rows) if page_id])

    hits: list[PageHit] = []
    for row in rows:
        payload = found.payload(row)
        page_id = found.page_id(row)
        doc_key = ids.parse_page_id(page_id)[:2] if page_id else ("", "")
        hits.append(hit_from(row, payload, scope=found.scope, pages=counts.get(doc_key, 0)))

    is_weak = weakness(found.total, found.stats.pages)
    status = Status.OK if hits else absence(found.stats.pages, found.searchable_pages)
    response = SearchResponse[PageHit](
        status=status,
        hits=hits,
        total=found.total,
        capped=found.total > len(hits),
        weak=is_weak,
        needs_scope=is_weak,
        next=_absence_moves(bool(hits), found.split),
        effective_scope=found.scope,
        scope_stats=found.stats,
        reads_remaining=reads_remaining,
        provenance=provenance,
    )
    _log_rung("skim_pages", found, response, query=query, image=image, exclude=exclude,
              limit=limit)
    return response


# ── the two aggregate rungs — the same fused candidates, grouped (§7.2.1 rule 4) ─────────────────

@dataclass(frozen=True)
class Group:
    """One aggregate row's worth of fused candidates, in fused order.

    ``rows`` is a slice of the one fused list, never a re-query, which is what makes
    ``pages_matched`` *the number of `skim_pages` rows in this group* rather than a second
    count that agrees with it most of the time.
    """

    key: str
    rows: tuple[FusedRow, ...]

    @property
    def pages_matched(self) -> int:
        return len(self.rows)

    @property
    def best_rank(self) -> int:
        """The best position any page of this group reached — the rows are in fused order."""
        return self.rows[0].rank if self.rows else UNRANKED

    @property
    def order(self) -> tuple[int, int, str]:
        """§7.2.1 rule 4: ``(best_rank, -pages_matched)``, made total.

        The key is the last element, so two groups sharing a best page — which is what a page
        straddling two sections is — come back in the same order on every call (§16). Only
        groups that matched are ever sorted: a disclosure row has no rank to sort on and is
        appended after all of them.
        """
        return (self.best_rank, -self.pages_matched, self.key)


def group_by(found: Candidates, keys_of: Any) -> list[Group]:
    """Group the fused candidates by whatever ``keys_of(payload)`` returns, in §7.2.1's order.

    ``keys_of`` returns a *sequence*, because a page belongs to one document and to **any number
    of sections**: a page straddling two sections is counted in both groups, which is §5.3's
    array field arriving at the surface it exists for (F8). Insertion order is fused order, so
    each group's first row is its best-ranked page and no group is ever re-sorted.
    """
    grouped: dict[str, list[FusedRow]] = {}
    for row in found.fused:
        for key in keys_of(found.payload(row)):
            if key:
                grouped.setdefault(str(key), []).append(row)
    groups = [Group(key=key, rows=tuple(rows)) for key, rows in grouped.items()]
    return sorted(groups, key=lambda group: group.order)


def _preview(page_id: str) -> Preview | None:
    """The group's thumbnail — a **reference**, at the 72-dpi triage tier, rendering nothing.

    Built through :func:`~vsir.serve.tools.lookup.image_ref`, which owns the route's grammar and
    its percent-encoding: a ``page_id`` contains a ``#`` (§5.1) and an unencoded one makes every
    reference a request for the document with a fragment the server never sees.
    """
    return Preview(page_id=page_id, thumb_url=image_ref(page_id).thumb_url) if page_id else None


def _facet_counts(client: Any, collection: str, query: qm.Filter, limit: int) -> dict[str, int]:
    """``doc_id → pages`` under ``query``. Exact, because a ratio built on an estimate is a lie."""
    return {str(hit.value): hit.count for hit in
            client.facet(collection, key="doc_id", facet_filter=query,
                         limit=limit, exact=True).hits}


def _ratios(client: Any, collection: str, found: Candidates,
            doc_ids: Sequence[str]) -> dict[str, float]:
    """``doc_id → searchable_ratio`` for the documents that will be rows (§5.7).

    Counted for **these documents** rather than read off `scope_stats.docs`, which is capped at
    :data:`~vsir.serve.tools.lookup.SCOPE_STAT_DOCS` documents because it is a display. A row is
    not a display: a matched binder that fell outside that cap would inherit the default `0.0`
    and be reported as a blind spot — the one number on this row an agent is meant to act on,
    inverted. Two facets, bounded by the ten rows, and the same ``scoped`` filter underneath, so
    where a document appears in both the two numbers are the same number.

    It is therefore the ratio over **what was searched**: with the ordinary scopes — none, or a
    `doc_id` — that is exactly the document's §5.7 ratio, and with a narrower one it answers the
    question the caller actually asked, *"how much of what you searched in this binder could be
    searched at all"*.
    """
    if not doc_ids:
        return {}
    within = qm.Filter(must=[found.scoped,
                             qm.FieldCondition(key="doc_id",
                                               match=qm.MatchAny(any=list(doc_ids)))])
    pages = _facet_counts(client, collection, within, len(doc_ids))
    blank = _facet_counts(client, collection, qm.Filter(must=[within, no_text()]), len(doc_ids))
    return {doc_id: health.ratio(pages.get(doc_id, 0),
                                 pages.get(doc_id, 0) - blank.get(doc_id, 0))
            for doc_id in doc_ids}


def _blind_spots(stats: ScopeStats, matched: Iterable[str]) -> list[str]:
    """The documents in scope that matched nothing **and cannot be matched by text** (§5.7, F4).

    This is the disclosure the rung exists for. A fully scanned binder has no text surface, so a
    query carrying a printed code excludes every one of its pages from every branch — and without
    this it would leave the answer set in silence, leaving the agent to conclude the part is not
    in a binder nobody looked in. It is returned instead, with ``searchable_ratio: 0.00``,
    ``pages_matched: 0`` and a thumbnail, sorted after every group that did match so it can never
    displace a result.

    Only ratio **zero** qualifies (:func:`~vsir.core.health.blind_spot`): a partly scanned
    document is found through the pages that do have text, and disclosing every document that
    merely failed to match would return the corpus and undo the narrowing.

    `scope_stats.docs` is the input, so the disclosure reaches as far as that breakdown does. A
    document is only ever *added* from it, never scored from it — the ratio a row carries is
    counted by :func:`_ratios`.
    """
    seen = set(matched)
    return sorted(stat.doc_id for stat in stats.docs
                  if stat.doc_id not in seen and health.blind_spot(stat.searchable_ratio))


def _first_pages(client: Any, collection: str,
                 doc_ids: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    """``doc_id → the payload of page 1``, for the disclosure rows (§7.1's preview fallback).

    §7.1: the preview is *"the group's best-ranked matched page, falling back to page 1 when
    nothing matched"* — and page 1 is the only page of a document a caller can be offered without
    a ranking to choose from. One scroll per disclosed document, and only for the ones that
    survive the ≤ 10 cut, so an unscoped skim of a corpus of scanned binders costs at most ten.

    It also supplies what the row would otherwise have to invent: the document's current
    ``revision`` — the page id needs it and a `DocHit` carries no revision field — its
    ``doc_type``, and page 1's own summary, which is the one sentence about a binder that has no
    other way of saying what it is.
    """
    found: dict[str, Mapping[str, Any]] = {}
    for doc_id in doc_ids:
        # The document's first page, not the scope's: this identifies a page rather than
        # searching for one, so the caller's other keys are not applied — a `page_no: 5` scope
        # must not turn *"page 1"* into *"page 5"*. ``is_current`` **is** applied, unconditionally
        # and server-side as everywhere else: a superseded cover sheet cannot preview a current
        # document (I7, F9).
        points, _ = client.scroll(
            collection,
            scroll_filter=scope_filter({"doc_id": doc_id, "is_current": True, "page_no": 1}),
            limit=1, with_payload=list(ROW_PAYLOAD), with_vectors=False)
        if points:
            found[doc_id] = points[0].payload or {}
    return found


def _doc_hit(group: Group, payload: Mapping[str, Any], *, scope: Mapping[str, Any],
             searchable: float, page_id: str) -> DocHit:
    """One group → one *"which binder?"* row (§7.1, §7.2.1).

    **No `page_id`, no text, no bytes.** The row hands back a scope — ``next.expand`` — and the
    caller descends with it; choosing the page for them is the routing §7.6 refuses.

    ``title`` is empty and that is a fact about the record, not an oversight: §5.3 has no
    document-level title to read, the PDF's ``/Info`` title is metadata this pipeline never
    stores, and deriving one from the filename or the first section heading would be an
    interpretation — the same argument §5.2 makes against a scraped grammar. The field stays in
    the contract, like ``next.references``, and ``summary`` carries the sentence a person
    actually needs.
    """
    summary, _lang = _summary(payload.get("content") or {}, scope)
    return DocHit(
        doc_id=group.key,
        doc_type=str(payload.get("doc_type") or ""),
        pages_matched=group.pages_matched,
        best_rank=group.best_rank,
        searchable_ratio=searchable,
        summary=summary,
        preview=_preview(page_id),
        next=NextMoves(expand={"doc_id": group.key}),
    )


def skim_documents(client: Any, collection: str, *,
                   query: str = "",
                   image: bytes | None = None,
                   scope: Mapping[str, Any] | None = None,
                   exclude: Sequence[str] = (),
                   embedder: Any,
                   provenance: Provenance,
                   reads_remaining: int = 0) -> SearchResponse[DocHit]:
    """*"Which binder?"* — the same fused candidates as `skim_pages`, grouped by ``doc_id``.

    Grouping is not only a presentation: it is what stops one chatty document occupying every
    slot and burying the binder that answers (§7.2.1). ≤ 10 rows, ordered by
    ``(best_rank, -pages_matched)``, and every row carries `searchable_ratio` — the agent's blind
    spot as a number (§5.7) — plus, sorted after them, a row for every fully scanned document in
    scope that matched nothing at all (:func:`_blind_spots`).

    `status` is decided by the pages, exactly as on the page rung, and **not** by whether a
    disclosure row is present: a scope in which nothing searchable matched is `not_searchable`
    even when this rung can name the binders to escalate to. Saying `ok` because the blind spot
    was disclosed would turn the disclosure into the answer.
    """
    found = _candidates(client, collection, rung="skim_documents", query=query, image=image,
                        scope=scope, exclude=exclude, embedder=embedder)

    every = group_by(found, lambda payload: (payload.get("doc_id"),))
    groups = every[:SKIM_LIMIT]
    # The disclosure rows are chosen **before** any of them is rendered, so the ratio every row
    # carries — matched or disclosed — is counted by one call for one list of documents.
    spots = _blind_spots(found.stats, (group.key for group in groups))
    disclosed = spots[:SKIM_LIMIT - len(groups)]
    page_ones = _first_pages(client, collection, disclosed)
    resolved = [doc_id for doc_id in disclosed if doc_id in page_ones]
    ratios = _ratios(client, collection, found,
                     [group.key for group in groups] + resolved)

    hits = [
        _doc_hit(group, found.payload(group.rows[0]), scope=found.scope,
                 searchable=ratios.get(group.key, 0.0), page_id=found.page_id(group.rows[0]))
        for group in groups
    ]
    hits += [
        _doc_hit(Group(key=doc_id, rows=()), page_ones[doc_id], scope=found.scope,
                 searchable=ratios.get(doc_id, 0.0),
                 page_id=str((page_ones[doc_id].get("provenance") or {}).get("page_id") or ""))
        for doc_id in resolved
    ]

    is_weak = weakness(found.total, found.stats.pages)
    response = SearchResponse[DocHit](
        status=Status.OK if groups else absence(found.stats.pages, found.searchable_pages),
        hits=hits,
        total=found.total,
        # `capped` is about the **rows**, and on an aggregate rung a row is a group: `total`
        # counts pages, so comparing it with `len(hits)` would report a cut on every call that
        # grouped anything at all. What a caller needs to know here is that there was more to
        # show than came back — a group that did not fit, or a blind spot that did not.
        capped=len(every) > len(groups) or len(spots) > len(disclosed),
        weak=is_weak,
        needs_scope=is_weak,
        next=_absence_moves(bool(groups), found.split),
        effective_scope=found.scope,
        scope_stats=found.stats,
        reads_remaining=reads_remaining,
        provenance=provenance,
    )
    _log_rung("skim_documents", found, response, query=query, image=image, exclude=exclude,
              groups=len(groups), disclosed=len(hits) - len(groups))
    return response


def _section_of(payload: Mapping[str, Any], section_id: str) -> Mapping[str, Any]:
    """The stored section with this id, off the page that belongs to it (§5.3 ``content.sections``).

    ``title`` and ``page_range`` are read from the **best-ranked** page of the group rather than
    recomputed from the group's own pages: the range is the section's extent after stitching
    (§6.1 step 07), which is a property of the document, and a range derived from the pages that
    happened to match would shrink as the query narrowed and read as though the chapter itself
    were smaller.
    """
    for section in (payload.get("content") or {}).get("sections") or ():
        if str(section.get("section_id") or "") == section_id:
            return section
    return {}


def skim_sections(client: Any, collection: str, *,
                  query: str = "",
                  image: bytes | None = None,
                  scope: Mapping[str, Any] | None = None,
                  exclude: Sequence[str] = (),
                  embedder: Any,
                  provenance: Provenance,
                  reads_remaining: int = 0) -> SearchResponse[SectionHit]:
    """*"Which chapter?"* — the same fused candidates, grouped by ``section_id``.

    A page that straddles two sections is counted in both (§5.3, F8), so the groups may overlap
    and two of them may share a best-ranked page; the ordering is total, so the rows come back
    the same way on every call.

    There is no blind-spot disclosure here and that is deliberate. `searchable_ratio` is a
    **document** signal (§5.7) and a `SectionHit` has no field to carry it, so a disclosed
    section would be a row that says *"this chapter matched nothing"* without the one number
    that explains why — which is a row an agent cannot act on. The binder is disclosed one rung
    up, by `skim_documents`, where the ratio is on the row.
    """
    found = _candidates(client, collection, rung="skim_sections", query=query, image=image,
                        scope=scope, exclude=exclude, embedder=embedder)

    every = group_by(found, lambda payload: payload.get("section_id") or ())
    groups = every[:SKIM_LIMIT]
    hits: list[SectionHit] = []
    for group in groups:
        payload = found.payload(group.rows[0])
        section = _section_of(payload, group.key)
        page_range = section.get("page_range")
        hits.append(SectionHit(
            section_id=group.key,
            title=str(section.get("title") or ""),
            page_range=tuple(page_range) if page_range else None,
            pages_matched=group.pages_matched,
            best_rank=group.best_rank,
            preview=_preview(found.page_id(group.rows[0])),
            next=NextMoves(expand={"section_id": [group.key]}),
        ))

    is_weak = weakness(found.total, found.stats.pages)
    response = SearchResponse[SectionHit](
        status=Status.OK if hits else absence(found.stats.pages, found.searchable_pages),
        hits=hits,
        total=found.total,
        capped=len(every) > len(hits),
        weak=is_weak,
        needs_scope=is_weak,
        next=_absence_moves(bool(hits), found.split),
        effective_scope=found.scope,
        scope_stats=found.stats,
        reads_remaining=reads_remaining,
        provenance=provenance,
    )
    _log_rung("skim_sections", found, response, query=query, image=image, exclude=exclude,
              groups=len(every))
    return response


def _log_rung(tool: str, found: Candidates, response: SearchResponse, *,
              query: str, image: bytes | None, exclude: Sequence[str], **extra: Any) -> None:
    """One `debug` line per rung, in one shape (§7.4, §11.4).

    `debug`, like `lookup`: §7.4 audits the two tools that spend and §11.4 asks for nothing per
    call from a free one. The branches that ran and the identifiers that were split out are what
    an operator needs to explain an order, and neither is reconstructible from the response.
    """
    _log.debug(
        tool,
        tool=tool,
        query=query,
        identifiers=list(found.split.identifiers),
        embedded=found.split.embedded,
        image=image is not None,
        branches=list(found.branches),
        status=response.status.value,
        total=found.total,
        hits=len(response.hits),
        candidates=len(found.fused),
        excluded=len(exclude),
        weak=response.weak,
        scope_keys=sorted(found.scope),
        pages=found.stats.pages,
        pages_no_text=found.stats.pages_no_text,
        **extra,
    )
