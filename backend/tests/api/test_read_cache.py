"""L2 — the `read` cache, and the one input on it that F19 is about (§6.3, §7.2.6).

Two claims, and they pull in opposite directions on purpose:

* **the same question about the same pages costs one call.** Re-running an identical `read` must
  not re-bill it — that is what a content-addressed key is *for*, and `impl` had none on this
  path at all.
* **a different question about the same pages costs a second one.** ``read_key`` is
  ``extract_key``'s inputs ‖ the question, so a new question is a **miss** (F19). Leave the
  question off the key and the second question is answered with the first question's answer,
  which is the most quietly wrong thing this service could do: a fluent, well-formed, verified
  answer to something nobody asked.

The spy is the event stream. The stub logs one ``vlm_replay`` per call it actually serves, so a
cache hit is visible as the *absence* of a line rather than as a claim in a response body.

**And the cache is not in this process.** The last two rows build a second app over the same
collections and hit the cache from it, because a dict on the process is N caches for N replicas,
each of which forgets on deploy (§15 Factor VI, §15.2).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest
from conftest import log_events
from fastapi.testclient import TestClient

from vsir.serve.app import create_app
from vsir.vlm import KIND_VLM_CACHE, READ, cache_point_id

REPO = Path(__file__).resolve().parents[3]
EXPECTED = json.loads(
    (REPO / "data/fixtures/synthetic_3window/expected.json").read_text(encoding="utf-8"))
CASES = EXPECTED["read"]["cases"]
FIRST, SECOND = CASES["answer"], CASES["second_question"]


def calls(stream: Any) -> list[str]:
    """The cache keys the model boundary was actually asked for, in order."""
    return [event["cache_key"] for event in log_events(stream)
            if event.get("event") == "vlm_replay"]


def origins(stream: Any) -> list[str]:
    """Which service answered each `read`: ``replay`` (the boundary) or ``cache`` (§6.9, D10)."""
    return [event["origin"] for event in log_events(stream) if event.get("event") == "read"]


def audits(stream: Any) -> list[dict]:
    return [event["audit"] for event in log_events(stream)
            if event.get("event") == "audit" and event["audit"]["tool"] == "read"]


class Reader:
    """One instance, and the two things a cache row asks of it."""

    def __init__(self, client: Any, env: dict, pages: Any) -> None:
        self.client = client
        self.env = env
        self._pages = pages

    def page_ids(self, *page_nos: int) -> list[str]:
        return self._pages.page_ids(*page_nos)

    def read(self, page_ids: Any, question: str) -> Any:
        return self.client.post("/tools/read", headers=self._pages.header,
                                json={"page_ids": list(page_ids), "question": question})


@pytest.fixture
def caching(qdrant: Any, rastered: Any) -> Iterator[Reader]:
    """The ingested corpus, read through an instance whose **cache starts empty**.

    Its own ``vsir_runs``, function-scoped, because every row here counts model calls: a cache
    shared with the suite that ran before would make *"the first call was a call"* depend on
    test order, and a green run would then be evidence about the order rather than about the key.
    """
    runs = f"{rastered.env['VSIR_RUNS_COLLECTION']}_cache"
    env = {**rastered.env, "VSIR_RUNS_COLLECTION": runs}
    if qdrant.collection_exists(runs):
        qdrant.delete_collection(runs)
    with TestClient(create_app(env)) as client:
        try:
            yield Reader(client, env, rastered)
        finally:
            if qdrant.collection_exists(runs):
                qdrant.delete_collection(runs)


@pytest.fixture
def cold(caching: Reader) -> Iterator[Reader]:
    """A second instance over the **same** collections — another replica, the same durable cache.

    Its own :class:`TestClient` and its own lifespan, so nothing in memory is shared with the
    instance that filled the cache. That is the whole point: this stands in for the replica that
    was not the one the caller reached the first time.
    """
    with TestClient(create_app(caching.env)) as client:
        yield Reader(client, caching.env, caching._pages)


# ── an identical call costs one model call (§6.3) ──────────────────────────────────────────────

def test_two_identical_reads_make_one_call(caching: Reader, log_stream: Any):
    """The call-count spy of U020's acceptance list. Re-running a read must not re-bill it."""
    pages = caching.page_ids(*FIRST["pages"])
    first = caching.read(pages, FIRST["question"])
    second = caching.read(pages, FIRST["question"])

    assert (first.status_code, second.status_code) == (200, 200), second.text
    assert calls(log_stream) == [FIRST["cache_key"]], "the second call was served from the cache"
    assert origins(log_stream) == ["replay", "cache"]


def test_the_cached_answer_is_the_same_answer(caching: Reader):
    """Byte-identical, stamps and all. A cache that returned *nearly* the same thing would be a
    second extractor with its own opinions in the path the answer gate trusts (I8)."""
    pages = caching.page_ids(*FIRST["pages"])
    first = caching.read(pages, FIRST["question"]).json()
    second = caching.read(pages, FIRST["question"]).json()

    assert first["result"] == second["result"]


