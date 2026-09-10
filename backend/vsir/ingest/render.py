"""Step 03 — page rasters. Ported from ``impl/app/render.py``, with its filesystem removed.

`impl` rendered every page at both dpis, unconditionally, and wrote 110 PNGs and 20.7 MB to
``/data/pages/<doc_id>/`` for one 55-page document — before anything had been validated, and with
nothing to collect them if the document was later quarantined (register E3). Two things came out of
that: a stale ``image_path`` on the record that made ``read()`` return 503 for every page (A5), and
an instance whose answers depended on files another instance did not have.

So the port keeps the rendering and deletes the disk. Spec §4.2 is explicit: **rasters are never
persisted.** They are rendered on demand into an in-process LRU cache, a cold instance returns
identical results and only more slowly (§15 Factor VI), and the record carries no path at all
(§5.3). What travels in a response is an ``ImageRef`` — a URL, never bytes (D12, §7.1).

Two dpis and three uses (§4.2, SA-12):

* ``dpi_index = 150`` — the raster that gets **embedded** (U010).
* ``dpi_answer = 220`` — pinned, and shared by two consumers: S2 extraction, where the ordered
  page image hashes are what ``extract_key`` is built from (§6.3), and ``read``, where the dpi is
  an input to ``read_key`` and a caller cannot change it (F19, §7.3).
* ``fetch`` and the thumbnail tiers render at 36/72/150/220/300/400. Those are cache-only and feed
  no key (U018).

`impl`'s ``render_image`` — the standalone-image door, which resized with Pillow and saved a PNG —
is not ported. The corpus is PDFs (§2.1), and every line of it was about writing files.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import pymupdf

from vsir.config import DPI_ANSWER, DPI_INDEX

#: How many rasters one process keeps. A cache, never a source of truth: evicting an entry costs a
#: re-render and changes no answer. Bounded because a long-lived `web` process would otherwise grow
#: with every page anyone has ever looked at.
RASTER_CACHE_PAGES = 96

#: How many page rectangles one process keeps. Four floats each, so this is deliberately far
#: larger than the raster cache: it is what lets a `fetch` refuse an over-budget render without
#: opening the document again, let alone rasterising it (§7.3, §15.1).
PAGE_BOX_CACHE_PAGES = 4096

#: A region is normalised to the page, so it means the same thing at every dpi (§7.3, D6).
FULL_PAGE = (0.0, 0.0, 1.0, 1.0)


@dataclass(frozen=True)
class Raster:
    """One rendered page, in memory. Nothing here has ever been on a filesystem."""

    page_no: int
    dpi: int
    width: int
    height: int
    png: bytes
    region: tuple[float, float, float, float] = FULL_PAGE

    @property
    def sha256(self) -> str:
        """The page image hash — an ordered list of these is what ``extract_key`` is built from."""
        return hashlib.sha256(self.png).hexdigest()

    @property
    def megapixels(self) -> float:
        """What §7.3's `fetch` budget is measured in."""
        return self.width * self.height / 1_000_000

    @property
    def is_full_page(self) -> bool:
        return self.region == FULL_PAGE


class RenderError(RuntimeError):
    """A typed refusal from the renderer, with a machine-readable code."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def normalise_region(region: Sequence[float] | None) -> tuple[float, float, float, float]:
    """Validate ``[x0, y0, x1, y1]`` in 0..1. A malformed region is a refusal, never a clamp."""
    if region is None:
        return FULL_PAGE
    values = tuple(float(v) for v in region)
    if len(values) != 4:
        raise RenderError("region_invalid", f"region is [x0, y0, x1, y1], got {list(region)}",
                          region=list(region))
    x0, y0, x1, y1 = values
    if not all(0.0 <= v <= 1.0 for v in values) or x0 >= x1 or y0 >= y1:
        raise RenderError("region_invalid",
                          f"region must be normalised 0..1 with x0<x1 and y0<y1, got {list(values)}",
                          region=list(values))
    return x0, y0, x1, y1


@lru_cache(maxsize=4096)
def source_hash(path: str, size: int, mtime_ns: int) -> str:
    """The file's identity for cache purposes, cheap enough to ask on every render.

    The digest is over the file's bytes; ``size`` and ``mtime_ns`` are in the *memo* key so a
    long-lived process re-hashes only when the file has moved underneath it. The ingest path does
    not rely on this at all — it passes the probe's ``content_hash`` straight through, which is the
    same digest computed once for the whole run.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(source: Path) -> str:
    stat = source.stat()
    return source_hash(str(source), stat.st_size, stat.st_mtime_ns)


