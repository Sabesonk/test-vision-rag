"""L1 — derivation, the offset proof and stitching over the **real** `impl` windows (§12.1, U012).

Spec §12.1's ledger row is the reason this file exists: the ported old-schema responses are good
for *"real window structure and page counts, so L1 derivation, the offset proof (I4/F7) and
stitching are testable on real data at zero spend."* Everything here is that, and it costs nothing:
19 responses somebody already paid for, no PDF, no model, no network.

Real data is the point. `data/fixtures/synthetic_3window/` was written to contain the traps, so a
suite green against it is green against traps somebody thought of. These 142 pages contain what a
real corpus contains — a document cut into 12 windows at chapter boundaries, a 55-page document cut
at 30, a section that straddles a fold, a page with no text layer at all, and pages whose printed
labels are `Page 31 of 55`, `201.1`, `503.1` and `3 / 3` rather than integers.

The suite reads both of :func:`~vsir.eval.legacy.Baseline.extraction`'s readings and the difference
is deliberate — see that module's docstring. ``codes_from="window"`` is the faithful one and is
what the offset proof runs on; ``codes_from="export"`` is the parity corpus the L2 suites seed.
"""
from __future__ import annotations

import dataclasses
import io
import json
import sys

import pytest

from vsir import logging as vsir_logging
from vsir.core.exact import printed_in
from vsir.core.tok import tok
from vsir.eval import legacy
from vsir.ingest.derive import OffsetError, probe_texts
from vsir.ingest.extract import WindowExtraction, page_index_problem
from vsir.ingest.window import Window


@pytest.fixture(scope="module")
def baseline() -> legacy.Baseline:
    return legacy.load()


@pytest.fixture
def events():
    """The event stream as parsed JSON — the same capture idiom as `test_logging.py`.

    A tolerated §6.4 observation is *only* visible as a log line, so asserting on it needs the
    envelope the rest of the system reads, not a formatted string.
    """
    captured = io.StringIO()
    vsir_logging.configure(release_id="rel-test", level="DEBUG", stream=captured)
    yield lambda: [json.loads(line) for line in captured.getvalue().splitlines() if line.strip()]
    vsir_logging.configure(release_id="unknown", level="INFO", stream=sys.stdout)


# ── the windows are where the export says they are ──────────────────────────────────────────────

@pytest.mark.parametrize("doc_id", legacy.load().doc_ids)
def test_the_windows_tile_the_document_exactly_once(doc_id, baseline):
    """Every ported window placed, covering 1..pages with no gap and no overlap.

    The placement is recovered from `labels.jsonl`, never assumed — so this asserts the recovery
    as much as the tiling. `LTC1AV81` is the one that could go wrong: 12 windows, eleven of them a
    single page, which is 12! orderings if the evidence did not pin them.
    """
    placed = baseline.placements(doc_id)
    covered = [page for placement in placed for page in placement.window.page_numbers]

    assert covered == list(range(1, baseline.page_count(doc_id) + 1))
    assert len(placed) == len(baseline.window_paths(doc_id))


def test_the_twelve_windows_of_ltc1av81_are_in_the_order_the_export_records(baseline):
    """The hard case, named: eleven one-page windows and one of 23, placed by their evidence."""
    placed = baseline.placements("LTC1AV81")

    assert [(one.window.start, one.window.end) for one in placed] == [
        *[(page, page) for page in range(1, 12)], (12, 34)]


# ── §6.4 check (1), the structural one ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("doc_id", legacy.load().doc_ids)
def test_every_real_window_answered_about_the_pages_it_was_given(doc_id, baseline):
    """§6.4's structural check over real responses: the page indices are exactly 1..N, each once.

    This is also the *"never accept a partial window"* half of F13, and it is the one the ported
    responses can prove outright — a 30-page window that came back with 22 forms would have lost
    eight pages of a manual, and the count is in the file.
    """
    for extraction in baseline.extraction(doc_id, codes_from="window").windows:
        assert page_index_problem(extraction.out, extraction.window) == "", extraction.key


# ── §6.4 check (2), the independent observation ─────────────────────────────────────────────────

def test_derivation_over_the_two_real_windows_of_tc1e_sf(baseline):
    """55 pages across a fold at 30, both offset checks, and no page lost (I4, F7).

    `TC1E-SF` is §12.3's own document, and its page 1 is the one page whose verbatim text layer
    `impl` recorded — so check (2) here is a model-read label tested against text that was actually
    extracted from the sheet, not against a projection.
    """
    derived = baseline.derived("TC1E-SF", codes_from="window")

    assert len(derived.pages) == 55
    assert [page.page_no for page in derived.pages] == list(range(1, 56))
    assert derived.bisected == ()
    first = derived.page(1).record
    assert first.content.printed_page_no == "Page 1 of 55"
    assert first.content.label_verified is True


