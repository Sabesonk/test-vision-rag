"""L2 — `vsir eval corpus`, the §12.6 report and the D11 gates (plan U026).

The report itself is **L5**: a canary run by hand against a published index, and its output is the
deliverable. What is automated here is the thing an L5 report cannot check about itself — that the
**arithmetic** between a measurement and a verdict is right, at every boundary D11 names, and that
the command is red exactly when the system is wrong.

So the file is in two halves:

* **the gates, as arithmetic** — :class:`~vsir.eval.corpus.Metric` and
  :class:`~vsir.eval.corpus.Gate` at 1.00, 0.95, 0.90 and 0.99 and one step either side of each,
  plus every way C10's re-baseline rule can be broken. No Qdrant, no corpus, no ambiguity about
  what is being asserted;
* **the command, end to end** — against the §13 M1 corpus and a ground-truth file mutated to make
  each failure real. A green report that cannot go red is a decoration, so every gate has a
  negative control that drives the measurement, not the verdict: the truth file is edited the way
  a genuine disagreement would arrive, and the command must find it.

Everything here is free. The command reads an index and the near-miss set is derived from the
observed-token inventory (§12.4, OQ-4), so there is no model call on any path — asserted twice
below, once with a spy and once against the import graph.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator

import pytest
from qdrant_client import QdrantClient

from vsir import cli
from vsir import vlm
from vsir.eval import corpus, synthetic

REPO = Path(__file__).resolve().parents[3]
EMBED_DIM = 1536

#: This suite's own namespace, for the reason `test_eval_commands.py` gives: two suites sharing an
#: ephemeral collection drop it out from under each other.
COLLECTION = "vsir_pages_evalcorpus"
RUNS = "vsir_runs_evalcorpus"

BASE_ENV = {
    "VSIR_PORT": "8000", "VSIR_COLLECTION": COLLECTION, "VSIR_RUNS_COLLECTION": RUNS,
    "VSIR_VLM": "stub", "VSIR_VLM_MODEL": "gemini-3.8-flash",
    "VSIR_EMBED_MODEL": "gemini-embedding-2", "VSIR_PROMPT_VERSION": "s2-v1",
    "VSIR_API_TOKENS": "test-only-not-a-credential", "VSIR_READ_QUOTA": "10",
    "VSIR_ALLOW_PAID": "0", "VSIR_LOG_LEVEL": "INFO", "VSIR_RELEASE_ID": "test-0",
}

#: The collection ``--corpus synthetic`` creates and must drop.
EPHEMERAL = (synthetic.synthetic_collection(f"{COLLECTION}_{corpus.EPHEMERAL}", EMBED_DIM),
             synthetic.synthetic_collection(f"{COLLECTION}_eval_abstention", EMBED_DIM))


def qdrant_url() -> str:
    return os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")


@pytest.fixture
def clean(qdrant: QdrantClient) -> Iterator[QdrantClient]:
    """No leftover ephemeral collection on the way in, and none on the way out."""
    def drop() -> None:
        for name in EPHEMERAL:
            if qdrant.collection_exists(name):
                qdrant.delete_collection(name)

    drop()
    try:
        yield qdrant
    finally:
        drop()


@pytest.fixture
def run(monkeypatch, clean):
    """`vsir eval corpus …` in this process, configured for the L2 stack. Returns the exit code."""
    for name, value in {**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url()}.items():
        monkeypatch.setenv(name, value)
    # A report that could reach a model must not be able to find a key even by accident (D10).
    for name in ("VSIR_VLM_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", corpus.TRUTH_ENV):
        monkeypatch.delenv(name, raising=False)

    def _run(*arguments: str) -> int:
        return cli.main(["eval", "corpus", *arguments])

    return _run


def gate(metric: str) -> corpus.Gate:
    return corpus.gates()[metric]


def metric(name: str, numerator: int, denominator: int, **rest: Any) -> corpus.Metric:
    """One measured metric at a chosen ratio — the gate arithmetic's only input."""
    return corpus.Metric(name=name, set_name="synthetic", gate=gate(name),
                         numerator=numerator, denominator=denominator, **rest)


