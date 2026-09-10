"""L2 — a run killed in flight (Spec §6.7, §15 Factor IX · **I7**, **F17**).

    *A crash at window 700 of a 1,440-page manual must leave 0 pages queryable* — otherwise
    `searchable_ratio` lies and the loop abstains about a page that is in the document.

This is the one property that cannot be checked in-process, because the failure mode is the
process ending. So the suite starts a **real `vsir ingest`** against the test Qdrant, kills it
partway through, and then asks the store what a tool would see.

Two kills, and they leave deliberately different marks:

* `SIGKILL` cannot be handled at all. The run point stays as its last checkpoint left it — `running`
  with a lease that will expire — and **zero pages are queryable**, because nothing flips
  `is_current` except the publish gates (I7).
* `SIGTERM` is handled: the run is checkpointed `stopped`, the lease is released, and `stopped` is
  the only state `--resume` accepts without `--steal` (§6.9).

Either way the point is the same one: a half-finished run has a record that says so and answers
nothing. `impl` had neither half — its run state was a dict on a daemon thread, so a kill left a
paid run with no report, no error and no resume (register **E2**).

The last section drives the operational commands of §4.4 — `vsir runs show`, `vsir gates rerun`,
`vsir publish --override` — as real subprocesses, because this module already owns the fixture that
runs the real CLI. An operational action that cannot be a `vsir` subcommand is not supported
(§15 Factor XII), so the subcommands are exercised the way an operator would use them.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from vsir.ingest import index as index_module
from vsir.ingest import run as run_module

REPO = Path(__file__).resolve().parents[3]
PDF = REPO / "data" / "source" / "synthetic_3window.pdf"
FIXTURE = REPO / "data" / "fixtures" / "synthetic_3window"
DOC = "synthetic-3window"

EMBED_DIM = 1536
COLLECTION = "vsir_pages_kill"
PAGES_COLLECTION = f"{COLLECTION}_{EMBED_DIM}"
RUNS = "vsir_runs_kill"

#: How long to wait for the child to reach the step we mean to kill it in. Generous: rendering 42
#: pages at dpi 220 is not fast, and a test that killed the process before it started would pass
#: for the wrong reason — so :func:`wait_for` asserts the marker was actually seen.
STEP_TIMEOUT_S = 180


def env_for(qdrant_url: str) -> dict[str, str]:
    """The §15 Factor III environment, as a mapping — no `.env`, no test-only branch."""
    return {
        **os.environ,
        "VSIR_PORT": "8000", "VSIR_QDRANT_URL": qdrant_url, "VSIR_COLLECTION": COLLECTION,
        "VSIR_RUNS_COLLECTION": RUNS, "VSIR_VLM": "stub", "VSIR_FIXTURE": str(FIXTURE),
        "VSIR_VLM_MODEL": "gemini-3.8-flash-001", "VSIR_EMBED_MODEL": "gemini-embedding-2",
        "VSIR_PROMPT_VERSION": "s2-v1", "VSIR_API_TOKENS": "test-only-not-a-credential",
        "VSIR_READ_QUOTA": "10", "VSIR_ALLOW_PAID": "0", "VSIR_LOG_LEVEL": "INFO",
        "VSIR_RELEASE_ID": "test-0", "PYTHONUNBUFFERED": "1",
    }


def wait_for(child: subprocess.Popen, marker: str, *, timeout: float = STEP_TIMEOUT_S) -> str:
    """Read the child's stdout until ``marker`` appears. Returns everything read so far."""
    seen = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = child.stdout.readline()  # type: ignore[union-attr]
        if not line:
            break
        seen += line
        if marker in line:
            return seen
    raise AssertionError(f"{marker!r} never appeared before the timeout; saw:\n{seen[-2000:]}")


def run_id_of(output: str) -> str:
    """The run id the CLI printed on its first line — the same one the control plane holds."""
    for line in output.splitlines():
        if line.startswith("vsir ingest"):
            return line.split("· run ")[1].split(" ·")[0].strip()
    raise AssertionError(f"no run id in:\n{output[:500]}")


def queryable(client: Any, doc_id: str = DOC) -> int:
    """What a tool would see: every tool injects `is_current=True` server-side (I7)."""
    if not client.collection_exists(PAGES_COLLECTION):
        return 0
    return index_module.count(client, PAGES_COLLECTION, {"doc_id": doc_id, "is_current": True})


@pytest.fixture
def store(qdrant):
    """Collections of this suite's own, dropped either side: a kill test starts from nothing."""
    def drop() -> None:
        for name in (PAGES_COLLECTION, RUNS):
            if qdrant.collection_exists(name):
                qdrant.delete_collection(name)

    drop()
    try:
        yield qdrant
    finally:
        drop()


