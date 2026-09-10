"""L0/L1 — the offset proof (Spec §6.4, I4, F7, AC-006).

*"A wrong offset shifts every page, citation and summary and nothing else errors — this is the
single most dangerous line in the pipeline."* `impl` had no test on it at all (register E6), and
its only guard logged a warning and **dropped** the page, which turns a shifted window into a
silent hole in a manual.

So both of §6.4's checks get their own tests, and the second one gets the case that matters: the
window really is shifted by one page and the model's own labels are what give it away.

Run this unit's slice:
    bash scripts/test-unit.sh -k "derive or grounded_rate or labels or reattribution or stitch \
        or i2_text_provenance"
"""
from __future__ import annotations

import dataclasses

import pytest

from vsir.ingest import derive as dv
from vsir.ingest.window import Window, WindowUnsplittable


def _shift(extraction, by: int):
    """The same response, told it covers a window ``by`` pages along. The off-by-one, made real."""
    window = extraction.window
    return dataclasses.replace(
        extraction,
        window=Window(window.start + by, window.end + by, window.level))


def _misaligned(extraction, by: int = 1):
    """The window is right; the **response** describes the pages one along.

    This is how the failure actually arises in production — the plan is authoritative, so
    `window.start` is not what goes wrong. What goes wrong is that the model answered about a
    different set of sheets than the ones it was handed, and every label it read comes off the
    neighbouring page. Coverage still holds, so the *only* thing that can notice is §6.4's
    second check.
    """
    forms = list(extraction.out.pages)
    labels = [form.printed_page_no for form in forms]
    moved = [form.model_copy(update={"printed_page_no": labels[(index + by) % len(labels)]})
             for index, form in enumerate(forms)]
    return dataclasses.replace(extraction,
                               out=extraction.out.model_copy(update={"pages": moved}))


def _drop_a_page(extraction):
    out = extraction.out
    return dataclasses.replace(extraction, out=out.model_copy(update={"pages": out.pages[:-1]}))


# ── check (1): structural ───────────────────────────────────────────────────────────────────────

def test_the_structural_check_passes_on_every_window_of_the_corpus(derived, extracted):
    """AC: the sound corpus passes, which is what makes a failure elsewhere meaningful."""
    _doc, probed, _facts, _plan, extraction = extracted

    for window in extraction.windows:
        dv.check_offset(window, probed)          # raises if it does not hold
    assert len(derived.pages) == probed.page_count


def test_a_window_missing_a_page_form_is_an_offset_error(extracted):
    """AC: a `page_index` set that is not exactly `1..window.pages` raises `OffsetError`.

    A 30-page window that comes back with 29 forms has lost a page of a manual, and every later
    step would read as a success (F13).
    """
    _doc, probed, _facts, _plan, extraction = extracted

    with pytest.raises(dv.OffsetError) as refusal:
        dv.check_offset(_drop_a_page(extraction.windows[0]), probed)

    assert refusal.value.code == "offset_check_failed"
    assert refusal.value.details["check"] == "structural"
    assert refusal.value.details["reason"] == dv.OFFSET


def test_a_duplicated_page_index_is_an_offset_error(extracted):
    _doc, probed, _facts, _plan, extraction = extracted
    one = extraction.windows[0]
    doubled = one.out.model_copy(update={"pages": [one.out.pages[0], *one.out.pages[1:-1],
                                                   one.out.pages[0]]})

    with pytest.raises(dv.OffsetError):
        dv.check_offset(dataclasses.replace(one, out=doubled), probed)


# ── check (2): the independent observation ──────────────────────────────────────────────────────

def test_a_window_shifted_by_one_page_is_caught_by_its_own_labels(extracted):
    """AC: the model-read `printed_page_no` phrase-matches a **neighbour's** text → `OffsetError`.

    This is the whole point of the second check. The structural check cannot see this failure:
    the indices are a perfect `1..N`, every form resolves, nothing is missing. The only witness
    is the page itself, which prints a different number than the model read off it.
    """
    _doc, probed, _facts, _plan, extraction = extracted
    shifted = _shift(extraction.windows[1], 1)

    with pytest.raises(dv.OffsetError) as refusal:
        dv.check_offset(shifted, probed)

    details = refusal.value.details
    assert details["check"] == "independent_observation"
    assert details["page_index"] == 1
    assert details["page_no"] == shifted.window.start
    # The neighbour that really prints the label is named, because "off by one which way?" is the
    # first question an operator asks.
    assert details["printed_on"] == [shifted.window.start - 1]
    assert details["label"] == "13"


@pytest.mark.parametrize("by", [1, -1])
def test_a_shift_in_either_direction_is_caught(extracted, by):
    """Both directions, and **only** ±1 — which is the whole rule §6.4 states.

    A larger shift cannot survive to be observed here: it would make two windows claim the same
    pages, and `derive` asserts the derived page set is exactly `1..page_count`. That assertion
    is why the neighbour band does not have to widen into a document-wide search, which would
    raise on any page whose printed label happens to be mentioned somewhere else in the binder.
    """
    _doc, probed, _facts, _plan, extraction = extracted

    with pytest.raises(dv.OffsetError):
        dv.check_offset(_shift(extraction.windows[1], by), probed)


def test_a_shift_large_enough_to_escape_the_neighbour_band_collides_instead(extracted):
    """The other half of that argument, asserted: a big shift fails on coverage, not on luck."""
    doc, probed, _facts, _plan, extraction = extracted
    collided = dataclasses.replace(
        extraction, windows=(extraction.windows[0], _shift(extraction.windows[2], -28),
                             extraction.windows[2]))

    with pytest.raises(dv.OffsetError) as refusal:
        dv.derive(collided, probed=probed, doc=doc)

    assert refusal.value.details["check"] == "coverage"


