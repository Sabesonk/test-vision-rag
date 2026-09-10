"""How a `page_id` becomes pixels, and how those pixels are addressed (Spec §7.2.5, §7.4, D6).

Net new. `impl` had the route — ``GET /api/v1/page-image/{page_id}`` — and it read a PNG off the
filesystem that step 03 had written unconditionally for every page at both dpis (register **E3**).
The path on the record went stale, so ``read()`` returned 503 for every page (**A5**), and an
instance's answers depended on files another replica did not have. §4.2 removes the disk: **rasters
are never persisted**, they are re-rendered on demand, and a cold instance returns an identical
image and only more slowly (§15 Factor VI).

**This module is the serving policy over that renderer, and it deliberately holds no cache of its
own.** The LRU is :func:`vsir.ingest.render._cached`, keyed by the source file's **content hash**.
A second cache here, keyed by ``page_id``, would look like an obvious optimisation and would be a
correctness bug: a ``(doc_id, revision)`` re-ingested from corrected bytes keeps the same page ids,
so such a cache would serve the superseded pixels for as long as the process lived — and it would
hold a second copy of every PNG while doing it, against the one resource limit §15.1 names. What
lives here instead is the four things a *request* needs and the renderer must not know about:

* **the URL grammar, and its encoding.** A ``page_id`` is ``{doc_id}@{revision}#p{NNN}`` (§5.1) and
  a ``#`` is a fragment delimiter to every HTTP client there is: ``/pages/TC1E-SF@1.3#p001/image``
  is a request for ``/pages/TC1E-SF@1.3`` with a fragment the server never sees. §7.2.5's own
  example shows the encoded form, so :func:`page_image_url` is the one place that produces it and
  :func:`page_id_of_path` is the one place that reads it back. Every `ImageRef` in every envelope
  is built here (U017's `image_ref` calls it), which is what makes the reference *dereferenceable*
  rather than merely present.
* **resolution.** ``page_id`` → the indexed page → the run that indexed it → the bytes in the
  document store (U029). Three refusals, kept distinct because a caller retries them differently:
  a page this corpus does not hold is a `404`, a page that is not the current revision is its own
  `404`, and a document whose *source* is missing is a `503` — the page exists and its image
  cannot be made, which is somebody's operational problem and not the caller's mistake (§11.3).
* **the integrity check.** The run record's ``content_hash`` is passed to
  :meth:`~vsir.ingest.store.DocumentStore.locate` as ``expect_hash``, so the one case that
  otherwise fails silently — a re-ingest from corrected bytes, whose pages are not published yet —
  refuses instead of rendering a page nobody indexed (§6.7).
* **the megapixel bound, before the render.** Rendering is the memory spike, so §7.3's 12 MP
  ceiling is checked from :func:`~vsir.ingest.render.predicted_megapixels` rather than by measuring
  the pixmap: a bound enforced after the allocation has already paid for what it refuses.

Every refusal leaves this module as a :class:`~vsir.serve.caps.ToolError`, so `POST /tools/fetch`
and `GET /pages/{page_id}/image` describe the same failure with the same code and the same status.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote, unquote

from vsir import logging as vsir_logging
from vsir.config import DPI_INDEX, Config
from vsir.core import ids
from vsir.core.verify import PageNotFound, page_payloads
from vsir.ingest import render as render_module
from vsir.ingest import run as run_module
from vsir.ingest import store as store_module
from vsir.serve.caps import ToolError, validate_dpi, validate_region

#: §7.4's path. One template, so the route and every `ImageRef` cannot disagree about it.
PAGE_IMAGE_PATH = "/pages/{page_id}/image"

#: What :func:`quote` leaves alone in a ``page_id``. ``@`` is left literal because §7.2.5's example
#: is ``/pages/TC1E-SF@1.3%23p001/image?dpi=150`` — the ``#`` is the character that breaks a
#: client, and encoding the ``@`` as well would make a citation unreadable to a person for no gain.
URL_SAFE = "@"

#: The only media type this service produces for a raster. PyMuPDF writes PNG, and one format
#: keeps the byte-identity criterion meaningful.
PNG_MEDIA_TYPE = "image/png"

_log = vsir_logging.get_logger(__name__)


# ── the URL grammar (§7.2.5, §7.4) ───────────────────────────────────────────────────────────────

def quoted_page_id(page_id: str) -> str:
    """``"TC1E-SF@1.3#p001"`` → ``"TC1E-SF@1.3%23p001"`` — the form a client can dereference."""
    return quote(page_id, safe=URL_SAFE)


def page_id_of_path(raw: str) -> str:
    """The path parameter → the ``page_id`` it spells.

    The ASGI server has already decoded the path, so ``%23`` normally arrives as ``#`` and this is
    the identity. The unquote is for the caller that encoded it twice, and it is safe to apply
    only because a canonical ``page_id`` can never contain a ``%``: ``doc_id`` is a slug and
    ``revision`` is validated against `store.SAFE_COMPONENT`. Guessing is *not* the fallback — an
    id that still does not parse is a typed `400` in :func:`resolve_pages`.
    """
    return unquote(raw) if "%" in raw else raw


def region_query(region: Sequence[float] | None) -> str:
    """A region as the query parameter spells it: ``"0,0,1,0.55"``, or empty for a full page."""
    if region is None:
        return ""
    return ",".join(f"{float(value):g}" for value in region)


def region_of_query(raw: str) -> list[float] | None:
    """``"0,0,1,0.55"`` → ``[0.0, 0.0, 1.0, 0.55]``. Malformed is a typed 400, never a guess.

    The bounds themselves are `caps.validate_region`'s (normalised, ``x0 < x1``, ``y0 < y1``); this
    only turns the four numbers of a query string into four floats, and refuses anything that is
    not four numbers under the same code — a caller that sent ``region=top-half`` asked for
    something this service cannot interpret, and cropping the page it *would* have guessed at is
    how a crop of the wrong half is returned as a success (§11.3).
    """
    text = (raw or "").strip()
    if not text:
        return None
    parts = [part.strip() for part in text.split(",")]
    try:
        values = [float(part) for part in parts]
    except ValueError:
        raise ToolError(
            "region_invalid",
            f"region is four numbers x0,y0,x1,y1 normalised to 0..1, got {raw!r}",
            requested=raw,
        ) from None
    if len(values) != 4:
        raise ToolError("region_invalid",
                        f"region is [x0, y0, x1, y1], got {len(values)} value(s): {raw!r}",
                        requested=raw)
    return values


def page_image_url(page_id: str, *, dpi: int = DPI_INDEX,
                   region: Sequence[float] | None = None) -> str:
    """The bearer-authenticated `GET` that returns this page's raster (§7.4).

    Relative on purpose: the service does not know what host a caller reached it on, and a URL
    built from a request header is a URL an operator can be made to publish (§15.1). A browser
    resolves it against the origin it loaded the response from, which is the only origin that can
    serve it.
    """
    path = PAGE_IMAGE_PATH.format(page_id=quoted_page_id(page_id))
    query = f"dpi={int(dpi)}"
    if region is not None:
        query = f"{query}&region={region_query(region)}"
    return f"{path}?{query}"


# ── resolution: page_id → the indexed page → the run → the bytes (U029) ──────────────────────────

@dataclass(frozen=True)
class ResolvedPage:
    """One addressable page: what the index holds, and the file its raster is made from.

    Frozen, and built per request. Nothing here is kept: the payload is one round trip's answer and
    the source is a path on a mounted volume, so two replicas resolve the same page to the same
    bytes without sharing anything (§15 Factor VI).
    """

    page_id: str
    payload: Mapping[str, Any]
    source: store_module.PageSource
    #: The ``content_hash`` of the run that indexed this page, or empty when that run predates
    #: §6.9 recording one. Empty means *"no expectation"* and not *"any bytes will do"*: the
    #: refusal it would have produced is the one case §6.7 leaves open, and a run with no hash
    #: cannot have that case.
    expected_hash: str = ""

    @property
    def path(self) -> Path:
        return self.source.path

    @property
    def page_no(self) -> int:
        return self.source.page_no

    @property
    def content_hash(self) -> str:
        return self.source.document.content_hash

    @property
    def document(self) -> str:
        return self.source.document.name


def as_tool_error(refusal: store_module.StoreRefused) -> ToolError:
    """A document-store refusal, in the surface's vocabulary. One check, one translation.

    The code and the status are the store's own — `document_not_stored` is a `503` because the page
    is indexed and its image cannot be made, `document_id_unsafe` is a `400` because it is about
    the input — so this adds a transport and not a policy (the shape `caps.as_tool_error` uses for
    the `INDEXED` gate).
    """
    return ToolError(refusal.code, refusal.message, http_status=refusal.http_status,
                     **refusal.details)


def render_error_as_tool_error(failure: render_module.RenderError) -> ToolError:
    """A renderer refusal, in the surface's vocabulary.

    ``region_invalid`` is the caller's (a `400`); anything else — ``page_out_of_range`` above all —
    is the index and the stored document disagreeing about how many pages there are, which is a
    `503` naming the document. Never a blank image and never the nearest page (§11.3).
    """
    if failure.code == "region_invalid":
        return ToolError(failure.code, failure.message, **failure.details)
    return ToolError(failure.code, failure.message, http_status=503, **failure.details)


def _parsed(page_ids: Sequence[str]) -> None:
    """Every id is §5.1's canonical spelling, or a typed 400 naming the ones that are not.

    The same check `verify` makes, for the same reason: a malformed citation and a page that is not
    in the corpus are different facts, and only one of them means *"look somewhere else"*.
    """
    malformed = [page_id for page_id in page_ids if not _parses(page_id)]
    if malformed:
        raise ToolError(
            "page_id_invalid",
            f"not page ids of the form doc@revision#pNNN (§5.1): {malformed}",
            page_ids=malformed,
        )


def _parses(page_id: str) -> bool:
    try:
        ids.parse_page_id(page_id)
    except ValueError:
        return False
    return True


def _expected_hashes(client: Any, runs_collection: str,
                     payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """``run_id`` → the ``content_hash`` that run recorded (§6.9). One read per distinct run.

    A `fetch` of five pages of one document asks the control plane once, not five times. A run that
    cannot be found is not a refusal: the pages are indexed and current, the store still holds the
    document, and the only thing missing is the integrity *expectation* — so the image is served
    and the missing hash is logged, rather than a page becoming unviewable because its run record
    was pruned.
    """
    run_ids = {str(payload.get("run_id") or "") for payload in payloads.values()}
    hashes: dict[str, str] = {}
    for run_id in sorted(run_ids - {""}):
        record = run_module.load(client, runs_collection, run_id)
        if record is None:
            _log.debug("run_record_absent", run_id=run_id,
                       detail="no content_hash to check the stored document against")
            continue
        hashes[run_id] = record.content_hash
    return hashes


def resolve_payloads(client: Any, cfg: Config,
                     page_ids: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    """Every named page → what the index holds for it, in the order asked for. **No store.**

    The half of resolution that a caller who wants no pixels needs, and it is separate from
    :func:`attach_sources` for one reason: §7.2.5 says dropping ``"image"`` from ``include`` makes
    `fetch` *a cheap text/summary read*, and a cheap read that refuses `document_not_stored`
    because the source PDF is not mounted is not cheap — it is unavailable. The `text` and the
    `summary` are payload fields written at index time (§5.3); nothing about them needs the bytes
    the page was rendered from, so nothing about them may depend on those bytes still being here.

    Three distinct refusals, none of them an empty result:

    * `page_id_invalid` (400) — this service cannot interpret the citation;
    * `page_not_found` (404) — the corpus does not hold that page;
    * `page_not_current` (404) — it holds it, and it is not the revision this release answers from.
      Separate from `page_not_found` deliberately: told *"no such page"*, a caller concludes its
      citation was wrong, when what actually happened is that the document moved on (F9, §6.7).
      The detail says so, and `resolve` is the move that finds the current page id.
    """
    wanted = list(dict.fromkeys(page_ids))
    _parsed(wanted)
    try:
        payloads = page_payloads(client, cfg.pages_collection, wanted)
    except PageNotFound as missing:
        raise ToolError(
            "page_not_found",
            f"not in {cfg.pages_collection}: {missing.page_ids}. A page that is not indexed has "
            f"no raster to render, and an empty image would be indistinguishable from a blank "
            f"page (§7.1, §11.3)",
            http_status=404, page_ids=missing.page_ids,
        ) from None

    superseded = [page_id for page_id, payload in payloads.items()
                  if not payload.get("is_current", False)]
    if superseded:
        raise ToolError(
            "page_not_current",
            f"indexed but not current: {superseded}. Either the run that wrote these pages has "
            f"not passed its publish gates, or a later revision superseded them (I7, §6.7). This "
            f"is not `page_not_found` — the citation is fine and the document moved on; `resolve` "
            f"the printed label to find the page that answers now",
            http_status=404, page_ids=superseded,
        )
    return {page_id: payloads[page_id] for page_id in wanted}


def attach_sources(client: Any, cfg: Config,
                   payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, ResolvedPage]:
    """Indexed pages → the bytes their rasters are made from. The half that needs U029.

    The chain is the whole reason U029 had to land first: ``page_id`` → the point (an exact address,
    ``uuid5(page_id)``) → the run that wrote it → ``doc_id@revision`` in the document store. No
    payload names a file (§5.3, register **A5**) and none needs to.

    A document the store does not hold is a `503` and not a `404`: the page is indexed, current and
    real, and the only thing missing is a mounted volume — somebody's operational problem and not
    the caller's mistake (§11.3).
    """
    store = store_module.DocumentStore.from_config(cfg)
    hashes = _expected_hashes(client, cfg.runs_collection, payloads)
    resolved: dict[str, ResolvedPage] = {}
    for page_id, payload in payloads.items():
        expected = hashes.get(str(payload.get("run_id") or ""), "")
        try:
            source = store.for_page(page_id, expect_hash=expected)
        except store_module.StoreRefused as refusal:
            raise as_tool_error(refusal) from None
        resolved[page_id] = ResolvedPage(page_id=page_id, payload=payload, source=source,
                                         expected_hash=expected)
    return resolved


def resolve_pages(client: Any, cfg: Config, page_ids: Sequence[str]) -> dict[str, ResolvedPage]:
    """Every named page → the bytes its raster is made from, in the order asked for.

    Both halves, for the callers that want pixels: the image route always does, and `fetch` does
    when ``"image"`` is in its ``include``.
    """
    return attach_sources(client, cfg, resolve_payloads(client, cfg, page_ids))


def resolve_page(client: Any, cfg: Config, page_id: str) -> ResolvedPage:
    """One page. The single-page door onto :func:`resolve_pages`, for the image route."""
    return resolve_pages(client, cfg, [page_id])[page_id]


# ── the render, and the bound in front of it (§7.3) ──────────────────────────────────────────────

def validate_raster_request(dpi: int, region: Sequence[float] | None) -> None:
    """The two §7.3 bounds that apply to a single raster, in the order a caller violates them.

    ``dpi`` first, because a dpi that is not on the list is wrong whatever the region is; then the
    region's own shape; then the rule that ties them together — above the pinned answer dpi a full
    page is refused and a `region` is required, because detail that fine is about *part* of a page
    and a full page at 400 dpi is 15 megapixels of raster (§7.3, §15.1).
    """
    validate_dpi(dpi, region)
    validate_region(region)


def megapixels(resolved: ResolvedPage, *, dpi: int,
               region: Sequence[float] | None = None) -> float:
    """How large this raster will be, **before** it is made (§7.3's `fetch` budget)."""
    try:
        return render_module.predicted_megapixels(
            resolved.path, resolved.page_no, dpi=dpi, region=region,
            content_hash=resolved.content_hash)
    except render_module.RenderError as failure:
        raise render_error_as_tool_error(failure) from None


def raster(resolved: ResolvedPage, *, dpi: int,
           region: Sequence[float] | None = None) -> render_module.Raster:
    """The page's raster — from the in-process cache when it is there, rendered when it is not.

    ``content_hash`` is passed through rather than recomputed, so the cache key is the bytes the
    store actually holds: the same page at the same dpi from a *replaced* file is a different key
    and cannot be answered from the cache (§6.7).
    """
    try:
        return render_module.render_page(resolved.path, resolved.page_no, dpi=dpi, region=region,
                                         content_hash=resolved.content_hash)
    except render_module.RenderError as failure:
        raise render_error_as_tool_error(failure) from None


def renders(before: Mapping[str, int], after: Mapping[str, int]) -> int:
    """How many rasters were actually **made** between two :func:`cache_info` snapshots.

    What the audit line's ``cache_hit`` is computed from (§7.4). Misses rather than hits, because a
    request that rendered nothing new is the claim worth recording — it is the one that cost no
    memory and no time.
    """
    return max(0, int(after.get("misses", 0)) - int(before.get("misses", 0)))


def cache_info() -> dict[str, int]:
    """What the raster cache holds. The renderer's, re-exported: there is only one (§4.2)."""
    return render_module.cache_info()


def cache_clear() -> None:
    """Evict every raster. Always safe — a cache, so this loses no information (§15 Factor VI)."""
    render_module.cache_clear()


def total_megapixels(resolved: Iterable[ResolvedPage], *, dpi: int,
                     region: Sequence[float] | None = None) -> float:
    """The megapixels one multi-page request would allocate, summed over its pages (§7.3)."""
    return sum(megapixels(page, dpi=dpi, region=region) for page in resolved)
