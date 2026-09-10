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
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from vsir import logging as vsir_logging
from vsir.config import load_config
from vsir.core import ids
from vsir.core.indexed import create_collection
from vsir.eval import synthetic
from vsir.ingest import embed as embed_module
from vsir.ingest import index as index_module
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
#: The collection the fused-surface suites use — its own again, because seeding vectors changes
#: what every other suite's `lookup` would rank and none of them asked for that (U017).
SKIM_COLLECTION = "vsir_pages_u017"
SKIM_RUNS = "vsir_runs_u017"
#: The collection the two aggregate rungs are exercised against (U019). Its own again, and for a
#: reason the M1 corpus cannot satisfy: `skim_documents` groups **documents**, and the M1 corpus
#: is one document. See :func:`aggregate_records`.
AGGREGATE_COLLECTION = "vsir_pages_u019"
AGGREGATE_RUNS = "vsir_runs_u019"
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
        "VSIR_VLM_MODEL": "gemini-3.8-flash",
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


# ── the three fused surfaces, seeded (U017) ─────────────────────────────────────────────────────

def seed_with_vectors(client: Any, collection: str, records: Any, *, dim: int,
                      embedder: Any) -> int:
    """Seed a collection with all three surfaces of §5.3, not payloads alone.

    `vsir.eval.synthetic.seed` writes an empty vector map, because M1 had no embedder and spends
    nothing — which is honest there and useless here: `skim_pages` reads a *vector*, so a corpus
    with none of them can only ever return nothing. The vectors are built by the shipped
    :func:`vsir.ingest.index.build_point`, so the `lexical` and `captions` surfaces are the real
    ones — `sparse.build` over the page's ``text`` and over `dedupe`d generated text — and only
    the dense vector is stood in for.

    **The stand-in is deliberate and it is a function of the page's own text**:
    ``StubEmbedder.embed_query(record.text)``. There is no raster behind this corpus, so the D4
    composition cannot be built at all; what this buys instead is the property the suites need —
    a query whose words are exactly a page's text lands on that page, so an assertion about the
    dense branch is an assertion about a query reaching a vector rather than about a hash.

    ``is_current`` is restored after :func:`~vsir.ingest.index.build_point`, which refuses a
    record that arrives already published (I7): the real path writes every point unpublished and
    lets the gates flip it, and this fixture stands in for the gates rather than for the writer.
    """
    create_collection(client, collection, dim, recreate=True)
    points = []
    for record in records:
        dense = embedder.embed_query(record.text or record.page_id)
        point = index_module.build_point(record.model_copy(update={"is_current": False}), dense)
        point.payload["is_current"] = record.is_current
        points.append(point)
    if points:
        client.upsert(collection, points=points, wait=True)
    return len(points)


def skim_config() -> Any:
    """The configuration the fused-surface app and its fixtures share, as a value."""
    return load_config(serve_env(VSIR_COLLECTION=SKIM_COLLECTION,
                                 VSIR_RUNS_COLLECTION=SKIM_RUNS))


@pytest.fixture(scope="session")
def stub_embedder() -> Any:
    """The embedding backend every fused-surface suite uses — selected by config, never a branch.

    ``VSIR_VLM=stub`` is what chooses it in the app under test too (§15 Factor X, D10), so the
    vectors the fixture writes and the vectors a request embeds come out of the same object.
    """
    return embed_module.embedder(skim_config())


@pytest.fixture(scope="session")
def skim_collection(qdrant: QdrantClient, stub_embedder: Any) -> Iterator[str]:
    """The §13 M1 corpus with vectors, in the collection the `skim`/`resolve` app is pointed at."""
    name = f"{SKIM_COLLECTION}_{EMBED_DIM}"
    corpus = synthetic.load()
    seed_with_vectors(qdrant, name, corpus.records(release_id="test"), dim=EMBED_DIM,
                      embedder=stub_embedder)
    try:
        yield name
    finally:
        synthetic.drop(qdrant, name)


@pytest.fixture
def skimming(qdrant: QdrantClient, skim_collection: str) -> Iterator[Any]:
    """A :class:`TestClient` over an app pointed at the vector-seeded collection."""
    with TestClient(create_app(serve_env(VSIR_COLLECTION=SKIM_COLLECTION,
                                         VSIR_RUNS_COLLECTION=SKIM_RUNS))) as client:
        try:
            yield client
        finally:
            if qdrant.collection_exists(SKIM_RUNS):
                qdrant.delete_collection(SKIM_RUNS)


