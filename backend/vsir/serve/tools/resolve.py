"""FOLLOW — ``resolve(printed_label, doc_id?)`` (Spec §7.2.3, F5).

An agent reading page 12 finds *"see page 8"* and needs the `page_id` that opens. That is the whole
tool: a **printed** label — what a person reads in a footer or a cross-reference — turned into the
identifier this service addresses pages by, with two disclosures that are as much of the answer as
the id is.

* ``label_verified`` — the page's own text layer prints that label (§6.5, and the same phrase
  question `lookup` asks, through the same :func:`~vsir.core.exact.exact_filter`).
* ``interpolated`` — the label was **inferred from the pages either side**, not read off this one.
  §6.5 permits exactly one inference, the bracketed one, and permits it only if it says so.

A page whose own label is **ambiguous** answers to every reading of it (``content.label_candidates``,
§6.5), not to none: reading only ``printed_page_no`` would leave the page a citation is most likely
to be wrong about the one page no citation could open (:func:`labels_of`).

And one refusal: **ambiguity returns every candidate** (F5). Two documents both printing *"8"*, or
a manual that restarts its numbering at every chapter, produce two hits and not a silent pick. The
injury F5 names is *"follows a cross-reference to the wrong page"*, and a resolver that chooses for
the agent is how that happens — the agent then cites a page it was never shown.

**Ported from `impl/app/retrieve.py::resolve`, and the one thing not ported is its mechanism.**
Register **E9**: ``find_by_printed_label`` scrolled 4,096 points and filtered them in Python —
*"falls over well before the 1,440-page manual"*. The defect is not the Python loop, it is the
fixed scroll bound: page 1,500 of a 1,440-page manual (a corpus of two such manuals) is simply
never reached, and the tool reports *not found* about a page it never looked at. Here the **index**
does the selecting, twice over:

1. the label is asked of the ``text`` phrase index — one indexed query over `variants()`, the one
   exact-match code path (I3), not a scan;
2. ``doc_id`` is **faceted** over that same filter, so *"which binders print this label"* is
   answered by the index rather than by counting payloads in this process.

Only the bounded candidate page returned by (1) is looked at in Python, and only to compare its
**stored** printed label with the one that was asked for. Nothing in this module scrolls.

**A citation is not a label.** What an agent reads on a page is *"see page 8"* or *"Page 8 of 55"*;
what a footer prints is ``8``. So when the citation as typed matches nothing, the words of it that
could themselves be a label are asked for one at a time (:func:`label_words`), and every candidate
is still confirmed against the **whole** citation. The second probe of *"Page 8 of 55"* can legitimately
find the page numbered 55, and that is not a defect to be tuned away: the citation really is
ambiguous evidence for it, and F5's answer to ambiguity is every candidate.

**The bracket, and why it is here rather than only at ingest.** A phrase query can only find a
label the page prints. An `interpolated` label is by definition *not* printed — it came from the
neighbours at derivation (§6.5's :func:`~vsir.ingest.derive.interpolate_labels`) — so the first
mechanism is structurally blind to exactly the case §7.2.3 asks this tool to disclose. So when the
phrase finds nothing and the label is a plain integer, the same bracket rule runs at query time:
if *n−1* and *n+1* are printed on two pages of one document two apart, the page between them is
the answer, returned ``interpolated: true`` and ``label_verified: false``. A bracket is not a
formula — §6.5 is explicit that no ``printed + offset = pdf`` relation exists in this corpus,
because the offset changes at every chapter — so nothing here extrapolates from one neighbour.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.core import ids
from vsir.core.exact import UnknownScopeKey, contains_phrase, exact_filter
from vsir.core.observed_tokens import is_code_like
from vsir.core.tok import tok
from vsir.serve.caps import ToolError, as_tool_error
from vsir.serve.envelope import (
    NextMoves,
    Provenance,
    ResolveHit,
    SearchResponse,
    Status,
    weakness,
)
from vsir.serve.tools.lookup import (
    absence,
    count_exact,
    effective_scope,
    image_ref,
    scope_filter,
    scope_stats,
)

#: How many candidate pages are compared per round trip.
RESOLVE_CANDIDATES = 64

#: How many such rounds one probe may make — the bound on how wide a free call gets. Beyond it the
#: response says ``capped`` and reports the exact ``total`` the index counted, so a caller can see
#: that the set was bigger than the look and narrow with ``doc_id``. That disclosure is the whole
#: difference from register E9, whose fixed 4,096-point scroll reported `not_found` about pages it
#: had never reached.
RESOLVE_SCAN_PAGES = 8

#: The documents named in the log line when a label spans more than one. A display bound.
RESOLVE_FACET_DOCS = 16

#: How many words of a citation are probed as labels in their own right. *"Page 8 of 55"* has two;
#: the bound exists so a caller cannot turn one resolve into a query per word of a sentence.
RESOLVE_LABEL_WORDS = 4

#: Only the two fields the comparison and the hit are built from. A payload selector rather than
#: the whole record: the page ``text`` is the largest thing on a point and no part of this answer.
RESOLVE_PAYLOAD = ("page_no", "content", "provenance")

_log = vsir_logging.get_logger(__name__)


def matches(requested: str, stored: str) -> bool:
    """Whether ``stored`` — a page's own printed label — is the label that was asked for.

    Tokenised on both sides and compared as a **phrase**, in either direction, because a citation
    and a footer are the same fact written at two lengths: a page whose label is stored as ``"8"``
    is what *"Page 8 of 55"* refers to, and a page whose label is stored in full as *"Page 8 of
    30"* is what a caller typing ``"8"`` means. :func:`~vsir.core.exact.contains_phrase` is the
    containment test — contiguous and in order, the same mechanism ``phrase_matching`` gives the
    index (§5.5) — so ``"8"`` never matches ``"18"`` and no edit distance exists anywhere near
    this (§7.6).

    The looseness is symmetric and it is why F5 is a *list*: ``"30"`` against a corpus that stores
    *"Page 8 of 30"* matches every page of the document, and the honest answer to that is every
    candidate plus ``capped``, not a confident first row.
    """
    want, have = tok(requested), tok(stored)
    if not want or not have:
        return False
    return want == have or contains_phrase(want, stored) or contains_phrase(have, requested)


def labels_of(content: Mapping[str, Any]) -> list[str]:
    """Every label this page answers to: its settled one, or the readings it could not arbitrate.

    §6.5 populates ``label_candidates`` **only** where the page's printed label is ambiguous — two
    readings the page itself cannot decide between — and leaves ``printed_page_no`` empty when it
    does, because filling it would be the silent pick F5 is about. Reading only ``printed_page_no``
    here would therefore make exactly those pages unresolvable **by any label**, which is the
    follow-up U009 recorded against this unit: the page a citation is most likely to be wrong about
    would be the one page no citation could open.

    So an ambiguous page answers to *both* readings, and the caller is handed it for either — as
    one candidate among however many others share the label, which is what F5 asks for.
    """
    printed = str(content.get("printed_page_no") or "").strip()
    if printed:
        return [printed]
    return [str(candidate) for candidate in (content.get("label_candidates") or []) if candidate]


def answers_to(content: Mapping[str, Any], requested: str) -> bool:
    """Whether this page's own label — settled or ambiguous — is the one that was asked for."""
    return any(matches(requested, label) for label in labels_of(content))


