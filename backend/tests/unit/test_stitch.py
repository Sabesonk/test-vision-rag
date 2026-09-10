"""L0/L1 — stitching, and the window fold that leaves no trace (Spec §6.1 step 08, §5.1, F8).

F8 is *"searches a subset believing it searched the chapter"*, and a window fold is how it
happens: the model on one side of the cut cannot see the other, so a section split by the fold
comes back as two piles of one-page sightings. This step has to make them one section, and put
**one** `section_id` on every page of it.

The corpus is cut at 14|15 and 28|29 and has two sections deliberately laid across those cuts —
`Emergency stop chain` on pages 13-17 and `Light curtain muting` on 27-31.

Two `impl` defects are asserted *against* here rather than ported: a contested start reported as
certain (guide 07 §7.1), and a `page_range` that claims pages nothing was observed on.
"""
from __future__ import annotations

import pytest

from vsir.ingest.derive import DerivedPage, SectionSighting, section_key
from vsir.ingest.stitch import FLAG_INTERPOLATED_START, FLAG_NONCONTIGUOUS, Section, stitch

DOC, REV = "TC1E-SF", "1.3"


def _page(page_no: int, *sightings, doc_id: str = DOC, revision: str = REV) -> DerivedPage:
    """A derived page carrying nothing but its section sightings — this step reads nothing else."""
    from vsir.core.record import PageRecord, Provenance

    record = PageRecord(
        doc_id=doc_id, revision=revision, page_no=page_no,
        provenance=Provenance(page_id=f"{doc_id}@{revision}#p{page_no:03d}"))
    return DerivedPage(
        record=record,
        sightings=tuple(SectionSighting(page_no=page_no, title=title, key=section_key(title),
                                        is_start=is_start)
                        for title, is_start in sightings))


# ── the fold ────────────────────────────────────────────────────────────────────────────────────

def test_straddling_section_one_section_id_across_fold(stitched, expected):
    """AC, and the F8 row: one `section_id` on every page of a section the fold cut in two."""
    folds = [end for _start, end in expected["windows"][:-1]]
    straddling = {section.title: section for section in stitched.sections
                  if any(section.page_range[0] <= fold < section.page_range[1] for fold in folds)}

    assert sorted(straddling) == sorted(expected["straddling_sections"])
    for section in straddling.values():
        pages = [record for record in stitched.pages
                 if section.section_id in record.section_id]
        low, high = section.page_range
        assert [record.page_no for record in pages] == list(range(low, high + 1))
        # One id, on both sides of the cut: the fold left no trace.
        assert {tuple(record.section_id) for record in pages} == {(section.section_id,)}


def test_two_windows_that_never_saw_each_other_produce_one_section():
    """The mechanism, in isolation: sightings merge on the canonical key, not on adjacency."""
    result = stitch([_page(13, ("Emergency stop chain", True)),
                     _page(14, ("Emergency stop chain", False)),      # ← window 1 ends here
                     _page(15, ("Emergency stop chain", False)),      # ← window 2 begins here
                     _page(16, ("Emergency stop chain", False))],
                    doc_id=DOC, revision=REV)

    assert len(result.sections) == 1
    assert result.sections[0].page_range == (13, 16)
    assert result.sections[0].start_page == 13
    assert result.sections[0].start_uncertain is False


def test_the_same_section_spelled_differently_by_two_windows_is_still_one_section():
    """Two calls, two transcriptions. The canonical key is what says they are the same thing."""
    result = stitch([_page(13, ("Emergency Stop Chain", True)),
                     _page(14, ("emergency stop chain", False))],
                    doc_id=DOC, revision=REV)

    assert len(result.sections) == 1
    assert result.sections[0].key == "emergency-stop-chain"
    assert result.sections[0].title == "Emergency Stop Chain"     # the first non-empty one


# ── the arrays (§5.3) ───────────────────────────────────────────────────────────────────────────

def test_a_page_in_two_sections_carries_both_ids():
    """AC: a straddling page's `section_id` array has **both** its sections.

    A single scalar per page would force this page to pick one, and a scope filter on the other
    would silently not return it — which is F8 from the other direction.
    """
    result = stitch([_page(1, ("Guard door interlocks", True)),
                     _page(2, ("Guard door interlocks", False), ("Light curtain muting", True)),
                     _page(3, ("Light curtain muting", False))],
                    doc_id=DOC, revision=REV)
    middle = next(record for record in result.pages if record.page_no == 2)

    assert len(middle.section_id) == 2
    assert len(middle.series_id) == 2
    assert {section.section_id for section in result.sections} == set(middle.section_id)
    assert [section.title for section in middle.content.sections] == ["Guard door interlocks",
                                                                      "Light curtain muting"]


def test_a_page_in_no_section_carries_empty_arrays_and_is_still_a_page():
    """There is no `class_totality` page-unit here (§2.4). A page needs no section to exist."""
    result = stitch([_page(1), _page(2, ("Front matter", True))], doc_id=DOC, revision=REV)
    orphan = next(record for record in result.pages if record.page_no == 1)

    assert orphan.section_id == []
    assert orphan.series_id == []
    assert orphan.content.sections == []
    assert len(result.pages) == 2


# ── ids ─────────────────────────────────────────────────────────────────────────────────────────

