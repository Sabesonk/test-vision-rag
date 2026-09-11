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
from types import SimpleNamespace

import pytest

from vsir import logging as vsir_logging
from vsir.config import MODEL_ENV, REQUIRED_ENV, InvalidConfig, MissingConfig, load_config
from vsir.doctor import (
    FAIL,
    INDEX_NOT_READY,
    OK,
    QDRANT_UNAVAILABLE,
    UNAVAILABLE,
    check_collection_fingerprint,
    check_collection_schema,
    doctor,
    report,
    run_boot_checks,
)

COMPLETE_ENV = {
    "VSIR_PORT": "8000",
    # A closed loopback port: the fast layer stays offline, and the live-collection check is
    # deterministically `unavailable` rather than depending on whether a dev Qdrant happens to be
    # running. Its logic is proved below against a fake client, with no I/O at all.
    "VSIR_QDRANT_URL": "http://127.0.0.1:6399",
    "VSIR_COLLECTION": "vsir_pages",
    "VSIR_VLM": "stub",
    "VSIR_VLM_MODEL": "gemini-3.8-flash",
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
    # INFO, not DEBUG: at DEBUG the HTTP client's own trace lines join the stream and the
    # assertions below would be about httpcore rather than about doctor.
    vsir_logging.configure(release_id="test-0", level="INFO", stream=stream)
    yield stream
    vsir_logging.configure(release_id="unknown", level="INFO", stream=sys.stdout)


def _lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _statuses(env: dict[str, str]) -> dict[str, str]:
    return {result.name: result.status for result in run_boot_checks(env)}


def test_doctor_passes_on_a_complete_environment(captured_log):
    assert doctor(COMPLETE_ENV) == 0
    assert not [result for result in run_boot_checks(COMPLETE_ENV) if result.failed]


def test_an_unreachable_qdrant_does_not_refuse_the_boot(captured_log):
    """§15.1 — refusing on unreachability turns a backing-service outage into a restart loop.

    It is not silence either: the check reports `unavailable` with a reason, and readiness (which
    *is* red on it) is what removes the instance from the load balancer.
    """
    assert doctor(COMPLETE_ENV) == 0

    statuses = _statuses(COMPLETE_ENV)
    assert statuses["collection_schema"] == UNAVAILABLE
    # Both of the checks that read the store, in the order `BOOT_CHECKS` runs them: the fingerprint
    # lives in the control plane, which is the same unreachable Qdrant.
    assert statuses["collection_fingerprint"] == UNAVAILABLE
    summary = next(line for line in _lines(captured_log)
                   if line["event"] == "doctor_inconclusive")
    assert summary["unavailable_checks"] == ["collection_schema", "collection_fingerprint"]
    assert summary["level"] == "warning"


def test_a_run_that_never_reached_the_collection_is_not_greppable_as_a_pass(captured_log):
    """An operator greps `event=doctor_ok` to mean "this release was checked"."""
    assert doctor(COMPLETE_ENV) == 0

    events = {line["event"] for line in _lines(captured_log)}
    assert "doctor_ok" not in events
    assert "doctor_inconclusive" in events


def test_doctor_ok_is_emitted_when_every_check_concluded(captured_log, monkeypatch):
    from vsir import doctor as doctor_module

    store_backed = (doctor_module.check_collection_schema,
                    doctor_module.check_collection_fingerprint)
    monkeypatch.setattr(
        doctor_module, "BOOT_CHECKS",
        tuple(check for check in doctor_module.BOOT_CHECKS if check not in store_backed),
    )

    assert doctor(COMPLETE_ENV) == 0

    summary = _lines(captured_log)[-1]
    assert summary["event"] == "doctor_ok"
    assert summary["unavailable_checks"] == []


def test_doctor_prints_release_model_ids_and_index_fingerprint(captured_log):
    assert doctor(COMPLETE_ENV) == 0

    summary = _lines(captured_log)[-1]
    # No Qdrant in the fast layer, so the run is honestly inconclusive rather than a pass; the
    # facts §13 M0 requires are printed either way.
    assert summary["event"] == "doctor_inconclusive"
    assert summary["release_id"] == "test-0"
    assert summary["models"] == {
        "VSIR_VLM_MODEL": "gemini-3.8-flash",
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


# ── the live-collection check (Spec §4.3 refusals 2 and 4) ──────────────────────────────────────

class FakeClient:
    """A Qdrant stand-in. No I/O, so the check's *logic* is what is under test."""

    def __init__(self, *, exists: bool = True, problems: list[str] | None = None,
                 raises: Exception | None = None) -> None:
        self._exists = exists
        self._problems = problems or []
        self._raises = raises
        self.calls: list[str] = []

    def collection_exists(self, _name: str) -> bool:
        self.calls.append("collection_exists")
        if self._raises is not None:
            raise self._raises
        return self._exists

    def get_collection(self, _name: str):
        self.calls.append("get_collection")
        raise AssertionError("schema_problems is stubbed in these tests")

    def close(self) -> None:
        self.calls.append("close")


def _schema_check(monkeypatch, client: FakeClient) -> object:
    from vsir.core import indexed

    monkeypatch.setattr(indexed, "schema_problems",
                        lambda _c, _n, _d: client._problems)
    return check_collection_schema(COMPLETE_ENV, client)


def test_a_matching_collection_passes(monkeypatch):
    result = _schema_check(monkeypatch, FakeClient(problems=[]))

    assert result.status == OK
    assert result.facts["collection"] == "vsir_pages_1536"


def test_a_drifted_schema_refuses_the_boot(monkeypatch):
    """I6 — a dropped index is a named refusal, not a quietly narrower answer (F10)."""
    client = FakeClient(problems=["payload index missing: 'text' (text)"])

    result = _schema_check(monkeypatch, client)

    assert result.status == FAIL
    assert "text" in result.detail
    assert result.reason is None


def test_a_collection_that_does_not_exist_yet_is_not_ready_rather_than_wrong(monkeypatch):
    """§15.1 — schema *presence* is readiness; schema *drift* is a boot refusal."""
    result = _schema_check(monkeypatch, FakeClient(exists=False))

    assert result.status == UNAVAILABLE
    assert result.reason == INDEX_NOT_READY
    assert "--create-collection" in result.detail


def test_an_unreachable_qdrant_is_reported_as_such(monkeypatch):
    result = _schema_check(monkeypatch, FakeClient(raises=ConnectionError("refused")))

    assert result.status == UNAVAILABLE
    assert result.reason == QDRANT_UNAVAILABLE


def test_the_check_never_closes_a_client_it_was_handed(monkeypatch):
    """A long-lived process hands in its own connection; closing it would break the next probe."""
    client = FakeClient(problems=[])

    _schema_check(monkeypatch, client)

    assert "close" not in client.calls


def test_the_schema_check_makes_no_search_call(monkeypatch):
    """§15.1 — the probe is free: metadata only, no vector search, no scroll."""
    client = FakeClient(problems=[])

    _schema_check(monkeypatch, client)

    assert set(client.calls) <= {"collection_exists", "get_collection"}


def test_a_refused_configuration_leaves_the_schema_unchecked(monkeypatch):
    """There is nothing to check a schema against when the configuration itself is refused."""
    env = {key: value for key, value in COMPLETE_ENV.items() if key != "VSIR_COLLECTION"}

    result = check_collection_schema(env, FakeClient())

    assert result.status == UNAVAILABLE
    assert result.reason == INDEX_NOT_READY


# ── the fingerprint check (Spec §4.3 refusal 3, §6.6, F11) ──────────────────────────────────────

#: What `vsir_runs` holds for a collection this release embedded: §6.6's four fields, plus the
#: discriminator every control-plane point carries (D9).
def _stored(**overrides: object) -> dict[str, object]:
    recipe = dict(load_config(COMPLETE_ENV).fingerprint)
    recipe.update(overrides)
    return {"kind": "fingerprint", "collection": "vsir_pages_1536", **recipe}


class FakeControlPlane:
    """`vsir_runs` with at most one fingerprint point in it. No I/O: the logic is what is tested."""

    def __init__(self, payload: dict[str, object] | None = None, *,
                 exists: bool = True, raises: Exception | None = None) -> None:
        self._payload = payload
        self._exists = exists
        self._raises = raises
        self.calls: list[str] = []

    def collection_exists(self, _name: str) -> bool:
        self.calls.append("collection_exists")
        if self._raises is not None:
            raise self._raises
        return self._exists

    def retrieve(self, _name: str, ids: list[str], with_payload: bool = True) -> list[object]:
        self.calls.append("retrieve")
        if self._payload is None:
            return []
        return [SimpleNamespace(id=ids[0], payload=dict(self._payload))]

    def search(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("a boot check never searches")

    def close(self) -> None:
        self.calls.append("close")


def test_a_collection_embedded_under_this_release_recipe_passes():
    result = check_collection_fingerprint(COMPLETE_ENV, FakeControlPlane(_stored()))

    assert result.status == OK
    assert result.facts["stored_digest"] == result.facts["configured_digest"]


def test_a_collection_embedded_by_another_model_refuses_the_boot():
    """§4.3's third refusal, and the one a write-time guard cannot make.

    `fingerprint.require` protects the *collection* from being mixed. It says nothing about a
    process that only ever reads: that one embeds the query with this release's model and compares
    it against vectors made by another, and the symptom is worse neighbours — no error at all.
    """
    client = FakeControlPlane(_stored(embed_model="gemini-embedding-1"))

    result = check_collection_fingerprint(COMPLETE_ENV, client)

    assert result.status == FAIL
    assert result.reason is None, "a wrong recipe is a refusal, not an unready instance"
    assert "gemini-embedding-1" in result.detail and "gemini-embedding-2" in result.detail
    assert result.facts["differences"]["embed_model"] == ["gemini-embedding-1",
                                                          "gemini-embedding-2"]


def test_a_composition_change_refuses_although_every_model_id_still_matches():
    """The field that is easy to leave out. Reordering the parts of §5.3 changes every vector
    without changing a model id, so a fingerprint without it agrees with a collection it no longer
    describes."""
    result = check_collection_fingerprint(COMPLETE_ENV,
                                          FakeControlPlane(_stored(composition_version="d4-v0")))

    assert result.status == FAIL
    assert "composition_version" in result.detail


def test_a_collection_nobody_has_embedded_into_yet_is_not_a_refusal():
    """§6.6 — the first ingest writes the record, so absence is the pre-ingest state, not drift.
    Refusing here would mean a fresh deployment could never boot far enough to run that ingest."""
    result = check_collection_fingerprint(COMPLETE_ENV, FakeControlPlane(None))

    assert result.status == OK
    assert "first ingest writes it" in result.detail


def test_a_stored_record_that_cannot_say_whether_it_matches_is_drift():
    """A control point missing one of §6.6's four fields is wrong, not absent — it names a recipe
    that cannot be compared, and serving from it would be a guess."""
    incomplete = _stored()
    del incomplete["composition_version"]

    result = check_collection_fingerprint(COMPLETE_ENV, FakeControlPlane(incomplete))

    assert result.status == FAIL
    assert "composition_version" in result.detail


def test_an_unreachable_control_plane_is_inconclusive_rather_than_a_refusal():
    """§15.1 — the same policy as the schema check: an outage is not a fleet-wide restart loop."""
    result = check_collection_fingerprint(COMPLETE_ENV,
                                          FakeControlPlane(raises=ConnectionError("refused")))

    assert result.status == UNAVAILABLE
    assert result.reason == QDRANT_UNAVAILABLE


def test_a_refused_configuration_leaves_the_fingerprint_check_inconclusive():
    """`config_valid` owns that refusal; there is no recipe to compare against a refused config."""
    env = {key: value for key, value in COMPLETE_ENV.items() if key != "VSIR_EMBED_MODEL"}

    result = check_collection_fingerprint(env, FakeControlPlane(_stored()))

    assert result.status == UNAVAILABLE
    assert result.reason == INDEX_NOT_READY


def test_the_fingerprint_check_never_closes_a_client_it_was_handed():
    client = FakeControlPlane(_stored())

    check_collection_fingerprint(COMPLETE_ENV, client)

    assert "close" not in client.calls


def test_the_fingerprint_check_runs_in_the_boot_list():
    """A check nothing calls is not a refusal. This is the wiring, asserted rather than assumed."""
    from vsir import doctor as doctor_module

    assert doctor_module.check_collection_fingerprint in doctor_module.BOOT_CHECKS


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