def hit_from_payload(payload: Mapping[str, Any], *, interpolated: bool | None = None) -> ResolveHit:
    """One page's payload → a :class:`~vsir.serve.envelope.ResolveHit`.

    ``printed_page_no`` is echoed **as stored**, which for an ambiguous page is empty: the page has
    no settled label, and writing the candidate that happened to match would claim the page prints a
    reading it could not arbitrate. ``label_verified: false`` beside it is the disclosure.

    ``label_verified`` and ``interpolated`` are read off the record, where derivation recorded them
    (§6.5), and are never re-derived here — the page's own text is the witness the ingest run
    weighed, and a second opinion formed at query time would be a second answer to §6.4's question.
    ``interpolated`` is overridden only by the bracket path below, which is the one case where
    *this* call did the inferring and has to say so.
    """
    content = payload.get("content") or {}
    provenance = payload.get("provenance") or {}
    page_id = str(provenance.get("page_id") or "")
    return ResolveHit(
        page_id=page_id,
        printed_page_no=str(content.get("printed_page_no") or ""),
        label_verified=bool(content.get("label_verified", False)),
        interpolated=bool(content.get("interpolated", False))
        if interpolated is None else interpolated,
        image=image_ref(page_id) if page_id else None,
    )


def _candidates(client: Any, collection: str, query: qm.Filter, limit: int,
                offset: int = 0) -> list[Any]:
    """One page of the pages the phrase filter matched, in reading order.

    ``OrderByQuery`` over the indexed ``page_no`` rather than an unordered fetch: the order decides
    *which* candidates come back first, so ordering on the index makes a truncated resolve the
    **first** pages of the document instead of an arbitrary sample of them — and makes the same
    label resolve the same way twice (§16).
    """
    response = client.query_points(collection, query=qm.OrderByQuery(order_by="page_no"),
                                   query_filter=query, limit=limit, offset=offset,
                                   with_payload=list(RESOLVE_PAYLOAD), with_vectors=False)
    return list(response.points)


