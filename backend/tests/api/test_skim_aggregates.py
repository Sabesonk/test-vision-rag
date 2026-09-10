"""L2 — `skim_documents` and `skim_sections`, the two aggregate rungs (Spec §7.2.1, U019).

The claim these suites exist to check is a **structural** one: §7.2.1 says the three rungs are
*"the same page query aggregated differently"*, and a paragraph cannot enforce that. Two
implementations against one store would pass every assertion about shape and still drift — a
different filter here, a deeper branch there — until `skim_documents` named a binder whose pages
`skim_pages` did not return. So the load-bearing test is the set equality of
:func:`test_the_documents_are_exactly_the_documents_of_the_page_rung`, and the two counts beside
it: `pages_matched` is the number of `skim_pages` rows in the group and `best_rank` is the
smallest `rank` in it. If the aggregates ever become a second search, those three fail together.

The rest divides as `skim_pages`' does. One half is the contract — ≤ 10 rows, the ordering,
`next.expand` as a *scope* rather than a citation, and the P2 line these rows draw one field
further out than a `PageHit` does: **no `page_id` at all**, because a row that answers *"which
binder?"* and also names a page has already made the choice §7.6 refuses to make. The other half
is the refusals, which belong to the search all three rungs share and are asserted on the two new
names because a caller who typed `skim_sections` must be refused by `skim_sections`.

`searchable_ratio` has its own suite next door (`test_searchable_ratio.py`): it is §5.7's number
and the reason the document rung exists, not one field among nine.
"""
from __future__ import annotations

import base64

import pytest

from vsir.serve.envelope import UNRANKED
from vsir.serve.tools.skim import SKIM_LIMIT

from conftest import AGGREGATE_CODE, AGGREGATE_LEAFLETS, AGGREGATE_QUERY

#: The same one-pixel PNG `test_image_query.py` uses. The stub embedder hashes the bytes, so what
#: matters is that they are stable, not that they are a photograph of anything.
PANEL_B64 = base64.b64encode(base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)).decode()

DOCUMENTS = "/tools/skim_documents"
SECTIONS = "/tools/skim_sections"
PAGES = "/tools/skim_pages"

#: The three-document half of the corpus. The twelve leaflets are `doc_type: leaflet` and are
#: reached by scoping to them — one collection, two sub-corpora, told apart by a scope.
MANUALS = {"doc_type": "manual"}
LEAFLETS = {"doc_type": "leaflet"}


def call(client, headers, route, **body):
    response = client.post(route, json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def refused(client, headers, route, **body):
    response = client.post(route, json=body, headers=headers)
    assert response.status_code == 400, response.text
    return response.json()


# ── one implementation, three aggregations (§7.2.1) ──────────────────────────────────────────────

def test_the_documents_are_exactly_the_documents_of_the_page_rung(aggregating, token_header):
    """The set equality that makes *"the same page query"* a property and not a promise.

    `limit` is the page rung's maximum, because the two rungs differ in **how many rows they
    render**, not in what they searched: the aggregate groups every fused candidate, so the page
    rung has to be allowed to return every fused candidate for the comparison to be about the
    search rather than about the cut. The corpus is 13 `manual` pages, well inside 25.
    """
    documents = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY, scope=MANUALS, limit=25)

    from_pages = {hit["page_id"].split("@")[0] for hit in pages["hits"]}
    assert {hit["doc_id"] for hit in documents["hits"]} == from_pages
    assert len(from_pages) == 3


def test_pages_matched_and_best_rank_are_read_off_the_page_rows(aggregating, token_header):
    """§7.2.1 rule 4, checked against the rows themselves rather than against a second count."""
    documents = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY, scope=MANUALS, limit=25)

    grouped: dict[str, list[int]] = {}
    for hit in pages["hits"]:
        grouped.setdefault(hit["page_id"].split("@")[0], []).append(hit["rank"])

    for hit in documents["hits"]:
        ranks = grouped[hit["doc_id"]]
        assert hit["pages_matched"] == len(ranks)
        assert hit["best_rank"] == min(ranks)


def test_the_sections_are_exactly_the_sections_of_the_page_rows(aggregating, token_header):
    """The same property one rung down — and a page straddling two sections counts in both."""
    sections = call(aggregating, token_header, SECTIONS, query=AGGREGATE_QUERY, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY, scope=MANUALS, limit=25)

    grouped: dict[str, list[int]] = {}
    for hit in pages["hits"]:
        for section_id in hit["next"]["expand"].get("section_id") or ():
            grouped.setdefault(section_id, []).append(hit["rank"])

    assert {hit["section_id"] for hit in sections["hits"]} == set(grouped)
    for hit in sections["hits"]:
        assert hit["pages_matched"] == len(grouped[hit["section_id"]])
        assert hit["best_rank"] == min(grouped[hit["section_id"]])


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_at_most_ten_rows_ordered_by_best_rank_then_by_pages_matched(aggregating, token_header,
                                                                     route):
    """§7.2.1 rule 4's ordering, as a sort key over what came back."""
    body = call(aggregating, token_header, route, query=AGGREGATE_QUERY, scope=MANUALS)
    rows = body["hits"]

    assert 0 < len(rows) <= SKIM_LIMIT
    keys = [(row["best_rank"] or 10**6, -row["pages_matched"]) for row in rows]
    assert keys == sorted(keys)


