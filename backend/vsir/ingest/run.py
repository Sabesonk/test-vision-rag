"""Step 11 — the run control plane, the publish flip and the three-clause retirement (§6.7, §6.9).

Ported with changes from ``impl/app/segjobs.py`` and the publish half of ``impl/app/pipeline.py``.

`impl`'s run state was ``_JOBS: dict[str, SegJob]`` — a module-level dict mutated by daemon threads
(register **E2**). A restart stranded a paid run with no report, no error and nothing to resume
from, and no second process could see it at all. So the state moves to Qdrant, which §4.2 already
makes the only store: **`vsir_runs` holds one point per run and one per window** (D9), plus the
observed-token inventory per document and U010's fingerprint. Every point says which ``kind`` of
control record it is. Nothing correctness-bearing is in process memory or on local disk (§15 VI),
so a second instance can answer `GET /runs/{run_id}` about a run it never executed.

**The lease is advisory, and saying so is the design.** Qdrant has no compare-and-swap, so
``claim`` cannot be a mutual exclusion primitive and pretending otherwise would be worse than not
having one. What makes a duplicated worker *safe* is elsewhere and is structural: ``point_id`` is
``uuid5(page_id)`` so a second writer overwrites rather than doubles (I1), and nothing is queryable
until the gates flip ``is_current`` (I7). A duplicated worker is therefore a **cost** bug, not a
corruption bug — it re-bills windows. The lease is what stops that from happening by accident;
``--steal`` is what lets an operator override it when a worker has died holding one.

**The publish flip, and why it is the ingest pipeline's only writer of ``is_current=True``.**
Step 10 writes every point ``False``, and :func:`vsir.ingest.index.build_point` refuses a record
that arrives claiming otherwise. Here, and only here, a filtered ``set_payload`` flips the run's
points — after the gates pass and never before (I7). It is idempotent (a filter, not a list of
ids, and the same value every time) and it is retried, and ``published_at`` is recorded **only
after it returns**: a recorded publish time in front of a half-applied flip is exactly the
half-finished run F17 names.

*(The one other place a current point is written is `vsir.eval.synthetic.seed`, which seeds M1's
pre-published fixture corpus into an ephemeral `{collection}_synthetic_{dim}` that
`vsir demo exact --synthetic` drops on the way out. It is a fixture loader, not a run: it never
touches the serving collection and there is no pipeline path to it.)*

**Retirement is scoped, and the scope is the whole point (F12 vs F9).** Three clauses, all filter-
based, all idempotent:

1. points of the **same** ``(doc_id, revision)`` from an *earlier* ``run_id`` are **deleted** — that
   is what stops totals doubling and stale pages staying findable (F12);
2. points of the **previously current other revision** are set ``is_current=False`` and **kept** —
   they are what ``found_only_in_superseded`` reads from (F9, exercised at M8);
3. points of any other document are never touched — structural, because every filter here carries
   the document's own ``doc_id``.

A blanket *"delete every point whose ``run_id`` is not the current run"* passes F12's test and
destroys F9's evidence, which is why clause 2 and clause 3 each have their own acceptance test.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field
from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.core import observed_tokens as observed_tokens_module
from vsir.core.ids import NAMESPACE
from vsir.core.record import SCHEMA_VERSION, PageRecord
from vsir.ingest import fingerprint as fingerprint_module
from vsir.ingest import gates as gates_module
from vsir.ingest.gates import GateReport, WindowOutcome

_log = vsir_logging.get_logger(__name__)

#: The ``kind`` discriminators in `vsir_runs`, beside U010's ``fingerprint``.
KIND_RUN = "run"
KIND_WINDOW = "window"
KIND_INVENTORY = "observed_tokens"
KINDS: tuple[str, ...] = (KIND_RUN, KIND_WINDOW, KIND_INVENTORY)

#: §6.9 — the run states. ``stopped`` is what a SIGTERM leaves behind (§15 Factor IX) and is the
#: only state ``--resume`` accepts without ``--steal``.
QUEUED, RUNNING, STOPPED, GATED, PUBLISHED, FAILED = (
    "queued", "running", "stopped", "gated", "published", "failed")
RUN_STATES: tuple[str, ...] = (QUEUED, RUNNING, STOPPED, GATED, PUBLISHED, FAILED)

#: A **window's** states, which are not a run's. A window is not `gated` or `published` — those are
#: judgements about a document — and the state that matters for `--resume` is whether this window's
#: work is `done` and can be skipped (U025) or has to be re-billed.
DONE = "done"
WINDOW_STATES: tuple[str, ...] = (QUEUED, RUNNING, DONE, FAILED)
#: The states ``vsir ingest --resume`` will take over without ``--steal`` — §6.9 names exactly one:
#: *"`stopped` is what a `SIGTERM` leaves behind and is the only state `--resume` accepts without
#: `--steal`."* Everything else is either somebody's live work (`running`, `queued`), a judgement
#: that a resume would silently re-litigate (`gated`), a run that failed for a reason nobody has
#: read yet (`failed`), or a document already serving (`published`). `--steal` takes any of them,
#: which is what makes taking one a decision rather than an accident.
RESUMABLE: tuple[str, ...] = (STOPPED,)

#: How long a claimed lease is believed for. Renewed as the run makes progress, so a worker that
#: dies stops renewing and the lease expires rather than having to be cleaned up by anything.
LEASE_SECONDS = 300

#: The control-plane payload keys that need an index, beyond the two U010 creates. Filtered scrolls
#: over `vsir_runs` are how `runs show`, `gates rerun` and the metrics endpoint read it, and an
#: unindexed filter is a scan that gets slower with every run ever recorded (F10's cousin).
CONTROL_INDEXES: dict[str, Any] = {
    "run_id": qm.PayloadSchemaType.KEYWORD,
    "doc_id": qm.PayloadSchemaType.KEYWORD,
    "revision": qm.PayloadSchemaType.KEYWORD,
    "state": qm.PayloadSchemaType.KEYWORD,
}

#: Scroll page size for the control plane and for the export's read-back of the index.
SCROLL_BATCH = 256

#: How many times a filtered write is retried before the run is failed, and the wait between them.
#: Small and finite: a `set_payload` that fails three times is an outage, and a publish that hangs
#: retrying is a half-finished run that never says so.
WRITE_ATTEMPTS = 3
WRITE_BACKOFF_S = 0.25


def now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or now()).isoformat()


class RunRefused(RuntimeError):
    """A typed refusal from the control plane. Nothing partial is left behind one."""

    code = "run_refused"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


class LeaseHeld(RunRefused):
    """Another worker holds a live lease on this run (D9). ``--steal`` is the override."""

    code = "lease_held"


class RunNotFound(RunRefused):
    """No run point with that id. A typed 404, never an empty run record."""

    code = "run_not_found"


class RunNotResumable(RunRefused):
    """The run is not in a state a resume may take over (§6.9). ``--steal`` is the override.

    Separate from :class:`LeaseHeld` because the two say different things and want different
    answers. A live lease means *another worker is probably on this*; a wrong state means *this
    run is not waiting to be continued* — resuming a `published` run would re-run every step
    against a document that is already serving, and resuming a `running` one whose lease merely
    expired is the duplicate-worker case the lease is there to make deliberate.
    """

    code = "run_not_resumable"


class GateBlocked(RunRefused):
    """A blocking gate failed and was not overridden — nothing is flipped (I7, §11.1)."""

    code = "publish_blocked"


class StoreUnavailable(RunRefused):
    """Qdrant did not answer a control-plane write after :data:`WRITE_ATTEMPTS` (§11.3)."""

    code = "qdrant_unavailable"


# ── the models of §6.9 ───────────────────────────────────────────────────────────────────────────

class Lease(BaseModel):
    """Who is working on this run, and until when. Advisory — see the module docstring."""

    model_config = ConfigDict(extra="forbid")

    owner: str = ""
    expires_at: str = ""

    def live(self, moment: datetime | None = None) -> bool:
        if not self.owner or not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return False
        return expiry > (moment or now())


class Override(BaseModel):
    """One released gate, why, and by whom (§6.9, §11.1)."""

    model_config = ConfigDict(extra="forbid")

    gate: str
    reason: str
    by: str = ""
    at: str = ""


class Failure(BaseModel):
    """Which step failed and why — so a failed run says more than ``state: failed``."""

    model_config = ConfigDict(extra="forbid")

    step: str
    reason: str
    detail: str = ""


class Cost(BaseModel):
    """What the run spent (register **E4**: `impl` counted nothing, in a pipeline organised
    entirely around what is billed). Cache hits are here because they are the number that says a
    replayed run cost nothing, which is the claim D10 makes."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0
    vlm_calls: int = 0
    embeddings_billed: int = 0
    embeddings_reused: int = 0