def verdicts(output: str) -> dict[str, str]:
    """The report's metric table, read back as ``{metric: verdict}``."""
    found: dict[str, str] = {}
    for line in output.splitlines():
        name = line.split(" ", 1)[0]
        if name in corpus.D11 and line.startswith(name):
            found[name] = line.rsplit(" ", 1)[-1]
    return found


def flat(output: str) -> str:
    """The report with every run of whitespace collapsed.

    The report wraps prose at a column so it is readable in a terminal, which means a sentence
    an assertion is about can arrive split across two lines. Asserting against the flattened
    text checks the sentence rather than the column width it happened to be wrapped to.
    """
    return " ".join(output.split())


def shipped_truth() -> dict:
    return json.loads(corpus.truth_path(fixture="synthetic_pages").read_text(encoding="utf-8"))


def truth_file(tmp_path: Path, mutate) -> str:
    """The shipped ground truth with one edit, written where ``--truth`` can be pointed at it.

    Derived from the checked-in file rather than hand-built, so a negative control stays a
    statement about **one** changed row and cannot drift into testing a different corpus.
    """
    document = shipped_truth()
    mutate(document)
    path = tmp_path / corpus.TRUTH_FILE
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


# ── the gate arithmetic, at every boundary D11 names ────────────────────────────────────────────

def test_the_d11_table_holds_the_spec_s_own_five_numbers():
    """§12.6's table, transcribed: a gate that had drifted makes every row below meaningless."""
    assert {name: bound.floor for name, bound in corpus.D11.items()} == {
        "code_precision": 1.00,
        "code_recall": 0.95,
        "abstention_correctness": 1.00,
        "alarm_label_hit": 0.99,
        "xref_resolve": 0.99,
    }
    # The two safety properties, and the one blocking floor D11 gives.
    assert [name for name, bound in corpus.D11.items() if bound.p0] == [
        "code_precision", "abstention_correctness"]
    assert {name: bound.block_below for name, bound in corpus.D11.items()
            if bound.block_below is not None} == {"code_recall": 0.90}


@pytest.mark.parametrize("name", ["code_precision", "abstention_correctness"])
def test_a_safety_gate_passes_at_exactly_one_and_at_nothing_below_it(name):
    """D11: `= 1.00`, and *"a single wrong code is a P0 stop"* — not a rounding pass."""
    assert metric(name, 484, 484).outcome == corpus.PASS
    one_miss = metric(name, 483, 484)

    assert one_miss.value == pytest.approx(0.99793, abs=1e-5)
    assert one_miss.outcome == corpus.FAIL
    assert one_miss.p0_stop is True
    # And it is never *blocked*: a P0 stop and a blocking floor are different instructions.
    assert metric(name, 0, 484).outcome != corpus.BLOCKED


@pytest.mark.parametrize("numerator, expected, p0, blocked", [
    pytest.param(100, corpus.PASS, False, False, id="1.00"),
    pytest.param(95, corpus.PASS, False, False, id="exactly-0.95"),
    pytest.param(94, corpus.FAIL, False, False, id="just-under-0.95"),
    pytest.param(90, corpus.FAIL, False, False, id="exactly-0.90-fails-but-does-not-block"),
    pytest.param(89, corpus.BLOCKED, False, True, id="just-under-0.90-blocks"),
])
def test_code_recall_at_the_three_boundaries(numerator, expected, p0, blocked):
    """AC: ≥ 0.95 passes; [0.90, 0.95) fails and is not a P0 stop; < 0.90 marks the run blocked."""
    measured = metric("code_recall", numerator, 100)

    assert measured.value == pytest.approx(numerator / 100)
    assert measured.outcome == expected
    assert measured.p0_stop is p0
    assert (measured.outcome == corpus.BLOCKED) is blocked


@pytest.mark.parametrize("name", ["alarm_label_hit", "xref_resolve"])
@pytest.mark.parametrize("numerator, expected", [
    pytest.param(99, corpus.PASS, id="exactly-0.99"),
    pytest.param(98, corpus.FAIL, id="just-under-0.99"),
])
def test_the_two_point_nine_nine_gates(name, numerator, expected):
    """AC: `alarm_label_hit ≥ 0.99` and `xref_resolve ≥ 0.99`, at the boundary itself."""
    measured = metric(name, numerator, 100)

    assert measured.outcome == expected
    assert measured.p0_stop is False


