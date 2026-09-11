"""L2 — `POST /search`, the flat surface: data out, never an answer (Spec §7.6, `serve/retrieval.py`).

Two consumers share this route and the suite is split the same way. One half is the **operator's**
question — the fusion's knobs, and the per-branch positions that make a ranking explicable. The
other is the **search-engine** caller: one request that returns ranked pages *with their content*,
so a consumer doing its own reasoning does not climb the ladder and does not pay an inference turn
per rung.

What both halves assert is the property that makes the content safe to hand over at all: a row
that carries `text` carries `text_trust` beside it, because an empty extraction on a scanned page
is not a blank page (§5.7), and every bound is a **typed refusal** naming what was asked for
rather than a quietly smaller — or, for a negation, quietly *larger* — result set.

And the one thing this surface still refuses: no `score`, anywhere, under any name (§7.6).
"""
from __future__ import annotations

import pytest

from vsir.core.status import Status
from vsir.serve.retrieval import (DEFAULT_TEXT_CHARS, FILTER_KEYS, MAX_OFFSET, MAX_TEXT_CHARS,
                                  PARTS)

SEARCH = "/search"

#: Words printed across several pages of the corpus, so all three branches have something to fuse.
QUERY = "emergency stop reset"


def search(client, headers, **body):
    return client.post(SEARCH, json=body, headers=headers)


def ok(client, headers, **body):
    response = search(client, headers, **body)
    assert response.status_code == 200, response.text
    return response.json()


def refused(client, headers, **body):
    response = search(client, headers, **body)
    assert response.status_code == 400, response.text
    return response.json()


# ── the ranking, unchanged by anything this unit added ──────────────────────────────────────────

def test_rank_is_a_one_based_ordinal_and_no_row_carries_a_score(skimming, token_header):
    """§7.6 — ordinals are published, the magnitude that ordered them is not."""
    body = ok(skimming, token_header, query=QUERY)

    assert body["rows"], "the corpus prints these words — an empty ranking is a seeding failure"
    assert [row["rank"] for row in body["rows"]] == list(range(1, len(body["rows"]) + 1))
    assert "score" not in repr(body)


def test_asking_for_content_does_not_change_the_ranking(skimming, token_header):
    """`include` is a projection, not a retrieval parameter — the rows must be the same rows.

    The failure this guards is the one `_candidates`'s own docstring guards for `limit`: if asking
    for content read a different candidate pool, a consumer would see the ranking move under it
    for a reason it could not observe.
    """
    bare = ok(skimming, token_header, query=QUERY)
    rich = ok(skimming, token_header, query=QUERY, include=["summary", "text", "codes"])

    assert [row["page_id"] for row in bare["rows"]] == [row["page_id"] for row in rich["rows"]]
    assert [row["surface_ranks"] for row in bare["rows"]] \
        == [row["surface_ranks"] for row in rich["rows"]]


# ── the search-engine half: content in the row ──────────────────────────────────────────────────

def test_omitting_include_returns_every_part_and_an_empty_list_returns_none(skimming, token_header):
    """`None` is *"you did not say"*; `[]` is an explicit *"no content"*. They differ.

    Defaulting an omitted `include` to nothing was the wrong choice: a consuming system that did
    not know the parameter existed got rows with `content: null` and no way to guess why. This
    surface exists to hand over the data, so silence means all of it — and an operator tuning the
    fusion still has `[]` to get metadata only.
    """
    from vsir.serve.retrieval import PARTS

    default = ok(skimming, token_header, query=QUERY)
    assert default["include"] == list(PARTS)
    assert all(row["content"] is not None for row in default["rows"])

    explicit_none = ok(skimming, token_header, query=QUERY, include=[])
    assert explicit_none["include"] == []
    assert all(row["content"] is None for row in explicit_none["rows"])


@pytest.mark.parametrize("part", PARTS)
def test_every_declared_part_is_served(skimming, token_header, part):
    """`PARTS` is the contract — a part this surface advertises must come back as a field."""
    body = ok(skimming, token_header, query=QUERY, include=[part])

    assert body["include"] == [part]
    for row in body["rows"]:
        assert row["content"] is not None