def test_derivation_over_the_twelve_real_windows_of_ltc1av81(baseline):
    """34 pages across eleven folds — the case a per-window derivation gets wrong quietly.

    Every window here is its own model call, so an off-by-one would not shift the document, it
    would put one page's reading on another page. The coverage assertion inside `derive` is what
    catches that, and this is it running on a real twelve-way cut.
    """
    derived = baseline.derived("LTC1AV81", codes_from="window")

    assert len(derived.pages) == 34
    assert [page.page_no for page in derived.pages] == list(range(1, 35))


def test_a_one_page_shift_of_a_real_window_is_caught_and_named(baseline):
    """The offset proof with teeth: move a real window by one page and §6.4 check (2) fires.

    The evidence is `impl`'s own recording of page 1 — the sheet prints ``Page 1 of 55``. Shift the
    first window down by one and the model's reading of that sheet lands on PDF page 2, whose text
    does not print the label while its neighbour does. That is the off-by-one signature, and the
    refusal names the check, the page and where the label really is rather than padding (F7).
    """
    extraction = baseline.extraction("TC1E-SF", codes_from="window")
    first, *rest = extraction.windows
    shifted = dataclasses.replace(
        extraction,
        windows=(WindowExtraction(window=Window(first.window.start + 1, first.window.end + 1,
                                                first.window.level),
                                  key=first.key, out=first.out, entry=first.entry), *rest),
    )

    with pytest.raises(OffsetError) as refusal:
        baseline.derived("TC1E-SF", extraction=shifted)

    assert refusal.value.code == "offset_check_failed"
    assert refusal.value.details["check"] == "independent_observation"
    assert refusal.value.details["page_no"] == 2
    assert refusal.value.details["label"] == "Page 1 of 55"
    assert refusal.value.details["printed_on"] == [1]


def test_the_eaton_projection_spells_a_label_on_a_neighbour_and_is_tolerated(baseline, events):
    """The lone-witness false positive fixes/002 exists for, on real ported data.

    `DS-5549-EATON` is three pages of IEC clause numbers — ``10.2.3.2``, ``10.2.3.3`` — and the
    observable projection joins them into one string. Qdrant's WORD tokenizer treats every
    separator alike, so those two identifiers put the tokens ``3 3`` side by side on page 2, and
    the phrase for page 3's printed label ``3 / 3`` is exactly ``[3, 3]``. Check (2) therefore sees
    page 3's label printed on page 2.

    It used to refuse the document for it. It no longer does, and the reason is not tolerance for
    its own sake: **page 1 confirms its own label**, which is direct evidence the window is
    aligned, and one stray numeral on a three-page datasheet cannot outvote it (§6.4, fixes/002).
    The observation is not swallowed either — it is logged as ``offset_singleton`` with the page
    and the neighbour, so a corpus sweep can still count these without re-running the check.

    The projection is still what is wrong here, not the check; U013's ingest of a real text layer
    is what removes the artefact rather than tolerating it.
    """
    derived = baseline.derived("DS-5549-EATON", codes_from="window")

    assert [page.page_no for page in derived.pages] == [1, 2, 3]

    singletons = [event for event in events() if event["event"] == "offset_singleton"]
    assert len(singletons) == 1, "the tolerated witness must leave exactly one trace"
    lone = singletons[0]
    assert lone["label"] == "3 / 3"
    assert lone["page_no"] == 3 and lone["printed_on"] == [2]
    assert lone["witnesses"] == 1 and lone["confirms_self"] >= 1


def test_a_real_shift_still_refuses_where_only_one_page_carries_a_legible_label(baseline):
    """The half of fixes/002 that must **not** be lost: sensitivity at one witness.

    `TC1E-SF`'s first window has all 30 labels, but 29 of them are printed nowhere in the ported
    projection — so a genuine one-page shift produces exactly **one** witness. A flat
    ``witnesses >= 2`` rule would accept it, and worse, would accept every half on the way down a
    bisection, so §6.2's terminus would be reached by agreeing with a shifted window rather than
    by naming a page.

    What separates this from the Eaton case is not the count. It is that **nothing confirms
    itself**: under a real shift no page can print the label the model read on it, which is §6.4's
    own argument for why one observation is as good as the twentieth.
    """
    extraction = baseline.extraction("TC1E-SF", codes_from="window")
    first, *rest = extraction.windows
    shifted = dataclasses.replace(
        extraction,
        windows=(WindowExtraction(window=Window(first.window.start + 1, first.window.end + 1,
                                                first.window.level),
                                  key=first.key, out=first.out, entry=first.entry), *rest),
    )

    with pytest.raises(OffsetError) as refusal:
        baseline.derived("TC1E-SF", extraction=shifted)

    assert refusal.value.details["check"] == "independent_observation"
    assert refusal.value.details["witnesses"] == 1
    assert refusal.value.details["confirms_self"] == 0


