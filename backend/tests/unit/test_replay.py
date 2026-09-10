"""L0/L1 — replay mode (Spec §3 D10, §12.1, §12.2, §15 Factor IV and X).

Replay is the reason the rest of this suite is free, and it is worth being precise about what it
promises. `VSIR_VLM=stub` plus `VSIR_FIXTURE=<dir>` serves both S2 extraction and `read` from
responses frozen under exactly the cache keys of §6.3. Two things it must never do, because each
one is worse than the error it replaces:

* **it must never make a live call.** A stub that fell back to the model on a miss turns a free CI
  run into a billed one and makes the suite depend on a credential nobody meant to give it — so
  the central test here is a network spy over a *whole* `--until extract` run, asserting zero
  outbound connections;
* **it must never fabricate a response.** A stub that synthesised a plausible `WindowOut` on a miss
  would make every green assertion downstream a statement about data no model ever produced. A miss
  is a typed `fixture_miss`, and it is loud.

And the backend is chosen by **configuration alone** (§15 Factor X, §15.2): one dictionary lookup
on `VSIR_VLM`, both backends imported unconditionally at module scope. A test-only branch would
mean the code under test is not the code that ships, which makes every green test a statement about
something else.
"""
from __future__ import annotations

import ast
import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from vsir import cli
from vsir import vlm
from vsir.config import DPI_ANSWER, VLM_BACKENDS, load_config
from vsir.eval import synthetic_pdf as generator
from vsir.ingest import probe, render
from vsir.ingest import window as w
from vsir.ingest.extract import S2_SCHEMA_HASH, WindowOut
from vsir.vlm import (EXTRACT, FACTS, READ, FixtureMiss, FixtureStore, GeminiBackend, Request,
                      StubBackend, VlmTruncated, VlmUnavailable)

BASE_ENV = {
    "VSIR_PORT": "8000",
    "VSIR_QDRANT_URL": "http://127.0.0.1:6399",
    "VSIR_COLLECTION": "vsir_pages",
    "VSIR_VLM": "stub",
    "VSIR_VLM_MODEL": "gemini-3.8-flash",
    "VSIR_EMBED_MODEL": "gemini-embedding-2",
    "VSIR_PROMPT_VERSION": "s2-v1",
    "VSIR_API_TOKENS": "test-only-not-a-credential",
    "VSIR_READ_QUOTA": "50",
    "VSIR_ALLOW_PAID": "0",
    "VSIR_LOG_LEVEL": "INFO",
    "VSIR_RELEASE_ID": "test-0",
}
MODEL = BASE_ENV["VSIR_VLM_MODEL"]
PROMPT = BASE_ENV["VSIR_PROMPT_VERSION"]
PACKAGE = Path(vlm.__file__).resolve().parent


@pytest.fixture
def env(monkeypatch, synthetic_fixture):
    for name, value in BASE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("VSIR_FIXTURE", str(synthetic_fixture))
    return monkeypatch


