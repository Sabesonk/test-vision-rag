"""L2 — the API describes itself from its own root (§7.4).

`/openapi.json` has described every path since U014, and an integrator had to **know to ask for
it**: the base URL answered `404`, which is the one response that teaches nothing. These tests
hold down the three things that closed that gap, and one property each:

* `GET /` is a service index, and it is **derived** — from the tool table and from the router — so
  a tool or a route added next milestone appears in it without anybody remembering.
* every OpenAPI tag a route uses is **described**, so `/docs` explains its own sections rather
  than showing seven bare words.
* the tool routes' `operationId`s are the tool names, because those become the method names of a
  generated client.

And the standing rule underneath all of it: reading the description authorises **nothing**.
"""
from __future__ import annotations

import pytest

from vsir.serve import app as app_module
from vsir.serve import auth as auth_module


@pytest.fixture
def index(served) -> dict:
    response = served.get("/")
    assert response.status_code == 200, "the root must be readable without a credential"
    return response.json()


@pytest.fixture
def schema(served) -> dict:
    return served.get("/openapi.json").json()


# ── the index ───────────────────────────────────────────────────────────────────────────────────

def test_the_root_is_an_index_and_not_a_404(index):
    """The one response that teaches nothing, replaced by the one that teaches the most."""
    assert index["service"] == "vision-segmentation-retriever"
    assert index["documentation"]["openapi"] == "/openapi.json"
    assert index["documentation"]["console"] == "/console"


def test_the_index_says_where_the_credential_goes(index):
    """An integrator's second request should not require reading our source."""
    auth = index["authentication"]

    assert auth["scheme"] == "Bearer"
    assert auth["header"] == "Authorization: Bearer <token>"
    assert "VSIR_API_TOKENS" in auth["tokens"]
    # Identity is derived from the token and never client-supplied — the index says so, because a
    # caller who guesses otherwise builds an `X-User-Id` header that is ignored and logged (§7.4).
    assert "never a client-supplied header" in auth["identity"]


def test_the_index_lists_the_eight_tools_in_ladder_order(index, served):
    """Ladder order and not alphabetical: the list is read by something choosing a **move**."""
    assert [card["name"] for card in index["tools"]] == list(served.app.state.tools)
    assert [card["move"] for card in index["tools"]][:3] == ["NARROW", "NARROW", "NARROW"]
    assert index["tools"][-1]["name"] == "read"


def test_the_index_names_the_one_tool_that_spends(index):
    """The single most consequential fact about the surface, and it is on the front page."""
    spending = [card["name"] for card in index["tools"] if card["spends"]]

    assert spending == ["read"]
    assert "COMPREHEND" in next(card["move"] for card in index["tools"]
                                if card["name"] == "read")


def test_every_tool_card_points_at_a_route_that_exists(index, schema):
    for card in index["tools"]:
        assert card["path"] in schema["paths"], f"{card['name']} advertises a path that is not served"
        assert card["description"], f"{card['name']} has no description to choose on"


def test_the_index_is_derived_from_the_table_and_not_hand_listed(index, served):
    """A list maintained by hand is a list that is wrong by the second release.

    Asserted by adding a tool to *this app's* table and reading the index again: if the cards were
    a literal, the new row would not appear.
    """
    served.app.state.tools["nine"] = app_module.ToolSpec(
        name="nine", request=app_module.LookupRequest, call=lambda *a: None,
        description="a tool that exists only in this test")
    try:
        again = served.get("/").json()
        assert "nine" in [card["name"] for card in again["tools"]]
    finally:
        del served.app.state.tools["nine"]


def test_the_path_table_covers_every_route_the_app_serves(index, served):
    """Derived from the router, so it cannot silently fall behind the surface."""
    routed = {
        f"{method} {getattr(route, 'path', '')}"
        for route in served.app.routes
        for method in sorted(getattr(route, "methods", set()) or set())
        if method not in ("HEAD", "OPTIONS") and getattr(route, "path", "")
    }
    missing = routed - set(index["paths"])

    assert not missing, f"the index does not mention these routes: {sorted(missing)}"


def test_every_path_in_the_table_says_what_it_is_for(index):
    undescribed = [path for path, purpose in index["paths"].items() if not purpose]

    assert not undescribed, f"listed with no explanation: {undescribed}"


# ── free, and free changes nothing ──────────────────────────────────────────────────────────────

def test_the_index_carries_no_credential(served):
    """§15.1 — it is a free page, so a token in it would be a published secret."""
    from conftest import CONTAINER_TOKEN, TEST_TOKEN

    rendered = served.get("/").text

    assert TEST_TOKEN not in rendered
    assert CONTAINER_TOKEN not in rendered


def test_the_index_carries_no_corpus_data(index):
    """What makes it free: the *shape* of the interface, and nothing the interface holds.

    No `doc_id`, no `page_id`, no `run_id`, no count of anything. A reader who can see this is
    exactly as far from the corpus as one who can read `/openapi.json` — one `401` away.
    """
    rendered = str(index)

    for leaked in ("SYN-M1", "page_id\":", "@1.0#p", "run_id\":"):
        assert leaked not in rendered, f"the index leaked corpus data: {leaked}"
    assert "documents" not in index or not isinstance(index.get("documents"), list)


def test_reading_the_index_does_not_open_the_api(served):
    """The standing rule, restated for the new free path."""
    assert served.get("/").status_code == 200

    assert served.post("/tools/lookup", json={"label": "SF 1.1A"}).status_code == 401
    assert served.get("/documents").status_code == 401
    assert served.get("/runs").status_code == 401


def test_the_root_is_free_for_the_documentation_reason_and_is_grouped_with_them(index):
    """It is in `DOC_PATHS`, not `PROBE_PATHS` — free because it is documentation."""
    assert "/" in auth_module.DOC_PATHS
    assert "/" not in auth_module.PROBE_PATHS
    assert "/" in index["authentication"]["free_paths"]


# ── the document explains its own sections ──────────────────────────────────────────────────────

def test_every_tag_a_route_uses_is_described(schema):
    """Seven bare words in Swagger was the same failure as the untyped tool body: the
    information existed and the document did not carry it."""
    used = {tag for operations in schema["paths"].values()
            for operation in operations.values() if isinstance(operation, dict)
            for tag in operation.get("tags", [])}
    described = {tag["name"] for tag in schema.get("tags", [])}

    assert used <= described, f"tag groups with no explanation: {sorted(used - described)}"


def test_the_tools_group_explains_the_two_properties_a_caller_must_know(schema):
    """A typed absence is not an empty result, and a bound is a refusal — said once, up front."""
    tools = next(tag for tag in schema["tags"] if tag["name"] == "tools")

    assert "typed absence" in tools["description"]
    assert "own code" in tools["description"]
    for move in ("NARROW", "JUMP", "FOLLOW", "CHECK", "LOOK", "COMPREHEND"):
        assert move in tools["description"]


def test_the_corpus_group_says_there_is_no_chunk(schema):
    """The question every integrator asks, answered where they will ask it."""
    corpus = next(tag for tag in schema["tags"] if tag["name"] == "corpus")

    assert "no chunk" in corpus["description"]
    assert "page_id" in corpus["description"]


def test_a_generated_client_gets_the_tool_name_as_its_method_name(schema):
    """FastAPI derives an `operationId` from the handler, and all eight are the same closure —
    so without this they would be `named_tool_tools_lookup_post` and friends."""
    for name in served_tools():
        operation = schema["paths"][f"/tools/{name}"]["post"]
        assert operation["operationId"] == name


def served_tools() -> list[str]:
    return sorted(app_module.tool_table())
