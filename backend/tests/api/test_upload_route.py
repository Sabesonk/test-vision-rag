"""L2 — ``POST /documents`` over the real app: auth, the typed refusals, and one round trip.

The round trip is the point of the unit: upload a PDF, poll §6.9's control plane until the run
publishes, then find a code from the uploaded document through ``POST /tools/lookup``. That chain
is the only thing that proves the transport, the child process, the control plane and the index all
agree about one ``run_id`` — which is exactly what broke when the route started the child with
``--resume`` and answered ``202`` with an id that was never written.

The child is a real `vsir ingest`, so this test needs the replay fixture and a real Qdrant. It
spends nothing: ``VSIR_VLM=stub`` serves frozen responses by cache key and a miss is a typed
``fixture_miss`` (D10).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("served")

PDF = Path(__file__).resolve().parents[3] / "data/source/synthetic_3window.pdf"
FIXTURE = "data/fixtures/synthetic_3window"
#: Long enough for three replayed windows, 42 embeddings and the gates on a loaded laptop.
PUBLISH_TIMEOUT_S = 180


def _upload(client, header, **fields):
    """One multipart POST, with the PDF and whatever facets the test declares."""
    return client.post("/documents", headers=header,
                       files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
                       data=fields)


# ── auth and the typed refusals ─────────────────────────────────────────────────────────────────

def test_an_upload_without_a_bearer_token_is_refused(served):
    """§7.4 — the three probes are the only free paths, and this one spends money."""
    response = served.post("/documents",
                           files={"file": ("d.pdf", b"%PDF-1.7\n", "application/pdf")})

    assert response.status_code == 401


def test_something_that_is_not_a_pdf_is_refused_at_the_boundary(served, token_header):
    response = served.post("/documents", headers=token_header,
                           files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0JFIF",
                                           "application/pdf")})

    assert response.status_code == 415
    assert response.json()["error"] == "not_a_pdf"


def test_an_unknown_step_is_refused_before_anything_is_spawned(served, token_header):
    response = _upload(served, token_header, until="nonsense")

    assert response.status_code == 400
    assert response.json()["error"] == "unknown_step"


def test_a_live_model_is_refused_while_the_release_forbids_spending(served, token_header):
    """The route is the one place ``VSIR_ALLOW_PAID`` decides anything (see `serve/ingest.py`)."""
    response = _upload(served, token_header, vlm="gemini")

    assert response.status_code == 403
    assert response.json()["error"] == "spend_not_permitted"


# ── the round trip ──────────────────────────────────────────────────────────────────────────────

def test_an_uploaded_pdf_ingests_publishes_and_becomes_findable(served, token_header):
    """Upload -> 202 -> the control plane -> a published document -> an exact hit on its text.

    ``until`` defaults to the full pipeline and that is safe rather than reckless: step 10 writes
    every point ``is_current=False`` and step 11 is the only thing that flips it, behind §11.1's
    blocking gates (I7, §6.7). A document that fails a gate leaves the index as it was.
    """
    doc_id = "uploaded-over-http"
    accepted = _upload(served, token_header, doc_id=doc_id, revision="2.0",
                       doc_type="safety_function_list", subjects="C24", tags="api",
                       uploader="test", fixture=FIXTURE)

    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    run_id = body["run_id"]
    assert body["poll"] == f"/runs/{run_id}"
    assert body["until"] == "publish"

    deadline = time.monotonic() + PUBLISH_TIMEOUT_S
    record: dict = {}
    while time.monotonic() < deadline:
        time.sleep(2)
        polled = served.get(f"/runs/{run_id}", headers=token_header)
        if polled.status_code != 200:
            continue
        record = polled.json()
        if record.get("state") in {"published", "failed", "blocked"}:
            break

    assert record, f"run {run_id} never reached the control plane"
    assert record["state"] == "published", record
    assert record["pages_indexed"] == 42
    assert {gate["gate"] for gate in record["gates"]} >= {"window_coverage", "offset_check",
                                                          "grounded_rate"}
    assert all(gate["verdict"] == "PASS" for gate in record["gates"]
               if gate.get("blocking")), record["gates"]

    found = served.post("/tools/lookup", headers=token_header,
                        json={"label": "SF 1.13b", "scope": {"doc_id": doc_id}})

    assert found.status_code == 200
    hit = found.json()
    assert hit["status"] == "ok" and hit["total"] == 1
    assert hit["hits"][0]["page_id"].startswith(f"{doc_id}@2.0#")
    assert hit["scope_stats"]["pages"] == 42


def test_a_run_that_refuses_before_the_control_plane_still_says_why(served, token_header,
                                                                   log_stream):
    """The failure this route used to swallow: a child that dies before writing a run record.

    With the child's output discarded, a caller got ``202`` and then a permanent ``404`` from
    ``/runs/{run_id}``, with nothing anywhere naming the cause. The tail of a non-zero child is now
    logged as ``upload_run_failed`` — the success path stays quiet.
    """
    accepted = _upload(served, token_header, fixture="data/fixtures/definitely-not-here")

    assert accepted.status_code == 202, "the refusal is the run's, not the boundary's"
    run_id = accepted.json()["run_id"]

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        time.sleep(2)
        if "upload_run_failed" in log_stream.getvalue():
            break

    assert "upload_run_failed" in log_stream.getvalue(), "a failed run left no trace"
    assert run_id in log_stream.getvalue()
    assert "vlm_backend_unavailable" in log_stream.getvalue()