def _clip(box: Any, region: tuple[float, float, float, float]) -> Any:
    """A normalised region as an absolute rectangle on this page, or ``None`` for a full page.

    One function, because two consumers must agree exactly: :func:`_render`, which rasterises the
    clip, and :func:`predicted_pixels`, which says how large that raster will be **before** it
    exists. `fetch`'s megapixel bound is enforced from the prediction (§7.3, U018), so a
    prediction computed from a slightly different rectangle would police a raster nobody renders.
    """
    if region == FULL_PAGE:
        return None
    x0, y0, x1, y1 = region
    return pymupdf.Rect(box.x0 + x0 * box.width, box.y0 + y0 * box.height,
                        box.x0 + x1 * box.width, box.y0 + y1 * box.height)


def _page(doc: Any, page_no: int) -> Any:
    """The 1-based page, or a typed refusal naming the range. Never a clamp to the last page."""
    if not 1 <= page_no <= doc.page_count:
        raise RenderError("page_out_of_range",
                          f"page {page_no} is outside 1..{doc.page_count}",
                          page_no=page_no, page_count=doc.page_count)
    return doc[page_no - 1]


def _render(source: str, page_no: int, dpi: int,
            region: tuple[float, float, float, float]) -> Raster:
    """Rasterise one page. **The uncached body**, and the only place pixels are produced.

    Separate from :func:`_cached` so that *"the cache served this one"* is observable: a
    call-count spy wraps **this** function, and :func:`cache_clear` then makes the next request
    render again. A cache whose hits cannot be counted is a cache nobody can prove is one — and
    §15 Factor VI rests on this being a cache and never a source of truth.
    """
    with pymupdf.open(source) as doc:
        page = _page(doc, page_no)
        pixels = page.get_pixmap(dpi=dpi, clip=_clip(page.rect, region))
        return Raster(page_no=page_no, dpi=dpi, width=pixels.width, height=pixels.height,
                      png=pixels.tobytes("png"), region=region)


@lru_cache(maxsize=RASTER_CACHE_PAGES)
def _cached(source: str, content_hash: str, page_no: int, dpi: int,
            region: tuple[float, float, float, float]) -> Raster:
    """Keyed by the file's **content**, so an edited PDF can never serve a stale raster.

    ``content_hash`` is in the key and unused in the body on purpose: it is what makes the key
    correct, and reading it here would defeat the point of having been given it.

    This is **the** raster cache — the one §4.2 and §7.2.5 require, shared by the ingest path and
    by the serving path. `serve/raster_cache.py` deliberately does not put a second one in front
    of it: a cache keyed by ``page_id`` cannot see a re-ingest of the same ``(doc_id, revision)``
    from corrected bytes, so it would serve the superseded pixels for as long as the process
    lived, and it would hold a second copy of every PNG while doing it.
    """
    return _render(source, page_no, dpi, region)


@lru_cache(maxsize=PAGE_BOX_CACHE_PAGES)
def _page_box(source: str, content_hash: str, page_no: int) -> tuple[float, float, float, float]:
    """The page's rectangle in points — the cheap fact behind :func:`predicted_pixels`.

    Its own memo, and far larger than the raster cache's: a page box is four floats and a raster
    is megabytes, and the whole point of asking for the box is to decide whether the raster may be
    made at all.
    """
    with pymupdf.open(source) as doc:
        box = _page(doc, page_no).rect
        return box.x0, box.y0, box.x1, box.y1


