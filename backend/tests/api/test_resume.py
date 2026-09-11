"""`vsir ingest --resume <run_id>` — finishing a killed run without buying it twice (U025).

The corpus is `data/source/synthetic_large.pdf`: 150 pages, no contents page, so the ladder folds
at the cap into **five** windows (§6.2). Spec §13 M8 asks for a generated large PDF rather than
the 1,440-page manual, and §6.2 gives the reason in a line — *"a resume test wants a
deterministic corpus, not a large one."*

**What "without re-billing" means here, mechanically.** §6.3 caches every response under a
content-addressable key, and U025 put that cache in `vsir_runs` where every replica can reach it
(`vlm/cached.py`, D9). So a resumed run re-runs step 06 from window 1, and every window the
killed run had already finished comes back out of the control plane under the key it was billed
under. The **backend is never called** for those windows — which is what the assertions count,
because a call count is the only measure of spend that does not depend on a price list.

The stub is used the way §12.2 requires (`VSIR_VLM=stub` + a frozen fixture, D10), and it is what
makes the count meaningful: the stub reads one file per call, so a `vlm_replay` event is a call
and a `vlm_cache_hit` event is a call that did not happen.

These run `vsir` as a **subprocess**, the way `test_kill_mid_run.py` does, because a resume is a
second process taking over from a first and asserting that in one process would be asserting
about something else.
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

from vsir.core.status import Status
from vsir.ingest import index as index_module
from vsir.ingest import run as run_module
from vsir.serve.envelope import Provenance
from vsir.serve.tools.lookup import lookup
from vsir.serve.tools.resolve import resolve
from vsir.vlm import cache as vlm_cache

REPO = Path(__file__).resolve().parents[3]
PDF = REPO / "data" / "source" / "synthetic_large.pdf"
FIXTURE = REPO / "data" / "fixtures" / "synthetic_large"
EXPECTED = json.loads((FIXTURE / "expected.json").read_text())

DOC = EXPECTED["doc_id"]
PAGE_COUNT = EXPECTED["page_count"]
WINDOWS = [tuple(window) for window in EXPECTED["windows"]]
EMBED_DIM = 1536
COLLECTION = "vsir_pages_resume"
PAGES_COLLECTION = f"{COLLECTION}_{EMBED_DIM}"
RUNS = "vsir_runs_resume"
#: 150 pages at dpi 220 is real rendering work on every step that touches a raster.
STEP_TIMEOUT_S = 900

PROVENANCE = Provenance(release_id="test")


def env_for(qdrant_url: str) -> dict[str, str]:
    return {
        **os.environ,
        "VSIR_PORT": "8000", "VSIR_QDRANT_URL": qdrant_url, "VSIR_COLLECTION": COLLECTION,
        "VSIR_RUNS_COLLECTION": RUNS, "VSIR_VLM": "stub", "VSIR_FIXTURE": str(FIXTURE),
        "VSIR_VLM_MODEL": "gemini-3.8-flash", "VSIR_EMBED_MODEL": "gemini-embedding-2",
        "VSIR_PROMPT_VERSION": "s2-v1", "VSIR_API_TOKENS": "test-only-not-a-credential",
        "VSIR_READ_QUOTA": "10", "VSIR_ALLOW_PAID": "0", "VSIR_LOG_LEVEL": "INFO",
        "VSIR_RELEASE_ID": "test-0", "PYTHONUNBUFFERED": "1",
    }


@pytest.fixture(scope="session")
def qdrant_url() -> str:
    return os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")


@pytest.fixture
def store(qdrant):
    for name in (PAGES_COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    yield qdrant
    for name in (PAGES_COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)


def ingest(qdrant_url: str, *extra: str) -> subprocess.Popen:
    """A `vsir ingest` in its own process, line-buffered so a marker can be waited on."""
    return subprocess.Popen(
        [sys.executable, "-m", "vsir", "ingest", str(PDF), "--vlm", "stub", *extra],
        cwd=str(REPO), env=env_for(qdrant_url), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1)


def wait_for(child: subprocess.Popen, marker: str, *, timeout: int = STEP_TIMEOUT_S) -> str:
    seen = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = child.stdout.readline()
        if not line:
            break
        seen += line
        if marker in line:
            return seen
    raise AssertionError(f"{marker!r} never appeared before the timeout; saw:\n{seen[-3000:]}")


def drain(child: subprocess.Popen, *, timeout: int = STEP_TIMEOUT_S,
          expect: int | None = None) -> str:
    """Wait for the process and return everything it said.

    ``expect`` asserts the exit code, and every caller that runs an ingest to completion passes
    it. A `drain` that ignored the status turned *"the run refused at step 01"* into *"the index
    has 0 of 150 pages"* three assertions later, which is the wrong end of the failure to be
    reading.
    """
    out, _ = child.communicate(timeout=timeout)
    if expect is not None:
        assert child.returncode == expect, (
            f"vsir exited {child.returncode}, expected {expect}:\n{out[-4000:]}")
    return out


def run_id_of(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("vsir ingest"):
            return line.split("· run ")[1].split(" ·")[0].strip()
    raise AssertionError(f"no run id in:\n{output[:500]}")


def cli(qdrant_url: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "vsir", *arguments], cwd=str(REPO),
                          env=env_for(qdrant_url), capture_output=True, text=True,
                          timeout=STEP_TIMEOUT_S)


def cached_windows(client) -> set[str]:
    """The `extract_key`s §6.3's durable cache holds — what a resume will not have to buy."""
    if not client.collection_exists(RUNS):
        return set()
    found, _ = client.scroll(collection_name=RUNS, limit=1000, with_payload=True,
                             with_vectors=False)
    return {str((point.payload or {}).get("cache_key"))
            for point in found
            if (point.payload or {}).get("kind") == vlm_cache.KIND_VLM_CACHE
            and (point.payload or {}).get("namespace") == vlm_cache.EXTRACT}