@pytest.fixture
def network_spy(monkeypatch):
    """Every outbound connection attempt in the process, recorded and refused.

    Refused as well as recorded on purpose: a test that only counted would let the call *happen*
    on a machine with a credential in its environment, which is the exact accident replay mode
    exists to make impossible (§12.2 — L0-L3 never call Gemini).
    """
    attempts: list[object] = []

    def refuse(*args, **kwargs):
        attempts.append(args[:1] or kwargs)
        raise AssertionError(f"outbound network call in replay mode: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return attempts


def _config(**overrides):
    return load_config({**BASE_ENV, **overrides})


def _request(key: str, namespace: str = EXTRACT, **overrides) -> Request:
    return Request(namespace=namespace, key=key, stage="s2", schema=WindowOut, **overrides)


def _window_key(pdf, window, probed, **overrides) -> str:
    inputs = {"vlm_model": MODEL, "prompt_version": PROMPT, "dpi": DPI_ANSWER,
              "schema_hash": S2_SCHEMA_HASH, **overrides}
    return vlm.extract_key(
        render.page_hashes(pdf, window.page_numbers, dpi=DPI_ANSWER,
                           content_hash=probed.content_hash), **inputs)


# ── the spy is real ────────────────────────────────────────────────────────────────────────────

def test_the_network_spy_would_notice_a_call(network_spy):
    """A "zero outbound calls" assertion is only worth what the spy is worth.

    So the spy gets its own negative control, in the style of the conformance suite's injected
    violation: an attempted connection is recorded *and* refused. Without this, patching the wrong
    symbol would make every assertion below vacuously true — which is the failure mode replay mode
    exists to eliminate, reintroduced one level up.
    """
    with pytest.raises(AssertionError):
        socket.create_connection(("127.0.0.1", 6399))
    with pytest.raises(AssertionError):
        socket.socket().connect(("127.0.0.1", 6399))

    assert len(network_spy) == 2


# ── the backend is a configuration lookup (§15 Factor X) ───────────────────────────────────────

def test_the_backend_is_selected_by_configuration_alone(synthetic_fixture, tmp_path):
    """AC — switching `VSIR_VLM` between `gemini` and `stub` selects the backend through one
    config lookup. Both are built here in one test, from two environments, with no branch."""
    stub = vlm.backend(_config(VSIR_FIXTURE=str(synthetic_fixture)))
    live = vlm.backend(_config(VSIR_VLM="gemini", VSIR_VLM_KEY="not-a-real-credential"))

    assert isinstance(stub, StubBackend) and stub.name == "stub"
    assert isinstance(live, GeminiBackend) and live.name == "gemini"
    assert set(vlm.BACKENDS) == set(VLM_BACKENDS)
    assert isinstance(stub, vlm.Backend) and isinstance(live, vlm.Backend)


def test_both_backends_are_imported_unconditionally_at_module_scope():
    """§15.2 — no conditional import, no import inside a function, no test-only path. The image
    contains both backends and the environment chooses; that is what makes the tested path the
    shipped path."""
    tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    top = {id(node) for node in tree.body}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert id(node) in top, f"line {node.lineno}: an import that is not at module scope"
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.If, ast.Try))
                and any(isinstance(c, (ast.Import, ast.ImportFrom)) for c in ast.walk(n))]


def test_a_backend_name_this_release_does_not_ship_is_named_not_guessed(synthetic_fixture):
    """A bare `KeyError` would name the dictionary; configuration validation names the *variable*.

    Reached by replacing the field rather than by an environment value, because `load_config`
    already refuses an unknown `VSIR_VLM` by name — this is the boundary's own second check, for
    the case where the two lists drift apart in a release (§4.3).
    """
    cfg = replace(_config(VSIR_FIXTURE=str(synthetic_fixture)), vlm="ollama")

    with pytest.raises(vlm.VlmError) as refusal:
        vlm.backend(cfg)

    assert refusal.value.code == "vlm_backend_unavailable"
    assert "VSIR_VLM" in str(refusal.value)
    assert refusal.value.details["available"] == sorted(VLM_BACKENDS)


@pytest.mark.parametrize(("fixture", "detail"), [("", "VSIR_FIXTURE"), ("/nonexistent", "not a")])
def test_the_stub_without_a_fixture_refuses_by_name(fixture, detail):
    """A suite that skipped every fixture-consuming test would be a green run asserting nothing."""
    with pytest.raises(VlmUnavailable) as refusal:
        vlm.backend(_config(VSIR_FIXTURE=fixture))

    assert refusal.value.code == "vlm_backend_unavailable"
    assert detail in str(refusal.value)


def test_the_live_backend_refuses_without_a_credential():
    """§15 Factor III — the credential arrives from the platform secret store at runtime, never
    from the image, so its absence is a refusal rather than an anonymous call."""
    with pytest.raises(VlmUnavailable) as refusal:
        vlm.backend(_config(VSIR_VLM="gemini"))

    assert "VSIR_VLM_KEY" in str(refusal.value)