def test_a_row_carrying_text_states_the_trust_that_qualifies_it(skimming, token_header):
    """The load-bearing assertion of this surface (§5.7, F4, R2).

    An empty `text` is either a page with nothing printed on it or a page **nobody could read**,
    and those are the two facts a consumer composing from snippets must not confuse. So the trust
    travels with the content, on every row, always.
    """
    body = ok(skimming, token_header, query=QUERY, include=["text"])

    for row in body["rows"]:
        assert row["text_trust"] in ("ok", "degraded", "untrusted", "no_text")
        assert row["has_text"] == (row["text_trust"] not in ("", "no_text"))
        if row["text_trust"] == "no_text":
            assert row["content"]["text"] == "", "a page with no text layer cannot have text"


def test_text_is_capped_and_says_when_it_truncated(skimming, token_header):
    """Truncation is stated per row, never silent — a clipped page is not a whole one."""
    body = ok(skimming, token_header, query=QUERY, include=["text"], text_chars=40)

    for row in body["rows"]:
        content = row["content"]
        assert len(content["text"]) <= 40
        assert content["text_truncated"] == (content["text_chars_total"] > 40)
        if content["text_truncated"]:
            assert content["text_chars_total"] > len(content["text"])


def test_the_default_text_cap_is_the_documented_one(skimming, token_header):
    body = ok(skimming, token_header, query=QUERY, include=["text"])

    assert all(len(row["content"]["text"]) <= DEFAULT_TEXT_CHARS for row in body["rows"])


def test_codes_are_claims_and_codes_in_text_is_the_backed_subset_of_them(skimming, token_header):
    """D3 — `codes` is what the model reported; `codes_in_text` is what the page's own text backs.

    **The two are in different forms, and that is the contract.** `codes` is verbatim because
    §5.2 forbids normalising what the model emitted; `codes_in_text` is lowercased and
    whitespace-collapsed because that is the form `core/health.py` decided membership in. So the
    subset relation holds *case-insensitively*, and a consumer comparing them exactly would find
    nothing and read it as "the text backs none of these codes" — the opposite of the truth. This
    suite asserts the real relation so the field descriptions cannot drift from it.
    """
    body = ok(skimming, token_header, query=QUERY, include=["codes"])

    seen = 0
    for row in body["rows"]:
        content = row["content"]
        claimed = {" ".join(code.split()).lower() for code in content["codes"]}
        assert set(content["codes_in_text"]) <= claimed, \
            "a backed code that was never claimed means the two lists came from different places"
        assert content["codes_in_text"] == sorted(content["codes_in_text"])
        seen += len(content["codes"])
    assert seen, "the corpus pages carry model-reported codes"


# ── paging ──────────────────────────────────────────────────────────────────────────────────────

def test_offset_pages_the_same_deterministic_ranking(skimming, token_header):
    """§16 — the ordering is deterministic, so a page of it is stable rather than a re-run."""
    whole = ok(skimming, token_header, query=QUERY, limit=6)
    second = ok(skimming, token_header, query=QUERY, limit=3, offset=3)

    assert second["offset"] == 3
    assert [row["page_id"] for row in second["rows"]] \
        == [row["page_id"] for row in whole["rows"][3:6]]
    assert [row["rank"] for row in second["rows"]] == [4, 5, 6], \
        "rank is the position in the ranking, not the position in the page"


def test_available_reports_the_end_of_the_pageable_list(skimming, token_header):
    """`available` is the candidate pool's edge — the fact that makes an empty page readable.

    Without it, a caller that paged past the pool would be handed an empty `rows` and could only
    read it as *"the corpus has no more"*, which is the fabricated absence §7.1 exists to prevent.
    """
    body = ok(skimming, token_header, query=QUERY, limit=5)

    assert body["available"] >= len(body["rows"])
    assert body["returned"] == len(body["rows"])
    beyond = ok(skimming, token_header, query=QUERY, offset=body["available"])
    assert beyond["rows"] == []
    assert beyond["available"] == body["available"], "the pool did not change, only the window"


# ── the two filter shapes `scope` cannot spell ──────────────────────────────────────────────────