# ── a multi-document corpus, for the aggregate rungs (U019) ─────────────────────────────────────

#: The three documents the `skim_documents` suite reads, and the one number each exists to show.
#:
#: `searchable_ratio` is the point of the rung, so the corpus is built around the three values it
#: can take: a binder that is entirely text, one that is half scanned, and one that is **entirely**
#: scanned — the agent's blind spot, at ``0.00``. The last is why the M1 corpus cannot be reused:
#: it is one document, and one document has no grouping to prove and no blind spot to disclose.
AGGREGATE_DOCS = (
    # (doc_id, doc_type, [(page_no, has_text)], [(section ordinal, title, page_range)])
    ("AGG-TEXT", "manual",
     [(1, True), (2, True), (3, True), (4, True), (5, True), (6, True)],
     [(1, "Carton discharge", (1, 3)), (2, "Emergency stop reset", (4, 6))]),
    ("AGG-MIXED", "manual",
     [(1, False), (2, False), (3, True), (4, True)],
     [(1, "Carton discharge conveyor", (1, 4))]),
    # No text layer anywhere. Its pages still carry a dense vector — D4 fuses the raster — so a
    # prose query finds them; a query carrying a printed code cannot, because the phrase filter
    # runs over `text` and this document has none. That is the case the disclosure row exists for.
    ("AGG-SCAN", "manual",
     [(1, False), (2, False), (3, False)],
     [(1, "Scanned binder", (1, 3))]),
)

#: Twelve one-page documents, so a `skim_documents` call has more than ten groups to cut. Their
#: own `doc_type`, which is how a scope tells the two sub-corpora apart in one collection: seeding
#: twice would be two session fixtures for one question.
AGGREGATE_LEAFLETS = 12

#: Printed on `AGG-TEXT` page 2 and nowhere else. `decompose()` splits it out of a query as an
#: identifier (it contains a digit), so it becomes a phrase filter over `text` — which is what
#: makes every page of `AGG-SCAN` fall out of every branch.
AGGREGATE_CODE = "K158"

#: The words every text page of the corpus carries, so the lexical branch has something to rank.
AGGREGATE_QUERY = "carton discharge restart"


def _aggregate_page(doc_id: str, revision: str, page_no: int, *, has_text: bool, doc_type: str,
                    section: Any, text: str) -> Any:
    """One §5.3 record. `has_text=False` is a scanned page: no text, `no_text`, no rate (§5.7)."""
    from vsir.core.record import PageContent, PageRecord, Provenance, StoredSection, Summary

    stored = (StoredSection(section_id=section[0], title=section[1], page_range=section[2],
                            series_id=section[3])
              if section else None)
    return PageRecord(
        doc_id=doc_id, revision=revision, is_current=True, doc_type=doc_type,
        page_kind="prose", lang=["en"], page_no=page_no,
        section_id=[stored.section_id] if stored else [],
        series_id=[stored.series_id] if stored else [],
        has_text=has_text,
        text_trust="ok" if has_text else "no_text",
        run_id="r-u019-seed",
        text=text if has_text else "",
        content=PageContent(
            printed_page_no=str(page_no),
            label_verified=has_text,
            summaries=[Summary(lang="en",
                               text=f"{doc_id} page {page_no}: carton discharge and the "
                                    f"emergency stop reset interlock.")],
            sections=[stored] if stored else [],
            # §5.7 — `None` where there is no text layer, never 0.0.
            grounded_rate=1.0 if has_text else None,
        ),
        provenance=Provenance(page_id=ids.page_id(doc_id, revision, page_no),
                              run_id="r-u019-seed", release_id="test"),
    )