def window_of(key: str) -> str:
    """``"31-60"`` for a key the fixture declares, or the key itself. For legible failures."""
    for span, declared in EXPECTED["extract_keys"].items():
        if declared == key:
            return span
    return key[:12]


def spans(keys) -> list[str]:
    return sorted(window_of(key) for key in keys)


def calls_in(output: str) -> list[str]:
    """Every S2 window the backend was actually asked for, from the event stream."""
    keys = []
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event.get("event") == "vlm_replay" and event.get("namespace") == vlm_cache.EXTRACT:
            keys.append(event["cache_key"])
    return keys


def cache_write_failures_in(output: str) -> list[str]:
    """`ControlPlaneStore.put` swallows its own failures by design — this is how they surface.

    A cache write that did not happen costs the next run a re-bill and costs this one nothing,
    which is the right trade at the boundary and the wrong thing to be silent about in a test
    that is *measuring* re-bills. Without this, a failed write reads as a re-billing pipeline.
    """
    failures = []
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event.get("event") == "vlm_cache_write_failed":
            failures.append(f"{event.get('cache_key')}: {event.get('detail')}")
    return failures


def cache_hits_in(output: str) -> list[str]:
    keys = []
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event.get("event") == "vlm_cache_hit" and event.get("namespace") == vlm_cache.EXTRACT:
            keys.append(event["cache_key"])
    return keys


def done_windows(client, run_id: str) -> list[tuple[int, int]]:
    return [(state.start, state.end)
            for state in run_module.windows(client, RUNS, run_id)
            if state.state == run_module.DONE]


def queryable(client) -> int:
    return index_module.count(client, PAGES_COLLECTION, {"doc_id": DOC, "is_current": True})


@pytest.fixture
def killed(store, qdrant_url):
    """A run stopped by `SIGTERM` partway through step 06. Yields ``(run_id, output)``.

    The kill lands **after** the second window's checkpoint, which is what makes the run an
    interesting one to resume: windows behind it are bought, windows in front of it are not, and
    exactly one is in flight.
    """
    child = ingest(qdrant_url)
    seen = wait_for(child, "06 S2 extraction")
    run_id = run_id_of(seen)
    deadline = time.monotonic() + STEP_TIMEOUT_S
    while time.monotonic() < deadline:
        if len(done_windows(store, run_id)) >= 2:
            break
        time.sleep(0.2)
    else:  # pragma: no cover - a timeout here is a failure, not a branch
        raise AssertionError("the run never checkpointed two windows")
    child.send_signal(signal.SIGTERM)
    seen += drain(child, timeout=120)
    record = run_module.require(store, RUNS, run_id)
    assert record.state == run_module.STOPPED, (
        f"the SIGTERM left the run {record.state!r}, so what follows would be testing a "
        f"different thing:\n{seen[-3000:]}")
    return run_id, seen