# ── what replay serves, and what it refuses ────────────────────────────────────────────────────

def test_a_frozen_response_is_served_verbatim(synthetic_fixture, synthetic_pdf, network_spy):
    """The body is the receipt (§6.3): what comes back is the bytes on disk, unreformatted."""
    probed = probe.run(synthetic_pdf)
    window = w.Window(1, 14, 1)
    backend = StubBackend(FixtureStore(synthetic_fixture))

    entry = backend.generate(_request(_window_key(synthetic_pdf, window, probed)))

    assert entry.body == generator.window_body(1, 14)
    assert entry.origin == "replay"
    assert entry.finish_reason == "STOP"
    assert not network_spy


def test_a_key_the_fixture_does_not_hold_is_a_typed_miss(synthetic_fixture, network_spy):
    """AC — never a live call, never a fabricated response. The refusal names the key and the
    directory, so the next attempt can be *different* rather than a retry of the same one."""
    backend = StubBackend(FixtureStore(synthetic_fixture))

    with pytest.raises(FixtureMiss) as refusal:
        backend.generate(_request("f" * 64))

    assert refusal.value.code == "fixture_miss"
    assert refusal.value.details["cache_key"] == "f" * 64
    assert refusal.value.details["namespace"] == EXTRACT
    assert refusal.value.to_payload()["error"] == "fixture_miss"
    assert not network_spy


def test_the_answer_is_selected_by_the_key_and_never_by_the_pixels(synthetic_fixture,
                                                                   synthetic_pdf):
    """The rasters ride along because the *key* was computed from them. A stub that inspected them
    would be a second extractor, with its own opinions, inside the path the tests trust."""
    probed = probe.run(synthetic_pdf)
    key = _window_key(synthetic_pdf, w.Window(1, 14, 1), probed)
    backend = StubBackend(FixtureStore(synthetic_fixture))

    without = backend.generate(_request(key))
    with_other_pixels = backend.generate(_request(key, images=(b"not a png", b"nor this")))

    assert without.body == with_other_pixels.body


def test_a_frozen_truncation_is_replayed_as_a_truncation(tmp_path):
    """F13 — a call the provider cut off at the output ceiling is a truncation on the wire, not a
    parse error, and §6.2's repair is only exercisable if the frozen corpus can express it."""
    vlm.write(tmp_path, EXTRACT, "a" * 64, generator.window_body(1, 4),
              meta={"finish_reason": "MAX_TOKENS", "usage": {"output_tokens": 8192}})
    backend = StubBackend(FixtureStore(tmp_path))

    with pytest.raises(VlmTruncated) as refusal:
        backend.generate(_request("a" * 64))

    assert refusal.value.code == "vlm_truncated"
    assert refusal.value.details["finish_reason"] == "MAX_TOKENS"


def test_the_provenance_sidecar_travels_with_the_response(tmp_path):
    """Register B1 — given a bare `{"pages": [...]}` you cannot tell which model, prompt or page
    range produced it, and once `prompt_version` moves the orphans are unidentifiable."""
    vlm.write(tmp_path, EXTRACT, "b" * 64, '{"pages": []}',
              meta={"finish_reason": "STOP", "usage": {"prompt_tokens": 11, "output_tokens": 22}})

    entry = FixtureStore(tmp_path).get(EXTRACT, "b" * 64)

    assert entry.usage == {"prompt_tokens": 11, "output_tokens": 22}
    assert entry.truncated is False
    assert entry.path.endswith(f"{'b' * 64}.json")


