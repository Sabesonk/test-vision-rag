"""L2 — `fetch`: material instead of an answer (Spec §7.2.5, §7.1, §7.4, U018).

The move this tool exists to make possible is *choose, then pay*. `impl` had no such tool: its
only way to see a page was `read()`, the vision call that bills — and which returned 503 for every
page anyway because the raster path on the record was stale (register **A5**). Splitting looking
from comprehending is what lets an agent decide whether a page is worth money.

What is asserted here is the contract, not the caps (`test_fetch_caps.py`) and not the cache
(`test_raster_cache.py`):

* **Family B, and never empty.** The pages were named, so there is nothing to be absent: `ok` with
  every page present, or a typed refusal. A `status` about the *call*, not about what was found.
* **the pixels and the URL are the same raster.** `inline=true` returns `bytes_b64`; the `url`
  beside it returns those same bytes from `GET /pages/{page_id}/image`. If they could differ, the
  console (`inline=false`) and the agent (`inline=true`) would be looking at different pages.
* **`include` controls the parts, and `None` is not empty.** Dropping `"image"` renders nothing at
  all; a page whose text layer is blank returns `""` and says `text_trust: "no_text"` beside it,
  which is F4's disclosure on this rung.
* **the text is `ingest/probe.py`'s and nobody else's** (I2, F15) — the same string `lookup`
  matched and `verify` checks against.
"""
from __future__ import annotations

import base64

import pytest

from vsir.core import ids
from vsir.ingest import render as render_module
from vsir.serve import audit as audit_module

from conftest import RASTER_NO_TEXT_PAGES, RASTER_PAGE_COUNT, TEST_TOKEN, log_events

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _pages(response) -> list[dict]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    return body["result"]["pages"]


# ── the envelope (§7.1 Family B) ────────────────────────────────────────────────────────────────

def test_a_fetch_returns_the_named_pages_in_the_order_they_were_named(rastered):
    wanted = rastered.page_ids(20, 3, 11)

    pages = _pages(rastered.fetch(wanted))

    assert [page["page_id"] for page in pages] == wanted


def test_the_envelope_is_family_b_with_provenance_and_reads_remaining(rastered):
    body = rastered.fetch(rastered.page_ids(20)).json()

    assert set(body) == {"status", "result", "reads_remaining", "provenance"}
    assert body["status"] == "ok"
    assert body["provenance"]["release_id"] == "test"
    assert body["provenance"]["schema_version"] == 1
    # Free (§8.1a): looking at a page does not consume the read budget.
    assert body["reads_remaining"] == rastered.config.read_quota


def test_no_response_field_is_a_score_and_none_is_an_ordinal(rastered):
    """§7.6 — `fetch` has no ordinal either: the caller chose these pages, nothing ranked them.

    Asserted on the field names rather than on the response text, because a megabyte of base64
    contains most short words by accident — a substring search over `bytes_b64` would be a test
    that passes or fails on the pixels.
    """
    pages = _pages(rastered.fetch(rastered.page_ids(20, 3), inline=False))

    for page in pages:
        assert not [key for key in page if "score" in key or key == "rank"]
        assert not [key for key in page["image"] if "score" in key or key == "rank"]


def test_the_same_page_named_twice_is_one_page(rastered):
    """§7.3 bounds *pages*: one page named five times is one page, rendered once."""
    page_id = rastered.page_id(20)

    pages = _pages(rastered.fetch([page_id] * 5))

    assert [page["page_id"] for page in pages] == [page_id]


# ── the pixels, and the reference beside them ───────────────────────────────────────────────────

def test_inline_defaults_to_true_and_the_bytes_are_a_png(rastered):
    """§7.2.5 — an agent needs the pixels in its context, and an MCP client cannot follow a URL."""
    page = _pages(rastered.fetch(rastered.page_ids(20)))[0]

    assert page["image"]["bytes_b64"], "inline is the default"
    assert base64.b64decode(page["image"]["bytes_b64"]).startswith(PNG_MAGIC)
    assert page["image"]["dpi"] == 150
    assert page["image"]["region"] is None
    assert page["image"]["width"] > 0 and page["image"]["height"] > 0


def test_the_inline_bytes_are_the_bytes_the_url_serves(rastered):
    """The two halves of §7.2.5 must be one raster.

    `inline=false` is what M7's console uses and `inline=true` is what an agent uses. If the URL
    could serve different pixels from the ones in the envelope, the operator and the agent would
    be looking at different pages while citing the same `page_id`.
    """
    page = _pages(rastered.fetch(rastered.page_ids(9)))[0]

    served = rastered.client.get(page["image"]["url"], headers=rastered.header)

    assert served.status_code == 200, served.text
    assert served.content == base64.b64decode(page["image"]["bytes_b64"])


