"""The corpus surface — `GET /documents`, one document, and a revision's pages (§5.1–5.3, §5.7).

Before these routes existed the only way to learn what the index held was to search it, so an
operator could ingest a corpus and had no way to see the corpus. What is asserted here is mostly
about **honesty of the numbers**: exact counts, a superseded revision that is listed rather than
hidden, and a `searchable_ratio` that matches what a triage row reports for the same document.

The `served` corpus is exactly the right shape for it — `SYN-M1` at revision `1.0` (30 pages,
current) and `0.9` (one page, superseded) — so "lists the revision no search reaches" is checked
against a real superseded revision and not a hand-made one.
"""
from __future__ import annotations

import pytest

from vsir.serve import auth as auth_module
from vsir.serve import manage

PATHS = ("/documents", "/documents/SYN-M1", "/documents/SYN-M1/pages")


@pytest.mark.parametrize("path", PATHS)
def test_the_corpus_surface_needs_a_bearer_token(served, path):
    """What the index contains is corpus data — free to nobody (§7.4)."""
    assert path not in auth_module.PUBLIC_PATHS
    assert served.get(path).status_code == 401


def test_the_listing_returns_the_document_with_both_revisions(served, token_header):
    """31 pages across two revisions, 30 of them reachable — exact, not estimated."""
    body = served.get("/documents", headers=token_header).json()

    assert body["total"] == 1
    assert body["returned"] == 1
    assert body["truncated"] is False
    row = body["documents"][0]
    assert row["doc_id"] == "SYN-M1"
    assert row["pages"] == 31
    assert row["current_pages"] == 30
    assert row["current_revision"] == "1.0"
    assert [revision["revision"] for revision in row["revisions"]] == ["0.9", "1.0"]


def test_the_superseded_revision_is_listed_and_marked_unreachable(served, token_header):
    """§6.7 **keeps** the old revision (F9), so this surface has to show it as kept.

    `is_current=False` with `pages=1` is the fact an operator needs: the revision exists, its page
    is still fetchable by `page_id`, and no search will ever return it.
    """
    row = served.get("/documents/SYN-M1", headers=token_header).json()

    superseded = next(entry for entry in row["revisions"] if entry["revision"] == "0.9")
    assert superseded["pages"] == 1
    assert superseded["current_pages"] == 0
    assert superseded["is_current"] is False

    current = next(entry for entry in row["revisions"] if entry["revision"] == "1.0")
    assert current["is_current"] is True
    assert current["current_pages"] == 30


def test_an_unknown_document_is_a_typed_404_and_never_an_empty_row(served, token_header):
    """A document never ingested and one whose revisions were all retired are different facts."""
    answered = served.get("/documents/NOPE", headers=token_header)

    assert answered.status_code == 404
    assert answered.json()["error"] == "document_not_found"
    assert answered.json()["doc_id"] == "NOPE"


def test_the_page_inventory_is_in_page_order_and_carries_usable_page_ids(served, token_header):
    """Every row's `page_id` is what `fetch`, `read` and `verify` take (§5.2) — checked, not
    assumed: an inventory whose ids no tool accepts is a listing of nothing."""
    body = served.get("/documents/SYN-M1/pages?limit=200", headers=token_header).json()

    assert body["doc_id"] == "SYN-M1"
    assert body["revision"] == "1.0"
    assert body["total"] == 30
    numbers = [row["page_no"] for row in body["pages"]]
    assert numbers == sorted(numbers)
    assert body["pages"][0]["page_id"] == "SYN-M1@1.0#p001"   # §5.2 zero-pads the page no
    assert all(row["revision"] == "1.0" for row in body["pages"])
    assert all(row["image_url"] for row in body["pages"])


def test_a_listed_page_id_is_one_the_tools_accept(served, token_header):
    """The inventory and the tool surface agree on what a page is."""
    listed = served.get("/documents/SYN-M1/pages?limit=1", headers=token_header).json()
    page_id = listed["pages"][0]["page_id"]

    verified = served.post("/tools/verify", headers=token_header,
                           json={"claims": ["SF 1.1A"], "page_ids": [page_id]})

    assert verified.status_code == 200


def test_the_inventory_defaults_to_the_published_revision_and_says_which(served, token_header):
    """A caller who asked for "the document" is told which revision it is looking at."""
    defaulted = served.get("/documents/SYN-M1/pages", headers=token_header).json()
    asked = served.get("/documents/SYN-M1/pages?revision=0.9", headers=token_header).json()

    assert defaulted["revision"] == "1.0"
    assert asked["revision"] == "0.9"
    assert asked["total"] == 1
    assert asked["pages"][0]["is_current"] is False


