"""L2 — the bounds in front of the money, and the outage that must not look like an answer.

F18's `read` half (§7.3) and §11.3's two `read` rows, over the served tool. Every row here is a
**refusal**, and each one is asserted twice: the code and the bound it names, and then the thing
that must not have happened — no model call, no quota spent, no truncated page list.

The second assertion is the one that matters. A `read` silently trimmed from four pages to three
answers a question about pages the caller did not ask about **and reports success**, and a quota
charged for a request that was then rejected bills a caller for an error message. `impl` had
neither bound: no auth, no quota, and `max_read_pages: 4` enforced by returning a JSON body with
an ``error`` key and HTTP 200 (register **E5**).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest
from conftest import log_events
from fastapi.testclient import TestClient

from vsir.serve.app import create_app

REPO = Path(__file__).resolve().parents[3]
EXPECTED = json.loads(
    (REPO / "data/fixtures/synthetic_3window/expected.json").read_text(encoding="utf-8"))
CASE = EXPECTED["read"]["cases"]["answer"]
QUESTION = CASE["question"]


def vlm_calls(stream: Any) -> int:
    """How many times the model boundary was actually reached — the call-count spy of U020's ACs.

    The stub logs one ``vlm_replay`` per call it serves, so this counts *calls*, not cache hits
    and not HTTP requests. A refusal that still reached the boundary would show up here even
    though the caller saw a `400`.
    """
    return sum(1 for event in log_events(stream) if event.get("event") == "vlm_replay")


def remaining(rastered: Any) -> int:
    """The caller's `reads_remaining`, read off a **free** tool so asking cannot change it."""
    response = rastered.fetch(rastered.page_ids(19), include=["text"])
    assert response.status_code == 200, response.text
    return response.json()["reads_remaining"]


# ── the page cap (F18, §7.3) ────────────────────────────────────────────────────────────────────

def test_three_pages_are_within_the_bound(rastered: Any):
    """The bound is three, and three is fine — the refusal below is about four (§2.4)."""
    response = rastered.read(rastered.page_ids(19, 20), QUESTION)

    assert response.status_code == 200, response.text


def test_a_fourth_page_is_a_typed_400_naming_its_bound(rastered: Any, log_stream: Any):
    """Never a clamp and never a truncated page list — and never a model call (F18)."""
    before = vlm_calls(log_stream)
    response = rastered.read(rastered.page_ids(19, 20, 21, 22), QUESTION)

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "read_page_cap_exceeded"
    assert (payload["limit"], payload["requested"]) == (3, 4)
    assert vlm_calls(log_stream) == before, "a refused call must not reach the model"


def test_the_page_cap_does_not_cost_the_caller_a_read(rastered: Any):
    """The reason `precheck` runs before the charge: a bound is not a reason to bill (§7.3).

    The quota is charged before the tool runs, because the money is spent inside it — so a bound
    that could be settled from the request alone has to be settled *before* that, or a caller
    that mistyped a page list pays for the error message.
    """
    before = remaining(rastered)
    assert rastered.read(rastered.page_ids(19, 20, 21, 22), QUESTION).status_code == 400

    assert remaining(rastered) == before


def test_one_page_named_twice_is_one_page(rastered: Any):
    """§7.3 bounds *pages*. Four ids over two pages is two pages rendered and one question asked."""
    pages = rastered.page_ids(19, 20, 19, 20)
    response = rastered.read(pages, QUESTION)

    assert response.status_code == 200, response.text
    assert [page["page_id"] for page in response.json()["result"]["page_provenance"]] == \
        rastered.page_ids(19, 20)


# ── the request itself ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body, code", [
    ({"page_ids": [], "question": QUESTION}, "read_empty"),
    ({"page_ids": ["x"], "question": "   "}, "read_question_missing"),
])
def test_a_malformed_read_is_refused_by_name(rastered: Any, body: dict, code: str):
    """A `read` with no pages can only be answered from what the model already believes; a `read`
    with no question is a `fetch`, and `fetch` is free (§7.2.5, §7.2.6)."""
    body = {**body, "page_ids": [rastered.page_id(19)] if body["page_ids"] else []}
    response = rastered.client.post("/tools/read", headers=rastered.header, json=body)

    assert response.status_code == 400
    assert response.json()["error"] == code


def test_a_page_this_corpus_does_not_hold_is_a_404(rastered: Any, log_stream: Any):
    """Resolution refuses before the render and long before the call (§7.1, §11.3)."""
    before = vlm_calls(log_stream)
    response = rastered.read(["NO-SUCH-DOC@1.0#p001"], QUESTION)

    assert response.status_code == 404
    assert response.json()["error"] == "page_not_found"
    assert vlm_calls(log_stream) == before


