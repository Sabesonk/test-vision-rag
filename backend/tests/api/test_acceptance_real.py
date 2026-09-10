"""L2 — the §12.3 acceptance table on the **real** pilot document, in replay (C10 · plan U013).

`test_acceptance_synthetic.py` asserts the same table against hand-written page text. This file
asserts it against `TC1E-SF`, from the fixture the one paid ingest froze — so the numbers are
measured on a real extraction of a real 55-page manual, and they cost nothing to re-measure on
every commit (§12.1, D10).

**C10 is the shape of this file.** `expected.json` is checked in *ahead of* the ingest, written
from Spec §12.3, and the two halves below treat it differently on purpose:

* the first half runs **today** and asserts the table's own integrity — that every §12.3 row is
  present, that no row contradicts §7.1, and that SA-7's reconciliation is recorded rather than
  quietly applied. A table that drifted from the spec would make every assertion below it
  meaningless, and nothing else checks it;
* the second half runs **once the fixture exists** and asserts the corpus against that table. It
  skips by name until then. The skip is not a permanent hole: U013's Definition of Done is that
  these skips become passes, and the count is printed so a green run is never mistaken for a
  complete one.

Until OQ-1 and OQ-2 close there is no `raw_window_*.json` to replay, and §12.3's PARITY rows are
covered on the ported baseline instead by `test_parity_lookup.py` and `test_withheld_negative_set.py`
— on the observable projection rather than on real text, which is precisely the gap this file
closes when the re-bill happens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from qdrant_client import QdrantClient

from vsir.core import ids
from vsir.eval import synthetic
from vsir.serve.envelope import Provenance, Status
from vsir.serve.tools.lookup import lookup
from vsir.core.verify import verify_claims

EMBED_DIM = 1536
ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(os.environ.get("VSIR_TC1E_FIXTURE") or ROOT / "data" / "fixtures" / "TC1E-SF")
EXPECTED = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
CORPUS = EXPECTED["corpus"]

#: The three artefacts the paid ingest buys. `expected.json` is not among them — it is the spec's.
BOUGHT = ("raw_window_1.json", "raw_window_2.json", "text.json")
MISSING = [name for name in BOUGHT if not (FIXTURE / name).is_file()]
NEEDS_THE_REBILL = pytest.mark.skipif(
    bool(MISSING),
    reason=(f"{', '.join(MISSING)} not in {FIXTURE}: OQ-1 (the pilot PDF) and OQ-2 (a Gemini key) "
            f"are open, so the M2b re-bill has not run. These rows assert real text and cannot be "
            f"faked; §12.3's PARITY rows run meanwhile on data/fixtures/legacy/. U013's DoD is "
            f"that this skip becomes a pass."),
)

PROVENANCE = Provenance(run_id="acceptance-real", release_id="test")


def _rows(kind: str) -> list[dict[str, Any]]:
    return list(EXPECTED[kind])


def _row(label: str) -> dict[str, Any]:
    for row in _rows("lookup"):
        if row["label"] == label:
            return row
    raise KeyError(f"{label} is not a row of the checked-in acceptance table")


# ── the table itself, asserted today, because everything below rests on it (C10) ────────────────

def test_the_table_names_the_pilot_document_at_the_page_count_12_3_states():
    """§12.3's counts are normative for TC1E-SF, and §12.1 says 55 pages over 2 windows."""
    assert CORPUS["doc_id"] == "TC1E-SF"
    assert CORPUS["pages"] == 55
    assert CORPUS["windows"] == 2
    assert CORPUS["window_ranges"] == [[1, 30], [31, 55]]
    assert sum(end - start + 1 for start, end in CORPUS["window_ranges"]) == CORPUS["pages"]


def test_every_lookup_row_of_12_3_is_in_the_table():
    """A row the table lost is a row nothing asserts. The list is §12.3's, verbatim and in order."""
    assert [row["label"] for row in _rows("lookup")] == [
        "SF 1.1A", "SF 5.5b", "SF 121.1", "EAO 84-5140.0020", "B&R X20SI4100", "3", "alarm 152",
    ]


@pytest.mark.parametrize("label", ["SF 1.1A", "SF 5.5b", "SF 121.1"])
def test_the_three_single_page_rows_expect_exactly_one_page(label):
    """§12.3 — any-order matching would give 3, 2 and a wrong page respectively (F1)."""
    row = _row(label)

    assert row["total"] == 1
    assert row["capped"] is False
    assert row["status"] == "ok"


def test_no_row_claims_capped_while_its_total_fits_inside_the_cap():
    """§7.1 and §7.2.2 both define `capped` as `total > cap`, and the response model enforces it.

    This is the assertion SA-7 exists for: §12.3's `EAO 84-5140.0020` row is written
    `total 10 (hits capped at cap, capped:true)`, which at the default `cap=20` cannot be true of
    any response this system can build.
    """
    for row in _rows("lookup"):
        if "capped" not in row:
            continue
        cap = row.get("cap", 20)
        assert row["capped"] == (row["total"] > cap), row["label"]