def test_an_unknown_revision_names_the_ones_there_are(served, token_header):
    """A refusal that lets the next attempt be correct rather than a retry of the same mistake."""
    answered = served.get("/documents/SYN-M1/pages?revision=7.7", headers=token_header)

    assert answered.status_code == 404
    body = answered.json()
    assert body["error"] == "document_not_found"
    assert sorted(body["available"]) == ["0.9", "1.0"]


def test_paging_walks_every_page_exactly_once(served, token_header):
    """A `page_no` offset rather than an opaque cursor, so paging cannot re-shuffle or skip."""
    seen: list[int] = []
    offset: int | None = 0
    while offset is not None:
        body = served.get(f"/documents/SYN-M1/pages?limit=7&offset={offset}",
                          headers=token_header).json()
        seen.extend(row["page_no"] for row in body["pages"])
        offset = body["next_offset"]

    assert sorted(seen) == list(range(1, 31))
    assert len(seen) == len(set(seen)), "a page was returned twice"


@pytest.mark.parametrize("limit", [0, -1, manage.MAX_PAGE_SIZE + 1])
def test_a_listing_bound_is_a_typed_400_naming_itself(served, token_header, limit):
    """A bound with its own code, like every other bound in this service (§7.3)."""
    answered = served.get(f"/documents/SYN-M1/pages?limit={limit}", headers=token_header)

    assert answered.status_code == 400
    body = answered.json()
    assert body["error"] == "listing_limit_exceeded"
    assert body["limit"] == manage.MAX_PAGE_SIZE
    assert body["requested"] == limit


def test_the_searchable_ratio_is_the_one_a_triage_row_reports(aggregating, token_header):
    """§5.7's number, and the reason it is on this row: at 0.00 `lookup` cannot answer at all.

    Checked against the *same* documents a `skim_documents` groups, because two different numbers
    for one document's searchability is the failure mode — an operator clearing an ingest against
    one of them while an agent acts on the other.
    """
    listed = aggregating.get("/documents?limit=100", headers=token_header).json()
    ratios = {row["doc_id"]: row["searchable_ratio"] for row in listed["documents"]}

    assert ratios["AGG-TEXT"] == pytest.approx(1.0)
    assert ratios["AGG-MIXED"] == pytest.approx(0.5)     # 2 of its 4 pages have a text layer

    skimmed = aggregating.post("/tools/skim_documents", headers=token_header,
                               json={"query": "carton discharge"}).json()
    for hit in skimmed["hits"]:
        if hit["doc_id"] in ratios:
            assert hit["searchable_ratio"] == pytest.approx(ratios[hit["doc_id"]])


def test_a_document_with_no_text_layer_reports_zero_rather_than_nothing(aggregating,
                                                                       token_header):
    """0.00 is an answer, and it is the answer that stops a 'not found' from being believed."""
    listed = aggregating.get("/documents?limit=100", headers=token_header).json()
    rows = {row["doc_id"]: row for row in listed["documents"]}

    assert rows["AGG-SCAN"]["searchable_ratio"] == pytest.approx(0.0)
    assert rows["AGG-SCAN"]["current_pages"] > 0


def test_the_listing_reports_truncation_as_a_fact_and_not_an_inference(aggregating,
                                                                      token_header):
    """`total` is the exact number of documents, so `truncated` does not have to be guessed at."""
    body = aggregating.get("/documents?limit=5", headers=token_header).json()

    assert body["returned"] == 5
    assert body["total"] == 15
    assert body["truncated"] is True


def test_the_corpus_surface_writes_nothing(served, token_header, qdrant, served_collection):
    """Read-only, asserted: retirement is §6.7's and it runs inside a publish, not from here."""
    before = qdrant.count(served_collection, exact=True).count

    for path in PATHS:
        served.get(path, headers=token_header)
    assert served.delete("/documents/SYN-M1", headers=token_header).status_code == 405
    assert served.post("/documents/SYN-M1", headers=token_header).status_code == 405

    assert qdrant.count(served_collection, exact=True).count == before


# ── the two defects found reviewing this surface before shipping it ─────────────────────────────

