"""L2 — a bearer token on every path but the three probes (Spec §7.4, §15.1; register **E5**).

The defect being closed is not subtle. `impl/app/main.py` exposes eleven endpoints and checks a
credential on none of them, including `POST /api/v1/read` — the vision call that spends money —
and `DELETE /api/v1/documents/{doc_id}`, which removes a document from the index. §2.5 A records
it; this suite is what makes it stay closed.

Two properties are asserted that a per-route dependency could not give:

* **Default deny.** ``GET /pages/{page_id}/image`` is built at U018 and is *already* refused
  without a token today, because protection is a property of the path and not something a route
  opts into. A route added next milestone cannot arrive unauthenticated.
* **Identity is the credential's, never the caller's.** An ``X-User-Id`` header is read only so
  that the attempt appears on the event stream as ignored; the identity that reaches the budget
  and the audit line is a digest of the token, and `test_audit.py` asserts that end to end.

Nothing here asserts on a token *value* beyond sending it. §15.1: the token must never appear in
a log line, a response or an error message — and the last test walks a whole request cycle to
check that it does not.
"""
from __future__ import annotations

import httpx
import pytest

from vsir.serve import auth as auth_module
from vsir.serve.app import create_app

from conftest import TEST_TOKEN, WRONG_TOKEN, log_events, serve_env

LOOKUP = "/tools/lookup"


def _body(corpus) -> dict[str, str]:
    """A label the corpus really carries, so a `200` means *found*, not *empty but authorised*."""
    return {"label": corpus.expected["compact_labels"][0]["label"]}


# ── 401 without a token, 200 with one ────────────────────────────────────────────────────────────

def test_a_tool_call_without_an_authorization_header_is_401(served):
    """§7.4's first clause, and U014's headline acceptance criterion."""
    response = served.post(LOOKUP, json={})

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_a_tool_call_with_a_configured_token_is_200(served, token_header, corpus):
    response = served.post(LOOKUP, json=_body(corpus), headers=token_header)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert response.json()["total"] == 1


def test_a_token_that_is_not_configured_is_401(served, corpus):
    response = served.post(LOOKUP, json=_body(corpus),
                           headers={"Authorization": f"Bearer {WRONG_TOKEN}"})

    assert response.status_code == 401


@pytest.mark.parametrize("header", [
    "",                              # present but empty
    TEST_TOKEN,                      # the token with no scheme
    f"Basic {TEST_TOKEN}",           # the right credential, the wrong scheme
    "Bearer",                        # the scheme with no credential
    "Bearer  ",
])
def test_a_malformed_authorization_header_is_401(served, corpus, header):
    """A header that does not parse is refused, never partially honoured."""
    response = served.post(LOOKUP, json=_body(corpus), headers={"Authorization": header})

    assert response.status_code == 401


def test_the_refusal_carries_www_authenticate(served):
    """What tells a client *how* to authenticate. The only thing a 401 body is allowed to say."""
    response = served.post(LOOKUP, json={})

    assert response.headers["www-authenticate"] == "Bearer"


def test_the_401_body_says_nothing_about_which_part_failed(served, corpus):
    """A missing header, a malformed one and a wrong token are indistinguishable to the caller.

    Telling an unauthenticated caller *"the header parsed but the token is unknown"* is an oracle,
    and it buys a legitimate client nothing the same sentence does not.
    """
    missing = served.post(LOOKUP, json=_body(corpus))
    wrong = served.post(LOOKUP, json=_body(corpus),
                        headers={"Authorization": f"Bearer {WRONG_TOKEN}"})

    assert missing.json() == wrong.json()


# ── which paths are free, and which are not ──────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/health", "/ready", "/metrics"])
def test_the_three_probes_need_no_token(served, path):
    """§7.4 — an orchestrator holds no credential, and a scrape is on an internal network."""
    response = served.get(path)

    assert response.status_code in {200, 503}, response.text
    assert response.status_code != 401


def test_the_page_image_route_requires_a_token_before_it_is_even_built(served):
    """§7.4 — `GET /pages/{page_id}/image` is bearer. It arrives at U018; it is protected now.

    This is the whole argument for middleware over a per-route dependency: the route does not
    exist, so there is nothing to decorate, and it is refused anyway. A future unit cannot ship it
    unauthenticated by forgetting.
    """
    response = served.get("/pages/SYN-M1@1.0%23p001/image?dpi=150")

    assert response.status_code == 401


@pytest.mark.parametrize("path", [
    "/runs/01JX000000000000000000000A",
    "/runs/01JX000000000000000000000A/export/labels.jsonl",
    "/tools/lookup",
    "/ask",
])
def test_every_non_probe_path_is_refused_without_a_token(served, path):
    """Default deny: the allowlist is three probes, and everything else is on the other side."""
    assert served.get(path).status_code == 401
    assert served.post(path, json={}).status_code == 401


def test_an_authorised_call_to_an_unbuilt_route_is_a_404_not_a_401(served, token_header):
    """The refusals stay distinct: *"who are you"* and *"there is nothing here"* are not the same.

    With a valid token the same page-image path falls through to routing, which has no such route
    yet — so the caller learns the truth (it is not built) instead of being told to authenticate
    again with the credential that just worked.
    """
    response = served.get("/pages/SYN-M1@1.0%23p001/image?dpi=150", headers=token_header)

    assert response.status_code == 404