class RunRecord(BaseModel):
    """The run record of §6.9 — the payload of the run point, and the `GET /runs/{run_id}` body.

    One model for both, deliberately: a separate response shape would be a second definition of
    what a run *is*, and the first time they drift the endpoint starts describing a run that the
    pipeline never writes.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    doc_id: str
    revision: str
    release_id: str = ""
    state: str = QUEUED
    step: str = ""
    windows_done: int = 0
    windows_total: int = 0
    pages_indexed: int = 0
    page_count: int = 0
    #: SHA-256 of the source PDF, from step 02's probe. Recorded because nothing else could name
    #: the bytes behind `doc_id@revision`: the page payload deliberately carries no path (§5.3,
    #: register A5) and the store is keyed by document identity, so this is the only thing that
    #: can tell a re-ingested file from the one these pages were indexed from. `ingest/store.py`
    #: refuses to serve bytes that disagree with it rather than rendering a page nobody indexed.
    content_hash: str = ""
    gate_results: dict[str, dict] = Field(default_factory=dict)
    overrides: list[Override] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    published_at: str | None = None
    lease: Lease = Field(default_factory=Lease)
    failed: Failure | None = None
    cost: Cost = Field(default_factory=Cost)
    collection: str = ""
    schema_version: int = SCHEMA_VERSION
    started_at: str = ""
    updated_at: str = ""
    #: What retirement did when this run published — the F12/F9 evidence, kept beside the run.
    retired: dict[str, Any] = Field(default_factory=dict)

    @property
    def report(self) -> GateReport:
        return GateReport.from_mapping(self.gate_results)

    @property
    def overridden(self) -> tuple[str, ...]:
        return tuple(override.gate for override in self.overrides)

    def to_payload(self) -> dict[str, Any]:
        return {"kind": KIND_RUN, **self.model_dump(mode="json")}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RunRecord":
        return cls.model_validate({k: v for k, v in payload.items() if k != "kind"})


class WindowState(BaseModel):
    """§6.7's window point: ``{state, attempts, checkpoint, extract_key}``, plus its span.

    ``checkpoint`` is the last step this window completed. It is what makes ``--resume`` able to
    skip a window that is already derived rather than re-billing it (U025), and it is why the
    window is a point of its own instead of a list inside the run: a 1,440-page manual has more
    windows than belong in one payload, and each is written as it finishes.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    doc_id: str
    start: int
    end: int
    state: str = QUEUED
    attempts: int = 0
    checkpoint: str = ""
    extract_key: str = ""
    pages_returned: int = 0
    offset_ok: bool = True
    check: str = ""
    detail: str = ""
    bisected: bool = False
    updated_at: str = ""

    @property
    def window(self) -> list[int]:
        return [self.start, self.end]

    def outcome(self) -> WindowOutcome:
        """The gate's view of this window (§11.1 `offset_check`)."""
        return WindowOutcome(start=self.start, end=self.end, pages_returned=self.pages_returned,
                             offset_ok=self.offset_ok, check=self.check, detail=self.detail,
                             bisected=self.bisected, attempts=max(self.attempts, 1))

    def to_payload(self) -> dict[str, Any]:
        return {"kind": KIND_WINDOW, "window": self.window, **self.model_dump(mode="json")}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "WindowState":
        return cls.model_validate({k: v for k, v in payload.items()
                                   if k not in ("kind", "window")})


