"""LOOK — ``fetch(page_ids, include, dpi=150, region=None, inline=True)`` (Spec §7.2.5). Net new.

**Material instead of an answer.** That sentence is the design: the caller gets the pixels, the
text and the summary of pages it chose, keeps them, and can ask a follow-up without re-billing.
Nothing here reasons — there is no model call, no judgment about whether the pages answer the
question, and no ranking. `read` is the tool that reasons and it is the tool that spends (§7.2.6);
this one is free, and the only thing it consumes is the caller's own context (§8.1a).

`impl` had no such tool. It had `read()`, which returned 503 for every page because the
``image_path`` on the record was stale (register **A5**), and that is the whole reason the *only*
way to see a page there was to pay for a vision call about it. Splitting looking from comprehending
is what makes an agent able to choose a page and then decide whether it is worth money.

**Family B, and never empty** (§7.1). The pages were named outright, so there is nothing to be
absent: either the call ran and every named page came back, or it is a typed refusal —
`page_not_found` (404), `page_not_current` (404), `document_not_stored` (503), or one of §7.3's
bounds (400). A partial result is refused specifically: an over-budget call does **not** come back
with the first five of six pages, because a caller that asked about six pages and reasoned over
five would not know which one it never saw (§11.3).

**Every bound is checked before anything is rendered.** Rendering is the memory spike §15.1 names,
so the page count, the dpi, the region and the 12 MP total are all settled from the page
rectangles — `serve/raster_cache.py` predicts the size instead of measuring the pixmap, because a
budget enforced after the allocation has already paid for what it refuses.
"""
from __future__ import annotations

import base64
from typing import Any, Literal, Mapping, Sequence

from vsir import logging as vsir_logging
from vsir.config import DPI_INDEX, Config
from vsir.serve import raster_cache
from vsir.serve.audit import Usage, page_ids_of
from vsir.serve.caps import validate_fetch_megapixels, validate_fetch_pages
from vsir.serve.envelope import (
    FetchImage,
    FetchPage,
    FetchResult,
    Provenance,
    Summary,
    ToolEnvelope,
)

#: The three parts of §7.2.5's ``include``. A `Literal` on the request model, so a fourth name is
#: an `invalid_request` from the dispatcher and never a silently ignored word.
PART = Literal["image", "text", "summary"]

#: The default: everything. Dropping ``"image"`` makes `fetch` a cheap text/summary read (§7.2.5).
INCLUDE_ALL: tuple[PART, ...] = ("image", "text", "summary")

_log = vsir_logging.get_logger(__name__)


def _summary(payload: Mapping[str, Any]) -> Summary | None:
    """The page's summary in its **dominant** language — its first (§5.2, D5).

    `fetch` takes no language and no scope, so there is nothing to prefer with: `skim_pages` picks
    by the caller's requested language because a *search* carries one. Here the honest answer is
    the page's own dominant summary, and the ``lang`` field says which language that turned out to
    be rather than leaving the caller to guess (D5 — never a blended multi-language string).
    """
    summaries = (payload.get("content") or {}).get("summaries") or []
    if not summaries:
        return None
    first = summaries[0]
    return Summary(lang=str(first.get("lang") or ""), text=str(first.get("text") or ""))


def _image(resolved: raster_cache.ResolvedPage, *, dpi: int,
           region: Sequence[float] | None, inline: bool) -> FetchImage:
    """One page's raster, as a reference and — when ``inline`` — as the pixels beside it.

    The URL is present either way and it is the same URL: ``inline=false`` is what the console
    uses so megabytes do not travel through JSON twice, and it must be able to render exactly what
    an inline caller received (§7.2.5).
    """
    raster = raster_cache.raster(resolved, dpi=dpi, region=region)
    return FetchImage(
        url=raster_cache.page_image_url(resolved.page_id, dpi=dpi, region=region),
        dpi=dpi,
        region=list(region) if region is not None else None,
        width=raster.width,
        height=raster.height,
        bytes_b64=base64.b64encode(raster.png).decode("ascii") if inline else None,
    )


