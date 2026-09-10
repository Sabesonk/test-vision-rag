"""The per-caller `read` quota, and ``reads_remaining`` on every envelope (Spec §7.3, §11.3).

Net new. `impl` had no quota of any kind on the one endpoint that spends money, and no auth in
front of it either (register **E5**) — so the cost ceiling of the previous system was the
project's Gemini billing alert.

**A quota that lives in process memory is not a quota.** `web` scales horizontally by construction
(§15 Factor VI/VIII), so a counter in a dict is N counters, one per replica, each of which resets
on every deploy: three replicas turn ``VSIR_READ_QUOTA=50`` into 150, and a rolling restart turns
it into unbounded. So the ledger is a point in the `vsir_runs` control plane (D9) — the same store
that already holds the run records, the window states and the observed-token inventory, for the
same reason: it is the only durable thing a replica shares.

**The ledger is advisory, exactly like the ingest lease — and for the same reason.** Qdrant has no
compare-and-swap, so two concurrent `read` calls from one caller can both read *spent = 49* and
both write *50*. The over-spend is bounded by the concurrency of one caller's own requests, it is
a **cost** bug and never a correctness bug, and the alternative — a lock service — is a fourth
backing service to make a fifty-call quota exact. D9 makes the same trade for the run lease and
says so; this is that judgement applied to money rather than to work.

**The window is a UTC day.** A lifetime quota exhausts and never recovers, which is not a quota
but a decommissioning; anything shorter than a day needs a scheduler to explain it. The period key
is part of the point id, so a new day is a new point and nothing has to reset anything — there is
no sweeper, no cron and no expiry to get wrong. Yesterday's points are inert records; §15.1's
retention row is where their lifetime is set, in deployment config.

**A refusal, never a truncation** (§11.3): a caller at zero gets ``429 budget_exhausted`` on the
next `read`. A `read` silently trimmed to the pages that fit under the ceiling answers a question
about pages the caller did not ask about and reports success.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict
from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.core.ids import NAMESPACE
from vsir.ingest import run as run_module
from vsir.serve.caps import ToolError

#: The ``kind`` discriminator for a budget point, beside `run`, `window`, `observed_tokens` and
#: `fingerprint`. Every point in `vsir_runs` says which control record it is (§4.2).
KIND_BUDGET = "budget"

#: The quota window. A UTC day, formatted into the point id — see the module docstring.
PERIOD_FORMAT = "%Y-%m-%d"

_log = vsir_logging.get_logger(__name__)


class Budget(BaseModel):
    """One caller's spend in one period. The whole ledger, and it holds no page and no question."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    period: str
    #: Reads charged in this period. Only `read` charges; everything else in §7.2 is free.
    spent: int = 0
    #: The quota in force when this point was last written — recorded so an operator can see that
    #: a caller hit a ceiling that has since been raised, rather than inferring it from config.
    quota: int = 0
    updated_at: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"kind": KIND_BUDGET, **self.model_dump(mode="json")}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Budget":
        return cls.model_validate({k: v for k, v in payload.items() if k != "kind"})

    def remaining(self, quota: int) -> int:
        """Never negative: an over-spend past the ceiling is still ``0 remaining``, not ``-2``."""
        return max(0, quota - self.spent)


def period(moment: datetime | None = None) -> str:
    """The current quota window's key, in UTC.

    UTC and not a local zone: two replicas in two regions must agree on which day it is, or a
    caller gets a second quota by being routed east.
    """
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(PERIOD_FORMAT)


def budget_point_id(user_id: str, period_key: str) -> str:
    """Derived, so a write is idempotent and two replicas address the same point (I1's habit)."""
    if not user_id:
        raise ValueError("a budget point needs a user_id")
    return str(uuid.uuid5(NAMESPACE, f"vsir:budget:{user_id}:{period_key}"))