def test_nothing_measured_is_never_a_perfect_score():
    """`0/0 = 1` is the one arithmetic accident that turns an empty corpus into a green gate."""
    empty = metric("code_precision", 0, 0)

    assert empty.value is None
    assert empty.outcome == corpus.SKIP
    assert empty.p0_stop is False


def test_a_set_too_small_to_evidence_its_gate_says_so():
    """Four cross-reference tokens can FAIL a 0.99 gate and cannot evidence it."""
    small = metric("xref_resolve", 4, 4)
    large = metric("xref_resolve", 6878, 6880)

    assert small.outcome == corpus.PASS and small.underpowered
    assert small.resolution == pytest.approx(0.25)
    assert large.outcome == corpus.PASS and not large.underpowered
    # A `= 1.00` gate has no tolerance to be coarser than, so it is reported with its `n` and
    # never labelled underpowered.
    assert not metric("code_precision", 4, 4).underpowered


def test_a_report_that_measured_nothing_is_not_a_pass():
    """Every set skipping by name is honest output and it is not a green run (§12.6)."""
    all_skipped = corpus.Report(
        doc_id="SYN-M1", revision="1.0", collection="c",
        metrics=tuple(corpus.Metric(name=name, set_name="s", gate=gate(name),
                                    skip_reason="no ground truth")
                      for name in corpus.D11),
    )

    assert all_skipped.failed == ()
    assert len(all_skipped.skipped) == len(corpus.D11)
    assert not all_skipped.ok


# ── C10: what a re-baseline has to carry, and what it may never buy ─────────────────────────────

def test_no_gate_is_re_baselined_in_this_release():
    """§12.6 re-baselines from the M2b measurement; M2b's re-bill is U013 and is blocked on OQ-1."""
    assert dict(corpus.REBASELINED) == {}
    assert all(not in_force.moved for in_force in corpus.gates().values())


@pytest.mark.parametrize("record, because", [
    pytest.param(corpus.Rebaseline(floor=0.90, measured_on="M2b", measurement="0.93",
                                   rationale=""), "rationale", id="no-rationale"),
    pytest.param(corpus.Rebaseline(floor=0.90, measured_on="M2b", measurement="",
                                   rationale="TC1E-SF rates lower"), "measurement",
                 id="no-measurement"),
    pytest.param(corpus.Rebaseline(floor=0.90, measured_on="", measurement="0.93",
                                   rationale="TC1E-SF rates lower"), "measured on",
                 id="no-corpus"),
])
def test_a_re_baseline_without_its_record_is_refused(record, because):
    """AC: *"a re-baseline attempt without [a recorded rationale] fails"* — C10, in one place."""
    with pytest.raises(corpus.RebaselineRefused) as refusal:
        corpus.gates({"code_recall": record})

    assert because in str(refusal.value)
    assert "code_recall" in str(refusal.value)


def test_a_re_baseline_that_moves_nothing_is_refused():
    """A record that lands on D11's own number leaves a note claiming a decision was taken."""
    with pytest.raises(corpus.RebaselineRefused, match="moves nothing"):
        corpus.gates({"code_recall": corpus.Rebaseline(
            floor=0.95, measured_on="M2b", measurement="0.97", rationale="confirmed")})


def test_no_rationale_buys_a_precision_under_one():
    """§12.6: precision is a **safety property**, not a measured target — this is not re-baselinable."""
    with pytest.raises(corpus.RebaselineRefused, match="safety property"):
        corpus.gates({"code_precision": corpus.Rebaseline(
            floor=0.99, measured_on="M2b", measurement="0.994",
            rationale="two register rows disagree with the page text")})


def test_a_re_baseline_under_the_blocking_floor_is_refused():
    """A gate that fails nothing above D11's blocking line is not a gate."""
    with pytest.raises(corpus.RebaselineRefused, match="blocks below"):
        corpus.gates({"code_recall": corpus.Rebaseline(
            floor=0.85, measured_on="M2b", measurement="0.87", rationale="measured at scale")})