def test_a_page_range_narrows_to_the_interval(skimming, token_header):
    """`page_no` as an interval — `scope` matches a value or any-of a list, never a range."""
    whole = ok(skimming, token_header, query=QUERY, include=["labels"], limit=25)
    pages = sorted({row["content"]["printed_page_no"] for row in whole["rows"]})
    assert pages, "the corpus rows must carry labels for this assertion to mean anything"

    ranged = ok(skimming, token_header, query=QUERY, page_from=1, page_to=3, limit=25)

    assert ranged["rows"], "pages 1-3 of the corpus are searchable"
    assert ranged["pages_searched"] <= whole["pages_searched"]
    assert ranged["total"] <= whole["total"]


def test_exclude_scope_negates_over_the_same_indexed_keys(skimming, token_header):
    """The negation of `scope`, and it must actually apply — see the refusal test below for why."""
    whole = ok(skimming, token_header, query=QUERY, limit=25)
    kinds = {row["page_kind"] for row in whole["rows"] if row["page_kind"]}
    assert kinds, "the corpus rows carry a page_kind"

    dropped = sorted(kinds)[0]
    narrowed = ok(skimming, token_header, query=QUERY, limit=25,
                  exclude_scope={"page_kind": [dropped]})

    assert all(row["page_kind"] != dropped for row in narrowed["rows"])
    assert narrowed["total"] <= whole["total"]


# ── the refusals ────────────────────────────────────────────────────────────────────────────────

def test_an_unknown_content_part_is_refused_and_not_ignored(skimming, token_header):
    """A caller who typed `summaries` and got no summary would blame the page."""
    body = refused(skimming, token_header, query=QUERY, include=["summaries"])

    assert body["error"] == "unknown_content_part"
    assert body["requested"] == ["summaries"]
    assert set(body["parts"]) == set(PARTS)


def test_an_offset_past_the_pageable_depth_is_refused(skimming, token_header):
    body = refused(skimming, token_header, query=QUERY, offset=MAX_OFFSET + 1)

    assert body["error"] == "offset_out_of_range"
    assert body["limit"] == MAX_OFFSET


@pytest.mark.parametrize("text_chars", [0, MAX_TEXT_CHARS + 1])
def test_text_chars_outside_its_bound_is_refused(skimming, token_header, text_chars):
    body = refused(skimming, token_header, query=QUERY, include=["text"], text_chars=text_chars)

    assert body["error"] == "text_chars_out_of_range"


def test_an_inverted_page_range_is_refused_rather_than_returning_nothing(skimming, token_header):
    """An empty answer here would report the caller's typo as a fact about the corpus (§7.1)."""
    body = refused(skimming, token_header, query=QUERY, page_from=40, page_to=10)

    assert body["error"] == "page_range_inverted"
    assert body["page_from"] == 40 and body["page_to"] == 10


def test_an_unknown_key_in_the_negation_is_refused(skimming, token_header):
    """I6, F10 — and the failure is inverted here, which is why the gate matters more.

    An unknown key quietly dropped from a `must_not` returns a **larger** result set that looks
    like a filtered one, and nothing in the response would show it.
    """
    body = refused(skimming, token_header, query=QUERY, exclude_scope={"printed_page_no": "8"})

    assert body["error"] == "filter_unknown_key"
    assert body["keys"] == ["printed_page_no"]


def test_the_surface_needs_a_credential_like_every_non_probe_path(skimming):
    """§7.4 — refused in middleware, before the body is looked at."""
    assert search(skimming, {}, query=QUERY).status_code == 401


# ── the contract a consuming system reads ───────────────────────────────────────────────────────

def test_status_is_the_field_to_branch_on_and_never_error(skimming, token_header):
    """§7.1 — an empty `rows` is one of four different facts, not one.

    `error` must never appear in a 200 body: a failure is a typed HTTP refusal, because an outage
    rendered as an absence becomes the caller's fabricated confidence.
    """
    body = ok(skimming, token_header, query=QUERY)

    assert body["status"] in {s.value for s in Status}
    assert body["status"] != Status.ERROR.value
    assert body["status"] == Status.OK.value, "the corpus prints these words"


