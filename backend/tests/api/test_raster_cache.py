"""L2 — the resolution chain and the one raster cache (Spec §4.2, §6.7, §15 Factor VI, U018).

`serve/raster_cache.py` is the serving policy over `ingest/render.py`, and this suite is about the
two claims that policy makes.

**One cache, keyed by the file's content.** There is deliberately no second LRU in front of the
renderer's. A cache keyed by `page_id` is the obvious optimisation and it is a correctness bug: a
`(doc_id, revision)` re-ingested from corrected bytes keeps every page id, so such a cache would
serve the superseded pixels for as long as the process lived — and would hold a second copy of
every PNG while doing it. The tests below assert the identity (`cache_info` *is* the renderer's)
and the behaviour (evicting re-renders byte-identically).

**The chain, and its three distinct refusals.** `page_id` → the indexed page → the run that indexed
it (§6.9's `content_hash`) → the bytes in the document store (U029). A page that is not indexed, a
document whose file is missing, and a document whose file has been *replaced* are three different
facts, and the last is the one that otherwise fails silently: the pages of the previous run are
still current until publish retires them (§6.7), so rendering the new file for an old page would
answer with a page nobody indexed.
"""
from __future__ import annotations

import pytest

from vsir.core import ids
from vsir.ingest import probe as probe_module
from vsir.ingest import render as render_module
from vsir.ingest import store as store_module
from vsir.serve import raster_cache
from vsir.serve.caps import ToolError

from conftest import RASTER_DOC_ID, RASTER_PAGE_COUNT, RASTER_REVISION


@pytest.fixture
def resolve(rastered):
    """Resolve a `page_id` exactly as the route and the tool do — same client, same config."""
    def resolver(page_id: str):
        return raster_cache.resolve_page(rastered.client.app.state.search, rastered.config,
                                         page_id)
    return resolver


# ── the chain (U029 → U018) ─────────────────────────────────────────────────────────────────────

def test_a_page_id_resolves_to_the_document_and_the_page_inside_it(rastered, resolve):
    resolved = resolve(rastered.page_id(20))

    assert resolved.page_no == 20
    assert resolved.document == f"{RASTER_DOC_ID}@{RASTER_REVISION}"
    assert resolved.path.is_file()
    assert resolved.content_hash == rastered.record["content_hash"]


def test_the_expected_hash_comes_from_the_run_that_indexed_the_page(rastered, resolve):
    """§6.9 — nothing else can name the bytes these pages were indexed from: the payload carries
    no path (register **A5**) and the store is keyed by document identity."""
    resolved = resolve(rastered.page_id(20))

    assert resolved.expected_hash == rastered.record["content_hash"]
    assert resolved.expected_hash == probe_module.content_hash(resolved.path)


def test_every_page_of_the_document_resolves(rastered, resolve):
    """Asserted over all 42 rather than a sample: the chain has to hold for the whole document."""
    for page_no in range(1, RASTER_PAGE_COUNT + 1):
        assert resolve(rastered.page_id(page_no)).page_no == page_no


def test_one_retrieve_of_the_run_record_serves_a_whole_multi_page_fetch(rastered):
    """Five pages of one document ask the control plane once, not five times (§6.9)."""
    resolved = raster_cache.resolve_pages(rastered.client.app.state.search, rastered.config,
                                          rastered.page_ids(1, 2, 3, 4, 5))

    assert len(resolved) == 5
    assert len({page.expected_hash for page in resolved.values()}) == 1


# ── the three refusals, each distinct (§11.3) ───────────────────────────────────────────────────

def test_a_page_that_is_not_indexed_is_a_404_before_the_store_is_touched(rastered, resolve):
    """The index is the gate, so a citation for a document nobody ingested never reaches a path."""
    with pytest.raises(ToolError) as refusal:
        resolve("never-ingested@1.0#p001")

    assert refusal.value.code == "page_not_found"
    assert refusal.value.http_status == 404


@pytest.mark.parametrize("page_id", ["../../etc/passwd@1.0#p001", "..@1.0#p001",
                                     "a/b@1.0#p001"])