# ── §6.1 step 08 — stitching across a real fold ─────────────────────────────────────────────────

def test_a_section_straddling_a_real_window_fold_survives_it(baseline):
    """F8 on real data: two calls that never saw each other reported one section.

    `LTC1AV81`'s windows are single pages up to page 11, so a section covering pages 4 and 5 was
    reported by two separate model calls. Stitching has to recognise it as one section carrying
    both pages, because a scope filter on the other half would otherwise silently not return it.
    """
    stitched = baseline.stitched("LTC1AV81", codes_from="window")
    folds = {one.window.end for one in baseline.placements("LTC1AV81")}
    straddling = [section for section in stitched.sections
                  if any(min(section.pages) <= fold < max(section.pages) for fold in folds)]

    assert straddling, "no section of LTC1AV81 crosses a window fold"
    for section in straddling:
        pages = {page.page_no for page in stitched.pages
                 if section.section_id in page.section_id}
        assert pages == set(section.pages)


def test_every_ported_document_stitches_into_one_record_per_page(baseline):
    """Step 08 over the whole ported corpus: 142 pages, six documents, one record each."""
    records = baseline.records()

    assert len(records) == 142
    assert len({record.page_id for record in records}) == 142
    assert all(record.is_current for record in records)


# ── §6.5 — reattribution, on real sightings ─────────────────────────────────────────────────────

def test_two_withheld_codes_move_to_the_page_that_prints_them_and_say_so(baseline):
    """F6 on real data, and the one place the negative set and reattribution meet.

    ``F302`` and ``F313`` are two of the 96 codes the old run withheld from page 5 — its text layer
    did not back them. Page 4's does. So the sighting moves, the receiving page records
    ``moved_from`` naming page 5, and the code is still `verified: false` wherever it ends up
    because it reaches nothing but ``vlm_codes``. `impl` had no such repair: the code stayed on
    page 5, unbacked, and the citation would have named the wrong sheet.
    """
    derived = baseline.derived("TC1E-PERIODIC")
    moved = {(move.code, move.from_page_no, move.to_page_no) for move in derived.moves}

    assert moved == {("F302", 5, 4), ("F313", 5, 4)}
    receiving = derived.page(4).record.content
    assert {code.code for code in receiving.moved_from} == {"F302", "F313"}
    assert {code.from_page_id for code in receiving.moved_from} == {"TC1E-PERIODIC@1.1#p005"}
    assert "codes_reattributed" in receiving.flags


# ── I2, over the ported responses ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("doc_id", legacy.load().doc_ids)
def test_i2_the_projection_reaches_the_record_unchanged(doc_id, baseline):
    """§12.1 requires the same L1 suite over the ported responses, and this is its central one.

    For every page, ``record.text`` is what the probe supplied and nothing else — no summary
    appended, no code list joined on. Here the probe supplies the observable projection rather than
    PyMuPDF's extraction, so what is proved is the *step*: derivation carries text through
    untouched whatever produced it, which is exactly what makes a code the model invented
    unfindable by `lookup` (F14).
    """
    derived = baseline.derived(doc_id)
    texts = probe_texts(baseline.probe(doc_id))

    for page in derived.pages:
        assert page.record.text == texts[page.page_no]
    assert all(page.record.text == "" for page in derived.pages) == (not baseline.has_text_layer(doc_id))


def test_no_withheld_code_reaches_the_text_of_any_record(baseline):
    """The whole of I2 over 96 real model-emitted codes and 142 real records.

    Asked as a **phrase**, because that is the only question the exact surface answers: a substring
    test would report ``Q5`` present on a page printing ``Q59``, which is F1 in miniature and the
    reason `MatchPhrase` over `tok()` is the mechanism rather than `in`.

    Every one of the 96 is carried on some page's ``codes`` — the model did say them, and D3's
    opt-in surface is where a model's word goes — and none of them is *printed* on the page it was
    withheld from, because nothing but the probe writes ``text``.
    """
    records = {record.page_id: record for record in baseline.records()}

    for page_id, raw in baseline.withheld():
        assert not printed_in(tok(records[page_id].text), raw)
        carriers = [record for record in records.values() if raw in record.content.codes]
        assert carriers, f"{raw} was withheld from {page_id} and is on no page's codes"
        assert all(raw in record.vlm_codes for record in carriers)
