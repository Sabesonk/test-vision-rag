"""Steps 04-05 — the window ladder. Ported from ``impl/app/windows.py``.

A window is a **page range, not a chunk**. Its boundary is an artefact of the model's attention
limit and stitching deletes it again; it never becomes a retrieval boundary. Three granularities
stay separate throughout: window (attention), section (semantics), page (index).

This step costs nothing and decides what the next one costs. Two decisions:

**How to cut.** Target 30 pages, subject to a ladder (§6.2). Level 0 sends the whole document;
Level 1 cuts on the chapter starts S1 read out of the front matter, so the windows are independent
and can run in parallel. `impl` has a third rung — a blind 30-page fold with a carry chain, where
*"batch 2 needs to know what batch 1 ended with"* — and **v1 does not implement it** (§2.5 B). A
document that needs it fails typed :class:`LadderLevel2Required`, naming the document, rather than
straddling a safety function across a fold nobody chose (which is F8, one level up). The concrete
consequence is stated in §6.2: `impl/corpus.yaml` records that the 1,440-page manual and the
592-page E-diagram are the only two documents that need Level 2, and it already excludes them.

**What to write on the batch.** ``extract_key`` is the receipt that stops the pipeline paying
twice, and it lives with the other three keys of §6.3 in :mod:`vsir.vlm.cache` — one module owns
every question of the form *"has this exact question already been asked of this exact model?"*,
because the four keys have to agree about what an input is. This module's job is to decide **which
pages** each receipt covers; :func:`vsir.vlm.extract_key` turns that into the receipt.

**Bisection (F13), written net new.** On ``MAX_TOKENS``, a truncated or schema-invalid response, or
an offset failure: split the window and re-bill. Never pad, never guess the offset, never accept a
partial window — a truncated 30-page window that is quietly kept loses 30 pages of a manual and
reports success. A single page that still exceeds the budget is :class:`WindowUnsplittable`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from vsir.config import CAP_PAGES_PER_WINDOW

#: Ported from `impl`: the inline part ceiling, with headroom. It rules Level 0 out for a file too
#: large to hand over in one piece even when its page count would fit.
MAX_INLINE_BYTES = 18 * 1024 * 1024

#: v1 climbs to Level 1 and stops. Level 2 is the blind cut and its carry chain (§2.5 B, §6.2).
MAX_LADDER_LEVEL = 1

#: Why a window was split. Each is a §6.2 trigger, and each re-bills — none of them pads or guesses.
BisectReason = Literal["max_tokens", "truncated", "schema_invalid", "offset"]
BISECT_REASONS: tuple[str, ...] = ("max_tokens", "truncated", "schema_invalid", "offset")


class WindowError(RuntimeError):
    """A typed refusal from the windowing step, with a machine-readable code.

    The code is the contract, exactly as it is for the tool surface (§7.3): an operator switches on
    ``ladder_level_2_required``, not on prose, and the details name the document and the bound so
    the next attempt can be different rather than a retry of the same one.
    """

    code = "window_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


class LadderLevel2Required(WindowError):
    """The document needs a blind cut, which v1 does not do (§6.2). Named, never silent."""

    code = "ladder_level_2_required"


class WindowUnsplittable(WindowError):
    """One page, still over budget. There is nothing left to bisect (F13)."""

    code = "window_unsplittable"


class TocEntry(BaseModel):
    """One chapter start, as S1 read it: a title and the **PDF page index** it begins on."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    #: 0 means "the model could not see a PDF index for this entry", which is the common case for
    #: a printed contents page: it shows printed labels, not indices. Such an entry cuts nothing.
    page_no: int = 0