def test_inline_false_returns_the_reference_only(rastered):
    """What the console uses, so megabytes do not travel through JSON twice (§7.2.5)."""
    inline = rastered.fetch(rastered.page_ids(20, 3))
    reference = rastered.fetch(rastered.page_ids(20, 3), inline=False)

    for page in _pages(reference):
        assert page["image"]["url"]
        assert page["image"]["bytes_b64"] is None
        assert page["image"]["width"] > 0, "the size is reported without moving the pixels"
    assert len(reference.content) * 20 < len(inline.content)


def test_a_crop_is_returned_at_the_dpi_that_requires_one(rastered):
    """§7.3, D6 — 400 dpi with a normalised region, rendered on demand and stored nowhere."""
    region = [0.0, 0.0, 1.0, 0.55]

    page = _pages(rastered.fetch(rastered.page_ids(20), dpi=400, region=region))[0]
    full = _pages(rastered.fetch(rastered.page_ids(20), dpi=220))[0]

    assert page["image"]["region"] == region
    assert page["image"]["dpi"] == 400
    assert page["image"]["width"] > full["image"]["width"], "400 dpi is finer than 220"
    # A portrait page cropped to its top 55% comes back wider than it is tall, which is the
    # cheapest available proof that a *region* was rendered and not a whole page at a finer dpi.
    assert page["image"]["height"] < page["image"]["width"]
    assert full["image"]["height"] > full["image"]["width"]
    assert base64.b64decode(page["image"]["bytes_b64"]).startswith(PNG_MAGIC)


# ── `include` — the parts, and what "not asked for" means ───────────────────────────────────────

def test_dropping_image_makes_it_a_cheap_text_read_and_renders_nothing(rastered):
    """§7.2.5, and the acceptance criterion: **zero** renders, not fewer renders."""
    render_module.cache_clear()
    before = render_module.cache_info()

    pages = _pages(rastered.fetch(rastered.page_ids(20, 3), include=["text", "summary"]))

    assert all(page["image"] is None for page in pages)
    assert all(page["text"] is not None for page in pages)
    assert render_module.cache_info()["misses"] == before["misses"], "nothing was rendered"


def test_a_text_read_needs_no_document_store_at_all(served, served_collection, corpus):
    """§7.2.5's *cheap text/summary read*, on a corpus that has no PDF behind it.

    The §13 M1 corpus is hand-written page text: those pages are indexed, current and answerable,
    and there has never been a source document for them. A `fetch` that resolved the document
    store before it read `include` refuses this call `document_not_stored` (503) — for bytes the
    caller did not ask for, on a rung §7.2.5 calls *cheap*. `text` and `summary` are payload
    fields (§5.3); the volume they were rendered from is nothing to do with them.

    The image half of the same call is asserted here too, because the fix must not have removed
    the refusal — only moved it behind the part that needs it.
    """
    page_id = corpus.expected["compact_labels"][0]["page_id"]
    header = {"Authorization": f"Bearer {TEST_TOKEN}"}

    body = {"page_ids": [page_id], "include": ["text", "summary"]}
    pages = _pages(served.post("/tools/fetch", headers=header, json=body))

    assert [page["page_id"] for page in pages] == [page_id]
    assert pages[0]["image"] is None
    assert pages[0]["text"], "the indexed text, with no source document in sight"

    refused = served.post("/tools/fetch", headers=header,
                          json={"page_ids": [page_id], "include": ["image"]})

    assert refused.status_code == 503, refused.text
    assert refused.json()["error"] == "document_not_stored"


def test_an_include_that_asks_for_nothing_is_the_cheapest_existence_check(rastered):
    pages = _pages(rastered.fetch(rastered.page_ids(20), include=[]))

    assert pages[0]["page_id"] == rastered.page_id(20)
    assert pages[0]["image"] is None
    assert pages[0]["text"] is None and pages[0]["summary"] is None
    assert pages[0]["text_trust"] == "ok", "a fact about the page, always disclosed"


def test_a_part_that_is_not_a_part_is_a_typed_400_naming_the_field(rastered):
    """A word this service silently ignored would be a page returned without what was asked for."""
    response = rastered.fetch(rastered.page_ids(20), include=["image", "summaries"])

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "invalid_request"
    assert any("include" in problem["field"] for problem in response.json()["problems"])


def test_the_text_is_the_indexed_text_and_nothing_re_extracted(rastered, qdrant):
    """I2, F15 — `ingest/probe.py` is the only writer of `text`, so this is a pass-through.

    Compared against the payload in the collection rather than against a re-extraction, because a
    second extractor is exactly the defect: the caller would be shown one string and have its
    claims checked against another.
    """
    page_id = rastered.page_id(20)
    point = qdrant.retrieve(rastered.collection, ids=[ids.point_id(page_id)],
                            with_payload=True)[0]

    page = _pages(rastered.fetch([page_id]))[0]

    assert page["text"] == point.payload["text"]
    assert "K120" in page["text"], "the corpus page this test is about"


