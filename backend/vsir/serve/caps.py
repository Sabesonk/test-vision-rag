"""The caps of Spec §7.3 (F18) — **each one a typed 400 naming its bound.**

Never a clamp, never a truncation, never a "did the best I could". The reason is specific: a `read`
silently trimmed from four pages to three answers a question about pages the caller did not ask
about, and reports success. A `dpi` quietly clamped from 400 to 220 returns an image the caller
cannot read the part number off, and reports success. In both cases the caller has no way to know,
so the failure surfaces as a wrong answer somewhere downstream instead of an error here.

`dpi` is also a **money** bound. 400 dpi over a full page is megapixels of raster and tokens of
vision input, which is why anything above the pinned answer dpi requires a `region`: an operator
who needs that detail needs it about a *part* of the page.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from vsir.config import MAX_READ_PAGES
from vsir.core.exact import UnknownScopeKey
from vsir.core.indexed import reject_unknown_keys

#: §7.3. 36/72 are the triage thumbnail tiers behind `thumb_url`, 150 is the `fetch` default, and
#: 220 is what `read` sees — pinned, because the dpi is an input to `read_key` (§6.3).
ALLOWED_DPI = (36, 72, 150, 220, 300, 400)
#: Above this, a full page is refused and a `region` is required.
REGION_REQUIRED_ABOVE = 220
MAX_FETCH_PAGES = 5
#: The raster budget for one `fetch`. Rendering is the memory spike, and this is what bounds it.
MAX_FETCH_MEGAPIXELS = 12.0


class ToolError(Exception):
    """A typed refusal with a machine-readable code, mapped to an HTTP status by `serve/app.py`.

    The code is the contract: an agent switches on `fetch_budget_exceeded`, not on prose. The
    details name the bound and what was asked for, so the next attempt can be correct rather than
    a retry of the same mistake.
    """

    def __init__(self, code: str, message: str, *, http_status: int = 400, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


def validate_read_pages(page_ids: Sequence[str]) -> None:
    """`read` takes at most three pages (§7.3) — tightened from `impl`'s four, deliberately."""
    if len(page_ids) > MAX_READ_PAGES:
        raise ToolError(
            "read_page_cap_exceeded",
            f"read takes at most {MAX_READ_PAGES} pages, got {len(page_ids)}",
            limit=MAX_READ_PAGES, requested=len(page_ids),
        )


def validate_fetch_pages(page_ids: Sequence[str]) -> None:
    if len(page_ids) > MAX_FETCH_PAGES:
        raise ToolError(
            "fetch_budget_exceeded",
            f"fetch takes at most {MAX_FETCH_PAGES} pages, got {len(page_ids)}",
            bound="pages", limit=MAX_FETCH_PAGES, requested=len(page_ids),
        )


def validate_fetch_megapixels(megapixels: float) -> None:
    if megapixels > MAX_FETCH_MEGAPIXELS:
        raise ToolError(
            "fetch_budget_exceeded",
            f"fetch is bounded at {MAX_FETCH_MEGAPIXELS} MP, requested {megapixels:.1f} MP",
            bound="megapixels", limit=MAX_FETCH_MEGAPIXELS, requested=round(megapixels, 2),
        )


def validate_dpi(dpi: int, region: Sequence[float] | None = None) -> None:
    """`dpi` is on the allowed list, and above the answer dpi it needs a region (§7.3)."""
    if dpi not in ALLOWED_DPI:
        raise ToolError(
            "dpi_not_allowed",
            f"dpi must be one of {list(ALLOWED_DPI)}, got {dpi}",
            allowed=list(ALLOWED_DPI), requested=dpi,
        )
    if dpi > REGION_REQUIRED_ABOVE and region is None:
        raise ToolError(
            "dpi_requires_region",
            f"dpi {dpi} exceeds {REGION_REQUIRED_ABOVE} and requires a region: detail that fine "
            f"is about part of a page, and a full page at this dpi is megapixels of raster",
            requested=dpi, region_required_above=REGION_REQUIRED_ABOVE,
        )


def validate_region(region: Sequence[float] | None) -> None:
    """A normalised ``[x0, y0, x1, y1]`` (D6). Out of range is refused, never clamped.

    §7.3 does not enumerate an error for a malformed region because it enumerates *bounds*; this is
    the same rule applied to the one parameter it leaves implicit. Clamping ``[0, 0, 2, 2]`` to the
    page would return a different crop from the one asked for and call it success.
    """
    if region is None:
        return
    if len(region) != 4:
        raise ToolError("region_invalid", f"region is [x0, y0, x1, y1], got {len(region)} values",
                        requested=list(region))
    x0, y0, x1, y1 = region
    if not all(0.0 <= value <= 1.0 for value in region):
        raise ToolError("region_invalid", f"region coordinates are normalised to 0..1, got {list(region)}",
                        requested=list(region))
    if x0 >= x1 or y0 >= y1:
        raise ToolError("region_invalid", f"region must have x0 < x1 and y0 < y1, got {list(region)}",
                        requested=list(region))


def validate_scope(scope: Mapping[str, Any] | Iterable[str] | None) -> None:
    """Every scope key is in ``INDEXED`` (I6, F10) — a typed 400, never an unindexed scan."""
    if not scope:
        return
    unknown = reject_unknown_keys(scope)
    if unknown:
        raise ToolError(
            "filter_unknown_key",
            f"not filterable (see INDEXED): {unknown}",
            keys=unknown,
        )


def validate_budget(reads_remaining: int) -> None:
    """The per-question ceiling (§8.4, F18). A 429, not a silent truncation of the loop."""
    if reads_remaining <= 0:
        raise ToolError(
            "budget_exhausted",
            "the read budget for this question is exhausted",
            http_status=429, reads_remaining=0,
        )


def as_tool_error(exc: UnknownScopeKey) -> ToolError:
    """Translate the core layer's domain error into the surface's typed 400.

    `core/` does not know about HTTP, and `serve/` does not re-implement the `INDEXED` gate: one
    check, one translation.
    """
    return ToolError("filter_unknown_key", str(exc), keys=exc.keys)