@pytest.fixture
def ingest(store, qdrant_url):
    """Start `vsir ingest` as a real process and make sure it is not left running."""
    children: list[subprocess.Popen] = []

    def start() -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, "-m", "vsir", "ingest", str(PDF), "--vlm", "stub"],
            cwd=str(REPO), env=env_for(qdrant_url), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        children.append(child)
        return child

    try:
        yield start
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=30)


@pytest.fixture(scope="session")
def qdrant_url() -> str:
    return os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")


# ── SIGKILL — the mark a crash leaves (I7, F17) ──────────────────────────────────────────────────

def test_kill_mid_run_zero_queryable_pages(store, ingest):
    """AC + F17: `SIGKILL` at window 2 of 3 leaves `state: running` with a lease that expires (or
    `stopped`), and **zero** queryable pages for that document.

    The kill lands after the second window's S2 record has been derived, which is the moment the
    process is holding the most and has published the least — exactly the shape of the 1,440-page
    crash §6.7 describes.
    """
    child = ingest()
    seen = wait_for(child, "07 derivation")
    child.send_signal(signal.SIGKILL)
    child.wait(timeout=30)

    assert child.returncode != 0
    assert queryable(store) == 0

    record = run_module.load(store, RUNS, run_id_of(seen))
    assert record is not None, "a run that died has to be a run that exists (register E2)"
    assert record.state in (run_module.RUNNING, run_module.STOPPED)
    assert record.published_at is None
    assert record.doc_id == DOC


def test_a_killed_run_leaves_its_window_checkpoints_behind(store, ingest):
    """§6.7 — one point per window, written as each step finishes. That is the difference between
    a run `--resume` can pick up and one that has to be re-billed from the first window."""
    child = ingest()
    seen = wait_for(child, "07 derivation")
    child.send_signal(signal.SIGKILL)
    child.wait(timeout=30)

    windows = run_module.windows(store, RUNS, run_id_of(seen))

    assert [window.window for window in windows] == [[1, 14], [15, 28], [29, 42]]
    assert {window.checkpoint for window in windows} == {"extract"}
    assert all(window.extract_key for window in windows)


def test_a_killed_run_leaves_its_lease_to_expire_and_a_resume_refuses_without_steal(store,
                                                                                   ingest):
    """D9 — the lease is advisory, so a dead worker's claim is not cleaned up by anything; it
    expires. Until it does, a second worker refuses rather than silently re-billing the windows."""
    child = ingest()
    seen = wait_for(child, "07 derivation")
    child.send_signal(signal.SIGKILL)
    child.wait(timeout=30)
    run_id = run_id_of(seen)

    record = run_module.require(store, RUNS, run_id)
    assert record.lease.live(), "the dead worker's lease is still live — nothing cleaned it up"

    with pytest.raises(run_module.LeaseHeld):
        run_module.claim(store, RUNS, run_id, owner="worker-2")
    assert run_module.claim(store, RUNS, run_id, owner="worker-2", steal=True).lease.owner == \
        "worker-2"


# ── SIGTERM — the mark a graceful stop leaves (§15 Factor IX) ────────────────────────────────────

def test_sigterm_checkpoints_the_run_as_stopped_and_publishes_nothing(store, ingest):
    """§6.9 — `stopped` is what a SIGTERM leaves behind, and it is the only state `--resume`
    accepts without `--steal`. Zero pages are queryable either way (I7)."""
    child = ingest()
    seen = wait_for(child, "06 S2 extraction")
    child.send_signal(signal.SIGTERM)
    child.wait(timeout=60)

    record = run_module.require(store, RUNS, run_id_of(seen))

    assert record.state == run_module.STOPPED
    assert record.failed is not None and record.failed.reason == "sigterm"
    assert not record.lease.live(), "a stopped run releases its lease so a resume needs no --steal"
    assert record.published_at is None
    assert queryable(store) == 0


def test_a_stopped_run_is_resumable_without_stealing(store, ingest):
    """The point of releasing the lease: an operator restarting a drained worker does not have to
    reach for `--steal`, which is the flag that should always mean *something went wrong*."""
    child = ingest()
    seen = wait_for(child, "06 S2 extraction")
    child.send_signal(signal.SIGTERM)
    child.wait(timeout=60)

    resumed = run_module.claim(store, RUNS, run_id_of(seen), owner="worker-2")

    assert resumed.state == run_module.RUNNING and resumed.lease.owner == "worker-2"


# ── and the run that is allowed to finish does publish ───────────────────────────────────────────