def test_a_scope_matching_nothing_is_out_of_scope_and_not_an_empty_ok(skimming, token_header):
    """The distinction that stops a consuming system reporting 'not in the documents' about a
    corpus it never actually asked (§7.1)."""
    body = ok(skimming, token_header, query=QUERY, scope={"doc_id": "NO-SUCH-DOCUMENT"})

    assert body["status"] == Status.OUT_OF_SCOPE.value
    assert body["rows"] == []
    assert body["pages_searched"] == 0, "nothing was in scope, so nothing was searched"


def test_the_absence_rule_is_the_one_the_rungs_use(skimming, token_header):
    """Not a second opinion about what an empty result means.

    `/search` and `skim_pages` must agree, because a consuming system comparing them would
    otherwise be told a scope was unsearchable by one surface and merely empty by the other.
    """
    scope = {"doc_id": "NO-SUCH-DOCUMENT"}
    flat = ok(skimming, token_header, query=QUERY, scope=scope)
    rung = skimming.post("/tools/skim_pages", json={"query": QUERY, "scope": scope},
                         headers=token_header).json()

    assert flat["status"] == rung["status"]


def test_the_query_interpretation_explains_the_row_set(skimming, token_header):
    """The split happens before anything is retrieved and it changes the answer completely.

    A consuming system that cannot see that `K158` became a hard phrase filter cannot tell a
    scoping result from a semantic one, and will misreport both.
    """
    plain = ok(skimming, token_header, query="reset procedure")
    coded = ok(skimming, token_header, query="reset procedure K158")

    assert plain["query_interpretation"]["identifiers"] == []
    assert coded["query_interpretation"]["identifiers"] == ["K158"]
    assert coded["query_interpretation"]["embedded_text"] == "reset procedure", \
        "only the prose reaches the embedding — the code goes to the phrase filter"
    assert coded["query_interpretation"]["identifier_matching"] == "phrase"


def test_a_switched_off_branch_says_why_it_did_not_run(skimming, token_header):
    """`branches_skipped` removes the commonest guesswork about a thin result."""
    body = ok(skimming, token_header, query=QUERY,
              weights={"dense": 1, "lexical": 0, "captions": 0})

    skipped = {one["branch"]: one for one in body["query_interpretation"]["branches_skipped"]}
    assert set(skipped) == {"lexical", "captions"}
    assert all(one["reason"] == "weighted_zero" for one in skipped.values())
    assert body["query_interpretation"]["branches_run"] == ["dense"]
    assert body["branches_run"] == body["query_interpretation"]["branches_run"], \
        "the mirrored field and the explanation cannot disagree"


def test_an_identifier_only_query_skips_the_dense_branch_and_says_so(skimming, token_header):
    """Embedding a bare code would blur an exact match into a similarity — so it is not embedded,
    and the response states that rather than leaving `branches_run` to be puzzled over."""
    body = ok(skimming, token_header, query="K158")

    interp = body["query_interpretation"]
    assert interp["identifiers"] == ["K158"] and interp["embedded_text"] == ""
    reasons = {one["branch"]: one["reason"] for one in interp["branches_skipped"]}
    assert reasons.get("dense") == "nothing_left_to_embed"


# ── null means "not requested", never "the page has none" ───────────────────────────────────────

def test_an_unrequested_part_is_null_and_a_requested_empty_one_is_not(skimming, token_header):
    """The discipline of `RowContent`, and the reason every field is optional.

    `text: null` = you did not ask. `text: ""` = the page's extraction is empty, which on a page
    with no text layer means nobody could read it. A falsy default for both is how a consumer
    concludes a page is blank when it simply never asked.
    """
    without = ok(skimming, token_header, query=QUERY, include=["summary"])
    with_text = ok(skimming, token_header, query=QUERY, include=["summary", "text"])

    for row in without["rows"]:
        assert row["content"]["text"] is None
        assert row["content"]["text_chars_total"] is None
        assert row["content"]["text_truncated"] is None
        assert row["content"]["summary"] is not None, "summary WAS requested"
    for row in with_text["rows"]:
        assert row["content"]["text"] is not None, "requested — even when the page has none"
        assert isinstance(row["content"]["text_chars_total"], int)