# ── point ids: derived, so every write in this module is idempotent ──────────────────────────────

def run_point_id(run_id: str) -> str:
    if not run_id:
        raise ValueError("a run point needs a run_id")
    return str(uuid.uuid5(NAMESPACE, f"vsir:run:{run_id}"))


def window_point_id(run_id: str, start: int, end: int) -> str:
    if not run_id:
        raise ValueError("a window point needs a run_id")
    return str(uuid.uuid5(NAMESPACE, f"vsir:window:{run_id}:{start}-{end}"))


def inventory_point_id(doc_id: str) -> str:
    """§6.8 — the observed-token inventory lives on the **document's** control point.

    Per document rather than per run: it is the corpus fact *"which code-like tokens does this
    document's text layer carry"*, and `present_instead` asks it about a document, not about the
    run that last ingested one.
    """
    if not doc_id:
        raise ValueError("an inventory point needs a doc_id")
    return str(uuid.uuid5(NAMESPACE, f"vsir:observed_tokens:{doc_id}"))


# ── the collection ───────────────────────────────────────────────────────────────────────────────

def ensure_control_plane(client: Any, runs_collection: str) -> bool:
    """Create `vsir_runs` and every payload index the control plane filters on.

    Additive over :func:`vsir.ingest.fingerprint.ensure_control_collection`, which creates the
    collection and the two indexes U010 needs. The missing ones are created here rather than there
    because they are read back from the live schema first: an index that already exists is not
    re-created on every run, and a collection made by an earlier release still gains them.
    """
    created = fingerprint_module.ensure_control_collection(client, runs_collection)
    schema = {} if created else (client.get_collection(runs_collection).payload_schema or {})
    for field_name, field_schema in CONTROL_INDEXES.items():
        if field_name not in schema:
            client.create_payload_index(runs_collection, field_name=field_name,
                                        field_schema=field_schema)
    return created