def aggregate_records() -> list[Any]:
    """The U019 corpus: three `manual` documents to group, twelve `leaflet`s to cut at ten."""
    revision = "1.0"
    records = []
    for doc_id, doc_type, pages, sections in AGGREGATE_DOCS:
        stored = {
            ordinal: (ids.section_id(doc_id, revision, ordinal), title, span,
                      ids.series_id(doc_id, title))
            for ordinal, title, span in sections
        }
        for page_no, has_text in pages:
            section = next((entry for entry in stored.values()
                            if entry[2][0] <= page_no <= entry[2][1]), None)
            code = f" {AGGREGATE_CODE}" if (doc_id == "AGG-TEXT" and page_no == 2) else ""
            records.append(_aggregate_page(
                doc_id, revision, page_no, has_text=has_text, doc_type=doc_type, section=section,
                text=f"Carton discharge restart interlock on page {page_no}.{code}"))
    for leaflet in range(1, AGGREGATE_LEAFLETS + 1):
        doc_id = f"AGG-L{leaflet:02d}"
        records.append(_aggregate_page(
            doc_id, revision, 1, has_text=True, doc_type="leaflet",
            section=(ids.section_id(doc_id, revision, 1), "Leaflet", (1, 1),
                     ids.series_id(doc_id, "Leaflet")),
            text="Carton discharge restart leaflet."))
    return records


@pytest.fixture(scope="session")
def aggregate_collection(qdrant: QdrantClient, stub_embedder: Any) -> Iterator[str]:
    """The U019 corpus, with all three surfaces, in the collection the aggregate app reads."""
    name = f"{AGGREGATE_COLLECTION}_{EMBED_DIM}"
    seed_with_vectors(qdrant, name, aggregate_records(), dim=EMBED_DIM, embedder=stub_embedder)
    try:
        yield name
    finally:
        synthetic.drop(qdrant, name)


@pytest.fixture
def aggregating(qdrant: QdrantClient, aggregate_collection: str) -> Iterator[Any]:
    """A :class:`TestClient` over an app pointed at the multi-document corpus."""
    with TestClient(create_app(serve_env(VSIR_COLLECTION=AGGREGATE_COLLECTION,
                                         VSIR_RUNS_COLLECTION=AGGREGATE_RUNS))) as client:
        try:
            yield client
        finally:
            if qdrant.collection_exists(AGGREGATE_RUNS):
                qdrant.delete_collection(AGGREGATE_RUNS)


# ── one real ingest, for the raster suites (U018) ────────────────────────────────────────────────

#: The document the four U018 suites look at, ingested **once** for the session.
#:
#: It has to be a real ingest and it has to be shared. Real, because `fetch` and
#: `GET /pages/{page_id}/image` resolve `page_id` → the run's `content_hash` → the bytes in the
#: document store (U029), and a hand-seeded collection would prove that a directory a fixture had
#: just written to could be read back. Shared, because that ingest is 42 pages through the whole of
#: §6.1 and four suites all only *read* what it produced.
RASTER_COLLECTION = "vsir_pages_u018"
RASTER_RUNS = "vsir_runs_u018"
RASTER_DOC_ID = "vsir-raster"
RASTER_REVISION = "1.0"
RASTER_PAGE_COUNT = 42
#: Pages 1 and 2 of the generated corpus carry no text layer, which is what makes them the honest
#: case for F4's disclosure: a `fetch` of them returns `text: ""` and `text_trust: "no_text"`.
RASTER_NO_TEXT_PAGES = (1, 2)
RASTER_PUBLISH_TIMEOUT_S = 300

REPO_ROOT = Path(__file__).resolve().parents[3]
RASTER_PDF = REPO_ROOT / "data/source/synthetic_3window.pdf"
RASTER_FIXTURE = REPO_ROOT / "data/fixtures/synthetic_3window"