def test_read_replays_by_question_so_a_new_question_is_a_miss(tmp_path):
    """D10 covers `read` as well as S2, and F19's mechanism is visible here: the question is a
    `read_key` input, so the fixture that answers one question misses on the next."""
    hashes = ("a" * 64,)
    asked = "Which relay does the stop category depend on?"
    key = vlm.read_key(hashes, vlm_model=MODEL, prompt_version=PROMPT, dpi=DPI_ANSWER,
                       schema_hash=S2_SCHEMA_HASH, question=asked)
    vlm.write(tmp_path, READ, key, '{"answer": "K122"}')
    backend = StubBackend(FixtureStore(tmp_path))

    assert backend.generate(_request(key, READ)).body == '{"answer": "K122"}'

    other = vlm.read_key(hashes, vlm_model=MODEL, prompt_version=PROMPT, dpi=DPI_ANSWER,
                         schema_hash=S2_SCHEMA_HASH, question="Which contactor is named?")
    with pytest.raises(FixtureMiss):
        backend.generate(_request(other, READ))


# ── the whole run, with a spy on the socket (§12.2) ────────────────────────────────────────────

def test_a_full_until_extract_run_makes_zero_outbound_calls(env, capsys, synthetic_pdf,
                                                            network_spy, expected):
    """AC — with `VSIR_VLM=stub`, a network spy records **zero** outbound HTTP calls across a full
    `--until extract` run. This is the assertion that keeps CI free and credential-less."""
    code = cli.main(["ingest", str(synthetic_pdf), "--until", "extract"])
    out = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "ALL ASSERTIONS PASSED" in out
    assert network_spy == []
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    origins = [event for event in events if event.get("event") == "vlm_replay"]
    assert len(origins) == expected["extraction"]["windows"] + 1  # every window, plus S1
    assert not [event for event in events if event.get("event") == "vlm_call"]


def test_a_miss_mid_run_refuses_without_calling_anything(env, capsys, synthetic_pdf,
                                                         network_spy, synthetic_fixture,
                                                         tmp_path):
    """AC — a cache key absent from `VSIR_FIXTURE` raises typed `fixture_miss`; the spy still
    records zero outbound calls and no response is fabricated.

    Staged where it bites hardest: the S1 response is present, so the run gets as far as step 06
    and *then* finds nothing under the window's `extract_key`. The honest outcome is a non-zero
    exit naming the key — not 42 pages of invented structure.
    """
    facts_key = vlm.facts_key(probe.content_hash(synthetic_pdf), vlm_model=MODEL,
                              prompt_version=PROMPT)
    vlm.write(tmp_path, FACTS, facts_key,
              FixtureStore(synthetic_fixture).get(FACTS, facts_key).body)
    env.setenv("VSIR_FIXTURE", str(tmp_path))

    code = cli.main(["ingest", str(synthetic_pdf), "--until", "extract"])
    out = capsys.readouterr().out

    assert code == cli.EXIT_REFUSED
    assert "REFUSED  fixture_miss" in out
    assert "ALL ASSERTIONS PASSED" not in out
    assert network_spy == []
    assert not list((tmp_path / EXTRACT).glob("*.json")), "replay filled its own cache"


def test_the_prompt_version_moves_the_whole_fixture(env, capsys, synthetic_pdf, network_spy):
    """The unit's demo, second half — and the risk the plan names: a frozen fixture going stale
    relative to a prompt edit. It cannot, because `prompt_version` is on every key: bumping it
    makes the frozen responses unfindable rather than silently wrong (F11)."""
    env.setenv("VSIR_PROMPT_VERSION", "v2")

    code = cli.main(["ingest", str(synthetic_pdf), "--until", "extract"])
    out = capsys.readouterr().out

    assert code == cli.EXIT_REFUSED
    assert "fixture_miss" in out
    assert network_spy == []


def test_replay_needs_no_credential_at_all(env, capsys, synthetic_pdf, network_spy):
    """§12.2 — the fixture-backed path must not be hostage to a secret. CI has no Gemini key and
    is expected to run this suite green (`.github/workflows/ci.yml` references no secret)."""
    env.delenv("VSIR_VLM_KEY", raising=False)

    assert cli.main(["ingest", str(synthetic_pdf), "--until", "extract"]) == cli.EXIT_OK
    assert network_spy == []