def _retry(operation: Callable[[], Any], *, what: str,
           attempts: int = WRITE_ATTEMPTS, backoff: float = WRITE_BACKOFF_S,
           sleep: Callable[[float], None] = time.sleep) -> Any:
    """Run an **idempotent** filtered write, retrying a store failure (§11.3).

    Only ever wrapped around writes that can be repeated with no different outcome — a filtered
    ``set_payload`` with a constant value, a filtered ``delete``, a keyed ``upsert``. A retry of
    anything else would turn one outage into two writes.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as failure:  # noqa: BLE001 — anything here is "the store did not answer"
            last = failure
            _log.warning("control_write_retry", what=what, attempt=attempt, attempts=attempts,
                         detail=f"{type(failure).__name__}: {failure}")
            if attempt < attempts:
                sleep(backoff * attempt)
    raise StoreUnavailable(
        f"{what} did not complete after {attempts} attempts: {type(last).__name__}: {last}. "
        f"Nothing partial was recorded — published_at is written only after the flip returns, so "
        f"a run that could not publish reports itself unpublished rather than half-published",
        what=what, attempts=attempts) from last


# ── reading and writing the run point ────────────────────────────────────────────────────────────

def save(client: Any, runs_collection: str, record: RunRecord) -> RunRecord:
    """Upsert the run point. The id is derived from ``run_id``, so this is idempotent."""
    stamped = record.model_copy(update={"updated_at": _stamp()})

    def write() -> None:
        # Inside the retry, not before it: `ensure_control_plane` is idempotent, and an
        # unreachable store must surface as one typed `qdrant_unavailable` rather than as
        # whichever raw client exception happened to be raised first (§11.3).
        ensure_control_plane(client, runs_collection)
        client.upsert(collection_name=runs_collection,
                      points=[qm.PointStruct(id=run_point_id(stamped.run_id), vector={},
                                             payload=stamped.to_payload())], wait=True)

    _retry(write, what="run_point_upsert")
    return stamped


def load(client: Any, runs_collection: str, run_id: str) -> RunRecord | None:
    """The run record, or ``None`` when there is no such run. Never a fabricated empty one."""
    if not client.collection_exists(runs_collection):
        return None
    found = client.retrieve(runs_collection, ids=[run_point_id(run_id)], with_payload=True)
    if not found:
        return None
    payload = found[0].payload or {}
    if payload.get("kind") != KIND_RUN:
        raise RunRefused(f"control point for {run_id!r} is a {payload.get('kind')!r} record",
                         run_id=run_id, kind=payload.get("kind"))
    return RunRecord.from_payload(payload)


def require(client: Any, runs_collection: str, run_id: str) -> RunRecord:
    record = load(client, runs_collection, run_id)
    if record is None:
        raise RunNotFound(f"no run {run_id!r} in {runs_collection}", run_id=run_id)
    return record


def start(client: Any, runs_collection: str, *, run_id: str, doc_id: str, revision: str,
          release_id: str, collection: str, page_count: int = 0, windows_total: int = 0,
          owner: str = "", lease_seconds: int = LEASE_SECONDS) -> RunRecord:
    """Open a run: claim the lease and record it as ``running`` before any work happens.

    Written **before** the first window rather than after the last, which is the whole difference
    from `impl`: a run that dies mid-flight is a run that exists, in a state that says so, with a
    lease that expires. A run recorded only on completion is one that a crash erases (register E2).
    """
    record = RunRecord(
        run_id=run_id, doc_id=doc_id, revision=revision, release_id=release_id,
        collection=collection, page_count=page_count, windows_total=windows_total,
        state=RUNNING, step="manifest", started_at=_stamp(),
        lease=Lease(owner=owner, expires_at=_stamp(now() + timedelta(seconds=lease_seconds))),
    )
    saved = save(client, runs_collection, record)
    _log.info("run_started", run_id=run_id, doc_id=doc_id, revision=revision, state=RUNNING,
              windows_total=windows_total, lease_owner=owner)
    return saved


def claim(client: Any, runs_collection: str, run_id: str, *, owner: str, steal: bool = False,
          lease_seconds: int = LEASE_SECONDS) -> RunRecord:
    """Take the lease on an existing run — ``--resume``'s first move (D9, §6.9).

    Refuses a **live** lease unless ``steal`` is passed. That is the whole enforcement: the lease
    is advisory, so this is a guard against a second worker being started by accident, not a
    mutual-exclusion primitive. What makes the accident harmless if it happens anyway is I1 and
    I7, not this function.

    Then it refuses a run whose **state** is not :data:`RESUMABLE` — §6.9's *"`stopped` … is the
    only state `--resume` accepts without `--steal`"*. The two checks are in this order because
    they answer different questions and the lease's is the more urgent: *"somebody else is on
    this"* has to be said before *"and it is not in the right state anyway"*, or an operator
    racing a live worker is told about a state machine instead of about the worker.
    """
    record = require(client, runs_collection, run_id)
    if record.lease.live() and record.lease.owner != owner and not steal:
        raise LeaseHeld(
            f"run {run_id} is leased by {record.lease.owner!r} until {record.lease.expires_at} "
            f"(state {record.state!r}). Pass --steal to take it: the lease is advisory, so a "
            f"duplicated worker re-bills windows but cannot corrupt the index — point_id is "
            f"idempotent (I1) and nothing is queryable until the gates flip is_current (I7)",
            run_id=run_id, owner=record.lease.owner, expires_at=record.lease.expires_at,
            state=record.state)
    if record.state not in RESUMABLE and not steal:
        raise RunNotResumable(
            f"run {run_id} is {record.state!r} and --resume takes over {list(RESUMABLE)} "
            f"(§6.9): a resume re-runs every step under this run's id, which for a "
            f"{record.state!r} run is either work somebody else is doing or a judgement already "
            f"recorded. Pass --steal to take it anyway",
            run_id=run_id, state=record.state, resumable=list(RESUMABLE))
    taken = record.model_copy(update={
        "state": RUNNING,
        # The previous stop is **cleared**, not carried. A run that is running again has not
        # failed, and a `published` record still reporting `failed: sigterm` is the run record
        # telling an operator two contradictory things about the same run — the stop is in the
        # event stream (`run_stopped`), which is where the history belongs (§11.4).
        "failed": None,
        "lease": Lease(owner=owner, expires_at=_stamp(now() + timedelta(seconds=lease_seconds))),
    })
    _log.info("run_lease_claimed", run_id=run_id, owner=owner, stolen=bool(
        steal and record.lease.live() and record.lease.owner != owner),
        previous_owner=record.lease.owner, previous_state=record.state)
    return save(client, runs_collection, taken)


def renew(client: Any, runs_collection: str, record: RunRecord, *,
          lease_seconds: int = LEASE_SECONDS, **progress: Any) -> RunRecord:
    """Extend the lease and record progress in one write. Called as each step finishes."""
    updated = record.model_copy(update={
        **progress,
        "lease": Lease(owner=record.lease.owner,
                       expires_at=_stamp(now() + timedelta(seconds=lease_seconds))),
    })
    return save(client, runs_collection, updated)


def stop(client: Any, runs_collection: str, record: RunRecord, *, reason: str = "sigterm",
         step: str = "") -> RunRecord:
    """SIGTERM: stop accepting work, record ``stopped``, release the lease (§15 Factor IX, F17).

    The lease is released rather than left to expire, because a stopped run is one a resume should
    be able to pick up immediately — and because a lease outliving the process that held it is
    what makes an operator reach for ``--steal`` when they should not have to.
    """
    stopped = record.model_copy(update={
        "state": STOPPED, "step": step or record.step, "lease": Lease(),
        "failed": Failure(step=step or record.step, reason=reason,
                          detail="stopped in flight; nothing was published"),
    })
    saved = save(client, runs_collection, stopped)
    _log.info("run_stopped", run_id=record.run_id, reason=reason, step=saved.step,
              published=False)
    return saved


def fail(client: Any, runs_collection: str, record: RunRecord, *, step: str, reason: str,
         detail: str = "") -> RunRecord:
    """Record a failed run and release the lease. Nothing is published, nothing is queryable."""
    failed = record.model_copy(update={
        "state": FAILED, "step": step, "lease": Lease(),
        "failed": Failure(step=step, reason=reason, detail=detail),
    })
    saved = save(client, runs_collection, failed)
    _log.error("run_failed", run_id=record.run_id, step=step, reason=reason, detail=detail)
    return saved


# ── window points ────────────────────────────────────────────────────────────────────────────────

def note_window(client: Any, runs_collection: str, state: WindowState) -> WindowState:
    """Write one window point. Idempotent by ``(run_id, start, end)``."""
    stamped = state.model_copy(update={"updated_at": _stamp()})

    def write() -> None:
        ensure_control_plane(client, runs_collection)
        client.upsert(collection_name=runs_collection,
                      points=[qm.PointStruct(
                          id=window_point_id(stamped.run_id, stamped.start, stamped.end),
                          vector={}, payload=stamped.to_payload())], wait=True)

    _retry(write, what="window_point_upsert")
    return stamped


def windows(client: Any, runs_collection: str, run_id: str) -> tuple[WindowState, ...]:
    """Every window point of a run, in page order — what `gates rerun` reads for `offset_check`."""
    found = _scroll(client, runs_collection,
                    qm.Filter(must=[qm.FieldCondition(key="kind", match=qm.MatchValue(
                        value=KIND_WINDOW)),
                        qm.FieldCondition(key="run_id", match=qm.MatchValue(value=run_id))]))
    states = [WindowState.from_payload(payload) for payload in found]
    return tuple(sorted(states, key=lambda state: (state.start, state.end)))


def _scroll(client: Any, collection: str, scroll_filter: qm.Filter | None,
            *, batch: int = SCROLL_BATCH) -> list[dict[str, Any]]:
    """Every matching payload. Paged, because a control plane with a year of runs in it is big."""
    payloads: list[dict[str, Any]] = []
    offset: Any = None
    while True:
        page, offset = client.scroll(collection, scroll_filter=scroll_filter, limit=batch,
                                     offset=offset, with_payload=True, with_vectors=False)
        payloads.extend((point.payload or {}) for point in page)
        if offset is None:
            break
    return payloads


# ── the observed-token inventory (§6.8, C7) ──────────────────────────────────────────────────────

def write_inventory(client: Any, runs_collection: str, *, doc_id: str, revision: str, run_id: str,
                    records: Sequence[PageRecord]) -> int:
    """Store the document's observed code-like tokens on its control point (§6.8, D9).

    Built from ``text`` and from nothing else, over the **searchable** pages only: a page whose
    text layer nobody may be shown as evidence must not be volunteering codes beside an `absent`
    verdict either (§5.7). Both rules are `core/observed_tokens.py`'s and are called, not
    re-implemented — this function is the writer §6.8 says the inventory was missing.
    """
    searchable = [record for record in records if observed_tokens_module.is_searchable(record)]
    inventory = observed_tokens_module.from_texts(doc_id, (record.text for record in searchable))

    def write() -> None:
        ensure_control_plane(client, runs_collection)
        client.upsert(collection_name=runs_collection, points=[qm.PointStruct(
            id=inventory_point_id(doc_id), vector={}, payload={
                "kind": KIND_INVENTORY, "doc_id": doc_id, "revision": revision, "run_id": run_id,
                "tokens": list(inventory.tokens), "token_count": len(inventory.tokens),
                "pages": len(searchable), "updated_at": _stamp()})], wait=True)

    _retry(write, what="inventory_upsert")
    # `observed=` rather than `tokens=`: the log redactor matches token-shaped field names
    # (`logging.redact`), and an inventory size reported as `***` is a count nobody can read.
    _log.info("observed_tokens_written", doc_id=doc_id, revision=revision, run_id=run_id,
              observed=len(inventory.tokens), pages_contributing=len(searchable))
    return len(inventory.tokens)


def read_inventory(client: Any, runs_collection: str,
                   doc_id: str) -> observed_tokens_module.Inventory | None:
    """The stored inventory for one document, or ``None`` if none has been written."""
    if not client.collection_exists(runs_collection):
        return None
    found = client.retrieve(runs_collection, ids=[inventory_point_id(doc_id)], with_payload=True)
    if not found:
        return None
    payload = found[0].payload or {}
    return observed_tokens_module.Inventory(doc_id=doc_id,
                                            tokens=tuple(payload.get("tokens") or ()))


def inventories(client: Any, runs_collection: str,
                doc_ids: Iterable[str] = ()) -> Iterator[dict[str, Any]]:
    """Every stored inventory, optionally restricted to ``doc_ids`` — the §6.8 export's source."""
    wanted = list(doc_ids)
    must: list[qm.Condition] = [qm.FieldCondition(key="kind",
                                                  match=qm.MatchValue(value=KIND_INVENTORY))]
    if wanted:
        must.append(qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=wanted)))
    for payload in sorted(_scroll(client, runs_collection, qm.Filter(must=must)),
                          key=lambda row: str(row.get("doc_id", ""))):
        yield payload


