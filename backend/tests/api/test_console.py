"""L2 — the operator console (§7.4, §16).

The console is markup, so these tests cannot click it. What they *can* hold down is everything
that makes it either safe or wrong, and there are four such things:

* it is **one free path** and carries no credential — the security property;
* it reaches **only this origin**, so the page cannot be made to load somebody else's script;
* every path it calls **exists in the OpenAPI document** — a console that drifts from the API is a
  console that shows an operator a 404 and calls it an empty corpus;
* and the load-bearing one: it does **not hard-code the eight tool signatures**. Its forms are
  generated from `/openapi.json`, so a parameter added in `serve/inputs.py` appears in the UI with
  its documentation, typed nowhere else. If a parameter name ever appears in this file, somebody
  has written the contract down twice and the copy will go stale.

Browser-level behaviour is U024's Playwright suite. This is the part that can be asserted without
one, and it is the part that would be a defect rather than a nuisance.
"""
from __future__ import annotations

import re

import pytest

from vsir.serve import app as app_module
from vsir.serve import auth as auth_module

#: Every parameter of every tool, from the table itself — so this list cannot fall behind the
#: models. If any of these strings is in the console, its forms stopped being generated.
TOOL_PARAMETERS = sorted({
    field
    for spec in app_module.tool_table().values()
    for field in spec.request.model_fields
})


@pytest.fixture(scope="module")
def page() -> str:
    from vsir.serve.app import CONSOLE_PAGE

    return CONSOLE_PAGE.read_text(encoding="utf-8")


@pytest.fixture
def schema(served) -> dict:
    return served.get("/openapi.json").json()


# ── safety ──────────────────────────────────────────────────────────────────────────────────────

def test_the_console_is_exactly_one_free_path(served):
    """A closed list of one. A build step would need a free path per bundled asset, and every one
    of those is a line in the unauthenticated surface — which is why this file is inlined."""
    assert auth_module.CONSOLE_PATHS == {"/console"}
    assert served.get("/console").status_code == 200
    assert served.get("/console/app.js").status_code == 401


def test_the_console_carries_no_credential(page):
    """§15.1 — a free page, so a token baked into it would be a published secret."""
    from conftest import CONTAINER_TOKEN, TEST_TOKEN

    assert TEST_TOKEN not in page
    assert CONTAINER_TOKEN not in page
    # And it asks for one rather than assuming a default.
    assert 'id="token"' in page


def test_the_console_loads_nothing_from_another_origin(page):
    """No CDN, no font host, no analytics. A page that can be made to load somebody else's script
    is a page that can be made to read the operator's token out of this browser."""
    external = re.findall(r'(?:src|href)\s*=\s*["\'](\w+:)?//[^"\']+', page)

    assert not external, f"the console reaches off-origin: {external}"


def test_the_console_sends_the_token_as_a_bearer_header_and_never_in_a_url(page):
    """A URL is logged by every proxy between here and the port (§15.1)."""
    assert 'Authorization: "Bearer "' in page or 'Authorization = "Bearer "' in page
    assert "token=" not in page.replace('localStorage.getItem("vsir.token")', "")


# ── it does not duplicate the contract ──────────────────────────────────────────────────────────

def tool_form_source(page: str) -> str:
    """Just the code that builds and submits a tool form.

    Scoped deliberately. A whole-script scan is the wrong test and fails on things that are not
    the defect: `class="cap"` is CSS and not `lookup`'s `cap`, and `doc_id`, `dpi` and `region`
    are query parameters of `GET /runs` and `GET /pages/{page_id}/image` — routes whose
    parameters live in the path, not in a tool body. What must not be hand-written is the part
    that turns a tool's **schema** into inputs.
    """
    start = page.index("function pickTool")
    return page[start:page.index("// ── API", start)]


def test_the_tool_forms_hard_code_no_tool_parameter(page):
    """The property that makes "self-documenting" true rather than claimed.

    The eight tools have nothing in common in their parameters, so a hand-written form per tool
    would be eight forms to update whenever a signature moved — and this page would be a second
    declaration of a contract §7.5 works to keep single. The forms are built from the published
    schema instead, which is also the honest test of that schema: if it were not good enough to
    build a UI from, this page could not exist.
    """
    source = tool_form_source(page)
    written = [field for field in TOOL_PARAMETERS
               if f'"{field}"' in source or f"'{field}'" in source]

    assert not written, (
        f"these tool parameters are written into the form builder: {written}. It is supposed to "
        f"read them from /openapi.json — see `pickTool`.")


def test_the_form_builder_reads_the_schemas_own_properties(page):
    """The mechanism, named — so it cannot be quietly replaced by a literal that passes the test
    above by listing nothing."""
    source = tool_form_source(page)

    assert "properties" in source and "Object.entries" in source
    assert "required" in source, "a required field must be marked as one"
    assert "spec.description" in source, "each field's own documentation becomes its help text"