class DocumentFacts(BaseModel):
    """Step 04's output — what document this is, and where its chapters start.

    S1 is a cheap call over the front matter whose *ToC output is the sole input to the branch that
    decides how much S2 costs*, which is why it is a separate step at all. `impl` neither cached
    nor persisted it, so every re-run re-billed it and — worse — a future call returning a
    different contents list silently re-picked the ladder and re-billed every window with it
    (register B2). §6.3 caches it under ``facts_key``, which is what makes the ladder reproducible.

    The model's ``revision``, ``doc_type`` and ``subjects`` are its **reading**, kept as a
    cross-check. Where the operator declared one, the manifest wins (§6.1 step 01): a silent
    disagreement about the revision would mint a second document in the graph.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    revision: str = ""
    doc_type: str = ""
    subjects: list[str] = Field(default_factory=list)
    lang: list[str] = Field(default_factory=list)
    #: Copied VERBATIM. This corpus dates applicability by build batch ("from batch 68"), not by
    #: calendar date; converting one into the other invents a fact about which machines are covered.
    effectivity_basis: str = ""
    toc: list[TocEntry] = Field(default_factory=list)


@dataclass(frozen=True)
class Window:
    """An inclusive, 1-based range of PDF pages, and how it came to exist."""

    start: int
    end: int
    level: int
    #: Empty for a window the ladder produced; otherwise the §6.2 trigger that split its parent.
    bisected_from: str = ""

    def __post_init__(self) -> None:
        if self.start < 1 or self.end < self.start:
            raise ValueError(f"not a page range: {self.start}..{self.end}")

    @property
    def pages(self) -> int:
        return self.end - self.start + 1

    @property
    def page_numbers(self) -> tuple[int, ...]:
        """The absolute PDF pages, in order — what gets rendered and hashed for the key."""
        return tuple(range(self.start, self.end + 1))

    def absolute(self, page_index: int) -> int:
        """§6.4: ``abs_page = window.start + page_index - 1``, and the range is checked.

        The single most dangerous line in the pipeline lives here, once, so no caller writes it
        again slightly differently. A ``page_index`` outside the window is not clamped into it —
        that is precisely the off-by-one this raises on.
        """
        if not 1 <= page_index <= self.pages:
            raise ValueError(
                f"page_index {page_index} is outside window {self.start}..{self.end} "
                f"({self.pages} pages): the model returned an index it was not given"
            )
        return self.start + page_index - 1


@dataclass(frozen=True)
class Plan:
    """The windows a document is cut into, and which rung of the ladder chose them."""

    level: int
    windows: tuple[Window, ...]

    @property
    def parallel(self) -> bool:
        """Always true in v1, and it is a property rather than a constant for a reason.

        Level 0 and Level 1 windows are independent, so they can run at once. Level 2's carry chain
        is what forced `impl` to run them in order, and it is out of scope — so if this ever
        returns False, something has re-introduced the rung §6.2 excludes.
        """
        return self.level <= MAX_LADDER_LEVEL

    @property
    def page_numbers(self) -> tuple[int, ...]:
        """Every page the plan covers, in order. Used to assert no gap and no duplicate."""
        return tuple(page for window in self.windows for page in window.page_numbers)

    def covers(self, page_count: int) -> bool:
        """Exactly pages 1..page_count, once each. A bisection must not change this."""
        return self.page_numbers == tuple(range(1, page_count + 1))

    def bisect(self, window: Window, reason: BisectReason) -> "Plan":
        """Replace one window with its two halves and re-bill them (F13).

        The page set is unchanged — the union of the halves is the original, with no gap and no
        duplicate — so the document is still covered exactly once. The halves get new keys for
        free: ``extract_key`` is built from the page image hashes, and each half has a different
        set of them.
        """
        if window not in self.windows:
            raise ValueError(f"window {window.start}..{window.end} is not in this plan")
        left, right = bisect_window(window, reason)
        index = self.windows.index(window)
        return replace(self, windows=self.windows[:index] + (left, right)
                       + self.windows[index + 1:])


def bisect_window(window: Window, reason: BisectReason) -> tuple[Window, Window]:
    """Split a window in half. One page raises :class:`WindowUnsplittable`."""
    if reason not in BISECT_REASONS:
        raise ValueError(f"not a bisection trigger: {reason!r} (expected {list(BISECT_REASONS)})")
    if window.pages < 2:
        raise WindowUnsplittable(
            f"page {window.start} still exceeds the output budget after bisection "
            f"({reason}): there is nothing left to split",
            page_no=window.start, reason=reason,
        )
    middle = window.start + window.pages // 2 - 1
    return (
        Window(window.start, middle, window.level, bisected_from=reason),
        Window(middle + 1, window.end, window.level, bisected_from=reason),
    )


def chapter_ranges(toc: Iterable[TocEntry | Mapping[str, Any]],
                   page_count: int) -> tuple[tuple[int, int], ...]:
    """Chapter starts → contiguous ranges covering the whole document. Ported from `impl`.

    An entry whose ``page_no`` is not a usable PDF index is dropped, and if nothing starts at page
    1 a range is inserted so the front matter is covered rather than skipped.
    """
    starts = sorted({
        int(entry.page_no if isinstance(entry, TocEntry) else entry.get("page_no", 0) or 0)
        for entry in toc
    } & set(range(1, page_count + 1)))
    if not starts:
        return ()
    if starts[0] != 1:
        starts.insert(0, 1)
    return tuple(
        (start, (starts[index + 1] - 1) if index + 1 < len(starts) else page_count)
        for index, start in enumerate(starts)
    )


def plan(page_count: int, *, toc: Iterable[TocEntry | Mapping[str, Any]] = (),
         size_bytes: int = 0, cap: int = CAP_PAGES_PER_WINDOW, document: str = "") -> Plan:
    """The ladder: Level 0, then Level 1, then a named refusal. Never a blind cut (§6.2)."""
    if page_count < 1:
        raise WindowError(f"a document has at least one page, got {page_count}",
                          document=document, page_count=page_count)

    if page_count <= cap and size_bytes <= MAX_INLINE_BYTES:
        return Plan(0, (Window(1, page_count, 0),))

    chapters = chapter_ranges(toc, page_count)
    if chapters and all(end - start + 1 <= cap for start, end in chapters):
        return Plan(1, tuple(Window(start, end, 1) for start, end in chapters))

    # `impl` fell through to a blind 30-page fold here. v1 refuses, by name, and says what would
    # have to change: usable chapter starts from S1, every chapter within the cap.
    oversized = [f"{start}-{end}" for start, end in chapters if end - start + 1 > cap]
    raise LadderLevel2Required(
        f"{document or 'document'}: {page_count} pages needs a window ladder v1 does not "
        f"implement (§6.2). Level 0 needs <= {cap} pages; Level 1 needs chapter starts from S1 "
        f"with every chapter <= {cap} pages"
        + (f", and these exceed it: {oversized}" if oversized
           else ", and S1 reported no usable chapter start"),
        document=document, page_count=page_count, cap=cap,
        chapters=len(chapters), oversized_chapters=oversized,
    )
