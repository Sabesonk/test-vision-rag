"""L2 — `skim_pages`, the page rung of the narrowing ladder (Spec §7.2.1, U017).

Against a real Qdrant holding the §13 M1 corpus **with all three surfaces written**: the dense
vector, the `lexical` sparse vector over the extracted text and the `captions` sparse vector over
the generated summaries. That is the point of this suite — until now those vectors were written by
U010 and queried by nothing, so this is the first evidence that what ingestion stores is what
retrieval reads.

The assertions divide in two. One half is about the **contract**: a bounded number of rows, a rank
that is an ordinal and not a confidence, `why` naming the branches, `next` carrying the moves, and
— the one P2 exists for — **no page text and no image bytes in a triage row**. The other half is
about the **refusals**: a limit outside its bound, a scope key outside `INDEXED`, a search with
nothing to search for. Each is a typed 400 naming what was asked for, because the alternative to a
refusal here is an answer that looks complete and is not.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from vsir.serve.caps import MAX_SKIM_LIMIT
from vsir.serve.tools.skim import SKIM_LIMIT, decompose

SKIM = "/tools/skim_pages"

#: Words that appear across several pages of the corpus, so the branches have something to fuse.
QUERY = "emergency stop reset"


def skim(client, headers, **body):
    return client.post(SKIM, json=body, headers=headers)


def ok(client, headers, **body):
    response = skim(client, headers, **body)
    assert response.status_code == 200, response.text
    return response.json()


# ── the rows ────────────────────────────────────────────────────────────────────────────────────

def test_the_rung_returns_at_most_limit_rows_and_ten_by_default(skimming, token_header):
    """§7.2.1: ≤ 10 rows by default, and `limit` is the only thing that changes it."""
    default = ok(skimming, token_header, query=QUERY)
    three = ok(skimming, token_header, query=QUERY, limit=3)

    assert SKIM_LIMIT == 10
    assert 0 < len(default["hits"]) <= SKIM_LIMIT
    assert len(three["hits"]) == 3


def test_rank_is_a_one_based_ordinal_with_no_gaps(skimming, token_header):
    """A position is not a confidence — and a position with a gap in it is not a position."""
    body = ok(skimming, token_header, query=QUERY)

    assert [hit["rank"] for hit in body["hits"]] == list(range(1, len(body["hits"]) + 1))


def test_why_names_every_branch_that_found_the_row(skimming, token_header):
    """§7.2.1 rule 3. `why` is what §8.2's *use `why` as a signal* is implementable on.

    The corpus is text, so the lexical branch is the one that can be reasoned about: a row the
    words of the query are printed on must say `lexical`, and every row must say `dense`, because
    the dense branch runs on every query and ranks every page in scope.
    """
    body = ok(skimming, token_header, query=QUERY)
    surfaces = {name for hit in body["hits"] for name in hit["why"]}

    assert surfaces <= {"dense", "lexical", "captions"}
    assert "dense" in surfaces and "lexical" in surfaces
    for hit in body["hits"]:
        assert hit["why"], f"{hit['page_id']} was ranked by no branch at all"
        # One order, always: a row a caller diffs between two calls must not reorder its own why.
        assert hit["why"] == [name for name in ("dense", "lexical", "captions")
                              if name in hit["why"]]


def test_a_lexical_only_row_says_so(skimming, token_header, stub_embedder):
    """The pair §7.2.1 spells out: `["dense", "lexical"]` where both hit, `["lexical"]` where one did.

    Constructed rather than hoped for: a one-row `limit` on a query whose words are printed on one
    page cannot show both cases, so the two are read off a deeper skim of the whole corpus.
    """
    body = ok(skimming, token_header, query="contactor K158", limit=MAX_SKIM_LIMIT)
    combinations = {tuple(hit["why"]) for hit in body["hits"]}

    assert ("dense",) in combinations or ("dense", "lexical") in combinations
    assert any("lexical" in why for why in combinations)


def test_no_triage_row_carries_page_text_or_image_bytes(skimming, token_header):
    """**P2, asserted over the serialised response** rather than left to convention.

    An agent that could answer from the search result would stop reasoning and start
    pattern-matching, and it would do it at 1–2k tokens a row. The check is on the raw bytes,
    because a field nested three levels down is still in the caller's context window.
    """
    response = skim(skimming, token_header, query=QUERY)
    raw = response.text
    body = response.json()

    assert "bytes_b64" not in raw
    for hit in body["hits"]:
        assert "text" not in hit
        assert set(hit) == {"page_id", "printed_page_no", "summary", "summary_lang", "page_kind",
                            "why", "rank", "flags", "grounded_rate", "text_trust", "image", "next"}
        assert hit["image"] is not None and "bytes_b64" not in hit["image"]


def test_every_hit_carries_an_image_reference_naming_its_page_and_an_allowed_dpi(
        skimming, token_header):
    """§7.1 — a reference, ~60 bytes, and nothing is rendered to produce it.

    The route arrives at U018, so what is asserted here is the shape of the URL and that it names
    this page and a dpi from §7.3's list. U018 owns the percent-encoding of the `#` and moves this
    assertion with it.
    """
    body = ok(skimming, token_header, query=QUERY)

    for hit in body["hits"]:
        image = hit["image"]
        assert image["url"].startswith("/pages/") and image["url"].endswith("/image?dpi=150")
        assert image["thumb_url"].endswith("/image?dpi=72")
        assert hit["page_id"].split("#")[0] in image["url"]
        assert image["dpi"] == 150
        # Zero until something renders: reporting a size would mean rendering a page to answer a
        # search, which is the cost the indirection exists to avoid.
        assert image["width"] == 0 and image["height"] == 0


def test_every_hit_carries_next_with_expand_neighbours_and_references(skimming, token_header):
    """P4 — retrieval as navigation. `expand` is a **scope**, so it is handed straight back."""
    body = ok(skimming, token_header, query=QUERY)

    for hit in body["hits"]:
        moves = hit["next"]
        assert set(moves) >= {"expand", "neighbours", "references"}
        assert moves["expand"], f"{hit['page_id']} offers no section to expand into"
        assert list(moves["expand"]) == ["section_id"]
        # The affordance must be usable as a scope, not just readable.
        descended = ok(skimming, token_header, query=QUERY, scope=moves["expand"])
        assert descended["effective_scope"]["section_id"] == moves["expand"]["section_id"]
        break


def test_neighbours_never_offer_a_page_the_document_does_not_have(skimming, token_header, corpus):
    """An affordance that 404s reads to an agent as *"that page is not in the corpus"*."""
    body = ok(skimming, token_header, query=QUERY, limit=MAX_SKIM_LIMIT)
    pages = len(corpus.current_records())

    seen_first = seen_last = False
    for hit in body["hits"]:
        page_no = int(hit["page_id"].split("#p")[1])
        expected = [f"{hit['page_id'].split('#')[0]}#p{page_no + offset:03d}"
                    for offset in (-1, 1) if 1 <= page_no + offset <= pages]
        assert hit["next"]["neighbours"] == expected
        seen_first |= page_no == 1
        seen_last |= page_no == pages
    assert len(body["hits"]) == MAX_SKIM_LIMIT  # enough rows for the bound to be exercised


def test_the_summary_states_the_language_it_returned(skimming, token_header):
    """D5 — never a blended multi-language string, and the row says which one it is."""
    body = ok(skimming, token_header, query=QUERY)

    for hit in body["hits"]:
        if hit["summary"]:
            assert hit["summary_lang"]


def test_grounded_rate_is_none_on_a_page_with_no_text_layer(skimming, token_header, corpus):
    """§5.7 — `0.0` there would read as *"extraction is broken"* about a page with no extraction."""
    scanned = [record for record in corpus.current_records() if not record.has_text]
    assert scanned, "the M1 corpus must carry a page with no text layer"
    body = ok(skimming, token_header, query=QUERY, limit=MAX_SKIM_LIMIT,
              scope={"has_text": False})

    assert body["hits"], "a page with no text layer is still rankable — the dense branch sees it"
    for hit in body["hits"]:
        assert hit["grounded_rate"] is None
        assert hit["text_trust"] == "no_text"


# ── the narrowing (§7.2.1 rule 1) ───────────────────────────────────────────────────────────────

def test_decompose_sends_the_code_to_the_phrase_filter_and_only_the_prose_to_the_embedding():
    """The acceptance criterion, on the branch inputs themselves."""
    split = decompose("reset K158")

    assert split.identifiers == ("K158",)
    assert split.embedded == "reset"
    assert split.text == "reset K158"


def test_a_query_that_decomposes_to_identifiers_only_runs_the_sparse_branches_alone(
        skimming, token_header):
    """`skim_pages("K158")` has nothing left to embed, and says so rather than inventing one.

    The mirror of D12's image-only rule: a branch runs when it has an input. Once the code has
    gone to the phrase filter there is no prose, so the dense branch is skipped and every row's
    `why` names the sparse surfaces alone — which is also the honest signal, because the pages
    that came back are pages that **print** the code rather than pages that resemble it.
    """
    body = ok(skimming, token_header, query="K158")

    assert body["status"] == "ok"
    assert body["hits"]
    for hit in body["hits"]:
        assert "dense" not in hit["why"]
        assert "lexical" in hit["why"]


def test_the_identifier_narrows_the_branches_and_an_empty_narrowing_suggests_lookup(
        skimming, token_header):
    """A code nothing prints empties the rung — and says which move could still answer.

    ``K999`` is the corpus's ungrounded code: the model claimed it, no page's text layer carries
    it, and §12.3 requires `lookup` to find nothing for it. The narrowing therefore matches no
    page, which is the case this asserts — a code that *is* printed, even on a page whose text
    layer is `untrusted`, is a candidate and comes back with its trust level on the row.


    `total` is the size of the set the branches were allowed to rank, so it goes to zero when the
    phrase matches nothing. That is the honest shape: the dense branch would happily have ranked
    thirty pages by resemblance, and every one of them would have been a page that does not print
    the code the caller asked about.
    """
    body = ok(skimming, token_header, query="reset K999")

    assert body["status"] == "not_found"
    assert body["total"] == 0
    assert body["hits"] == []
    assert body["next"]["suggest"] == ["lookup"]


def test_exclude_drops_the_page_and_leaves_the_rest_of_the_order_alone(skimming, token_header):
    """C11 — the agent holds the state, and `exclude` is how it stops re-opening a page."""
    before = ok(skimming, token_header, query=QUERY, limit=5)
    dropped = before["hits"][1]["page_id"]
    after = ok(skimming, token_header, query=QUERY, limit=5, exclude=[dropped])

    assert dropped not in [hit["page_id"] for hit in after["hits"]]
    kept = [hit["page_id"] for hit in before["hits"] if hit["page_id"] != dropped]
    assert [hit["page_id"] for hit in after["hits"]][:len(kept)] == kept
    assert [hit["rank"] for hit in after["hits"]] == list(range(1, len(after["hits"]) + 1))


# ── the refusals (§11.3) ────────────────────────────────────────────────────────────────────────

def test_a_limit_above_the_bound_is_a_typed_400_naming_it(skimming, token_header):
    """Never a clamp: twenty-five returned for a hundred asked is a caller believing it saw all."""
    response = skim(skimming, token_header, query=QUERY, limit=MAX_SKIM_LIMIT + 1)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "limit_out_of_range"
    assert body["limit"] == MAX_SKIM_LIMIT == 25 and body["requested"] == 26


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_refused_too(skimming, token_header, limit):
    assert skim(skimming, token_header, query=QUERY, limit=limit).status_code == 400


def test_an_unknown_scope_key_is_filter_unknown_key(skimming, token_header):
    """I6, F10 — a filter that quietly did not apply returns a smaller answer that looks whole."""
    response = skim(skimming, token_header, query=QUERY, scope={"bogus": 1})

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "filter_unknown_key"
    assert body["keys"] == ["bogus"]


def test_neither_a_query_nor_an_image_is_refused(skimming, token_header):
    """An empty query embedded as the empty string still returns ten confident-looking rows."""
    response = skim(skimming, token_header, scope={"doc_id": "SYN-M1"})

    assert response.status_code == 400
    assert response.json()["error"] == "query_required"


def test_a_scope_that_matches_no_document_is_out_of_scope_not_not_found(skimming, token_header):
    """§7.1 — the corpus was never asked, which is a different problem from asking and missing."""
    body = ok(skimming, token_header, query=QUERY, scope={"doc_id": "NO-SUCH-DOC"})

    assert body["status"] == "out_of_scope"
    assert body["hits"] == []
    assert body["scope_stats"]["pages"] == 0


# ── the trust signals ───────────────────────────────────────────────────────────────────────────

def test_weak_is_the_server_constant_and_not_the_callers_limit(skimming, token_header):
    """§7.1 — a trust signal a client could flip with a parameter is worse than no signal."""
    wide = ok(skimming, token_header, query=QUERY, limit=1)
    narrow = ok(skimming, token_header, query=QUERY, limit=1, scope={"page_no": 1})

    assert wide["weak"] is True and wide["needs_scope"] is True
    assert wide["total"] > 20
    assert narrow["weak"] is False and narrow["needs_scope"] is False
    assert narrow["total"] == 1
    # `limit` moved neither: it bounds the rows, and nothing else.
    assert ok(skimming, token_header, query=QUERY, limit=MAX_SKIM_LIMIT)["weak"] is True


def test_a_shorter_limit_is_the_prefix_of_a_longer_one(skimming, token_header):
    """`limit` truncates the fused list — it does not re-rank it.

    The branch depth is a constant for exactly this reason: an agent that narrowed from ten rows
    to three and saw three *different* pages would have no way to tell whether the ranking had
    changed or the corpus had.
    """
    ten = ok(skimming, token_header, query=QUERY, limit=10)
    three = ok(skimming, token_header, query=QUERY, limit=3)

    assert [hit["page_id"] for hit in three["hits"]] == \
        [hit["page_id"] for hit in ten["hits"]][:3]
    assert [hit["why"] for hit in three["hits"]] == [hit["why"] for hit in ten["hits"]][:3]


def test_capped_says_the_rows_are_a_page_of_a_larger_set(skimming, token_header):
    body = ok(skimming, token_header, query=QUERY, limit=2)

    assert body["capped"] is True
    assert body["total"] > len(body["hits"])


# ── §7.6, structurally ──────────────────────────────────────────────────────────────────────────

def test_no_response_model_in_the_fused_path_declares_a_field_named_score():
    """An **AST scan**, not a grep: the acceptance criterion asks for the declaration, not the word.

    A fused float is a similarity score under another name, and `impl` returned one as
    ``Hit.fused``. The scan walks every annotated assignment and every keyword argument of the
    modules the fused path is built from, so a field added as ``score: float`` or as
    ``score = Field(...)`` fails here even where a conformance grep's line pattern would not.
    """
    package = Path(__file__).resolve().parents[2] / "vsir"
    modules = [package / "serve" / "envelope.py",
               package / "serve" / "tools" / "skim.py",
               package / "serve" / "tools" / "resolve.py",
               package / "serve" / "app.py"]

    declared: list[str] = []
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            elif isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            declared += [f"{path.name}:{node.lineno}:{name}"
                         for name in names if name == "score"]

    assert declared == []


def test_the_response_is_the_bytes_a_caller_receives(skimming, token_header):
    """One serialiser for every transport (§7.5) — the envelope is not re-rendered per surface."""
    response = skim(skimming, token_header, query=QUERY, limit=2)

    assert json.loads(response.content) == response.json()
    assert b"  " not in response.content  # compact separators, as `envelope.wire` writes them
