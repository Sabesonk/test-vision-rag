"""L4 — the one paid ingest of the pilot document (Spec §13 M2b, §12.1, C10, R4 · plan U013).

This is the only test in the repository that may spend money, and it is meant to run **once**.
What it buys is not a passing assertion: it is `data/fixtures/TC1E-SF/`, the frozen corpus that
makes every level from M3 onward free forever (§12.1). Everything else in the suite replays.

Three gates stand in front of it, in this order, and each refuses by name rather than failing
somewhere inside a billed call:

* ``VSIR_ALLOW_PAID=1`` — `scripts/test-paid.sh` refuses without it, and so does this module, so a
  bare ``pytest tests/paid`` cannot spend either;
* the pilot PDF at ``data/source/TC1E-SF.pdf`` — **OQ-1**, still open at the time of writing;
* ``VSIR_VLM_KEY`` — **OQ-2**. A paid layer with no credential would fail per call, after billing
  whatever it managed to send.

**C10 is the reason `expected.json` is checked in ahead of this run.** The acceptance numbers were
written from Spec §12.3 before anything was ingested, so this test compares reality against the
spec rather than recording reality as the spec. A disagreement here is a **blocking finding** —
an offset or a tokenisation defect until proven a corpus difference — and changing a number in
that file requires a recorded rationale in the run report. A test that re-baselined its own
expectations would be a safety net that quietly cuts itself down.

**R4 is the other half.** The run's `grounded_rate` distribution is reported by
`vsir.eval.grounded_rate`, and the threshold `core/health.py` pins is set from it — by a release,
not by this test, which asserts only that the measurement exists and is a measurement.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from vsir.cli import main as cli_main
from vsir.config import load_config
from vsir.eval import grounded_rate as distribution_module
from vsir.ingest import gates as gates_module
from vsir.ingest import run as run_module
from vsir.vlm.cache import EXTRACT, FixtureStore

pytestmark = pytest.mark.paid

ROOT = Path(__file__).resolve().parents[3]
PILOT_PDF = Path(os.environ.get("VSIR_PILOT_PDF") or ROOT / "data" / "source" / "TC1E-SF.pdf")
FIXTURE = Path(os.environ.get("VSIR_TC1E_FIXTURE") or ROOT / "data" / "fixtures" / "TC1E-SF")
EXPECTED = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
DOC_ID = EXPECTED["corpus"]["doc_id"]
REVISION = EXPECTED["corpus"]["revision"]

if os.environ.get("VSIR_ALLOW_PAID") != "1":
    pytest.skip("VSIR_ALLOW_PAID is not 1 — this module spends money and refuses to run without "
                "the explicit opt-in (§12.2)", allow_module_level=True)
if not PILOT_PDF.is_file():
    pytest.skip(f"OQ-1 is open: the pilot PDF is not at {PILOT_PDF}. The operator places it there "
                f"(data/source/ stays gitignored) or points VSIR_PILOT_PDF at it. Until then M2b's "
                f"re-bill cannot run and every other level replays off data/fixtures/legacy/ and "
                f"data/fixtures/synthetic_3window/ (§17, D10)", allow_module_level=True)
if not (os.environ.get("VSIR_VLM_KEY") or "").strip():
    pytest.skip("OQ-2 is open: VSIR_VLM_KEY is unset. A paid layer with no credential fails per "
                "call, after billing whatever it managed to send (§17)", allow_module_level=True)


@pytest.fixture(scope="module")
def cfg():
    """The process configuration, with the live backend selected — never a code branch (§15 X)."""
    os.environ["VSIR_VLM"] = "gemini"
    # Replay must not shadow the call this module exists to make: a fixture directory left in the
    # environment would serve the previous run's answers and the re-bill would buy nothing.
    os.environ.pop("VSIR_FIXTURE", None)
    return load_config()


@pytest.fixture(scope="module")
def store(cfg) -> QdrantClient:
    client = QdrantClient(url=cfg.qdrant_url, timeout=60, check_compatibility=False)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="module")
def ingested(cfg, store: QdrantClient) -> run_module.RunRecord:
    """The one paid run: S2 and the embeddings, once, recording as it goes.

    ``--record`` is what makes this a purchase rather than an expense (§12.1): the same pass that
    publishes the document freezes every verbatim body under its §6.3 key, so the next level to
    ask the same question replays instead of paying.
    """
    exit_code = cli_main([
        "ingest", str(PILOT_PDF),
        "--vlm", "gemini",
        "--record", str(FIXTURE),
        "--doc-id", DOC_ID,
        "--revision", REVISION,
    ])
    assert exit_code == 0, "the paid ingest did not complete — see the refusal code it printed"
    runs = run_module.runs(store, cfg.runs_collection, doc_id=DOC_ID)
    assert runs, f"no run point for {DOC_ID} in {cfg.runs_collection}"
    return runs[0]


# ── the acceptance criteria of §13 M2b ──────────────────────────────────────────────────────────

def test_the_run_publishes_every_page_of_the_pilot_document(ingested):
    """§13 M2b — 55 points published, and the page count is the spec's, not the run's."""
    assert ingested.state == run_module.PUBLISHED
    assert ingested.page_count == EXPECTED["corpus"]["pages"]
    assert ingested.pages_indexed == EXPECTED["gates"]["pages_indexed"]


def test_the_published_points_are_the_current_revision_and_there_are_fifty_five(cfg, store,
                                                                                ingested):
    """I7 — points are written `is_current=False` and only the publish gates flip them."""
    from qdrant_client.http import models as qm

    count = store.count(cfg.pages_collection, exact=True, count_filter=qm.Filter(must=[
        qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=DOC_ID)),
        qm.FieldCondition(key="revision", match=qm.MatchValue(value=REVISION)),
        qm.FieldCondition(key="is_current", match=qm.MatchValue(value=True)),
    ])).count

    assert count == EXPECTED["corpus"]["pages"]


def test_window_coverage_is_one_and_both_windows_pass_the_offset_proof(ingested):
    """§11.1's two blocking gates, on real data. I4/F7 — never pad, never guess."""
    report = ingested.report

    assert report[gates_module.WINDOW_COVERAGE].metric == EXPECTED["gates"]["window_coverage"]
    assert report[gates_module.WINDOW_COVERAGE].passed is True
    assert report[gates_module.OFFSET_CHECK].passed is True


