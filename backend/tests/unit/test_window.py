"""L0/L1 — steps 04-05, the window ladder (Spec §6.2, §6.4, F13, fixes/001).

Every rung produces windows of at most the cap covering the document **exactly once**, and every
rung is parallel. The rungs differ only in where the boundaries come from — the document, its
chapters, or the cap — and that is what the level number reports. Coverage is asserted structurally
at every rung and every chapter shape, because `impl`'s failure mode here was a silent one-page
hole rather than an error.

Level 2 used to be a named refusal (§2.5 B), on the grounds that `impl`'s fold needed a carry
chain. fixes/001 measured the cost of that: 14 documents and 2,719 pages of the real corpus — 49%,
including the pilot `TC1E-SF` — could not be ingested at all. The carry chain's reason left with
``units[]`` when §5.2 deleted section extent, so the fold is safe and parallel here; what is
asserted is that it carries nothing between windows. A window that comes back truncated must still
bisect and re-bill: keeping the partial answer loses 30 pages of a manual and reports success (F13).

The four cache keys moved to `vlm/cache.py` with the VLM boundary (U008) and so did their tests —
`test_cache_keys.py`. What is still asserted here is the ladder's *use* of one: each window of a
plan, and each half of a bisection, must key differently, because a window's receipt is a fact
about the pages it actually covers.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from vsir.config import CAP_PAGES_PER_WINDOW, DPI_ANSWER
from vsir.eval import synthetic_pdf as generator
from vsir.ingest import probe, render
from vsir.ingest import window as w
from vsir.ingest.extract import S2_SCHEMA_HASH
from vsir.vlm import extract_key

MODEL = "gemini-3.8-flash-001"
PROMPT = "s2-v1"

#: The pilot's acceptance table, written from the spec before any ingest and normative (§12.1).
PILOT_EXPECTED = Path(__file__).resolve().parents[3] / "data/fixtures/TC1E-SF/expected.json"


@pytest.fixture(scope="module")
def pilot_expected() -> dict:
    """`TC1E-SF`'s declared corpus facts, read from the file rather than copied into an assertion."""
    if not PILOT_EXPECTED.is_file():
        pytest.skip(f"no pilot acceptance table at {PILOT_EXPECTED}")
    return json.loads(PILOT_EXPECTED.read_text())["corpus"]


def _key(source, window, probed):
    """One window's `extract_key`, over the rasters S2 would actually be shown (§6.3)."""
    return extract_key(
        render.page_hashes(source, window.page_numbers, dpi=DPI_ANSWER,
                           content_hash=probed.content_hash),
        vlm_model=MODEL, prompt_version=PROMPT, dpi=DPI_ANSWER, schema_hash=S2_SCHEMA_HASH)


# ── the ladder ──────────────────────────────────────────────────────────────────────────────────

def test_the_synthetic_corpus_plans_exactly_three_windows(synthetic_pdf, expected):
    """AC: three windows, each with a distinct `extract_key` (§6.2, Level 1)."""
    probed = probe.run(synthetic_pdf)
    plan = w.plan(probed.page_count, toc=generator.toc_entries(), size_bytes=probed.size_bytes,
                  document=expected["doc_id"])

    assert plan.level == expected["ladder_level"]
    assert [[win.start, win.end] for win in plan.windows] == expected["windows"]
    assert plan.covers(probed.page_count)
    assert plan.parallel is True

    keys = {_key(synthetic_pdf, win, probed) for win in plan.windows}
    assert len(keys) == len(plan.windows)


def test_a_document_inside_the_cap_is_one_window():
    plan = w.plan(CAP_PAGES_PER_WINDOW, size_bytes=1024)

    assert plan.level == 0
    assert plan.windows == (w.Window(1, CAP_PAGES_PER_WINDOW, 0),)
    assert plan.covers(CAP_PAGES_PER_WINDOW)


def test_a_file_too_large_to_send_whole_is_bounded_rather_than_refused():
    """Ported from `impl`: the page count is not the only ceiling on one pass.

    It used to refuse — and refusing was useless, because it only pushed the document onto a rung
    that refused too. As a **bound on the cap** it does the job it was written for (fixes/001): ten
    pages just over the inline ceiling become nine plus one, still covering the document once.
    """
    plan = w.plan(10, size_bytes=w.MAX_INLINE_BYTES + 1)

    assert [(win.start, win.end) for win in plan.windows] == [(1, 9), (10, 10)]
    assert plan.covers(10)
    assert plan.parallel is True


