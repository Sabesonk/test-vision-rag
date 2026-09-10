"""L2 — `searchable_ratio` on every `skim_documents` row, and the blind spot it discloses (§5.7).

This is the number the document rung exists for, so it gets a suite of its own rather than a line
in the one next door. §5.7 defines it as *pages with `has_text` ÷ pages*, and §7.2.1 puts it **on
every row** for a reason that is easier to see from the failure it prevents than from the field:

    A binder is scanned. Its pages carry a dense vector — D4 fuses the raster — but no text. The
    agent asks for a printed code. `decompose()` splits the code out and it becomes a phrase
    filter over `text`, so every page of that binder falls out of every branch. The binder is not
    ranked low; it is **not there**. The agent reads a confident list of the binders that were
    searched and concludes the part does not exist.

That is F4 at the document level, and the answer is disclosure: the binder comes back anyway, at
`searchable_ratio: 0.00`, with `pages_matched: 0`, a thumbnail of its first page and a
`next.expand` to descend into it with `fetch`. It sorts after every group that did match, so it
can never displace a result — an honest extra row, never a wrong one.

The corpus is built for exactly this (`conftest.AGGREGATE_DOCS`): one binder that is all text, one
half scanned, one entirely scanned. Three documents, three values of one number.
"""
from __future__ import annotations

import pytest

from vsir.core.health import blind_spot, ratio, searchable_ratio
from vsir.serve.envelope import UNRANKED

from conftest import AGGREGATE_CODE, AGGREGATE_QUERY

DOCUMENTS = "/tools/skim_documents"
PAGES = "/tools/skim_pages"
MANUALS = {"doc_type": "manual"}

#: `(doc_id, pages, pages with a text layer)` — the corpus, as §5.7 counts it.
EXPECTED = {"AGG-TEXT": (6, 6), "AGG-MIXED": (4, 2), "AGG-SCAN": (3, 0)}


def call(client, headers, route, **body):
    response = client.post(route, json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ── the number itself (§5.7) ─────────────────────────────────────────────────────────────────────

def test_every_document_row_carries_the_exact_ratio_of_its_pages(aggregating, token_header):
    """*"For a document with N pages of which M have text, `searchable_ratio == M / N` exactly."*

    Exactly, not approximately: the counts behind it are `count(exact=True)` facets, because a
    ratio built on an estimate is a number an agent would act on and a number nobody could
    reproduce.
    """
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=MANUALS)
    rows = {row["doc_id"]: row for row in body["hits"]}

    assert set(rows) == set(EXPECTED)
    for doc_id, (pages, with_text) in EXPECTED.items():
        assert rows[doc_id]["searchable_ratio"] == ratio(pages, with_text)
    assert rows["AGG-TEXT"]["searchable_ratio"] == 1.0
    assert rows["AGG-MIXED"]["searchable_ratio"] == 0.5
    assert rows["AGG-SCAN"]["searchable_ratio"] == 0.0


def test_the_row_and_the_scope_stats_agree_on_the_same_document(aggregating, token_header):
    """Two numbers for one document in one response would be a bug report waiting to happen.

    `scope_stats.docs` is *"what was actually searched"* (§7.1) and the row is *"which binder?"*
    (§7.2.1); they are counted separately, against the same scope filter, and they must land on
    the same value or one of them is wrong.
    """
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=MANUALS)
    per_scope = {stat["doc_id"]: stat["searchable_ratio"] for stat in body["scope_stats"]["docs"]}

    for row in body["hits"]:
        assert row["searchable_ratio"] == per_scope[row["doc_id"]]


def test_pages_no_text_is_the_numerator_the_ratios_are_taken_against(aggregating, token_header):
    """F4's disclosure and §5.7's ratio are the same count, so they cannot disagree."""
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=MANUALS)

    assert body["scope_stats"]["pages"] == sum(pages for pages, _ in EXPECTED.values())
    assert body["scope_stats"]["pages_no_text"] == sum(
        pages - with_text for pages, with_text in EXPECTED.values())


# ── the blind spot: still returned (§7.2.1, F4) ─────────────────────────────────────────────────

def test_a_fully_scanned_binder_is_returned_when_it_matched(aggregating, token_header):
    """A prose query reaches it through the dense branch, and nothing filters it out.

    `branch_filter` carries no trust condition — deliberately, because a skim row is a page worth
    looking at and not a hit on the exact surface — so the scanned binder is a candidate like any
    other and its row states what it is.
    """
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_QUERY, scope=MANUALS)
    scanned = next(row for row in body["hits"] if row["doc_id"] == "AGG-SCAN")

    assert scanned["searchable_ratio"] == 0.0
    assert scanned["pages_matched"] > 0
    assert scanned["best_rank"] > UNRANKED