class RasterStack:
    """One ingested document, and everything a raster suite needs to ask about it."""

    def __init__(self, client: Any, store: Any, record: dict, collection: str) -> None:
        self.client = client
        self.store = store
        self.record = record
        self.collection = collection

    @property
    def config(self) -> Any:
        return self.client.app.state.config

    @property
    def header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {TEST_TOKEN}"}

    def page_id(self, page_no: int) -> str:
        from vsir.core import ids

        return ids.page_id(RASTER_DOC_ID, RASTER_REVISION, page_no)

    def page_ids(self, *page_nos: int) -> list[str]:
        return [self.page_id(page_no) for page_no in page_nos]

    def image_url(self, page_no: int, *, dpi: int = 150, region: str = "") -> str:
        """The URL an envelope would carry for this page — built by the shipped function.

        ``region`` is appended **verbatim**, as a caller typed it, rather than parsed and
        re-formatted: the malformed-region cases (`0,0,2,2`, `top-half`) have to reach the route
        exactly as sent, and a helper that validated them first would be testing the helper.
        """
        from vsir.serve import raster_cache

        url = raster_cache.page_image_url(self.page_id(page_no), dpi=dpi)
        return f"{url}&region={region}" if region else url

    def get_image(self, page_no: int, **params: Any) -> Any:
        return self.client.get(self.image_url(page_no, **params), headers=self.header)

    def fetch(self, page_ids: Any, **arguments: Any) -> Any:
        body = {"page_ids": list(page_ids), **arguments}
        return self.client.post("/tools/fetch", headers=self.header, json=body)

    def read(self, page_ids: Any, question: str, **arguments: Any) -> Any:
        """`POST /tools/read` over the same ingested document (U020).

        The same client, the same collection and the same document store as `fetch`: `read`
        renders from the store U029 wrote and stamps against the index step 10 wrote, so a
        second stack here would be a `read` over pages nothing had really ingested.
        """
        body = {"page_ids": list(page_ids), "question": question, **arguments}
        return self.client.post("/tools/read", headers=self.header, json=body)

    @property
    def env(self) -> dict:
        """The environment this instance was built from — the base for a variant app."""
        return dict(self.client.app.state.env)


@pytest.fixture(scope="session")
def rastered(qdrant: QdrantClient, tmp_path_factory: Any) -> Iterator[RasterStack]:
    """Ingest the generated corpus over HTTP, into this session's own collection and store.

    Isolated for the reason `test_upload_route.py` records: a real ingest writes 42 pages into
    whichever collection its app is configured for, and running it against the shared one corrupts
    the corpus every other suite asserts about.

    The document store is a `tmp_path`, which is what a disposable instance has and is honest about
    being — §4.2's requirement is that the *rasters* are never persisted, and they never are: the
    only thing on that path is the source PDF (U029).
    """
    from vsir.eval import synthetic as synthetic_module
    from vsir.ingest.store import DocumentStore

    stamp = f"{RASTER_COLLECTION}_{int(time.time() * 1000) % 10_000_000}"
    pages, runs = f"{stamp}_{EMBED_DIM}", f"{stamp}_runs"
    root = tmp_path_factory.mktemp("u018-documents")
    create_collection(qdrant, pages, EMBED_DIM, recreate=True)
    # ``VSIR_FIXTURE`` is on the **app** and not only on the upload request from U020 onward:
    # `read` resolves its backend from the release's configuration (§15 Factor X), so an instance
    # with no fixture directory is an instance whose `read` is a `503 vlm_unavailable` — which is
    # correct, and is exercised deliberately by `test_read_caps.py`, not by accident here.
    # The read quota is the session's, not a bound under test: `test_read_caps.py` exercises the
    # ceiling on an instance of its own (`VSIR_READ_QUOTA=0`), and a low ceiling here would only
    # make the *other* suites fail as a side effect of how many reads they happen to make.
    env = serve_env(VSIR_COLLECTION=stamp, VSIR_RUNS_COLLECTION=runs, VSIR_DOC_STORE=str(root),
                    VSIR_FIXTURE=str(RASTER_FIXTURE), VSIR_READ_QUOTA="500")
    try:
        with TestClient(create_app(env)) as client:
            header = {"Authorization": f"Bearer {TEST_TOKEN}"}
            accepted = client.post(
                "/documents", headers=header,
                files={"file": (RASTER_PDF.name, RASTER_PDF.read_bytes(), "application/pdf")},
                data={"fixture": str(RASTER_FIXTURE), "doc_id": RASTER_DOC_ID,
                      "revision": RASTER_REVISION})
            assert accepted.status_code == 202, accepted.text
            run_id = accepted.json()["run_id"]

            deadline = time.monotonic() + RASTER_PUBLISH_TIMEOUT_S
            record: dict = {}
            while time.monotonic() < deadline:
                time.sleep(2)
                polled = client.get(f"/runs/{run_id}", headers=header)
                if polled.status_code != 200:
                    continue
                record = polled.json()
                if record.get("state") in {"published", "failed", "gated"}:
                    break
            assert record.get("state") == "published", record
            assert record["pages_indexed"] == RASTER_PAGE_COUNT, record
            yield RasterStack(client, DocumentStore(root), record, pages)
    finally:
        synthetic_module.drop(qdrant, pages)
        if qdrant.collection_exists(runs):
            qdrant.delete_collection(runs)
