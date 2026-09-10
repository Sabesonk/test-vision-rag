"""Step 08 — stitching. Where the window folds are deleted again (§6.1, F8).

Ported from ``impl/app/stitch.py`` and **retargeted from units to sections**, which is the same
algorithm over a different noun: `impl` merged ``Unit`` sightings keyed by an identifier grammar,
this merges section sightings keyed by the canonical form of the model's own title. The grammar is
struck (C1) and the key is `derive.section_key` — a slug, no taxonomy, no keyword list.

**Why it is the only place extent is created.** §5.2 forbids the model from reporting how far a
section reaches, and the reason is structural rather than stylistic: a window fold can cut through
a section, and the call on one side of the fold cannot see the other, so any span it gave would be
a guess made confidently. Presence per page is a thing a model can actually see. Extent is
``(min, max)`` over sightings, and it cannot be computed until every window has returned —

    window 1 (1-14):   "Emergency stop chain" on 13, 14
    window 2 (15-28):  "Emergency stop chain" on 15, 16, 17
    here:              one section, pages 13-17, one section_id on all five

Two separate calls that never saw each other, reassembled by sorting page numbers. **That is what
makes cutting the document safe**, and F8 is what happens when it is not done: an agent scopes a
search to a section, gets the half of it that fell inside one window, and believes it searched the
chapter.

**Two `impl` defects, not ported.**

* ``head_page_uncertain`` fired only when **no** page claimed the head, never when several did —
  and `impl`'s own trace has a unit with **four** competing head claims reported as certain
  (guide 07 §7.1). Here the declaring pages are counted and anything other than exactly one is
  uncertain, which is the fix that guide asks for.
* ``page_range`` is a range and the observed pages are a set, and `impl` kept both precisely
  because a section observed on 17-20 and 22-25 would otherwise claim page 21. Both are kept here
  too, and the gap is disclosed as ``noncontiguous_section`` rather than smoothed over.

**`series_id` is net new** (§5.1, F8). ``section_id`` carries the revision, so a scope expressed
with one dies at the next revision; ``series_id`` is the same section across revisions and is
built from the canonical key alone. U025 asserts it stays stable across a revision; this unit is
what writes it. Both are **keyword arrays** on the page, so a page that straddles two sections
carries both ids and a scope filter matching *any* element finds it either way (§5.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from vsir import logging as vsir_logging
from vsir.core import ids
from vsir.core.record import PageRecord, StoredSection
from vsir.ingest.derive import DerivedPage, SectionSighting

_log = vsir_logging.get_logger(__name__)

#: Disclosure flags stitching adds to a page. Both are admissions that the section's extent is
#: wider than its evidence, and both are read by nothing that filters — they are for the reader.
FLAG_NONCONTIGUOUS = "noncontiguous_section"
FLAG_INTERPOLATED_START = "interpolated_section_start"
STITCH_FLAGS: tuple[str, ...] = (FLAG_NONCONTIGUOUS, FLAG_INTERPOLATED_START)


@dataclass(frozen=True)
class Section:
    """One whole section, after the folds are gone (§5.1, §6.8).

    ``pages`` is what was **observed**; ``page_range`` is the **span**. They differ exactly when
    some page inside the span never reported the section, and keeping both is what stops
    ``page_range`` from making a claim nothing supports.
    """

    section_id: str
    series_id: str
    key: str
    title: str
    pages: tuple[int, ...]
    page_range: tuple[int, int]
    start_page: int
    #: True where the section's start was inferred rather than declared — no page claimed it, or
    #: several did. Surfaces as `interpolated_section_start` on every page of the section.
    start_uncertain: bool

    @property
    def contiguous(self) -> bool:
        """Whether every page of the span actually reported the section."""
        low, high = self.page_range
        return list(self.pages) == list(range(low, high + 1))

    @property
    def straddles(self) -> bool:
        """Whether the section covers more than one page — the fold case, when it does."""
        return self.page_range[0] != self.page_range[1]

    def stored(self, page_no: int) -> StoredSection:
        """This section as it is written on one page's record.

        ``is_start`` is the **resolved** start, not the raw claim: a section whose start was
        contested has one start page here and ``interpolated_section_start`` on every page, rather
        than four pages each quietly calling themselves the beginning.
        """
        return StoredSection(section_id=self.section_id, title=self.title,
                             series_id=self.series_id, page_range=self.page_range,
                             is_start=page_no == self.start_page)


@dataclass(frozen=True)
class Stitched:
    """Step 08's output: the finished records, and the sections they belong to."""

    pages: tuple[PageRecord, ...]
    sections: tuple[Section, ...]

    def section(self, key: str) -> Section:
        for section in self.sections:
            if section.key == key:
                return section
        raise KeyError(f"no section keyed {key!r}")

    @property
    def straddling(self) -> tuple[Section, ...]:
        return tuple(section for section in self.sections if section.straddles)


