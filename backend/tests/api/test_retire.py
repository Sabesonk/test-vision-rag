"""`vsir retire <doc_id> [--revision]` — the operator's withdrawal (§4.4, §2.5 A, U025).

It replaces `impl`'s ``DELETE /api/v1/documents/{doc_id}``, and the two differences are the test
plan:

* **it is a subcommand, not a route.** Withdrawing a document is an operator action, not a
  caller's, so it runs as a one-off admin process from the same image as `web` and
  `ingest-worker` (§15 Factor XII) and no bearer token can reach it. The last test asserts the
  route is gone rather than merely unused.
* **it demotes, it never deletes.** Every page is set `is_current=False` and **kept**, on the
  same terms as §6.7's clause 2: those pages are what `found_only_in_superseded` reads and what
  an audit of an answer already given checks against. A retirement that deleted would make every
  citation a reader is holding unverifiable.

And it is scoped the way retirement is scoped — :func:`vsir.ingest.run._page_filter` cannot be
built without a `doc_id`, so *"points of any other document are never touched"* is structural
rather than a check somebody could forget. That is asserted by payload hash, not by a count.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import EMBED_DIM as CONFTEST_DIM
from conftest import seed_with_vectors
from test_publish_and_retire import (COLLECTION, EMBED_DIM, FINGERPRINT, RUNS, build_records,
                                     open_run, payload_digest, vectors_for, windows_of)
from vsir.ingest import gates
from vsir.ingest import index as index_module
from vsir.ingest import run as run_module

REPO = Path(__file__).resolve().parents[3]
DOC = "RETIRE-DOC"
OTHER = "RETIRE-OTHER"
OLD, NEW = "1.3", "1.4"
PAGES = 5


@pytest.fixture
def store(qdrant):
    for name in (COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    index_module.ensure_collection(qdrant, name=COLLECTION, dim=EMBED_DIM,
                                   fingerprint=FINGERPRINT, runs_collection=RUNS)
    yield qdrant
    for name in (COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)


def publish(client, doc_id: str, revision: str, run_id: str):
    records = build_records(doc_id, revision, run_id, pages=PAGES)
    index_module.upsert(client, COLLECTION, list(records), vectors_for(records),
                        fingerprint=FINGERPRINT, runs_collection=RUNS)
    record = open_run(client, records, page_count=PAGES)
    report = gates.evaluate(records=list(records), page_count=PAGES, windows=windows_of(PAGES))
    return run_module.publish(client, runs_collection=RUNS, collection=COLLECTION,
                              record=record, report=report, records=list(records))


def count(client, **scope) -> int:
    return index_module.count(client, COLLECTION, scope)


def retire(client, doc_id: str, revision: str | None = None):
    return run_module.retire_document(client, COLLECTION, doc_id=doc_id, revision=revision)


# ── what it does ────────────────────────────────────────────────────────────────────────────────

def test_retire_sets_is_current_false_for_every_page_and_deletes_none(store):
    """AC: every page of the document stops answering, and every page is still there."""
    publish(store, DOC, OLD, "R-OLD")
    publish(store, DOC, NEW, "R-NEW")
    before = count(store, doc_id=DOC)

    report = retire(store, DOC)

    assert report["retired"] == PAGES, "only 1.4 was current; 1.3 was demoted when 1.4 published"
    assert count(store, doc_id=DOC, is_current=True) == 0
    assert count(store, doc_id=DOC) == before == PAGES * 2
    assert report["still_current"] == 0


def test_retire_is_idempotent(store):
    """AC: a filtered write of a constant. The second call demotes nothing and reports nothing."""
    publish(store, DOC, NEW, "R-NEW")

    first = retire(store, DOC)
    second = retire(store, DOC)

    assert first["retired"] == PAGES
    assert second["retired"] == 0
    assert second["kept"] == first["kept"] == PAGES
    assert count(store, doc_id=DOC, is_current=True) == 0


def test_revision_narrows_the_retirement_to_one_revision(store):
    """AC: `--revision` withdraws one revision and leaves the document's others serving."""
    publish(store, DOC, OLD, "R-OLD")
    # 1.3 is current again only because nothing superseded it in this arrangement: publish 1.4
    # into a *different* document id would be a different test. Here 1.3 is the live revision.
    assert count(store, doc_id=DOC, revision=OLD, is_current=True) == PAGES

    report = retire(store, DOC, OLD)

    assert report["retired"] == PAGES
    assert report["revision"] == OLD
    assert count(store, doc_id=DOC, revision=OLD) == PAGES
    assert count(store, doc_id=DOC, revision=OLD, is_current=True) == 0


def test_retiring_one_revision_leaves_the_other_serving(store):
    """The scope is `(doc_id, revision)`, so the current revision keeps answering."""
    publish(store, DOC, OLD, "R-OLD")
    publish(store, DOC, NEW, "R-NEW")

    report = retire(store, DOC, OLD)

    assert report["retired"] == 0, "1.3 was already demoted by 1.4's publish (§6.7 clause 2)"
    assert report["still_current"] == PAGES
    assert count(store, doc_id=DOC, revision=NEW, is_current=True) == PAGES


def test_retire_never_touches_another_document(store):
    """AC, by payload hash before and after — clause 3, structurally."""
    publish(store, DOC, NEW, "R-NEW")
    publish(store, OTHER, NEW, "R-OTHER")
    untouched = payload_digest(store, OTHER)

    retire(store, DOC)

    assert payload_digest(store, OTHER) == untouched
    assert count(store, doc_id=OTHER, is_current=True) == PAGES


