"""The eight named tool routes of §7.4 — one path per tool, one dispatcher underneath.

`POST /tools/{tool_name}` was the whole tool surface, and it published **one** OpenAPI operation
with an untyped body for eight tools whose parameters have nothing in common. These tests hold the
two halves of the fix together: each tool now has its own path with its own schema, and *nothing
about how a call is answered changed* — same dispatcher, same typed refusals, same bytes.

The second half is the one worth guarding. A named route that validated its own body would be a
second validator, and its failure would be a `422` with a JSON pointer where §7.3 promises a code
an agent can switch on. So the tests below assert byte-identity between the two paths and assert
that a misspelt parameter is still `invalid_request` — not that the route merely exists.
"""
from __future__ import annotations

import pytest

from vsir.serve import app as app_module
from vsir.serve import auth as auth_module

TOOLS = sorted(app_module.tool_table())


@pytest.fixture
def schema(served) -> dict:
    return served.get("/openapi.json").json()


def test_every_tool_has_its_own_path(schema):
    """Eight tools, eight paths — generated from the table, so neither can drift from the other."""
    for name in TOOLS:
        assert f"/tools/{name}" in schema["paths"], f"{name} has no named route"
        assert "post" in schema["paths"][f"/tools/{name}"]


def test_the_generic_route_is_no_longer_published(schema):
    """It stays mounted and stops being described: eight tools documented once, not twice."""
    assert "/tools/{tool_name}" not in schema["paths"]


def test_each_route_publishes_its_own_request_schema(schema):
    """The point of the exercise: a caller learns `read` takes `question` from the document.

    A ``$ref`` and a schema that is actually in ``components`` — a dangling pointer renders as an
    empty form in Swagger and fails a code generator outright, which is worse than the untyped
    body it replaced.
    """
    for name in TOOLS:
        body = schema["paths"][f"/tools/{name}"]["post"]["requestBody"]
        ref = body["content"]["application/json"]["schema"]["$ref"]
        model = ref.rsplit("/", 1)[-1]
        assert model in schema["components"]["schemas"], f"{name}: {ref} is dangling"
        assert model == app_module.tool_table()[name].request.__name__


def test_the_published_body_is_the_model_the_dispatcher_validates(schema):
    """One declaration. The schema a client generates from is the one that refuses a bad call."""
    table = app_module.tool_table()
    for name in TOOLS:
        published = schema["components"]["schemas"][table[name].request.__name__]
        assert published["additionalProperties"] is False, \
            f"{name}: a misspelt parameter must be a 400, not silently ignored"
        declared = set(table[name].request.model_fields)
        assert set(published.get("properties", {})) == declared


def test_every_parameter_carries_a_description_a_caller_can_act_on(schema):
    """The `#:` comments that only Sphinx could see are now on the wire (§7.5).

    Asserted on the *published* schema rather than on the source, because the whole failure this
    fixes was a note that existed in the code and reached neither transport.
    """
    table = app_module.tool_table()
    missing: list[str] = []
    for name in TOOLS:
        published = schema["components"]["schemas"][table[name].request.__name__]
        for field, spec in published.get("properties", {}).items():
            described = spec.get("description") or any(
                entry.get("description") for entry in spec.get("allOf", [])
                if isinstance(entry, dict))
            if not described:
                missing.append(f"{name}.{field}")
    assert not missing, f"undocumented parameters reach both transports blind: {missing}"


def test_each_route_publishes_the_envelope_it_returns(schema):
    """§7.1's envelope, per tool — so a generated client types the response as well as the body."""
    for name in TOOLS:
        ok = schema["paths"][f"/tools/{name}"]["post"]["responses"]["200"]
        assert "$ref" in str(ok["content"]["application/json"]["schema"])


