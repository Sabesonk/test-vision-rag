"""Level 2 — the fold at the cap, and the code that outlived the refusal (§6.2, fixes/001, U025).

Spec §13 M8 still reads *"attempting a Level-2 document fails with a typed
`ladder_level_2_required`"*. **That clause is superseded and §6.2 is where it was superseded**, in
the same document: *"`ladder_level_2_required` is retained as a code and no longer raised."* The
exclusion was measured rather than argued — keeping it refused 14 documents and 2,719 pages, 48 %
of the real corpus, including the pilot `TC1E-SF`, whose own `expected.json` had declared
`window_ranges: [[1, 30], [31, 55]]` all along.

So this file asserts the behaviour §6.2 specifies, and asserts the two things the old clause was
protecting:

* **the code still exists and is still in the taxonomy.** Deleting it would break an operator who
  is switching on it, which is why `fixes/001` kept the class after removing every raise;
* **nothing folds blind.** The old objection to `impl`'s Level 2 was a carry chain — *"batch 2
  needs to know what batch 1 ended with"* — and what removed the objection was §5.2 deleting
  section **extent** from the model. The fold is only safe because a section reassembles from
  presence alone (F8), so that is asserted here on the corpus that actually folds.

The corpus is `data/source/synthetic_large.pdf` (`vsir.eval.synthetic_large`), which declares no
contents page for exactly this reason. Nothing here needs Docker, a model or a key: `plan()` is
pure and the acceptance numbers are read from the fixture's `expected.json`, never computed from
the code under test (C10).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vsir.core import ids
from vsir.core.record import PageRecord, Provenance
from vsir.eval import synthetic_large
from vsir.ingest import derive as derive_module
from vsir.ingest import stitch as stitch_module
from vsir.ingest import window as window_module

REPO = Path(__file__).resolve().parents[3]
EXPECTED = json.loads(
    (REPO / "data" / "fixtures" / "synthetic_large" / "expected.json").read_text())


def planned() -> window_module.Plan:
    """The plan for the M8 corpus, from the corpus's own declared facts."""
    return window_module.plan(synthetic_large.PAGE_COUNT, toc=synthetic_large.TOC,
                              document=synthetic_large.DOC_STEM)


# ── the rung itself ──────────────────────────────────────────────────────────────────────────────

def test_a_document_with_no_contents_page_plans_at_ladder_level_2():
    """AC: a Level-2 document **plans**. It is not refused, and it is not cut blind.

    The numbers come from `expected.json`, which was written from §6.2's rule — fill before
    spill, at the cap — and not from asking `plan()` what it did.
    """
    plan = planned()

    assert plan.level == EXPECTED["ladder_level"] == 2
    assert [[w.start, w.end] for w in plan.windows] == EXPECTED["windows"]
    assert len(plan.windows) >= 3, "U025's acceptance wants at least three window checkpoints"


def test_every_level_2_window_is_within_the_cap_and_covers_the_document_once():
    """§6.2: *"every rung produces windows of at most the cap covering the document exactly once"*."""
    plan = planned()

    assert plan.covers(synthetic_large.PAGE_COUNT)
    assert all(window.pages <= window_module.CAP_PAGES_PER_WINDOW for window in plan.windows)
    assert all(window.level == 2 for window in plan.windows)


def test_the_fold_fills_before_it_spills_so_the_pilots_declared_ranges_reproduce():
    """The pilot's `[[1, 30], [31, 55]]`, reproduced exactly rather than approached.

    `data/fixtures/TC1E-SF/expected.json` declared those ranges from the spec before the ingest,
    and they are normative (C10). Fill-before-spill is what reproduces them; even parts would
    give `[[1, 28], [29, 55]]`, which is a different pair of model calls under different keys.
    """
    assert window_module.split_oversized(((1, 55),), 30) == ((1, 30), (31, 55))


def test_level_2_is_parallel_because_nothing_is_carried_between_its_windows():
    """The carry chain's reason left with `units[]`; the exclusion stayed behind (§6.2).

    Asserted structurally: a :class:`~vsir.ingest.window.Window` is a page range and a level, and
    it has no field naming a predecessor. There is nothing for window 2 to be told about window 1
    because §5.2 deleted section extent from the model's answer.
    """
    plan = planned()

    assert plan.parallel
    fields = set(vars(plan.windows[0]))
    assert fields == {"start", "end", "level", "bisected_from"}
    # `bisected_from` is §6.2's repair trigger, not a carry: it names why a window was split, and
    # the ladder's own windows carry it empty.
    assert all(window.bisected_from == "" for window in plan.windows)