def _merge(sightings: Iterable[SectionSighting], *, doc_id: str,
           revision: str) -> tuple[Section, ...]:
    """Group sightings by canonical key and derive each section's extent.

    Ordinals are assigned by **first page**, so ``#s001`` is the section that begins earliest in
    the document and re-running the same document produces the same ids. Ties break on the key, so
    two sections first seen on one page still order deterministically.
    """
    pages: dict[str, set[int]] = {}
    titles: dict[str, str] = {}
    starts: dict[str, set[int]] = {}

    for sighting in sightings:
        if not sighting.key:
            # A title with no alphanumeric character in it addresses nothing: there is no key to
            # merge on and no `series_id` to mint. Derivation already drops these; dropping them
            # here too is what keeps this function total for any caller.
            continue
        pages.setdefault(sighting.key, set()).add(sighting.page_no)
        starts.setdefault(sighting.key, set())
        if sighting.is_start:
            starts[sighting.key].add(sighting.page_no)
        # The first title seen for a key wins, and only a non-empty one is recorded: two windows
        # can spell the same section differently and the key is what says they are one.
        if sighting.title and not titles.get(sighting.key):
            titles[sighting.key] = sighting.title

    ordered = sorted(pages, key=lambda key: (min(pages[key]), key))
    sections = []
    for ordinal, key in enumerate(ordered, start=1):
        observed = tuple(sorted(pages[key]))
        declared = starts[key]
        # Exactly one page claiming the start is the only certain case. None means nobody carried
        # the title block; several means the model said "it begins here" on pages that cannot all
        # be the beginning — `impl` reported the second case as certain (guide 07 §7.1).
        uncertain = len(declared) != 1
        sections.append(Section(
            section_id=ids.section_id(doc_id, revision, ordinal),
            series_id=ids.series_id(doc_id, key),
            key=key,
            title=titles.get(key, ""),
            pages=observed,
            page_range=(observed[0], observed[-1]),
            start_page=min(declared) if declared else observed[0],
            start_uncertain=uncertain,
        ))
    return tuple(sections)


def stitch(pages: Sequence[DerivedPage], *, doc_id: str, revision: str) -> Stitched:
    """Per-page section sightings → sections, and the ids back onto every page they cover.

    A page carries **every** section it was sighted in, as arrays — that is §5.3's rule and F8's
    other half: a single scalar `section_id` per page would force a straddling page to pick one
    section, and a scope filter on the other one would silently not return it.
    """
    sections = _merge((sighting for page in pages for sighting in page.sightings),
                      doc_id=doc_id, revision=revision)
    by_page: dict[int, list[Section]] = {}
    for section in sections:
        for page_no in section.pages:
            by_page.setdefault(page_no, []).append(section)

    finished = []
    for page in pages:
        mine = by_page.get(page.page_no, [])
        flags = set(page.record.content.flags)
        if any(not section.contiguous for section in mine):
            flags.add(FLAG_NONCONTIGUOUS)
        if any(section.start_uncertain for section in mine):
            flags.add(FLAG_INTERPOLATED_START)
        finished.append(page.record.model_copy(update={
            "section_id": [section.section_id for section in mine],
            "series_id": [section.series_id for section in mine],
            "content": page.record.content.model_copy(update={
                "sections": [section.stored(page.page_no) for section in mine],
                "flags": sorted(flags),
            }),
        }))

    _log.info("stitch", pages=len(finished), sections=len(sections),
              straddling=sum(1 for section in sections if section.straddles),
              noncontiguous=sum(1 for section in sections if not section.contiguous),
              uncertain_start=sum(1 for section in sections if section.start_uncertain))
    return Stitched(pages=tuple(finished), sections=sections)