# ── the kill leaves something to resume ─────────────────────────────────────────────────────────

def test_sigterm_checkpoint_loses_at_most_one_window(killed, store):
    """AC + AC-016: at most one window's work is lost, measured against the pre-kill checkpoint.

    The comparison the acceptance asks for: the windows recorded `done` before the kill are
    exactly the windows the resume does **not** call the backend for, so the only window that can
    be re-billed is the one that was in flight — and `vlm/cached.py` means even that one is only
    re-billed if the kill landed before its response came back.
    """
    run_id, _ = killed
    record = run_module.require(store, RUNS, run_id)
    checkpointed = done_windows(store, run_id)

    assert record.state == run_module.STOPPED
    assert record.failed is not None and record.failed.reason == "sigterm"
    assert record.published_at is None
    assert queryable(store) == 0, "a kill publishes nothing (I7, F17)"

    assert 2 <= len(checkpointed) < len(WINDOWS)
    assert checkpointed == WINDOWS[:len(checkpointed)], "windows finish in plan order"
    # Every checkpointed window's response is in the durable cache, which is what makes the
    # checkpoint mean *bought* rather than merely *attempted*.
    assert cached_windows(store) >= {
        EXPECTED["extract_keys"][f"{start}-{end}"] for start, end in checkpointed}


def test_the_corpus_forces_at_least_three_window_checkpoints():
    """AC: `synthetic_large.pdf` is large enough that a kill can land in the middle of a run.

    A statement about the **corpus**, read from its own acceptance table, so it costs nothing:
    a 150-page ingest to assert a number that is checked into the repository would be the most
    expensive way to read a file.
    """
    assert len(WINDOWS) >= 3, "at least three window checkpoints (U025's acceptance)"
    assert len(WINDOWS) == 5 and EXPECTED["page_count"] == PAGE_COUNT
    assert EXPECTED["ladder_level"] == 2


@pytest.fixture
def stopped_run(store):
    """A run record in the state a `SIGTERM` leaves, written straight to the control plane.

    `claim()` reads the **run point** and nothing else, so the two tests below — which are about
    which states and leases a resume will take over — need a run record, not a document. The
    real thing is proved next door: `test_sigterm_checkpoint.py` kills an actual 150-page ingest
    and asserts the state, the lease and the checkpoints it leaves. Paying for that ingest again
    here would be re-proving it to test an `if`.
    """
    run_module.ensure_control_plane(store, RUNS)
    opened = run_module.start(store, RUNS, run_id="R-STOPPED", doc_id=DOC, revision="1.0",
                              release_id="test-0", collection=PAGES_COLLECTION,
                              page_count=PAGE_COUNT, windows_total=len(WINDOWS), owner="worker-1")
    return run_module.stop(store, RUNS, opened, reason="sigterm", step="extract").run_id


def test_a_stopped_run_is_the_only_state_resume_takes_without_steal(stopped_run, store):
    """§6.9: `stopped` is what a `SIGTERM` leaves and the only state `--resume` accepts.

    The lease is released by `stop()` so the resume does not need `--steal`; the *state* check is
    what refuses every other run, and the two refusals are distinct because they want different
    answers from an operator.
    """
    assert not run_module.require(store, RUNS, stopped_run).lease.live()

    taken = run_module.claim(store, RUNS, stopped_run, owner="worker-2")
    assert taken.state == run_module.RUNNING
    assert taken.failed is None, "a run that is running again has not failed"

    run_module.save(store, RUNS, taken.model_copy(
        update={"state": run_module.PUBLISHED, "lease": run_module.Lease()}))
    with pytest.raises(run_module.RunNotResumable) as refusal:
        run_module.claim(store, RUNS, stopped_run, owner="worker-3")
    assert refusal.value.details["state"] == run_module.PUBLISHED
    assert refusal.value.code == "run_not_resumable"
    assert run_module.RESUMABLE == (run_module.STOPPED,)

    assert run_module.claim(store, RUNS, stopped_run, owner="worker-3",
                            steal=True).state == run_module.RUNNING