def test_a_fully_scanned_binder_is_returned_when_it_could_not_match_at_all(aggregating,
                                                                           token_header):
    """The case the disclosure exists for: a printed code, which no scanned page can match.

    `AGG-SCAN` contributes **no** fused candidate here — the phrase filter runs over `text` and
    it has none — so it appears in `skim_pages` nowhere at all. It must still appear here, or the
    agent concludes from a confident-looking list that the code is not in the corpus.
    """
    pages = call(aggregating, token_header, PAGES, query=AGGREGATE_CODE, scope=MANUALS, limit=25)
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_CODE, scope=MANUALS)
    rows = {row["doc_id"]: row for row in body["hits"]}

    assert "AGG-SCAN" not in {hit["page_id"].split("@")[0] for hit in pages["hits"]}
    assert body["status"] == "ok"                       # a text binder did match
    assert rows["AGG-TEXT"]["pages_matched"] == 1
    assert "AGG-SCAN" in rows
    assert rows["AGG-SCAN"]["searchable_ratio"] == 0.0
    assert rows["AGG-SCAN"]["pages_matched"] == 0


def test_a_disclosure_row_previews_page_one_and_sorts_after_every_group_that_matched(
        aggregating, token_header):
    """§7.1's fallback — *"falling back to page 1 when nothing matched"* — and its position.

    Page 1 is the only page of a document that can be offered without a ranking to choose from,
    and a thumbnail is how a person eyeballs an image-only binder without paying for a `read`.
    The row sorts last because `best_rank` is :data:`~vsir.serve.envelope.UNRANKED`: a disclosure
    can never displace a result.
    """
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_CODE, scope=MANUALS)
    rows = body["hits"]
    scanned = next(row for row in rows if row["doc_id"] == "AGG-SCAN")

    assert scanned["best_rank"] == UNRANKED
    assert rows.index(scanned) == len(rows) - 1
    assert [row["best_rank"] for row in rows if row["best_rank"] != UNRANKED] == \
        sorted(row["best_rank"] for row in rows if row["best_rank"] != UNRANKED)
    assert scanned["preview"]["page_id"] == "AGG-SCAN@1.0#p001"
    assert "dpi=72" in scanned["preview"]["thumb_url"]
    assert "bytes_b64" not in scanned["preview"]
    # And it still hands back a scope, so the agent's next move is `fetch`, not a guess.
    assert scanned["next"]["expand"] == {"doc_id": "AGG-SCAN"}


def test_a_half_scanned_binder_is_not_disclosed_it_is_simply_found(aggregating, token_header):
    """Only ratio **zero** earns a disclosure row (:func:`~vsir.core.health.blind_spot`).

    `AGG-MIXED` is half scanned and is found through the pages that do have text, so it is an
    ordinary group with an ordinary rank. Disclosing every document that merely failed to match
    would return the corpus and undo the narrowing the rung exists to do.
    """
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_CODE, scope=MANUALS)
    rows = {row["doc_id"]: row for row in body["hits"]}

    assert blind_spot(0.0) and not blind_spot(0.5)
    assert "AGG-MIXED" not in rows          # it has text, and this code is not printed in it


def test_a_scope_of_nothing_but_a_scanned_binder_is_not_searchable_and_says_which(aggregating,
                                                                                  token_header):
    """§7.1 — the status is decided by the pages, never by whether a disclosure row is present.

    Saying `ok` because the blind spot was disclosed would turn the disclosure into the answer.
    `not_searchable` is *"escalate to vision"*, and the row is what says where to escalate to.
    """
    body = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_CODE,
                scope={"doc_id": "AGG-SCAN"})

    assert body["status"] == "not_searchable"
    assert body["total"] == 0
    assert [row["doc_id"] for row in body["hits"]] == ["AGG-SCAN"]
    assert body["hits"][0]["searchable_ratio"] == 0.0
    assert body["scope_stats"]["pages"] == 3 and body["scope_stats"]["pages_no_text"] == 3


def test_the_ratio_on_a_disclosure_row_is_counted_like_any_other(aggregating, token_header):
    """A disclosed row is not a special case with a hard-coded zero: it is counted.

    The distinction matters because `0.0` is also the default of the field. If the row's number
    came from the default rather than from a count, a change that broke the counting would look
    exactly the same on this row and be invisible until it hit a matched one.
    """
    scanned = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_CODE,
                   scope={"doc_id": "AGG-SCAN"})["hits"][0]
    text = call(aggregating, token_header, DOCUMENTS, query=AGGREGATE_CODE,
                scope={"doc_id": "AGG-TEXT"})["hits"][0]

    assert scanned["searchable_ratio"] == ratio(3, 0) == 0.0
    assert text["searchable_ratio"] == ratio(6, 6) == 1.0


# ── the pure rule, single-sourced (§5.7) ────────────────────────────────────────────────────────

@pytest.mark.parametrize("pages,with_text,expected", [
    (0, 0, 0.0),        # a document with no pages is not searchable, and is not a 500
    (3, 0, 0.0),
    (4, 2, 0.5),
    (6, 6, 1.0),
])
def test_the_ratio_is_one_rule_whichever_form_it_is_given(pages, with_text, expected):
    """:func:`~vsir.core.health.ratio` and :func:`~vsir.core.health.searchable_ratio` agree.

    Two callers hold two shapes of the same fact — derivation holds a page-parallel list, the
    document rung holds two counts — and one of them writing `M / N` again is where a `0/0`
    becomes a `ZeroDivisionError` on a document with no pages.
    """
    assert ratio(pages, with_text) == expected
    assert searchable_ratio([True] * with_text + [False] * (pages - with_text)) == expected