# ── publish (I7) and retirement (§6.7) ───────────────────────────────────────────────────────────

def _page_filter(doc_id: str, revision: str | None = None, run_id: str | None = None,
                 *, is_current: bool | None = None) -> qm.Filter:
    """A filter over the pages collection. **Always carries ``doc_id``** — that is clause 3.

    Retirement's third clause — *points of any other document are never touched* — is not a check
    somewhere, it is the fact that no filter this module builds can omit the document.
    """
    must: list[qm.Condition] = [qm.FieldCondition(key="doc_id",
                                                  match=qm.MatchValue(value=doc_id))]
    if revision is not None:
        must.append(qm.FieldCondition(key="revision", match=qm.MatchValue(value=revision)))
    if run_id is not None:
        must.append(qm.FieldCondition(key="run_id", match=qm.MatchValue(value=run_id)))
    if is_current is not None:
        must.append(qm.FieldCondition(key="is_current", match=qm.MatchValue(value=is_current)))
    return qm.Filter(must=must)


def _count(client: Any, collection: str, query: qm.Filter) -> int:
    if not client.collection_exists(collection):
        return 0
    return client.count(collection, count_filter=query, exact=True).count


def flip_current(client: Any, collection: str, *, doc_id: str, revision: str,
                 run_id: str) -> int:
    """The publish flip: ``is_current=True`` for this run's points, by filter (I7, §6.7).

    A **filter**, not a list of point ids, for two reasons. It is idempotent — running it twice
    sets the same value on the same set — and it cannot half-apply because of something the
    calling process forgot to hold: the set is defined by what is in the index, not by a list
    assembled in memory before the flip started.
    """
    query = _page_filter(doc_id, revision, run_id)
    _retry(lambda: client.set_payload(collection_name=collection, payload={"is_current": True},
                                      points=query, wait=True), what="publish_flip")
    flipped = _count(client, collection, _page_filter(doc_id, revision, run_id, is_current=True))
    _log.info("publish_flip", collection=collection, doc_id=doc_id, revision=revision,
              run_id=run_id, is_current=flipped)
    return flipped