def render_page(source: str | Path, page_no: int, *, dpi: int = DPI_ANSWER,
                region: Sequence[float] | None = None, content_hash: str | None = None) -> Raster:
    """Render one page. In memory, cached by page content hash, never written down."""
    path = Path(source)
    return _cached(str(path), content_hash or _identity(path), page_no, dpi,
                   normalise_region(region))


def render_pages(source: str | Path, pages: Iterable[int], *, dpi: int = DPI_ANSWER,
                 content_hash: str | None = None) -> tuple[Raster, ...]:
    """Render several pages in absolute page order — a window's rasters, as S2 sees them."""
    path = Path(source)
    identity = content_hash or _identity(path)
    return tuple(render_page(path, page_no, dpi=dpi, content_hash=identity) for page_no in pages)


def page_hashes(source: str | Path, pages: Iterable[int], *, dpi: int = DPI_ANSWER,
                content_hash: str | None = None) -> tuple[str, ...]:
    """The **ordered page image hashes** ``extract_key`` is built from (§6.3)."""
    return tuple(raster.sha256
                 for raster in render_pages(source, pages, dpi=dpi, content_hash=content_hash))


def index_raster(source: str | Path, page_no: int, *, content_hash: str | None = None) -> Raster:
    """The ``dpi_index`` raster — the one the dense vector embeds (D4, U010)."""
    return render_page(source, page_no, dpi=DPI_INDEX, content_hash=content_hash)


def predicted_pixels(source: str | Path, page_no: int, *, dpi: int,
                     region: Sequence[float] | None = None,
                     content_hash: str | None = None) -> tuple[int, int]:
    """How large this raster **will be**, without making it (§7.3's megapixel bound, §15.1).

    Rendering is the memory spike, so the bound that exists to cap it has to be checked before the
    render rather than after: a 12 MP ceiling enforced by measuring the pixmap has already
    allocated the pixmap. The arithmetic is PyMuPDF's own — ``dpi/72`` as a scale matrix applied to
    the same rectangle :func:`_clip` produces — and `test_render.py` asserts the prediction equals
    the rendered size for every dpi of §7.3 and for a crop, because a prediction that drifted from
    the renderer would refuse calls that fit and admit calls that do not.
    """
    path = Path(source)
    normalised = normalise_region(region)
    x0, y0, x1, y1 = _page_box(str(path), content_hash or _identity(path), page_no)
    box = pymupdf.Rect(x0, y0, x1, y1)
    target = _clip(box, normalised) or box
    zoom = dpi / 72
    rect = (target * pymupdf.Matrix(zoom, zoom)).irect
    return rect.width, rect.height


def predicted_megapixels(source: str | Path, page_no: int, *, dpi: int,
                         region: Sequence[float] | None = None,
                         content_hash: str | None = None) -> float:
    """:func:`predicted_pixels` in the unit §7.3's `fetch` budget is written in."""
    width, height = predicted_pixels(source, page_no, dpi=dpi, region=region,
                                     content_hash=content_hash)
    return width * height / 1_000_000


def cache_info() -> dict[str, int]:
    """What the raster cache is holding. Reported by the CLI; nothing branches on it."""
    stats = _cached.cache_info()
    return {"hits": stats.hits, "misses": stats.misses,
            "size": stats.currsize, "maxsize": stats.maxsize or 0}


def cache_clear() -> None:
    """Drop every cached raster. A cache, so this is always safe and never loses information.

    Also the eviction a test forces to prove the cold path: after this, the same request renders
    again and must return a **byte-identical** image, which is what makes the cache provably an
    optimisation and not a source of truth (§4.2, §15 Factor VI).
    """
    _cached.cache_clear()
    _page_box.cache_clear()
    source_hash.cache_clear()
