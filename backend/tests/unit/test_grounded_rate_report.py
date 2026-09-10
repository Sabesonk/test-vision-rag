"""L0/L1 — the `grounded_rate` distribution report and the threshold it proposes (Spec §11.1, R4).

R4 is a residual risk with a name: *"`grounded_rate ≥ 0.8` is chosen, not derived."* The report is
what derives it, so the thing this suite has to pin down is not arithmetic — it is the **refusals**.
A report that recommends a number off the wrong corpus is worse than no report, because the number
arrives with a paper trail and gets adopted. So three of these tests are about when the module
declines to recommend at all:

* a corpus whose text layer nobody extracted (both checked-in corpora are constructions — the M1
  pages are hand-written and the `impl` baseline's text is a projection that rates 1.0 by
  definition);
* a fully scanned document, where §11.1 **skips** the gate rather than failing it (F4);
* a document under every rung, which is R3's extractor collapse and a finding about the ingest.

The fourth is the asymmetry: one document may lower the bar and may not raise it.

Run just this file:
    bash scripts/test-unit.sh -k grounded_rate_report
"""
from __future__ import annotations

import json

import pytest

from vsir.core import health
from vsir.core.exact import printed_on
from vsir.core.record import PageRecord
from vsir.eval import grounded_rate as report_module
from vsir.eval import synthetic

INGESTED = "pymupdf-1.26.0"


def _record(page_no: int, rate: float | None, *, doc_id: str = "DOC", revision: str = "1.0",
            probe_version: str = INGESTED) -> PageRecord:
    """One page carrying a rate, with `has_text` and `text_trust` kept consistent with it (§5.7)."""
    has_text = rate is not None
    return PageRecord(
        doc_id=doc_id, revision=revision, page_no=page_no, has_text=has_text,
        text_trust=health.page_trust(rate, has_text=has_text),
        content={"grounded_rate": rate},
        provenance={"page_id": f"{doc_id}@{revision}#p{page_no:03d}",
                    "probe_version": probe_version},
    )


def _document(rates, *, probe_version: str = INGESTED) -> report_module.Distribution:
    return report_module.from_records([
        _record(page_no, rate, probe_version=probe_version)
        for page_no, rate in enumerate(rates, start=1)
    ])


# ── the distribution is the gate's own reading, not a second one ────────────────────────────────

def test_the_median_is_the_gate_s_median_and_not_a_reimplementation():
    """§11.1 scores the document on `health.median`; a report against another number is a trap."""
    rates = [1.0, 0.9, None, 0.4, None, 0.75]
    distribution = _document(rates)

    assert distribution.median == health.median(rates)


def test_a_page_with_no_text_layer_contributes_no_rate_and_is_not_a_zero():
    """§5.7's rule, at the aggregate: the `None`s are dropped, never defaulted (F4)."""
    distribution = _document([1.0, None, 1.0, None])

    assert distribution.page_count == 4
    assert distribution.pages_with_text == 2
    assert distribution.pages_without_text == 2
    assert distribution.measured == (1.0, 1.0)
    assert distribution.median == 1.0
    assert distribution.searchable_ratio == 0.5


def test_records_from_two_documents_are_refused_by_name():
    """A median across documents is a number §11.1 gates nothing on."""
    records = [_record(1, 1.0, doc_id="A"), _record(1, 0.2, doc_id="B")]

    with pytest.raises(report_module.NoRecords, match="A@1.0, B@1.0"):
        report_module.from_records(records)


def test_records_from_two_revisions_of_one_document_are_refused_too():
    """§6.7 publishes one revision at a time; scoring both together scores pages together that
    the gate never evaluates together."""
    records = [_record(1, 1.0, revision="1.0"), _record(1, 0.2, revision="1.1")]

    with pytest.raises(report_module.NoRecords, match="DOC@1.0, DOC@1.1"):
        report_module.from_records(records)


def test_no_records_at_all_is_refused_rather_than_reported_as_empty():
    with pytest.raises(report_module.NoRecords, match="not a measurement"):
        report_module.from_records([])