def test_the_audit_line_says_which_call_cost_nothing(caching: Reader, log_stream: Any):
    """§7.4 — ``cache_hit`` is the field that distinguishes a read that spent from one that did not.

    It is in the audit log and not in the response body, deliberately: the operator's question
    (*"did the cache save this?"*) and the agent's (*"how many reads have I left?"*) are
    different questions and get different channels.
    """
    pages = caching.page_ids(*FIRST["pages"])
    caching.read(pages, FIRST["question"])
    caching.read(pages, FIRST["question"])

    lines = audits(log_stream)[-2:]

    assert [line["cache_hit"] for line in lines] == [False, True]
    # And the token columns are zero on the hit. Found by running the demo against a real model:
    # in replay both lines are zero anyway, so only a live call could show that the cached entry's
    # usage was being reported again — and an operator summing `input_tokens` over a month would
    # have billed every re-read at the price of the read it replaced.
    assert (lines[1]["input_tokens"], lines[1]["output_tokens"]) == (0, 0)


def test_a_cache_hit_still_charges_the_quota(caching: Reader):
    """The quota is a **ceiling on reads**, charged before the tool runs (§7.3).

    It cannot be otherwise: whether a call will hit the cache is not knowable until the pages are
    resolved and rendered, and a budget that were charged afterwards would already have paid for
    the call it then refuses. The saving is real and it is recorded where cost belongs — the
    audit line above — rather than by making the ceiling depend on the cache.
    """
    pages = caching.page_ids(*FIRST["pages"])
    first = caching.read(pages, FIRST["question"]).json()["reads_remaining"]
    second = caching.read(pages, FIRST["question"]).json()["reads_remaining"]

    assert second == first - 1


# ── F19: a new question is a miss ──────────────────────────────────────────────────────────────

def test_a_new_question_about_the_same_pages_makes_a_second_call(caching: Reader,
                                                                 log_stream: Any):
    """F19, over HTTP, on the same two pages — the row the failure catalogue names.

    The two questions differ and nothing else does: the same document, the same pages, the same
    order, the same dpi, the same model and the same prompt version. So the *only* thing that can
    make this a second call is the question being on the key.
    """
    pages = caching.page_ids(*FIRST["pages"])
    assert FIRST["pages"] == SECOND["pages"]

    first = caching.read(pages, FIRST["question"])
    second = caching.read(pages, SECOND["question"])

    assert (first.status_code, second.status_code) == (200, 200), second.text
    assert calls(log_stream) == [FIRST["cache_key"], SECOND["cache_key"]]
    assert first.json()["result"]["extract"] != second.json()["result"]["extract"]


def test_the_second_question_gets_its_own_answer_and_its_own_stamps(caching: Reader):
    """The consequence F19 protects: the wrong answer here would be a *plausible* one."""
    pages = caching.page_ids(*SECOND["pages"])
    payload = caching.read(pages, SECOND["question"]).json()

    assert payload["result"]["extract"] == SECOND["extract"]
    assert [code["raw"] for code in payload["result"]["codes"]] == SECOND["codes"]
    assert {code["status"] for code in payload["result"]["codes"]} == {"present"}


def test_a_different_page_set_is_also_a_miss(caching: Reader, log_stream: Any):
    """The other half of the key: the pixels. Same question, different pages, different receipt."""
    caching.read(caching.page_ids(*FIRST["pages"]), FIRST["question"])
    caching.read(caching.page_ids(*CASES["scanned"]["pages"]), FIRST["question"])

    assert calls(log_stream) == [FIRST["cache_key"], CASES["scanned"]["cache_key"]]


# ── where the cache lives: the control plane, not the process (D9, §15 Factor VI) ──────────────

def test_the_entry_is_a_control_point_in_vsir_runs(caching: Reader, qdrant: Any):
    """One point, addressed by a derived id, beside the run records and the budget ledger.

    Not the instance's filesystem and not its memory (§15.2). The body is kept **verbatim** —
    the receipt, not our summary of it — so a change to how a response is parsed or stamped costs
    nothing to make.
    """
    caching.read(caching.page_ids(*FIRST["pages"]), FIRST["question"])
    point_id = cache_point_id(READ, FIRST["cache_key"])
    runs = caching.env["VSIR_RUNS_COLLECTION"]

    found = qdrant.retrieve(runs, ids=[point_id], with_payload=True)

    assert found, f"no {KIND_VLM_CACHE} point at {point_id} in {runs}"
    payload = found[0].payload
    assert payload["kind"] == KIND_VLM_CACHE
    assert payload["cache_key"] == FIRST["cache_key"]
    assert json.loads(payload["body"])["extract"] == FIRST["extract"]
    assert payload["vlm_model"] == caching.env["VSIR_VLM_MODEL"]


def test_a_second_instance_hits_the_cache_the_first_one_filled(caching: Reader, cold: Reader,
                                                               log_stream: Any):
    """The row that makes the cache worth having in a service that scales horizontally.

    A counter in a dict is N counters for N replicas and it forgets on every deploy — so the
    second identical `read` after a rolling restart would bill again, and a cache that only
    sometimes saves money is one nobody can plan against (§15 Factor VI/VIII).
    """
    pages = caching.page_ids(*FIRST["pages"])
    assert caching.read(pages, FIRST["question"]).status_code == 200

    response = cold.read(pages, FIRST["question"])

    assert response.status_code == 200, response.text
    assert calls(log_stream) == [FIRST["cache_key"]], "the cold instance made no call of its own"
    assert response.json()["result"]["extract"] == FIRST["extract"]
