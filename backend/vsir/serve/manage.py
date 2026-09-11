"""The corpus management surface — what is in the index, and what it is made of (§5.1–5.3, §6.9).

**The gap this fills.** Until now the only way to learn what this service holds was to search it.
`POST /documents` put a document in and `GET /runs/{run_id}` reported on one run *whose id you
already had*; nothing answered *"what documents are published"*, *"which revisions of this one
exist"*, *"which of its pages have no text layer"*, or *"what ran last week"*. So an operator
could ingest a corpus and then had no way to see the corpus, and a console could not render a
document browser at all — the pages it would list are in the index, and no endpoint returned them.

**Why these are queries and never a second pipeline.** Every number here is read from the two
collections the ingest pipeline writes (register **E1**, §15 Factor XII): page rows come from the
page index, revision and run facts from the `vsir_runs` control plane. This module computes
nothing that ingestion did not already record and stores nothing of its own — so it cannot drift
from what a search sees, and a replica answers identically because there is no per-instance state
(§15 Factor VI, C11).

**Why the counts are exact.** ``facet(exact=True)`` and ``count(exact=True)`` throughout, at the
cost of some latency on a large collection. A management surface is where somebody decides whether
a document ingested correctly, and an *estimated* page count that is short by two is indistinguishable
from an ingest that dropped two pages. §5.7's own argument, applied to the surface that reports it:
a ratio built on an estimate is a lie.

**Why nothing here mutates.** `POST /documents` creates and §6.7's retirement runs *inside* a
publish, where it is one clause of a transition with the run record as its evidence. A bare
"retire this revision" endpoint would be the one operation on this surface that changes what every
future search returns, and it is deliberately not here — see the note on :func:`routes`.

**Why the units are documents, revisions, pages and runs — and not chunks.** There is no chunk in
this system to manage, by design: a *window* is a page range that stitching deletes again and it
never becomes a retrieval boundary (`ingest/window.py`), and the three granularities that survive
— window (attention), section (semantics), page (index) — are kept separate throughout. The
addressable unit is the **page**, under the `page_id` of §5.2, which is what `fetch` and `read`
take and what this surface therefore lists.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import models as qm

from vsir import logging as vsir_logging
from vsir.core import health
from vsir.ingest import run as run_module
from vsir.serve.caps import ToolError
from vsir.serve.raster_cache import page_image_url
from vsir.serve.tools.lookup import no_text

_log = vsir_logging.get_logger(__name__)

#: Rows one listing call may return. A bound with its own code, like every other bound in this
#: service (§7.3): a corpus is unbounded and a caller that wants the next page asks for it.
MAX_PAGE_SIZE = 200
#: The default, small enough to be a screenful and a cheap first call.
DEFAULT_PAGE_SIZE = 50
#: Documents one `GET /documents` may describe. Each row costs two facets and a scroll, so this is
#: the bound that keeps a listing from becoming a table scan of the whole corpus.
MAX_DOCUMENTS = 100


class RevisionRow(BaseModel):
    """One revision of one document, as the index holds it (§5.1, §6.7)."""

    model_config = ConfigDict(extra="forbid")

    revision: str = Field(description="The revision string. `\"\"` is a document ingested without "
                                      "a declared revision.")
    pages: int = Field(description="Pages indexed for this revision, exact.")
    current_pages: int = Field(
        description="Of those, how many are `is_current=True`. Zero means this revision is "
                    "**retired or never published** — step 10 writes every point "
                    "`is_current=False` and step 11's gates are the only thing that flips it "
                    "(I7, §6.7), so a revision with pages and no current pages is one that was "
                    "indexed and did not pass, or one a later revision superseded.")
    is_current: bool = Field(
        description="Whether this is the revision a search reaches. Exactly one revision of a "
                    "document is current at a time (§6.7, F9); the others are **kept**, not "
                    "deleted, which is why they are listed here.")
    run_id: str = Field(default="", description="The run that indexed it — `GET /runs/{run_id}` "
                                                "for its steps, gates and cost (§6.9).")


class DocumentRow(BaseModel):
    """One document across its revisions — a row of the corpus (§5.1, §5.3, §5.7)."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(description="The revision-stable document id (§5.1).")
    doc_type: str = Field(default="", description="The declared document type (§5.3).")
    subjects: list[str] = Field(default_factory=list,
                                description="The machine/model subjects this document covers "
                                            "(§5.3) — a `scope` key.")
    tags: list[str] = Field(default_factory=list,
                            description="The uploader's tags (§5.3) — a `scope` key.")
    pages: int = Field(description="Pages indexed across **every** revision, exact.")
    current_pages: int = Field(description="Pages a search can currently reach.")
    current_revision: str = Field(default="",
                                  description="The published revision, or `\"\"` if none of this "
                                              "document's revisions passed its gates.")
    revisions: list[RevisionRow] = Field(default_factory=list,
                                         description="Every revision held, newest-sorting last.")
    searchable_ratio: float = Field(
        description="The §5.7 fraction of the **current** revision's pages that have a text "
                    "layer. This is the number that decides whether `lookup` can answer at all "
                    "for this document: at 0.0 every code on every page is `unverifiable` rather "
                    "than absent, and a caller told 'not found' would be told it wrongly (§7.1).")