def test_a_re_baseline_of_a_metric_12_6_does_not_have_is_refused():
    """A gate nothing measures cannot be reviewed, so it cannot be moved."""
    with pytest.raises(corpus.RebaselineRefused, match="not one of"):
        corpus.gates({"answer_similarity": corpus.Rebaseline(
            floor=0.8, measured_on="M2b", measurement="0.82", rationale="asked for by a reader")})


def test_a_complete_re_baseline_moves_the_gate_and_is_printed_with_its_rationale(capsys):
    """AC: *"any threshold re-baselined … carries a recorded rationale in the report"*."""
    record = corpus.Rebaseline(
        floor=0.90, measured_on="M2b · TC1E-SF@1.3, 55 pages",
        measurement="code_recall 0.9273 (51/55)",
        rationale="the pilot's two scanned pages carry 4 printed codes the text layer cannot "
                  "reach; 0.95 would quarantine every document with a photocopied insert")
    moved = corpus.gates({"code_recall": record})["code_recall"]

    assert moved.moved and moved.bound.floor == 0.90
    assert moved.origin.floor == 0.95
    # The blocking floor travels with it, unchanged: a re-baseline moves a target, not the block.
    assert moved.bound.block_below == 0.90
    assert corpus.Metric(name="code_recall", set_name="s", gate=moved,
                         numerator=91, denominator=100).outcome == corpus.PASS

    corpus.print_report(corpus.Report(
        doc_id="TC1E-SF", revision="1.3", collection="c",
        metrics=(corpus.Metric(name="code_recall", set_name="component_register", gate=moved,
                               numerator=91, denominator=100),)))

    output = capsys.readouterr().out
    assert "re-baselined 0.95 → 0.90 on M2b · TC1E-SF@1.3, 55 pages" in output
    assert "code_recall 0.9273 (51/55)" in output
    assert "quarantine every document with a photocopied insert" in output


# ── the command, against the M1 corpus ──────────────────────────────────────────────────────────

def test_the_report_prints_one_row_per_metric_with_its_gate_and_a_verdict(run, capsys):
    """AC: *"one row per §12.6 set with its metric, its D11 gate and PASS/FAIL"*, exit 0."""
    code = run()

    output = capsys.readouterr().out
    assert code == cli.EXIT_OK, output
    table = verdicts(output)
    assert set(table) == set(corpus.D11), output
    assert table["code_precision"] == corpus.PASS
    assert table["code_recall"] == corpus.PASS
    assert table["abstention_correctness"] == corpus.PASS
    assert table["xref_resolve"] == corpus.PASS
    # Every set §12.6 names is on the table, and so is each gate as the spec words it.
    for set_name in corpus.SETS:
        assert set_name in output
    assert "= 1.00" in output and "≥ 0.95, block <0.90" in output and "≥ 0.99" in output
    assert "corpus: 4 measured, 0 failed, 1 skipped — PASS" in output


def test_the_two_ratios_are_measured_over_the_register_the_file_states(run, capsys):
    """The denominators are the ground truth's, and the one miss is named with its reason."""
    run()

    output = flat(capsys.readouterr().out)
    register = shipped_truth()["component_register"]["rows"]
    assert f"/{len(register)}" in output, output
    # K404 is printed on the photocopied insert, whose text layer is untrusted (§5.7): a recall
    # miss the corpus caused, and the report has to say which of the two it is.
    assert "missed K404 → SYN-M1@1.0#p010" in output
    assert "text layer is untrusted" in output and "vlm_codes" in output


def test_the_near_miss_set_is_100_codes_and_must_be_perfect(run, capsys):
    """AC: `abstention_correctness` over §12.4's 100-sample set, and it must be exactly 1.00."""
    run()

    output = capsys.readouterr().out
    assert "abstention_correctness   near_miss" in output
    assert "1.0000  100/100" in output
    assert "OQ-4" in output          # derived from the inventory; the 8,414-pair list is not needed