def test_the_console_reads_the_schema_and_the_index_to_build_its_forms(page):
    """Named explicitly, so the mechanism cannot be quietly replaced by a literal."""
    assert '"/openapi.json"' in page
    assert "requestBody" in page and "properties" in page
    # `$ref` resolution, because the request bodies are published by reference.
    assert "$ref" in page


def test_the_console_takes_the_ladder_order_from_the_service_index(page):
    """Not an array in this file: the index publishes the eight in ladder order already."""
    assert "index.tools" in page
    for name in app_module.tool_table():
        assert f'"{name}"' not in page, f"{name} is written into the console"


# ── it does not drift from the API ──────────────────────────────────────────────────────────────

def test_every_path_the_console_calls_is_a_path_the_api_serves(page, schema):
    """A console that drifts shows an operator a 404 and calls it an empty corpus."""
    served_paths = set(schema["paths"])
    # The literal API paths it fetches, less the templated ones it builds at run time.
    # `/openapi.json` is deliberately absent: it is the document itself, and FastAPI does not
    # describe its own description route as an operation.
    called = {"/documents", "/runs", "/", "/ready", "/search"}

    missing = {path for path in called if path not in served_paths}
    assert not missing, f"the console calls paths the API does not serve: {sorted(missing)}"
    assert "/openapi.json" in page, "and it does read the document itself"


def test_the_console_links_only_to_documentation_that_is_free(page, schema):
    """Its API tab links to four pages; all four have to be readable without a credential, or the
    links are dead ends for the person who has not typed a token yet."""
    for path in ("/docs", "/redoc", "/openapi.json", "/"):
        assert f'href="{path}"' in page
        assert path in auth_module.PUBLIC_PATHS


def test_the_console_covers_the_whole_surface_it_is_for(page):
    """Six sections: manage, ingest, execute, search, document."""
    for view in ("view-corpus", "view-ingest", "view-runs", "view-tools", "view-search",
                 "view-api"):
        assert f'id="{view}"' in page


# ── the search tab: the flat surface, rendered ──────────────────────────────────────────────────

def test_the_search_tab_offers_every_content_part_the_surface_serves(page):
    """`retrieval.PARTS` is the contract, and the tab's toggles are generated from its own copy.

    The copy is the thing to pin. `/search` is not a tool, so its form is not generated from
    `/openapi.json` — these are checkboxes an operator ticks, and the list behind them is written
    in the page. A part added to the surface that never reaches this array is a feature no
    operator can reach, and nothing else in the suite would notice.
    """
    from vsir.serve.retrieval import PARTS

    declared = re.search(r"const PARTS = \[([^\]]*)\]", page)
    assert declared, "the search tab declares no content parts"
    offered = tuple(one.strip().strip('"\'') for one in declared.group(1).split(",")
                    if one.strip())

    assert offered == tuple(PARTS), (
        f"the search tab offers {offered}, the surface serves {tuple(PARTS)}")


def test_the_search_tab_exposes_every_filter_the_surface_takes(page):
    """Each of `/search`'s own parameters has an input, so the tab is the whole surface and not a
    subset of it that quietly cannot express a scope an operator needs."""
    for field in ("sQuery", "sScope", "sExcludeScope", "sFrom", "sTo", "sInclude",
                  "sTextChars", "sLimit", "sDense", "sLexical", "sCaptions", "sK"):
        assert f'id="{field}"' in page, f"no input for {field}"


def test_the_search_tab_renders_the_trust_that_qualifies_every_row(page):
    """§5.7's four values, each with what it means for the row beside it.

    This is the load-bearing assertion of the tab. An operator scanning twenty-five rows must see
    which pages nobody could read, because an empty `text` on a scanned page is not a blank page —
    and a console that showed the text without the trust would teach the opposite.
    """
    from vsir.core.record import TextTrust
    from typing import get_args

    for value in get_args(TextTrust):
        assert f"{value}:" in page or f'"{value}"' in page, \
            f"the search tab does not render text_trust={value}"
    assert "no_text" in page and "nobody could read this page" in page


def test_the_search_tab_states_the_blind_spot_on_every_search(page):
    """`pages_without_text` is what turns a thin lexical result from a puzzle into a fact (§7.1)."""
    assert "pages_without_text" in page
    assert "cannot reach them at all" in page


def test_the_search_tab_distinguishes_the_pool_from_the_corpus(page):
    """`available` is the end of the ranked list and `total` is the scope.

    A console that showed one number would let an empty page at a high offset read as *"the corpus
    has no more"* — the fabricated absence §7.1 exists to prevent, arriving through pagination.
    """
    assert "available" in page and "in scope" in page
    assert "not the corpus" in page, "an exhausted pool must say it is the pool"


