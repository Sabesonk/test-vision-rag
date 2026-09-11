"""L2 — the server refuses to start rather than serve a partial service (Spec §4.3, §11.3).

*"Never degrade to a partial service."* Five conditions make a process wrong rather than merely
unlucky, and each exits non-zero **before a socket is bound**: a model id that floats, a live
payload schema that disagrees with `INDEXED`, a collection embedded under a recipe this release
does not produce (§6.6), a missing required variable, and a configuration value that does not
parse.

**Before the port is bound** is the load-bearing half, and it is why the schema test spawns a real
`vsir serve` rather than only calling the factory. A process that binds and *then* discovers it
cannot answer correctly has already joined the load balancer: readiness would eventually remove
it, but the window between bind and the first probe is a window in which it answers. The exit
code is the contract; the closed port is the property.

Readiness is the other side of the same coin, and it is deliberately *not* a refusal: a Qdrant
that is down, or a collection that has never been ingested into, leaves the process alive and out
of the load balancer (`test_probes.py`). Absent is not wrong. Wrong is wrong.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from vsir.config import load_config
from vsir.core.indexed import TEXT_INDEX_PARAMS
from vsir.doctor import BootRefused
from vsir.ingest import fingerprint
from vsir.serve.app import app_factory, create_app

from conftest import QDRANT_URL, SERVED_COLLECTION, SERVED_RUNS, serve_env

#: A port nothing else in the test stack uses. The point of the subprocess test is that after the
#: refusal, nothing is listening on it.
REFUSAL_PORT = 8099
#: How long the refusing process is given. It does no I/O beyond one Qdrant metadata call.
REFUSAL_TIMEOUT_S = 45


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


# ── the four refusals, at the factory ────────────────────────────────────────────────────────────

def test_boot_refuses_on_schema_drift(qdrant, served_collection):
    """§11.3 — an existing collection that disagrees with `INDEXED` is wrong, not merely absent.

    A missing payload index means a filter on that key would run as an unindexed scan, which is a
    quietly narrower answer (I6, F10). The process refuses instead of serving from it.
    """
    qdrant.delete_payload_index(served_collection, field_name="text")
    try:
        with pytest.raises(BootRefused) as refused:
            create_app(serve_env())
    finally:
        qdrant.create_payload_index(served_collection, field_name="text",
                                    field_schema=TEXT_INDEX_PARAMS)

    assert refused.value.failed_checks == ["collection_schema"]
    assert "text" in str(refused.value)


@pytest.fixture
def isolated_runs(qdrant):
    """A control plane of this test's own, so a fingerprint it writes cannot reach another suite.

    §6.6's record is one point per *pages* collection, and the pages collection here is the shared
    served one — so the isolation has to be the `vsir_runs` side.
    """
    name = f"{SERVED_RUNS}_fingerprint_check"
    if qdrant.collection_exists(name):
        qdrant.delete_collection(name)
    yield name
    if qdrant.collection_exists(name):
        qdrant.delete_collection(name)


def test_boot_refuses_when_the_collection_was_embedded_under_another_recipe(
        qdrant, served_collection, isolated_runs):
    """§4.3's third refusal (§6.6, F11) — and the one the write-time guard cannot make.

    `fingerprint.require` refuses an *upsert*, which keeps two families of vector out of one cosine
    space. A serving process is the other half: it embeds the query with the model it is configured
    for and compares it against whatever is already stored. Nothing is written, so no guard fires,
    and the only symptom is worse neighbours — which is indistinguishable from a thin corpus.
    """
    env = serve_env(VSIR_RUNS_COLLECTION=isolated_runs)
    stored = replace(fingerprint.Fingerprint.of(load_config(env)),
                     embed_model="gemini-embedding-1")
    fingerprint.write(qdrant, isolated_runs, served_collection, stored)

    with pytest.raises(BootRefused) as refused:
        create_app(env)

    assert refused.value.failed_checks == ["collection_fingerprint"]
    assert "gemini-embedding-1" in str(refused.value)
    assert "gemini-embedding-2" in str(refused.value)


def test_the_same_collection_boots_when_the_recipe_agrees(qdrant, served_collection,
                                                          isolated_runs):
    """The control. A refusal that fires on the agreeing case too would only look like rigour."""
    env = serve_env(VSIR_RUNS_COLLECTION=isolated_runs)
    fingerprint.write(qdrant, isolated_runs, served_collection,
                      fingerprint.Fingerprint.of(load_config(env)))

    create_app(env)  # no refusal


def test_a_collection_with_no_fingerprint_yet_still_boots(served_collection, isolated_runs):
    """A fresh deployment has not ingested yet, so there is no record to disagree with — and
    refusing here would mean it could never boot far enough to run the ingest that writes one."""
    create_app(serve_env(VSIR_RUNS_COLLECTION=isolated_runs))  # no refusal


def test_boot_refuses_on_a_floating_model_alias(served_collection):
    """F11 — a `-latest` id makes every cache key and every provenance stamp a lie."""
    with pytest.raises(BootRefused) as refused:
        create_app(serve_env(VSIR_VLM_MODEL="gemini-pro-latest"))

    assert refused.value.failed_checks == ["model_ids_pinned"]


def test_boot_refuses_on_a_missing_required_variable(served_collection):
    env = {key: value for key, value in serve_env().items() if key != "VSIR_API_TOKENS"}

    with pytest.raises(BootRefused) as refused:
        create_app(env)

    assert "VSIR_API_TOKENS" in str(refused.value)


def test_boot_refuses_an_empty_token_list(served_collection):
    """A service configured with no credential would be `impl`'s open surface again (E5)."""
    with pytest.raises(BootRefused) as refused:
        create_app(serve_env(VSIR_API_TOKENS=" , "))

    assert "VSIR_API_TOKENS" in str(refused.value)