def load(client: Any, runs_collection: str, *, user_id: str,
         period_key: str | None = None) -> Budget:
    """This caller's ledger for this period — a zeroed one when nothing has been spent yet.

    A caller with no point is a caller who has spent nothing, which is a fact and not an absence,
    so this returns a zeroed :class:`Budget` rather than ``None``. A store that cannot be reached
    raises, and the dispatcher turns that into ``503 qdrant_unavailable``: guessing *"probably
    nothing spent"* during an outage is how an outage becomes an unmetered afternoon.
    """
    period_key = period_key or period()
    fresh = Budget(user_id=user_id, period=period_key)
    if not client.collection_exists(runs_collection):
        return fresh
    found = client.retrieve(runs_collection, ids=[budget_point_id(user_id, period_key)],
                            with_payload=True)
    if not found:
        return fresh
    payload = found[0].payload or {}
    if payload.get("kind") != KIND_BUDGET:
        raise run_module.RunRefused(
            f"the control point for {user_id}'s {period_key} budget is a "
            f"{payload.get('kind')!r} record", user_id=user_id, period=period_key)
    return Budget.from_payload(dict(payload))


def remaining(client: Any, runs_collection: str, *, user_id: str, quota: int,
              period_key: str | None = None) -> int:
    """``reads_remaining`` for this caller — the one integer §7.4 puts in the response body.

    Read on **every** tool call, free or paid, because §7.1 puts ``reads_remaining`` on every
    envelope. It is one point retrieved by a derived id, which is the cheapest question this
    service asks of the store, and the honest alternative — a number this process guessed — is a
    number an agent would plan against.
    """
    return load(client, runs_collection, user_id=user_id, period_key=period_key).remaining(quota)


def charge(client: Any, runs_collection: str, *, user_id: str, quota: int, tool: str,
           reads: int = 1, period_key: str | None = None) -> int:
    """Charge ``reads`` against the caller's quota and return what is left. Refuses at zero.

    Called **before** the tool runs, so a caller at the ceiling is refused instead of billed: the
    money is spent inside the tool, and a post-hoc charge would have already paid for the call it
    then rejects. A tool that fails after this point has consumed a read the caller did not get
    an answer for — which is the correct direction for the error to fall, because the provider was
    called either way.
    """
    period_key = period_key or period()
    ledger = load(client, runs_collection, user_id=user_id, period_key=period_key)
    if ledger.remaining(quota) < reads:
        _log.warning("budget_exhausted", tool=tool, user_id=user_id, period=period_key,
                     quota=quota, spent=ledger.spent, requested=reads)
        raise ToolError(
            "budget_exhausted",
            f"the read quota for {period_key} is exhausted: {ledger.spent} of {quota} used. "
            f"This is a refusal and not a truncated result — a partial answer to a question about "
            f"pages that were never read is worse than no answer (§11.3)",
            http_status=429,
            reads_remaining=0, quota=quota, period=period_key, tool=tool,
        )

    charged = ledger.model_copy(update={
        "spent": ledger.spent + reads,
        "quota": quota,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write(client, runs_collection, charged)
    _log.info("budget_charged", tool=tool, user_id=user_id, period=period_key, reads=reads,
              spent=charged.spent, quota=quota, reads_remaining=charged.remaining(quota))
    return charged.remaining(quota)


def _write(client: Any, runs_collection: str, ledger: Budget) -> None:
    """Upsert the ledger point, creating the control plane if this deployment has never run one.

    The serving surface is the first thing to write to `vsir_runs` in a deployment that has only
    ever served — an instance in front of a collection somebody else ingested — so the collection
    is ensured here rather than assumed. It is idempotent.

    **Not retried, unlike the control-plane writes in `ingest/run.py`.** A run's publish is
    retried because a half-written publish is a document that is queryable and says it is not; a
    budget write happens *before* the tool runs, so a store that will not take it means the call
    is refused with a `503` and nothing was billed. Retrying here would only delay a refusal the
    caller is going to see anyway, on the request path rather than in a worker (§11.3).
    """
    run_module.ensure_control_plane(client, runs_collection)
    client.upsert(collection_name=runs_collection,
                  points=[qm.PointStruct(id=budget_point_id(ledger.user_id, ledger.period),
                                         vector={}, payload=ledger.to_payload())],
                  wait=True)
