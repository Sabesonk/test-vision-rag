"""Shared setup for L2/L3 — the collection the test stack's Qdrant must hold, and a served app.

An instance with no collection is deliberately **not ready** (§15.1), so every test that expects a
green `/ready` needs the collection to exist first. Creating it here, from the same
`core.indexed.create_collection` the CLI uses, is also the only way these tests prove the real
creation path rather than a fixture's idea of it.

From U014 there is a second shared shape: an app built by :func:`vsir.serve.app.create_app` over a
collection seeded with the §13 M1 corpus, with a token in ``VSIR_API_TOKENS``. The suites that
exercise auth, the audit line, the budget and §11.3's refusals all need the same three things — a
real index with real pages, a real credential, and the real middleware stack — so they are built
once here rather than four times.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from vsir import logging as vsir_logging
from vsir.core.indexed import create_collection
from vsir.eval import synthetic
from vsir.serve.app import create_app

QDRANT_URL = os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")
BASE_URL = os.environ.get("VSIR_TEST_BASE_URL", "http://localhost:8001")
COLLECTION = "vsir_pages"
EMBED_DIM = 1536

#: The token the served fixtures configure. Not a secret and never was: it is generated per
#: repository, it authorises nothing outside a container that is torn down with `down -v`, and the
#: point of the suites below is that a *wrong* one is refused.
TEST_TOKEN = "u014-local-test-credential"
#: A syntactically fine token that is not in `VSIR_API_TOKENS`.
WRONG_TOKEN = "u014-not-in-the-configured-list"
#: The base name of the collection the served app is pointed at. Its own, so a suite that seeds
#: pages cannot change what `test_probes.py` or the acceptance table sees.
SERVED_COLLECTION = "vsir_pages_u014"
#: The runs collection the budget ledger is written to — also its own, for the same reason.
SERVED_RUNS = "vsir_runs_u014"

#: The credential the **container** in `docker-compose.test.yml` is configured with, resolved the
#: same way the compose file does. From U014 every path but the three probes needs it, including
#: `GET /runs/{run_id}` and the two exports (§7.4).
#:
#: The variable is `VSIR_TEST_API_TOKENS`, not `VSIR_API_TOKENS`, and that is the whole point:
#: Compose interpolates from `.env`, so reading the production name meant a developer's own token
#: silently became the test stack's — and the suite that asserts no credential reaches the log
#: stream was checking for a string the container had never been given.
CONTAINER_TOKEN = (os.environ.get("VSIR_TEST_API_TOKENS")
                   or "test-only-not-a-secret").split(",")[0].strip()
CONTAINER_AUTH = {"Authorization": f"Bearer {CONTAINER_TOKEN}"}


@pytest.fixture(scope="session")
def repo_root() -> str:
    """The directory `docker-compose.test.yml` lives in — these tests drive the real stack."""
    return str(Path(__file__).resolve().parents[3])


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def qdrant() -> QdrantClient:
    client = QdrantClient(url=QDRANT_URL, timeout=30, check_compatibility=False)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def pages_collection(qdrant: QdrantClient) -> str:
    """The collection, created from `INDEXED` exactly as `vsir doctor --create-collection` does."""
    name = f"{COLLECTION}_{EMBED_DIM}"
    create_collection(qdrant, name, EMBED_DIM, recreate=True)
    return name


# ── the served app: a real index, a real credential, the real middleware (U014) ──────────────────

def serve_env(**overrides: str) -> dict[str, str]:
    """The twelve required variables of §15 Factor III, pointed at the test stack.

    A plain dict passed to :func:`create_app`, never ``os.environ``: configuration is an argument
    here, so two apps with different settings can exist in one test process and nothing a suite
    sets leaks into another (§15 Factor III, and the reason the factory takes ``env`` at all).
    """
    return {
        "VSIR_PORT": "8000",
        "VSIR_QDRANT_URL": QDRANT_URL,
        "VSIR_COLLECTION": SERVED_COLLECTION,
        "VSIR_RUNS_COLLECTION": SERVED_RUNS,
        "VSIR_VLM": "stub",
        "VSIR_VLM_MODEL": "gemini-3.8-flash-001",
        "VSIR_EMBED_MODEL": "gemini-embedding-2",
        "VSIR_PROMPT_VERSION": "s2-v1",
        "VSIR_API_TOKENS": TEST_TOKEN,
        "VSIR_READ_QUOTA": "10",
        "VSIR_ALLOW_PAID": "0",
        "VSIR_LOG_LEVEL": "INFO",
        "VSIR_RELEASE_ID": "test",
        **overrides,
    }


@pytest.fixture(scope="session")
def served_collection(qdrant: QdrantClient) -> Iterator[str]:
    """The §13 M1 corpus, seeded into the collection the served app is configured for.

    The real corpus rather than two hand-made points, because the suites over it assert things
    only a real one has: a page whose ``text_trust`` is ``untrusted`` (§11.3's collapsed
    `grounded_rate` row), a page with no text layer, and a superseded revision.
    """
    name = f"{SERVED_COLLECTION}_{EMBED_DIM}"
    corpus = synthetic.load()
    synthetic.seed(qdrant, name, corpus.records(release_id="test"), dim=EMBED_DIM)
    try:
        yield name
    finally:
        synthetic.drop(qdrant, name)


@pytest.fixture(scope="session")
def corpus() -> synthetic.Corpus:
    """The checked-in corpus and its acceptance table — the source of every expected value."""
    return synthetic.load()


@pytest.fixture
def served(qdrant: QdrantClient, served_collection: str) -> Iterator[Any]:
    """A :class:`TestClient` over the real app: boot checks, middleware, auth, budget and all.

    ``TestClient`` drives the ASGI application directly, so the middleware stack under test is the
    shipped one — including the pure-ASGI ordering that makes the correlation ids reach a handler.
    The budget ledger this app writes is dropped afterwards, so a suite that exhausts a quota does
    not exhaust it for the next one.
    """
    with TestClient(create_app(serve_env())) as client:
        try:
            yield client
        finally:
            if qdrant.collection_exists(SERVED_RUNS):
                qdrant.delete_collection(SERVED_RUNS)


@pytest.fixture
def token_header() -> dict[str, str]:
    """The one header every non-probe path needs (§7.4)."""
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """Capture the process's JSON event stream (§15 Factor XI) for the duration of one test.

    Requested **after** ``served`` wherever both are used: `create_app` configures logging to
    stdout, so a buffer installed first would be replaced by it. At ``DEBUG``, because the free
    tools log at debug on purpose (§7.4 audits only the two that spend) and a suite that asserted
    *no* line from a `lookup` needs to be able to see the one there is.
    """
    buffer = io.StringIO()
    vsir_logging.configure(release_id="test", level="DEBUG", stream=buffer)
    try:
        yield buffer
    finally:
        vsir_logging.configure(release_id="test", level="INFO")


def log_events(buffer: io.StringIO) -> list[dict[str, Any]]:
    """The captured stream, parsed. One JSON object per line is the contract, so this is total."""
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