# ── the readings ────────────────────────────────────────────────────────────────────────────────

def test_every_percentile_is_a_rate_some_page_actually_holds():
    """Nearest rank, not interpolation: on 55 pages an interpolated value is a number dressed as
    a measurement."""
    rates = [0.1, 0.4, 0.55, 0.9, 1.0]
    distribution = _document(rates)

    for p in report_module.PERCENTILES:
        assert distribution.percentile(p) in rates
    assert distribution.percentile(0) == 0.1
    assert distribution.percentile(100) == 1.0
    assert distribution.percentile(50) == 0.55


def test_a_percentile_outside_0_100_is_refused():
    with pytest.raises(ValueError, match="not within 0..100"):
        _document([1.0]).percentile(101)


def test_the_histogram_covers_every_measured_page_and_cuts_on_the_trust_ladder():
    """`0.2` and `0.8` must be bucket edges — a reader has to see the untrusted and ok cuts."""
    distribution = _document([0.0, 0.19, 0.2, 0.79, 0.8, 1.0, None])
    buckets = distribution.histogram()

    assert sum(count for _, _, count in buckets) == len(distribution.measured) == 6
    edges = {low for low, _, _ in buckets} | {high for _, high, _ in buckets}
    assert health.TRUST_UNTRUSTED_BELOW in edges
    assert health.TRUST_OK_MIN in edges
    # The last bucket is closed, so a perfect page is counted rather than dropped off the end.
    assert buckets[-1] == (0.8, 1.0, 2)


def test_the_worst_pages_are_the_lowest_rating_ones_ties_by_page_number():
    distribution = _document([0.5, 1.0, 0.5, 0.2, None])

    assert [page.page_no for page in distribution.worst(3)] == [4, 1, 3]


def test_worst_pages_never_include_a_page_that_has_no_rate():
    distribution = _document([None, None, 1.0])

    assert [page.page_no for page in distribution.worst()] == [3]


# ── a candidate threshold's verdict ─────────────────────────────────────────────────────────────

def test_a_candidate_scores_the_document_on_the_median_and_the_pages_on_their_own_rates():
    distribution = _document([1.0, 1.0, 1.0, 0.1, 0.1])

    candidate = distribution.at(0.8)

    assert candidate.document_passes is True      # the median is 1.0
    assert candidate.pages_below == 2             # ... and two pages are not
    assert candidate.share_below == 0.4
    assert candidate.headroom == pytest.approx(0.2)


def test_a_threshold_outside_0_1_is_refused_rather_than_clamped():
    with pytest.raises(ValueError, match="not a share within 0..1"):
        _document([1.0]).at(80)


def test_the_sweep_is_ascending_and_deduplicated():
    candidates = report_module.sweep(_document([1.0]), [0.9, 0.5, 0.9])

    assert [candidate.threshold for candidate in candidates] == [0.5, 0.9]


# ── the three refusals to recommend ─────────────────────────────────────────────────────────────

def test_a_fully_scanned_document_is_skipped_not_failed_and_sets_no_threshold():
    """§11.1 skips the gate at zero text coverage; F4 publishes the document, it is not scored."""
    distribution = _document([None, None, None])

    assert distribution.fully_scanned is True
    assert distribution.median is None
    assert distribution.at(0.8).document_passes is None      # skipped — not False
    suggestion = report_module.recommend(distribution)
    assert suggestion.threshold is None
    assert "not_searchable" in suggestion.rationale


@pytest.mark.parametrize("probe_version", ["hand-written-m1", "legacy-projection-r-poc-5", ""])
def test_a_corpus_the_extractor_never_touched_sets_no_threshold(probe_version):
    """R4 is set from a real ingest. A construction reports its own construction."""
    distribution = _document([1.0] * 10, probe_version=probe_version)

    assert distribution.measured_by_the_extractor is False
    suggestion = report_module.recommend(distribution)
    assert suggestion.threshold is None
    assert report_module.EXTRACTOR_PREFIX in suggestion.rationale
    # The ceiling is still reported: it is a fact about the corpus, just not evidence about the gate.
    assert suggestion.supported == 0.95


