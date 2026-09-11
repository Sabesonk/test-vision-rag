"""`GET /runs` — the ingest history (§6.9).

`GET /runs/{run_id}` has always returned the full record, and it needs a `run_id` the caller
already has. Nothing answered *"what has been ingested, and how did it end"*, so a run whose gates
refused it was invisible unless somebody had kept the id from the `202`.

The row that matters here is **`gated`**. It is not `failed`: the run completed, and §11.1's gates
declined to publish what it produced. That is the outcome the gates exist to produce, and which
gate refused is the entire content of the row — so `failed_gates` names them rather than counting
them.
"""
from __future__ import annotations

import pytest

from vsir.ingest import gates
from vsir.ingest import run as run_module
from vsir.serve import auth as auth_module
from vsir.serve import manage

from conftest import SERVED_RUNS

RUNS = [
    ("r-history-a", "SYN-M1", run_module.PUBLISHED, "11", "2026-09-01T00:00:00+00:00"),
    ("r-history-b", "SYN-M1", run_module.GATED, "10", "2026-09-02T00:00:00+00:00"),
    ("r-history-c", "OTHER-DOC", run_module.FAILED, "07", "2026-09-03T00:00:00+00:00"),
]


@pytest.fixture
def history(qdrant, served) -> None:
    """Three runs in the control plane the served app reads, in a known `updated_at` order.

    Written after ``served`` so the app's own lifespan has created the collection, and removed by
    ``served``'s teardown, which drops the whole runs collection.
    """
    run_module.ensure_control_plane(qdrant, SERVED_RUNS)
    for run_id, doc_id, state, step, stamp in RUNS:
        record = run_module.start(qdrant, SERVED_RUNS, run_id=run_id, doc_id=doc_id,
                                  revision="1.0", release_id="test", collection="c",
                                  page_count=4, windows_total=1, owner="suite")
        update = {"state": state, "step": step, "updated_at": stamp, "pages_indexed": 4,
                  "windows_done": 1}
        if state == run_module.GATED:
            # `pass`, not `passed` — `GateResult.as_dict()` renames it on the way into the run
            # record, so this is the shape the control plane actually holds. Built through
            # `as_dict()` rather than typed out, so the fixture cannot drift from the writer.
            update["gate_results"] = {
                "grounded_rate": gates.GateResult(
                    name="grounded_rate", passed=False, blocking=True,
                    detail="below threshold", metric=0.61, threshold=0.8).as_dict(),
                "window_coverage": gates.GateResult(
                    name="window_coverage", passed=True, blocking=True,
                    detail="covered").as_dict(),
            }
        run_module.save(qdrant, SERVED_RUNS, record.model_copy(update=update))


def test_the_history_needs_a_bearer_token(served):
    """A run record names documents and costs — free to nobody (§7.4)."""
    assert "/runs" not in auth_module.PUBLIC_PATHS
    assert served.get("/runs").status_code == 401


def test_the_history_is_newest_first(served, token_header, history):
    """The order somebody scanning a history wants, and the order they should not have to ask for."""
    body = served.get("/runs", headers=token_header).json()

    assert body["total"] == 3
    assert [row["run_id"] for row in body["runs"]] == ["r-history-c", "r-history-b",
                                                       "r-history-a"]


def test_a_gated_run_names_the_gate_that_refused_it(served, token_header, history):
    """`gated` is not `failed`, and *which* gate is the whole content of the row (§11.1)."""
    body = served.get("/runs?state=gated", headers=token_header).json()

    assert body["total"] == 1
    row = body["runs"][0]
    assert row["run_id"] == "r-history-b"
    assert row["state"] == "gated"
    assert row["failed_gates"] == ["grounded_rate"]      # and not the one that passed
    assert row["published_at"] is None


def test_a_published_run_carries_its_publish_stamp_and_no_failed_gate(served, token_header,
                                                                     history):
    body = served.get("/runs?state=published", headers=token_header).json()

    assert [row["run_id"] for row in body["runs"]] == ["r-history-a"]
    assert body["runs"][0]["failed_gates"] == []


def test_the_history_filters_by_document(served, token_header, history):
    """The question an operator actually asks: what happened to *this* binder."""
    body = served.get("/runs?doc_id=SYN-M1", headers=token_header).json()

    assert body["total"] == 2
    assert {row["run_id"] for row in body["runs"]} == {"r-history-a", "r-history-b"}


def test_an_empty_history_is_an_empty_list_and_not_a_refusal(served, token_header):
    """No runs is an answer. A control plane with nothing in it is not an outage (§11.3)."""
    body = served.get("/runs", headers=token_header).json()

    assert body["total"] == 0
    assert body["runs"] == []
    assert body["truncated"] is False


def test_the_history_reports_truncation_and_honours_its_bound(served, token_header, history):
    body = served.get("/runs?limit=2", headers=token_header).json()

    assert body["returned"] == 2
    assert body["total"] == 3
    assert body["truncated"] is True

    refused = served.get(f"/runs?limit={manage.MAX_PAGE_SIZE + 1}", headers=token_header)
    assert refused.status_code == 400
    assert refused.json()["error"] == "listing_limit_exceeded"


def test_a_row_points_at_the_full_record(served, token_header, history):
    """The summary is a summary: everything it leaves out is one `GET` away (§6.9)."""
    listed = served.get("/runs", headers=token_header).json()
    run_id = listed["runs"][0]["run_id"]

    full = served.get(f"/runs/{run_id}", headers=token_header)

    assert full.status_code == 200
    assert full.json()["run_id"] == run_id