class DocumentList(BaseModel):
    """A page of the corpus."""

    model_config = ConfigDict(extra="forbid")

    documents: list[DocumentRow]
    total: int = Field(description="Documents in the index, exact — not the length of this list.")
    returned: int = Field(description="Rows in this response.")
    truncated: bool = Field(description="Whether `total` exceeded the requested `limit`. There is "
                                        "no cursor here on purpose: a corpus is browsed by "
                                        "filtering it, and `GET /documents/{doc_id}` is the way "
                                        "to reach one document regardless of how many there are.")


class PageRow(BaseModel):
    """One page of one revision — the addressable unit of this system (§5.2)."""

    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(description="`<doc_id>@<revision>#p<page_no>` (§5.2) — pass this "
                                     "straight to `fetch`, `read` or `verify`.")
    page_no: int = Field(description="Our 1-based index into the rendered document. **Not** the "
                                     "number printed on the page; `resolve` is the tool that "
                                     "maps a printed reference to a page (§7.2.3).")
    revision: str
    is_current: bool = Field(description="Whether a search reaches this page.")
    has_text: bool = Field(description="Whether the page has a text layer at all. `false` means "
                                       "every claim about it is `unverifiable` and never "
                                       "`absent` (I2, §7.1).")
    text_trust: str = Field(default="", description="How far the text layer is trusted (§5.7).")
    page_kind: str = Field(default="", description="What kind of page this is (§5.3).")
    section_id: list[str] = Field(default_factory=list,
                                  description="The sections this page belongs to (§5.6).")
    image_url: str = Field(description="The raster, rendered on demand — a reference and never "
                                       "bytes (§7.1). Needs the same bearer token.")


