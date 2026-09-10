"""L2 — every row of Spec §11.3 as a **refusal**, never a best-effort fallback.

The rows this unit owns: an unreachable Qdrant, an exhausted per-caller quota, and the surfacing
of a collapsed `grounded_rate`. The `read`-specific halves belong to their own units — U020 wires
the real `read` behind `503 vlm_unavailable`, U018 the `fetch` bounds — so what is asserted here
is the **dispatcher's policy**, over a tool registered in the same table the real ones will use.

One sentence explains the whole file. *A failed call returned as an empty call turns our outage
into the agent's fabricated abstention.* An empty `200` is indistinguishable from *"searched, and
the part genuinely is not there"*, which is the one answer this system exists to be trusted about
— so a backing service that did not answer is a `503` with a name, and never a result.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from vsir.core import verify as verify_module
from vsir.core.record import UNSEARCHABLE_TRUST
from vsir.serve import app as app_module
from vsir.serve import auth as auth_module
from vsir.serve import budget as budget_module
from vsir.serve.app import create_app
from vsir.serve.audit import Usage
from vsir.serve.envelope import Provenance, ToolEnvelope
from vsir.vlm.cache import VlmCallFailed, VlmSchemaInvalid, VlmUnavailable

from conftest import SERVED_RUNS, TEST_TOKEN, serve_env

LOOKUP = "/tools/lookup"
UNREACHABLE_URL = "http://127.0.0.1:6399"  # nothing listens here, and nothing may start to


class Nothing(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpyRequest(app_module.ToolRequest):
    page_ids: list[str] = []


def _raises(failure: BaseException):
    def call(context: app_module.ToolContext, body: SpyRequest):
        raise failure
    return call


def _answers(context: app_module.ToolContext, body: SpyRequest):
    return (ToolEnvelope[Nothing](status="ok", result=Nothing(),
                                  provenance=Provenance(release_id=context.cfg.release_id)),
            Usage.free())


def _register(client, name: str, call, *, spends: bool = False) -> None:
    client.app.state.tools[name] = app_module.ToolSpec(
        name=name, request=SpyRequest, call=call, spends=spends)


@contextmanager
def app_with(qdrant, **overrides: str):
    """A second app with different configuration, and its budget ledger cleaned up afterwards."""
    try:
        with TestClient(create_app(serve_env(**overrides))) as client:
            yield client
    finally:
        if qdrant.collection_exists(SERVED_RUNS):
            qdrant.delete_collection(SERVED_RUNS)


def _headers(**extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}", **extra}


# ── row 1 · Qdrant unreachable ───────────────────────────────────────────────────────────────────

def test_qdrant_down_503_ready_red_health_green(qdrant, corpus):
    """§11.3 row 1, whole. Liveness green, readiness red, every tool a named, retryable `503`.

    Green liveness is not a detail: if `/health` failed on a backing-service outage, the
    orchestrator would restart every replica, and the restarts would outlast the outage.
    """
    with app_with(qdrant, VSIR_QDRANT_URL=UNREACHABLE_URL) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        tool = client.post(LOOKUP, headers=_headers(),
                           json={"label": corpus.expected["compact_labels"][0]["label"]})

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 503
    assert tool.status_code == 503, tool.text
    assert tool.json()["error"] == "qdrant_unavailable"
    assert tool.json()["retryable"] is True


def test_a_store_outage_is_never_a_200_with_an_empty_hits_list(qdrant, corpus):
    """The failure this whole design exists to prevent, asserted directly."""
    with app_with(qdrant, VSIR_QDRANT_URL=UNREACHABLE_URL) as client:
        response = client.post(LOOKUP, headers=_headers(), json={"label": "K158"})

    assert response.status_code != 200
    body = response.json()
    assert "hits" not in body and "status" not in body, body
    assert body["error"] == "qdrant_unavailable"


def test_the_outage_refusal_names_no_credential(qdrant):
    """§15.1 — a `503` body carries a type name, never a URL that could carry userinfo."""
    with app_with(qdrant, VSIR_QDRANT_URL=UNREACHABLE_URL) as client:
        body = client.post(LOOKUP, headers=_headers(), json={"label": "K158"}).text

    assert TEST_TOKEN not in body
    assert "6399" not in body


# ── row 2 · the model backend cannot run ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("failure", [
    VlmUnavailable("no credential is configured"),
    VlmCallFailed("the provider did not answer after 4 attempts"),
])
def test_a_vlm_outage_is_503_vlm_unavailable_while_the_free_tools_answer(served, corpus, failure):
    """§11.3 row 2 — `503 vlm_unavailable` on the tool that needed the model; free tools unaffected.

    U020 wires the real `read` behind this mapping; what is asserted here is that the mapping
    exists and that it does not take the free surface down with it. A corpus you can still search
    while the vision model is down is most of the value of having a text index at all.
    """
    _register(served, "read", _raises(failure), spends=False)

    paid = served.post("/tools/read", json={"page_ids": ["SYN-M1@1.0#p001"]}, headers=_headers())
    free = served.post(LOOKUP, headers=_headers(),
                       json={"label": corpus.expected["compact_labels"][0]["label"]})

    assert paid.status_code == 503, paid.text
    assert paid.json()["error"] == "vlm_unavailable"
    assert paid.json()["cause"] == failure.code
    assert free.status_code == 200
    assert free.json()["status"] == "ok"


def test_a_model_that_answered_unusably_is_a_502_under_its_own_code(served):
    """Distinct from an outage: the provider is up and its answer cannot be used.

    An operator retries these differently — one waits, the other bisects — so collapsing them
    into one status would make the runbook guess.
    """
    _register(served, "read", _raises(VlmSchemaInvalid("the response is not a WindowOut")))

    response = served.post("/tools/read", json={"page_ids": ["x"]}, headers=_headers())

    assert response.status_code == 502
    assert response.json()["error"] == "vlm_schema_invalid"


def test_a_bug_in_a_tool_is_a_500_naming_only_the_exception_type(served):
    """Not swallowed into an empty result, and not leaking a message that could carry a URL."""
    _register(served, "read", _raises(ZeroDivisionError("division by zero at /srv/secret")))

    response = served.post("/tools/read", json={"page_ids": ["x"]}, headers=_headers())

    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert "ZeroDivisionError" in response.json()["detail"]
    assert "/srv/secret" not in response.text


# ── row 7 · the per-caller read quota ────────────────────────────────────────────────────────────

def test_read_quota_exhausted_429(qdrant):
    """§7.3, §11.3 row 7 — `429 budget_exhausted`, **not** a silent truncation.

    The refusal comes *before* the tool runs: the money is spent inside it, so a caller at the
    ceiling must be refused rather than billed for a call whose answer is then discarded.
    """
    with app_with(qdrant, VSIR_READ_QUOTA="2") as client:
        _register(client, "read", _answers, spends=True)
        first = client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
        second = client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
        third = client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())

    assert first.status_code == 200 and first.json()["reads_remaining"] == 1
    assert second.status_code == 200 and second.json()["reads_remaining"] == 0
    assert third.status_code == 429, third.text
    assert third.json()["error"] == "budget_exhausted"
    assert third.json()["reads_remaining"] == 0
    assert third.json()["quota"] == 2


def test_a_free_tool_is_still_answered_when_the_quota_is_gone(qdrant, corpus):
    """The quota is on `read`. A caller out of reads can still search, which is the point."""
    with app_with(qdrant, VSIR_READ_QUOTA="1") as client:
        _register(client, "read", _answers, spends=True)
        client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
        exhausted = client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
        free = client.post(LOOKUP, headers=_headers(),
                           json={"label": corpus.expected["compact_labels"][0]["label"]})

    assert exhausted.status_code == 429
    assert free.status_code == 200
    assert free.json()["reads_remaining"] == 0


def test_the_quota_is_per_caller_and_not_per_process(qdrant):
    """One caller's spend does not consume another's, and the ledger is keyed by identity."""
    second = "u014-a-second-local-test-credential"
    with app_with(qdrant, VSIR_READ_QUOTA="1",
                  VSIR_API_TOKENS=f"{TEST_TOKEN},{second}") as client:
        _register(client, "read", _answers, spends=True)
        client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
        mine = client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
        theirs = client.post("/tools/read", json={"page_ids": ["a"]},
                             headers={"Authorization": f"Bearer {second}"})

    assert mine.status_code == 429
    assert theirs.status_code == 200, theirs.text


def test_the_ledger_survives_the_process_that_wrote_it(qdrant):
    """§15 Factor VI — the quota is in `vsir_runs`, so N replicas enforce one ceiling.

    A counter in process memory would be N counters that each forget on deploy: three replicas
    would turn a quota of two into six, and a rolling restart into no quota at all. Two apps in
    sequence is the cheapest way to assert the property a second replica would need.
    """
    try:
        with TestClient(create_app(serve_env(VSIR_READ_QUOTA="2"))) as first:
            _register(first, "read", _answers, spends=True)
            spent = first.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())

        with TestClient(create_app(serve_env(VSIR_READ_QUOTA="2"))) as second:
            _register(second, "read", _answers, spends=True)
            after = second.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
            refused = second.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())
    finally:
        if qdrant.collection_exists(SERVED_RUNS):
            qdrant.delete_collection(SERVED_RUNS)

    assert spent.json()["reads_remaining"] == 1
    assert after.json()["reads_remaining"] == 0, "the second process saw the first one's spend"
    assert refused.status_code == 429


def test_the_ledger_records_the_caller_by_digest_and_never_the_token(qdrant):
    """§15.1 — the durable record of who spent what holds no credential."""
    with app_with(qdrant, VSIR_READ_QUOTA="3") as client:
        _register(client, "read", _answers, spends=True)
        client.post("/tools/read", json={"page_ids": ["a"]}, headers=_headers())

        ledger = budget_module.load(qdrant, SERVED_RUNS,
                                    user_id=auth_module.caller_id(TEST_TOKEN))
        assert ledger.spent == 1
        assert ledger.user_id.startswith(auth_module.CALLER_PREFIX)
        assert TEST_TOKEN not in str(ledger.model_dump())


# ── row 6 · a document whose `grounded_rate` collapses ───────────────────────────────────────────

def test_collapsed_grounded_rate_sets_untrusted(qdrant, served, served_collection, corpus):
    """§11.3 row 6, all three clauses, over the corpus's own untrusted page.

    ``text_trust: untrusted`` is §5.7's verdict on a text layer nobody should be told is evidence.
    It counts as unsearchable for `lookup` — so a phrase that *does* occur in the garbled
    extraction is never returned as a verified hit — and `verify` answers `unverifiable` rather
    than `absent`, because telling an agent *"that code is not on the page"* about a page nobody
    could read converts our blind spot into its confident denial.
    """
    row = corpus.expected["untrusted"]
    page_id, label = row["page_id"], row["label"]

    payloads = verify_module.page_payloads(qdrant, served_collection, [page_id])
    assert payloads[page_id]["text_trust"] == "untrusted"
    assert "untrusted" in UNSEARCHABLE_TRUST

    scoped = served.post(LOOKUP, headers=_headers(),
                         json={"label": label, "scope": row["scope"]})
    assert scoped.status_code == 200
    assert scoped.json()["status"] == row["scoped_status"] == "not_searchable"
    assert scoped.json()["hits"] == []

    unscoped = served.post(LOOKUP, headers=_headers(), json={"label": label})
    assert unscoped.json()["status"] == row["unscoped_status"]

    # `verify` over HTTP is U015's wrapper; the verdict it will wrap is this one, unchanged.
    verdict = verify_module.verify_claims(qdrant, served_collection, [label], [page_id])
    assert verdict.claims[label].status == "unverifiable"


def test_a_page_with_no_text_layer_is_not_searchable_rather_than_not_found(served, corpus):
    """F4 — *"that part doesn't exist"* about a scanned page is the answer that must not happen."""
    row = corpus.expected["no_text"]

    response = served.post(LOOKUP, headers=_headers(),
                           json={"label": row["label"], "scope": row["scope"]})

    assert response.json()["status"] == "not_searchable"
    assert response.json()["scope_stats"]["pages_no_text"] >= 1


# ── the typed 400s reach the caller through the transport unchanged (§7.3, F18) ──────────────────

def test_an_unknown_scope_key_is_a_typed_400_naming_the_key(served):
    """I6, F10 — a filter outside `INDEXED` is refused, never degraded to an unindexed scan."""
    response = served.post(LOOKUP, headers=_headers(),
                           json={"label": "K158", "scope": {"bogus": 1}})

    assert response.status_code == 400
    assert response.json()["error"] == "filter_unknown_key"
    assert response.json()["keys"] == ["bogus"]


def test_a_cap_below_one_is_a_typed_400_naming_its_bound(served):
    """§7.3's family — a bound is named, never clamped to something the caller did not ask for."""
    response = served.post(LOOKUP, headers=_headers(), json={"label": "K158", "cap": 0})

    assert response.status_code == 400
    assert response.json()["error"] == "cap_out_of_range"
    assert response.json()["minimum"] == 1
