"""L0 — the boot self-check of Spec §4.3.

Every test drives ``doctor`` with an explicit environment mapping rather than mutating
``os.environ``: the process's configuration is an input, not a global, and a test that patches the
real environment cannot prove that (§15 Factor III, VI).
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import time

import pytest

from vsir import logging as vsir_logging
from vsir.config import MODEL_ENV, REQUIRED_ENV, InvalidConfig, MissingConfig, load_config
from vsir.doctor import FAIL, OK, doctor, report, run_boot_checks

COMPLETE_ENV = {
    "VSIR_PORT": "8000",
    "VSIR_QDRANT_URL": "http://localhost:6333",
    "VSIR_COLLECTION": "vsir_pages",
    "VSIR_VLM": "stub",
    "VSIR_VLM_MODEL": "gemini-3.8-flash-001",
    "VSIR_EMBED_MODEL": "gemini-embedding-2",
    "VSIR_PROMPT_VERSION": "s2-v1",
    "VSIR_API_TOKENS": "t0,t1",
    "VSIR_READ_QUOTA": "50",
    "VSIR_ALLOW_PAID": "0",
    "VSIR_LOG_LEVEL": "INFO",
    "VSIR_RELEASE_ID": "test-0",
}


@pytest.fixture
def captured_log():
    """Capture the JSON event stream the way a collector sees it: one line at a time."""
    stream = io.StringIO()
    vsir_logging.configure(release_id="test-0", level="DEBUG", stream=stream)
    yield stream
    vsir_logging.configure(release_id="unknown", level="INFO", stream=sys.stdout)


def _lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _statuses(env: dict[str, str]) -> dict[str, str]:
    return {result.name: result.status for result in run_boot_checks(env)}


def test_doctor_passes_on_a_complete_environment(captured_log):
    assert doctor(COMPLETE_ENV) == 0
    assert all(result.status == OK for result in run_boot_checks(COMPLETE_ENV))


def test_doctor_prints_release_model_ids_and_index_fingerprint(captured_log):
    assert doctor(COMPLETE_ENV) == 0

    summary = _lines(captured_log)[-1]
    assert summary["event"] == "doctor_ok"
    assert summary["release_id"] == "test-0"
    assert summary["models"] == {
        "VSIR_VLM_MODEL": "gemini-3.8-flash-001",
        "VSIR_EMBED_MODEL": "gemini-embedding-2",
    }
    # The fingerprint is what a collection is checked against, so all four of its inputs are
    # printed, not just the digest (§6.6).
    assert summary["fingerprint"] == {
        "embed_model": "gemini-embedding-2",
        "dim": 1536,
        "distance": "cosine",
        "composition_version": "d4-fused-v1",
    }
    assert len(summary["fingerprint_id"]) == 16


@pytest.mark.parametrize("var", MODEL_ENV)
def test_doctor_refuses_latest_model_alias(captured_log, var):
    """F11 (boot half) — a floating alias makes an answer untraceable to the model behind it."""
    env = {**COMPLETE_ENV, var: "gemini-pro-latest"}

    assert doctor(env) == 1

    refusal = next(line for line in _lines(captured_log) if line["event"] == "boot_check_failed")
    assert refusal["check"] == "model_ids_pinned"
    assert "-latest" in refusal["detail"]
    assert var in refusal["detail"]
    assert _statuses(env)["model_ids_pinned"] == FAIL


def test_doctor_refuses_a_latest_alias_on_either_model_at_once(captured_log):
    env = {**COMPLETE_ENV, "VSIR_VLM_MODEL": "a-latest", "VSIR_EMBED_MODEL": "b-latest"}

    assert doctor(env) == 1

    refusal = next(line for line in _lines(captured_log) if line["event"] == "boot_check_failed")
    assert sorted(refusal["floating"]) == ["VSIR_EMBED_MODEL", "VSIR_VLM_MODEL"]


def test_a_pinned_id_that_merely_contains_latest_is_accepted():
    """The refusal is on the *suffix*: `-latest` is the alias, `latest-001` is a pinned id."""
    env = {**COMPLETE_ENV, "VSIR_VLM_MODEL": "gemini-latest-001"}

    assert _statuses(env)["model_ids_pinned"] == OK


@pytest.mark.parametrize("var", REQUIRED_ENV)
def test_doctor_refuses_a_missing_required_variable_by_name(captured_log, var):
    env = {key: value for key, value in COMPLETE_ENV.items() if key != var}

    assert doctor(env) == 1

    refusal = next(line for line in _lines(captured_log) if line["event"] == "boot_check_failed")
    assert refusal["check"] == "required_env"
    assert refusal["missing"] == [var]
    assert var in refusal["detail"]


def test_doctor_refuses_a_required_variable_that_is_present_but_blank():
    """An empty value is a missing value: `VSIR_COLLECTION=` must not become a default."""
    assert _statuses({**COMPLETE_ENV, "VSIR_COLLECTION": "   "})["required_env"] == FAIL


def test_the_vlm_key_is_required_only_by_the_gemini_backend():
    """Replay mode has nothing to authenticate to, and CI must be able to run it (D10)."""
    stub = {**COMPLETE_ENV, "VSIR_VLM": "stub"}
    gemini = {**COMPLETE_ENV, "VSIR_VLM": "gemini"}

    assert _statuses(stub)["required_env"] == OK
    assert _statuses(gemini)["required_env"] == FAIL
    assert _statuses({**gemini, "VSIR_VLM_KEY": "k"})["required_env"] == OK


def test_doctor_reports_every_failing_check_not_just_the_first(captured_log):
    """A builder fixing one refusal should see the others in the same run (§4.3)."""
    env = {**COMPLETE_ENV, "VSIR_VLM_MODEL": "x-latest", "VSIR_PORT": "not-a-port"}

    assert doctor(env) == 1

    summary = _lines(captured_log)[-1]
    assert summary["event"] == "doctor_refused"
    assert sorted(summary["failed_checks"]) == ["config_valid", "model_ids_pinned"]


def test_doctor_reports_no_fingerprint_when_the_configuration_is_refused(captured_log):
    """The fingerprint is derived from the configuration: with none, there is none to print."""
    env = {key: value for key, value in COMPLETE_ENV.items() if key != "VSIR_EMBED_MODEL"}

    assert doctor(env) == 1

    facts = report(env)
    assert facts["fingerprint"] is None
    assert facts["models"] is None
    assert facts["release_id"] == "test-0"


def test_every_doctor_log_line_is_json_with_release_id_and_level(captured_log):
    doctor(COMPLETE_ENV)

    raw = [line for line in captured_log.getvalue().splitlines() if line.strip()]
    assert raw, "doctor must report on the event stream"
    for line in raw:
        parsed = json.loads(line)
        assert parsed["release_id"] == "test-0"
        assert parsed["level"] in {"debug", "info", "warning", "error", "critical"}


def test_no_log_line_carries_a_configured_credential(captured_log):
    """§15.1 — the API tokens and the VLM key never appear in a log line."""
    env = {**COMPLETE_ENV, "VSIR_VLM": "gemini", "VSIR_API_TOKENS": "s3cr3t-token",
           "VSIR_VLM_KEY": "s3cr3t-key"}

    doctor(env)

    logged = captured_log.getvalue()
    assert "s3cr3t-token" not in logged
    assert "s3cr3t-key" not in logged


def test_a_credential_in_the_qdrant_url_is_scrubbed(captured_log):
    env = {**COMPLETE_ENV, "VSIR_QDRANT_URL": "http://user:s3cr3t@qdrant:6333"}

    doctor(env)

    logged = captured_log.getvalue()
    assert "s3cr3t" not in logged
    assert "***@qdrant:6333" in logged


# ── the configuration itself ─────────────────────────────────────────────────────────────────────

def test_load_config_names_the_missing_variable():
    env = {key: value for key, value in COMPLETE_ENV.items() if key != "VSIR_QDRANT_URL"}

    with pytest.raises(MissingConfig) as raised:
        load_config(env)

    assert raised.value.var == "VSIR_QDRANT_URL"


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("VSIR_PORT", "0"),
        ("VSIR_PORT", "70000"),
        ("VSIR_PORT", "eight thousand"),
        ("VSIR_VLM", "openai"),
        ("VSIR_ALLOW_PAID", "maybe"),
        ("VSIR_LOG_LEVEL", "CHATTY"),
        ("VSIR_READ_QUOTA", "-1"),
        ("VSIR_EMBED_DIM", "1024"),
        ("VSIR_VLM_TIER", "cheap"),
        ("VSIR_READS_PER_QUESTION", "0"),
        ("VSIR_API_TOKENS", ",,"),
    ],
)
def test_load_config_refuses_an_out_of_range_value(var, value):
    with pytest.raises(InvalidConfig) as raised:
        load_config({**COMPLETE_ENV, var: value})

    assert raised.value.var == var


def test_the_collection_name_carries_the_dimension():
    """Comparing dims is two collections, not two named vectors (§5.5)."""
    cfg = load_config({**COMPLETE_ENV, "VSIR_EMBED_DIM": "3072"})

    assert cfg.pages_collection == "vsir_pages_3072"
    assert cfg.fingerprint["dim"] == 3072


def test_the_fingerprint_changes_with_the_embedding_model_and_the_dimension():
    """A model or dim change is a new collection plus a full re-embed, never an in-place mix."""
    base = load_config(COMPLETE_ENV)
    other_model = load_config({**COMPLETE_ENV, "VSIR_EMBED_MODEL": "gemini-embedding-3"})
    other_dim = load_config({**COMPLETE_ENV, "VSIR_EMBED_DIM": "768"})

    assert len({base.fingerprint_id, other_model.fingerprint_id, other_dim.fingerprint_id}) == 3
    assert load_config(COMPLETE_ENV).fingerprint_id == base.fingerprint_id


def test_the_prompt_version_is_configuration_not_a_literal():
    """Editing a prompt re-bills, so its version is config and an input to extract_key (§6.3)."""
    assert load_config({**COMPLETE_ENV, "VSIR_PROMPT_VERSION": "s2-v2"}).prompt_version == "s2-v2"


def test_replay_mode_is_selected_by_configuration_alone():
    """D10 / Factor X — the stub is chosen by env, never by a code branch or a test-only import."""
    assert load_config(COMPLETE_ENV).replay is False
    assert load_config({**COMPLETE_ENV, "VSIR_FIXTURE": "data/fixtures/x"}).replay is True
    live = load_config({**COMPLETE_ENV, "VSIR_VLM": "gemini", "VSIR_FIXTURE": "data/fixtures/x"})
    assert live.replay is False


def test_the_config_repr_cannot_leak_a_credential():
    cfg = load_config({**COMPLETE_ENV, "VSIR_API_TOKENS": "s3cr3t-token", "VSIR_VLM_KEY": "s3cr3t"})

    assert "s3cr3t" not in repr(cfg)
    assert cfg.api_tokens == ("s3cr3t-token",)


# ── the process (Spec §15 Factor IX) ─────────────────────────────────────────────────────────────

SIGTERM_BOOT = (
    "import time;"
    "from vsir import logging as L;"
    "from vsir.cli import install_sigterm_handler;"
    "L.configure(release_id='test-0', level='INFO');"
    "install_sigterm_handler();"
    "print('{\"event\": \"ready\", \"level\": \"info\", \"release_id\": \"test-0\"}', flush=True);"
    "time.sleep(30)"
)


def test_sigterm_boot_exits_zero_and_leaves_no_orphan():
    """A process must be killable at any instant, cleanly and within the grace period."""
    process = subprocess.Popen(
        [sys.executable, "-c", SIGTERM_BOOT],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None
    assert json.loads(process.stdout.readline())["event"] == "ready"

    started = time.monotonic()
    process.terminate()
    stdout, stderr = process.communicate(timeout=10)
    elapsed = time.monotonic() - started

    assert process.returncode == 0, stderr
    assert elapsed < 10
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert events[-1]["event"] == "sigterm"
    assert events[-1]["action"] == "exit"
    assert process.poll() is not None