def test_the_summary_is_the_pages_dominant_summary(rastered, qdrant):
    """D5 — one language per summary, never a blended string; `lang` says which one this is."""
    page_id = rastered.page_id(20)
    point = qdrant.retrieve(rastered.collection, ids=[ids.point_id(page_id)],
                            with_payload=True)[0]
    stored = point.payload["content"]["summaries"]

    page = _pages(rastered.fetch([page_id]))[0]

    assert stored, "the corpus page has a summary to return"
    assert page["summary"] == {"lang": stored[0]["lang"], "text": stored[0]["text"]}


@pytest.mark.parametrize("page_no", RASTER_NO_TEXT_PAGES)
def test_a_page_with_no_text_layer_says_so_beside_its_empty_text(rastered, page_no):
    """F4 on this rung. `text: ""` on its own reads as *"this page is blank"*, and the page is not
    blank — it has no text layer, which is what `text_trust` is there to say (§5.7). The image is
    the answer for a page like this, and it is returned."""
    page = _pages(rastered.fetch(rastered.page_ids(page_no)))[0]

    assert page["text"] == ""
    assert page["text_trust"] == "no_text"
    assert page["image"]["bytes_b64"], "the pixels are the only evidence this page has"


# ── the refusals that are not caps (§11.3) ──────────────────────────────────────────────────────

def test_a_page_that_is_not_indexed_refuses_the_whole_call(rastered):
    """Never a partial result: four pages and one that does not exist is not three-and-a-half."""
    response = rastered.fetch([*rastered.page_ids(20, 3),
                               rastered.page_id(RASTER_PAGE_COUNT + 1)])

    assert response.status_code == 404, response.text
    assert response.json()["error"] == "page_not_found"
    assert "result" not in response.json()


def test_a_malformed_page_id_is_a_400_and_names_which_one(rastered):
    response = rastered.fetch([rastered.page_id(20), "D@1#p0001"])

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "page_id_invalid"
    assert response.json()["page_ids"] == ["D@1#p0001"]


def test_a_fetch_of_no_pages_is_refused_rather_than_answered_emptily(rastered):
    response = rastered.fetch([])

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "fetch_empty"


def test_no_image_can_be_used_as_a_query_here(rastered):
    """I2, I3 — a photograph may *find* a page; it can never be an argument to this tool."""
    response = rastered.fetch(rastered.page_ids(20), image="aGVsbG8=")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


# ── the audit line (§7.4) ───────────────────────────────────────────────────────────────────────

def test_one_fetch_writes_one_audit_line_with_exactly_ten_fields(rastered, log_stream):
    """§7.4 audits `read` **and** `fetch`. Free (§8.1a) and audited anyway: the line tracks
    image-byte movement, which is the resource this tool actually consumes."""
    render_module.cache_clear()
    assert rastered.fetch(rastered.page_ids(20, 3), dpi=72).status_code == 200

    lines = [event["audit"] for event in log_events(log_stream) if event["event"] == "audit"]

    assert len(lines) == 1, lines
    line = lines[0]
    # The *set*, not the order: the event stream serialises with sorted keys, and §7.4's field
    # order is asserted where it is declared — `audit.py` raises at import if `AuditLine` and
    # `AUDIT_FIELDS` disagree.
    assert sorted(line) == sorted(audit_module.AUDIT_FIELDS)
    assert len(line) == 10
    assert line["tool"] == "fetch"
    assert line["page_ids"] == rastered.page_ids(20, 3)
    assert line["dpi"] == 72
    assert line["cache_hit"] is False, "the cache was cleared, so both pages were rendered"
    assert (line["input_tokens"], line["output_tokens"]) == (0, 0), "no model was called"
    assert line["latency_ms"] >= 0


def test_a_second_identical_fetch_records_the_cache_hit(rastered, log_stream):
    """The one number that says the call cost no memory and no time (§7.4, §6.3's argument)."""
    render_module.cache_clear()
    rastered.fetch(rastered.page_ids(11), dpi=72)
    rastered.fetch(rastered.page_ids(11), dpi=72)

    lines = [event["audit"] for event in log_events(log_stream) if event["event"] == "audit"]

    assert [line["cache_hit"] for line in lines] == [False, True]


def test_a_text_only_fetch_records_no_dpi_because_it_rendered_nothing(rastered, log_stream):
    rastered.fetch(rastered.page_ids(11), include=["text"])

    lines = [event["audit"] for event in log_events(log_stream) if event["event"] == "audit"]

    assert len(lines) == 1
    assert lines[0]["dpi"] == 0 and lines[0]["cache_hit"] is False


def test_no_page_text_or_image_bytes_reach_the_event_stream(rastered, log_stream):
    """§15.1's retention row — an audit stream carrying page text is a copy of the corpus in the
    log aggregator, with the retention policy of a log aggregator."""
    page = _pages(rastered.fetch(rastered.page_ids(20)))[0]
    stream = log_stream.getvalue()

    assert page["image"]["bytes_b64"][:64] not in stream
    assert page["text"][:64] not in stream