def _documents(client: Any, collection: str, query: qm.Filter) -> list[str]:
    """Which documents print this label — an **indexed facet**, not a count of payloads (E9).

    Also the ambiguity signal an unscoped `resolve` needs most: one binder printing *"8"* is a
    page, three binders printing it is a question the caller has to answer with a ``doc_id``.
    """
    return sorted(str(hit.value) for hit in
                  client.facet(collection, key="doc_id", facet_filter=query,
                               limit=RESOLVE_FACET_DOCS, exact=True).hits)


def label_words(printed_label: str) -> list[str]:
    """The parts of a citation that could themselves be a printed label (§6.8's heuristic).

    *"Page 8 of 55"* is a **citation**; what a footer prints is ``8``. The phrase index can only
    find what a page actually carries, so when the citation as typed matches nothing, the words of
    it that contain a digit are asked for one at a time — ``8``, then ``55`` — and each candidate
    is still confirmed against the **whole** citation by :func:`matches`.

    That the second probe can also find a page is not a defect: a corpus of 55-page manuals really
    does have a page numbered 55, and *"Page 8 of 55"* really is ambiguous evidence for it. F5's
    answer to ambiguity is every candidate, not a cleverer guess.
    """
    return [word for word in (printed_label or "").split()
            if any(is_code_like(token) for token in tok(word))][:RESOLVE_LABEL_WORDS]


@dataclass(frozen=True)
class Probe:
    """One question put to the index, and what came back: the confirmations, and the reach.

    ``total`` is the size of the matched set as the **index** counted it, ``scanned`` is how much of
    that set was actually compared. They are reported separately because their difference is the
    whole of register E9: a resolver that looked at part of a set and said *"not found"* about the
    rest is the defect, and one that says ``capped`` is not.
    """

    payloads: tuple[Mapping[str, Any], ...] = ()
    total: int = 0
    scanned: int = 0

    @property
    def complete(self) -> bool:
        return self.scanned >= self.total