def test_text_usable_is_the_gate_and_is_not_has_text(skimming, token_header):
    """§5.7 — an `untrusted` page *has* text and its text may not be believed.

    `text_usable` is the single field a consumer gates on; conflating it with `has_text` is how a
    garbled extraction gets treated as evidence.
    """
    body = ok(skimming, token_header, query=QUERY, include=["text"], limit=25)

    for row in body["rows"]:
        assert row["text_usable"] == (row["text_trust"] in ("ok", "degraded"))
        assert row["has_text"] == (row["text_trust"] != "no_text")
        if row["text_trust"] == "untrusted":
            assert row["has_text"] and not row["text_usable"], \
                "the case the two flags exist to keep apart"


def test_sections_are_typed_rows_not_loose_objects(skimming, token_header):
    """A consuming system reads `page_range` as two integers and `section_id` as a scope value."""
    body = ok(skimming, token_header, query=QUERY, include=["sections"], limit=25)

    seen = 0
    for row in body["rows"]:
        for section in row["content"]["sections"]:
            assert set(section) == {"section_id", "title", "series_id", "page_range"}
            assert section["page_range"] is None or len(section["page_range"]) == 2
            seen += 1
    assert seen, "the corpus pages belong to sections"


# ── the published schema is the contract ────────────────────────────────────────────────────────

def test_every_bound_and_vocabulary_is_in_the_published_schema(served):
    """A consuming system generates its client from `/openapi.json`, so the bounds have to be
    *in* it — discovering `offset_out_of_range` at run time is not a contract."""
    schema = served.get("/openapi.json").json()
    props = schema["components"]["schemas"]["SearchRequest"]["properties"]

    assert props["limit"]["maximum"] == 25 and props["limit"]["minimum"] == 1
    assert props["offset"]["maximum"] == MAX_OFFSET
    assert props["text_chars"]["maximum"] == MAX_TEXT_CHARS
    assert props["include"]["items"]["enum"] == list(PARTS)
    assert props["images"]["maxItems"] == 4
    assert props["scope"]["propertyNames"]["enum"] == list(FILTER_KEYS)


def test_the_filter_vocabulary_excludes_the_two_text_surfaces(skimming, token_header):
    """`text` and `vlm_codes` are reachable only through `lookup` and `verify` — never as a
    caller filter, in `scope` or in its negation."""
    assert "text" not in FILTER_KEYS and "vlm_codes" not in FILTER_KEYS
    for field in ("scope", "exclude_scope"):
        body = refused(skimming, token_header, query=QUERY, **{field: {"text": "K158"}})
        assert body["error"] == "filter_unknown_key"


# ── the row is addressable, viewable and actionable ─────────────────────────────────────────────

def test_a_row_carries_its_own_identity_split_out(skimming, token_header):
    """`doc_id`, `revision` and `page_no` parsed from the id, so a consumer never splits it.

    And `page_no` is **not** `printed_page_no`: no fixed offset exists in this corpus because
    numbering restarts at chapters, which is exactly why both are on the row.
    """
    body = ok(skimming, token_header, query=QUERY)

    for row in body["rows"]:
        assert row["doc_id"] and row["revision"] and row["page_no"] > 0
        assert row["page_id"].startswith(f"{row['doc_id']}@{row['revision']}#p")


def test_a_row_carries_a_thumbnail_and_a_full_raster_reference(skimming, token_header):
    """A UI renders a list of pages straight out of a search — and the `#` in a page id is
    percent-encoded, so neither url can be assembled by the reader."""
    body = ok(skimming, token_header, query=QUERY)

    for row in body["rows"]:
        assert row["image"]["url"] and row["image"]["thumb_url"]
        assert "%23" in row["image"]["url"], "an unencoded # makes the reference undereferenceable"
        assert row["image"]["dpi"] > 0
        assert row["image"]["width"] == 0 and row["image"]["height"] == 0, \
            "a size here would mean rendering the page to answer a search"
        assert row["image_url"] == row["image"]["url"], "the shorthand cannot disagree"


def test_next_is_a_scope_to_hand_back_and_the_pages_either_side(skimming, token_header):
    """`expand` is a scope, not an id — the same affordance a `skim_pages` row carries, from the
    same function, so the two surfaces cannot disagree about what a page's section is (F8)."""
    body = ok(skimming, token_header, query=QUERY)

    for row in body["rows"]:
        moves = row["next"]
        assert set(moves) == {"expand", "neighbours", "references", "suggest", "tokens_observed"}
        if row["section_id"]:
            assert moves["expand"] == {"section_id": row["section_id"]}
        for neighbour in moves["neighbours"]:
            assert neighbour.startswith(f"{row['doc_id']}@{row['revision']}#p")
        assert moves["references"] == [], \
            "declared and empty — scraping cross-references out of page text is what F5 forbids"