def test_a_document_under_every_rung_is_a_finding_about_the_ingest_not_a_lower_bar():
    """R3 — the extractor is the single point of truth, and a collapse looks exactly like this."""
    distribution = _document([0.1, 0.2, 0.15])

    suggestion = report_module.recommend(distribution)

    assert suggestion.threshold is None
    assert "R3" in suggestion.rationale


# ── the asymmetry ───────────────────────────────────────────────────────────────────────────────

def test_one_document_may_not_raise_the_bar_however_well_it_rates():
    """Fitting a gate over 5,505 pages to 55 of them holds every later document on a sample of
    one. The ceiling is reported as evidence; the recommendation stays at the pin."""
    distribution = _document([1.0] * 55)

    suggestion = report_module.recommend(distribution, current=0.8)

    assert suggestion.supported == 0.95
    assert suggestion.threshold == 0.8
    assert suggestion.changes_the_pin is False


def test_a_document_that_rates_below_the_pin_does_lower_it():
    """R4's first named injury is a gate that quarantines good documents — this is the evidence
    for it, and it is evidence in one direction only."""
    distribution = _document([0.7, 0.7, 0.75, 0.7])   # median 0.70

    suggestion = report_module.recommend(distribution, current=0.8)

    assert suggestion.supported == 0.60
    assert suggestion.threshold == 0.60
    assert suggestion.changes_the_pin is True


def test_a_recommendation_is_always_provisional_and_says_so():
    suggestion = report_module.recommend(_document([1.0] * 55))

    assert suggestion.provisional is True
    assert "R4" in suggestion.rationale
    assert "--override grounded_rate" in suggestion.rationale


def test_the_recommendation_never_reaches_the_gate_by_itself():
    """The pin is code. Nothing here writes it, and `recommend` reports the shipped value."""
    assert report_module.recommend(_document([1.0] * 5)).current == health.TRUST_OK_MIN


# ── the candidate threshold from the environment ────────────────────────────────────────────────

def test_the_env_threshold_is_read_when_set_and_is_none_when_not():
    assert report_module.env_threshold({}) is None
    assert report_module.env_threshold({report_module.THRESHOLD_ENV: ""}) is None
    assert report_module.env_threshold({report_module.THRESHOLD_ENV: "0.75"}) == 0.75


@pytest.mark.parametrize("raw", ["80", "-0.1", "1.5", "eighty"])
def test_a_threshold_that_is_not_a_share_is_a_named_refusal_not_a_default(raw):
    """An operator who typed `80` meant `0.8`; reporting against 80 shows every page failing."""
    with pytest.raises(ValueError, match=report_module.THRESHOLD_ENV):
        report_module.env_threshold({report_module.THRESHOLD_ENV: raw})


def test_the_env_var_is_read_by_this_report_and_by_nothing_that_gates():
    """§5.7 — a deployment that could re-tune what "trusted" means could turn F14 back on by
    editing an env var, so the name appears in `eval/` and nowhere in `ingest/` or `serve/`."""
    from pathlib import Path

    root = Path(report_module.__file__).resolve().parents[1]
    offenders = [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*.py"))
        if report_module.THRESHOLD_ENV in path.read_text(encoding="utf-8")
    ]

    assert offenders == ["eval/grounded_rate.py"]


def test_the_candidate_threshold_is_documented_in_the_env_example():
    """§15 Factor III — a deployment-varying value is an env var in `.env.example`, and this one
    also has to say what it does *not* do, or an operator will set it and expect the gate to move."""
    from pathlib import Path

    example = (Path(__file__).resolve().parents[3] / ".env.example").read_text(encoding="utf-8")

    assert f"{report_module.THRESHOLD_ENV}=" in example
    assert "TRUST_OK_MIN" in example
    assert "R4" in example


# ── the printed and machine-readable reports ────────────────────────────────────────────────────

