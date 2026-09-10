"""L0/L1 — the five publish gates of Spec §11.1 (I7, F4, F7, F12).

The gates are the moment the pipeline decides whether any of the work counts, and `impl` had no
test on any of them (register E6). Two of its four were struck outright and the two that remain in
spirit — coverage and disclosure — changed shape, so every row here is new.

The failures being guarded against are asymmetric, and the suite is written around that asymmetry:

* a **blocking** gate that fails open publishes a half-ingested manual, and then every coverage
  measurement of the corpus silently reports the pipeline's own incompleteness (§11.1);
* a **flagging** gate that blocks quarantines a scanned document, and the agent is then told *"that
  part doesn't exist"* about a page that is in the manual — F4, the injury the whole design exists
  to prevent.

So `grounded_rate` at zero text coverage gets its own test, `label_monotonic` gets a decreasing
sequence it must **not** block on, and the override path is tested both ways round: it releases the
one gate §11.1 offers it for, and it refuses the two that are not judgements.

Run this unit's slice:
    bash scripts/test-unit.sh -k "gates or export_shape or safety_flag"
"""
from __future__ import annotations

import pytest

from vsir.core import health
from vsir.core.record import PageRecord
from vsir.ingest import gates


def _windows(count: int = 3, *, failing: int | None = None) -> list[gates.WindowOutcome]:
    """``count`` window outcomes over a 42-page document, optionally with one that failed I4."""
    spans = [(1, 14), (15, 28), (29, 42)][:count]
    return [gates.WindowOutcome(start=start, end=end, pages_returned=end - start + 1,
                                offset_ok=(index != failing),
                                check="independent_observation" if index == failing else "")
            for index, (start, end) in enumerate(spans)]


def _rate(record: PageRecord, rate: float | None) -> PageRecord:
    """The same record with a different `grounded_rate`, and `has_text` kept consistent (§5.7)."""
    content = record.content.model_copy(update={"grounded_rate": rate})
    return record.model_copy(update={"content": content, "has_text": rate is not None,
                                     "text_trust": "no_text" if rate is None else "ok"})


def _label(record: PageRecord, printed: str) -> PageRecord:
    return record.model_copy(update={
        "content": record.content.model_copy(update={"printed_page_no": printed})})


@pytest.fixture(scope="module")
def records(stitched) -> tuple[PageRecord, ...]:
    """The M2a corpus's finished records — 42 pages, two of them without a text layer."""
    return tuple(stitched.pages)


@pytest.fixture(scope="module")
def report(records) -> gates.GateReport:
    return gates.evaluate(records=records, page_count=len(records), windows=_windows())


# ── the corpus passes, which is what makes every failure below meaningful ────────────────────────

def test_the_generated_corpus_passes_every_gate_and_raises_no_flag(report):
    """AC: the sound document publishes. Five results, three blocking, none of them blocking it."""
    assert [result.name for result in report.results] == list(gates.GATES)
    assert report.failures == ()
    assert report.flags == ()
    assert report.publishable()
    assert [result.name for result in report.results if result.blocking] == [
        gates.WINDOW_COVERAGE, gates.OFFSET_CHECK, gates.GROUNDED_RATE]


def test_a_passing_grounded_rate_gate_does_not_list_worst_pages(report):
    """§11.1 lists the worst pages as override material. On a published document that would be a
    list of its best-behaved pages, presented as a warning."""
    assert report[gates.GROUNDED_RATE].passed
    assert report[gates.GROUNDED_RATE].evidence == ()


# ── window_coverage — blocks below 1.0 (§11.1) ───────────────────────────────────────────────────

def test_a_missing_page_blocks_the_publish_and_names_the_window(records):
    """AC: `window_coverage < 1.0` after retries **blocks**, and the run record shows the gate."""
    short = [record for record in records if record.page_no != 20]

    report = gates.evaluate(records=short, page_count=len(records), windows=_windows())

    assert report[gates.WINDOW_COVERAGE].blocks
    assert report.blocking() == (gates.WINDOW_COVERAGE,)
    assert report[gates.WINDOW_COVERAGE].metric == pytest.approx(41 / 42)
    assert report[gates.WINDOW_COVERAGE].evidence[0] == {"window": [15, 28], "missing": [20]}


def test_a_document_with_no_records_at_all_blocks(records):
    """Nothing extracted is not "nothing to check": it is a document that must not publish."""
    report = gates.evaluate(records=[], page_count=42, windows=_windows())

    assert report[gates.WINDOW_COVERAGE].blocks
    assert report[gates.WINDOW_COVERAGE].metric == 0.0