def test_the_sa_7_reconciliation_is_recorded_rather_than_silently_applied():
    """C10 — changing a number in this table requires a written rationale, in the table."""
    row = _row("EAO 84-5140.0020")
    reconciled = row["reconciled"]

    assert row["total"] == 10                     # unchanged: the count is still normative
    assert row["capped"] is False                 # corrected against §7.1's own definition
    assert reconciled["finding"] == "SA-7"
    assert "capped ⇔ total > cap" in reconciled["authority"]
    assert reconciled["unchanged"] == "total: 10"


def test_the_weak_row_is_a_server_constant_and_holds_at_every_cap():
    """§7.1 — a trust signal a client parameter can flip is worse than none. §12.3: "at ANY cap"."""
    row = _row("3")

    assert row["weak"] is True and row["needs_scope"] is True
    assert row["weak_abs"] == synthetic.load().expected["weak"]["weak_abs"] == 20
    assert row["caps"] == [5, 20, 200]
    assert "cap" not in row


def test_the_absent_row_suggests_a_move_rather_than_returning_a_wrong_page():
    """§12.3 — never a wrong page, never a bare empty 200 (F3, §7.1)."""
    row = _row("alarm 152")

    assert row["status"] == "not_found"
    assert row["hits"] == 0
    assert row["suggest"] == ["skim_pages"]


def test_the_verify_row_is_absent_on_a_page_whose_tokens_are_present():
    """§12.3 — one `exact_filter` answers `verify` and `lookup`, so F2 cannot disagree with F1."""
    row, = _rows("verify")

    assert row["claim"] == "SF 1.1A"
    assert row["status"] == "absent"
    assert row["page_ids"] == [ids.page_id(CORPUS["doc_id"], CORPUS["revision"], 8)]


def test_the_parity_and_negative_sets_point_at_the_baseline_somebody_already_paid_for():
    """§12.1 — the PARITY rows are free because `impl` kept its receipts."""
    assert EXPECTED["parity"]["source"].endswith("labels.jsonl")
    assert EXPECTED["negative_set"]["source"].endswith("withheld.jsonl")
    assert "GAIN" in EXPECTED["parity"]["gains"].upper()


def test_the_table_records_what_it_is_still_waiting_for():
    """The skip below must be legible from the fixture, not only from a pytest summary."""
    assert "U013" in EXPECTED["_status"]
    for name in BOUGHT:
        assert name in EXPECTED["_status"] or name == "text.json" and "text.json" in EXPECTED["_status"]


def test_the_skipped_row_count_is_visible_rather_than_silent():
    """A permanent skip nobody notices is the failure mode this print exists to prevent."""
    if MISSING:
        print(f"\nACCEPTANCE (real): {len(MISSING)} of {len(BOUGHT)} paid artefacts absent "
              f"({', '.join(MISSING)}) — the corpus rows below are SKIPPED, not passed. "
              f"OQ-1/OQ-2.")
    assert set(MISSING) <= set(BOUGHT)


# ── the corpus rows, once the re-bill has happened ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def records():
    """The pilot document's page records, rebuilt from the frozen fixture — no PDF, no VLM.

    Steps 07-08 over the verbatim `WindowOut` bodies and the extractor's own `text.json`, through
    the shipped `derive` and `stitch`. Rebuilding rather than reading a snapshot of the records is
    deliberate: it means this suite re-proves the offset placement and the health signals on real
    data every time it runs, instead of asserting against numbers a previous run wrote down.
    """
    from vsir.ingest import derive as derive_module
    from vsir.ingest import stitch as stitch_module
    from vsir.ingest.extract import Extraction, WindowExtraction, WindowOut
    from vsir.ingest.manifest import Manifest
    from vsir.ingest.probe import PageProbe, Probe
    from vsir.ingest.window import Plan, Window
    from vsir.vlm.cache import Entry

    frozen = json.loads((FIXTURE / "text.json").read_text(encoding="utf-8"))
    probed = Probe(
        page_count=frozen["page_count"], size_bytes=0, content_hash=frozen["content_hash"],
        probe_version=frozen["probe_version"],
        pages=tuple(PageProbe(page_no=page["page_no"], text=page["text"], label=page["label"])
                    for page in frozen["pages"]),
    )
    doc = Manifest(doc_id=CORPUS["doc_id"], revision=CORPUS["revision"], doc_type="manual",
                   subjects=(), tags=(), source=Path(f'{CORPUS["doc_id"]}.pdf'), size_bytes=0,
                   uploader="", revision_declared=True, doc_type_declared=False)
    windows = []
    for number, (start, end) in enumerate(CORPUS["window_ranges"], start=1):
        body = (FIXTURE / f"raw_window_{number}.json").read_text(encoding="utf-8")
        window = Window(start=start, end=end)
        windows.append(WindowExtraction(
            window=window, key=f"raw_window_{number}", out=WindowOut.model_validate_json(body),
            entry=Entry(key=f"raw_window_{number}", namespace="extract", body=body),
        ))
    extraction = Extraction(plan=Plan(level=0, windows=tuple(w.window for w in windows)),
                            windows=tuple(windows))
    derived = derive_module.derive(extraction, probed=probed, doc=doc, run_id="acceptance-real",
                                   release_id="test", vlm_model="frozen",
                                   prompt_version="s2-v1", dpi=220)
    stitched = stitch_module.stitch(derived.pages, doc_id=doc.doc_id, revision=doc.revision)
    return tuple(record.model_copy(update={"is_current": True}) for record in stitched.pages)