def test_the_search_tab_shows_per_branch_positions_and_never_a_score(page):
    """`surface_ranks` is the honest form of *why is this here* — and a branch that did not return
    the page at all is a dash, which is a different fact from returning it last."""
    assert "surface_ranks" in page
    assert "A position is not a confidence" in page


def test_the_search_tab_treats_codes_as_claims_and_compares_them_case_insensitively(page):
    """D3, and the §5.2 / §6.8 form mismatch that makes a naive comparison silently wrong.

    `codes` is verbatim and `codes_in_text` is lowercased and whitespace-collapsed, so matching
    them exactly finds nothing and renders every backed code as unbacked — which reads as *"the
    page's text supports none of this"*, the opposite of the truth.
    """
    assert "codes_in_text" in page
    assert ".toLowerCase()" in page, "the backed-code comparison must be case-insensitive"
    assert "Claims, not verdicts" in page


def test_the_search_tab_renders_the_status_before_the_rows(page):
    """§7.1's six values reach this tab through the same `STATUS` table the Tools tab uses.

    An empty `rows` under `not_searchable` and one under `not_found` are different instructions,
    and a console showing "0 results" for both would undo the reason they are typed.
    """
    assert "result.status" in page
    assert "STATUS[result.status]" in page, "the status table is shared, not a second copy"


def test_the_search_tab_explains_why_these_rows(page):
    """The interpretation panel — the identifier split is the usual reason a result surprises."""
    assert "query_interpretation" in page
    assert "Exact phrase filter" in page and "branches_skipped" in page
    assert "cannot appear at any rank" in page


def test_the_search_tab_surfaces_the_superseded_revision_to_re_ask_with(page):
    """F9 — "it exists, in a revision no longer current" is useless without the revision."""
    assert "result.superseded" in page
    assert "revision" in page and "Re-ask with" in page


def test_the_search_tab_gates_on_text_usable_and_not_on_has_text(page):
    """§5.7 — an `untrusted` page *has* text and its text may not be believed. Marking the row on
    `has_text` would present a garbled extraction as evidence."""
    assert "row.text_usable" in page
    assert "has text, not usable" in page, "the case the two flags exist to keep apart"


def test_the_search_tab_distinguishes_an_unrequested_part_from_an_empty_one(page):
    """`null` = you did not ask; `""` = the page's extraction is empty. Conflating them is how an
    operator concludes a page is blank when the text was simply never requested."""
    assert "content.text !== null" in page
    assert "nobody could read it, not that it is blank" in page


def test_the_search_tab_checks_the_servers_bounds_before_the_round_trip(page):
    """The same numbers `serve/retrieval.py` refuses on, so an operator sees the named refusal
    immediately — and the server stays the authority for anything that gets through."""
    from vsir.serve.retrieval import MAX_OFFSET, MAX_RRF_K, MAX_TEXT_CHARS
    from vsir.serve.caps import MAX_SKIM_LIMIT

    assert "const BOUNDS" in page
    for bound in (MAX_OFFSET, MAX_RRF_K, MAX_TEXT_CHARS, MAX_SKIM_LIMIT):
        assert str(bound) in page, f"the console does not know the bound {bound}"
    assert "page_range_inverted" in page and "query_required" in page


def test_the_search_tab_shows_a_thumbnail_fetched_with_the_token(page):
    """A page raster is behind the bearer token and an `<img src>` cannot carry a header, so the
    thumbnail has to be fetched and handed to the tag as a blob."""
    assert "loadThumb" in page
    assert "data-thumb" in page and "createObjectURL" in page
    assert "Bearer " in page


def test_the_search_tab_expands_a_row_into_its_details(page):
    """The row is a summary; the detail panel is where the text, codes and operations live."""
    assert "sdetail" in page and "shead" in page
    assert 'closest(".shead")' in page, "one delegated listener, not one per row"


def test_the_search_tab_renders_the_assembled_operations_and_marks_the_one_that_bills(page):
    """`actions` is the point of the row for a consuming system, and an operator should be able to
    copy the body. The one that spends has to look different from the six that do not."""
    assert "row.actions" in page
    assert "one.spends" in page and "bills" in page
    assert "operations on this page" in page


def test_the_search_tab_hands_the_expand_scope_back_without_assembling_it(page):
    """`next.expand` is a scope, handed back exactly as it came — no string building in the UI."""
    assert "data-scope" in page
    assert "next.expand" in page or "moves.expand" in page