def test_the_inline_ceiling_reduces_the_cap_in_proportion_to_the_file():
    """:func:`inline_cap` is the bound, and it is arithmetic on the source PDF, not a guess.

    Conservative by construction: it measures the source while ``extract_window`` sends rendered
    PNGs. A raster-bytes budget is the honest replacement and is a follow-up, not this fix.
    """
    assert w.inline_cap(10, w.MAX_INLINE_BYTES, 30) == 30, "at the ceiling, the cap is untouched"
    assert w.inline_cap(10, w.MAX_INLINE_BYTES * 2, 30) == 4, (
        "twice the ceiling fits about half the pages, and rounds **down** — 4 rather than 5, "
        "because a bound that rounds up is not a bound")
    assert w.inline_cap(10, w.MAX_INLINE_BYTES * 100, 30) == 1, "never below one page"
    assert w.inline_cap(0, w.MAX_INLINE_BYTES * 2, 30) == 30, "no pages, nothing to divide by"
    assert w.inline_cap(10, 1024, 30) == 30, "a small file is not bounded at all"


def test_level_one_cuts_on_the_chapters_and_covers_the_front_matter():
    plan = w.plan(42, toc=[{"page_no": 15}, {"page_no": 29}], size_bytes=1024)

    assert plan.level == 1
    assert [(win.start, win.end) for win in plan.windows] == [(1, 14), (15, 28), (29, 42)]


def test_a_document_with_no_chapter_folds_at_the_cap_instead_of_refusing():
    """fixes/001 — the 1,440-page manual §6.2 named as permanently excluded now ingests.

    Eleven of the fourteen documents the shipped ladder refused declare no outline at all. There is
    no structure to cut on, so the cap is the only boundary there is — and that is a *rung*, not a
    failure, because §5.2 deleted the section extent that made `impl`'s fold need a carry chain.
    """
    plan = w.plan(1440, toc=[], size_bytes=1024, document="LTC1AV81-MANUAL")

    assert plan.level == 2
    assert len(plan.windows) == 48
    assert plan.windows[0] == w.Window(1, 30, 2)
    assert plan.covers(1440), "no gap and no duplicate, at the rung that invents its own folds"
    assert max(win.pages for win in plan.windows) <= CAP_PAGES_PER_WINDOW
    assert plan.parallel is True, "the fold carries nothing between windows (§5.2)"


def test_a_chapter_over_the_cap_is_folded_within_itself():
    """The other three refusals: an outline exists but one chapter is bigger than the cap.

    The chapter boundary is kept and the fold happens *inside* it, so the document stays at Level 1
    — its boundaries still come from its own structure, with the cap only subdividing.
    """
    plan = w.plan(80, toc=[{"page_no": 1}, {"page_no": 41}], size_bytes=1024, document="D")

    assert plan.level == 1
    assert [(win.start, win.end) for win in plan.windows] == [(1, 30), (31, 40),
                                                              (41, 70), (71, 80)]
    assert plan.covers(80)


def test_the_pilot_document_folds_into_the_windows_its_fixture_already_declares(pilot_expected):
    """The point of fixes/001: `TC1E-SF` is why M2b could not complete.

    55 pages with a single 55-page chapter — over the cap, so Level 0 is out, and the shipped rung
    refused it one step *before* the spend it was thought to be waiting on a credential for.
    ``data/fixtures/TC1E-SF/expected.json`` is normative and was written from the spec before any
    ingest; it declared these two windows all along. Asserted against the file rather than a
    literal, so the code and the acceptance table cannot drift apart again.
    """
    plan = w.plan(55, toc=[{"title": "Safety functions", "page_no": 1}], document="TC1E-SF")

    assert [[win.start, win.end] for win in plan.windows] == pilot_expected["window_ranges"]
    assert plan.covers(55)


def test_a_dense_outline_packs_instead_of_billing_one_call_per_page():
    """``ETC1AV81`` declares 8,187 bookmarks over 592 pages: 592 one-page windows, ~20 of work.

    The cap bounded a window above and nothing bounded it below. :data:`MIN_WINDOW_PAGES` is the
    floor, and it applies to the *chapter*, not to the accumulated window — see the next test.
    """
    plan = w.plan(592, toc=[{"page_no": n} for n in range(1, 593)], size_bytes=1024)

    assert len(plan.windows) == 20
    assert plan.covers(592)
    assert max(win.pages for win in plan.windows) <= CAP_PAGES_PER_WINDOW


