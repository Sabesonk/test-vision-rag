"""L2 — the service holds no scope between calls (Spec §7.1, C11, F8's stateless half, U017).

plan2 specified a server-side `RetrievalState` holding `scope` and `exclude_list` across turns.
C11 struck it, and F8 says why in one line: *"searches a subset believing it searched the
chapter"*. A server that remembers the last scope answers a later, unscoped question from inside
the earlier narrowing — and the caller has no way to see that it did, because the response looks
exactly like a full-corpus answer.

So the contract is the opposite of a session: `scope` and `exclude` are **parameters**, and every
Family A response echoes `effective_scope` back — the caller is told what was searched rather than
trusted to remember what it asked. That is also the twelve-factor half of the same rule (§15
Factor VI): with nothing in process memory, a second replica answers identically and no
sticky-session requirement can creep in.

The assertions run against `skim_pages`, `lookup` and `resolve` together, because the property is
of the **surface** and not of one tool: one of them growing a memory would be exactly as damaging
as all three doing it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vsir.serve.app import create_app

from conftest import SKIM_COLLECTION, SKIM_RUNS, serve_env

SKIM = "/tools/skim_pages"
LOOKUP = "/tools/lookup"
RESOLVE = "/tools/resolve"
QUERY = "emergency stop reset"

#: A scope narrow enough that an answer from inside it is obviously not a full-corpus answer.
NARROW = {"doc_id": "SYN-M1", "page_no": 1}


def post(client, headers, path, body):
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ── effective_scope is echoed, on every rung ────────────────────────────────────────────────────

@pytest.mark.parametrize("path,body,scope", [
    (SKIM, {"query": QUERY, "scope": NARROW}, NARROW),
    (SKIM, {"query": QUERY}, {}),
    (LOOKUP, {"label": "K158", "scope": {"doc_id": "SYN-M1"}}, {"doc_id": "SYN-M1"}),
    (RESOLVE, {"printed_label": "8"}, {}),
])
def test_effective_scope_is_echoed_and_equals_the_request_plus_is_current(skimming, token_header,
                                                                          path, body, scope):
    """F8 — the caller is told what was searched, and `is_current` is added server-side (I7)."""
    answered = post(skimming, token_header, path, body)

    assert answered["effective_scope"] == {**scope, "is_current": True}


def test_a_caller_cannot_ask_for_unpublished_pages_and_is_shown_the_override(skimming,
                                                                             token_header):
    """An explicit `is_current: False` is **overridden**, not honoured — and visibly so."""
    answered = post(skimming, token_header, SKIM,
                    {"query": QUERY, "scope": {"doc_id": "SYN-M1", "is_current": False}})

    assert answered["effective_scope"]["is_current"] is True


# ── nothing carries over ────────────────────────────────────────────────────────────────────────

def test_a_narrow_call_does_not_narrow_the_next_one(skimming, token_header):
    """The injury F8 names, as a sequence of three calls on one connection."""
    wide_before = post(skimming, token_header, SKIM, {"query": QUERY})
    narrow = post(skimming, token_header, SKIM, {"query": QUERY, "scope": NARROW})
    wide_after = post(skimming, token_header, SKIM, {"query": QUERY})

    assert narrow["scope_stats"]["pages"] == 1
    assert wide_before["scope_stats"]["pages"] > 1
    assert wide_after["scope_stats"]["pages"] == wide_before["scope_stats"]["pages"]
    assert [hit["page_id"] for hit in wide_after["hits"]] == \
        [hit["page_id"] for hit in wide_before["hits"]]


def test_an_excluded_page_comes_back_on_the_next_call(skimming, token_header):
    """`exclude` is an argument, not a memory: the agent holds the list of what it rejected."""
    before = post(skimming, token_header, SKIM, {"query": QUERY, "limit": 5})
    dropped = before["hits"][0]["page_id"]

    without = post(skimming, token_header, SKIM,
                   {"query": QUERY, "limit": 5, "exclude": [dropped]})
    again = post(skimming, token_header, SKIM, {"query": QUERY, "limit": 5})

    assert dropped not in [hit["page_id"] for hit in without["hits"]]
    assert again["hits"][0]["page_id"] == dropped


def test_two_callers_do_not_see_each_others_scope(skimming, token_header):
    """No session table means no per-caller anything — including no cross-talk to have."""
    from conftest import TEST_TOKEN

    other = {"Authorization": f"Bearer {TEST_TOKEN}", "x-session-id": "another-session"}
    mine = post(skimming, token_header, SKIM, {"query": QUERY, "scope": NARROW})
    theirs = post(skimming, other, SKIM, {"query": QUERY})

    assert mine["effective_scope"] == {**NARROW, "is_current": True}
    assert theirs["effective_scope"] == {"is_current": True}
    assert theirs["scope_stats"]["pages"] > mine["scope_stats"]["pages"]


def test_a_second_instance_answers_the_same_unscoped_question_the_same_way(skimming, token_header):
    """§15 Factor VI — a replica behind a load balancer, with no sticky session to require."""
    body = {"query": QUERY, "scope": {"doc_id": "SYN-M1"}, "limit": 5}
    mine = post(skimming, token_header, SKIM, body)

    with TestClient(create_app(serve_env(VSIR_COLLECTION=SKIM_COLLECTION,
                                         VSIR_RUNS_COLLECTION=SKIM_RUNS))) as replica:
        theirs = post(replica, token_header, SKIM, body)

    assert theirs["effective_scope"] == mine["effective_scope"]
    assert [hit["page_id"] for hit in theirs["hits"]] == [hit["page_id"] for hit in mine["hits"]]


# ── and there is nowhere for it to be kept ──────────────────────────────────────────────────────

def test_the_request_context_holds_no_scope_cursor_or_history():
    """C11, read off the types: what a tool call is given is a store, a config and a request.

    A field for "the last scope" would have to exist before a session could be kept in one, so the
    assertion is on the shape rather than on behaviour — behaviour can be right by accident on the
    day it is measured.
    """
    import dataclasses

    from vsir.serve.app import ToolContext, ToolRuntime

    assert {field.name for field in dataclasses.fields(ToolContext)} == {
        "client", "cfg", "identity", "reads_remaining", "provenance", "embedder"}
    assert {field.name for field in dataclasses.fields(ToolRuntime)} == {
        "config", "search", "tools", "embedder"}


def test_the_tool_modules_hold_no_module_level_mutable_store():
    """§15.2's ban, asserted on the modules the ladder is built from.

    A dict or a list at module scope is where a session store appears first — one object shared by
    every app in the process, surviving every request, and invisible until two callers disagree.
    """
    import vsir.serve.tools.lookup as lookup_module
    import vsir.serve.tools.resolve as resolve_module
    import vsir.serve.tools.skim as skim_module

    for module in (skim_module, resolve_module, lookup_module):
        mutable = {name: value for name, value in vars(module).items()
                   if isinstance(value, (dict, list, set)) and not name.startswith("__")}
        # `WHY` is the one mapping, and it is a constant table of two-word strings, not a store.
        assert set(mutable) <= {"WHY"}, f"{module.__name__} holds {sorted(mutable)}"
