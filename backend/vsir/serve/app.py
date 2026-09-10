"""The HTTP surface (Spec §7.4) — at this milestone, the two probes of §15.1.

Adapted from ``impl/app/main.py``. What survives is that module's central discipline: distinct
failures stay distinct, because collapsing them manufactures silent wrong answers. What does not
survive is the ``200``-empty abstention path (§2.5 A — four typed absences replace it), the
combined ``GET /api/health``, the HTML UI at ``/``, and an unauthenticated surface. The eight
tools, bearer auth, the audit log and the budget arrive with U014.

**Liveness and readiness answer different questions, and mixing them amplifies an outage.**

``GET /health`` says *this process is up*. It touches no backing service and it MUST NOT fail
because Qdrant is unreachable: if it did, a Qdrant outage would become a fleet-wide restart loop,
and the restarts would outlast the outage.

``GET /ready`` says *this instance can serve correct answers right now* — the boot self-check
passed, Qdrant is reachable, and the pinned index schema is present. When it goes red the load
balancer removes the instance and the outage stays an outage. It never degrades into a green
answer, because a backing service that returns an empty result instead of an error turns our
outage into the caller's fabricated abstention (§11.3).

Both probes are free: no read, no embedding, and no vector search beyond a bounded metadata call.

**The run and export surface (§6.8, §6.9, §11.4).** ``GET /runs/{run_id}`` is the run record, and
the two exports are **streamed from the index** — never read off the instance's filesystem, because
there is nothing on it to read (§15 Factor VI). `impl` wrote its exports to disk from the CLI path
and never from the HTTP path (register **E1**), so a UI ingest produced nothing for the graph team
and what it did produce lived on one replica. Reading from Qdrant makes every instance able to
serve every run.

``GET /metrics`` is §11.4's two gauges, computed from the control plane rather than from counters
held in this process: an in-memory counter would report a different number per replica and reset on
every deploy, which is a metric about the deployment rather than about the corpus.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterator, Literal, Mapping

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import QdrantClient
from starlette.concurrency import run_in_threadpool

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.config import Config, load_config
from vsir.doctor import QDRANT_UNAVAILABLE, BootRefused, assert_boot_ok, run_boot_checks
from vsir.ingest import export as export_module
from vsir.ingest import run as run_module

#: A local boot check that has started failing after boot (a rotated variable, say).
BOOT_CHECK_FAILED = "boot_check_failed"
#: A probe must never be the slow thing in the cluster: two seconds, then it is unreachable.
PROBE_TIMEOUT_S = 2
#: The control plane and the exports get their own client, because one timeout cannot be both
#: honest answers: a probe that waits 30 seconds is a probe that fails to fail, and an export of a
#: 1,440-page manual that gives up after 2 is a truncated contract artefact.
CONTROL_TIMEOUT_S = 30
#: uvicorn's own loggers, folded into the one JSON stream (§15 Factor XI).
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_log = vsir_logging.get_logger(__name__)


class HealthResponse(BaseModel):
    """Liveness. Deliberately says nothing about a backing service (§15.1)."""

    status: Literal["ok"] = "ok"
    release_id: str
    version: str


class ReadyResponse(BaseModel):
    """Readiness, with the reason named when it is red — never a bare boolean."""

    status: Literal["ready", "not_ready"]
    release_id: str
    reason: str | None = None
    checks: dict[str, str] = Field(default_factory=dict)


class ControlError(BaseModel):
    """A typed refusal from the control-plane surface (§11.3).

    Named and distinct, always. An unknown run is `run_not_found` and a store that did not answer
    is `qdrant_unavailable`: the first is a fact about the request, the second is somebody else's
    outage, and collapsing them into one empty body is how a caller retries the wrong thing.
    """

    model_config = ConfigDict(extra="forbid")

    error: str
    detail: str
    run_id: str = ""


#: The Prometheus text exposition format's own content type. Pinned here rather than defaulted,
#: because a scrape of `text/plain` without the version negotiates differently on some scrapers.
PROMETHEUS_MEDIA_TYPE = "text/plain; version=0.0.4; charset=utf-8"

#: §11.4's two series, with the help text a dashboard shows beside them.
_GAUGE_HELP = {
    "ingest_grounded_rate_median": "The §5.7 grounded_rate median of each document's latest "
                                   "published run, over its pages with a text layer.",
    "ingest_gate_failures_total": "Publish gates of §11.1 that have failed, by gate, across every "
                                  "run in the control plane.",
}


def _label(value: str) -> str:
    """Escape a Prometheus label value. Ids here are slugs, but an export is not the place to
    discover that something was not."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metrics(snapshot: Mapping[str, Mapping[str, Any]]) -> str:
    """The §11.4 gauges in Prometheus text exposition format.

    Written by hand rather than with a client library for one reason: a library would be a
    dependency outside §4.2, and what it would buy — a process-wide registry of counters — is
    precisely the in-process state §15 Factor VI rules out. Both series are declared `gauge`, as
    §11.4 words them: `ingest_gate_failures_total` is a total *recomputed* from the control plane
    on every scrape, not a counter this process increments.
    """
    lines: list[str] = []
    for name, series in snapshot.items():
        help_text = _GAUGE_HELP.get(name, "")
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        label = "doc_id" if name.endswith("median") else "gate"
        for key, value in sorted(series.items()):
            lines.append(f'{name}{{{label}="{_label(str(key))}"}} {value}')
    return "\n".join(lines) + "\n"