def test_every_row_carries_assembled_operations_with_exactly_one_that_bills(skimming, token_header):
    """The 'next operation' signal: arguments already built, and `spends` on the one that costs.

    A consuming system posts `arguments` verbatim rather than composing a body around a page id
    that contains an `@` and a `#` — a request that addresses nothing comes back looking like an
    empty result rather than a client bug.
    """
    body = ok(skimming, token_header, query=QUERY)

    for row in body["rows"]:
        actions = {one["action"]: one for one in row["actions"]}
        assert {"open_page_image", "fetch_material", "check_codes", "comprehend"} <= set(actions)
        assert [one["action"] for one in row["actions"]][-1] == "comprehend", \
            "the one that spends is last, so it is never reached by accident"
        spending = [one["action"] for one in row["actions"] if one["spends"]]
        assert spending == ["comprehend"], f"exactly one operation bills, got {spending}"

        # every assembled body addresses this page and nothing else
        for name in ("fetch_material", "check_codes", "comprehend"):
            assert actions[name]["arguments"]["page_ids"] == [row["page_id"]]
            assert actions[name]["target"].startswith("/tools/")
        if row["section_id"]:
            expand = actions["expand_section"]["arguments"]
            assert expand["scope"]["section_id"] == row["section_id"]
            assert expand["query"] == QUERY, \
                "the query travels with the scope, or /search refuses the body it hands back"


def test_the_assembled_fetch_call_actually_works(skimming, token_header):
    """The affordance is only worth having if it can be posted verbatim. So post it verbatim.

    Dropping `image` from the assembled `include` is what makes this assertable on this fixture:
    the corpus is seeded into the index without its source PDFs, and a raster is re-rendered from
    the source on demand — so asking for pixels here is a truthful `document_not_stored` 503 about
    the fixture rather than anything about the arguments. The text-and-summary path needs no
    source, and it proves the part that could actually be wrong: that the page id, the target and
    the body shape are right.
    """
    row = ok(skimming, token_header, query=QUERY)["rows"][0]
    fetch = next(one for one in row["actions"] if one["action"] == "fetch_material")
    arguments = {**fetch["arguments"], "include": ["text", "summary"]}

    response = skimming.post(fetch["target"], json=arguments, headers=token_header)

    assert response.status_code == 200, response.text
    assert response.json()["result"]["pages"][0]["page_id"] == row["page_id"]


def test_the_assembled_arguments_are_never_refused_as_malformed(skimming, token_header):
    """Every assembled body is at least *accepted* — a 400 here would mean this surface hands a
    consuming system a call it cannot make.

    The placeholder-carrying ones (`check_codes`, `comprehend`) are checked for argument shape
    only: `comprehend` bills, so it is never actually called from a test.
    """
    row = ok(skimming, token_header, query=QUERY)["rows"][0]
    for one in row["actions"]:
        if one["action"] in ("open_page_image", "comprehend"):
            continue
        response = skimming.post(one["target"], json=one["arguments"], headers=token_header)
        assert response.status_code != 400, \
            f"{one['action']} hands the caller a malformed body: {response.text}"


def test_the_expand_scope_can_be_posted_straight_back(skimming, token_header):
    """`next.expand` is handed back as a `scope` with no assembly, and it must select something."""
    row = next(one for one in ok(skimming, token_header, query=QUERY)["rows"]
               if one["section_id"])

    narrowed = ok(skimming, token_header, query=QUERY, scope=row["next"]["expand"])

    assert narrowed["status"] == Status.OK.value
    assert narrowed["pages_searched"] > 0, "the section the row came from is not empty"