def test_a_set_with_no_ground_truth_skips_by_name_and_does_not_fail_the_run(run, capsys):
    """Edge case: *"a set with no ground truth … must skip with a named reason, never silently pass"*."""
    code = run()

    output = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert verdicts(output)["alarm_label_hit"] == corpus.SKIP
    assert "SKIP · SYN-M1 prints no alarm numbers at all" in flat(output)
    assert ", 1 skipped" in output
    # A skip is not a pass: it is excluded from the measured count as well as from the failures.
    assert "4 measured" in output


def test_one_wrong_page_is_a_p0_stop_that_names_the_code_and_the_page(run, capsys, tmp_path):
    """AC: `code_precision < 1.00` prints a P0 STOP naming every offending code and page, exit ≠ 0.

    The break is made in the ground truth, which is where a real disagreement arrives: the
    register is edited to place `K158` on p002. `lookup` still answers p001, correctly, and the
    eval's job is to call that pair wrong and stop — the negative control for every green
    precision row above.
    """
    def move_k158(document):
        for row in document["component_register"]["rows"]:
            if row["code"] == "K158":
                row["page_ids"] = ["SYN-M1@1.0#p002"]

    code = run("--truth", truth_file(tmp_path, move_k158))

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED, output
    assert verdicts(output)["code_precision"] == corpus.FAIL
    assert "P0 STOP" in output
    assert "K158 → SYN-M1@1.0#p001" in output
    assert "precision is a safety property and must be perfect" in output
    assert "do not re-baseline it" in output
    assert "— FAIL" in output


def test_recall_between_the_two_floors_fails_without_stopping_the_world(run, capsys, tmp_path):
    """AC: a value in [0.90, 0.95) fails the gate and is **not** a P0 stop."""
    def add_one_unprinted_code(document):
        document["component_register"]["rows"].append(
            {"code": "K777", "page_ids": ["SYN-M1@1.0#p002"]})

    code = run("--truth", truth_file(tmp_path, add_one_unprinted_code))

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED, output
    table = verdicts(output)
    assert table["code_recall"] == corpus.FAIL
    assert table["code_precision"] == corpus.PASS          # nothing wrong was returned
    assert "19/21" in output
    assert "P0 STOP" not in output
    assert "BLOCKED —" not in output


def test_recall_under_0_90_marks_the_run_blocked(run, capsys, tmp_path):
    """AC: `code_recall < 0.90` marks the run **blocked**, which is worse than a failed target."""
    def add_four_unprinted_codes(document):
        document["component_register"]["rows"] += [
            {"code": f"K77{n}", "page_ids": ["SYN-M1@1.0#p002"]} for n in range(4)]

    code = run("--truth", truth_file(tmp_path, add_four_unprinted_codes))

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED, output
    assert verdicts(output)["code_recall"] == corpus.BLOCKED
    assert "BLOCKED — D11 blocks the run below these floors" in output
    assert "code_recall 0.7917 < 0.90" in output
    assert "P0 STOP" not in output


def test_a_cross_reference_that_stops_resolving_fails_its_gate(run, capsys, tmp_path):
    """The `xref_resolve` negative control: one citation pointed at a page it does not open."""
    def break_a_citation(document):
        document["cross_references"]["tokens"][0]["page_ids"] = ["SYN-M1@1.0#p029"]

    code = run("--truth", truth_file(tmp_path, break_a_citation))

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED, output
    assert verdicts(output)["xref_resolve"] == corpus.FAIL
    assert "3/4" in output
    assert "missed 13 → SYN-M1@1.0#p029" in output


def test_the_bracketed_citation_is_in_the_set_and_resolves(run, capsys):
    """p008 prints no number of its own, so §6.5's bracket is the only way that token resolves."""
    run()

    output = capsys.readouterr().out
    assert verdicts(output)["xref_resolve"] == corpus.PASS
    assert "4/4" in output
    tokens = shipped_truth()["cross_references"]["tokens"]
    assert any(row["page_ids"] == ["SYN-M1@1.0#p008"] for row in tokens)