class PageList(BaseModel):
    """A page of one document's page inventory."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    revision: str = Field(description="The revision these rows are from — the resolved one, so a "
                                      "caller that asked for the current revision is told which "
                                      "it got.")
    pages: list[PageRow]
    total: int = Field(description="Pages in this revision, exact.")
    returned: int
    next_offset: int | None = Field(
        default=None,
        description="Pass as `offset` for the next page, or `null` at the end. A `page_no` offset "
                    "rather than an opaque cursor, for the reason §6.8's export uses one: the "
                    "order is total and stable, so paging cannot re-shuffle or skip a row.")


def _payloads(client: Any, collection: str, query: qm.Filter, *, limit: int,
              order: str | None = None) -> Iterator[Mapping[str, Any]]:
    """Scroll ``limit`` payloads under ``query``. Vectors never leave the store for a listing."""
    if not client.collection_exists(collection):
        return
    records, _ = client.scroll(
        collection_name=collection, scroll_filter=query, limit=limit,
        with_payload=True, with_vectors=False,
        order_by=order,  # type: ignore[arg-type]
    )
    for record in records:
        yield record.payload or {}


def _count(client: Any, collection: str, query: qm.Filter | None) -> int:
    """Exact, or zero when the collection is not there — see the module note on exactness."""
    if not client.collection_exists(collection):
        return 0
    return client.count(collection, count_filter=query, exact=True).count


def _doc(doc_id: str) -> qm.Condition:
    return qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))


def _revision(revision: str) -> qm.Condition:
    return qm.FieldCondition(key="revision", match=qm.MatchValue(value=revision))


def _current() -> qm.Condition:
    return qm.FieldCondition(key="is_current", match=qm.MatchValue(value=True))


def validate_page_size(limit: int, *, maximum: int = MAX_PAGE_SIZE) -> None:
    """A listing bound, with its own code. See :data:`MAX_PAGE_SIZE`."""
    if limit < 1 or limit > maximum:
        raise ToolError(
            "listing_limit_exceeded",
            f"a listing returns between 1 and {maximum} rows, got {limit}",
            minimum=1, limit=maximum, requested=limit)


def document_ids(client: Any, collection: str, *, limit: int,
                 scope: Sequence[qm.Condition] = ()) -> tuple[dict[str, int], int]:
    """``doc_id → pages`` and the exact number of documents, by facet.

    Two calls rather than one: the facet capped at ``limit`` gives the rows, and a facet capped at
    :data:`MAX_DOCUMENTS` + 1 gives the total, so `truncated` is a fact and not an inference from
    a full page of results.
    """
    if not client.collection_exists(collection):
        return {}, 0
    query = qm.Filter(must=list(scope)) if scope else None
    counted = client.facet(collection, key="doc_id", facet_filter=query,
                           limit=max(limit, 1), exact=True)
    everything = client.facet(collection, key="doc_id", facet_filter=query,
                              limit=MAX_DOCUMENTS + 1, exact=True)
    return ({str(hit.value): hit.count for hit in counted.hits}, len(everything.hits))


def revisions_of(client: Any, collection: str, doc_id: str) -> list[RevisionRow]:
    """Every revision of one document, with the current one marked (§6.7, F9).

    The revisions of a superseded document are **kept** rather than deleted, which is what makes
    this list worth returning: it is the audit trail of what this document has been, and a page
    of an old revision is still fetchable by its `page_id` even though no search reaches it.
    """
    if not client.collection_exists(collection):
        return []
    facets = client.facet(collection, key="revision",
                          facet_filter=qm.Filter(must=[_doc(doc_id)]),
                          limit=MAX_DOCUMENTS, exact=True)
    rows: list[RevisionRow] = []
    for hit in facets.hits:
        revision = str(hit.value)
        scoped = qm.Filter(must=[_doc(doc_id), _revision(revision)])
        current = _count(client, collection, qm.Filter(
            must=[_doc(doc_id), _revision(revision), _current()]))
        run_id = ""
        for payload in _payloads(client, collection, scoped, limit=1):
            run_id = str(payload.get("run_id", "") or "")
        rows.append(RevisionRow(revision=revision, pages=int(hit.count),
                                current_pages=current, is_current=current > 0, run_id=run_id))
    return sorted(rows, key=lambda row: row.revision)


def searchable_ratio(client: Any, collection: str, doc_id: str,
                     revision: str | None = None) -> float:
    """§5.7's ratio for one document — pages with a text layer over pages.

    Computed the way `skim`'s `_ratios` computes it, from two exact counts over the same filter,
    so the number this surface reports and the number a triage row reports are the same number.
    """
    must: list[qm.Condition] = [_doc(doc_id)]
    must.append(_revision(revision) if revision is not None else _current())
    scoped = qm.Filter(must=must)
    pages = _count(client, collection, scoped)
    blank = _count(client, collection, qm.Filter(must=[*must, no_text()]))
    return health.ratio(pages, pages - blank)


def document(client: Any, collection: str, doc_id: str) -> DocumentRow:
    """One document. A `404 document_not_found` when nothing in the index carries the id.

    Named and absent, never an empty row: the same argument §7.1 makes about a search result,
    applied here — a document that was never ingested and a document whose every revision was
    retired are different facts, and a zero-page row would report them identically.
    """
    revisions = revisions_of(client, collection, doc_id)
    if not revisions:
        raise ToolError(
            "document_not_found",
            f"no document {doc_id!r} in this index. This is an absence and not an empty "
            f"document: GET /documents lists the ids there are (§7.1)",
            http_status=404, doc_id=doc_id)

    current = next((row for row in revisions if row.is_current), None)
    facts: Mapping[str, Any] = {}
    wanted = qm.Filter(must=[_doc(doc_id), _revision(current.revision)]) if current \
        else qm.Filter(must=[_doc(doc_id)])
    for payload in _payloads(client, collection, wanted, limit=1):
        facts = payload
    return DocumentRow(
        doc_id=doc_id,
        doc_type=str(facts.get("doc_type", "") or ""),
        subjects=[str(value) for value in (facts.get("subjects") or [])],
        tags=[str(value) for value in (facts.get("tags") or [])],
        pages=sum(row.pages for row in revisions),
        current_pages=sum(row.current_pages for row in revisions),
        current_revision=current.revision if current else "",
        revisions=revisions,
        # `None` means "the current revision" and is the ordinary case. With **no** published
        # revision there is no current one to measure, so the newest revision held is measured
        # instead — passing `""` here would filter on `revision == ""`, match nothing, and report
        # 0.00 for a document that demonstrably has pages.
        searchable_ratio=searchable_ratio(
            client, collection, doc_id,
            None if current else revisions[-1].revision),
    )


def documents(client: Any, collection: str, *, limit: int = DEFAULT_PAGE_SIZE) -> DocumentList:
    """The corpus, one page of it. Bounded by :data:`MAX_DOCUMENTS`."""
    validate_page_size(limit, maximum=MAX_DOCUMENTS)
    counts, total = document_ids(client, collection, limit=limit)

    # A document that vanished between the facet and its own read is **skipped, not raised**.
    # `document()` refuses an unknown id with a `404`, which is right when the caller *named* the
    # document and wrong here: this is two round trips, and between them a publish can retire a
    # revision or a delete can remove one. Propagating that 404 would fail the entire listing —
    # fourteen documents unreturnable because a fifteenth was retired while we counted — which
    # turns somebody else's ordinary write into this caller's outage. §11.3's rule is that a
    # refusal must not be reported as an empty result; the converse holds too, and a row that no
    # longer exists is not a row.
    rows: list[DocumentRow] = []
    for doc_id in sorted(counts):
        try:
            rows.append(document(client, collection, doc_id))
        except ToolError as vanished:
            if vanished.code != "document_not_found":
                raise
            _log.info("document_vanished_mid_listing", doc_id=doc_id, collection=collection)
            total -= 1
    return DocumentList(documents=rows, total=max(total, len(rows)), returned=len(rows),
                        truncated=max(total, len(rows)) > len(rows))


def pages(client: Any, collection: str, doc_id: str, *, revision: str | None = None,
          limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> PageList:
    """One revision's page inventory, in `page_no` order.

    ``revision=None`` resolves to the current one and echoes back which that was — a caller who
    asked for "the document" is told which revision it is looking at, because that is the fact
    that changes under it when somebody publishes a new one.
    """
    validate_page_size(limit)
    described = document(client, collection, doc_id)
    resolved = described.current_revision if revision is None else revision
    if revision is None and not resolved:
        # Every revision is unpublished — so there is no "current" one to default to, and the
        # honest answer is the newest thing held rather than an empty list for a document that
        # demonstrably has pages.
        resolved = described.revisions[-1].revision

    scoped = qm.Filter(must=[_doc(doc_id), _revision(resolved)])
    total = _count(client, collection, scoped)
    if total == 0 and revision is not None:
        raise ToolError(
            "document_not_found",
            f"document {doc_id!r} has no revision {revision!r}. It holds: "
            f"{', '.join(repr(row.revision) for row in described.revisions)}",
            http_status=404, doc_id=doc_id, revision=revision,
            available=[row.revision for row in described.revisions])

    window = qm.Filter(must=[_doc(doc_id), _revision(resolved),
                             qm.FieldCondition(key="page_no", range=qm.Range(gte=offset))])
    rows: list[PageRow] = []
    for payload in _payloads(client, collection, window, limit=limit, order="page_no"):
        # `page_id` lives under `provenance`, single-sourced where §5.3 puts it — the same
        # read `skim` does, so the two surfaces cannot name a page differently.
        page_id = str((payload.get("provenance") or {}).get("page_id") or "")
        rows.append(PageRow(
            page_id=page_id,
            page_no=int(payload.get("page_no", 0) or 0),
            revision=str(payload.get("revision", "") or ""),
            is_current=bool(payload.get("is_current", False)),
            has_text=bool(payload.get("has_text", False)),
            text_trust=str(payload.get("text_trust", "") or ""),
            page_kind=str(payload.get("page_kind", "") or ""),
            section_id=[str(value) for value in (payload.get("section_id") or [])],
            # Built here rather than injected by the route: the HTTP surface and the MCP
            # resource must name a page's raster identically, and a parameter each caller
            # fills in is a parameter one of them can fill in differently.
            image_url=page_image_url(page_id) if page_id else "",
        ))
    rows.sort(key=lambda row: row.page_no)
    last = rows[-1].page_no if rows else offset
    # A full page means "ask again", and nothing else. Deliberately **not** `last + 1 <= total`:
    # `total` is a count and `page_no` is an index, and `ingest/export.py` guards against exactly
    # the document those two disagree on — one whose page numbering has a hole. With a hole,
    # `total` is smaller than the last `page_no`, and that comparison would end the walk early
    # and report a truncated inventory as a complete one. The cost of dropping it is one empty
    # request at the end of a walk, which is the honest trade.
    return PageList(doc_id=doc_id, revision=resolved, pages=rows, total=total,
                    returned=len(rows),
                    next_offset=last + 1 if len(rows) == limit else None)


class RunRow(BaseModel):
    """One ingest run, as the control plane holds it (§6.9).

    A **summary** and not the record: `GET /runs/{run_id}` returns the whole `RunRecord` — gates,
    windows, overrides, lease, cost, retirement. This is the row a history list shows, so it
    carries what somebody scanning for "which run should I open" needs and nothing else. Reusing
    `RunRecord` here would put a run's every gate result in a list of two hundred runs.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="Pass to `GET /runs/{run_id}` for the full §6.9 record.")
    doc_id: str
    revision: str
    state: str = Field(description="One of `queued`, `running`, `stopped`, `gated`, `published`, "
                                   "`failed`. **`gated` is not `failed`** — the run completed and "
                                   "its gates refused to publish it, which is the outcome §11.1 "
                                   "exists to produce and the one worth looking at.")
    step: str = Field(default="", description="The §6.1 step it is on, or stopped at.")
    pages_indexed: int = 0
    page_count: int = 0
    windows_done: int = 0
    windows_total: int = 0
    started_at: str = ""
    updated_at: str = ""
    published_at: str | None = Field(
        default=None,
        description="When step 11 flipped its pages `is_current` (I7). `null` for every run that "
                    "has not published, whether it is still going or was refused.")
    failed_gates: list[str] = Field(
        default_factory=list,
        description="Gates of §11.1 that this run failed. Named rather than counted: which gate "
                    "refused is the whole content of a `gated` run.")
    release_id: str = ""