def test_the_default_request_example_shows_every_control(served):
    """Swagger drops `examples[0]` into its Try-it-out box, so a minimal body in that slot makes a
    fourteen-parameter surface look like it takes one field.

    That is not a cosmetic preference — it is the difference between a reader discovering `scope`,
    `weights` and `include` and concluding they do not exist. The fully-populated body is first,
    and the route also publishes the four as *named* examples so the UI labels them.
    """
    from vsir.serve.retrieval import REQUEST_EXAMPLES, SearchRequest

    first = SearchRequest.model_json_schema()["examples"][0]
    assert len(first) >= 10, f"the default example shows only {sorted(first)}"
    for control in ("scope", "exclude_scope", "include", "weights", "limit", "offset", "k",
                    "page_from", "page_to", "text_chars"):
        assert control in first, f"{control} is invisible in the default example"

    content = served.get("/openapi.json").json()["paths"]["/search"]["post"]["requestBody"][
        "content"]["application/json"]
    assert set(content["examples"]) == set(REQUEST_EXAMPLES)
    assert all(one["summary"] for one in content["examples"].values()), \
        "an unlabelled example is 'Example 2' in the dropdown"


def test_every_request_example_is_actually_accepted(served, skimming, token_header):
    """An example that does not validate teaches a wrong body — worse than no example at all.

    The photograph one carries a placeholder rather than real base64, so it is checked against the
    model instead of being posted; the other three are posted.
    """
    from vsir.serve.retrieval import REQUEST_EXAMPLES, SearchRequest

    for name, example in REQUEST_EXAMPLES.items():
        SearchRequest.model_validate(example["value"])          # every field name is real
        if name == "with_a_photograph":
            continue
        response = skimming.post(SEARCH, json=example["value"], headers=token_header)
        assert response.status_code == 200, f"example {name!r} is refused: {response.text}"


# ── keyword filters: a hard requirement on what the page prints ─────────────────────────────────

def test_require_phrases_narrows_to_pages_that_print_them(skimming, token_header):
    """A filter, not a query term: a page not printing the phrase cannot appear at any rank."""
    base = ok(skimming, token_header, query="stop time", include=[], limit=25)
    filtered = ok(skimming, token_header, query="stop time", include=[], limit=25,
                  require_phrases=["stop time"])

    assert 0 < filtered["total"] < base["total"], "the filter must actually narrow"
    assert filtered["query_interpretation"]["required_phrases"] == ["stop time"]


def test_exclude_phrases_is_the_complement_of_requiring_them(skimming, token_header):
    """The two halves must partition the scope — otherwise one of them is matching differently."""
    base = ok(skimming, token_header, query="stop time", include=[], limit=25)
    required = ok(skimming, token_header, query="stop time", include=[], limit=25,
                  require_phrases=["stop time"])
    excluded = ok(skimming, token_header, query="stop time", include=[], limit=25,
                  exclude_phrases=["stop time"])

    assert required["total"] + excluded["total"] == base["total"]


def test_requiring_and_excluding_the_same_phrase_matches_nothing(skimming, token_header):
    """Contradictory filters are honoured rather than reconciled — the caller's arithmetic."""
    body = ok(skimming, token_header, query="stop time", include=[],
              require_phrases=["stop time"], exclude_phrases=["stop time"])

    assert body["total"] == 0 and body["rows"] == []


def test_an_unmatched_keyword_filter_is_not_found_and_not_out_of_scope(skimming, token_header):
    """**The distinction this filter's plumbing exists for.**

    `out_of_scope` means *"no page matched your filters, so the corpus was never really asked —
    widen"*. A keyword filter that matched nothing has *searched* the scope. Reporting it as
    `out_of_scope` would send a consuming system off to widen a scope that was never the problem,
    and would claim the corpus was unasked when thirty readable pages were searched. So content
    conditions reach the branch filter only, never the scope denominator.
    """
    content = ok(skimming, token_header, query="stop time", include=[],
                 require_phrases=["zzq definitely not printed anywhere"])
    scoped = ok(skimming, token_header, query="stop time", include=[],
                scope={"doc_id": "NO-SUCH-DOCUMENT"})

    assert content["status"] == Status.NOT_FOUND.value
    assert content["pages_searched"] > 0, "the scope was searched, and must say so"
    assert scoped["status"] == Status.OUT_OF_SCOPE.value
    assert scoped["pages_searched"] == 0


