"""Steps 04-05 — the window ladder. Ported from ``impl/app/windows.py``.

A window is a **page range, not a chunk**. Its boundary is an artefact of the model's attention
limit and stitching deletes it again; it never becomes a retrieval boundary. Three granularities
stay separate throughout: window (attention), section (semantics), page (index).

This step costs nothing and decides what the next one costs. Two decisions:

**How to cut.** Target 30 pages, subject to a ladder (§6.2). Level 0 sends the whole document;
Level 1 cuts on the chapter starts the document declares; Level 2 folds at the cap where there is
no structure to cut on. Every rung produces windows of at most ``cap`` pages covering the document
exactly once, and **every rung is parallel**.

**Level 2 is not `impl`'s rung (fixes/001).** §2.5 B excluded it because `impl`'s fold *"had to run
sequentially with a carry chain"* — *"batch 2 needs to know what batch 1 ended with"*. That was a
correct description of `impl`, whose model reported section **extent**, so a window beginning
mid-section had to be told where it was. §5.2 deleted extent: ``sections[]`` is presence per page
and §6.1 step 08 computes extent as ``(min, max)`` over sightings keyed by ``derive.section_key``,
so two windows that never saw each other reassemble one section — which is what F8 is and what
:mod:`vsir.ingest.stitch` already does. **The carry chain's reason was removed with ``units[]``;
the exclusion stayed behind.** A window is a page range, never a retrieval boundary, so nothing
else about a fold is unsafe here and :attr:`Plan.parallel` stays true at every rung.

Refusing it cost the corpus, not just the two documents §6.2 named. Put every PDF under
``dilmah_enginnering_usecase/dataset`` — 202 files, 5,578 pages — through the shipped ladder, giving
Level 1 the best possible break by feeding it each file's own outline: **14 documents and 2,719
pages, 49% of the corpus, refused**. Eleven of the fourteen declare no outline at all. One of them
is the pilot `TC1E-SF`, so M2b could not complete — it failed at step 05, one step before the spend
it was waiting on a credential for, and ``data/fixtures/TC1E-SF/expected.json`` already declared
the ``[[1, 30], [31, 55]]`` this rung produces.

**A window is now bounded below as well as above.** ``chapter_ranges`` bounded chapters above and
packed nothing together, so a densely outlined file billed one call per sheet: ``ETC1AV81`` declares
8,187 bookmarks over 592 pages and cut into 592 one-page windows where about 20 do the same work,
and `impl`'s own 34-page ``LTC1AV81`` ran 12. :func:`pack` folds a chapter below
:data:`MIN_WINDOW_PAGES` into its neighbour and leaves every chapter above it alone — a floor on
the merge rather than a fill to the cap, because a Level 1 that packs to the cap has taken its
boundaries from the cap and is Level 2 wearing Level 1's number.

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

#: Level 2 is a fold at the cap. It is **not** `impl`'s rung: §5.2 deleted section extent from the
#: model, so the carry chain that forced `impl`'s Level 2 to run sequentially has nothing left to
#: carry (§6.2, and fixes/001).
MAX_LADDER_LEVEL = 2

#: Below this, a chapter is too small to be worth a model call of its own and :func:`pack` folds it
#: into its neighbour (fixes/001). A third of the cap: large enough that a document of one-page
#: bookmarks stops billing per sheet, small enough that a chapter anyone would call a chapter keeps
#: its own window and Level 1 keeps meaning what it says.
MIN_WINDOW_PAGES = CAP_PAGES_PER_WINDOW // 3

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
    """Retained for the error taxonomy; **no longer raised** (fixes/001).

    `plan()` reached this when a document had no usable chapter start, or a chapter over the cap.
    Level 2 is now a fold at the cap rather than a refusal, so nothing produces it — but the class
    stays: :class:`WindowUnsplittable` inherits from the same :class:`WindowError` family that
    ``cli.py`` catches, and an operator may already be switching on ``ladder_level_2_required``.
    Deleting a code is a breaking change for a caller that handles it; leaving it unreachable is
    not.
    """

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
        """Always true, at every rung — and a property rather than a constant for a reason.

        Level 0 and Level 1 windows are independent because they cut on the document's own
        structure; Level 2's are independent because this fold has no carry chain (fixes/001). A
        rung that could not run in parallel would be one that had re-introduced section **extent**
        into the model's schema, which is the thing §5.2 deleted — so this staying true is an
        assertion about the schema, not just about the scheduler.
        """
        return True

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


def split_oversized(ranges: Iterable[tuple[int, int]], cap: int) -> tuple[tuple[int, int], ...]:
    """Fold a range longer than ``cap`` into ``cap``-page windows, filling before spilling.

    This is the fold `impl` called Level 2, without the part that made it unsafe there. Its carry
    chain existed because `impl`'s model reported section **extent** — *"batch 2 needs to know what
    batch 1 ended with"*. §5.2 deleted extent: ``sections[]`` is presence per page and step 08
    computes ``(min, max)`` over sightings, so two windows that never saw each other reassemble one
    section (F8). The reason for the chain was removed with the schema; the fold is safe without it
    and stays parallelisable.

    Fill-before-spill rather than even parts: it is one comparison instead of two divisions, and it
    is what `impl` did, so ``data/fixtures/TC1E-SF/expected.json``'s ``[[1, 30], [31, 55]]`` —
    written from the spec before the ingest, and normative — is reproduced exactly rather than
    approached.
    """
    out: list[tuple[int, int]] = []
    for start, end in ranges:
        at = start
        while at <= end:
            out.append((at, min(at + cap - 1, end)))
            at += cap
    return tuple(out)


def pack(ranges: Iterable[tuple[int, int]], cap: int,
         floor: int = MIN_WINDOW_PAGES) -> tuple[tuple[int, int], ...]:
    """Merge **uneconomically small** consecutive ranges into windows of at most ``cap`` pages.

    The cap bounded a window above and nothing bounded it below, so a densely outlined document
    billed one call per sheet: ``ETC1AV81`` declares 8,187 bookmarks over 592 pages and cut into 592
    one-page windows where about 20 do the same work, and `impl`'s 34-page ``LTC1AV81`` ran 12.

    Only a range below ``floor`` is folded into its predecessor, and never past the cap. Filling
    greedily to the cap instead would also merge chapters that are already the right size — the
    synthetic corpus's three 14-page chapters become two 28-page windows — and that is not a
    saving worth having, because it makes **Level 1's boundaries come from the cap rather than from
    the chapters**, which is the whole difference between the rungs. A rung that packs to the cap is
    Level 2 wearing Level 1's number, and the fold it invents is exactly the one §6.2 did not want
    nobody to have chosen.

    Order-preserving, so the page set is unchanged and every boundary it keeps is still a chapter
    boundary. On the three documents fixes/001 measured this reaches the same counts as filling to
    the cap would — ``ETC1AV81`` 592 -> 20, ``LTC1AV81`` 12 -> 2, ``TC1E-SF`` unchanged at
    ``(1, 30), (31, 55)`` — because in every one of them the offending chapters are the small ones.
    """
    packed: list[tuple[int, int]] = []
    for start, end in ranges:
        small = end - start + 1 < floor
        if packed and small and end - packed[-1][0] + 1 <= cap:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    return tuple(packed)


def inline_cap(page_count: int, size_bytes: int, cap: int) -> int:
    """``cap``, reduced where the file is too large to hand over ``cap`` pages at a time.

    Ported from `impl` as a ceiling on Level 0 and kept here as a bound on **every** rung. As a
    refusal it only pushed the document to a rung that refused too; as a bound it does the thing it
    was for.

    It measures the **source PDF** while ``extract_window`` sends **rendered PNGs**, so it is
    conservative rather than exact. A raster-bytes budget is the honest replacement and is a
    follow-up, not this fix.
    """
    if size_bytes <= MAX_INLINE_BYTES or page_count < 1:
        return cap
    return max(1, min(cap, int(MAX_INLINE_BYTES // (size_bytes / page_count))))


def plan(page_count: int, *, toc: Iterable[TocEntry | Mapping[str, Any]] = (),
         size_bytes: int = 0, cap: int = CAP_PAGES_PER_WINDOW, document: str = "") -> Plan:
    """The ladder: Level 0 whole, Level 1 on the document's own structure, Level 2 a fold.

    Every rung produces windows of at most ``cap`` pages covering 1..``page_count`` exactly once,
    and every rung is parallel. The difference between them is only **where the boundaries come
    from** — the document itself, its chapters, or the cap — which is what the rung number is for
    and what the run record reports.
    """
    if page_count < 1:
        raise WindowError(f"a document has at least one page, got {page_count}",
                          document=document, page_count=page_count)

    cap = inline_cap(page_count, size_bytes, cap)

    if page_count <= cap:
        return Plan(0, (Window(1, page_count, 0),))

    chapters = chapter_ranges(toc, page_count)
    if chapters:
        return Plan(1, tuple(Window(start, end, 1)
                             for start, end in pack(split_oversized(chapters, cap), cap)))

    # No structure to cut on, so the cap is the only boundary there is. Not `impl`'s rung: no carry
    # chain, no sequential dependency — see `split_oversized`.
    return Plan(2, tuple(Window(start, end, 2)
                         for start, end in split_oversized(((1, page_count),), cap)))