def test_the_report_is_deterministic_over_deterministic_input():
    """It goes into a run report and a commit message verbatim, so it may not wobble."""
    distribution = _document([1.0, 0.9, None, 0.4])

    assert report_module.report(distribution) == report_module.report(distribution)


def test_the_report_names_the_pin_the_median_and_every_candidate():
    distribution = _document([1.0] * 55)

    printed = report_module.report(distribution, proposed=0.75)

    assert "DOC@1.0" in printed
    assert "← the pin" in printed
    for rung in report_module.LADDER:
        assert f"{rung:.2f}" in printed
    assert f"{report_module.THRESHOLD_ENV}=0.75" in printed


def test_the_report_warns_in_full_when_the_corpus_was_never_extracted():
    printed = report_module.report(_document([1.0] * 5, probe_version="hand-written-m1"))

    assert "NOT A MEASUREMENT" in printed
    assert "hand-written-m1" in printed


def test_the_json_report_round_trips_through_json_and_carries_the_recommendation():
    distribution = _document([1.0, 0.5, None])
    payload = distribution.as_dict()
    payload["recommendation"] = report_module.recommend(distribution).as_dict()

    reloaded = json.loads(json.dumps(payload, sort_keys=True))

    assert reloaded["page_count"] == 3
    assert reloaded["pages_with_text"] == 2
    assert reloaded["measured_by_the_extractor"] is True
    assert reloaded["recommendation"]["current_pin"] == health.TRUST_OK_MIN


# ── over the corpora that exist today ───────────────────────────────────────────────────────────

def test_the_m2a_ingest_is_the_one_corpus_the_extractor_did_measure(stitched):
    """The generated PDF goes through `ingest/probe.py`, so its pages carry a `pymupdf-` probe
    version — the shape a real M2b ingest reports, exercised without spending anything."""
    distribution = report_module.from_records(stitched.pages)

    assert distribution.measured_by_the_extractor is True
    assert distribution.page_count == 42
    assert distribution.pages_without_text == 2       # the two scanned pages of the corpus
    assert distribution.median is not None
    assert report_module.recommend(distribution).threshold is not None


def test_the_m1_corpus_reports_its_shape_but_proposes_nothing():
    corpus = synthetic.load()

    distribution = report_module.from_records(corpus.current_records())

    assert distribution.measured_by_the_extractor is False
    assert report_module.recommend(distribution).threshold is None


# ── the fix this report uncovered (§5.7's phrase, in the M1 fixture builder) ─────────────────────
#
# `eval/synthetic.py` used to compute the corpus's `grounded_rate` and `codes_in_text` with a
# `token_set` intersection — the formula §5.7's "Why a phrase" paragraph exists to reject. It
# rated every compact and multi-token label 0.0: `SF121.1` is printed on p003 as `SF121.1)`, which
# Qdrant's WORD tokenizer reads as [sf121, 1], so the code is never a member of the page's token
# set even though `lookup` finds it there. The corpus therefore disagreed with its own index about
# which codes it was evidence for, which is exactly what I3 forbids.

def test_the_m1_corpus_grounds_a_code_exactly_where_lookup_would_find_it():
    """§5.7, §5.6, I3 — one question about membership, with one answer."""
    for record in synthetic.load().records():
        if not record.has_text:
            continue
        expected = [code for code in record.content.codes if printed_on(code, record.text)]
        assert record.content.codes_in_text == health.codes_in_text(expected), record.page_id
        assert record.content.grounded_rate == health.grounded_rate(
            len(record.content.codes), len(expected), has_text=True), record.page_id


def test_the_m1_corpus_s_compact_labels_are_grounded_not_scored_zero():
    """The pages the intersection got wrong: a compact `SF121.1)` and a spaced `SF 1.1A`."""
    corpus = synthetic.load()
    by_id = {record.page_id: record for record in corpus.records()}

    for row in corpus.expected["compact_labels"]:
        record = by_id[row["page_id"]]
        assert row["label"].lower().replace(" ", "") in "".join(
            code.lower().replace(" ", "") for code in record.content.codes_in_text), row["label"]
