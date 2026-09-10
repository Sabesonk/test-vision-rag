"""L2 — `GET /pages/{page_id}/image`: the raster, over the real transport (§7.2.5, §7.4, U018).

The route `impl` had (`/api/v1/page-image/{page_id}`) read a PNG that step 03 had written for every
page at both dpis — 110 files and 20.7 MB for one 55-page document, before anything was validated
(register **E3**) — and the path it stored went stale, which is why `read()` returned 503 for every
page (**A5**). Here nothing is on disk: the `page_id` resolves through the document store to the
source PDF (U029) and the raster is made now, into an in-process cache (§4.2, §15 Factor VI).

Four properties are asserted that nothing else in the suite can:

* **the reference is dereferenceable.** Every envelope has carried an `image.url` since U017. This
  suite takes one of those URLs *verbatim* and gets a `200` — which is what makes the `#` of a
  `page_id` being percent-encoded a fact rather than an intention.
* **the cache is a cache.** One render for two identical requests, and after eviction the same
  request renders again and returns a **byte-identical** image. A cold instance is slower and
  never different.
* **nothing is written.** A filesystem-write spy around a whole request cycle, because §4.2's
  "rasters are never persisted" is exactly the sentence `impl` also believed it was following.
* **every refusal is distinct.** A page that is not indexed, a page that is not current, a document
  whose bytes are missing and a dpi that is not allowed are four different problems, and a caller
  retries them differently (§11.3).
"""
from __future__ import annotations

import builtins
import os
import pathlib
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from vsir.core import ids
from vsir.ingest import render as render_module
from vsir.serve.app import create_app
from vsir.serve.caps import ALLOWED_DPI

