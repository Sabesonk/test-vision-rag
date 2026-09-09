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

from vsir.doctor import BootRefused
from vsir.serve.app import QDRANT_UNAVAILABLE, create_app

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
def live_client():
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
    assert ready.json()["checks"]["qdrant_reachable"] == "ok"


def test_health_stays_green_and_ready_goes_red_when_qdrant_is_unreachable(outage_client):
    """§11.3 row 1 — never an empty result, never a restart loop."""
    health = outage_client.get("/health")
    ready = outage_client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 503
    assert ready.json()["reason"] == QDRANT_UNAVAILABLE
    assert ready.json()["checks"]["qdrant_reachable"] == "fail"


def test_the_readiness_probe_is_free(live_client):
    """§15.1 — no read, no embedding, no vector search beyond a bounded metadata call.

    Asserted on the call shape rather than on a latency number: a probe that scrolled the
    collection would still be fast on an empty one, and catastrophic on 5,505 pages.
    """
    calls: list[str] = []

    class Recorder:
        def __getattr__(self, name: str):
            async def record(*_args, **_kwargs):
                calls.append(name)
                return {}
            return record

    live_client.app.state.qdrant = Recorder()

    assert live_client.get("/ready").status_code == 200
    assert calls == ["info"]


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


def test_the_running_container_serves_both_probes():
    """The image in the test stack, not an in-process app: the same release production runs."""
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200, ready.text
    assert ready.json()["checks"]["qdrant_reachable"] == "ok"