def test_window_coverage_is_not_overridable(records):
    """§11.1 offers one override, and this is not it: pages missing from the index are not a
    judgement about a threshold, so no reason an operator types makes them publishable."""
    with pytest.raises(gates.OverrideRefused) as refusal:
        gates.check_override(gates.WINDOW_COVERAGE, "we are in a hurry")

    assert refusal.value.details["overridable"] == [gates.GROUNDED_RATE]


# ── offset_check — I4 on every window (F7) ───────────────────────────────────────────────────────

def test_a_window_that_failed_either_offset_check_blocks_and_is_named(records):
    """AC: any window failing either §6.4 check **blocks**, and the record names the window."""
    report = gates.evaluate(records=records, page_count=len(records),
                            windows=_windows(failing=1))

    assert report[gates.OFFSET_CHECK].blocks
    assert report.blocking() == (gates.OFFSET_CHECK,)
    assert "15-28" in report[gates.OFFSET_CHECK].detail
    assert report[gates.OFFSET_CHECK].evidence[0]["window"] == [15, 28]
    assert report[gates.OFFSET_CHECK].evidence[0]["check"] == "independent_observation"


def test_a_bisected_window_is_a_pass_and_says_so(records):
    """§6.2's repair worked. F13's ladder re-bills and re-derives; it is not a defect to hold a
    document for, and the record still says it happened."""
    repaired = _windows()
    repaired[2] = gates.WindowOutcome(start=29, end=42, pages_returned=14, bisected=True)

    result = gates.offset_check(repaired)

    assert result.passed
    assert "bisected and re-billed" in result.detail and "29-42" in result.detail


def test_no_window_outcome_at_all_blocks_rather_than_passing_vacuously():
    """A gate with nothing to check must not report a pass: I4 is proved on every window, and an
    empty list is not proof of anything."""
    result = gates.offset_check([])

    assert result.blocks
    assert "never proved" in result.detail


# ── grounded_rate — blocking, overridable, and skipped where it cannot be measured ───────────────

def test_a_collapsed_grounded_rate_blocks_and_lists_the_worst_pages(records):
    """AC: the median below the threshold blocks, holds for review and lists the worst pages."""
    poor = [_rate(record, 0.1 if record.page_no % 2 else 0.4) for record in records]

    report = gates.evaluate(records=poor, page_count=len(records), windows=_windows())
    result = report[gates.GROUNDED_RATE]

    assert result.blocks and result.metric is not None and result.metric < gates.GROUNDED_RATE_MIN
    assert result.threshold == gates.GROUNDED_RATE_MIN == 0.8
    assert len(result.evidence) == gates.WORST_PAGES
    assert [row["grounded_rate"] for row in result.evidence] == [0.1] * gates.WORST_PAGES
    assert "--override grounded_rate" in result.detail


def test_the_override_releases_the_hold_and_flags_every_page(records):
    """AC: `vsir publish --override grounded_rate --reason "…"` publishes, and the decision says
    every page carries `published_with_override`."""
    poor = [_rate(record, 0.1) for record in records]
    report = gates.evaluate(records=poor, page_count=len(records), windows=_windows())

    held = gates.decide(report)
    released = gates.decide(report, [gates.GROUNDED_RATE])

    assert not held.publish and held.blocked_by == (gates.GROUNDED_RATE,)
    assert released.publish and released.blocked_by == ()
    assert released.flags == (gates.FLAG_PUBLISHED_WITH_OVERRIDE,)


def test_an_override_without_a_reason_is_refused():
    """The reason is the only thing that will later explain why a held document is in the index."""
    gates.check_override(gates.GROUNDED_RATE, "M2b baseline says 0.62 is this corpus's normal")

    with pytest.raises(gates.OverrideRefused):
        gates.check_override(gates.GROUNDED_RATE, "   ")


def test_an_override_does_not_release_a_gate_it_did_not_name(records):
    """Overriding `grounded_rate` on a document whose offset proof failed publishes nothing."""
    poor = [_rate(record, 0.1) for record in records]
    report = gates.evaluate(records=poor, page_count=len(records), windows=_windows(failing=0))

    assert gates.decide(report, [gates.GROUNDED_RATE]).blocked_by == (gates.OFFSET_CHECK,)


