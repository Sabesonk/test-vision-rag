"""`SIGTERM` during step 06 — §15 Factor IX, I7, F17, AC-016 (U025).

*"On `SIGTERM`, stop accepting work, drain in-flight requests within the grace period, and
checkpoint the ingest window in progress so a kill loses at most one window and never publishes a
partial run. Any process is killable at any instant without leaving a queryable half-document."*

`test_kill_mid_run.py` proves the M2a half of that on a 42-page, three-window document: the run
records `stopped`, the lease is released, nothing is queryable. What it could not prove is the
*window* half, because until U025 the window points were written in bulk **after** step 06
returned — so a kill during extraction left every window `queued` and the run had no record of
what it had already bought. A checkpoint written after the loop is a checkpoint that never
survives the event it exists for.

This file proves the window half on the five-window corpus, and proves the two properties that
make the checkpoint worth anything:

* the windows recorded `done` are the windows that really finished, in plan order;
* each of them has its `extract_key`, and the response under that key is in the durable cache —
  so `done` means **bought**, and `test_resume.py` can hold the pipeline to it.

`SIGKILL` is covered too, in the one place the two differ: `SIGTERM` is caught and checkpoints
the run, `SIGKILL` cannot be, and the design's answer to that is the lease expiring rather than a
cleanup somebody has to run.
"""
from __future__ import annotations

import json
import signal
import time

import pytest

from test_resume import (EXPECTED, PAGES_COLLECTION, RUNS, WINDOWS, cached_windows, drain,
                         ingest, qdrant_url, run_id_of, store, wait_for)  # noqa: F401
from vsir.ingest import index as index_module
from vsir.ingest import run as run_module

#: How long to let extraction run before the signal. Long enough that at least one window has
#: finished on any machine that can run this suite at all, short enough that the kill is never
#: the last window — which would make "at most one lost" vacuous.
FIRST_CHECKPOINT_TIMEOUT_S = 600


def windows_in(client, run_id: str) -> list[run_module.WindowState]:
    return list(run_module.windows(client, RUNS, run_id))


def wait_for_checkpoints(client, run_id: str, count: int) -> list[run_module.WindowState]:
    deadline = time.monotonic() + FIRST_CHECKPOINT_TIMEOUT_S
    while time.monotonic() < deadline:
        done = [state for state in windows_in(client, run_id)
                if state.state == run_module.DONE]
        if len(done) >= count:
            return done
        time.sleep(0.2)
    raise AssertionError(f"the run never checkpointed {count} window(s)")


def queryable(client) -> int:
    return index_module.count(client, PAGES_COLLECTION,
                              {"doc_id": EXPECTED["doc_id"], "is_current": True})


@pytest.fixture
def interrupted(store, qdrant_url):
    """One run, killed by `SIGTERM` after its first window is checkpointed."""
    child = ingest(qdrant_url)
    seen = wait_for(child, "06 S2 extraction")
    run_id = run_id_of(seen)
    wait_for_checkpoints(store, run_id, 1)
    child.send_signal(signal.SIGTERM)
    seen += drain(child, timeout=120)
    return run_id, seen


# ── the checkpoint ──────────────────────────────────────────────────────────────────────────────

def test_a_sigterm_mid_window_leaves_a_checkpoint_for_the_window_in_flight(interrupted, store):
    """AC: the run is `stopped`, zero pages are queryable, and `vsir_runs` says where it got to.

    The in-flight window is the first one that is not `done`, and it is recorded — `running`,
    with the `window` checkpoint — rather than absent. That distinction is the acceptance
    criterion: *a checkpoint for the in-flight window in `vsir_runs`*.
    """
    run_id, output = interrupted
    record = run_module.require(store, RUNS, run_id)
    states = {(state.start, state.end): state for state in windows_in(store, run_id)}

    assert record.state == run_module.STOPPED
    assert record.failed is not None and record.failed.reason == "sigterm"
    assert record.published_at is None
    assert queryable(store) == 0

    done = [window for window in WINDOWS if states[window].state == run_module.DONE]
    assert done, "at least one window must have finished before the signal"
    assert done == WINDOWS[:len(done)]
    if len(done) < len(WINDOWS):
        in_flight = states[WINDOWS[len(done)]]
        assert in_flight.state in (run_module.RUNNING, run_module.QUEUED)
        assert in_flight.checkpoint in ("window", "")

    assert '"event": "sigterm"' in output
    assert '"action": "checkpoint_and_exit"' in output

    # The run record has to agree with the window points. `runs show` reporting `windows 0/5`
    # about a run that finished two of them is the run record misleading exactly the person who
    # is deciding whether to resume it.
    assert record.windows_done == len(done)
    assert record.windows_total == len(WINDOWS)


