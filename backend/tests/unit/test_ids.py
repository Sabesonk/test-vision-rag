"""L0 — identifiers (Spec §5.1).

The property that matters is not the format, it is **determinism**: the same page must produce the
same `point_id` in every process, forever, because that is what makes a re-ingest overwrite rather
than duplicate (I1) and what keeps totals from doubling (F12).
"""
from __future__ import annotations

import subprocess
import sys
import uuid

import pytest

from vsir.core import ids


def test_page_id_has_the_documented_shape():
    assert ids.page_id("TC1E-SF", "1.3", 1) == "TC1E-SF@1.3#p001"
    assert ids.page_id("TC1E-SF", "1.3", 54) == "TC1E-SF@1.3#p054"


def test_page_id_is_byte_identical_across_calls():
    assert ids.page_id("TC1E-SF", "1.3", 1) == ids.page_id("TC1E-SF", "1.3", 1)


def test_page_id_pads_to_three_digits_and_never_truncates():
    """§5.1 says "padded to 3+": a 1,440-page manual must not wrap at page 1000."""
    assert ids.page_id("M", "1", 999).endswith("#p999")
    assert ids.page_id("M", "1", 1000).endswith("#p1000")
    assert ids.page_id("M", "1", 1440).endswith("#p1440")


def test_page_id_refuses_a_zero_or_negative_page():
    """`page_no` is the 1-based absolute page with the offset already applied (§6.4)."""
    with pytest.raises(ValueError):
        ids.page_id("M", "1", 0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("TC1E-SF@1.3#p001", ("TC1E-SF", "1.3", 1)),
        ("TC1E-SF@1.3#p1440", ("TC1E-SF", "1.3", 1440)),
    ],
)
def test_parse_page_id_round_trips(value, expected):
    assert ids.parse_page_id(value) == expected


@pytest.mark.parametrize("stem", ["TC1E@SF", "a#b", "x@y#p001", "rev@1.3"])
def test_a_doc_id_can_never_contain_the_separators(stem):
    """What makes the parse unambiguous: `doc_id` is a slug, so `@` and `#` are separators only."""
    generated = ids.doc_id(stem)

    assert "@" not in generated and "#" not in generated
    assert ids.parse_page_id(ids.page_id(generated, "1.3", 4)) == (generated, "1.3", 4)


@pytest.mark.parametrize(
    "value",
    ["TC1E-SF#p001", "TC1E-SF@1.3", "TC1E-SF@1.3#p1", "TC1E-SF@1.3#s001", "", "p001"],
)
def test_parse_page_id_refuses_a_malformed_citation(value):
    """`resolve` takes a citation from outside this service: refuse, never guess (§7.2.3)."""
    with pytest.raises(ValueError):
        ids.parse_page_id(value)


def test_point_id_is_uuid5_of_the_page_id_under_namespace_url():
    """The namespace is part of the id: changing it would orphan every point in the collection."""
    page = ids.page_id("TC1E-SF", "1.3", 1)

    assert ids.point_id(page) == str(uuid.uuid5(uuid.NAMESPACE_URL, page))
    assert ids.NAMESPACE == uuid.NAMESPACE_URL


def test_point_id_is_stable_across_processes():
    """I1 — a fresh interpreter must compute the same point id, or a re-ingest duplicates."""
    page = "TC1E-SF@1.3#p001"
    expected = ids.point_id(page)

    result = subprocess.run(
        [sys.executable, "-c",
         f"from vsir.core import ids; print(ids.point_id({page!r}))"],
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip() == expected


def test_a_different_page_or_revision_is_a_different_point():
    """F12 — two revisions of one page are two points, so F9 keeps its evidence."""
    distinct = {
        ids.point_id(ids.page_id("TC1E-SF", "1.3", 1)),
        ids.point_id(ids.page_id("TC1E-SF", "1.3", 2)),
        ids.point_id(ids.page_id("TC1E-SF", "1.4", 1)),
        ids.point_id(ids.page_id("OTHER", "1.3", 1)),
    }
    assert len(distinct) == 4


def test_section_id_carries_the_revision_and_series_id_does_not():
    """F8 — a scope expressed as a series survives a revision boundary; a section cannot."""
    assert ids.section_id("TC1E-SF", "1.3", 7) == "TC1E-SF@1.3#s007"
    assert ids.section_id("TC1E-SF", "1.4", 7) != ids.section_id("TC1E-SF", "1.3", 7)

    assert ids.series_id("TC1E-SF", "Emergency Stop") == "TC1E-SF#s:emergency-stop"
    assert "1.3" not in ids.series_id("TC1E-SF", "Emergency Stop")


def test_series_id_is_stable_under_incidental_title_differences():
    """The canonical key comes from stitching (U009); the id grammar must not add its own noise."""
    assert ids.series_id("D", "Emergency stop") == ids.series_id("D", "emergency  stop")
    assert ids.series_id("D", "Emergency-Stop") == ids.series_id("D", "Emergency Stop")


def test_series_id_refuses_an_empty_key():
    with pytest.raises(ValueError):
        ids.series_id("D", "   ")


def test_doc_id_is_a_slug_from_the_manifest():
    assert ids.doc_id("TC1E-SF") == "TC1E-SF"
    assert ids.doc_id("TC1E SF rev 1.3") == "TC1E-SF-rev-1-3"
    assert ids.doc_id("...") == "doc"


def test_run_id_is_a_26_character_crockford_ulid():
    """Register E1 — `uuid4().hex[:8]` is replaced by an id that sorts and carries its time."""
    value = ids.run_id()

    assert len(value) == ids.ULID_LENGTH == 26
    assert set(value) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    assert not set(value) & set("ILOU"), "Crockford omits I, L, O and U"


def test_run_id_sorts_in_time_order():
    early = ids.run_id(now_ms=1_600_000_000_000, randomness=b"\xff" * 10)
    late = ids.run_id(now_ms=1_600_000_000_001, randomness=b"\x00" * 10)

    assert early < late, "a later run must sort after an earlier one, whatever the randomness"


def test_two_run_ids_in_the_same_millisecond_still_differ():
    same_ms = 1_600_000_000_000
    assert ids.run_id(now_ms=same_ms) != ids.run_id(now_ms=same_ms)


def test_run_id_is_deterministic_given_its_inputs():
    assert ids.run_id(now_ms=1, randomness=b"\x01" * 10) == ids.run_id(now_ms=1,
                                                                       randomness=b"\x01" * 10)


@pytest.mark.parametrize(
    ("now_ms", "randomness"),
    [(-1, None), (1 << 48, None), (0, b"\x00" * 9), (0, b"\x00" * 11)],
)
def test_run_id_refuses_out_of_range_inputs(now_ms, randomness):
    with pytest.raises(ValueError):
        ids.run_id(now_ms=now_ms, randomness=randomness)