def stamp_flags(client: Any, collection: str, *, doc_id: str, revision: str, run_id: str,
                flags: Sequence[str]) -> int:
    """Add ``flags`` to ``content.flags`` on every page of the run, keeping what is already there.

    Grouped by the flag set a page ends up with, so a 1,440-page manual costs a handful of writes
    rather than 1,440 — and the per-page flags derivation put there (``ungrounded_codes``,
    ``label_ambiguous``, …) survive, which a single filtered write of one constant list would
    silently erase.
    """
    if not flags:
        return 0
    pages = _scroll(client, collection, _page_filter(doc_id, revision, run_id))
    groups: dict[tuple[str, ...], list[str]] = {}
    for payload in pages:
        content = payload.get("content") or {}
        existing = list(content.get("flags") or [])
        merged = tuple(dict.fromkeys([*existing, *flags]))
        if merged != tuple(existing):
            groups.setdefault(merged, []).append(
                str((payload.get("provenance") or {}).get("page_id", "")))
    stamped = 0
    for merged, page_ids in groups.items():
        point_ids = [str(uuid.uuid5(NAMESPACE, page_id)) for page_id in page_ids if page_id]
        if not point_ids:
            continue
        _retry(lambda ids=point_ids, value=list(merged): client.set_payload(
            collection_name=collection, payload={"flags": value}, points=ids, key="content",
            wait=True), what="flag_stamp")
        stamped += len(point_ids)
    _log.info("page_flags_stamped", collection=collection, doc_id=doc_id, revision=revision,
              run_id=run_id, flags=list(flags), pages=stamped)
    return stamped