def test_more_than_ten_groups_is_a_cut_and_weak_still_comes_from_total(aggregating, token_header):
    """The plan's edge case: twelve one-page documents, ten rows.

    And the second half of it, which is the one that matters: `weak` is §7.1's formula over
    `total` — the **pages** the branches were allowed to rank — so it does not move when the row
    list is cut. Twelve pages is under `WEAK_ABS`, and it stays under it whether ten rows come
    back or twelve.
    """
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=LEAFLETS)

    assert len(body["hits"]) == SKIM_LIMIT
    assert body["capped"] is True
    assert body["total"] == AGGREGATE_LEAFLETS       # pages, not groups and not rows
    assert body["weak"] is False and body["needs_scope"] is False


@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_no_aggregate_row_carries_a_page_id_page_text_or_image_bytes(aggregating, token_header,
                                                                     route):
    """§7.1, asserted over the serialised response — one field further out than `PageHit`.

    A `DocHit` has no `page_id` because it answers *"which binder?"*: naming a page in the row
    would be the routing §7.6 refuses, made to look like data. The `preview` carries one, and
    that is the exception §7.1 draws deliberately — a thumbnail is how a person eyeballs a
    binder — so the check is that the **row** does not, not that the string never appears.
    """
    response = aggregating.post(route, json={"query": AGGREGATE_QUERY, "scope": MANUALS},
                                headers=token_header)
    body = response.json()

    assert "bytes_b64" not in response.text
    for row in body["hits"]:
        assert "page_id" not in row and "text" not in row
        assert set(row) == ({"doc_id", "title", "doc_type", "pages_matched", "best_rank",
                             "searchable_ratio", "summary", "preview", "next"}
                            if route == DOCUMENTS else
                            {"section_id", "title", "page_range", "pages_matched", "best_rank",
                             "preview", "next"})


@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_every_row_carries_a_preview_thumbnail_of_its_best_ranked_page(aggregating, token_header,
                                                                       route):
    """§13 M5's acceptance clause (C13): a reference at the thumbnail tier, never bytes."""
    body = call(aggregating, token_header, route, query=AGGREGATE_QUERY, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY, scope=MANUALS, limit=25)
    by_rank = {hit["rank"]: hit["page_id"] for hit in pages["hits"]}

    for row in body["hits"]:
        preview = row["preview"]
        assert preview is not None and set(preview) == {"page_id", "thumb_url"}
        assert "bytes_b64" not in preview
        assert preview["thumb_url"].startswith("/pages/") and "dpi=72" in preview["thumb_url"]
        assert preview["page_id"] == by_rank[row["best_rank"]]


def test_a_section_row_carries_the_stitched_page_range_not_the_matched_one(aggregating,
                                                                           token_header):
    """`page_range` is the section's extent after stitching (§6.1 step 07), not the group's.

    A range that shrank as the query narrowed would read as though the chapter itself were
    smaller — so the two sections of `AGG-TEXT` report 1–3 and 4–6 however few of their pages the
    query happened to reach.
    """
    body = call(aggregating, token_header, SECTIONS, query=AGGREGATE_CODE, scope=MANUALS)
    rows = {row["section_id"]: row for row in body["hits"]}

    only = rows["AGG-TEXT@1.0#s001"]
    assert only["pages_matched"] == 1          # the code is printed on one page of the three
    assert only["page_range"] == [1, 3]        # …and the section is still three pages long
    assert only["title"] == "Carton discharge"


# ── the affordance: a scope, not a citation (P4, §7.6) ───────────────────────────────────────────

def test_a_document_rows_expand_reproduces_exactly_that_groups_pages(aggregating, token_header):
    """`next.expand` handed straight back as the next rung's `scope` returns the group (P4)."""
    documents = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY, scope=MANUALS, limit=25)

    for row in documents["hits"]:
        descended = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY,
                         scope={**MANUALS, **row["next"]["expand"]}, limit=25)
        assert {hit["page_id"] for hit in descended["hits"]} == {
            hit["page_id"] for hit in pages["hits"]
            if hit["page_id"].startswith(f"{row['doc_id']}@")}


