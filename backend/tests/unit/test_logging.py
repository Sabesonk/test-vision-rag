"""L0 — the event stream of Spec §15 Factor XI.

Logs are an event stream on stdout: structured JSON, one event per line, every line carrying
``release_id`` and ``level``, with ``run_id`` / ``session_id`` / ``request_id`` / ``tool``
correlating a line back to the call that produced it (§11.4). The app never opens a log file,
never rotates and never ships logs itself (§15.2).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import sys

import pytest

from vsir import logging as vsir_logging


@pytest.fixture
def stream():
    captured = io.StringIO()
    vsir_logging.configure(release_id="rel-42", level="DEBUG", stream=captured)
    yield captured
    vsir_logging.configure(release_id="unknown", level="INFO", stream=sys.stdout)


def _events(captured: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in captured.getvalue().splitlines() if line.strip()]


def test_json_log_line_carries_release_id_and_level(stream):
    log = vsir_logging.get_logger("vsir.test")

    log.info("ingest_window_started", run_id_hint="ignored")
    log.warning("gate_held", gate="grounded_rate")

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert parsed["release_id"] == "rel-42"
        assert parsed["level"] in {"debug", "info", "warning", "error", "critical"}
        assert parsed["logger"] == "vsir.test"
        assert "ts" in parsed and "event" in parsed


def test_json_log_carries_the_caller_fields(stream):
    vsir_logging.get_logger("vsir.test").info("read_billed", pages=2, dpi=220)

    event = _events(stream)[0]
    assert event["event"] == "read_billed"
    assert event["pages"] == 2
    assert event["dpi"] == 220


def test_correlation_ids_ride_along_and_do_not_outlive_the_block(stream):
    log = vsir_logging.get_logger("vsir.test")

    with vsir_logging.correlate(run_id="r-1", request_id="q-1", tool="lookup"):
        log.info("tool_call")
    log.info("after")

    inside, outside = _events(stream)
    assert (inside["run_id"], inside["request_id"], inside["tool"]) == ("r-1", "q-1", "lookup")
    assert not {"run_id", "request_id", "tool"} & set(outside)


def test_correlation_blocks_nest_and_unwind(stream):
    log = vsir_logging.get_logger("vsir.test")

    with vsir_logging.correlate(run_id="r-1"):
        with vsir_logging.correlate(request_id="q-1"):
            log.info("inner")
        log.info("outer")

    inner, outer = _events(stream)
    assert inner["run_id"] == "r-1" and inner["request_id"] == "q-1"
    assert outer["run_id"] == "r-1" and "request_id" not in outer


def test_an_unknown_correlation_id_is_refused():
    """The four ids are the correlation contract; a typo is a broken audit trail, not a field."""
    with pytest.raises(ValueError, match="not a correlation id"):
        with vsir_logging.correlate(session="s-1"):
            pass


def test_correlation_does_not_leak_between_concurrent_tasks(stream):
    """Not a session store (C11): one task's ids are invisible to another's."""
    log = vsir_logging.get_logger("vsir.test")

    async def call(request_id: str) -> None:
        with vsir_logging.correlate(request_id=request_id):
            await asyncio.sleep(0)
            log.info("tool_call")

    async def both() -> None:
        await asyncio.gather(call("q-1"), call("q-2"))

    asyncio.run(both())

    calls = [event for event in _events(stream) if event["event"] == "tool_call"]
    assert sorted(event["request_id"] for event in calls) == ["q-1", "q-2"]
    assert vsir_logging.correlation() == {}


@pytest.mark.parametrize(
    "field",
    ["api_tokens", "token", "vlm_key", "authorization", "bearer", "client_secret", "password"],
)
def test_a_credential_shaped_field_is_redacted(stream, field):
    vsir_logging.get_logger("vsir.test").info("auth", **{field: "s3cr3t"})

    event = _events(stream)[0]
    assert event[field] == vsir_logging.REDACTED
    assert "s3cr3t" not in stream.getvalue()


@pytest.mark.parametrize("field", ["extract_key", "read_key", "embed_key", "point_id", "run_id"])
def test_a_cache_key_is_not_mistaken_for_a_credential(stream, field):
    """The keys of §6.3 are the provenance trail — redacting them would blind the audit log."""
    vsir_logging.get_logger("vsir.test").info("cache_hit", **{field: "abc123"})

    assert _events(stream)[0][field] == "abc123"


def test_a_caller_field_cannot_shadow_an_envelope_key(stream):
    vsir_logging.get_logger("vsir.test").info("real_event", level="fake", release_id="fake")

    event = _events(stream)[0]
    assert event["level"] == "info"
    assert event["release_id"] == "rel-42"


def test_an_exception_is_reported_as_structured_fields(stream):
    log = vsir_logging.get_logger("vsir.test")

    try:
        raise ValueError("qdrant unreachable")
    except ValueError:
        log.exception("backend_failed", backend="qdrant")

    event = _events(stream)[0]
    assert event["level"] == "error"
    assert event["error"]["type"] == "ValueError"
    assert event["error"]["message"] == "qdrant unreachable"
    assert "ValueError" in event["error"]["traceback"]


def test_a_multiline_value_stays_one_event_per_line(stream):
    vsir_logging.get_logger("vsir.test").info("probe", text="line one\nline two line three")

    assert len(stream.getvalue().splitlines()) == 1
    assert _events(stream)[0]["text"] == "line one\nline two line three"


def test_the_level_gates_the_stream(stream):
    vsir_logging.configure(release_id="rel-42", level="WARNING", stream=stream)
    log = vsir_logging.get_logger("vsir.test")

    log.info("quiet")
    log.error("loud")

    assert [event["event"] for event in _events(stream)] == ["loud"]


def test_an_unknown_level_falls_back_to_info_rather_than_raising(stream):
    """The boot self-check reports a bad VSIR_LOG_LEVEL, and it needs a logger to report with."""
    vsir_logging.configure(release_id="rel-42", level="CHATTY", stream=stream)

    vsir_logging.get_logger("vsir.test").info("still_logging")

    assert [event["event"] for event in _events(stream)] == ["still_logging"]


def test_configure_is_idempotent_and_never_duplicates_a_line(stream):
    for _ in range(3):
        vsir_logging.configure(release_id="rel-42", level="DEBUG", stream=stream)

    vsir_logging.get_logger("vsir.test").info("once")

    assert len(stream.getvalue().splitlines()) == 1
    assert len(logging.getLogger().handlers) == 1


def test_the_default_stream_is_stdout_and_no_handler_writes_to_a_file():
    """§15.2 — no app-managed log file, no rotation, no shipping."""
    vsir_logging.configure(release_id="rel-42", level="INFO")

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert handlers[0].stream is sys.stdout
    assert not isinstance(handlers[0], logging.FileHandler)

    vsir_logging.configure(release_id="unknown", level="INFO", stream=sys.stdout)


def test_third_party_logging_is_reformatted_not_bypassed(stream):
    """qdrant-client and httpx log through the root logger; their lines must be JSON too."""
    logging.getLogger("httpx").warning("retrying %s", "upsert")

    event = _events(stream)[0]
    assert event["logger"] == "httpx"
    assert event["event"] == "retrying upsert"
    assert event["release_id"] == "rel-42"