def test_the_frozen_fixture_holds_a_receipt_for_every_window(ingested):
    """§12.1 — what the re-bill buys. A window with no frozen body is a level that must pay
    again, which is the one thing D10 says no level may ever require."""
    store = FixtureStore(FIXTURE)
    frozen = [path for path in store.directory(EXTRACT).glob("*.json")
              if not path.name.endswith(".meta.json")]

    assert len(frozen) == ingested.windows_total == EXPECTED["corpus"]["windows"]
    assert (FIXTURE / "text.json").is_file()


def test_the_named_window_files_of_12_1_carry_the_verbatim_bodies(ingested):
    """§12.1 names `raw_window_1.json` (pages 1-30) and `raw_window_2.json` (31-55).

    They are the same bytes as the key-addressed receipts beside them, under the names the spec's
    fixture tree uses: replay selects by key (§6.3), a reader selects by window. Written here
    rather than by the recorder because the window *ordering* is the plan's, not the cache's.
    """
    frozen = sorted(
        (path for path in FixtureStore(FIXTURE).directory(EXTRACT).glob("*.json")
         if not path.name.endswith(".meta.json")),
        key=lambda path: json.loads(path.read_text(encoding="utf-8"))["pages"][0]["page_index"],
    )
    for number, (path, window) in enumerate(zip(frozen, EXPECTED["corpus"]["window_ranges"]), 1):
        named = FIXTURE / f"raw_window_{number}.json"
        named.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        body = json.loads(named.read_text(encoding="utf-8"))
        assert len(body["pages"]) == window[1] - window[0] + 1, f"window {number} is {window}"

    assert (FIXTURE / "raw_window_1.json").is_file()
    assert (FIXTURE / "raw_window_2.json").is_file()


def test_re_running_the_identical_ingest_replays_and_costs_nothing(cfg, store, ingested):
    """§12.1's promise, measured: every window is an `extract_key` hit and nothing is billed.

    It runs in replay against the fixture the first pass just froze, which is the only honest test
    of that fixture: if a key differed by one byte the run would be a typed `fixture_miss` (D10),
    not a silent second purchase.
    """
    exit_code = cli_main([
        "ingest", str(PILOT_PDF),
        "--vlm", "stub", "--fixture", str(FIXTURE),
        "--doc-id", DOC_ID, "--revision", REVISION,
    ])

    assert exit_code == 0
    replayed = run_module.runs(store, cfg.runs_collection, doc_id=DOC_ID)[0]
    assert replayed.run_id != ingested.run_id
    assert replayed.cost.vlm_calls == 0
    assert replayed.cost.cache_hits == EXPECTED["corpus"]["windows"] + 1   # the windows, and S1
    assert replayed.cost.embeddings_billed == 0
    assert replayed.cost.embeddings_reused == EXPECTED["corpus"]["pages"]


# ── R4 · the distribution the gate threshold is set from ────────────────────────────────────────

def test_the_grounded_rate_distribution_is_a_measurement_and_is_reported(cfg, store, ingested):
    """R4 — `grounded_rate ≥ 0.8` is chosen, not derived. This is where it gets derived.

    The report is printed rather than asserted against a number: the threshold is a release
    decision recorded in the run report (§11.1), and a test that asserted a particular median
    would be asserting the corpus rather than the code.
    """
    records = run_module.run_records(store, cfg.pages_collection, doc_id=DOC_ID,
                                     revision=REVISION, run_id=ingested.run_id)
    distribution = distribution_module.from_records(records)

    print(distribution_module.report(distribution))

    assert distribution.page_count == EXPECTED["corpus"]["pages"]
    assert distribution.measured_by_the_extractor is True, (
        "the pages must carry a pymupdf- probe_version: R4 is set from a real ingest")
    assert distribution.median is not None
    assert distribution_module.recommend(distribution).provisional is True


# ── C10 · the acceptance table is compared against, never rewritten ─────────────────────────────

def test_the_acceptance_table_is_not_rewritten_by_this_run():
    """C10 — the numbers were written from §12.3 before the ingest, and this run may not move them.

    The corpus rows themselves are asserted by `tests/api/test_acceptance_real.py`, in replay,
    against the fixture this module froze — which is the point: once the receipts exist, every
    assertion about them is free and runs on every commit.
    """
    checked_in = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))

    assert checked_in == EXPECTED, (
        "expected.json changed during the paid run. C10 makes a disagreement between the table "
        "and the ingest a blocking finding — an offset or tokenisation defect until proven a "
        "corpus difference — and any change needs a recorded rationale in the run report")