@pytest.fixture(scope="module")
def seeded(qdrant: QdrantClient, records) -> str:
    """The rebuilt corpus in a collection of its own, dropped at the end of the module."""
    collection = synthetic.synthetic_collection("vsir_pages_real", EMBED_DIM)
    synthetic.seed(qdrant, collection, records, dim=EMBED_DIM)
    try:
        yield collection
    finally:
        synthetic.drop(qdrant, collection)


@pytest.fixture
def ask(qdrant: QdrantClient, seeded: str):
    def _ask(label: str, **kwargs: Any):
        return lookup(qdrant, seeded, label, provenance=PROVENANCE, **kwargs)
    return _ask


@NEEDS_THE_REBILL
def test_the_fixture_rebuilds_to_fifty_five_pages(records):
    """C10 — a page count that disagrees with §12.3 is a blocking finding, not a re-baseline."""
    assert len(records) == CORPUS["pages"]
    assert [record.page_no for record in records] == list(range(1, CORPUS["pages"] + 1))


@NEEDS_THE_REBILL
@pytest.mark.parametrize("label", ["SF 1.1A", "SF 5.5b", "SF 121.1"])
def test_a_single_page_row_finds_exactly_that_page_on_real_text(ask, label):
    row = _row(label)

    response = ask(label)

    assert response.status is Status.OK, f'{label}: §12.3 says exactly {row["total"]}'
    assert response.total == row["total"]
    assert response.capped is row["capped"]


@NEEDS_THE_REBILL
def test_the_ten_hit_row_is_not_capped_at_the_default_cap(ask):
    """SA-7, measured: `capped` is `total > cap` and 10 is not more than 20 (§7.1)."""
    row = _row("EAO 84-5140.0020")

    response = ask(row["label"], cap=row["cap"])

    assert response.total == row["total"]
    assert response.capped is False
    assert len(response.hits) == row["total"]


@NEEDS_THE_REBILL
def test_the_fifty_four_hit_row_is_capped_and_reports_the_whole_set(ask):
    """§7.1 — `total` is the SET size, not `len(hits)`."""
    row = _row("B&R X20SI4100")

    response = ask(row["label"], cap=row["cap"])

    assert response.total == row["total"]
    assert response.capped is True
    assert len(response.hits) == row["hits"] == row["cap"]


@NEEDS_THE_REBILL
@pytest.mark.parametrize("cap", _row("3")["caps"])
def test_the_weak_row_is_weak_at_every_cap(ask, cap):
    """§7.1 — WEAK_ABS is a server constant; the caller's `cap` cannot flip a trust signal."""
    response = ask("3", cap=cap)

    assert response.weak is True
    assert response.needs_scope is True


@NEEDS_THE_REBILL
def test_the_absent_row_abstains_and_suggests_a_move(ask):
    row = _row("alarm 152")

    response = ask(row["label"])

    assert response.status is Status.NOT_FOUND
    assert response.hits == []
    assert response.next is not None and list(response.next.suggest) == row["suggest"]


@NEEDS_THE_REBILL
def test_verify_is_absent_where_the_tokens_are_present_and_the_phrase_is_not(qdrant, seeded):
    row, = _rows("verify")

    result = verify_claims(qdrant, seeded, [row["claim"]], page_ids=row["page_ids"])

    verdict = result.claims[row["claim"]]
    assert verdict.status == row["status"]
    assert verdict.page_ids == row["page_ids"]


@NEEDS_THE_REBILL
def test_every_identifier_the_old_gate_accepted_is_still_findable_on_real_text(ask):
    """§12.3's PARITY row, on the real extraction rather than on the projection (R7)."""
    from vsir.eval import legacy

    baseline = legacy.load()
    misses = [raw for page_id, raw in baseline.accepted(CORPUS["doc_id"])
              if page_id not in [hit.page_id for hit in ask(raw).hits]]

    assert misses == [], f"{len(misses)} identifier(s) the old gate accepted are no longer findable"


@NEEDS_THE_REBILL
def test_every_withheld_raw_is_unfindable_in_the_text_surface(ask):
    """§12.3's negative set — model-emitted codes the text layer never backed (I2, F14)."""
    from vsir.eval import legacy

    baseline = legacy.load()
    leaked = [raw for _page_id, raw in baseline.withheld(CORPUS["doc_id"]) if ask(raw).hits]

    assert leaked == [], f"{len(leaked)} withheld code(s) reached the exact surface"
