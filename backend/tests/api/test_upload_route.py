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
from fastapi.testclient import TestClient

from vsir.core.indexed import create_collection
from vsir.eval import synthetic
from vsir.serve.app import create_app

from conftest import EMBED_DIM, serve_env

PDF = Path(__file__).resolve().parents[3] / "data/source/synthetic_3window.pdf"
#: Absolute, deliberately. The child's working directory is the server's, which under pytest is
#: `backend/` — so a relative fixture path resolves somewhere it is not, and the route refuses it
#: as `fixture_not_found` rather than handing out a 202 for a run that cannot start.
FIXTURE = str(Path(__file__).resolve().parents[3] / "data/fixtures/synthetic_3window")
#: Long enough for three replayed windows, 42 embeddings and the gates on a loaded laptop.
PUBLISH_TIMEOUT_S = 180


def _upload(client, header, **fields):
    """One multipart POST, with the PDF and whatever facets the test declares."""
    return client.post("/documents", headers=header,
                       files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
                       data=fields)


@pytest.fixture
def isolated(qdrant):
    """An app on **its own empty collection**, for the one test that really ingests.

    The shared ``served`` fixture seeds §13 M1's corpus into a session-scoped collection that every
    other suite asserts against — point counts, the negative set, a superseded revision. A real
    ingest writes 42 more pages into whatever collection its app is configured for, so running it
    against that one corrupts the corpus underneath every test that follows. It did: the first
    green round trip took 93 other tests down with it.

    So this fixture gives the ingest a collection of its own, created with the `INDEXED` schema the
    boot self-check requires (§4.3) and dropped afterwards along with its control plane. The
    isolation is the ingest's, not the route's — every other test here uses ``served``, because a
    refusal at the boundary writes nothing anywhere.
    """
    stamp = f"vsir_upload_{int(time.time() * 1000) % 10_000_000}"
    pages, runs = f"{stamp}_{EMBED_DIM}", f"{stamp}_runs"
    create_collection(qdrant, pages, EMBED_DIM, recreate=True)
    env = serve_env(VSIR_COLLECTION=stamp, VSIR_RUNS_COLLECTION=runs)
    try:
        with TestClient(create_app(env)) as client:
            yield client
    finally:
        synthetic.drop(qdrant, pages)
        if qdrant.collection_exists(runs):
            qdrant.delete_collection(runs)


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

def test_an_uploaded_pdf_ingests_publishes_and_becomes_findable(isolated, token_header):
    """Upload -> 202 -> the control plane -> a published document -> an exact hit on its text.

    ``until`` defaults to the full pipeline and that is safe rather than reckless: step 10 writes
    every point ``is_current=False`` and step 11 is the only thing that flips it, behind §11.1's
    blocking gates (I7, §6.7). A document that fails a gate leaves the index as it was.
    """
    doc_id = "uploaded-over-http"
    accepted = _upload(isolated, token_header, doc_id=doc_id, revision="2.0",
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
        polled = isolated.get(f"/runs/{run_id}", headers=token_header)
        if polled.status_code != 200:
            continue
        record = polled.json()
        if record.get("state") in {"published", "failed", "blocked"}:
            break

    assert record, f"run {run_id} never reached the control plane"
    assert record["state"] == "published", record
    assert record["pages_indexed"] == 42

    verdicts = record["gate_results"]
    assert set(verdicts) >= {"window_coverage", "offset_check", "grounded_rate"}, verdicts
    assert all(verdicts[gate]["pass"] for gate in ("window_coverage", "offset_check",
                                                   "grounded_rate")), verdicts

    found = isolated.post("/tools/lookup", headers=token_header,
                          json={"label": "SF 1.13b", "scope": {"doc_id": doc_id}})

    assert found.status_code == 200
    hit = found.json()
    assert hit["status"] == "ok" and hit["total"] == 1
    assert hit["hits"][0]["page_id"].startswith(f"{doc_id}@2.0#")
    assert hit["scope_stats"]["pages"] == 42


def test_a_missing_replay_directory_is_a_400_and_not_a_doomed_202(served, token_header):
    """The bug this test was written for, then found for real: a run that cannot start.

    `stub` refuses ``vlm_backend_unavailable`` at step 04, correctly — replay mode never falls back
    to a live call (D10). But §6.9's control plane is written from step 09 onward, so a child that
    dies at step 04 leaves **no run record**, and the caller who was handed ``202`` polls ``404``
    for ever with the reason only in the server's log. It is a property of the request, so it is a
    refusal the caller can read.
    """
    response = _upload(served, token_header, fixture="/tmp/definitely-not-a-fixture-dir")

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "fixture_not_found"
    # Absolute, and not necessarily the string given: `resolve()` follows symlinks, so on macOS
    # `/tmp` reads back as `/private/tmp`. The path it *tried* is what a caller needs.
    assert body["resolved"].startswith("/")
    assert body["resolved"].endswith("definitely-not-a-fixture-dir")


def test_a_relative_replay_directory_is_refused_with_what_it_resolved_to(served, token_header):
    """A relative path resolves against the *server's* working directory, not the caller's.

    Silently accepting one is how the round trip above failed the first time it ran under the
    Docker harness, where the server's cwd is `backend/` rather than the repository root.
    """
    response = _upload(served, token_header, fixture="data/fixtures/synthetic_3window")

    assert response.status_code == 400
    assert response.json()["error"] == "fixture_not_found"
    assert response.json()["resolved"].startswith("/"), "the refusal names the absolute path tried"


def test_a_run_that_dies_after_starting_still_says_why_in_the_log(isolated, token_header,
                                                                 log_stream):
    """The other half: a child that gets past the boundary and then fails anyway.

    With its output going to `DEVNULL` this was invisible — a ``202`` and then silence. The tail of
    a non-zero child is now logged as ``upload_run_failed``; the success path stays quiet. A PDF
    whose header is valid and whose body is not gets past `check_upload` and dies inside PyMuPDF,
    which is the failure mode that has no request-time refusal available to it.
    """
    truncated = b"%PDF-1.7\n" + b"garbage that is not a document\n" * 8
    accepted = isolated.post("/documents", headers=token_header,
                             files={"file": ("broken.pdf", truncated, "application/pdf")},
                           data={"until": "probe", "fixture": FIXTURE})

    assert accepted.status_code == 202, "a valid header is all the boundary can check"
    run_id = accepted.json()["run_id"]

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        time.sleep(2)
        if "upload_run_failed" in log_stream.getvalue():
            break

    assert "upload_run_failed" in log_stream.getvalue(), "a failed run left no trace"
    assert run_id in log_stream.getvalue()