def test_resume_refuses_a_live_lease_without_steal_and_proceeds_with_it(stopped_run, store):
    """AC: a live lease is `lease_held`; `--steal` takes it.

    The lease is advisory (Qdrant has no compare-and-swap), so what makes the duplicate safe is
    I1 and I7 rather than this refusal — the refusal is what stops it happening by accident. The
    *"and the final point count is still `pdf.page_count`"* half of the criterion is
    `test_a_resumed_run_leaves_no_duplicate_or_orphan_point`, over a real resumed run.
    """
    run_module.claim(store, RUNS, stopped_run, owner="worker-holding-it")

    with pytest.raises(run_module.LeaseHeld) as refusal:
        run_module.claim(store, RUNS, stopped_run, owner="worker-2")
    assert refusal.value.details["owner"] == "worker-holding-it"

    assert run_module.claim(store, RUNS, stopped_run, owner="worker-2",
                            steal=True).lease.owner == "worker-2"


# ── the resume itself ───────────────────────────────────────────────────────────────────────────

@pytest.fixture
def resumed_index(killed, store, qdrant_url):
    """A killed run, resumed to `published`. Shared by the tests that inspect what it left.

    `test_resume_completes_without_rebilling` keeps its own kill-and-resume because it measures
    the *resume*; these two measure the **index** the resume produced, and one is enough.
    """
    run_id, _ = killed
    drain(ingest(qdrant_url, "--resume", run_id), expect=0)
    return store, run_id


def test_resume_completes_without_rebilling(killed, store, qdrant_url):
    """AC + AC-016, the unit's whole point: the run reaches `published` and buys nothing twice.

    Every window the killed run finished is served from §6.3's durable cache on the way through,
    and the backend is asked only for the windows that were never bought. The final index is the
    same 150 current pages a clean run produces — `point_id` is `uuid5(page_id)` (I1), so the
    resume overwrites in place and the total cannot double (F12, register E7).
    """
    run_id, _ = killed
    bought_before = done_windows(store, run_id)

    resumed = drain(ingest(qdrant_url, "--resume", run_id), expect=0)

    record = run_module.require(store, RUNS, run_id)
    assert record.state == run_module.PUBLISHED, resumed[-4000:]
    assert record.run_id == run_id, "a resume keeps the run's own id (§6.7)"
    assert record.windows_done == record.windows_total == len(WINDOWS)
    # A published run that still reports `failed: sigterm` tells an operator two contradictory
    # things about one run. `claim` clears it; the stop stays on the event stream (§11.4).
    assert record.failed is None
    assert queryable(store) == PAGE_COUNT

    already = {EXPECTED["extract_keys"][f"{start}-{end}"] for start, end in bought_before}
    called = set(calls_in(resumed))
    assert already, "the killed run must have bought something for this to be a measurement"
    assert already & called == set(), (
        f"{spans(already & called)} were checkpointed `done` by the killed run and bought again "
        f"by the resume. done={spans(already)} called={spans(called)} "
        f"cached={spans(cached_windows(store))} "
        f"write_failures={cache_write_failures_in(resumed)}")
    assert already <= set(cache_hits_in(resumed)), "they came back out of the control plane"
    assert len(called) <= len(WINDOWS) - len(bought_before)


def test_a_resumed_run_leaves_no_duplicate_or_orphan_point(resumed_index):
    """Register **E7**: the resumed run's index is exactly one point per page, all its own."""
    store, run_id = resumed_index

    assert index_module.count(store, PAGES_COLLECTION, {"doc_id": DOC}) == PAGE_COUNT
    assert index_module.count(store, PAGES_COLLECTION, {"run_id": run_id}) == PAGE_COUNT
    assert queryable(store) == PAGE_COUNT


def test_the_resumed_document_answers_the_code_its_fixture_declares(resumed_index):
    """The index a resume produces is an index that works — not merely one with the right count."""
    store, _run_id = resumed_index

    response = lookup(store, PAGES_COLLECTION, EXPECTED["unique_code"], provenance=PROVENANCE,
                      runs_collection=RUNS)

    assert response.status == Status.OK
    assert [hit.page_no for hit in response.hits] == [EXPECTED["unique_code_page"]]


