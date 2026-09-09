"""L2 — the liveness and readiness probes against a real Qdrant (Spec §15.1).

Requires the test stack: `bash scripts/test-api.sh` publishes Qdrant on 6335 and the backend on
8001. No model is reachable from this layer — the stack runs `VSIR_VLM=stub` with
`VSIR_ALLOW_PAID=0`.

The property under test is the one that keeps a backing-service outage from becoming a fleet-wide
restart loop: **`/health` stays green while Qdrant is down, and `/ready` goes red naming why.**
"""
from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from vsir.core.indexed import TEXT_INDEX_PARAMS
from vsir.doctor import INDEX_NOT_READY, QDRANT_UNAVAILABLE, BootRefused
from vsir.serve.app import create_app

QDRANT_URL = os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")
BASE_URL = os.environ.get("VSIR_TEST_BASE_URL", "http://localhost:8001")
UNREACHABLE_URL = "http://127.0.0.1:6399"  # nothing listens here, and nothing may start to

BASE_ENV = {
    "VSIR_PORT": "8000",
    "VSIR_COLLECTION": "vsir_pages",
    "VSIR_VLM": "stub",
    "VSIR_VLM_MODEL": "gemini-3.8-flash-001",
    "VSIR_EMBED_MODEL": "gemini-embedding-2",
    "VSIR_PROMPT_VERSION": "s2-v1",
    "VSIR_API_TOKENS": "probe-only-not-a-secret",
    "VSIR_READ_QUOTA": "10",
    "VSIR_ALLOW_PAID": "0",
    "VSIR_LOG_LEVEL": "INFO",
    "VSIR_RELEASE_ID": "test",
}


def _env(qdrant_url: str) -> dict[str, str]:
    return {**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url}


@pytest.fixture
def live_client(pages_collection):
    """An instance whose Qdrant is up **and** whose collection exists — the ready state."""
    with TestClient(create_app(_env(QDRANT_URL))) as client:
        yield client


@pytest.fixture
def outage_client():
    """An instance whose Qdrant is unreachable — the same code, a broken backing service."""
    with TestClient(create_app(_env(UNREACHABLE_URL))) as client:
        yield client


def test_health_and_ready_are_both_green_when_qdrant_is_up(live_client):
    health = live_client.get("/health")
    ready = live_client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["reason"] is None
    assert ready.json()["checks"]["collection_schema"] == "ok"


def test_health_stays_green_and_ready_goes_red_when_qdrant_is_unreachable(outage_client):
    """§11.3 row 1 — never an empty result, never a restart loop."""
    health = outage_client.get("/health")
    ready = outage_client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 503
    assert ready.json()["reason"] == QDRANT_UNAVAILABLE
    assert ready.json()["checks"]["collection_schema"] == "unavailable"


def test_ready_goes_red_when_the_pinned_index_is_absent(pages_collection):
    """§15.1's third clause — an instance with no index must not join the load balancer.

    Qdrant is up and the boot checks are green; only the collection is missing. That is `not_ready`
    with its own reason, and it is deliberately *not* a boot refusal: a fresh deployment waiting
    for its first ingest is unready, not misconfigured.
    """
    env = {**_env(QDRANT_URL), "VSIR_COLLECTION": "vsir_pages_never_created"}

    with TestClient(create_app(env)) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["reason"] == INDEX_NOT_READY
    assert ready.json()["checks"]["collection_schema"] == "unavailable"


def test_ready_goes_red_when_the_schema_drifts_under_a_running_instance(qdrant, pages_collection):
    """I6, F10 — a dropped payload index turns the instance red, mid-flight.

    The checks are re-run per probe rather than cached from start-up, which is the only way this
    can be caught: the instance booted green, and somebody dropped an index underneath it. A
    quietly narrower answer is the alternative.
    """
    with TestClient(create_app(_env(QDRANT_URL))) as client:
        assert client.get("/ready").status_code == 200

        qdrant.delete_payload_index(pages_collection, field_name="text")
        try:
            ready = client.get("/ready")
            health = client.get("/health")
        finally:
            qdrant.create_payload_index(pages_collection, field_name="text",
                                        field_schema=TEXT_INDEX_PARAMS)

    assert health.status_code == 200, "liveness never depends on the index"
    assert ready.status_code == 503
    assert ready.json()["checks"]["collection_schema"] == "fail"
    assert ready.json()["reason"] == "boot_check_failed"


def test_the_app_refuses_to_start_when_the_live_schema_has_drifted(qdrant, pages_collection):
    """§4.3 — the M0 acceptance claim: a missing payload index is refused, by name.

    Not readiness here but a **boot refusal**: an existing collection that disagrees with
    `INDEXED` is wrong, not merely absent, so the process exits rather than serving from it.
    """
    qdrant.delete_payload_index(pages_collection, field_name="text")
    try:
        with pytest.raises(BootRefused) as refused:
            create_app(_env(QDRANT_URL))
    finally:
        qdrant.create_payload_index(pages_collection, field_name="text",
                                    field_schema=TEXT_INDEX_PARAMS)

    assert refused.value.failed_checks == ["collection_schema"]
    assert "text" in str(refused.value)


def test_the_readiness_probe_is_free(live_client):
    """§15.1 — no read, no embedding, no vector search beyond a bounded metadata call.

    Asserted on the call shape rather than on a latency number: a probe that scrolled the
    collection would still be fast on an empty one, and catastrophic on 5,505 pages.
    """
    calls: list[str] = []

    class Recorder:
        """Sync, like the client the checks share with the CLI."""

        def __getattr__(self, name: str):
            def record(*_args, **_kwargs):
                calls.append(name)
                return True
            return record

    live_client.app.state.qdrant = Recorder()

    live_client.get("/ready")

    # Metadata only. A probe that scrolled the collection would still be fast on an empty one and
    # catastrophic on 5,505 pages, so the assertion is on the call shape, not on a latency number.
    assert calls, "the readiness probe must actually ask Qdrant something"
    assert set(calls) <= {"collection_exists", "get_collection"}


def test_every_probe_response_carries_the_release(live_client):
    """§15 Factor V — an answer, and a probe, trace to the exact code and config behind them."""
    assert live_client.get("/health").json()["release_id"] == "test"
    assert live_client.get("/ready").json()["release_id"] == "test"


def test_the_probes_need_no_bearer_token(live_client):
    """§7.4 — both probes are unauthenticated: an orchestrator holds no token."""
    assert live_client.get("/health", headers={}).status_code == 200
    assert live_client.get("/ready", headers={}).status_code == 200


def test_the_app_refuses_to_start_on_a_floating_model_alias():
    """§4.3, F11 — the refusal happens before a port is bound: no partial service."""
    with pytest.raises(BootRefused) as refused:
        create_app({**_env(QDRANT_URL), "VSIR_VLM_MODEL": "gemini-pro-latest"})

    assert refused.value.failed_checks == ["model_ids_pinned"]
    assert "-latest" in str(refused.value)


def test_the_app_refuses_to_start_on_a_missing_variable():
    env = {key: value for key, value in _env(QDRANT_URL).items() if key != "VSIR_RELEASE_ID"}

    with pytest.raises(BootRefused) as refused:
        create_app(env)

    assert "VSIR_RELEASE_ID" in str(refused.value)


def test_the_running_container_serves_both_probes(pages_collection):
    """The image in the test stack, not an in-process app: the same release production runs."""
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200, ready.text
    assert ready.json()["checks"]["collection_schema"] == "ok"