def test_a_keyword_filter_asks_the_index_for_every_spelling_of_the_term(skimming, token_header):
    """It goes through the same exact-match path as `lookup`, so `variants()` applies.

    Asserted on what is actually asked of the index rather than on a corpus count, because
    `variants()` is deliberately **not symmetric**: `"SF 1.1A"` expands to include the bare
    `"SF1.1A"`, while `"SF1.1A"` does not regenerate the spaced form. That is `lookup`'s existing
    behaviour — three spellings, as-given, whitespace-removed and boundary-spaced, and no attempt
    to reconstruct arbitrary intermediate spacings — and a keyword filter inherits it precisely
    because it does not have a matcher of its own.
    """
    from vsir.core.exact import phrases_of
    from vsir.core.variants import variants
    from vsir.serve.retrieval import phrase_conditions

    for term in ("SF 1.1A", "safety output"):
        condition, = phrase_conditions([term], field="require_phrases")
        assert phrases_of(condition) == variants(term), \
            f"the filter for {term!r} does not ask for the spellings `variants` defines"


def test_a_keyword_filter_is_phrase_matching_and_not_loose_tokens(skimming, token_header):
    """Adjacency and order matter: two words that appear far apart on a page are not a match.

    So requiring a real phrase from the corpus finds pages, and requiring the same words reversed
    finds none — which is the property that makes this a filter worth having rather than a second,
    blunter query.
    """
    forward = ok(skimming, token_header, query="stop", include=[], limit=25,
                 require_phrases=["stop time"])
    reversed_words = ok(skimming, token_header, query="stop", include=[], limit=25,
                        require_phrases=["time stop"])

    assert forward["total"] > 0
    assert reversed_words["total"] == 0, "word order is part of a phrase"


def test_a_required_phrase_can_never_reach_a_page_with_no_readable_text(skimming, token_header):
    """§5.7, F4 — and the asymmetry that makes both directions the safe one.

    A phrase filter matches the page's extracted text, so a page nobody could read carries nothing
    to match: requiring drops it, excluding keeps it. The response has to make the size of that
    blind spot visible, or an empty result reads as "the corpus does not contain this".
    """
    body = ok(skimming, token_header, query="stop time", include=[], limit=25,
              require_phrases=["stop time"])

    assert body["pages_searched"] > body["searchable_pages"], \
        "this corpus has pages with no usable text — that is the point of the fixture"
    assert body["pages_without_text"] > 0
    for row in body["rows"]:
        assert row["text_usable"], "a required phrase cannot have matched an unreadable page"


@pytest.mark.parametrize("field", ["require_phrases", "exclude_phrases"])
def test_an_empty_phrase_is_refused_rather_than_dropped(skimming, token_header, field):
    """A caller that sent `["", "safety"]` and got the results of `["safety"]` was filtered on
    something it did not ask for."""
    body = refused(skimming, token_header, query=QUERY, **{field: ["  "]})

    assert body["error"] == "phrase_empty"
    assert body["field"] == field and body["position"] == 0


@pytest.mark.parametrize("field", ["require_phrases", "exclude_phrases"])
def test_too_many_phrases_is_refused_naming_the_bound(skimming, token_header, field):
    from vsir.serve.retrieval import MAX_PHRASE_TERMS

    body = refused(skimming, token_header, query=QUERY,
                   **{field: [f"term {n}" for n in range(MAX_PHRASE_TERMS + 1)]})

    assert body["error"] == "too_many_phrase_terms"
    assert body["limit"] == MAX_PHRASE_TERMS


def test_the_keyword_filters_use_the_one_exact_match_code_path(skimming, token_header):
    """I3, F1 — no second matcher. A `MatchPhrase` assembled in `serve/` would be a place where a
    spelling could be forgotten, and a forgotten spelling is a page that silently stops being
    findable by a filter that looks like it worked."""
    import inspect

    from vsir.serve import retrieval

    assert "exact_filter" in inspect.getsource(retrieval.phrase_conditions)
    # Call-shaped rather than the bare word, for the reason `test_conformance.py` gives about
    # `score`: this module's comments explain *why* it does not assemble one, and a scan that
    # banned the explanation would ban explaining.
    assert "qm.MatchPhrase(" not in inspect.getsource(retrieval), \
        "this module must not build a phrase condition of its own"
