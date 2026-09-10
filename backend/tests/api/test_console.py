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

def test_the_console_hard_codes_no_tool_parameter(page):
    """The property that makes "self-documenting" true rather than claimed.

    The eight tools have nothing in common in their parameters, so a hand-written form per tool
    would be eight forms to update whenever a signature moved — and this page would be a second
    declaration of a contract §7.5 works to keep single. The forms are built from the published
    schema instead, which is also the honest test of that schema: if it were not good enough to
    build a UI from, this page could not exist.
    """
    script = page[page.index("<script>"):]
    written = [field for field in TOOL_PARAMETERS
               if f'"{field}"' in script or f"'{field}'" in script]

    assert not written, (
        f"these tool parameters are written into the console: {written}. Its forms are supposed "
        f"to come from /openapi.json — see `pickTool`.")


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
    # The literal paths it fetches, less the templated ones it builds at run time.
    called = {"/documents", "/runs", "/openapi.json", "/", "/ready"}

    missing = {path for path in called if path not in served_paths}
    assert not missing, f"the console calls paths the API does not serve: {sorted(missing)}"


def test_the_console_links_only_to_documentation_that_is_free(page, schema):
    """Its API tab links to four pages; all four have to be readable without a credential, or the
    links are dead ends for the person who has not typed a token yet."""
    for path in ("/docs", "/redoc", "/openapi.json", "/"):
        assert f'href="{path}"' in page
        assert path in auth_module.PUBLIC_PATHS


def test_the_console_covers_the_whole_surface_it_is_for(page):
    """Five sections, and the four verbs the request was about: manage, ingest, execute, document."""
    for view in ("view-corpus", "view-ingest", "view-runs", "view-tools", "view-api"):
        assert f'id="{view}"' in page


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


def test_the_console_reads_the_gate_field_that_exists(page):
    """`GateResult` declares `passed`. The previous console read `pass`, which is always
    undefined — so every gate of every run rendered as a failure."""
    script = page[page.index("<script>"):]

    assert "gate.passed" in script
    assert "gate.pass;" not in script and "g.pass;" not in script