def test_paging_survives_a_hole_in_the_page_numbering(served, token_header, qdrant,
                                                      served_collection):
    """A `page_no` that is not `1..total` must not end the walk early.

    The first cut gated `next_offset` on ``last + 1 <= total``, which mixes a **count** with an
    **index**. `ingest/export.py` guards against exactly the document those two disagree on — one
    whose page numbering has a hole — and with one, `total` is smaller than the last `page_no`, so
    that comparison stopped paging and reported a truncated inventory as a complete one.

    The corpus has no hole, so one is made here: three pages of a document numbered far apart, which
    is the smallest thing that reproduces it (`total` is 3 and the last `page_no` is 900).
    """
    from qdrant_client import models as qm

    from vsir.core import ids

    doc_id = "HOLE-DOC"
    points = [
        qm.PointStruct(
            id=ids.point_id(ids.page_id(doc_id, "1.0", page_no)),
            vector={"dense": [0.01] * 1536},
            payload={"doc_id": doc_id, "revision": "1.0", "is_current": True, "page_no": page_no,
                     "has_text": True, "text_trust": "ok", "page_kind": "prose",
                     "doc_type": "manual", "lang": ["en"], "section_id": [], "series_id": [],
                     "run_id": "r-hole", "text": f"page {page_no}", "vlm_codes": "",
                     "provenance": {"page_id": ids.page_id(doc_id, "1.0", page_no),
                                    "run_id": "r-hole", "release_id": "test"}},
        )
        for page_no in (1, 500, 900)
    ]
    qdrant.upsert(served_collection, points=points, wait=True)
    try:
        seen: list[int] = []
        offset: int | None = 0
        while offset is not None:
            body = served.get(f"/documents/{doc_id}/pages?limit=2&offset={offset}",
                              headers=token_header).json()
            seen.extend(row["page_no"] for row in body["pages"])
            offset = body["next_offset"]

        assert seen == [1, 500, 900], "the walk stopped before the last page"
    finally:
        qdrant.delete(served_collection, points_selector=qm.Filter(must=[
            qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]), wait=True)


def test_a_document_with_no_published_revision_reports_a_real_ratio(served, token_header, qdrant,
                                                                   served_collection):
    """With nothing published there is no *current* revision to measure — measure the newest.

    The first cut passed `""` as the revision in that case, which filters on ``revision == ""``,
    matches nothing, and reported `searchable_ratio: 0.00` for a document that demonstrably has
    pages — the one number on this row an operator acts on, inverted, and inverted in the
    direction that says "this binder is unsearchable" about a binder that is merely unpublished.
    """
    from qdrant_client import models as qm

    from vsir.core import ids

    doc_id = "UNPUBLISHED-DOC"
    points = [
        qm.PointStruct(
            id=ids.point_id(ids.page_id(doc_id, "2.0", page_no)),
            vector={"dense": [0.01] * 1536},
            payload={"doc_id": doc_id, "revision": "2.0", "is_current": False,
                     "page_no": page_no, "has_text": True, "text_trust": "ok",
                     "page_kind": "prose", "doc_type": "manual", "lang": ["en"],
                     "section_id": [], "series_id": [], "run_id": "r-unpub",
                     "text": f"page {page_no}", "vlm_codes": "",
                     "provenance": {"page_id": ids.page_id(doc_id, "2.0", page_no),
                                    "run_id": "r-unpub", "release_id": "test"}},
        )
        for page_no in (1, 2)
    ]
    qdrant.upsert(served_collection, points=points, wait=True)
    try:
        row = served.get(f"/documents/{doc_id}", headers=token_header).json()

        assert row["current_revision"] == "", "nothing here passed its gates"
        assert row["current_pages"] == 0
        assert row["pages"] == 2
        # Both pages have a text layer, so the ratio is 1.00 — the document is unpublished, which
        # is not the same fact as unsearchable.
        assert row["searchable_ratio"] == pytest.approx(1.0)

        # And its pages are still listable, under the revision it actually has.
        pages = served.get(f"/documents/{doc_id}/pages", headers=token_header).json()
        assert pages["revision"] == "2.0"
        assert pages["total"] == 2
    finally:
        qdrant.delete(served_collection, points_selector=qm.Filter(must=[
            qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]), wait=True)


def test_a_document_retired_mid_listing_does_not_fail_the_listing(served, token_header, qdrant,
                                                                 served_collection, monkeypatch):
    """One row vanishing must not cost the caller the other fourteen.

    `documents()` facets for ids and then reads each one, so there are two round trips and a
    publish or a delete can land between them. `document()` refuses an unknown id with a `404`,
    which is right when the caller *named* it and wrong in a listing: propagating it would turn
    somebody else's ordinary write into this caller's outage.

    Simulated by making the facet report a document that is not there, which is exactly what a
    delete landing between the two calls looks like from here.
    """
    from vsir.serve import manage as manage_module

    real = manage_module.document_ids

    def with_a_ghost(client, collection, *, limit, scope=()):
        counts, total = real(client, collection, limit=limit, scope=scope)
        return {**counts, "GHOST-DOC": 3}, total + 1

    monkeypatch.setattr(manage_module, "document_ids", with_a_ghost)

    answered = served.get("/documents", headers=token_header)

    assert answered.status_code == 200
    body = answered.json()
    assert [row["doc_id"] for row in body["documents"]] == ["SYN-M1"]
    assert body["total"] == 1, "the ghost must not be counted as a document that exists"
    assert body["returned"] == 1