def test_ordinals_follow_the_first_page_so_ids_are_reproducible():
    result = stitch([_page(9, ("Second", True)), _page(1, ("First", True)),
                     _page(5, ("Middle", True))], doc_id=DOC, revision=REV)

    assert [section.section_id for section in result.sections] == [
        f"{DOC}@{REV}#s001", f"{DOC}@{REV}#s002", f"{DOC}@{REV}#s003"]
    assert [section.title for section in result.sections] == ["First", "Middle", "Second"]


def test_series_id_carries_no_revision_so_a_scope_survives_one(stitched):
    """§5.1, F8 — `section_id` dies at the next revision; `series_id` is the point of the pair."""
    for section in stitched.sections:
        assert "@" not in section.series_id
        assert section.series_id.endswith(f"#s:{section.key}")
        assert section.section_id.startswith(f"{section.series_id.split('#')[0]}@")


def test_the_same_section_keeps_its_series_id_across_a_revision():
    """U025 asserts this end to end; the id it will assert on is minted here."""
    old = stitch([_page(3, ("Emergency stop chain", True), revision="1.2")],
                 doc_id=DOC, revision="1.2")
    new = stitch([_page(4, ("Emergency stop chain", True), revision="1.3")],
                 doc_id=DOC, revision="1.3")

    assert old.sections[0].series_id == new.sections[0].series_id
    assert old.sections[0].section_id != new.sections[0].section_id


# ── the two `impl` defects, not ported ──────────────────────────────────────────────────────────

def test_a_contested_start_is_uncertain_rather_than_the_first_one_seen():
    """`impl` took the first `is_head` and reported it certain — even with four claims.

    A section four pages each call the beginning is arguably *less* certain than one no page
    claims, and `expand()` read exactly that flag to decide whether to degrade honestly.
    """
    result = stitch([_page(17, ("Periodic check list", True)),
                     _page(18, ("Periodic check list", True)),
                     _page(19, ("Periodic check list", False)),
                     _page(20, ("Periodic check list", True))],
                    doc_id=DOC, revision=REV)
    section = result.sections[0]

    assert section.start_uncertain is True
    assert section.start_page == 17          # still the earliest claim — but never called certain
    assert all(FLAG_INTERPOLATED_START in record.content.flags for record in result.pages)


def test_a_section_no_page_claims_the_start_of_is_also_uncertain():
    result = stitch([_page(5, ("Wiring", False)), _page(6, ("Wiring", False))],
                    doc_id=DOC, revision=REV)

    assert result.sections[0].start_uncertain is True
    assert result.sections[0].start_page == 5


def test_a_gap_inside_the_span_is_disclosed_not_smoothed_over():
    """`page_range` is a range and `pages` is a set; keeping both is what stops a false claim."""
    result = stitch([_page(17, ("Periodic check list", True)),
                     _page(18, ("Periodic check list", False)),
                     _page(20, ("Periodic check list", False))],
                    doc_id=DOC, revision=REV)
    section = result.sections[0]

    assert section.pages == (17, 18, 20)
    assert section.page_range == (17, 20)
    assert section.contiguous is False
    assert all(FLAG_NONCONTIGUOUS in record.content.flags for record in result.pages)
    # Page 19 never reported the section, so it is not in it — the range does not put it there.
    assert [record.page_no for record in result.pages] == [17, 18, 20]


def test_is_start_is_written_on_the_resolved_start_page_only():
    result = stitch([_page(17, ("Periodic check list", True)),
                     _page(18, ("Periodic check list", True))],
                    doc_id=DOC, revision=REV)

    starts = {record.page_no: record.content.sections[0].is_start for record in result.pages}
    assert starts == {17: True, 18: False}


# ── on the corpus ───────────────────────────────────────────────────────────────────────────────

def test_the_corpus_stitches_to_the_sections_the_fixture_records(stitched, expected):
    observed = [{"first": section.page_range[0], "last": section.page_range[1],
                 "title": section.title} for section in stitched.sections]

    assert observed == expected["sections"]
    assert all(section.contiguous for section in stitched.sections)
    assert all(not section.start_uncertain for section in stitched.sections)


def test_every_page_of_the_corpus_ends_up_in_exactly_one_section(stitched):
    assert all(len(record.section_id) == 1 for record in stitched.pages)
    assert len(stitched.pages) == 42


def test_stitching_changes_nothing_a_page_already_carried(stitched, derived):
    """Step 08 adds ids. It must not touch `text`, the codes, the label or the health signals."""
    before = {page.page_no: page.record for page in derived.pages}

    for record in stitched.pages:
        was = before[record.page_no]
        assert record.text == was.text
        assert record.content.codes == was.content.codes
        assert record.content.codes_in_text == was.content.codes_in_text
        assert record.content.grounded_rate == was.content.grounded_rate
        assert record.content.printed_page_no == was.content.printed_page_no
        assert record.is_current is False


@pytest.mark.parametrize("title", ["", "   ", "///"])
def test_a_section_with_no_usable_title_is_not_a_section(title):
    """`section_key` of an empty title is empty, and an empty key cannot address anything."""
    assert section_key(title) == ""
    assert stitch([_page(1, (title, True))], doc_id=DOC, revision=REV).sections == ()