def test_a_section_rows_expand_reproduces_exactly_that_groups_pages(aggregating, token_header):
    """The same, one rung down: `{"section_id": [...]}` is a scope key `INDEXED` knows (§5.4)."""
    sections = call(aggregating, token_header, SECTIONS, query=AGGREGATE_QUERY, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY, scope=MANUALS, limit=25)

    for row in sections["hits"]:
        descended = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY,
                         scope={**MANUALS, **row["next"]["expand"]}, limit=25)
        assert {hit["page_id"] for hit in descended["hits"]} == {
            hit["page_id"] for hit in pages["hits"]
            if row["section_id"] in (hit["next"]["expand"].get("section_id") or ())}


# ── the search underneath is the shared one ──────────────────────────────────────────────────────

@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_an_image_only_query_runs_the_dense_branch_alone(aggregating, token_header, route):
    """D12 rule 2, on the aggregate rungs: every contributing row's `why` is `["dense"]`.

    An aggregate row has no `why` of its own — it is a group, and §7.1 gives it none — so the
    branch is read where it is stated: on the page rows of the very same query. That is also the
    honest form of the criterion, since it is the contributing rows whose evidence is weaker.
    """
    body = call(aggregating, token_header, route, image=PANEL_B64, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, image=PANEL_B64, scope=MANUALS, limit=25)

    assert body["hits"] and pages["hits"]
    assert {tuple(hit["why"]) for hit in pages["hits"]} == {("dense",)}


@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_the_same_call_twice_returns_the_same_rows_in_the_same_order(aggregating, token_header,
                                                                     route):
    """§16 — and on a rung whose ordering has a tie in it, two groups sharing a best page."""
    first = aggregating.post(route, json={"query": AGGREGATE_QUERY, "scope": MANUALS},
                             headers=token_header)
    second = aggregating.post(route, json={"query": AGGREGATE_QUERY, "scope": MANUALS},
                              headers=token_header)

    assert first.content == second.content


@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_exclude_removes_the_page_from_the_group_it_was_counted_in(aggregating, token_header,
                                                                    route):
    """`exclude` is the caller's memory, and it has to reach the counts (C11, §7.2.1)."""
    before = call(aggregating, token_header, route, query=AGGREGATE_QUERY, scope=MANUALS)
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_QUERY, scope=MANUALS, limit=25)
    dropped = pages["hits"][0]["page_id"]

    after = call(aggregating, token_header, route, query=AGGREGATE_QUERY, scope=MANUALS,
                 exclude=[dropped])
    key = "doc_id" if route == DOCUMENTS else "section_id"
    matched = {row[key]: row["pages_matched"] for row in before["hits"]}
    for row in after["hits"]:
        if row["pages_matched"]:
            assert row["pages_matched"] <= matched.get(row[key], 0)
    assert sum(row["pages_matched"] for row in after["hits"]) < \
        sum(row["pages_matched"] for row in before["hits"])


# ── the refusals, on the two new names ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_a_search_with_nothing_to_search_for_is_a_typed_refusal_naming_the_rung(aggregating,
                                                                                token_header,
                                                                                route):
    """`query_required` — and it names the rung the caller actually typed."""
    body = refused(aggregating, token_header, route, scope=MANUALS)

    assert body["error"] == "query_required"
    assert route.rsplit("/", 1)[-1] in body["detail"]


@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_a_scope_key_outside_indexed_is_a_typed_400_and_never_a_scan(aggregating, token_header,
                                                                     route):
    """I6, F10 — the same gate as `skim_pages`, because it is the same `_candidates` call."""
    body = refused(aggregating, token_header, route, query=AGGREGATE_QUERY,
                   scope={"machine": "TC1E"})

    assert body["error"] == "filter_unknown_key"


@pytest.mark.parametrize("route", [DOCUMENTS, SECTIONS])
def test_the_aggregate_rungs_take_no_limit(aggregating, token_header, route):
    """§7.2.1 gives them none, and ``extra="forbid"`` makes asking for one a `400`."""
    response = aggregating.post(route, json={"query": AGGREGATE_QUERY, "limit": 25},
                                headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_a_scope_matching_no_document_is_out_of_scope_not_an_empty_ok(aggregating, token_header):
    """§7.1 — the corpus was never asked, so the status says so and `hits` is empty."""
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY,
                scope={"doc_id": "AGG-NOT-A-DOCUMENT"})

    assert body["status"] == "out_of_scope"
    assert body["hits"] == [] and body["total"] == 0


def test_an_identifier_that_is_printed_nowhere_suggests_lookup(aggregating, token_header):
    """The narrowing emptied it and the caller cannot see that from `effective_scope` (§7.1)."""
    body = call(aggregating, token_header, DOCUMENTS, query="reset K999", scope=LEAFLETS)

    assert body["status"] == "not_found"
    assert body["next"]["suggest"] == ["lookup"]
    assert all(row["best_rank"] == UNRANKED for row in body["hits"])