def test_packing_leaves_chapters_that_are_already_the_right_size_alone():
    """The floor is on the merge, not a fill to the cap — and that distinction is Level 1 itself.

    Three 14-page chapters fit two-to-a-window under the cap, so filling greedily would return
    ``[(1, 28), (29, 42)]``: two calls instead of three, at the price of a fold **nobody chose**,
    sitting wherever 30 pages happened to land. That is precisely what §6.2 did not want, and a
    Level 1 that does it has taken its boundaries from the cap rather than from the document.
    """
    plan = w.plan(42, toc=[{"page_no": 1}, {"page_no": 15}, {"page_no": 29}], size_bytes=1024)

    assert [(win.start, win.end) for win in plan.windows] == [(1, 14), (15, 28), (29, 42)]
    assert w.pack(((1, 14), (15, 28), (29, 42)), 30) == ((1, 14), (15, 28), (29, 42))
    assert w.pack(((1, 4), (5, 8), (9, 12)), 30) == ((1, 12),), "small ones do fold together"


@pytest.mark.parametrize("page_count", [1, 2, 29, 30, 31, 55, 92, 592, 1440])
@pytest.mark.parametrize("shape", ["none", "whole", "dense", "mixed"])
def test_every_rung_covers_the_document_exactly_once(page_count, shape):
    """The one invariant no rung may break, over every rung and every chapter shape.

    Coverage is what makes a window a page range rather than a chunk: 1..N once each, no gap and
    no duplicate, and never a window over the cap. `impl`'s failure mode was a silent one-page
    hole, so this is asserted structurally rather than trusted.
    """
    tocs = {
        "none": [],
        "whole": [{"page_no": 1}],
        "dense": [{"page_no": n} for n in range(1, page_count + 1)],
        "mixed": [{"page_no": 1}, {"page_no": max(1, page_count // 2)}],
    }
    plan = w.plan(page_count, toc=tocs[shape], size_bytes=1024)

    assert plan.covers(page_count), f"{shape} at {page_count} pages does not tile the document"
    assert max(win.pages for win in plan.windows) <= CAP_PAGES_PER_WINDOW
    assert plan.level <= w.MAX_LADDER_LEVEL
    assert plan.parallel is True


def test_a_toc_entry_the_model_could_not_index_cuts_nothing():
    """A printed contents page shows printed labels, not PDF indices, so `page_no` comes back 0."""
    assert w.chapter_ranges([{"page_no": 0}, {"page_no": 999}], 42) == ()
    assert w.chapter_ranges([w.TocEntry(page_no=0), w.TocEntry(page_no=15)], 42) == ((1, 14),
                                                                                     (15, 42))


def test_the_fold_carries_no_state_between_its_windows():
    """Why Level 2 can exist here at all, asserted rather than argued (fixes/001).

    `impl`'s Level 2 had to run sequentially because its model reported section **extent** —
    *"batch 2 needs to know what batch 1 ended with"*. §5.2 deleted extent, so a window's only
    inputs are its own page range and the document; nothing a previous window produced reaches it.
    The observable form of that is :attr:`Plan.parallel`, true at every rung, and a ladder level
    that never exceeds the fold.
    """
    assert w.MAX_LADDER_LEVEL == 2
    folded = w.plan(1440)

    assert folded.parallel is True
    assert all(win.level == 2 and not win.bisected_from for win in folded.windows)
    # Each window is a function of its own range alone: rebuilding one in isolation reproduces it.
    assert folded.windows[7] == w.Window(211, 240, 2)


def test_the_level_two_refusal_is_retained_as_a_code_but_never_raised():
    """The class stays for the error taxonomy; nothing produces it any more (fixes/001).

    Deleting the code would be a breaking change for an operator already switching on
    ``ladder_level_2_required``. Leaving it unreachable is not — and it still belongs to the
    :class:`WindowError` family that `cli.py` catches, alongside ``window_unsplittable``.
    """
    assert w.LadderLevel2Required.code == "ladder_level_2_required"
    assert issubclass(w.LadderLevel2Required, w.WindowError)

    source = inspect.getsource(w.plan)
    assert "LadderLevel2Required" not in source, "plan() must not raise it any more"


# ── bisection (F13) ─────────────────────────────────────────────────────────────────────────────

def test_oversized_window_bisects(expected):
    """F13 — on MAX_TOKENS the window splits and re-bills. Never pad, never accept a partial.

    The page set is the invariant: the union of the halves is the original, with no gap and no
    duplicate, so the document is still covered exactly once.
    """
    plan = w.plan(42, toc=generator.toc_entries(), size_bytes=1024)
    oversized = plan.windows[1]

    after = plan.bisect(oversized, "max_tokens")

    assert len(after.windows) == len(plan.windows) + 1
    assert [(x.start, x.end) for x in after.windows] == [(1, 14), (15, 21), (22, 28), (29, 42)]
    assert after.page_numbers == plan.page_numbers
    assert after.covers(42)
    assert sorted(after.page_numbers) == list(dict.fromkeys(after.page_numbers))
    assert [x.bisected_from for x in after.windows] == ["", "max_tokens", "max_tokens", ""]


def test_a_bisected_window_re_bills(synthetic_pdf):
    """The halves get new keys for free: `extract_key` is built from the page image hashes."""
    probed = probe.run(synthetic_pdf)
    plan = w.plan(probed.page_count, toc=generator.toc_entries(), size_bytes=probed.size_bytes)
    parent = plan.windows[0]
    left, right = w.bisect_window(parent, "truncated")

    keys = {_key(synthetic_pdf, window, probed) for window in (parent, left, right)}
    assert len(keys) == 3


@pytest.mark.parametrize("reason", w.BISECT_REASONS)
def test_every_documented_trigger_bisects(reason):
    """§6.2 lists four: MAX_TOKENS, a truncated response, a schema-invalid one, and an offset
    failure. Each one splits and re-bills; none of them guesses."""
    left, right = w.bisect_window(w.Window(1, 30, 1), reason)

    assert (left.start, left.end, right.start, right.end) == (1, 15, 16, 30)
    assert left.bisected_from == right.bisected_from == reason


def test_a_trigger_the_spec_does_not_name_is_refused():
    with pytest.raises(ValueError):
        w.bisect_window(w.Window(1, 30, 1), "felt_like_it")


def test_window_unsplittable():
    """F13's floor: one page, still over budget. There is nothing left to split, and saying so is
    the only honest answer — padding it would publish a page the model never described."""
    with pytest.raises(w.WindowUnsplittable) as refusal:
        w.bisect_window(w.Window(7, 7, 1), "max_tokens")

    assert refusal.value.code == "window_unsplittable"
    assert refusal.value.details == {"page_no": 7, "reason": "max_tokens"}


def test_an_odd_window_bisects_without_losing_or_duplicating_a_page():
    left, right = w.bisect_window(w.Window(1, 25, 1), "offset")

    assert left.page_numbers + right.page_numbers == tuple(range(1, 26))


def test_bisecting_a_window_that_is_not_in_the_plan_is_a_programming_error():
    plan = w.plan(20, size_bytes=1024)

    with pytest.raises(ValueError):
        plan.bisect(w.Window(1, 5, 0), "max_tokens")


# ── the offset (§6.4) ───────────────────────────────────────────────────────────────────────────

def test_the_absolute_page_is_computed_in_exactly_one_place():
    """`abs_page = window.start + page_index - 1`, once, so no caller writes it again differently."""
    window = w.Window(15, 28, 1)

    assert window.absolute(1) == 15
    assert window.absolute(14) == 28
    assert [window.absolute(i) for i in range(1, window.pages + 1)] == list(window.page_numbers)


@pytest.mark.parametrize("page_index", [0, -1, 15])
def test_an_index_outside_the_window_raises_rather_than_clamping(page_index):
    """A clamp here shifts a citation onto a page the model never saw, and nothing else errors."""
    with pytest.raises(ValueError):
        w.Window(15, 28, 1).absolute(page_index)


def test_a_window_is_a_page_range_and_refuses_not_to_be():
    with pytest.raises(ValueError):
        w.Window(10, 9, 0)
    with pytest.raises(ValueError):
        w.Window(0, 5, 0)