def test_a_retired_document_is_still_in_the_store_for_an_audit(store):
    """The point of demote-not-delete: the pages, their text and their provenance all survive."""
    publish(store, DOC, NEW, "R-NEW")
    before = payload_digest(store, DOC)

    retire(store, DOC)

    assert count(store, doc_id=DOC) == PAGES
    assert payload_digest(store, DOC) != before, "is_current changed, and only is_current"
    stored, _ = store.scroll(collection_name=COLLECTION, limit=PAGES, with_payload=True,
                             scroll_filter=run_module._page_filter(DOC))
    assert all((point.payload or {}).get("text") for point in stored)
    assert all((point.payload or {})["is_current"] is False for point in stored)


# ── the subcommand ──────────────────────────────────────────────────────────────────────────────

#: The subcommand runs as its **own process** against the shipped configuration, so its
#: collection is the shipped shape: `VSIR_COLLECTION` unsuffixed, and the service appends the
#: release's embedding dimension. `test_publish_and_retire`'s 8-dimensional collection is a
#: convenience for in-process tests and is not a name any `vsir` invocation can be pointed at.
CLI_COLLECTION = "vsir_pages_retirecli"
CLI_PAGES = f"{CLI_COLLECTION}_{CONFTEST_DIM}"
CLI_RUNS = "vsir_runs_retirecli"


@pytest.fixture
def cli_store(qdrant, stub_embedder):
    """Two documents, published, at the release's embedding dimension."""
    for name in (CLI_PAGES, CLI_RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    run_module.ensure_control_plane(qdrant, CLI_RUNS)
    seeded = [record.model_copy(update={"is_current": True})
              for doc_id, revision, run_id in ((DOC, OLD, "R-OLD"), (OTHER, NEW, "R-OTHER"))
              for record in build_records(doc_id, revision, run_id, pages=PAGES)]
    seed_with_vectors(qdrant, CLI_PAGES, seeded, dim=CONFTEST_DIM, embedder=stub_embedder)
    yield qdrant
    for name in (CLI_PAGES, CLI_RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)


def cli_count(client, **scope) -> int:
    return index_module.count(client, CLI_PAGES, scope)


def env_for(qdrant_url: str) -> dict[str, str]:
    return {
        **os.environ,
        "VSIR_PORT": "8000", "VSIR_QDRANT_URL": qdrant_url,
        "VSIR_COLLECTION": CLI_COLLECTION,
        "VSIR_RUNS_COLLECTION": CLI_RUNS, "VSIR_VLM": "stub",
        "VSIR_FIXTURE": str(REPO / "data" / "fixtures" / "synthetic_3window"),
        "VSIR_VLM_MODEL": "gemini-3.8-flash", "VSIR_EMBED_MODEL": "gemini-embedding-2",
        "VSIR_PROMPT_VERSION": "s2-v1", "VSIR_API_TOKENS": "test-only-not-a-credential",
        "VSIR_READ_QUOTA": "10", "VSIR_ALLOW_PAID": "0", "VSIR_LOG_LEVEL": "INFO",
        "VSIR_RELEASE_ID": "test-0", "PYTHONUNBUFFERED": "1",
    }


def cli(qdrant_url: str, *arguments: str) -> subprocess.CompletedProcess:
    """One `vsir` subcommand, in its own process, configured only by the environment."""
    return subprocess.run([sys.executable, "-m", "vsir", *arguments], cwd=str(REPO),
                          env=env_for(qdrant_url), capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="session")
def qdrant_url() -> str:
    return os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")


def test_the_subcommand_withdraws_the_document_and_says_what_it_did(cli_store, qdrant_url):
    """`vsir retire RETIRE-DOC` — the operator's own command, over the real control plane.

    ``VSIR_COLLECTION`` is the **unsuffixed** name and the service appends the dimension, which
    is what makes this exercise the shipped configuration rather than a test's idea of it.
    """
    done = cli(qdrant_url, "retire", DOC)

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"demoted      {PAGES} page(s)" in done.stdout
    assert "never deletes" in done.stdout
    assert cli_count(cli_store, doc_id=DOC, is_current=True) == 0
    assert cli_count(cli_store, doc_id=DOC) == PAGES


def test_the_subcommand_is_idempotent_over_the_process_boundary(cli_store, qdrant_url):
    """Twice from the shell is twice the same filtered write — and the second says so."""
    assert cli(qdrant_url, "retire", DOC).returncode == 0

    again = cli(qdrant_url, "retire", DOC)

    assert again.returncode == 0, again.stdout + again.stderr
    assert "demoted      0 page(s)" in again.stdout
    assert cli_count(cli_store, doc_id=DOC) == PAGES


def test_the_subcommand_refuses_a_document_the_index_has_never_held(cli_store, qdrant_url):
    """A typed, non-zero refusal naming the code — never a cheerful report of demoting nothing."""
    refused = cli(qdrant_url, "retire", "NO-SUCH-DOC")

    assert refused.returncode != 0
    assert "REFUSED  run_not_found" in refused.stdout


def test_the_subcommand_narrows_with_revision(cli_store, qdrant_url):
    done = cli(qdrant_url, "retire", DOC, "--revision", OLD)

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"retired      {DOC}@{OLD}" in done.stdout
    assert cli_count(cli_store, doc_id=DOC, is_current=True) == 0
    assert cli_count(cli_store, doc_id=OTHER, is_current=True) == PAGES


def test_deletion_is_not_offered_over_http(served, token_header):
    """§2.5 A: `impl`'s `DELETE /api/v1/documents/{doc_id}` is gone and stays gone.

    Asserted against the **OpenAPI document** rather than by calling the verb, because a 405 is
    what an unrouted path returns anyway: the claim is that the release does not publish a
    delete on any path, which is a statement about the surface and not about one request.
    """
    schema = json.loads(served.get("/openapi.json").content)
    deleting = [f"DELETE {path}" for path, verbs in schema["paths"].items() if "delete" in verbs]

    assert deleting == []
