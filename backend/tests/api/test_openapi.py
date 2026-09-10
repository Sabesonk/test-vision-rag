"""L2 — the API describes itself, and the description is true (§7.4).

The document is not decoration: it is what a caller reads to find out whether a token is needed and
where it goes. Auth here is **default deny by path, in middleware**, which FastAPI cannot infer
from the routes — so a generated schema described an API with no security at all, and that is wrong
in the direction that matters. A reader concludes no credential is needed, and Swagger UI shows no
*Authorize* button, so every `Try it out` returns 401 with nowhere to put one.

The first attempt at fixing this was a local proxy that injected the token. That was the wrong
answer for three reasons worth recording, because they are the reasons not to reach for it again:
it put the credential in a second place, the surface that worked was not the shipped one, and
`/docs` stayed broken for everyone who did not run the proxy.

So the requirement is declared in the document, derived from the same list the middleware reads.
What these tests hold down is that the two cannot disagree.
"""
from __future__ import annotations

import pytest

from vsir.serve import auth as auth_module

pytestmark = pytest.mark.usefixtures("served")


@pytest.fixture
def schema(served) -> dict:
    response = served.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


# ── the document says what the middleware does ──────────────────────────────────────────────────

def test_every_operation_that_needs_a_token_says_so(schema):
    """Derived from `PUBLIC_PATHS`, so a route added later is covered without anyone remembering.

    That is the same property the middleware has, and it is the point: a route is protected by
    existing, not by opting in.
    """
    undeclared = [
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        if path not in auth_module.PUBLIC_PATHS
        for method, operation in operations.items()
        if isinstance(operation, dict) and not operation.get("security")
    ]

    assert not undeclared, f"these operations require a token but do not declare one: {undeclared}"


def test_every_operation_that_needs_a_token_documents_the_refusal(schema):
    missing = [
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        if path not in auth_module.PUBLIC_PATHS
        for method, operation in operations.items()
        if isinstance(operation, dict) and "401" not in operation.get("responses", {})
    ]

    assert not missing, f"these operations can answer 401 but do not document it: {missing}"


def test_the_probes_declare_no_credential_because_they_need_none(schema):
    """An orchestrator holds no token, and a liveness probe that could fail on a rotation would
    turn a secret rotation into a restart loop (§15.1)."""
    for probe in ("/health", "/ready", "/metrics"):
        operation = schema["paths"][probe]["get"]

        assert not operation.get("security"), f"{probe} must not ask for a credential"
        assert "401" not in operation.get("responses", {})


def test_the_scheme_is_bearer_and_says_where_the_token_comes_from(schema):
    scheme = schema["components"]["securitySchemes"]["bearerAuth"]

    assert scheme["type"] == "http" and scheme["scheme"] == "bearer"
    assert "VSIR_API_TOKENS" in scheme["description"]


def test_no_credential_appears_in_the_description(served):
    """§15.1 — this document is now readable without a token, so it must not contain one.

    Naming the *variable* is fine and is the useful thing to say; carrying its value would publish
    the credential to anyone who can reach the port.
    """
    from conftest import CONTAINER_TOKEN, TEST_TOKEN

    rendered = served.get("/openapi.json").text

    assert TEST_TOKEN not in rendered
    assert CONTAINER_TOKEN not in rendered


# ── the pages are readable, and reading them authorises nothing ─────────────────────────────────

@pytest.mark.parametrize("path", sorted(auth_module.DOC_PATHS - {"/docs/oauth2-redirect"}))
def test_the_description_and_its_pages_need_no_token(path, served):
    """A browser cannot attach a header to a plain navigation, so an authenticated `/docs` is a
    401 and nothing else. What these pages contain is the shape of the interface — no corpus data,
    no run, no page, no token."""
    response = served.get(path)

    assert response.status_code == 200, f"{path} must be readable without a credential"


def test_reading_the_description_does_not_open_the_api(served):
    """The whole point of declaring the scheme rather than removing the requirement."""
    assert served.get("/openapi.json").status_code == 200

    assert served.post("/tools/lookup", json={"label": "SF 1.1A"}).status_code == 401
    assert served.post("/documents", files={"file": ("d.pdf", b"%PDF-1.7\n")}).status_code == 401
    assert served.get("/runs/01ABC").status_code == 401


def test_the_free_surface_is_exactly_the_probes_the_documents_and_the_console():
    """Three sets, free for different reasons — and a closed list, so none grows by accident.

    A probe is free so an orchestrator can reach it, a document so a human can read the interface,
    the console so a browser can load the page that then asks for a credential. **Anything that
    returns corpus data, a run, a raster or prose belongs in none of them** — which is what the
    last assertion is for, and it is the one that would fail if somebody made a data route free to
    save typing a token.
    """
    assert auth_module.PROBE_PATHS == {"/health", "/ready", "/metrics"}
    assert auth_module.CONSOLE_PATHS == {"/console"}
    # The documents are the interface describing itself, and `/` is the index of it: paths, tool
    # names and where a credential goes. It grew by one for that reason and may only grow again
    # for the same one.
    assert auth_module.DOC_PATHS == {"/", "/openapi.json", "/docs", "/docs/oauth2-redirect",
                                     "/redoc"}
    assert auth_module.PUBLIC_PATHS == (auth_module.PROBE_PATHS | auth_module.DOC_PATHS
                                        | auth_module.CONSOLE_PATHS)
    assert not any(path.startswith(("/tools", "/documents", "/runs", "/ask", "/pages"))
                   for path in auth_module.PUBLIC_PATHS)


def test_the_console_page_is_served_and_asks_for_no_credential(served):
    """A browser cannot attach a header to a navigation, so the page has to be free — and serving
    markup authorises nothing: every call the page makes carries the operator's own token."""
    response = served.get("/console")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "vsir console" in response.text


def test_the_console_carries_no_credential_of_its_own(served):
    """§15.1 — it is a free page, so a token baked into it would be a published secret.

    The operator types theirs in and it stays in their browser.
    """
    from conftest import CONTAINER_TOKEN, TEST_TOKEN

    page = served.get("/console").text

    assert TEST_TOKEN not in page
    assert CONTAINER_TOKEN not in page


def test_a_path_that_merely_starts_like_a_public_one_is_still_protected(served):
    """`is_public` is an exact match, not a prefix: a prefix rule is how an unauthenticated
    surface grows by accident."""
    assert not auth_module.is_public("/docs-admin")
    assert not auth_module.is_public("/openapi.json.bak")
    assert not auth_module.is_public("/healthz-admin")