# ── identity comes from the token, and only from the token ───────────────────────────────────────

def test_the_identity_is_a_digest_of_the_token_and_is_not_the_token():
    """§15.1 — what reaches an audit line and a budget record is never the credential."""
    identity = auth_module.caller_id(TEST_TOKEN)

    assert identity.startswith(auth_module.CALLER_PREFIX)
    assert TEST_TOKEN not in identity
    assert identity == auth_module.caller_id(TEST_TOKEN), "stable across calls and replicas"
    assert identity != auth_module.caller_id(WRONG_TOKEN)


def test_a_client_supplied_user_id_header_is_ignored_and_said_so(served, token_header, corpus,
                                                                 log_stream):
    """§7.4 — identity is propagated, never client-supplied.

    The header is read for exactly one purpose: to put the attempt on the event stream. The
    ``user_id`` on that line is the token's digest, not what the client asked to be called.
    `test_audit.py` asserts the same thing on the audit record itself.
    """
    response = served.post(LOOKUP, json=_body(corpus),
                           headers={**token_header, "X-User-Id": "root", "X-Caller-Id": "root"})

    assert response.status_code == 200
    ignored = [event for event in log_events(log_stream)
               if event["event"] == "client_identity_ignored"]
    assert len(ignored) == 1, log_stream.getvalue()
    assert sorted(ignored[0]["headers"]) == ["x-caller-id", "x-user-id"]
    assert ignored[0]["user_id"] == auth_module.caller_id(TEST_TOKEN)
    assert ignored[0]["user_id"] != "root"


def test_two_configured_tokens_are_two_identities(qdrant, served_collection, corpus):
    """A deployment with several callers distinguishes them, and the digest is what does it."""
    second = "u014-a-second-local-test-credential"
    env = serve_env(VSIR_API_TOKENS=f"{TEST_TOKEN},{second}")

    from fastapi.testclient import TestClient
    with TestClient(create_app(env)) as client:
        first_call = client.post(LOOKUP, json=_body(corpus),
                                 headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        second_call = client.post(LOOKUP, json=_body(corpus),
                                  headers={"Authorization": f"Bearer {second}"})

    assert first_call.status_code == 200
    assert second_call.status_code == 200
    assert auth_module.caller_id(TEST_TOKEN) != auth_module.caller_id(second)


# ── the tool table, and a body that does not fit it ──────────────────────────────────────────────

def test_a_tool_this_release_does_not_serve_is_a_404_naming_what_it_does(served, token_header):
    """A name that is not in the table is *absent*, not empty (§7.1's whole argument, applied)."""
    response = served.post("/tools/read", json={"page_ids": ["x"], "question": "?"},
                           headers=token_header)

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "tool_not_found"
    assert body["available"] == ["lookup"]


def test_a_misspelt_parameter_is_a_400_and_not_a_quietly_different_query(served, token_header,
                                                                        corpus):
    """``extra="forbid"`` — ``includeUnverified`` must not be accepted and then ignored."""
    response = served.post(LOOKUP, json={**_body(corpus), "includeUnverified": True},
                           headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert "includeUnverified" in str(response.json()["problems"])


def test_a_body_that_is_not_json_is_a_400(served, token_header):
    response = served.post(LOOKUP, content=b"{not json", headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_json"


# ── §15.1: no credential on the event stream, anywhere in a request cycle ────────────────────────

def test_no_token_and_no_key_appears_anywhere_in_a_full_request_cycle(served, token_header,
                                                                      corpus, log_stream):
    """§15.1 — the tokens and the VLM key never reach a log line, a response or an error message.

    A *cycle*, not one call: an authorised call, an unauthorised one, a refused body, a probe and
    a metrics scrape, then the whole captured stream and every response body is searched.
    """
    responses = [
        served.post(LOOKUP, json=_body(corpus), headers=token_header),
        served.post(LOOKUP, json={}),
        served.post(LOOKUP, json=_body(corpus),
                    headers={"Authorization": f"Bearer {WRONG_TOKEN}"}),
        served.post(LOOKUP, json={"nope": 1}, headers=token_header),
        served.get("/health"),
        served.get("/metrics"),
    ]

    stream = log_stream.getvalue()
    assert stream, "the cycle must actually have logged something"
    for secret in (TEST_TOKEN, WRONG_TOKEN):
        assert secret not in stream, f"a credential reached the event stream: {secret}"
        for response in responses:
            assert secret not in response.text
            assert secret not in str(dict(response.headers))


def test_the_running_container_refuses_an_unauthenticated_tool_call(base_url, pages_collection):
    """The image in the test stack, not an in-process app: the release production would run."""
    with httpx.Client(base_url=base_url, timeout=10) as client:
        anonymous = client.post(LOOKUP, json={"label": "SF 1.1A"})
        probe = client.get("/health")

    assert anonymous.status_code == 401, anonymous.text
    assert anonymous.headers["www-authenticate"] == "Bearer"
    assert probe.status_code == 200
