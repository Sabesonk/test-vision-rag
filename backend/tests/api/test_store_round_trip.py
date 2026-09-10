"""L2 — the document store over a real ingest: `page_id` → bytes, end to end (U029, §4.2).

One upload, then the question the whole vision half of retrieval rests on: *given a `page_id` this
run published, can the bytes it was rendered from still be found?* Until this unit the answer was
no, and nothing said so — a CLI ingest happened to work because the operator's copy was on their
filesystem, an upload's spool was deleted when the run exited, and no payload and no run record
named a file (register **A5** removed `image_path` deliberately).

Asserted through the resolution chain rather than by listing a directory. A store that holds a file
nothing can address is exactly the state this unit found the system in.

The ingest is real: a real child process, a real Qdrant, 42 pages. It spends nothing —
``VSIR_VLM=stub`` replays frozen S2 by cache key and the embedder is
:class:`~vsir.ingest.embed.StubEmbedder`, both selected by configuration and not by a branch (D10,
§15 Factor X).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vsir.core import ids
from vsir.core.indexed import INDEXED, create_collection, schema_problems
from vsir.eval import synthetic
from vsir.ingest import probe as probe_module
from vsir.ingest import store as store_module
from vsir.ingest.store import DocumentStore
from vsir.serve.app import create_app

from conftest import EMBED_DIM, TEST_TOKEN, serve_env

PDF = Path(__file__).resolve().parents[3] / "data/source/synthetic_3window.pdf"
FIXTURE = str(Path(__file__).resolve().parents[3] / "data/fixtures/synthetic_3window")
PUBLISH_TIMEOUT_S = 240
DOC_ID = "stored-over-http"
REVISION = "3.1"
PAGE_COUNT = 42


def _upload(client, header, **fields):
    return client.post("/documents", headers=header,
                       files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
                       data={"fixture": FIXTURE, **fields})


def _poll(client, header, run_id: str, *, until: set[str]) -> dict:
    """The control plane until the run settles, or the assertion that it never did (§6.9)."""
    deadline = time.monotonic() + PUBLISH_TIMEOUT_S
    record: dict = {}
    while time.monotonic() < deadline:
        time.sleep(2)
        polled = client.get(f"/runs/{run_id}", headers=header)
        if polled.status_code != 200:
            continue
        record = polled.json()
        if record.get("state") in until:
            return record
    raise AssertionError(f"run {run_id} never reached {until}: {record or 'no run record'}")


class _Stack:
    """One ingested document and everything a test needs to ask about it."""

    def __init__(self, client: Any, store: DocumentStore, record: dict) -> None:
        self.client = client
        self.store = store
        self.record = record


@pytest.fixture(scope="module")
def ingested(qdrant, tmp_path_factory) -> Any:
    """Upload the corpus once, into a collection and a document store of this module's own.

    Module-scoped because a real 42-page ingest is the expensive part and every assertion below
    is a *read* of what it produced. Isolated for the reason `test_upload_route.py` records: a
    real ingest writes 42 pages into whichever collection its app is configured for, and running
    it against the shared one corrupts the corpus every other suite asserts about.
    """
    stamp = f"vsir_store_{int(time.time() * 1000) % 10_000_000}"
    pages, runs = f"{stamp}_{EMBED_DIM}", f"{stamp}_runs"
    root = tmp_path_factory.mktemp("documents")
    create_collection(qdrant, pages, EMBED_DIM, recreate=True)
    env = serve_env(VSIR_COLLECTION=stamp, VSIR_RUNS_COLLECTION=runs, VSIR_DOC_STORE=str(root))
    try:
        with TestClient(create_app(env)) as client:
            header = {"Authorization": f"Bearer {TEST_TOKEN}"}
            accepted = _upload(client, header, doc_id=DOC_ID, revision=REVISION)
            assert accepted.status_code == 202, accepted.text
            record = _poll(client, header, accepted.json()["run_id"],
                           until={"published", "failed", "gated"})
            assert record["state"] == "published", record
            yield _Stack(client, DocumentStore(root), record)
    finally:
        synthetic.drop(qdrant, pages)
        if qdrant.collection_exists(runs):
            qdrant.delete_collection(runs)


# ── the resolution chain (AC: `page_id` -> bytes for every page) ────────────────────────────────

def test_every_page_of_an_uploaded_document_resolves_to_bytes(ingested):
    """The unit's acceptance criterion, asserted over all 42 pages rather than a sample.

    The spool this upload arrived in is gone — the reaper deletes it when the child exits — so
    what answers here is the store, and nothing else could.
    """
    assert ingested.record["pages_indexed"] == PAGE_COUNT

    for page_no in range(1, PAGE_COUNT + 1):
        source = ingested.store.for_page(ids.page_id(DOC_ID, REVISION, page_no))

        assert source.page_no == page_no
        assert source.path.is_file()
    assert source.path.read_bytes() == PDF.read_bytes(), "one file, not forty-two"


def test_the_stored_bytes_are_the_uploaded_bytes(ingested):
    stored = ingested.store.locate(DOC_ID, REVISION)

    assert stored.content_hash == probe_module.content_hash(PDF)
    assert stored.size_bytes == PDF.stat().st_size


def test_the_run_record_carries_the_content_hash_of_what_it_ingested(ingested):
    """Nothing else can tell a re-ingested file from the one these pages came from (§6.9)."""
    assert ingested.record["content_hash"] == probe_module.content_hash(PDF)


def test_a_page_that_was_indexed_can_be_rendered_from_the_store(ingested):
    """The end of the chain U018 will serve: `page_id` -> bytes -> a raster, in memory.

    Rendering here rather than only resolving, because "the file is there" and "a raster can be
    made from it" are different claims and the second is the one `GET /pages/{page_id}/image`
    depends on.
    """
    from vsir.ingest import render

    source = ingested.store.for_page(ids.page_id(DOC_ID, REVISION, 7))
    raster = render.render_page(source.path, source.page_no, dpi=72,
                                content_hash=source.document.content_hash)

    assert raster.page_no == 7
    assert raster.png.startswith(b"\x89PNG")


# ── what the store must NOT have changed ────────────────────────────────────────────────────────

def test_the_page_payload_gained_no_field_and_the_boot_assertion_still_passes(ingested, qdrant):
    """`INDEXED` is one dict with three jobs (I6) and the store is not one of them.

    The store resolves a *file* from a document's identity, so no record may carry a path — that
    is A5's fix and the reason `image_path` does not exist (§5.3). A payload key added here would
    also be a schema the live collection does not have, which is a boot refusal (§4.3).
    """
    collection = ingested.client.app.state.config.pages_collection
    scrolled, _ = qdrant.scroll(collection, limit=1, with_payload=True)

    assert scrolled, "the ingest wrote no points"
    payload = scrolled[0].payload
    assert "image_path" not in payload
    assert "content_hash" not in payload, "the hash belongs on the run record, not on every page"
    assert "source_path" not in payload and "doc_store" not in payload
    assert set(INDEXED) <= set(payload), sorted(set(INDEXED) - set(payload))
    assert schema_problems(qdrant, collection, dim=EMBED_DIM) == []


def test_the_instance_is_ready_with_a_store_configured(ingested):
    """A thirteenth required variable would have changed what `/ready` means. It is optional."""
    assert ingested.client.get("/ready").status_code == 200


# ── the two refusals, over the real store (§11.3) ───────────────────────────────────────────────

def test_a_document_missing_from_the_store_is_a_typed_refusal_naming_it(ingested):
    """Never a 500 and never a blank image: the page is indexed, the bytes are not here."""
    with pytest.raises(store_module.DocumentNotStored) as refusal:
        ingested.store.for_page(f"never-ingested@1.0#p001")

    assert refusal.value.code == "document_not_stored"
    assert refusal.value.details["document"] == "never-ingested@1.0"


def test_bytes_that_disagree_with_the_run_record_are_refused_rather_than_served(ingested):
    """The published pages of this run recorded a hash. Serving other bytes for them would
    answer with a page nobody indexed — so the store refuses, and says both digests."""
    stored = ingested.store.locate(DOC_ID, REVISION)
    original = stored.path.read_bytes()
    stored.path.write_bytes(b"%PDF-1.7\nsomebody replaced the file\n%%EOF\n")
    try:
        with pytest.raises(store_module.DocumentHashMismatch) as refusal:
            ingested.store.for_page(ids.page_id(DOC_ID, REVISION, 1),
                                    expect_hash=ingested.record["content_hash"])
    finally:
        stored.path.write_bytes(original)

    assert refusal.value.details["expected_hash"] == ingested.record["content_hash"]
    assert refusal.value.details["stored_hash"] != ingested.record["content_hash"]
    # And once the real bytes are back, the same page resolves again.
    assert ingested.store.for_page(ids.page_id(DOC_ID, REVISION, 1),
                                   expect_hash=ingested.record["content_hash"]).path.is_file()


# ── resumable across a restart, which the store is what makes possible (AC) ────────────────────

def test_an_upload_started_run_resumes_from_the_store_with_no_path_at_all(qdrant,
                                                                          tmp_path_factory):
    """The limitation `POST /documents` used to disclose, closed and asserted.

    An upload spools to ``/tmp`` and the spool goes with the instance, so ``vsir ingest --resume``
    had nothing to be pointed at and the operator had no copy either — a paid run died with its
    container. Here the run is started over HTTP, the client that took it is thrown away, and the
    run is finished by a **separate process** that is given nothing but the run id: the document
    comes out of the store, keyed by the ``doc_id@revision`` on the run record and checked against
    its ``content_hash``.

    ``--steal`` because the first worker exited without releasing its lease and a lease outlives
    the process that held it by design (D9) — which is exactly the situation ``--steal`` exists
    for, and is not what is under test here.
    """
    stamp = f"vsir_resume_{int(time.time() * 1000) % 10_000_000}"
    pages, runs = f"{stamp}_{EMBED_DIM}", f"{stamp}_runs"
    root = tmp_path_factory.mktemp("resume-documents")
    create_collection(qdrant, pages, EMBED_DIM, recreate=True)
    env = serve_env(VSIR_COLLECTION=stamp, VSIR_RUNS_COLLECTION=runs, VSIR_DOC_STORE=str(root))
    header = {"Authorization": f"Bearer {TEST_TOKEN}"}
    try:
        with TestClient(create_app(env)) as client:
            accepted = _upload(client, header, doc_id="resumed-doc", revision="1.1",
                               until="index")
            assert accepted.status_code == 202, accepted.text
            run_id = accepted.json()["run_id"]
            _wait_for_points(qdrant, pages, PAGE_COUNT)
            unpublished = client.get(f"/runs/{run_id}", headers=header).json()

        # The instance is gone. Its spool went with it; the document did not.
        assert not list(Path(tempfile.gettempdir()).glob(f"vsir-spool/{run_id}.pdf"))
        assert DocumentStore(root).holds("resumed-doc", "1.1")

        finished = subprocess.run(
            [sys.executable, "-m", "vsir", "ingest", "--resume", run_id, "--steal",
             "--until", "publish"],
            env={**os.environ, **env, "VSIR_FIXTURE": FIXTURE},
            capture_output=True, text=True, timeout=PUBLISH_TIMEOUT_S)

        assert finished.returncode == 0, finished.stdout[-4000:] + finished.stderr[-2000:]
        assert "resuming" in finished.stdout

        with TestClient(create_app(env)) as client:
            record = client.get(f"/runs/{run_id}", headers=header).json()

        assert unpublished["state"] != "published", "the first leg must not have published"
        assert record["state"] == "published", record
        assert record["run_id"] == run_id, "a resume keeps the id every point of the run carries"
        assert record["content_hash"] == probe_module.content_hash(PDF)
    finally:
        synthetic.drop(qdrant, pages)
        if qdrant.collection_exists(runs):
            qdrant.delete_collection(runs)


def _wait_for_points(client, collection: str, expected: int) -> None:
    """Step 10 has no progress write of its own, so the points are the signal it finished."""
    deadline = time.monotonic() + PUBLISH_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(2)
        if client.count(collection, exact=True).count >= expected:
            return
    raise AssertionError(f"{collection} never reached {expected} points")