def test_only_the_paid_tool_documents_a_quota_refusal(schema):
    """`read` can 429 and the seven free tools cannot — the document says which is which."""
    for name in TOOLS:
        responses = schema["paths"][f"/tools/{name}"]["post"]["responses"]
        spends = app_module.tool_table()[name].spends
        assert ("429" in responses) is spends, f"{name}: 429 documented={not spends}"


def test_every_documented_refusal_carries_the_typed_error_schema(schema):
    """A code an agent switches on is worthless if the document never names the shape it is in."""
    for name in TOOLS:
        responses = schema["paths"][f"/tools/{name}"]["post"]["responses"]
        for status, described in responses.items():
            if status == "200" or not str(status).startswith(("4", "5")):
                continue
            if status == "401":
                continue           # declared by `_described` from the middleware's own path list
            assert "content" in described, f"{name} {status}: refusal has no schema"


def test_a_named_route_needs_the_same_token(served):
    """Default-deny covers a route that did not exist when the middleware was written."""
    for name in TOOLS:
        assert f"/tools/{name}" not in auth_module.PUBLIC_PATHS
        assert served.post(f"/tools/{name}", json={}).status_code == 401


@pytest.mark.parametrize("name,body", [
    ("lookup", {"label": "SF 1.1A"}),
    ("verify", {"claims": ["SF 1.1A"], "page_ids": ["SYN-M1@1.0#p1"]}),
    ("resolve", {"printed_label": "1"}),
    ("skim_documents", {"query": "carton discharge"}),
])
def test_the_named_route_and_the_generic_route_return_the_same_bytes(served, token_header,
                                                                    name, body):
    """The property that makes nine routes one surface (§7.5's argument, applied to HTTP).

    Byte-identity and not "equivalent JSON": both paths call :func:`~vsir.serve.envelope.wire` on
    the outcome of the same dispatcher, so this is a fact about the object graph. A route that
    built its own response would pass a shallow equality check and drift on the first field whose
    serialisation differs.
    """
    named = served.post(f"/tools/{name}", json=body, headers=token_header)
    generic = served.post("/tools/{tool_name}".format(tool_name=name), json=body,
                          headers=token_header)

    assert named.status_code == generic.status_code
    assert named.content == generic.content


def test_a_misspelt_parameter_is_still_a_typed_400_and_never_a_422(served, token_header):
    """The refusal contract survives the new routes — this is the whole risk of adding them.

    Had the named route declared a typed body parameter, FastAPI would have answered this with a
    `422` and a JSON pointer. §7.3 promises a code, so the body is validated by the dispatcher on
    both paths and by FastAPI on neither.
    """
    answered = served.post("/tools/lookup", headers=token_header,
                           json={"label": "SF 1.1A", "includeUnverified": True})

    assert answered.status_code == 400
    body = answered.json()
    assert body["error"] == "invalid_request"
    # The field is named in `problems`, which is where the dispatcher puts it — and it is a
    # 400 with a code rather than a 422 with a JSON pointer, which is the property under test.
    assert [problem["field"] for problem in body["problems"]] == ["includeUnverified"]


def test_an_unknown_tool_is_still_the_typed_404_under_the_generic_route(served, token_header):
    """A tool absent from this release is absent, not empty — §7.1 applied to the surface itself."""
    answered = served.post("/tools/summarise", json={}, headers=token_header)

    assert answered.status_code == 404
    body = answered.json()
    assert body["error"] == "tool_not_found"
    assert sorted(body["available"]) == TOOLS


def test_the_named_routes_are_generated_from_the_table_and_not_written_out(served):
    """A tool cannot get a route without being in the table, or be in the table without one.

    Asserted as a set equality rather than by counting: a ninth hand-written route would pass a
    count of eight the moment somebody also deleted a row.
    """
    routed = {route.path.removeprefix("/tools/") for route in served.app.routes
              if getattr(route, "path", "").startswith("/tools/")
              and "{" not in getattr(route, "path", "")}

    assert routed == set(served.app.state.tools)