def _probe(client: Any, collection: str, phrase: str, scope: Mapping[str, Any], *,
           requested: str = "") -> Probe:
    """Ask the index for ``phrase`` and keep every page whose stored label is ``requested``.

    Two arguments rather than one because they are two different jobs: ``phrase`` is what the index
    is asked for — a page has to *print* it — and ``requested`` is what the caller asked to resolve,
    which is what a candidate's stored label has to match. For a bare label the two are the same
    string; for a citation they are not.

    **It pages through the matched set rather than looking at a window of it.** That is the fix for
    E9 rather than a larger version of the defect: a bare ``"40"`` is printed as a *number* on many
    pages and as a *label* on one, so a single window of 64 sorted candidates can easily contain
    none of the confirmations and would report `not_found` about a page it never compared. The
    budget of :data:`RESOLVE_SCAN_PAGES` pages is the honest bound on how wide one free call may
    be, and when it binds the response says ``capped`` and the caller can narrow with ``doc_id``.
    """
    query = exact_filter(phrase, scope, field="text")
    total = count_exact(client, collection, query)
    found: list[Mapping[str, Any]] = []
    scanned = 0
    for page in range(RESOLVE_SCAN_PAGES):
        batch = _candidates(client, collection, query, RESOLVE_CANDIDATES,
                            offset=page * RESOLVE_CANDIDATES)
        if not batch:
            break
        scanned += len(batch)
        found += [point.payload or {} for point in batch
                  if answers_to((point.payload or {}).get("content") or {},
                                requested or phrase)]
        if scanned >= total:
            break
    return Probe(payloads=tuple(found), total=total, scanned=scanned)