def test_the_level_names_say_where_each_rungs_boundaries_came_from():
    """§6.2: the rungs *"differ only in where the boundaries come from"*, and the run record says.

    One table, read by the demo, so a level the printer had never heard of cannot be described as
    one it had — which is what a two-branch conditional did until this corpus reached Level 2.
    """
    assert window_module.LEVEL_NAMES[2] == "folded at the cap"
    assert len(window_module.LEVEL_NAMES) == window_module.MAX_LADDER_LEVEL + 1


# ── what the refusal was protecting ──────────────────────────────────────────────────────────────

def test_ladder_level_2_required_is_retained_as_a_code_and_never_raised():
    """fixes/001: deleting a code is a breaking change for a caller that handles it.

    The class stays in the :class:`~vsir.ingest.window.WindowError` family, keeps its code, and
    is raised nowhere in the tree. `window_unsplittable` remains the terminus of bisection (F13).
    """
    assert window_module.LadderLevel2Required.code == "ladder_level_2_required"
    assert issubclass(window_module.LadderLevel2Required, window_module.WindowError)

    source = (REPO / "backend" / "vsir").rglob("*.py")
    raising = [str(path.relative_to(REPO)) for path in source
               if "raise LadderLevel2Required" in path.read_text(encoding="utf-8")]
    assert raising == [], f"§6.2 says the code is retained and no longer raised: {raising}"

    assert window_module.WindowUnsplittable.code == "window_unsplittable"


def test_a_section_straddling_a_level_2_fold_reassembles_from_presence_alone():
    """F8 at the rung that needs it: two windows that never saw each other, one section.

    This is the whole safety argument for folding at the cap. `impl`'s Level 2 needed a carry
    chain because its model reported section **extent**; §5.2 deleted extent, so stitching
    computes ``(min, max)`` over per-page sightings and a section spanning a fold comes back as
    one section with one id. The corpus is built so this is not hypothetical —
    :data:`~vsir.eval.synthetic_large.AREA_PAGES` is coprime with the cap on purpose.
    """
    plan = planned()
    folds = {window.end for window in plan.windows[:-1]}

    straddling = [
        area for index, area in enumerate(synthetic_large.AREAS)
        if any(index * synthetic_large.AREA_PAGES < fold
               < min((index + 1) * synthetic_large.AREA_PAGES, synthetic_large.PAGE_COUNT)
               for fold in folds)
    ]
    assert straddling, "the corpus must have at least one section crossing a window fold"

    # Two sightings of one title, reported by two different windows, with nothing carried
    # between them — which is exactly what the frozen S2 responses of those two windows contain.
    title = straddling[0]
    first = min(fold for fold in folds
                if synthetic_large.area_of(fold) == title == synthetic_large.area_of(fold + 1))
    pages = [_sighting(title, page_no) for page_no in (first, first + 1)]
    stitched = stitch_module.stitch(pages, doc_id="synthetic-large", revision="1.3")

    assert len(stitched.sections) == 1
    section = stitched.sections[0]
    assert section.page_range == (first, first + 1)
    assert section.series_id == f"synthetic-large#s:{_slug(title)}"
    assert [page.section_id for page in stitched.pages] == [[section.section_id]] * 2


def _slug(title: str) -> str:
    return ids.slug(title).lower()


def _sighting(title: str, page_no: int) -> derive_module.DerivedPage:
    """One derived page carrying one section sighting — the shape step 08 consumes.

    The record is the minimum a page is: stitching only reads ``page_no`` and ``content.flags``
    off it and writes the ids back, so anything richer here would be decoration that could drift
    from what derivation really produces.
    """
    return derive_module.DerivedPage(
        record=PageRecord(
            doc_id="synthetic-large", revision="1.3", run_id="R-LEVEL2", page_no=page_no,
            has_text=True, text_trust="ok",
            text=" ".join(synthetic_large.expected_text(page_no)),
            provenance=Provenance(page_id=ids.page_id("synthetic-large", "1.3", page_no),
                                  run_id="R-LEVEL2"),
        ),
        sightings=(derive_module.SectionSighting(
            page_no=page_no, key=derive_module.section_key(title), title=title, is_start=False),),
    )


@pytest.mark.parametrize("page_count, expected_windows", [
    (30, 1),    # at the cap: Level 0, one window, no fold at all
    (31, 2),    # one over: the fold appears
    (60, 2),
    (61, 3),
    (150, 5),   # the corpus
])
def test_the_fold_is_a_function_of_the_cap_and_nothing_else(page_count, expected_windows):
    """No structure to cut on, so the cap is the only boundary there is — and it is the only one."""
    plan = window_module.plan(page_count, toc=(), document="unstructured")

    assert len(plan.windows) == expected_windows
    assert plan.covers(page_count)
    assert plan.level == (0 if page_count <= window_module.CAP_PAGES_PER_WINDOW else 2)