def retire(client: Any, collection: str, *, doc_id: str, revision: str,
           run_id: str) -> dict[str, Any]:
    """§6.7's three clauses. Filter-based, idempotent, and **scoped** — see the module docstring.

    Returns what each clause did, which goes into the run record: the evidence for F12 (the delete
    happened) and for F9 (the other revision was kept) is the same record, so neither can be
    claimed without the other being visible.
    """
    superseded_query = qm.Filter(
        must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id)),
              qm.FieldCondition(key="is_current", match=qm.MatchValue(value=True))],
        must_not=[qm.FieldCondition(key="revision", match=qm.MatchValue(value=revision))])
    superseded_before = _count(client, collection, superseded_query)

    # Clause 1 — earlier runs of the SAME (doc_id, revision) are deleted (F12).
    stale_query = qm.Filter(
        must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id)),
              qm.FieldCondition(key="revision", match=qm.MatchValue(value=revision))],
        must_not=[qm.FieldCondition(key="run_id", match=qm.MatchValue(value=run_id))])
    stale = _count(client, collection, stale_query)
    if stale:
        _retry(lambda: client.delete(collection_name=collection,
                                     points_selector=stale_query, wait=True),
               what="retire_stale_points")

    # Clause 2 — the previously current OTHER revision is demoted and KEPT (F9). A delete here
    # would satisfy F12 by destroying the evidence `found_only_in_superseded` reads from.
    if superseded_before:
        _retry(lambda: client.set_payload(collection_name=collection,
                                          payload={"is_current": False},
                                          points=superseded_query, wait=True),
               what="retire_supersede")
    kept = _count(client, collection,
                  qm.Filter(must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(
                      value=doc_id))],
                      must_not=[qm.FieldCondition(key="revision",
                                                  match=qm.MatchValue(value=revision))]))
    report = {"deleted_stale_points": stale, "superseded_demoted": superseded_before,
              "other_revision_points_kept": kept}
    _log.info("retirement", collection=collection, doc_id=doc_id, revision=revision,
              run_id=run_id, **report)
    return report


def retire_document(client: Any, collection: str, *, doc_id: str,
                    revision: str | None = None) -> dict[str, Any]:
    """`vsir retire <doc_id> [--revision]` — withdraw a document from service (§4.4, U025).

    **Demotion, never deletion.** Every page of the document (or of the one revision named) is set
    ``is_current=False`` and kept, exactly as §6.7 clause 2 keeps a superseded revision: the pages
    stop answering, and what is still recorded about them is what a `found_only_in_superseded`
    can surface and what an audit of a past answer can be checked against. A retirement that
    deleted would make every citation a reader already holds unverifiable.

    It replaces `impl`'s ``DELETE /api/v1/documents/{doc_id}`` (§2.5 A), and the move from a route
    to a subcommand is the point: withdrawing a document is an **operator** action, not a
    caller's, so it is a one-off admin process run from the same image as `web` and
    `ingest-worker` (§15 Factor XII) rather than a verb any bearer token can reach.

    Idempotent — it is a filtered write of a constant, so running it twice sets the same value on
    the same set and the second call reports ``retired: 0`` because there was nothing current left
    to demote. Scoped, on the same terms as :func:`retire`: :func:`_page_filter` cannot be built
    without a ``doc_id``, so clause 3 — *points of any other document are never touched* — is
    structural here too rather than a check somebody could forget.
    """
    current = _page_filter(doc_id, revision, is_current=True)
    retired = _count(client, collection, current)
    if retired:
        _retry(lambda: client.set_payload(collection_name=collection,
                                          payload={"is_current": False},
                                          points=current, wait=True),
               what="retire_document")
    kept = _count(client, collection, _page_filter(doc_id, revision))
    still_current = _count(client, collection, _page_filter(doc_id, is_current=True))
    report = {"doc_id": doc_id, "revision": revision or "", "retired": retired, "kept": kept,
              "still_current": still_current}
    _log.info("document_retired", collection=collection, **report)
    return report


def publish(client: Any, *, runs_collection: str, collection: str, record: RunRecord,
            report: GateReport, records: Sequence[PageRecord] = (),
            by: str = "") -> RunRecord:
    """Step 11: gate, flip, stamp, retire, count, record — in that order, and only in that order.

    The ordering is the invariant. Gates first, because I7 is *"a run that has not passed its
    gates cannot answer"*. ``published_at`` last, because it is the claim that the flip completed
    and a claim written in front of the act is what F17 is about. Retirement in between, because a
    stale point deleted before the new one is current is a window in which the document is not in
    the index at all.
    """
    decision = gates_module.decide(report, record.overridden)
    if not decision.publish:
        held = record.model_copy(update={
            "state": GATED, "step": "gates", "gate_results": report.as_dict(),
            "flags": list(decision.flags), "lease": Lease(),
        })
        saved = save(client, runs_collection, held)
        _log.warning("publish_blocked", run_id=record.run_id, doc_id=record.doc_id,
                     blocked_by=list(decision.blocked_by), queryable=0)
        raise GateBlocked(
            f"{record.doc_id}@{record.revision}: {list(decision.blocked_by)} blocked the publish. "
            f"The run's points stay is_current=False, so zero pages of this document are "
            f"queryable (I7) — a half-published document would make every coverage measurement "
            f"report the pipeline's own incompleteness as a property of the corpus",
            run_id=record.run_id, doc_id=record.doc_id, revision=record.revision,
            blocked_by=list(decision.blocked_by), gate_results=saved.gate_results)

    flipped = flip_current(client, collection, doc_id=record.doc_id, revision=record.revision,
                           run_id=record.run_id)
    if decision.flags:
        stamp_flags(client, collection, doc_id=record.doc_id, revision=record.revision,
                    run_id=record.run_id, flags=decision.flags)
    retired = retire(client, collection, doc_id=record.doc_id, revision=record.revision,
                     run_id=record.run_id)
    if records:
        write_inventory(client, runs_collection, doc_id=record.doc_id, revision=record.revision,
                        run_id=record.run_id, records=records)

    current = _count(client, collection,
                     _page_filter(record.doc_id, record.revision, is_current=True))
    published = record.model_copy(update={
        "state": PUBLISHED, "step": "publish", "gate_results": report.as_dict(),
        "flags": list(decision.flags), "pages_indexed": current,
        "published_at": _stamp(), "retired": retired, "lease": Lease(),
    })
    saved = save(client, runs_collection, published)
    _log.info("published", run_id=record.run_id, doc_id=record.doc_id, revision=record.revision,
              pages_indexed=current, flipped=flipped, overrides=list(record.overridden),
              flags=list(decision.flags), by=by or record.lease.owner, **retired)
    return saved