def test_a_page_id_that_would_be_a_path_traversal_never_reaches_the_filesystem(rastered, resolve,
                                                                               page_id):
    """Two gates, and the outer one is the index (U029's `SAFE_COMPONENT` is the inner one).

    A `page_id` is a value a caller may supply from a saved citation, so it is a path traversal's
    natural carrier. It is refused as `page_not_found` here — there is no such point in the
    collection — and `safe_component` refuses the same value at the store if it ever got that far.
    Both are asserted, because one gate is an accident away from being none.
    """
    with pytest.raises(ToolError) as refusal:
        resolve(page_id)

    assert refusal.value.code in {"page_not_found", "page_id_invalid"}

    with pytest.raises(store_module.DocumentIdUnsafe):
        store_module.file_name(page_id.split("@")[0], "1.0")


def test_a_document_missing_from_the_store_is_a_503_naming_it(rastered, tmp_path):
    """§11.3 — the page is indexed and its image cannot be made. Never a 500, never a blank PNG."""
    empty = store_module.DocumentStore(tmp_path / "an-empty-store")

    with pytest.raises(store_module.DocumentNotStored) as refusal:
        empty.for_page(rastered.page_id(20))

    assert refusal.value.code == "document_not_stored"
    assert refusal.value.http_status == 503
    assert refusal.value.details["document"] == f"{RASTER_DOC_ID}@{RASTER_REVISION}"


def test_bytes_that_disagree_with_the_run_are_refused_rather_than_rendered(rastered, resolve):
    """§6.7's silent case, closed. The window is real: between a corrected re-ingest and its
    publish, the previous run's pages are still `is_current` — and they recorded the previous
    hash, so what they get is a named refusal instead of a page nobody indexed."""
    stored = rastered.store.locate(RASTER_DOC_ID, RASTER_REVISION)
    original = stored.path.read_bytes()
    render_module.cache_clear()
    try:
        stored.path.write_bytes(b"%PDF-1.7\nsomebody replaced the file\n%%EOF\n")

        with pytest.raises(ToolError) as refusal:
            resolve(rastered.page_id(20))

        assert refusal.value.code == "document_hash_mismatch"
        assert refusal.value.http_status == 503
        assert refusal.value.details["expected_hash"] == rastered.record["content_hash"]
    finally:
        stored.path.write_bytes(original)
        render_module.cache_clear()

    assert resolve(rastered.page_id(20)).page_no == 20, "the store is back as it was"


def test_the_route_reports_that_refusal_as_a_503_over_http(rastered):
    """The same fact, through the transport: one translation, both surfaces (§7.3's shape)."""
    stored = rastered.store.locate(RASTER_DOC_ID, RASTER_REVISION)
    original = stored.path.read_bytes()
    render_module.cache_clear()
    try:
        stored.path.write_bytes(b"%PDF-1.7\nreplaced\n%%EOF\n")

        image = rastered.get_image(20)
        fetched = rastered.fetch(rastered.page_ids(20))

        assert image.status_code == 503, image.text
        assert image.json()["error"] == "document_hash_mismatch"
        assert fetched.status_code == 503
        assert fetched.json()["error"] == "document_hash_mismatch"
    finally:
        stored.path.write_bytes(original)
        render_module.cache_clear()


# ── one cache, and it is the renderer's ─────────────────────────────────────────────────────────

def test_the_serving_cache_is_the_renderers_cache(rastered):
    """No second LRU in front of it: `page_id` is not the bytes, so a page-keyed cache would go
    stale exactly when it matters (§6.7). Asserted as an identity rather than as a comment."""
    render_module.cache_clear()
    rastered.get_image(15, dpi=72)

    assert raster_cache.cache_info() == render_module.cache_info()
    assert raster_cache.cache_info()["maxsize"] == render_module.RASTER_CACHE_PAGES