def test_the_process_entry_point_exits_one_rather_than_unwinding(served_collection):
    """`app_factory` is what uvicorn calls: a refusal is exit 1, with its reason already on the
    stream as JSON — a forty-line traceback after it is non-JSON noise on a stream whose contract
    is one object per line (§15 Factor XI)."""
    import os

    previous = dict(os.environ)
    os.environ.update(serve_env(VSIR_EMBED_MODEL="gemini-embedding-latest"))
    try:
        with pytest.raises(SystemExit) as exited:
            app_factory()
    finally:
        os.environ.clear()
        os.environ.update(previous)

    assert exited.value.code == 1


# ── and the same refusal from `vsir serve`, with nothing bound ───────────────────────────────────

def test_vsir_serve_refuses_before_binding_the_port(qdrant, served_collection, repo_root):
    """U014's acceptance criterion, asserted on a real process: exit non-zero, port never open.

    Calling the factory proves the check runs; spawning the CLI proves the *ordering*. The app is
    built before uvicorn exists, so there is no path on which a refusing process has already
    accepted a connection.
    """
    assert not _listening(REFUSAL_PORT), f"something is already on {REFUSAL_PORT}"
    env = {**serve_env(VSIR_PORT=str(REFUSAL_PORT)), "PATH": "/usr/bin:/bin", "HOME": "/tmp"}
    qdrant.delete_payload_index(served_collection, field_name="text")
    try:
        started = time.monotonic()
        finished = subprocess.run([sys.executable, "-m", "vsir", "serve"],
                                  env=env, cwd=repo_root, capture_output=True, text=True,
                                  timeout=REFUSAL_TIMEOUT_S)
        elapsed = time.monotonic() - started
        bound = _listening(REFUSAL_PORT)
    finally:
        qdrant.create_payload_index(served_collection, field_name="text",
                                    field_schema=TEXT_INDEX_PARAMS)

    assert finished.returncode == 1, finished.stdout + finished.stderr
    assert not bound, "the port was bound by a process that refused to start"
    assert "collection_schema" in finished.stdout + finished.stderr
    assert elapsed < REFUSAL_TIMEOUT_S


def test_vsir_serve_names_the_missing_variable_and_exits_one(repo_root):
    """A configuration refusal is a named non-zero exit, not a traceback and not a warning."""
    env = {key: value for key, value in serve_env().items() if key != "VSIR_RELEASE_ID"}
    env.update({"PATH": "/usr/bin:/bin", "HOME": "/tmp"})

    finished = subprocess.run([sys.executable, "-m", "vsir", "serve"], env=env, cwd=repo_root,
                              capture_output=True, text=True, timeout=REFUSAL_TIMEOUT_S)

    assert finished.returncode == 1
    assert "VSIR_RELEASE_ID" in finished.stdout + finished.stderr


def test_serve_is_in_the_command_table(repo_root):
    """§4.4 — an operational action that is not a `vsir` subcommand is not supported."""
    finished = subprocess.run([sys.executable, "-m", "vsir", "--help"],
                              env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"}, cwd=repo_root,
                              capture_output=True, text=True, timeout=REFUSAL_TIMEOUT_S)

    assert finished.returncode == 0, finished.stderr
    assert "serve" in finished.stdout


def test_the_collection_the_refusals_are_about_is_the_configured_one(served_collection):
    """A guard on this file's own premise: these tests must be about the served collection."""
    assert served_collection.startswith(SERVED_COLLECTION)
    assert serve_env()["VSIR_QDRANT_URL"] == QDRANT_URL