def test_the_scope_keys_come_from_the_schema_and_not_from_this_file(page):
    """A key list typed into this page could offer one the server refuses, and the operator would
    read `filter_unknown_key` as a bug in the corpus rather than in the console."""
    from vsir.serve.retrieval import FILTER_KEYS

    assert "propertyNames.enum" in page, "the keys are read off the published schema"
    assert "scopeKeys" in page and "keys.map" in page, "and the options are built from them"

    # The defect this guards is a *list* written into the page, not the incidental mention of a
    # key: `doc_id` appears in the corpus tab and in a placeholder, and neither is a second
    # declaration of the filter vocabulary. So look for three or more of them on one line, which
    # is what a hard-coded array would be and what no legitimate line is.
    for number, line in enumerate(page.splitlines(), start=1):
        present = [key for key in FILTER_KEYS if f'"{key}"' in line or f"'{key}'" in line]
        assert len(present) < 3, (
            f"line {number} looks like a hard-coded filter vocabulary ({present}) — it must come "
            f"from /openapi.json so the console cannot offer a key the server refuses")


def test_the_search_tab_turns_on_every_content_part_like_the_api_does(page):
    """Omitting `include` returns all six; a tab defaulting to fewer would show an operator a
    thinner row than a consuming system gets."""
    assert "PARTS.forEach" in page
    assert "All six are on by default" in page


def test_the_search_tab_offers_the_keyword_filters_and_warns_about_unreadable_pages(page):
    """§5.7, F4 — a required phrase silently excludes every page nobody could read, and an
    operator who does not know that will read an empty result as an absent part."""
    assert 'id="sRequire"' in page and 'id="sForbid"' in page
    assert "require_phrases" in page and "exclude_phrases" in page
    assert "could not be read" in page, "the blind spot has to be stated where it is created"
    assert "required_phrases" in page, "and echoed back in the interpretation panel"


def test_the_search_tab_says_the_keyword_filters_are_expanded_to_lists(page):
    """Comma-separated in the box; an empty term would be a `phrase_empty` refusal, so the
    trailing comma an operator leaves behind is filtered rather than sent."""
    assert "const phrases" in page
    assert ".filter(Boolean)" in page


def test_the_search_tab_says_the_surface_is_free_and_never_answers(page):
    """§7.6 and §8.4 — the one thing an operator must not conclude from this tab is an answer."""
    assert "/ask</code> is the only one that may" in page or "only one that may" in page
    assert "nothing is billed" in page


# ── it renders the distinctions that are the product ────────────────────────────────────────────

def test_the_console_renders_all_six_statuses_of_the_envelope(page):
    """§7.1's four typed absences are four different next moves. A console that collapsed them
    into "no results" would undo the reason they are typed."""
    from vsir.core.status import Status

    for status in Status:
        assert status.value in page, f"the console cannot render {status.value}"


def test_the_console_keeps_verified_and_unverified_apart(page):
    """D3 / I2 — a code read off an image is not a code found in the page's text, and a UI that
    interleaved them would undo the guarantee the index exists to make."""
    assert "unverified_hits" in page
    assert "hit unverified" in page and "hit verified" in page


def test_the_console_marks_the_one_tool_that_spends(page):
    """§8.1's argument is that the free moves come first. A console where the paid call looked
    like the other seven would quietly undo it — so `spends` drives a badge and the button."""
    assert "tool.spends" in page or "picked.spends" in page
    assert "spends money" in page


def test_the_console_reads_the_gate_field_the_wire_actually_carries(page):
    """`GateResult` declares `passed` in Python and `as_dict()` renames it to **`pass`**.

    Worth a test precisely because the Python attribute and the wire field disagree: reading
    `passed` off a run record yields `undefined`, which is falsey, so every gate of every run
    would render as a failure — a published document reported as one that failed its gates.
    """
    from vsir.ingest.gates import GateResult

    script = page[page.index("<script>"):]
    wire = GateResult(name="g", passed=True, blocking=True, detail="").as_dict()

    assert "pass" in wire and "passed" not in wire, "the wire name moved; the console must follow"
    assert "gate.pass" in script
    assert "gate.passed" not in script


def test_the_console_treats_an_early_run_not_found_as_starting(page):
    """`POST /documents` mints the `run_id` in the route and answers `202` **before** the child
    process starts, so the first poll routinely arrives before the run record exists.

    Reporting that `404` as a failure was wrong twice over: it is the expected state for the first
    second or two, and giving up on it *stopped the watch* — so a run that went on to fail for a
    real reason showed the operator `run_not_found` instead of the actual cause. Observed on a
    live 56-page ingest whose real failure was at step 09.
    """
    script = page[page.index("<script>"):]

    assert "RUN_APPEARS_WITHIN_MS" in script
    assert 'failure.code === "run_not_found"' in script
    assert "starting" in script