def test_two_identical_requests_render_once_and_a_third_after_eviction_renders_again(rastered,
                                                                                     resolve):
    """The acceptance criterion at the level the cache lives at, with a call-count spy."""
    render_module.cache_clear()
    resolved = resolve(rastered.page_id(15))
    calls: list[tuple] = []
    real = render_module._render

    def counted(source, page_no, dpi, region):
        calls.append((page_no, dpi, region))
        return real(source, page_no, dpi, region)

    original = render_module._render
    render_module._render = counted
    try:
        first = raster_cache.raster(resolved, dpi=150)
        second = raster_cache.raster(resolved, dpi=150)

        assert len(calls) == 1
        assert second.png == first.png

        raster_cache.cache_clear()
        third = raster_cache.raster(resolved, dpi=150)

        assert len(calls) == 2
        assert third.png == first.png, "an evicted entry re-renders byte-identically"
    finally:
        render_module._render = original


def test_the_cache_distinguishes_the_dpi_and_the_region(rastered, resolve):
    """Every input that changes the pixels is in the key, or a crop would serve a whole page."""
    render_module.cache_clear()
    resolved = resolve(rastered.page_id(15))

    page = raster_cache.raster(resolved, dpi=150)
    finer = raster_cache.raster(resolved, dpi=220)
    crop = raster_cache.raster(resolved, dpi=150, region=(0.0, 0.0, 1.0, 0.5))

    assert len({page.sha256, finer.sha256, crop.sha256}) == 3
    assert render_module.cache_info()["misses"] >= 3


def test_renders_counts_only_what_was_actually_made(rastered, resolve):
    """What the audit line's `cache_hit` is computed from (§7.4) — misses, not hits."""
    render_module.cache_clear()
    resolved = resolve(rastered.page_id(16))

    before = raster_cache.cache_info()
    raster_cache.raster(resolved, dpi=72)
    after_first = raster_cache.cache_info()
    raster_cache.raster(resolved, dpi=72)
    after_second = raster_cache.cache_info()

    assert raster_cache.renders(before, after_first) == 1
    assert raster_cache.renders(after_first, after_second) == 0


# ── the megapixel prediction, over the real document ────────────────────────────────────────────

def test_the_predicted_total_is_the_sum_of_the_pages(rastered):
    resolved = raster_cache.resolve_pages(rastered.client.app.state.search, rastered.config,
                                          rastered.page_ids(1, 2, 3))

    total = raster_cache.total_megapixels(resolved.values(), dpi=150)

    assert total == pytest.approx(sum(raster_cache.megapixels(page, dpi=150)
                                      for page in resolved.values()))
    assert total > 6, "three A4 pages at 150 dpi are about 2.2 MP each"


def test_predicting_the_size_of_a_page_renders_nothing(rastered, resolve):
    """§15.1 — the bound has to be decidable without paying for the thing it bounds."""
    render_module.cache_clear()
    resolved = resolve(rastered.page_id(17))

    predicted = raster_cache.megapixels(resolved, dpi=400, region=(0.0, 0.0, 1.0, 0.55))

    assert predicted > 0
    assert render_module.cache_info()["misses"] == 0

    actual = raster_cache.raster(resolved, dpi=400, region=(0.0, 0.0, 1.0, 0.55))

    assert predicted == pytest.approx(actual.megapixels)


# ── what the store is not ───────────────────────────────────────────────────────────────────────

def test_the_document_store_holds_only_the_source_and_never_a_raster(rastered):
    """§4.2 — rasters are never persisted. The one file on that volume is the PDF that was
    ingested; everything else about a page is made on demand and kept in memory."""
    rastered.get_image(20, dpi=220)
    rastered.get_image(20, dpi=400, region="0,0,1,0.55")

    files = [path for path in rastered.store.root.rglob("*") if path.is_file()]

    assert [path.name for path in files] == [f"{RASTER_DOC_ID}@{RASTER_REVISION}.pdf"]
    assert not [path for path in files if path.suffix in {".png", ".jpg", ".jpeg", ".webp"}]


def test_no_page_payload_names_a_file(rastered, qdrant):
    """Register A5 — the stale `image_path` that made `read()` 503 for every page (§5.3).

    U029 gave the serving path a way to *find* the bytes; it did not put a path back on the
    record. The payload names the document, the store resolves the file.
    """
    point = qdrant.retrieve(rastered.collection, ids=[ids.point_id(rastered.page_id(20))],
                            with_payload=True)[0]

    assert "image_path" not in point.payload
    assert not [key for key in point.payload if "path" in key.lower()]
    assert str(rastered.store.root) not in str(point.payload)