def _bracketed(client: Any, collection: str, label: str,
               scope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """§6.5's bracket, applied to a label no page prints: *n−1* and *n+1*, two pages apart.

    Returns the payload of the page between them, or nothing. Deliberately narrow:

    * the label must be a plain integer — a bracket between ``"iv"`` and ``"3-2"`` is not arithmetic
      anybody should be doing on a caller's behalf;
    * **both** neighbours must be found, in the **same** document and revision, and their physical
      pages exactly two apart. One neighbour and a delta is extrapolation, which is what `impl` did
      and what §6.5 refuses: no ``printed + offset = pdf`` formula exists in this corpus;
    * the page between them must not already print a label of its own — if it does, this label
      belongs to a different page and the bracket is a coincidence.
    """
    if not label.strip().isdigit():
        return []
    number = int(label.strip())
    if number < 1:
        return []
    before = _probe(client, collection, str(number - 1), scope).payloads
    after = _probe(client, collection, str(number + 1), scope).payloads
    found: list[Mapping[str, Any]] = []
    for low in before:
        for high in after:
            low_id = str((low.get("provenance") or {}).get("page_id") or "")
            high_id = str((high.get("provenance") or {}).get("page_id") or "")
            if not (low_id and high_id):
                continue
            doc_id, revision, low_page = ids.parse_page_id(low_id)
            high_doc, high_revision, high_page = ids.parse_page_id(high_id)
            if (doc_id, revision) != (high_doc, high_revision) or high_page - low_page != 2:
                continue
            between = ids.page_id(doc_id, revision, low_page + 1)
            for point in client.retrieve(collection, ids=[ids.point_id(between)],
                                         with_payload=list(RESOLVE_PAYLOAD), with_vectors=False):
                payload = point.payload or {}
                content = payload.get("content") or {}
                if not labels_of(content) or answers_to(content, label):
                    found.append(payload)
    return found


def resolve(client: Any, collection: str, printed_label: str, *,
            doc_id: str | None = None,
            provenance: Provenance,
            reads_remaining: int = 0) -> SearchResponse[ResolveHit]:
    """A printed label → every page that carries it, with ``label_verified`` and ``interpolated``.

    ``doc_id`` is optional and narrows; without it the whole current corpus is in scope, which is
    what makes a cross-reference in one binder able to point at another. ``is_current=True`` is
    injected server-side either way (I7) and the scope is echoed back (F8, C11).

    Refusals are typed: an empty label, and a ``doc_id`` that is not a filterable key — the second
    is impossible today and is checked anyway, because the `INDEXED` gate is the one thing between
    a scope and an unindexed scan (I6, F10).
    """
    if not tok(printed_label or ""):
        raise ToolError(
            "label_empty",
            "resolve takes the label as it is printed on the page, e.g. \"8\" or \"Page 8 of 55\" "
            "(§7.2.3) — an empty label has no page to be about",
            requested=printed_label,
        )

    scope_in_force = effective_scope({"doc_id": doc_id} if doc_id else None)
    try:
        phrase_query = exact_filter(printed_label, scope_in_force, field="text")
        scoped = scope_filter(scope_in_force)
    except UnknownScopeKey as refusal:
        raise as_tool_error(refusal) from None

    stats, searchable_pages = scope_stats(client, collection, scoped)
    documents = _documents(client, collection, phrase_query)

    asked = _probe(client, collection, printed_label, scope_in_force)
    probes = [asked]
    probed: list[str] = []
    if not asked.payloads:
        # The citation as typed matched nothing. Ask for the parts of it that a footer could
        # actually print, and confirm every candidate against the whole citation (`label_words`).
        for word in label_words(printed_label):
            if word == printed_label:
                continue                       # already asked, and answered
            probed.append(word)
            probes.append(_probe(client, collection, word, scope_in_force,
                                 requested=printed_label))

    seen: set[str] = set()
    hits: list[ResolveHit] = []
    for payload in (payload for probe in probes for payload in probe.payloads):
        page_id = str((payload.get("provenance") or {}).get("page_id") or "")
        if page_id and page_id not in seen:
            seen.add(page_id)
            hits.append(hit_from_payload(payload))

    # The size of the set the answer came out of, and whether all of it was compared. Not a sum
    # over the probes: they overlap, and a number that double-counts a page is worse than the
    # largest honest one.
    total = max(probe.total for probe in probes)
    complete = all(probe.complete for probe in probes)

    bracketed = False
    if not hits:
        bracket = _bracketed(client, collection, printed_label, scope_in_force)
        hits = [hit_from_payload(payload, interpolated=True) for payload in bracket]
        bracketed = bool(hits)

    # Deterministic, and in reading order across documents: the same label resolves to the same
    # list in the same order on every instance and in every process (§16).
    hits.sort(key=lambda hit: (hit.page_id.split("#")[0], hit.page_id))

    is_weak = weakness(total, stats.pages)
    status = Status.OK if hits else absence(stats.pages, searchable_pages)
    next_moves: NextMoves | None = None
    if status == Status.NOT_FOUND:
        # A label nothing prints is exactly the case a skim can still answer — the page may carry
        # the *content* the citation was about even where the numbering is not in the text layer
        # (a scanned chapter, a label the model never read). The status stays honest; the
        # affordance stops the agent abstaining on a numbering accident (§7.1).
        next_moves = NextMoves(suggest=["skim_pages", "lookup"])

    response = SearchResponse[ResolveHit](
        status=status,
        hits=hits,
        total=total,
        capped=not complete,
        weak=is_weak,
        needs_scope=is_weak,
        next=next_moves,
        effective_scope=scope_in_force,
        scope_stats=stats,
        reads_remaining=reads_remaining,
        provenance=provenance,
    )
    _log.debug(
        "resolve",
        tool="resolve",
        printed_label=printed_label,
        doc_id=doc_id or "",
        documents=documents,
        probed=probed,
        scanned=sum(probe.scanned for probe in probes),
        status=response.status.value,
        total=total,
        hits=len(hits),
        ambiguous=len(hits) > 1,
        bracketed=bracketed,
        pages=stats.pages,
    )
    return response


def candidates_of(response: SearchResponse[ResolveHit]) -> Sequence[str]:
    """The page ids a resolve returned — for the demo, and for an agent that wants the list flat.

    Exposed because *"how many candidates"* is the question F5 is about, and a caller reading it
    off ``len(hits)`` would have to know that ``unverified_hits`` is never populated here.
    """
    return [hit.page_id for hit in response.hits]
