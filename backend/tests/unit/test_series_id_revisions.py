"""`series_id` across a revision boundary — F8's third part, closed at M8 (§5.1, §5.3, U025).

`section_id` carries the revision (`TC1E-SF@1.3#s007`), so a scope expressed with one dies the
moment a new revision publishes: the pages are still there, the chapter is still the same chapter,
and a filter written yesterday silently returns nothing. That is F8 — *"searches a subset believing
it searched the chapter"* — arriving through time rather than through a window fold.

`series_id` is the repair, and it is a repair by **grammar** rather than by bookkeeping: it is
`{doc_id}#s:{canonical key}` and there is no revision in it to go stale. Nothing has to be
migrated when 1.4 publishes, because 1.4 mints the same string 1.3 did from the same section
title.

The two halves asserted here are the ones that can be asserted without a store:

* **the id is stable.** Same document, same section, two revisions, one `series_id` — and the
  `section_id`s differ, because if they did not the two revisions would be indistinguishable in
  a scope and F12's retirement would have nothing to act on.
* **the id is an array on the page**, so a page straddling two sections is in scope for either
  (§5.3). A scalar would force a straddling page to pick one section, and the scope filter on the
  other one would silently not return it.

The store-backed half — a `series_id` scope returning pages from **both** revisions where a
`section_id` scope returns one — is `tests/api/test_revision_lifecycle.py`, because it is a
statement about what is in an index.
"""
from __future__ import annotations

import pytest

from vsir.core import ids
from vsir.core.record import PageRecord, Provenance
from vsir.ingest import derive as derive_module
from vsir.ingest import stitch as stitch_module

DOC = "TC1E-SF"
OLD, NEW = "1.3", "1.4"

#: The same chapter, spelled the way two different windows of two different revisions might
#: spell it. `derive.section_key` is what makes them one key, and it is the *only* thing that
#: does: there is no title similarity anywhere in this system (§2.2, F1).
TITLE = "Emergency stop chain"
RESPELLED = "EMERGENCY STOP CHAIN"


def page(page_no: int, revision: str, *titles: str) -> derive_module.DerivedPage:
    """One derived page sighted in each of ``titles``. The shape step 08 consumes."""
    return derive_module.DerivedPage(
        record=PageRecord(
            doc_id=DOC, revision=revision, run_id=f"R-{revision}", page_no=page_no,
            has_text=True, text_trust="ok", text=f"page {page_no} of {DOC} rev {revision}",
            provenance=Provenance(page_id=ids.page_id(DOC, revision, page_no),
                                  run_id=f"R-{revision}"),
        ),
        sightings=tuple(
            derive_module.SectionSighting(page_no=page_no, key=derive_module.section_key(title),
                                          title=title, is_start=(index == 0 and page_no == 1))
            for index, title in enumerate(titles)),
    )


def test_series_id_stable_across_revisions():
    """F8's third part: the same section in 1.3 and 1.4 has the **same** `series_id`.

    And a different `section_id`, which is the other half of the same requirement — retirement
    acts on `(doc_id, revision)` (§6.7), so the two revisions have to be distinguishable by the
    id that carries the revision while remaining addressable by the one that does not.
    """
    old = stitch_module.stitch([page(1, OLD, TITLE), page(2, OLD, TITLE)],
                               doc_id=DOC, revision=OLD)
    new = stitch_module.stitch([page(1, NEW, TITLE), page(2, NEW, TITLE), page(3, NEW, TITLE)],
                               doc_id=DOC, revision=NEW)

    assert old.sections[0].series_id == new.sections[0].series_id == f"{DOC}#s:emergency-stop-chain"
    assert old.sections[0].section_id != new.sections[0].section_id
    assert "@" not in old.sections[0].series_id


def test_series_id_survives_a_respelling_because_the_canonical_key_is_what_it_is_built_from():
    """1.4 shouts the heading in capitals. It is the same chapter and it keeps the same id.

    Not fuzzy matching, and the distinction matters (F1, §2.2): `derive.section_key` is
    `slug().lower()`, a **normalisation**, so two titles either produce the same key or they do
    not. Nothing here scores a similarity, and a one-character difference in the words produces a
    different section rather than a close one.
    """
    old = stitch_module.stitch([page(1, OLD, TITLE)], doc_id=DOC, revision=OLD)
    new = stitch_module.stitch([page(1, NEW, RESPELLED)], doc_id=DOC, revision=NEW)

    assert old.sections[0].series_id == new.sections[0].series_id
    assert derive_module.section_key(TITLE) == derive_module.section_key(RESPELLED)


def test_series_id_differs_the_moment_the_section_really_differs():
    """The guard on the test above: a *different* chapter is a different series, not a near one."""
    stitched = stitch_module.stitch(
        [page(1, NEW, TITLE), page(2, NEW, "Emergency stop chains")], doc_id=DOC, revision=NEW)

    assert len({section.series_id for section in stitched.sections}) == 2


def test_series_id_is_per_document_so_two_documents_never_share_a_section():
    """`{doc_id}#s:{key}` — the document is in the grammar, so a shared heading is not a shared
    section. Two manuals both have an *"Emergency stop chain"*; scoping to one must not return
    the other's pages."""
    mine = stitch_module.stitch([page(1, OLD, TITLE)], doc_id=DOC, revision=OLD)
    theirs = ids.series_id("OTHER-DOC", derive_module.section_key(TITLE))

    assert mine.sections[0].series_id != theirs


def test_series_id_is_a_keyword_array_on_every_page_it_covers():
    """§5.3, F8's other half: a straddling page carries **both**, so either scope returns it."""
    stitched = stitch_module.stitch(
        [page(1, NEW, TITLE), page(2, NEW, TITLE, "Guard door interlocks"),
         page(3, NEW, "Guard door interlocks")], doc_id=DOC, revision=NEW)

    straddling = stitched.pages[1]
    assert len(straddling.series_id) == len(straddling.section_id) == 2
    assert isinstance(straddling.series_id, list)
    assert set(straddling.series_id) == {f"{DOC}#s:emergency-stop-chain",
                                         f"{DOC}#s:guard-door-interlocks"}


def test_a_page_carries_the_series_id_of_every_revision_it_is_in_and_no_other():
    """The pages of 1.3 keep 1.3's `section_id` after 1.4 publishes — nothing is rewritten.

    Retirement demotes the older revision's points and **keeps** them (§6.7 clause 2, F9); it
    does not migrate their ids. So a 1.3 page's `section_id` still names 1.3, and the only thing
    that reaches across the boundary is the `series_id` both revisions minted independently.
    """
    old = stitch_module.stitch([page(1, OLD, TITLE)], doc_id=DOC, revision=OLD)
    new = stitch_module.stitch([page(1, NEW, TITLE)], doc_id=DOC, revision=NEW)

    assert old.pages[0].section_id == [f"{DOC}@{OLD}#s001"]
    assert new.pages[0].section_id == [f"{DOC}@{NEW}#s001"]
    assert old.pages[0].series_id == new.pages[0].series_id


@pytest.mark.parametrize("key", ["", "   ", "---", "!!"])
def test_a_title_that_addresses_nothing_mints_no_series_id(key):
    """A heading with no alphanumeric character has no key to merge on, so there is no id to mint.

    :func:`vsir.core.ids.series_id` raises rather than returning `"DOC#s:"`, which would be one
    id shared by every untitled section in the document — a scope that quietly widened to all of
    them. Stitching drops such sightings before they reach here (see `_merge`).
    """
    with pytest.raises(ValueError):
        ids.series_id(DOC, key)
