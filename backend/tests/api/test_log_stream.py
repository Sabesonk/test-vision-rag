"""L2 — the served process's stdout is **one JSON object per line** (Spec §15 Factor XI).

This is the regression guard for a defect that came back once already. uvicorn installs its own
plain-text handlers, so without `logging.capture_stdlib_loggers()` roughly half of what the
platform collects is not an event: ``INFO:  127.0.0.1 - "GET /health HTTP/1.1" 200 OK``. Nothing in
the source says "keep your handlers", so a uvicorn bump or a newly imported library reinstates it
silently — which is exactly the kind of quiet regression a test has to hold.

It runs against the **container** in the test stack, because that is the stream a platform reads:
an in-process assertion would prove something about a logger, not about the process.
"""
from __future__ import annotations

import json
import subprocess

import httpx
import pytest

COMPOSE_FILE = "docker-compose.test.yml"
SERVICE = "backend-test"


def _container_stdout(repo_root: str) -> list[str]:
    result = subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, "logs", "--no-log-prefix", SERVICE],
        capture_output=True, text=True, check=True, cwd=repo_root,
    )
    return [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]


@pytest.fixture(scope="module")
def exercised_stream(repo_root, base_url) -> list[str]:
    """Make the server do the things that historically logged in plain text, then read its stream."""
    with httpx.Client(base_url=base_url, timeout=10) as client:
        client.get("/health")
        client.get("/ready")
        client.get("/does-not-exist")          # a 404 — an access-log line
        client.post("/health")                 # a 405 — another
    return _container_stdout(repo_root)


def test_every_line_the_container_writes_is_json(exercised_stream):
    offenders: list[str] = []
    for line in exercised_stream:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            offenders.append(line)

    assert not offenders, f"{len(offenders)} non-JSON line(s) on the stream: {offenders[:5]}"


def test_every_line_carries_the_release_and_a_level(exercised_stream):
    """The two keys a collector correlates on (§15 Factor XI)."""
    for line in exercised_stream:
        event = json.loads(line)
        assert event["release_id"] == "test", event
        assert event["level"] in {"debug", "info", "warning", "error", "critical"}, event


def test_the_access_log_is_on_the_stream_rather_than_dropped(exercised_stream):
    """Folding uvicorn's loggers in must not mean silencing them."""
    events = [json.loads(line)["event"] for line in exercised_stream]

    assert any("GET /health" in event for event in events), "no access-log line found"
    assert any("does-not-exist" in event for event in events), "the 404 was not logged"


def test_the_startup_line_is_an_event_too(exercised_stream):
    loggers = {json.loads(line)["logger"] for line in exercised_stream}

    assert "vsir.serve.app" in loggers
    assert any(logger.startswith("uvicorn") for logger in loggers), (
        "uvicorn's own records are not reaching the JSON formatter"
    )


def test_no_credential_appears_on_the_stream(exercised_stream):
    """§15.1 — the API tokens never appear in a log line, and the test stack has one configured."""
    for line in exercised_stream:
        assert "test-only-not-a-secret" not in line