def _refusal(refusal: run_module.RunRefused, status: int) -> JSONResponse:
    payload = refusal.to_payload()
    return JSONResponse(status_code=status, content={
        "error": payload.get("error", refusal.code), "detail": refusal.message,
        "run_id": str(payload.get("run_id", "")),
    })


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    """Build the app, refusing to start rather than serving a half-configured process (§4.3).

    A factory rather than a module-level ``app``: the configuration is an argument, so a test can
    build an instance pointed at a different Qdrant without touching the process environment, and
    importing this module never has a side effect. Run it with
    ``uvicorn --factory vsir.serve.app:create_app``.
    """
    env = os.environ if env is None else env

    # Logging comes up before the first check so the refusal itself is on the event stream.
    vsir_logging.configure(
        release_id=(env.get("VSIR_RELEASE_ID") or "").strip() or "unknown",
        level=(env.get("VSIR_LOG_LEVEL") or "INFO").strip(),
    )
    # uvicorn has already installed its own plain-text handlers by the time it calls this factory.
    # Fold them into the one stream, or half of what the platform collects is not an event.
    vsir_logging.capture_stdlib_loggers(*_UVICORN_LOGGERS)
    assert_boot_ok(env)
    cfg = load_config(env)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """One Qdrant client for the process, and no wait-for-Qdrant loop.

        ``impl`` blocked start-up for up to 60 seconds waiting for Qdrant. Readiness is what gates
        traffic (§15.1), so this process starts immediately and reports itself unready until the
        backing service answers — which is also what makes start-up have no warm-up requirement.
        """
        # One connection for the process, handed to the boot checks on every readiness probe so
        # they do not build and tear down an HTTP client every few seconds. It is the **sync**
        # client because the checks are sync and shared with the CLI: `/ready` runs the whole list
        # in a worker thread rather than doing blocking I/O on the event loop.
        app.state.qdrant = QdrantClient(url=cfg.qdrant_url, timeout=PROBE_TIMEOUT_S,
                                        check_compatibility=False)
        app.state.control = QdrantClient(url=cfg.qdrant_url, timeout=CONTROL_TIMEOUT_S,
                                         check_compatibility=False)
        _log.info("startup", port=cfg.port, collection=cfg.pages_collection)
        try:
            yield
        finally:
            # SIGTERM: uvicorn stops accepting, drains in flight, then unwinds this (§15 IX).
            _log.info("shutdown", draining="complete")
            app.state.qdrant.close()
            app.state.control.close()

    app = FastAPI(
        title="Vision segmentation, index & retrieval",
        version=__version__,
        lifespan=lifespan,
        description=(
            "The document service behind an engineering question.\n\n"
            "**A code this service returns is a code printed on the page.** Nothing matched is one "
            "of four typed absences, never an empty `200` — an empty success is indistinguishable "
            "from a fabricated abstention. A filter outside `INDEXED` is a typed `400`, never a "
            "degraded unindexed scan. A backing-service failure is a `503`, never an empty result."
        ),
    )
    app.state.config = cfg
    app.state.env = dict(env)

    @app.get("/health", response_model=HealthResponse, tags=["probes"])
    async def health() -> HealthResponse:
        """Liveness (§15.1). Green whenever the process can answer, Qdrant up or down."""
        return HealthResponse(release_id=cfg.release_id, version=__version__)

    @app.get("/ready", response_model=ReadyResponse, tags=["probes"])
    async def ready(response: Response) -> ReadyResponse:
        """Readiness (§15.1): boot checks green, Qdrant reachable, pinned index schema present.

        All three clauses are the one ``BOOT_CHECKS`` list, under readiness's policy rather than
        boot's: **red on a failure *or* on a check that could not conclude.** That difference is
        the whole design. A schema that is already drifted at start-up is a boot refusal, so the
        process never begins serving; a schema that drifts *under a running instance* turns it red
        here, which is why the checks are re-run per probe. An unreachable Qdrant or a collection
        that does not exist yet leaves the instance alive but out of the load balancer, because a
        restart loop would outlast the outage.

        The checks are re-run per probe rather than cached from start-up, so a schema that drifts
        under a running process turns the instance red instead of leaving it answering. They run in
        a worker thread: the check list is sync and shared with the CLI, and blocking the event
        loop on a probe would be its own outage.
        """
        results = await run_in_threadpool(run_boot_checks, app.state.env, app.state.qdrant)
        checks = {result.name: result.status for result in results}

        failed = [result for result in results if result.failed]
        inconclusive = [result for result in results if result.inconclusive]
        reason: str | None = None
        detail: str | None = None
        if failed:
            reason, detail = BOOT_CHECK_FAILED, "; ".join(r.detail for r in failed)
        elif inconclusive:
            # A named reason, not a bare boolean: `qdrant_unavailable` is somebody else's outage,
            # `index_not_ready` is this deployment waiting for its first ingest (§11.3).
            reason = inconclusive[0].reason or QDRANT_UNAVAILABLE
            detail = "; ".join(r.detail for r in inconclusive)

        if reason is not None:
            response.status_code = 503
            _log.warning("not_ready", reason=reason, detail=detail, checks=checks)
        return ReadyResponse(
            status="not_ready" if reason else "ready",
            release_id=cfg.release_id,
            reason=reason,
            checks=checks,
        )

    # ── the run control plane and the two exports (§6.8, §6.9, §11.4) ────────────────────────────

    def _run_record(run_id: str) -> run_module.RunRecord:
        """The run point, or a typed refusal. Sync: every caller runs it in a worker thread."""
        return run_module.require(app.state.control, cfg.runs_collection, run_id)

    @app.get("/runs/{run_id}", response_model=run_module.RunRecord, tags=["runs"],
             responses={404: {"model": ControlError}, 503: {"model": ControlError}})
    async def run_record(run_id: str) -> Any:
        """The run record of §6.9 — state, step, gates, overrides, lease, cost, retirement.

        Read from `vsir_runs`, so any replica answers about any run: the ingest worker that
        executed it holds nothing (§15 Factor VI, register E2). An unknown run is a typed `404`
        and an unreachable store is a `503`; neither is an empty record, because a caller cannot
        tell an empty record from a run that produced nothing.
        """
        try:
            return await run_in_threadpool(_run_record, run_id)
        except run_module.RunNotFound as refusal:
            return _refusal(refusal, 404)
        except Exception as failure:  # noqa: BLE001 — anything else is the store not answering
            _log.error("runs_unavailable", run_id=run_id,
                       detail=f"{type(failure).__name__}: {failure}")
            return _refusal(run_module.StoreUnavailable(
                f"the control plane did not answer: {type(failure).__name__}", run_id=run_id), 503)

    @app.get("/runs/{run_id}/export/{artefact}.jsonl", tags=["runs"],
             responses={200: {"content": {export_module.MEDIA_TYPE: {}}},
                        404: {"model": ControlError}, 503: {"model": ControlError}})
    async def run_export(run_id: str, artefact: str) -> Any:
        """`labels.jsonl` and `observed_tokens.jsonl` of §6.8 — **streamed from the index**.

        Nothing is written to this instance's filesystem, and there is no file to read from it
        either: the generator produces NDJSON lines as Qdrant answers, so the response holds one
        chunk of pages at a time and the disk is never touched (§15 Factor VI, register E1).
        """
        try:
            record = await run_in_threadpool(_run_record, run_id)
        except run_module.RunNotFound as refusal:
            return _refusal(refusal, 404)
        except Exception as failure:  # noqa: BLE001
            return _refusal(run_module.StoreUnavailable(
                f"the control plane did not answer: {type(failure).__name__}", run_id=run_id), 503)

        def lines() -> Iterator[str]:
            yield from export_module.stream(
                app.state.control, artefact=artefact, collection=cfg.pages_collection,
                runs_collection=cfg.runs_collection, record=record,
                safety_doc_types=cfg.safety_doc_types, safety_topics=cfg.safety_topics)

        try:
            stream = lines()
            first = next(stream, None)
        except export_module.ExportRefused as refusal:
            return JSONResponse(status_code=404, content={**refusal.to_payload(),
                                                          "run_id": run_id})

        def body() -> Iterator[str]:
            # The first line is already in hand — pulled before the response started so an unknown
            # artefact is a typed 404 rather than a 200 whose body turns out to be a traceback.
            if first is not None:
                yield first
            yield from stream

        return StreamingResponse(body(), media_type=export_module.MEDIA_TYPE, headers={
            "content-disposition": f'attachment; filename="{artefact}-{run_id}.jsonl"'})

    @app.get("/metrics", response_class=PlainTextResponse, tags=["probes"],
             responses={503: {"model": ControlError}})
    async def metrics() -> Any:
        """§11.4 — `ingest_grounded_rate_median{doc_id}` and `ingest_gate_failures_total{gate}`.

        Both are computed from `vsir_runs` on each scrape rather than counted in this process. A
        counter in memory would be a different number on every replica and would reset on every
        deploy, which measures the deployment rather than the corpus (§15 Factor VI).
        """
        try:
            snapshot = await run_in_threadpool(run_module.gauges, app.state.control,
                                               cfg.runs_collection)
        except Exception as failure:  # noqa: BLE001
            _log.error("metrics_unavailable", detail=f"{type(failure).__name__}: {failure}")
            return _refusal(run_module.StoreUnavailable(
                f"the control plane did not answer: {type(failure).__name__}"), 503)
        return PlainTextResponse(render_metrics(snapshot), media_type=PROMETHEUS_MEDIA_TYPE)

    return app


def app_factory() -> FastAPI:
    """The process entry point: ``uvicorn --factory vsir.serve.app:app_factory``.

    Identical to :func:`create_app` but for one thing: a §4.3 boot refusal exits **1** instead of
    unwinding as a traceback. The refusal is a designed behaviour with its reason already on the
    event stream as JSON, so a forty-line traceback after it is redundant non-JSON noise on a
    stream whose contract is one JSON object per line (§15 Factor XI).

    `create_app` keeps raising, because a library that calls `sys.exit` is untestable and a test
    asserting *which* check refused is worth more than a tidy exit code.
    """
    try:
        return create_app()
    except BootRefused as refusal:
        _log.error("boot_refused", failed_checks=refusal.failed_checks, detail=str(refusal))
        raise SystemExit(1) from None


def config_of(app: FastAPI) -> Config:
    """The configuration this app was built with — no module-level singleton to import."""
    return app.state.config
