"""L2 — every §7.3 bound on `fetch`, each a typed 400 naming it (F18's `fetch` half, U018).

The rule these tests exist to defend is not *"the bound is enforced"* — it is **never a clamp and
never a truncation** (§11.3). Both alternatives are worse than a refusal, and both are the
convenient thing to write:

* a six-page call answered with five pages reports success about pages the caller never saw, and
  it cannot tell which one is missing;
* a `dpi=400` quietly served at 220 returns an image the operator cannot read the part number off,
  and reports success.

In both cases the caller has no way to know, so the failure surfaces as a wrong answer somewhere
downstream instead of an error here.

The megapixel bound has a second property asserted below: it is decided **before** anything is
rendered. A 12 MP ceiling enforced by measuring the pixmap has already allocated what it refuses,
which is exactly the resource limit §15.1 asks it to protect.
"""
from __future__ import annotations

import pytest

from vsir.ingest import render as render_module
from vsir.serve.caps import (
    ALLOWED_DPI,
    MAX_FETCH_MEGAPIXELS,
    MAX_FETCH_PAGES,
    REGION_REQUIRED_ABOVE,
)

from conftest import log_events

CROP = [0.0, 0.0, 1.0, 0.55]


# ── the page count (the acceptance criterion, verbatim) ─────────────────────────────────────────

def test_six_pages_is_refused_and_there_is_no_partial_five_page_result(rastered):
    """`fetch_budget_exceeded {limit: 5, requested: 6}` — and **no** 200 with five pages."""
    response = rastered.fetch(rastered.page_ids(1, 2, 3, 4, 5, 6))

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"] == "fetch_budget_exceeded"
    assert body["limit"] == MAX_FETCH_PAGES == 5
    assert body["requested"] == 6
    assert body["bound"] == "pages"
    assert "result" not in body and "pages" not in body


def test_five_pages_is_the_bound_and_is_served(rastered):
    response = rastered.fetch(rastered.page_ids(1, 2, 3, 4, 5), inline=False)

    assert response.status_code == 200, response.text
    assert len(response.json()["result"]["pages"]) == 5


def test_an_over_budget_call_renders_nothing_at_all(rastered):
    """The bound is checked before the work, so a refused call costs a round trip and no pixels."""
    render_module.cache_clear()
    before = render_module.cache_info()

    refused = rastered.fetch(rastered.page_ids(1, 2, 3, 4, 5, 6))

    assert refused.status_code == 400
    assert render_module.cache_info()["misses"] == before["misses"]


# ── the megapixel total ─────────────────────────────────────────────────────────────────────────

def test_two_pages_at_300_dpi_exceed_the_megapixel_bound_and_name_it(rastered):
    """§7.3 — an A4 page at 300 dpi is 8.7 MP, so two of them are 17.4 and the pair is refused.

    Named as the *megapixel* bound and not as the page bound: two pages are inside the five-page
    limit, and a caller told only `fetch_budget_exceeded` would retry with two pages again. What
    it must not get is a silent drop to a lower dpi.
    """
    response = rastered.fetch(rastered.page_ids(20, 3), dpi=300, region=[0.0, 0.0, 1.0, 1.0])

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"] == "fetch_budget_exceeded"
    assert body["bound"] == "megapixels"
    assert body["limit"] == MAX_FETCH_MEGAPIXELS == 12.0
    assert body["requested"] > MAX_FETCH_MEGAPIXELS
    assert "result" not in body


def test_the_megapixel_bound_is_decided_before_a_single_render(rastered, monkeypatch):
    """§15.1 — rendering is the memory spike, so the bound that caps it cannot pay for it first."""
    render_module.cache_clear()
    rendered: list[tuple] = []
    monkeypatch.setattr(render_module, "_render",
                        lambda *args: rendered.append(args) or pytest.fail("rendered anyway"))

    response = rastered.fetch(rastered.page_ids(20, 3), dpi=300, region=[0.0, 0.0, 1.0, 1.0])

    assert response.status_code == 400
    assert response.json()["bound"] == "megapixels"
    assert rendered == []


def test_one_page_at_300_dpi_fits_and_is_served(rastered):
    response = rastered.fetch(rastered.page_ids(20), dpi=300, region=CROP)

    assert response.status_code == 200, response.text
    assert response.json()["result"]["pages"][0]["image"]["dpi"] == 300