def test_a_malformed_page_id_is_a_400_and_not_a_404(rastered: Any):
    """A citation this service cannot interpret and a page the corpus does not hold are different
    facts, and a caller retries them differently (§7.2.3)."""
    response = rastered.read(["not-a-page-id"], QUESTION)

    assert response.status_code == 400
    assert response.json()["error"] == "page_id_invalid"


# ── the quota: a refusal, never a truncation (§7.3, §11.3) ─────────────────────────────────────

@pytest.fixture
def penniless(qdrant: Any, rastered: Any) -> Iterator[Any]:
    """The same corpus and the same store, for a caller whose read quota is zero.

    A whole app rather than a monkeypatched ledger: the charge happens in the dispatcher, before
    the tool, and the point of the row is that *that* is where an exhausted caller stops.
    """
    runs = f"{rastered.env['VSIR_RUNS_COLLECTION']}_penniless"
    env = {**rastered.env, "VSIR_READ_QUOTA": "0", "VSIR_RUNS_COLLECTION": runs}
    with TestClient(create_app(env)) as client:
        try:
            yield client
        finally:
            if qdrant.collection_exists(runs):
                qdrant.delete_collection(runs)


def test_an_exhausted_quota_is_a_429_and_spends_nothing(penniless: Any, rastered: Any,
                                                        log_stream: Any):
    """§11.3 — *"`429 budget_exhausted`, not silent truncation"*.

    A `read` trimmed to the pages that fit under a ceiling answers a question about pages the
    caller did not ask about and reports success, which is the failure this row prevents.
    """
    before = vlm_calls(log_stream)
    response = penniless.post(
        "/tools/read", headers=rastered.header,
        json={"page_ids": rastered.page_ids(19, 20), "question": QUESTION})

    assert response.status_code == 429
    payload = response.json()
    assert payload["error"] == "budget_exhausted"
    assert payload["reads_remaining"] == 0
    assert vlm_calls(log_stream) == before, "a caller at the ceiling is refused, never billed"


def test_the_free_tools_are_unaffected_by_an_exhausted_read_quota(penniless: Any, rastered: Any):
    """Only `read` charges. Seven of §7.2's eight are free and stay free at the ceiling (§7.4)."""
    response = penniless.post("/tools/fetch", headers=rastered.header,
                              json={"page_ids": rastered.page_ids(19), "include": ["text"]})

    assert response.status_code == 200, response.text


# ── §11.3: Gemini unreachable → 503 on `read`; every free tool keeps working ────────────────────

@pytest.fixture
def modelless(qdrant: Any, rastered: Any) -> Iterator[Any]:
    """The same corpus, on an instance whose model backend cannot be built.

    Configuration and nothing else (§15 Factor X): `VSIR_VLM=stub` with no ``VSIR_FIXTURE`` is a
    backend with nowhere to read a response from, which is the replay-mode shape of *"the model
    is unreachable"*. No monkeypatch, no test-only branch, no injected failure — the released
    code path, mis-configured on purpose.
    """
    runs = f"{rastered.env['VSIR_RUNS_COLLECTION']}_modelless"
    env = {**rastered.env, "VSIR_RUNS_COLLECTION": runs}
    env.pop("VSIR_FIXTURE", None)
    with TestClient(create_app(env)) as client:
        try:
            yield client
        finally:
            if qdrant.collection_exists(runs):
                qdrant.delete_collection(runs)


def test_an_unreachable_model_makes_read_a_503_and_not_an_empty_answer(modelless: Any,
                                                                      rastered: Any):
    """§11.3's row. An outage reported as *"the pages say nothing"* is a fabricated abstention."""
    response = modelless.post(
        "/tools/read", headers=rastered.header,
        json={"page_ids": rastered.page_ids(19, 20), "question": QUESTION})

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"] == "vlm_unavailable"
    assert payload["retryable"] is True


@pytest.mark.parametrize("tool, arguments", [
    ("lookup", {"label": "K119"}),
    ("verify", {"claims": ["K119"], "page_ids": ["PAGE"]}),
    ("skim_pages", {"query": "guard door interlocks"}),
    ("skim_documents", {"query": "guard door interlocks"}),
    ("skim_sections", {"query": "guard door interlocks"}),
    ("resolve", {"printed_label": "17"}),
    ("fetch", {"page_ids": ["PAGE"], "include": ["text"]}),
])
def test_every_free_tool_still_answers_while_the_model_is_down(modelless: Any, rastered: Any,
                                                               tool: str, arguments: dict):
    """The other half of the row, and the half that is easy to lose: *"every free tool keeps
    working"*. A VLM handle built at boot would have taken all seven down with `read`."""
    arguments = {key: (rastered.page_ids(19) if value == ["PAGE"] else value)
                 for key, value in arguments.items()}
    response = modelless.post(f"/tools/{tool}", headers=rastered.header, json=arguments)

    assert response.status_code == 200, response.text