def test_the_same_pipeline_uninterrupted_publishes_every_page(store, ingest):
    """The control: without a kill, the run reaches `published` and all 42 pages are queryable.

    Without this row the four above would pass on a pipeline that never publishes anything, which
    is the failure mode of every "assert nothing happened" test.
    """
    child = ingest()
    output, _ = child.communicate(timeout=600)

    assert child.returncode == 0, output[-3000:]
    record = run_module.require(store, RUNS, run_id_of(output))
    assert record.state == run_module.PUBLISHED and record.published_at
    assert record.pages_indexed == 42 == queryable(store)
    assert json.loads([line for line in output.splitlines()
                       if '"event": "published"' in line][-1])["pages_indexed"] == 42


# ── the operational commands of §4.4, as an operator runs them ───────────────────────────────────

def cli(qdrant_url: str, *arguments: str) -> subprocess.CompletedProcess:
    """One `vsir` subcommand, in its own process, configured only by the environment."""
    return subprocess.run([sys.executable, "-m", "vsir", *arguments], cwd=str(REPO),
                          env=env_for(qdrant_url), capture_output=True, text=True, timeout=300)


@pytest.fixture
def published_run(store, ingest, qdrant_url) -> str:
    """One completed `vsir ingest`, for the three commands that read and act on a finished run."""
    child = ingest()
    output, _ = child.communicate(timeout=600)
    assert child.returncode == 0, output[-3000:]
    return run_id_of(output)


def test_runs_show_prints_the_record_of_6_9(published_run, qdrant_url):
    """§4.4 — `vsir runs show <run_id>`: the run record, from `vsir_runs` and nowhere else."""
    result = cli(qdrant_url, "runs", "show", published_run)

    assert result.returncode == 0, result.stdout[-2000:]
    for line in ("state        published", f"run          {published_run}", "gate", "retired"):
        assert line in result.stdout
    for gate in ("window_coverage", "offset_check", "grounded_rate", "text_coverage",
                 "label_monotonic"):
        assert gate in result.stdout


def test_runs_show_refuses_an_unknown_run_by_name(qdrant_url, store):
    result = cli(qdrant_url, "runs", "show", "01J0NOSUCHRUN000000000000")

    assert result.returncode == 1
    assert "REFUSED  run_not_found" in result.stdout


def test_gates_rerun_re_evaluates_against_the_index_and_publishes_nothing(published_run,
                                                                         qdrant_url, store):
    """§4.4 — free, and it changes no page. The records are scrolled back out of the collection,
    so it judges the document that is stored rather than one a process remembered (§15 VI)."""
    before = queryable(store)

    result = cli(qdrant_url, "gates", "rerun", published_run)

    assert result.returncode == 0, result.stdout[-2000:]
    assert "blocked by   nothing" in result.stdout
    assert "re-evaluated against the index" in result.stdout
    assert queryable(store) == before == 42


def test_publish_with_an_override_records_the_reason_and_flags_every_page(published_run,
                                                                         qdrant_url, store):
    """AC + §4.4 — the reason is recorded in the run and **every** page is flagged
    `published_with_override`. Run here on a document whose gates pass, because what is being
    checked is the operator path: the blocking half is asserted in `test_publish_and_retire`."""
    result = cli(qdrant_url, "publish", published_run, "--override", "grounded_rate",
                 "--reason", "M2b baseline: this scanner reads 0.62 and the pages are fine")

    assert result.returncode == 0, result.stdout[-2000:]
    assert "override     grounded_rate" in result.stdout
    assert "M2b baseline" in result.stdout

    record = run_module.require(store, RUNS, published_run)
    pages = run_module.run_records(store, PAGES_COLLECTION, doc_id=DOC, revision="1.0",
                                   run_id=published_run)
    assert [override.gate for override in record.overrides] == ["grounded_rate"]
    assert len(pages) == 42
    assert all("published_with_override" in page.content.flags for page in pages)
    assert queryable(store) == 42


def test_publish_refuses_an_override_of_a_gate_that_does_not_take_one(published_run, qdrant_url):
    """§11.1 offers exactly one override, and the refusal names which."""
    result = cli(qdrant_url, "publish", published_run, "--override", "offset_check",
                 "--reason", "the labels look fine to me")

    assert result.returncode == 1
    assert "REFUSED  override_refused" in result.stdout
    assert "['grounded_rate']" in result.stdout


def test_publish_refuses_an_override_with_no_reason(published_run, qdrant_url):
    """The reason is the only thing that will later explain why a held document is in the index."""
    result = cli(qdrant_url, "publish", published_run, "--override", "grounded_rate")

    assert result.returncode == 1
    assert "REFUSED  override_refused" in result.stdout