def fetch(client: Any, cfg: Config, page_ids: Sequence[str], *,
          include: Sequence[str] = INCLUDE_ALL,
          dpi: int = DPI_INDEX,
          region: Sequence[float] | None = None,
          inline: bool = True,
          provenance: Provenance,
          reads_remaining: int = 0) -> tuple[ToolEnvelope[FetchResult], Usage]:
    """The named pages' material (§7.2.5), and what the call consumed for the audit line (§7.4).

    Stateless in the way that matters: ``client`` and ``cfg`` are the store and the release's
    configuration, ``provenance`` and ``reads_remaining`` come from the request context the caller
    owns, and nothing survives the call — the rendered rasters live in the process's LRU, which is
    a cache and never a source of truth (§4.2, §15 Factor VI). The HTTP route and the MCP server
    both call **this** function and add only transport (§7.5).

    ``page_ids`` is de-duplicated with the caller's order preserved, and the bound is checked on
    what that leaves: §7.3 bounds *pages*, and one page named five times is one page rendered once.

    Returns the envelope **and** a :class:`~vsir.serve.audit.Usage`, because §7.4 audits `fetch`
    beside `read` — the shared line tracks image-byte movement rather than spend (`fetch` is free,
    §8.1a). ``cache_hit`` is true when the call rendered nothing new, which is the fact worth
    recording: it is the call that cost no memory and no time.
    """
    wanted = list(dict.fromkeys(page_ids))
    parts = set(include)

    # The bounds first, and in this order: the page count needs no I/O at all, the dpi and the
    # region need none either, and only the megapixel total needs the documents open. A caller
    # that violated two of them is told about the cheapest one, which is also the one it can fix
    # without knowing anything about the corpus.
    validate_fetch_pages(wanted)
    raster_cache.validate_raster_request(dpi, region)

    # The index half always; the document store **only** when pixels were asked for. §7.2.5 calls
    # a `fetch` without `"image"` a cheap text/summary read, and it stops being one the moment it
    # can fail on an unmounted volume: `text` and `summary` are payload fields, so a caller that
    # wants neither the bytes nor a URL must not be refused for bytes it never asked for.
    payloads = raster_cache.resolve_payloads(client, cfg, wanted)
    resolved: dict[str, raster_cache.ResolvedPage] = {}
    if "image" in parts:
        resolved = raster_cache.attach_sources(client, cfg, payloads)
        validate_fetch_megapixels(
            raster_cache.total_megapixels(resolved.values(), dpi=dpi, region=region))

    before = raster_cache.cache_info()
    pages = [
        FetchPage(
            page_id=page_id,
            image=(_image(resolved[page_id], dpi=dpi, region=region, inline=inline)
                   if "image" in parts else None),
            # `text` comes from the payload `ingest/probe.py` wrote and from nowhere else: it is
            # the same string `lookup` matched and `verify` checks against, so a caller cannot be
            # shown one extraction and have its claim checked against another (I2, F15).
            text=str(payloads[page_id].get("text") or "") if "text" in parts else None,
            summary=_summary(payloads[page_id]) if "summary" in parts else None,
            text_trust=str(payloads[page_id].get("text_trust") or "no_text"),
        )
        for page_id in wanted
    ]
    rendered = raster_cache.renders(before, raster_cache.cache_info())

    _log.info("fetch", tool="fetch", pages=len(pages), dpi=dpi,
              include=sorted(parts), inline=inline, region=list(region) if region else None,
              rendered=rendered,
              # The megapixels actually produced, so an operator can see what the 12 MP bound is
              # protecting. Never the bytes and never the page text (§15.1's retention row).
              megapixels=round(sum((page.image.width * page.image.height) / 1_000_000
                                   for page in pages if page.image), 2))
    usage = Usage(page_ids=page_ids_of(wanted), dpi=dpi if "image" in parts else 0,
                  cache_hit="image" in parts and rendered == 0)
    return ToolEnvelope[FetchResult](
        # `ok` because the **call** ran (§7.1). There is no absence to express: the caller named
        # the pages, and a page that could not be produced left this function as a refusal.
        status="ok",
        result=FetchResult(pages=pages),
        reads_remaining=reads_remaining,
        provenance=provenance,
    ), usage