from conftest import (
    RASTER_DOC_ID,
    RASTER_NO_TEXT_PAGES,
    RASTER_PAGE_COUNT,
    RASTER_REVISION,
    TEST_TOKEN,
    serve_env,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


@contextmanager
def _write_spy(monkeypatch):
    """Every filesystem write this process attempts, by any Python route.

    The same spy `tests/unit/test_render.py` puts around the renderer, here around a whole HTTP
    request: the route resolves a document, opens a PDF, renders and serves, and the claim being
    checked is that not one of those steps produces a file. Reads are untouched — the source PDF
    has to be readable for any of this to work.
    """
    written: list[str] = []
    real_open, real_os_open, real_path_open = builtins.open, os.open, pathlib.Path.open

    def spy_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wxa+"):
            written.append(f"open({file!s}, {mode!r})")
        return real_open(file, mode, *args, **kwargs)

    def spy_os_open(path, flags, *args, **kwargs):
        if flags & _WRITE_FLAGS:
            written.append(f"os.open({path!s}, {flags})")
        return real_os_open(path, flags, *args, **kwargs)

    def spy_path_open(self, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wxa+"):
            written.append(f"Path.open({self!s}, {mode!r})")
        return real_path_open(self, mode, *args, **kwargs)

    def spy_write_bytes(self, data):
        written.append(f"Path.write_bytes({self!s})")
        raise AssertionError(f"the request wrote {len(data)} bytes to {self}")

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(os, "open", spy_os_open)
    monkeypatch.setattr(pathlib.Path, "open", spy_path_open)
    monkeypatch.setattr(pathlib.Path, "write_bytes", spy_write_bytes)
    yield written


# ── the happy path, and the authorisation in front of it ────────────────────────────────────────

def test_a_page_image_is_a_png_with_a_bearer_token(rastered):
    """§7.4 — the route's whole job, at the default `fetch` dpi."""
    response = rastered.get_image(20, dpi=150)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_MAGIC)
    assert len(response.content) > 10_000, "a rendered A4 page at 150 dpi is not a few bytes"


def test_the_same_page_without_a_token_is_refused(rastered):
    """§16 — a raster is never served without a credential, and the refusal comes first."""
    response = rastered.client.get(rastered.image_url(20, dpi=150))

    assert response.status_code == 401
    assert not response.content.startswith(PNG_MAGIC)


def test_a_wrong_token_is_refused_without_naming_what_it_should_have_been(rastered):
    response = rastered.client.get(rastered.image_url(20, dpi=150),
                                   headers={"Authorization": "Bearer not-this-releases-token"})

    assert response.status_code == 401
    assert TEST_TOKEN not in response.text


# ── the reference an envelope hands back is the URL that works ──────────────────────────────────

@pytest.mark.parametrize("tool", ["skim_pages", "lookup", "resolve"])
def test_an_image_reference_out_of_a_real_envelope_dereferences_to_a_png(rastered, tool):
    """U017 emitted the reference; this is the assertion that it points at something (U018).

    The URL is used **verbatim**, exactly as an agent or a browser `<img>` would: no
    reconstruction, no re-encoding, no knowledge of the grammar on the test's side. Before this
    unit that request reached `/pages/{doc_id}@{revision}` with the page number as a fragment the
    server never sees — a reference that was present, well-formed and undereferenceable.

    **All three page-level rungs**, because §7.1 puts an `ImageRef` on every page-level hit and
    one shared builder is an argument rather than a proof: `image_ref` is called from three
    modules, and a rung left out of this list is a rung whose references nothing has ever
    dereferenced.
    """
    arguments = {"query": "guard door interlocks", "limit": 3} if tool == "skim_pages" else \
                {"label": "K120"} if tool == "lookup" else \
                {"printed_label": "17"}
    envelope = rastered.client.post(f"/tools/{tool}", headers=rastered.header, json=arguments)
    assert envelope.status_code == 200, envelope.text
    hits = envelope.json()["hits"]
    assert hits, envelope.json()

    for hit in hits:
        url = hit["image"]["url"]
        assert "%23" in url and "#" not in url

        image = rastered.client.get(url, headers=rastered.header)

        assert image.status_code == 200, f"{url} → {image.text}"
        assert image.content.startswith(PNG_MAGIC)


def test_the_thumbnail_tier_is_smaller_than_the_page_tier(rastered):
    """36 and 72 are the triage tiers behind `thumb_url` (§7.3) — cheap, and really cheaper."""
    thumb = rastered.get_image(20, dpi=72)
    page = rastered.get_image(20, dpi=150)

    assert thumb.status_code == page.status_code == 200
    assert len(thumb.content) < len(page.content)


@pytest.mark.parametrize("dpi", [tier for tier in ALLOWED_DPI if tier <= 220])
def test_every_full_page_dpi_tier_is_served(rastered, dpi):
    response = rastered.get_image(20, dpi=dpi)

    assert response.status_code == 200, response.text
    assert response.content.startswith(PNG_MAGIC)


@pytest.mark.parametrize("dpi", [300, 400])
def test_above_the_answer_dpi_a_region_is_required_and_then_served(rastered, dpi):
    """§7.3 — detail that fine is about *part* of a page, and a full page at 400 dpi is 15 MP."""
    refused = rastered.get_image(20, dpi=dpi)

    assert refused.status_code == 400
    assert refused.json()["error"] == "dpi_requires_region"
    assert refused.json()["requested"] == dpi

    cropped = rastered.get_image(20, dpi=dpi, region="0,0,1,0.55")

    assert cropped.status_code == 200, cropped.text
    assert cropped.content.startswith(PNG_MAGIC)


def test_a_crop_is_a_strict_part_of_the_page_at_the_same_dpi(rastered):
    """D6 — `region` is normalised, so it means the same thing at every dpi."""
    full = rastered.get_image(20, dpi=220)
    top = rastered.get_image(20, dpi=220, region="0,0,1,0.5")

    assert full.status_code == top.status_code == 200
    assert len(top.content) < len(full.content)
    assert top.content != full.content


# ── the caps, each a typed 400 naming its bound (§7.3, F18) ─────────────────────────────────────

@pytest.mark.parametrize("dpi", ["100", "0", "-150", "abc", "150.5", ""])
def test_a_dpi_outside_the_allowed_set_is_a_typed_400_naming_the_set(rastered, dpi):
    """Including the ones that are not numbers: *"that is not a dpi"* belongs in the same family
    as *"that dpi is not allowed"*, because an agent switches on the `error` and not on the shape
    of the body. Declared as an `int` the route would have answered FastAPI's own 422 instead."""
    response = rastered.client.get(
        f"{rastered.image_url(20).split('?')[0]}?dpi={dpi}", headers=rastered.header)

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "dpi_not_allowed"
    assert response.json()["allowed"] == list(ALLOWED_DPI)


@pytest.mark.parametrize("region", ["0,0,2,2", "0,0,1", "0.9,0,0.1,1", "top-half", "0,0,1,0.5,1"])
def test_a_malformed_or_out_of_range_region_is_refused_and_never_clipped(rastered, region):
    """§11.3 — clipping `[0,0,2,2]` to the page would return a different crop and call it success."""
    response = rastered.get_image(20, dpi=220, region=region)

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "region_invalid"
    assert not response.content.startswith(PNG_MAGIC)


# ── the four distinct refusals (§11.3) ──────────────────────────────────────────────────────────

def test_a_page_that_is_not_indexed_is_a_404_naming_it(rastered):
    """Never a blank image: a page that does not exist and a page that is blank are not the same."""
    response = rastered.client.get(
        rastered.image_url(RASTER_PAGE_COUNT + 1), headers=rastered.header)

    assert response.status_code == 404, response.text
    assert response.json()["error"] == "page_not_found"


@pytest.mark.parametrize("page_id", ["not-a-page-id", "D@1#p0001", "D@1", "D@1#p000"])
def test_a_malformed_page_id_is_a_400_and_not_a_404(rastered, page_id):
    """§5.1 — only the canonical spelling parses, and a citation this service cannot interpret is
    the caller's bug rather than a fact about the corpus (`resolve` accepts saved citations)."""
    from vsir.serve import raster_cache

    response = rastered.client.get(
        f"/pages/{raster_cache.quoted_page_id(page_id)}/image?dpi=150", headers=rastered.header)

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "page_id_invalid"


def test_a_page_that_is_not_current_is_its_own_refusal(rastered, qdrant):
    """I7, F9 — told *"no such page"*, a caller concludes its citation was wrong. It was not:
    the run has not passed its gates, or a later revision superseded it. Different fact, different
    code, and `resolve` is the move that finds the page that answers now.

    The flag is flipped on one page directly and put back, because the alternative — a second
    42-page ingest stopped before publish — would cost minutes to assert one status code."""
    page_id = rastered.page_id(RASTER_PAGE_COUNT)
    point = ids.point_id(page_id)
    qdrant.set_payload(rastered.collection, payload={"is_current": False}, points=[point],
                       wait=True)
    try:
        response = rastered.client.get(rastered.image_url(RASTER_PAGE_COUNT),
                                       headers=rastered.header)

        assert response.status_code == 404, response.text
        assert response.json()["error"] == "page_not_current"
        assert page_id in response.json()["page_ids"]
    finally:
        qdrant.set_payload(rastered.collection, payload={"is_current": True}, points=[point],
                           wait=True)

    assert rastered.get_image(RASTER_PAGE_COUNT).status_code == 200


def test_a_document_missing_from_the_store_is_a_503_naming_the_document(rastered, monkeypatch):
    """§11.3 — the page is indexed and its image cannot be made. Never a 500, never a placeholder.

    The store is moved rather than the file deleted, so the session's one ingest survives: what is
    under test is the route's answer when `page_id` resolves to bytes that are not there.
    """
    from vsir.ingest import store as store_module

    empty = rastered.store.root / "not-the-store"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(store_module.DocumentStore, "from_config",
                        classmethod(lambda cls, cfg: cls(empty)))

    response = rastered.get_image(20)

    assert response.status_code == 503, response.text
    assert response.json()["error"] == "document_not_stored"
    assert response.json()["document"] == f"{RASTER_DOC_ID}@{RASTER_REVISION}"
    assert "re-ingest" in response.json()["detail"].lower() or "mount" in response.json()["detail"]


# ── the cache: one render, an eviction, and a byte-identical cold path ──────────────────────────

def test_the_second_identical_request_renders_nothing(rastered, monkeypatch):
    """U018's acceptance criterion, over the transport and with a call-count spy on the renderer."""
    render_module.cache_clear()
    calls: list[tuple] = []
    real = render_module._render

    def counted(source, page_no, dpi, region):
        calls.append((page_no, dpi, region))
        return real(source, page_no, dpi, region)

    monkeypatch.setattr(render_module, "_render", counted)

    first = rastered.get_image(11, dpi=150)
    second = rastered.get_image(11, dpi=150)

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert len(calls) == 1, f"the cache did not serve the second request: {calls}"

    render_module.cache_clear()
    after_eviction = rastered.get_image(11, dpi=150)

    assert len(calls) == 2, "an evicted entry must render again"
    assert after_eviction.content == first.content, "byte-identical, only slower"


def test_a_cold_process_returns_a_byte_identical_image(rastered, qdrant):
    """§15 Factor VI — a second instance, with an empty cache, answers identically.

    A different app object over the same collection and the same store, which is what a replica
    is: nothing about the answer may depend on which process rendered it, because nothing about it
    is held anywhere (the only thing the two share is the source document).
    """
    warm = rastered.get_image(7, dpi=220)
    assert warm.status_code == 200

    render_module.cache_clear()
    env = serve_env(VSIR_COLLECTION=rastered.config.collection,
                    VSIR_RUNS_COLLECTION=rastered.config.runs_collection,
                    VSIR_DOC_STORE=str(rastered.store.root))
    with TestClient(create_app(env)) as cold:
        response = cold.get(rastered.image_url(7, dpi=220), headers=rastered.header)

    assert response.status_code == 200, response.text
    assert response.content == warm.content


def test_serving_a_page_image_writes_nothing_to_the_filesystem(rastered, monkeypatch):
    """§4.2, register E3 — the sentence `impl` also believed it was following."""
    render_module.cache_clear()
    store_before = sorted(path.name for path in rastered.store.root.rglob("*"))

    with _write_spy(monkeypatch) as written:
        response = rastered.get_image(3, dpi=150)
        rastered.get_image(3, dpi=400, region="0,0,1,0.55")

    assert response.status_code == 200
    assert written == [], f"the request wrote to the filesystem: {written}"
    assert sorted(path.name for path in rastered.store.root.rglob("*")) == store_before


# ── the ETag, so a console can scroll thumbnails ────────────────────────────────────────────────

def test_the_response_carries_the_rasters_own_digest_and_revalidates(rastered):
    response = rastered.get_image(9, dpi=72)

    assert response.status_code == 200
    assert response.headers["etag"].strip('"')
    assert "must-revalidate" in response.headers["cache-control"]
    assert "private" in response.headers["cache-control"]


def test_a_matching_if_none_match_is_a_304_with_no_body(rastered):
    """The digest is the raster's own SHA-256, so it changes exactly when the pixels do."""
    first = rastered.get_image(9, dpi=72)
    etag = first.headers["etag"]

    again = rastered.client.get(rastered.image_url(9, dpi=72),
                                headers={**rastered.header, "If-None-Match": etag})

    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag


def test_a_different_dpi_is_a_different_etag(rastered):
    assert rastered.get_image(9, dpi=72).headers["etag"] != \
        rastered.get_image(9, dpi=150).headers["etag"]


# ── the event stream, and what is deliberately not on it (§7.4, §15.1) ──────────────────────────

def test_the_route_logs_the_request_without_widening_the_audit_schema(rastered, log_stream):
    """§7.4 audits the two *tools* that consume something; this is not one, so it logs its own
    event with the same facts. Widening `AUDITED_TOOLS` would widen an append-only schema."""
    from conftest import log_events

    assert rastered.get_image(12, dpi=72).status_code == 200
    events = log_events(log_stream)

    lines = [event for event in events if event["event"] == "page_image"]
    assert len(lines) == 1, events
    assert lines[0]["page_id"] == rastered.page_id(12)
    assert lines[0]["dpi"] == 72
    assert lines[0]["bytes"] > 0
    assert not [event for event in events if event["event"] == "audit"]
    assert TEST_TOKEN not in log_stream.getvalue()


def test_a_page_with_no_text_layer_still_renders(rastered):
    """§5.7 — a scanned page is the case the whole vision half exists for. It is not an error."""
    for page_no in RASTER_NO_TEXT_PAGES:
        response = rastered.get_image(page_no, dpi=150)

        assert response.status_code == 200, response.text
        assert response.content.startswith(PNG_MAGIC)