def test_the_r4_threshold_is_re_validated_against_the_corpus_the_report_read(run, capsys):
    """Risk R4: this report is where the bar set from 55 pages is re-checked at corpus scale.

    On a hand-written corpus the honest answer is that it sets no threshold at all, and
    `recommend` refuses by name rather than proposing one off a construction.
    """
    run()

    output = flat(capsys.readouterr().out)
    assert "R4 — the grounded_rate publish bar" in output
    assert "pin: 0.8" in output
    assert "not written by the pinned extractor (probe_version: hand-written-m1)" in output
    assert "This sets no threshold" in output
    assert "recommendation: no change" in output


def test_the_paths_the_ported_baseline_cannot_cover_are_printed_beside_the_metrics(run, capsys):
    """Risk R7: a green corpus report is not sign-off on the §7/§8 paths `impl` never exercised."""
    run()

    output = capsys.readouterr().out
    assert "NO LEGACY COVERAGE" in output
    assert "A green report above is not sign-off on these" in output


def test_the_report_says_the_corpus_is_not_the_held_out_canary(run, capsys):
    """§12.2 L5 asks for a document nobody tuned against, and the M1 corpus is not one."""
    run()

    output = capsys.readouterr().out
    assert "held out: NO" in output
    assert "§12.2 L5 asks for a document nobody tuned against" in output


# ── refusals: a report with no evidence is never a pass ─────────────────────────────────────────

def test_a_missing_ground_truth_file_is_a_named_refusal(run, capsys, tmp_path):
    """No truth, no report — and the refusal names the variable that relocates the file."""
    code = run("--truth", str(tmp_path / "nowhere"))

    output = flat(capsys.readouterr().out)
    assert code == cli.EXIT_REFUSED
    assert "corpus report refused" in output
    assert corpus.TRUTH_ENV in output
    assert "corpus: not measured" in output
    assert "PASS" not in output


def test_an_empty_set_with_no_stated_reason_is_refused_rather_than_skipped(tmp_path):
    """§12.6 allows a set to be missing and does not allow it to be silent."""
    def silence_the_register(document):
        document["component_register"] = {"rows": []}

    with pytest.raises(corpus.TruthInvalid, match="no `unavailable` reason"):
        corpus.load(truth_file(tmp_path, silence_the_register))


def test_a_ground_truth_row_about_another_document_is_refused(tmp_path):
    """A row pointing elsewhere would score `lookup` against a page it was never asked about."""
    def point_at_another_binder(document):
        document["component_register"]["rows"][0]["page_ids"] = ["TC1E-SF@1.3#p008"]

    with pytest.raises(corpus.TruthInvalid, match="ground truth for SYN-M1@1.0"):
        corpus.load(truth_file(tmp_path, point_at_another_binder))


def test_an_unindexed_collection_refuses_instead_of_reporting_nothing(run, capsys):
    """`--corpus indexed` with nothing published: a refusal, never `0 failed`."""
    code = run("--corpus", "indexed")

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED
    assert "does not exist" in output
    assert "corpus: not measured" in output


def test_the_indexed_corpus_is_measured_when_one_is_published(run, capsys, clean):
    """The L5 shape: point it at a published collection and it reports on what is there."""
    served = f"{COLLECTION}_{EMBED_DIM}"
    pages = synthetic.load()
    synthetic.seed(clean, served, pages.records(release_id="test-0"), dim=EMBED_DIM)
    try:
        code = run("--corpus", "indexed")

        output = capsys.readouterr().out
        assert code == cli.EXIT_OK, output
        assert f"SYN-M1@1.0 in {served}" in output
        assert verdicts(output)["code_precision"] == corpus.PASS
    finally:
        clean.delete_collection(served)


# ── what the command must never do ──────────────────────────────────────────────────────────────

def payload_digest(client: QdrantClient, collection: str) -> tuple[int, str]:
    """`(point count, digest of every payload)` — the fingerprint a read-only report must not move."""
    points, _next = client.scroll(collection_name=collection, limit=4096, with_payload=True,
                                  with_vectors=False)
    ordered = sorted((str(point.id), json.dumps(point.payload, sort_keys=True, default=str))
                     for point in points)
    return (client.count(collection, exact=True).count,
            hashlib.sha256(json.dumps(ordered).encode("utf-8")).hexdigest())