class RunList(BaseModel):
    """A page of run history, newest first."""

    model_config = ConfigDict(extra="forbid")

    runs: list[RunRow]
    total: int = Field(description="Runs in the control plane matching the filter, exact.")
    returned: int
    truncated: bool


def runs(client: Any, runs_collection: str, *, limit: int = DEFAULT_PAGE_SIZE,
         doc_id: str = "", state: str = "") -> RunList:
    """The run history, newest first. `GET /runs/{run_id}` needed an id you already had.

    Sorted here rather than by Qdrant: `updated_at` is an ISO-8601 string in the payload and not
    an indexed numeric field, so a store-side `order_by` would need a schema change to the control
    plane for what is a display concern. The filter narrows first, so what is sorted is a page of
    runs and not the year of them the collection may hold.
    """
    validate_page_size(limit)
    if not client.collection_exists(runs_collection):
        return RunList(runs=[], total=0, returned=0, truncated=False)

    must: list[qm.Condition] = [qm.FieldCondition(key="kind",
                                                  match=qm.MatchValue(value=run_module.KIND_RUN))]
    if doc_id:
        must.append(_doc(doc_id))
    if state:
        must.append(qm.FieldCondition(key="state", match=qm.MatchValue(value=state)))

    payloads = run_module._scroll(client, runs_collection, qm.Filter(must=must))
    ordered = sorted(payloads, key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    rows = [
        RunRow(
            run_id=str(row.get("run_id", "") or ""),
            doc_id=str(row.get("doc_id", "") or ""),
            revision=str(row.get("revision", "") or ""),
            state=str(row.get("state", "") or ""),
            step=str(row.get("step", "") or ""),
            pages_indexed=int(row.get("pages_indexed", 0) or 0),
            page_count=int(row.get("page_count", 0) or 0),
            windows_done=int(row.get("windows_done", 0) or 0),
            windows_total=int(row.get("windows_total", 0) or 0),
            started_at=str(row.get("started_at", "") or ""),
            updated_at=str(row.get("updated_at", "") or ""),
            published_at=row.get("published_at") or None,
            # `pass`, not `passed`: `GateResult.as_dict()` renames it on the way to the control
            # plane (`ingest/gates.py`), and `from_mapping` reads it back under that name. The
            # same read `run.py`'s metrics snapshot does — a skipped gate is not a failed one.
            failed_gates=sorted(
                name for name, result in (row.get("gate_results") or {}).items()
                if isinstance(result, dict) and not result.get("pass", True)
                and not result.get("skipped", False)),
            release_id=str(row.get("release_id", "") or ""),
        )
        for row in ordered[:limit]
    ]
    return RunList(runs=rows, total=len(ordered), returned=len(rows),
                   truncated=len(ordered) > len(rows))


__all__ = [
    "DEFAULT_PAGE_SIZE", "MAX_DOCUMENTS", "MAX_PAGE_SIZE", "DocumentList", "DocumentRow",
    "PageList", "PageRow", "RevisionRow", "RunList", "RunRow", "document", "document_ids",
    "documents", "pages", "revisions_of", "runs", "searchable_ratio", "validate_page_size",
]