def test_a_text_only_fetch_is_not_measured_in_megapixels(rastered):
    """Dropping `"image"` renders nothing, so the raster budget has nothing to bound (§7.2.5).

    The same five pages at the same dpi, twice: with images it is 23 MP and refused, and as a
    text read it is served. That is what makes the bound a bound on *rasters* rather than a bound
    on calls — an agent that only needs the text of five pages is not competing for the memory a
    render would take.
    """
    wanted = rastered.page_ids(1, 2, 3, 4, 5)

    with_images = rastered.fetch(wanted, dpi=220, inline=False)
    text_only = rastered.fetch(wanted, dpi=220, include=["text", "summary"])

    assert with_images.status_code == 400, with_images.text
    assert with_images.json()["bound"] == "megapixels"
    assert text_only.status_code == 200, text_only.text
    assert all(page["image"] is None for page in text_only.json()["result"]["pages"])


# ── the dpi set, and the region rule above the answer dpi ───────────────────────────────────────

@pytest.mark.parametrize("dpi", [1, 35, 100, 149, 221, 500, 1200])
def test_a_dpi_off_the_list_is_dpi_not_allowed(rastered, dpi):
    response = rastered.fetch(rastered.page_ids(20), dpi=dpi, region=CROP)

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "dpi_not_allowed"
    assert response.json()["allowed"] == list(ALLOWED_DPI)
    assert response.json()["requested"] == dpi


@pytest.mark.parametrize("dpi", [36, 72])
def test_the_two_thumbnail_tiers_succeed(rastered, dpi):
    """36 and 72 are the triage tiers behind `thumb_url` (§7.3) — and they are real dpis."""
    response = rastered.fetch(rastered.page_ids(20), dpi=dpi)

    assert response.status_code == 200, response.text
    image = response.json()["result"]["pages"][0]["image"]
    assert image["dpi"] == dpi
    assert image["width"] < 700, "a thumbnail is a thumbnail"


@pytest.mark.parametrize("dpi", [300, 400])
def test_above_the_answer_dpi_a_region_is_required(rastered, dpi):
    response = rastered.fetch(rastered.page_ids(20), dpi=dpi)

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"] == "dpi_requires_region"
    assert body["requested"] == dpi
    assert body["region_required_above"] == REGION_REQUIRED_ABOVE == 220


def test_the_same_call_with_a_region_succeeds_and_returns_a_crop(rastered):
    """The acceptance criterion's second half: the rule is a redirection, not a wall."""
    response = rastered.fetch(rastered.page_ids(20), dpi=400, region=CROP)

    assert response.status_code == 200, response.text
    image = response.json()["result"]["pages"][0]["image"]
    assert image["region"] == CROP
    assert image["bytes_b64"]


@pytest.mark.parametrize("region", [
    [0.0, 0.0, 2.0, 2.0],            # outside the page
    [0.0, 0.0, 1.0],                 # three values
    [0.5, 0.0, 0.5, 1.0],            # zero width
    [1.0, 0.0, 0.0, 1.0],            # inverted
    [-0.1, 0.0, 1.0, 1.0],           # negative
])
def test_an_out_of_range_region_is_a_typed_400_and_not_a_clipped_guess(rastered, region):
    """§11.3 — clamping `[0,0,2,2]` to the page returns a different crop and calls it success."""
    response = rastered.fetch(rastered.page_ids(20), dpi=400, region=region)

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "region_invalid"
    assert "result" not in response.json()


# ── an empty call, and the shape of every refusal ───────────────────────────────────────────────

def test_a_refusal_names_the_tool_and_carries_no_envelope(rastered):
    """A caller switches on `error`; a refusal is not a half-filled envelope (§7.1, §11.3)."""
    body = rastered.fetch(rastered.page_ids(1, 2, 3, 4, 5, 6)).json()

    assert body["tool"] == "fetch"
    assert set(body) >= {"error", "detail", "tool", "limit", "requested"}
    assert "status" not in body, "a refusal is not an envelope with a status in it"


def test_no_refused_call_writes_an_audit_line(rastered, log_stream):
    """§7.4's line records what a call consumed, and a refused call consumed nothing."""
    assert rastered.fetch(rastered.page_ids(1, 2, 3, 4, 5, 6)).status_code == 400
    assert rastered.fetch(rastered.page_ids(20), dpi=100).status_code == 400

    assert [event for event in log_events(log_stream) if event["event"] == "audit"] == []
    refusals = [event for event in log_events(log_stream) if event["event"] == "tool_refused"]
    assert {event["code"] for event in refusals} == {"fetch_budget_exceeded", "dpi_not_allowed"}