def test_a_page_with_no_text_layer_cannot_witness_the_offset(extracted):
    """§6.4 — the check needs a text layer to check against, and says nothing without one.

    Pages 1-2 of the corpus are scanned. The model reports no label for them, and even if it did
    there would be nothing to compare it with: `offset_observation` returns empty rather than
    inventing a verdict, which is the same refusal `verify` makes for such a page (§5.7).
    """
    _doc, probed, _facts, _plan, extraction = extracted
    window = extraction.windows[0]
    scanned = next(form for form in window.out.pages
                   if window.window.absolute(form.page_index) == 1)

    assert not probed.page(1).has_text
    assert dv.offset_observation(scanned, 1, probed) == ()
    # Even a confidently wrong label on a page with no text layer is not evidence of a shift.
    invented = scanned.model_copy(update={"printed_page_no": "13"})
    assert dv.offset_observation(invented, 1, probed) == ()


def test_a_label_printed_nowhere_is_a_misread_not_a_shift(extracted):
    """A label on neither this page nor its neighbours is the model misreading one page.

    Bisecting on that would re-bill a window over a single bad reading, and re-billing would not
    change it. The label simply comes back unverified (§6.5) — the disclosure, not the refusal.
    """
    _doc, probed, _facts, _plan, extraction = extracted
    window = extraction.windows[1]
    form = window.out.pages[3].model_copy(update={"printed_page_no": "ZZ-999"})

    assert dv.offset_observation(form, window.window.absolute(form.page_index), probed) == ()


# ── the repair: bisect and re-bill (§6.2, F13) ──────────────────────────────────────────────────

def test_without_a_way_to_re_bill_the_offset_error_reaches_the_caller(extracted):
    """AC: **no record is emitted for the shifted window.** With no `reextract`, nothing is."""
    doc, probed, _facts, _plan, extraction = extracted
    bad = dataclasses.replace(
        extraction, windows=(extraction.windows[0], _misaligned(extraction.windows[1]),
                             extraction.windows[2]))

    with pytest.raises(dv.OffsetError) as refusal:
        dv.derive(bad, probed=probed, doc=doc)

    assert refusal.value.details["check"] == "independent_observation"


def test_an_offset_failure_bisects_the_window_and_re_derives_the_halves(extracted):
    """AC: the window bisects, and the misaligned response contributes no record of its own.

    The stand-in for step 06 answers each half correctly — which is what a re-billed call does
    when the first response was the model's mistake. What is asserted is the *shape* of the
    repair: two halves, each with its own receipt, and not one page of the document derived from
    the response that failed the check (§6.2, §6.3, F13).
    """
    doc, probed, _facts, _plan, extraction = extracted
    good = extraction.windows[1]
    bad = dataclasses.replace(
        extraction, windows=(extraction.windows[0], _misaligned(good), extraction.windows[2]))
    asked: list[tuple[int, int]] = []

    def reextract(window):
        """The correct answer for one half, renumbered to that half's own `page_index` space."""
        asked.append((window.start, window.end))
        renumbered = [
            form.model_copy(update={
                "page_index": good.window.absolute(form.page_index) - window.start + 1})
            for form in good.out.pages
            if window.start <= good.window.absolute(form.page_index) <= window.end
        ]
        return (dataclasses.replace(good, window=window,
                                    out=good.out.model_copy(update={"pages": renumbered}),
                                    key=f"re-billed-{window.start}-{window.end}"),)

    derivation = dv.derive(bad, probed=probed, doc=doc, reextract=reextract)

    assert asked == [(15, 21), (22, 28)]
    assert derivation.bisected == ((15, 28),)
    assert [page.page_no for page in derivation.pages] == list(range(1, probed.page_count + 1))
    # The failed response's receipt is on no page: the halves replaced it entirely (§6.3).
    keys = {page.record.provenance.extract_key for page in derivation.pages}
    assert good.key not in keys
    assert {"re-billed-15-21", "re-billed-22-28"} <= keys


def test_bisection_bottoms_out_at_one_page_rather_than_looping(extracted):
    """§6.2's terminus: a half that fails the same way is split again, down to one named page.

    There is no depth counter anywhere in this path, and there must not be: §6.2 names the page,
    not a recursion limit, as the thing an operator is told about.
    """
    doc, probed, _facts, _plan, extraction = extracted
    good = extraction.windows[1]
    bad = dataclasses.replace(
        extraction, windows=(extraction.windows[0], _misaligned(good), extraction.windows[2]))

    def reextract(window):
        """Re-billing changes nothing: the model reads the next sheet's label every time.

        Taken from the probe's own label table rather than by rotating the window's forms, so
        the answer is still wrong when the window is down to a single page — which is the case
        that has to reach the terminus rather than accidentally coming out right.
        """
        renumbered = [
            form.model_copy(update={
                "page_index": good.window.absolute(form.page_index) - window.start + 1,
                "printed_page_no": probed.page(
                    min(good.window.absolute(form.page_index) + 1, probed.page_count)).label,
            })
            for form in good.out.pages
            if window.start <= good.window.absolute(form.page_index) <= window.end
        ]
        return (dataclasses.replace(good, window=window,
                                    out=good.out.model_copy(update={"pages": renumbered})),)

    with pytest.raises(WindowUnsplittable) as refusal:
        dv.derive(bad, probed=probed, doc=doc, reextract=reextract)

    assert refusal.value.code == "window_unsplittable"
    assert refusal.value.details["page_no"] >= good.window.start