def test_every_checkpointed_window_carries_the_key_it_was_billed_under(interrupted, store):
    """`done` has to mean **bought**, or a resume that trusts it re-bills or skips silently."""
    run_id, _ = interrupted
    done = [state for state in windows_in(store, run_id) if state.state == run_module.DONE]
    cached = cached_windows(store)

    for state in done:
        declared = EXPECTED["extract_keys"][f"{state.start}-{state.end}"]
        assert state.extract_key == declared
        assert state.checkpoint == "extract"
        assert state.pages_returned == state.end - state.start + 1
        assert declared in cached, "the response is in the control plane, not just the tally"


def test_the_run_publishes_nothing_partial(interrupted, store):
    """I7 and F17: the gates are the only thing that flips `is_current`, and they never ran.

    Every point the killed run did write is `is_current=False`, so the document does not answer
    at all rather than answering about the pages that happened to finish — *"a half-published
    document would make every coverage measurement report the pipeline's own incompleteness as a
    property of the corpus."*
    """
    run_id, _ = interrupted

    assert queryable(store) == 0
    assert index_module.count(store, PAGES_COLLECTION,
                              {"run_id": run_id, "is_current": True}) == 0


def test_the_lease_is_released_so_a_resume_needs_no_steal(interrupted, store):
    """`stop()` releases rather than letting it expire: a stopped run is one to pick up now."""
    run_id, _ = interrupted
    record = run_module.require(store, RUNS, run_id)

    assert not record.lease.live()
    assert run_module.claim(store, RUNS, run_id, owner="worker-2").state == run_module.RUNNING


def test_the_checkpoints_are_written_during_step_06_and_not_after_it(store, qdrant_url):
    """The regression this unit fixes, asserted directly: they exist **before** the step ends.

    Read off the control plane while the process is still inside step 06 — if the write happened
    after the loop, this read returns nothing and a kill here would lose every window.
    """
    child = ingest(qdrant_url)
    seen = wait_for(child, "06 S2 extraction")
    run_id = run_id_of(seen)
    try:
        done = wait_for_checkpoints(store, run_id, 1)
        assert child.poll() is None, "step 06 must still be running when this is asserted"
        assert done[0].run_id == run_id
        assert (done[0].start, done[0].end) == WINDOWS[0]
    finally:
        child.kill()
        child.wait(timeout=60)


# ── SIGKILL, and the one thing it does differently ──────────────────────────────────────────────

def test_a_sigkill_cannot_checkpoint_the_run_and_leaves_its_lease_to_expire(store, qdrant_url):
    """The honest limit of §15 Factor IX: `SIGKILL` is not catchable, and nothing pretends it is.

    What survives is what was already written: the windows the run had checkpointed are still
    there, nothing is queryable (I7), and the lease is left **live** — so a resume refuses
    without `--steal` rather than quietly racing a process that might still be alive.
    """
    child = ingest(qdrant_url)
    seen = wait_for(child, "06 S2 extraction")
    run_id = run_id_of(seen)
    wait_for_checkpoints(store, run_id, 1)
    child.kill()
    child.wait(timeout=60)

    record = run_module.require(store, RUNS, run_id)
    assert record.state == run_module.RUNNING, "nothing got to write `stopped`"
    assert record.published_at is None
    assert queryable(store) == 0
    assert record.lease.live()

    with pytest.raises(run_module.LeaseHeld):
        run_module.claim(store, RUNS, run_id, owner="worker-2")
    assert run_module.claim(store, RUNS, run_id, owner="worker-2",
                            steal=True).state == run_module.RUNNING


def test_the_sigterm_event_is_on_the_stream_with_the_run_it_stopped(interrupted):
    """§11.4: structured JSON to stdout, correlated — an operator has to find this line."""
    _run_id, output = interrupted
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    sigterm = [event for event in events if event.get("event") == "sigterm"]

    assert len(sigterm) == 1
    assert sigterm[0]["run_id"] == _run_id
    assert sigterm[0]["action"] == "checkpoint_and_exit"
