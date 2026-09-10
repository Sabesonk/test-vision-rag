"""L1 — the ported `impl` baseline is the source, byte for byte (Spec §12.1, plan U012).

U012's second risk is the one this file exists for: *"the old-schema responses are silently coerced
into the new schema and the baseline stops being a baseline."* A baseline that something adjusted
is not evidence about anything, so the fixture is asserted against digests recorded at port time —
and against the `impl` tree itself wherever a machine has one mounted.

The suite also asserts the two **properties** the L2 parity and negative suites rest on, locally
and before any of them asks Qdrant: every accepted identifier is printed in its own page's
observable projection, and no withheld raw is. If either ever stops holding, this fast layer says
so rather than a Docker-bound suite failing for a reason that looks like an index problem.
"""
from __future__ import annotations

import json

import pytest

from vsir.core.exact import printed_in
from vsir.core.tok import tok
from vsir.eval import legacy


@pytest.fixture(scope="module")
def baseline() -> legacy.Baseline:
    return legacy.load()


# ── the port is the source ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ported", [
    pytest.param(row, id=row.path) for row in legacy.load().ported
])
def test_every_ported_file_matches_its_recorded_digest(ported, baseline):
    """AC: every ported file's sha256 is the one `--port` recorded for it.

    One row per file rather than one loop, so a corrupted fixture names the file it corrupted.
    """
    path = baseline.source / ported.path

    assert path.is_file(), f"{ported.path} is in SOURCE.json and not in the fixture"
    assert path.stat().st_size == ported.bytes
    assert legacy.sha256_of(path) == ported.sha256


def test_the_ledger_covers_every_file_in_the_fixture(baseline):
    """Nothing arrives in the fixture without a row saying where it came from.

    The digests above only prove the files the ledger *names*; this is the other direction, and it
    is what stops an unported file being added beside the ported ones and read as evidence.
    """
    on_disk = {
        str(path.relative_to(baseline.source))
        for path in baseline.source.rglob("*")
        if path.is_file() and path.name != "SOURCE.json"
    }

    assert on_disk == {row.path for row in baseline.ported}


def test_the_recorded_digests_are_the_impl_tree_s_when_it_is_mounted(baseline):
    """AC: sha256 identical to the `impl/data/raw/` and `impl/data/exports/` sources.

    ``VSIR_IMPL_ROOT`` is absent on any machine that has only this repository, which is the normal
    case and not a reason to assert nothing: the ledger still has to name a real `impl` location
    for every ported file, and the digests above still have to match it.
    """
    root = legacy.impl_root()
    if root is None:
        for row in baseline.ported:
            assert row.source.startswith(("data/raw/", "data/exports/", "INGESTION_WALKTHROUGH")), (
                f"{row.path} claims a source that is not an `impl` artefact: {row.source}"
            )
        return

    for row in baseline.ported:
        source = root / row.source
        if not source.is_file():          # the walkthrough block is extracted, not copied
            continue
        assert legacy.sha256_of(source) == row.sha256, f"{row.path} is not {row.source}"


def test_the_export_run_is_recorded_with_its_reason(baseline):
    """Which of `impl`'s five exports this is, and why — in the fixture, not only in a docstring."""
    ledger = json.loads((baseline.source / "SOURCE.json").read_text(encoding="utf-8"))

    assert ledger["export_run"] == legacy.EXPORT_RUN
    assert "r-poc-3/4" in ledger["export_run_rationale"]
    assert ledger["schema_version"] == baseline.manifest["schema_version"]


# ── the fixture is what §12.1 says it is ────────────────────────────────────────────────────────

@pytest.mark.parametrize("doc_id", legacy.EXPECTED_DOCUMENTS)
def test_all_seven_documents_of_12_1_are_ported(doc_id, baseline):
    """§12.1 counts seven documents' worth of S2 responses. All seven are here."""
    assert baseline.window_paths(doc_id), f"{doc_id} has no ported window"


def test_the_window_counts_are_the_ones_12_1_records(baseline):
    """`TC1E-SF` as 2 windows and `LTC1AV81` as 12 — §12.1, verbatim."""
    assert len(baseline.window_paths("TC1E-SF")) == 2
    assert len(baseline.window_paths("LTC1AV81")) == 12
    assert sum(len(baseline.window_paths(doc)) for doc in legacy.EXPECTED_DOCUMENTS) == 19


def test_the_raw_responses_are_still_the_old_schema(baseline):
    """The port copies; it does not migrate.

    The new schema's four fields are exactly what §12.1 says the ported responses lack, so finding
    one in a ported file would mean something wrote it — and the baseline would be describing this
    system rather than the one it is a baseline for.
    """
    for doc_id in legacy.EXPECTED_DOCUMENTS:
        for path in baseline.window_paths(doc_id):
            body = json.loads(path.read_text(encoding="utf-8"))
            for page in body["pages"]:
                assert set(page) <= {"page_index", "printed_page_no", "page_kind", "lang",
                                     "units", "refs", "identifiers"}, path
                assert "codes" not in page and "sections" not in page
                assert "summaries" not in page and "topics" not in page