def test_a_second_clean_ingest_of_the_same_document_buys_nothing(store, qdrant_url):
    """§6.3's cache, stated as the property it exists for — and the shape a resume relies on.

    Also register **B2** seen from the other side: `impl` cached neither S1 nor S2, so every
    re-run re-billed the whole document and a future S1 could silently re-pick the ladder.
    """
    first = drain(ingest(qdrant_url), expect=0)
    assert run_module.require(store, RUNS, run_id_of(first)).state == run_module.PUBLISHED
    assert len(calls_in(first)) == len(WINDOWS)
    assert cache_write_failures_in(first) == []
    assert spans(cached_windows(store)) == spans(calls_in(first)), (
        f"every window the run called for must be in the cache it wrote: "
        f"called {spans(calls_in(first))}, cached {spans(cached_windows(store))}")

    second = drain(ingest(qdrant_url), expect=0)

    assert calls_in(second) == []
    assert len(cache_hits_in(second)) == len(WINDOWS)
    assert queryable(store) == PAGE_COUNT


def test_resume_against_a_different_document_is_refused_by_name(killed, store, qdrant_url):
    """A resume writes this document's pages under that run's id, and publish would flip them."""
    run_id, _ = killed
    other = REPO / "data" / "source" / "synthetic_3window.pdf"

    refused = subprocess.run(
        [sys.executable, "-m", "vsir", "ingest", str(other), "--vlm", "stub",
         "--resume", run_id, "--until", "manifest"],
        cwd=str(REPO), env=env_for(qdrant_url), capture_output=True, text=True,
        timeout=STEP_TIMEOUT_S)

    assert refused.returncode != 0
    assert "REFUSED  run_document_mismatch" in refused.stdout


def test_resume_with_no_path_resolves_the_source_from_the_document_store(killed, store,
                                                                        qdrant_url):
    """§6.9, U029: an upload is resumable across a restart, because the bytes are not on the pod."""
    run_id, _ = killed

    resumed = subprocess.run(
        [sys.executable, "-m", "vsir", "ingest", "--vlm", "stub", "--resume", run_id],
        cwd=str(REPO), env=env_for(qdrant_url), capture_output=True, text=True,
        timeout=STEP_TIMEOUT_S)

    assert resumed.returncode == 0, resumed.stdout[-4000:]
    assert f"resuming     {run_id}" in resumed.stdout
    assert run_module.require(store, RUNS, run_id).state == run_module.PUBLISHED


# ── register E9, re-verified at this corpus's scale ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def published(qdrant, qdrant_url):
    """One clean ingest of the 150-page corpus, shared by every test that only **reads** it.

    Module-scoped on purpose. A 150-page ingest renders 150 rasters at dpi 220 and writes 150
    points across three surfaces, and the tests below assert about the *index it produces*, not
    about producing it — so paying for one each would be three minutes spent re-proving what
    `test_a_second_clean_ingest_of_the_same_document_buys_nothing` already proves.
    """
    for name in (PAGES_COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    drain(ingest(qdrant_url), expect=0)
    yield qdrant
    for name in (PAGES_COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)


class SpyClient:
    """Records every store call by name and answers from the real client (see E9)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        def recorded(*args: Any, **call: Any) -> Any:
            self.calls.append(name)
            return attribute(*args, **call)

        return recorded


def test_resolve_still_uses_an_indexed_facet_at_150_pages(published):
    """Register **E9** at M8's scale: `resolve` facets, it never scrolls and filters in Python.

    `test_resolve.py` asserts this over a six-page corpus, where a scroll would be invisible
    because it would also be fast. The plan asks for it again at scale-out, and this is the
    largest corpus in the tree: 150 pages, every one of them printing a label.
    """
    spy = SpyClient(published)

    found = resolve(spy, PAGES_COLLECTION, "75", provenance=PROVENANCE)

    assert "scroll" not in spy.calls
    assert "facet" in spy.calls
    assert [hit.printed_page_no for hit in found.hits] == ["75"]


def test_the_superseded_probe_costs_nothing_on_a_hit(published):
    """F9's probe is on the absence path only — a `lookup` that answers pays for no facet."""
    spy = SpyClient(published)

    lookup(spy, PAGES_COLLECTION, EXPECTED["unique_code"], provenance=PROVENANCE,
           runs_collection=RUNS)
    on_a_hit = spy.calls.count("facet")

    spy.calls.clear()
    lookup(spy, PAGES_COLLECTION, "M999999", provenance=PROVENANCE, runs_collection=RUNS)

    # `scope_stats` facets `doc_id` on every call; the probe adds one on `revision`, and only
    # where there was nothing to return.
    assert spy.calls.count("facet") > on_a_hit