def override(record: RunRecord, *, gate: str, reason: str, by: str) -> RunRecord:
    """Add an override to a run record. Refuses a gate that does not take one (§11.1, §4.4)."""
    gates_module.check_override(gate, reason)
    already = {existing.gate for existing in record.overrides}
    if gate in already:
        return record
    return record.model_copy(update={
        "overrides": [*record.overrides, Override(gate=gate, reason=reason.strip(), by=by,
                                                  at=_stamp())],
    })


# ── reading a run's pages back, and §11.4's gauges ───────────────────────────────────────────────

def run_records(client: Any, collection: str, *, doc_id: str, revision: str,
                run_id: str) -> tuple[PageRecord, ...]:
    """The run's pages, read **out of the index** — what `gates rerun` re-evaluates against.

    Reading them back rather than being handed them is what makes the re-evaluation honest: the
    gates then judge the document that is actually stored, not the one the ingesting process
    believed it stored.
    """
    payloads = _scroll(client, collection, _page_filter(doc_id, revision, run_id))
    found = [PageRecord.from_payload(payload) for payload in payloads]
    return tuple(sorted(found, key=lambda record: record.page_no))


def runs(client: Any, runs_collection: str, *, doc_id: str = "",
         state: str = "") -> tuple[RunRecord, ...]:
    """Every run point, newest first. ``run_id`` is a ULID, so id order **is** time order."""
    if not client.collection_exists(runs_collection):
        return ()
    must: list[qm.Condition] = [qm.FieldCondition(key="kind", match=qm.MatchValue(value=KIND_RUN))]
    if doc_id:
        must.append(qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id)))
    if state:
        must.append(qm.FieldCondition(key="state", match=qm.MatchValue(value=state)))
    found = [RunRecord.from_payload(payload)
             for payload in _scroll(client, runs_collection, qm.Filter(must=must))]
    return tuple(sorted(found, key=lambda record: record.run_id, reverse=True))


def gauges(client: Any, runs_collection: str) -> dict[str, Any]:
    """§11.4's two gauges, computed from the control plane rather than from process counters.

    A counter incremented in memory would be a different number on every instance and would reset
    on every deploy (§15 Factor VI). These are derived from `vsir_runs`, so any instance answers
    the same thing and a scrape after a restart is not a hole in the series.
    """
    grounded: dict[str, float] = {}
    failures: dict[str, int] = {gate: 0 for gate in gates_module.GATES}
    for record in sorted(runs(client, runs_collection), key=lambda item: item.run_id):
        for name, row in record.gate_results.items():
            if not row.get("pass", True) and not row.get("skipped", False) \
                    and row.get("blocking", False):
                failures[name] = failures.get(name, 0) + 1
        median = (record.gate_results.get(gates_module.GROUNDED_RATE) or {}).get("metric")
        if record.state == PUBLISHED and isinstance(median, (int, float)):
            grounded[record.doc_id] = float(median)
    return {"ingest_grounded_rate_median": grounded, "ingest_gate_failures_total": failures}


__all__ = [
    "CONTROL_INDEXES", "DONE", "FAILED", "GATED", "KINDS", "KIND_INVENTORY", "KIND_RUN", "KIND_WINDOW",
    "LEASE_SECONDS", "PUBLISHED", "QUEUED", "RESUMABLE", "RUNNING", "RUN_STATES", "STOPPED", "WINDOW_STATES",
    "Cost", "Failure", "GateBlocked", "Lease", "LeaseHeld", "Override", "RunNotFound",
    "RunRecord", "RunRefused", "StoreUnavailable", "WindowState", "claim", "ensure_control_plane",
    "fail", "flip_current", "gauges", "inventories", "inventory_point_id", "load", "note_window",
    "override", "publish", "read_inventory", "renew", "require", "retire", "run_point_id",
    "run_records", "runs", "save", "stamp_flags", "start", "stop", "window_point_id", "windows",
    "write_inventory",
]