@pytest.mark.parametrize("arguments", [
    pytest.param((), id="synthetic"),
    pytest.param(("--corpus", "indexed"), id="indexed"),
])
def test_the_report_leaves_the_published_index_byte_identical(run, capsys, clean, arguments):
    """AC: *"it reads the published index only"* — a point count and payload hash either side."""
    served = f"{COLLECTION}_{EMBED_DIM}"
    pages = synthetic.load()
    synthetic.seed(clean, served, pages.records(release_id="test-0"), dim=EMBED_DIM)
    try:
        before = payload_digest(clean, served)

        run(*arguments)
        capsys.readouterr()

        assert payload_digest(clean, served) == before
        for name in EPHEMERAL:
            assert not clean.collection_exists(name), f"{name} was left behind"
    finally:
        clean.delete_collection(served)


def test_the_report_makes_zero_vlm_calls(run, capsys, monkeypatch):
    """AC: *"zero ingest steps and … zero VLM calls (asserted by a call spy)"*.

    The spy is on the boundary itself — `vsir.vlm.backend` is the one function that hands out a
    backend, and both backends' `generate` are wrapped under it — so a call through *any* path,
    live or replayed, is recorded. Zero, on the run that produces the whole report.
    """
    calls: list[str] = []
    monkeypatch.setattr(vlm, "backend", lambda cfg: calls.append("backend"))
    monkeypatch.setattr(vlm.GeminiBackend, "generate",
                        lambda self, request: calls.append("gemini"))
    monkeypatch.setattr(vlm.StubBackend, "generate", lambda self, request: calls.append("stub"))

    assert run() == cli.EXIT_OK, capsys.readouterr().out
    capsys.readouterr()

    assert calls == []


def test_the_report_runs_no_ingest_step(run, capsys, monkeypatch):
    """AC: *"the command triggers **zero** ingest steps"* — §11.4, it reads what ingest emitted.

    Spied at the four steps that cost something or write something: the probe, the S2 extraction,
    the embedder and the upsert. A report that re-derived a page instead of reading it would trip
    one of them, and on a real corpus it would also bill for it.
    """
    from vsir.ingest import embed as embed_module
    from vsir.ingest import extract as extract_module
    from vsir.ingest import index as index_module
    from vsir.ingest import probe as probe_module

    ran: list[str] = []
    steps = ((probe_module, "page_texts"), (extract_module, "extract"),
             (embed_module, "embed_document"), (index_module, "upsert"))
    for module, name in steps:
        # Named rather than guarded with `hasattr`: a renamed step must break this spy loudly,
        # or the assertion below quietly stops watching anything.
        assert hasattr(module, name), f"{module.__name__}.{name} is gone — re-point the spy"
        monkeypatch.setattr(module, name,
                            lambda *a, _step=f"{module.__name__}.{name}", **k:
                            ran.append(_step))

    assert run() == cli.EXIT_OK, capsys.readouterr().out
    capsys.readouterr()

    assert ran == []


def test_the_corpus_eval_cannot_reach_a_model_at_all():
    """The structural half: `vsir.vlm` is not in this module's import graph, so no run can.

    The same argument `test_no_eval_module_can_reach_a_model_at_all` makes about the other two
    evals. A spy proves *this* run spent nothing; the import graph proves none can.
    """
    imports = set()
    tree = ast.parse(Path(corpus.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert not any(name.startswith("vsir.vlm") for name in imports), imports
    assert not any(name.startswith("vsir.ingest") for name in imports), imports
    assert not any("genai" in name or "google" in name for name in imports), imports


def test_the_command_is_the_name_4_4_publishes():
    """§4.4's row is `vsir eval acceptance | abstention | corpus`, and all three are served now."""
    parser = cli.build_parser()

    for name in ("acceptance", "abstention", "corpus"):
        assert parser.parse_args(["eval", name]).eval == name


def test_the_corpus_gates_run_in_ci_beside_the_abstention_eval():
    """`code_precision` and `abstention_correctness` are P0 stops, so the gates run every commit."""
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "eval_corpus" in workflow
    assert "secrets." not in workflow