def test_a_fully_scanned_document_skips_the_grounded_rate_gate_entirely(records):
    """AC + F4: at `text_coverage == 0.0` the gate is **not evaluated**, and the document
    publishes with `mostly_scanned` rather than being quarantined."""
    scanned = [_rate(record, None) for record in records]

    report = gates.evaluate(records=scanned, page_count=len(records), windows=_windows())
    result = report[gates.GROUNDED_RATE]

    assert result.skipped and result.metric is None
    assert not result.blocks and report.publishable()
    assert report.flags == (gates.FLAG_MOSTLY_SCANNED,)
    assert "not_searchable" in result.detail


def test_a_page_without_text_is_ignored_by_the_median_rather_than_scored_zero(records):
    """§5.7's `None` rule, at document level: the two scanned pages of the corpus do not drag a
    healthy document under a blocking threshold."""
    mixed = [_rate(record, None if record.page_no <= 20 else 1.0) for record in records]
    document = health.document_health([r.content.grounded_rate for r in mixed],
                                      [r.has_text for r in mixed])

    result = gates.grounded_rate(mixed, document)

    assert result.passed and result.metric == 1.0
    assert document.pages_with_text == 22


# ── text_coverage and label_monotonic — disclosure, never a block (§11.1) ────────────────────────

def test_text_coverage_never_blocks_however_low_it_goes(records):
    """It is the only gate whose worst case is a document that must still be published (F4)."""
    for share in (0.0, 0.1, 0.49):
        with_text = int(len(records) * share)
        pages = [_rate(record, 1.0 if index < with_text else None)
                 for index, record in enumerate(records)]
        report = gates.evaluate(records=pages, page_count=len(records), windows=_windows())

        assert not report[gates.TEXT_COVERAGE].blocking
        assert report[gates.TEXT_COVERAGE].flag == gates.FLAG_MOSTLY_SCANNED
        assert gates.FLAG_MOSTLY_SCANNED in report.flags


def test_a_non_monotonic_label_sequence_flags_and_publishes(records):
    """AC: a non-monotonic printed-label sequence publishes with `label_conflict`."""
    conflicting = [_label(record, "3" if record.page_no == 30 else
                          record.content.printed_page_no) for record in records]

    report = gates.evaluate(records=conflicting, page_count=len(records), windows=_windows())
    result = report[gates.LABEL_MONOTONIC]

    assert not result.passed and not result.blocking
    assert report.publishable() and report.flags == (gates.FLAG_LABEL_CONFLICT,)
    assert result.evidence[0]["page_no"] == 30 and result.evidence[0]["printed_page_no"] == "3"


def test_roman_front_matter_followed_by_arabic_is_not_a_conflict(records):
    """The corpus itself: `i, ii, 1, 2, …`. Comparing `ii` against `1` would flag every manual in
    the corpus, which is the fastest way to make a disclosure flag mean nothing."""
    assert [records[0].content.printed_page_no, records[1].content.printed_page_no] == ["i", "ii"]

    assert gates.label_monotonic(records).passed


def test_an_unlabelled_page_is_skipped_rather_than_compared_as_zero(records):
    """A page with no printed label is not a page numbered 0. Skipping it is the difference
    between a signal and noise on every scanned cover page in the corpus."""
    blanked = [_label(record, "" if record.page_no in (10, 11) else
                      record.content.printed_page_no) for record in records]

    assert gates.label_monotonic(blanked).passed


# ── the report shape the run record carries (§6.9) ───────────────────────────────────────────────

def test_the_report_round_trips_through_the_run_record_payload(report):
    """`gates rerun` and `runs show` both read gate results back out of Qdrant, so a result that
    did not survive the payload would be a decision nobody could review afterwards."""
    restored = gates.GateReport.from_mapping(report.as_dict())

    assert restored.as_dict() == report.as_dict()
    assert [result.name for result in restored.results] == list(gates.GATES)
    assert restored.publishable() == report.publishable()


def test_a_skipped_gate_is_not_recorded_as_a_pass(records):
    """The payload keeps `skipped` distinct from `pass`, because "we did not measure this" and
    "this measured well" are different things to read off a run six months later (§5.7)."""
    scanned = [_rate(record, None) for record in records]
    stored = gates.evaluate(records=scanned, page_count=len(records),
                            windows=_windows()).as_dict()

    assert stored[gates.GROUNDED_RATE]["skipped"] is True
    assert stored[gates.GROUNDED_RATE]["metric"] is None


def test_the_gate_threshold_is_the_page_level_trust_threshold(records):
    """One number for one judgement (§5.7, §11.1): two would let a page be individually trusted
    inside a document the gate refuses to publish."""
    assert gates.GROUNDED_RATE_MIN is health.TRUST_OK_MIN