def test_the_negative_set_is_model_emitted_codes_and_nothing_else(baseline):
    """§12.1's own words for `withheld.jsonl`: *model-emitted codes the text layer never backed*.

    This is the assertion behind choosing `r-poc-5`. The earlier runs' withheld sets also carry
    `source: "text"` rows — SF labels harvested off the page and then refused by a gate defect the
    last run had already fixed — and a negative set containing strings that **are** printed would
    make the whole suite assert the opposite of what it means to.
    """
    rows = baseline.withheld_rows

    assert rows, "the negative set is empty"
    assert {row["source"] for row in rows} == {"vlm"}
    assert {row["reason"] for row in rows} == {"not_in_text_layer"}


def test_the_export_and_the_manifest_agree_about_every_page(baseline):
    """Every `page_id` in the export parses to a page the manifest says the document has."""
    for row in baseline.labels:
        doc_id = str(row["doc_id"])
        page_id = str(row["page_id"])
        assert page_id == baseline.page_id(doc_id, int(page_id.rsplit("#p", 1)[1]))
        assert 1 <= int(page_id.rsplit("#p", 1)[1]) <= baseline.page_count(doc_id)


def test_a_document_with_no_text_layer_backs_nothing(baseline):
    """`CE-TC1AV8`: scanned, one page, no tokens — so no gate and nothing accepted (§5.7, F4).

    It is in the corpus on purpose. A parity suite whose every document has a text layer never
    exercises the `not_searchable` answer, which is the one absence F4 exists to keep distinct.
    """
    assert baseline.has_text_layer("CE-TC1AV8") is False
    assert baseline.accepted("CE-TC1AV8") == ()
    assert baseline.observable_text("CE-TC1AV8@1.0#p001") == ""


# ── the one page of real text ───────────────────────────────────────────────────────────────────

def test_the_recorded_page_is_the_walkthrough_block(baseline):
    """The only verbatim text layer `impl` wrote down, and the part numbers that make it matter.

    Two of the strings below are §12.3's own acceptance rows — ``EAO 84-5140.0020`` and
    ``B&R X20SI4100`` — and both are codes the old grammar dropped *before* the gate. They are why
    the GAINS list is not empty, so a fixture that quietly lost this block would turn a proven gain
    into an untested claim.
    """
    text = baseline.recorded_text["TC1E-SF@1.3#p001"]

    assert text.startswith("Page 1 of 55")
    for printed in ("SF 1.1A", "EAO 84-5140.0020", "B&R X20SI4100", "C24", "K158"):
        assert printed_in(tok(text), printed), printed


# ── the two properties the L2 suites rest on ────────────────────────────────────────────────────

def test_every_accepted_identifier_is_printed_in_its_own_page_s_projection(baseline):
    """The parity property, asserted locally before Qdrant is asked the same question.

    `core.exact.printed_in` is the same mechanism `exact_filter` sends to the index — variants,
    then a contiguous token run — so a failure here is a failure of `variants()`/`tok()` on a real
    identifier shape, told apart from an indexing problem by being in the fast layer.
    """
    unfindable = [
        (page_id, raw) for page_id, raw in baseline.accepted()
        if not printed_in(tok(baseline.observable_text(page_id)), raw)
    ]

    assert unfindable == []
    assert len(baseline.accepted()) == 1644


def test_no_withheld_raw_is_printed_in_the_projection_of_the_page_it_was_withheld_from(baseline):
    """The negative property (I2, F14): the model said it, the page does not print it.

    Asserted here rather than assumed, because the projection joins the accepted identifiers into
    one string and the WORD tokenizer treats every separator alike — so two adjacent identifiers
    *could* in principle spell a third. On this corpus none of the 96 does, and if a re-port ever
    made one, this is where it says so.
    """
    findable = [
        (page_id, raw) for page_id, raw in baseline.withheld()
        if printed_in(tok(baseline.observable_text(page_id)), raw)
    ]

    assert findable == []
    assert len(baseline.withheld()) == 96


def test_the_r7_no_coverage_list_is_published(baseline):
    """R7 — U012 must publish what parity cannot cover, or a green run reads as sign-off."""
    assert len(legacy.NO_LEGACY_COVERAGE) >= 10
    assert any("§8" in line for line in legacy.NO_LEGACY_COVERAGE)
    assert any("§7.2.3" in line for line in legacy.NO_LEGACY_COVERAGE)


def test_the_whole_baseline_is_built_with_no_network_and_no_api_key(monkeypatch):
    """AC: zero outbound calls, and green with ``GEMINI_API_KEY`` unset.

    U012 is the free unit inside a paid milestone, so *"spends nothing"* is a property worth
    holding a socket against rather than trusting to the stub. Every outbound connection raises
    here, the credential is removed from the environment, and the entire path runs anyway — load,
    placement, derivation, stitching, records, gains — because every byte it needs is a file
    somebody already paid for (§12.1, D10).
    """
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("U012 spends nothing and talks to nothing: an outbound call was made")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    baseline = legacy.load()
    records = baseline.records()

    assert len(records) == 142
    assert baseline.gains()
    assert all(placement.window.pages >= 1
               for doc_id in baseline.doc_ids
               for placement in baseline.placements(doc_id))
