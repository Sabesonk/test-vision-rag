"""The HTTP surface (Spec §7.4) — the probes of §15.1, the run control plane, and the tools.

Adapted from ``impl/app/main.py``. What survives is that module's central discipline: distinct
failures stay distinct, because collapsing them manufactures silent wrong answers. What does not
survive is the ``200``-empty abstention path (§2.5 A — four typed absences replace it), the
combined ``GET /api/health``, the HTML UI at ``/``, and — the one that mattered most —
**an unauthenticated surface**.

`impl` exposed eleven endpoints with no credential on any of them, including the vision call that
spends money and the delete that removes a document (register **E5**). Here every path but the
three free probes is refused without a bearer token, and it is refused in *middleware* rather than
by a decorator on each route: a route this file gains next milestone is protected before it is
written (`serve/auth.py`).

**The tool surface is one route and a table.** ``POST /tools/{tool_name}`` looks the name up in
:func:`tool_table`, validates the body against that tool's own Pydantic model, charges the budget
if the tool spends, runs it, stamps ``reads_remaining`` on the envelope and — for `read` and
`fetch` only — writes the ten-field audit line of §7.4. Adding a tool is adding a row, so no tool
can arrive with its own idea of auth, of the budget, or of which failures are which. The table in
this release holds `lookup` and `verify`; the rest of §7.2 joins it as its milestone lands, and a
name that is not in the table is a typed `404` naming what is, never a 501-shaped silence.

**And the table is not the HTTP surface's — it is the release's.** §7.5 requires the MCP server to
expose the same tools *"calling the identical implementations (no second code path)"*, so the
route above is a thin shell around :func:`dispatch`, which takes a :class:`ToolRuntime` and a
plain dict of arguments and knows nothing about HTTP. `vsir/mcp/server.py` calls the same
function with the same runtime, which is why the two surfaces cannot drift: there is nothing to
keep in step. The MCP SSE transport is mounted on **this** app and binds **this** port (§15
Factor VII) — one process, one socket, two protocols over it.

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
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from dataclasses import dataclass
from typing import (Any, AsyncIterator, Awaitable, Callable, Iterator, Literal, Mapping,
                    MutableMapping, Sequence)

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.openapi.utils import get_openapi
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               StreamingResponse)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from starlette.concurrency import run_in_threadpool

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.config import LOOKUP_CAP, Config, load_config
from vsir.doctor import QDRANT_UNAVAILABLE, BootRefused, assert_boot_ok, run_boot_checks
from vsir.ingest import export as export_module
from vsir.ingest import run as run_module
from vsir.serve import audit as audit_module
from vsir.serve import auth as auth_module
from vsir.serve import budget as budget_module
from vsir.serve import ingest as ingest_module
from vsir.serve.audit import Usage
from vsir.serve.auth import BearerAuth, Identity
from vsir.serve.caps import ToolError
from vsir.serve.envelope import Provenance, wire
from vsir.serve.tools.lookup import lookup as lookup_tool
from vsir.serve.tools.verify import verify as verify_tool
from vsir.vlm.cache import VlmCallFailed, VlmError, VlmUnavailable

#: A local boot check that has started failing after boot (a rotated variable, say).
BOOT_CHECK_FAILED = "boot_check_failed"
#: A probe must never be the slow thing in the cluster: two seconds, then it is unreachable.
PROBE_TIMEOUT_S = 2
#: The control plane and the exports get their own client, because one timeout cannot be both
#: honest answers: a probe that waits 30 seconds is a probe that fails to fail, and an export of a
#: 1,440-page manual that gives up after 2 is a truncated contract artefact.
CONTROL_TIMEOUT_S = 30
#: And the tool surface gets its own again: a tool call is on a caller's request path, so a store
#: that has stopped answering has to become a `503` while the caller is still there to read it.
SEARCH_TIMEOUT_S = 10
#: uvicorn's own loggers, folded into the one JSON stream (§15 Factor XI).
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

#: Correlation only — never identity (§7.4). A caller may name its own request, session and runner
#: run so its logs and ours line up; who it *is* comes from the token and nothing else.
REQUEST_ID_HEADER = "x-request-id"
SESSION_ID_HEADER = "x-session-id"
RUN_ID_HEADER = "x-run-id"
#: A correlation id is an identifier, not a payload. Bounded so a caller cannot push a kilobyte
#: onto every line of the event stream.
MAX_CORRELATION_CHARS = 64

#: Exceptions that mean *the store did not answer*. Each becomes `503 qdrant_unavailable` —
#: retryable, and **never** an empty result, because a backend failure returned as "nothing found"
#: turns our outage into the agent's fabricated abstention (§7.1, §11.3).
STORE_FAILURES: tuple[type[BaseException], ...] = (
    ResponseHandlingException, UnexpectedResponse, run_module.StoreUnavailable,
    ConnectionError, TimeoutError, OSError,
)
#: Exceptions that mean *the model backend cannot run*. `503 vlm_unavailable` on the tool that
#: needed it, while every free tool keeps working (§11.3 row 2).
VLM_UNAVAILABLE: tuple[type[BaseException], ...] = (VlmUnavailable, VlmCallFailed)

_log = vsir_logging.get_logger(__name__)

#: The console page, resolved from `__file__` so it is found in a wheel as well as in a tree. It
#: ships because `[tool.setuptools.package-data]` names it; `test_release_artefacts.py` fails if a
#: runtime data file under `vsir/` is not declared, which is the check that would have caught the
#: prompts going missing from the image.
CONSOLE_PAGE = Path(__file__).resolve().parent / "console" / "index.html"


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


# ── correlation (§11.4) ──────────────────────────────────────────────────────────────────────────

#: Where :class:`RequestContext` parks the ids so the tool dispatcher can put them on the audit
#: line explicitly, rather than trusting a ``ContextVar`` to survive the hop into a worker thread.
SCOPE_CORRELATION = "vsir.correlation"


def _header(headers: Sequence[tuple[bytes, bytes]], name: str) -> str:
    wanted = name.encode("latin-1")
    for key, value in headers:
        if key.lower() == wanted:
            return value.decode("latin-1", "replace").strip()[:MAX_CORRELATION_CHARS]
    return ""


class RequestContext:
    """Bind ``request_id``/``session_id``/``run_id`` for the life of one request (§11.4).

    Pure ASGI, not ``BaseHTTPMiddleware``, and the reason is the whole point of the class: that
    base class runs the downstream app in a **separate task**, so a ``ContextVar`` bound in its
    ``dispatch`` never reaches the endpoint and every log line inside the request would be missing
    the id that ties it to the request. A plain ASGI callable awaits the app in the same task.

    It is the outermost middleware, so a `401` from :class:`~vsir.serve.auth.BearerAuth` is on the
    stream with a ``request_id`` too — an unauthenticated call is exactly the kind an operator has
    to be able to correlate.

    Nothing here is identity. A caller supplies these three so *its* logs and ours line up; who it
    is comes from the bearer token, in the next middleware down (§7.4).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: MutableMapping[str, Any],
                       receive: Callable[[], Awaitable[Any]],
                       send: Callable[[Any], Awaitable[None]]) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers") or ()
        ids = {
            "request_id": _header(headers, REQUEST_ID_HEADER) or uuid.uuid4().hex,
            "session_id": _header(headers, SESSION_ID_HEADER),
            "run_id": _header(headers, RUN_ID_HEADER),
        }
        scope[SCOPE_CORRELATION] = ids
        with vsir_logging.correlate(**{k: v for k, v in ids.items() if v}):
            await self.app(scope, receive, send)


# ── the tool surface (§7.2, §7.4) ────────────────────────────────────────────────────────────────

class ToolRequest(BaseModel):
    """Base for every tool body. ``extra="forbid"``, so a misspelt parameter is a `400`.

    Silently ignoring an unknown field is how a caller passes ``include_unverified=True`` as
    ``includeUnverified`` and is told, with a straight face, that the corpus does not contain it.
    """

    model_config = ConfigDict(extra="forbid")


class LookupRequest(ToolRequest):
    """``lookup(label, scope?, include_unverified=False, cap=20)`` — §7.2.2.

    The request shapes live here, beside the table, until the tool's own module takes ownership of
    its wrapper: `skim_*`/`resolve` at U017, `fetch` at U018, `read` at U020. What may never move
    is where they are *validated* — one table, one dispatcher, one place that charges the budget
    and writes the audit line, and both transports go through it.

    These models are also the **MCP input schemas** (§7.5): `mcp/server.py` publishes
    ``model_json_schema()`` for each row of the table rather than hand-writing a JSON Schema per
    tool, so an MCP client and an HTTP client are validated against the same declaration and a
    new parameter cannot reach one surface without reaching the other.
    """

    label: str
    #: Not a typed model: `INDEXED` is the schema, and `core.exact` refuses a key outside it with
    #: `filter_unknown_key` (I6, F10). A Pydantic mirror of `INDEXED` would be a second source of
    #: truth for the one dict that has three jobs (§5.4).
    scope: dict[str, Any] = Field(default_factory=dict)
    include_unverified: bool = False
    cap: int = LOOKUP_CAP


class VerifyRequest(ToolRequest):
    """``verify(claims, page_ids)`` — §7.2.4.

    No ``scope``: the pages are named outright, so there is nothing to filter. No ``image``
    either, and that is I2/I3 rather than an omission — a photograph may *find* a candidate page,
    it can never *confirm* a code.
    """

    claims: list[str]
    page_ids: list[str]


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool call needs that is not in its body. Built per request, held nowhere.

    No session, no cursor, no last-scope: `scope` and `exclude` are parameters and
    `effective_scope` is echoed back (C11, §15 Factor VI).
    """

    client: Any
    cfg: Config
    identity: Identity
    reads_remaining: int
    provenance: Provenance


@dataclass(frozen=True)
class ToolSpec:
    """One row of the table: the name, its body shape, the call, and whether it spends."""

    name: str
    request: type[ToolRequest]
    call: Callable[[ToolContext, Any], tuple[BaseModel, Usage]]
    #: Charges the per-caller `read` quota before running (§7.3). `read`'s row sets it at U020.
    spends: bool = False
    #: What an agent reads when it is choosing a move. Published as the MCP tool description
    #: (§7.5) and as the route's OpenAPI summary, from one string, because a tool described two
    #: ways is a tool two clients understand differently.
    description: str = ""


@dataclass(frozen=True)
class ToolRuntime:
    """Everything :func:`dispatch` needs, with no transport in it.

    The seam §7.5 requires. HTTP builds one per app in the lifespan; `vsir/mcp/server.py` builds
    one from the same configuration and the same table, so *"calling the identical
    implementations"* is a fact about the object graph rather than a promise in a docstring.

    ``tools`` is the very dict on ``app.state.tools`` and not a copy: a release that registers a
    tool registers it once, for every surface at once.
    """

    config: Config
    #: The Qdrant client on a caller's request path — its own timeout, so a store that stopped
    #: answering becomes a `503` while the caller is still there to read it.
    search: Any
    tools: Mapping[str, ToolSpec]


@dataclass(frozen=True)
class ToolOutcome:
    """The result of one tool call, before any transport has looked at it.

    ``status`` is the **HTTP** status even when nobody is speaking HTTP: it is the vocabulary §7.3
    and §11.3 are written in — `400` names a bound, `404` is absent, `429` is the quota, `503` is
    somebody else's outage — and the MCP surface maps it onto ``isError`` rather than inventing a
    second taxonomy of failure for the same events.
    """

    status: int
    payload: Mapping[str, Any]

    @property
    def refused(self) -> bool:
        return self.status >= 400

    def body(self) -> bytes:
        """The bytes a caller receives, on either transport (:func:`~vsir.serve.envelope.wire`)."""
        return wire(self.payload)


def _call_lookup(context: ToolContext, body: LookupRequest) -> tuple[BaseModel, Usage]:
    """The transport adapter, and deliberately nothing more.

    `serve/tools/lookup.py` is the tool; this hands it the store and the request context and adds
    **not one line of behaviour**, which is what makes M1's proof still true at the HTTP boundary.
    The response is free, so it reports :meth:`Usage.free` and no audit line is written (§7.4).
    """
    response = lookup_tool(
        context.client, context.cfg.pages_collection, body.label,
        scope=body.scope, include_unverified=body.include_unverified, cap=body.cap,
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )
    return response, Usage.free()


def _call_verify(context: ToolContext, body: VerifyRequest) -> tuple[BaseModel, Usage]:
    """The same adapter shape for §7.2.4 — a Family B envelope instead of a Family A one.

    Nothing here notices the difference, which is the point: `verify` returning ``ok`` with three
    `absent` verdicts travels the identical path as a `lookup` returning one hit, because
    ``status`` in Family B is about the **call** and the dispatcher only ever asked whether the
    call ran (§7.1).
    """
    envelope = verify_tool(
        context.client, context.cfg.pages_collection, body.claims, body.page_ids,
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )
    return envelope, Usage.free()


#: What each tool is *for*, in the words an agent needs to choose between them. Kept beside the
#: table rather than lifted from the Python docstrings: those explain the implementation to a
#: maintainer, and a tool description explains a **move** to a caller (§7.2, §8.2).
LOOKUP_DESCRIPTION = (
    "JUMP. Exact, phrase-only lookup of a printed code or label — a SET of pages, never a "
    "ranking and never a similarity match. A code this returns is a code printed on the page. "
    "Nothing matched is one of four typed absences, never an empty success: `not_found` (abstain, "
    "but read `next.suggest`), `not_searchable` (the candidate pages have no text layer — "
    "escalate to vision), `out_of_scope` (no document matched the filters — widen), "
    "`found_only_in_superseded`. `include_unverified=true` additionally returns model-claimed "
    "codes in `unverified_hits`, permanently `verified: false`; they are recall on a scanned "
    "page and they are never evidence. Free."
)
VERIFY_DESCRIPTION = (
    "CHECK. Is each of these codes actually printed on each of these pages? Per (claim, page), "
    "so a draft citing two pages cannot borrow the neighbouring page's evidence. Three verdicts: "
    "`present`, `absent` (with up to five `present_instead` codes observed on the page — a "
    "different part, never a nearest match), and `unverifiable` (no text layer, an untrusted "
    "extraction, or a page that is not current) — which is never the same as `absent`. Every "
    "claim absent is still a successful call. Free."
)


def tool_table() -> dict[str, ToolSpec]:
    """The tools this release exposes — over HTTP at ``POST /tools/{tool_name}`` and over MCP.

    A function, not a module constant, for the reason §15.2 bans a module-level mutable store: a
    dict at import time is one object shared by every app in the process, and a test that pointed
    one app at a different table would be changing every other app's. Each :func:`create_app`
    gets its own, parked on ``app.state`` and handed to the :class:`ToolRuntime`.

    Six of §7.2's eight are absent here and that is a fact about the release, not a gap in the
    dispatcher: `skim_*` and `resolve` land at U017, `fetch` at U018 and `read` at U020. Until
    then their names are a typed `404` that lists what *is* available, because a caller that
    asked for `read` needs to know it is not here — not receive an empty result.
    """
    return {
        "lookup": ToolSpec(name="lookup", request=LookupRequest, call=_call_lookup,
                           description=LOOKUP_DESCRIPTION),
        "verify": ToolSpec(name="verify", request=VerifyRequest, call=_call_verify,
                           description=VERIFY_DESCRIPTION),
    }


def runtime_from_env(env: Mapping[str, str]) -> tuple[ToolRuntime, QdrantClient]:
    """A :class:`ToolRuntime` for a process with no ASGI lifespan to build one for it.

    `vsir mcp --stdio` and the `vsir lookup` / `vsir verify` one-shots are ordinary processes of
    this release (§15 Factor XII) that need the same table, the same configuration and the same
    store as `web`. Building it here rather than in each of them is what makes the one-shots
    evidence about the shipped tool: `vsir lookup` runs the code path `POST /tools/lookup` runs,
    down to the typed refusals, and a demo of it is a demo of the service.

    The **boot self-check runs first** (§4.3), before the client is opened and before a single
    argument is read: a floating model id or a live payload schema that disagrees with `INDEXED`
    is a named non-zero exit, never a process that answers one call correctly and the next one
    from a collection that moved underneath it.

    The client is returned beside the runtime because the caller owns closing it — nothing here
    holds a connection past the process that asked for one.
    """
    assert_boot_ok(env)
    cfg = load_config(env)
    client = QdrantClient(url=cfg.qdrant_url, timeout=SEARCH_TIMEOUT_S, check_compatibility=False)
    return ToolRuntime(config=cfg, search=client, tools=tool_table()), client


def _tool_refusal(code: str, detail: str, *, status: int, **details: Any) -> ToolOutcome:
    """A typed refusal from the tool surface: a machine-readable ``error`` and its bound.

    Returns a transport-neutral :class:`ToolOutcome`, because a `filter_unknown_key` is the same
    refusal whether it arrives over HTTP or over MCP and a caller must not have to learn it
    twice.
    """
    return ToolOutcome(status=status, payload={"error": code, "detail": detail, **details})


def _failure_response(failure: BaseException, *, tool: str) -> ToolOutcome:
    """Map an exception out of a tool onto §11.3's refusals. Never onto an empty result.

    The order is the contract. A typed :class:`~vsir.serve.caps.ToolError` is the tool naming its
    own bound and carries its own status (a `400`, or the `429` of an exhausted quota). A store
    failure is `503 qdrant_unavailable`. A model backend that cannot run is `503 vlm_unavailable`,
    and a model that answered unusably is a `502` under its own code — those are different
    operational problems and an operator retries them differently. Anything left is a bug in this
    service and is a `500` naming only the exception *type*: a message can carry a URL, and a URL
    can carry a credential (§15.1).
    """
    if isinstance(failure, ToolError):
        # Merged rather than passed as keywords: a bound's details legitimately carry `tool`
        # (the budget's do), and a duplicate keyword would turn a refusal into a `TypeError`.
        _log.warning("tool_refused", **{"tool": tool, "code": failure.code, **failure.details})
        return _tool_refusal(failure.code, failure.message, status=failure.http_status,
                             **{"tool": tool, **failure.details})
    if isinstance(failure, STORE_FAILURES):
        _log.error("tool_unavailable", tool=tool, code=QDRANT_UNAVAILABLE,
                   detail=f"{type(failure).__name__}: {failure}")
        return _tool_refusal(
            QDRANT_UNAVAILABLE,
            f"the index did not answer: {type(failure).__name__}. This is a refusal and not an "
            f"empty result — an outage reported as 'nothing found' becomes a fabricated "
            f"abstention (§7.1, §11.3)",
            status=503, retryable=True, tool=tool)
    if isinstance(failure, VLM_UNAVAILABLE):
        _log.error("tool_unavailable", tool=tool, code="vlm_unavailable",
                   cause=getattr(failure, "code", ""), detail=str(failure))
        return _tool_refusal("vlm_unavailable", str(failure), status=503, retryable=True,
                             tool=tool, cause=getattr(failure, "code", ""))
    if isinstance(failure, VlmError):
        _log.error("tool_backend_error", tool=tool, code=failure.code, detail=str(failure))
        return _tool_refusal(failure.code, str(failure), status=502, tool=tool)
    if isinstance(failure, run_module.RunRefused):
        _log.error("tool_refused", tool=tool, code=failure.code, detail=failure.message)
        return _tool_refusal(failure.code, failure.message, status=503, tool=tool)
    _log.exception("tool_failed", tool=tool, detail=type(failure).__name__)
    return _tool_refusal("internal_error", f"the call failed: {type(failure).__name__}",
                         status=500, tool=tool)


def run_tool(runtime: ToolRuntime, spec: ToolSpec, body: ToolRequest, *, identity: Identity,
             correlation: Mapping[str, str]) -> ToolOutcome:
    """Budget → call → ``reads_remaining`` → audit. Sync: the Qdrant client is sync.

    Its caller runs it in a worker thread, so the correlation ids are re-bound here from the
    values the transport captured rather than relied on to travel with the thread — the audit
    line of §7.4 is the last place to discover that a ``ContextVar`` did not make the hop.
    """
    cfg = runtime.config
    tool = spec.name
    with vsir_logging.correlate(tool=tool, **{k: v for k, v in correlation.items() if v}):
        timer = audit_module.Timer()
        try:
            # Before the call, never after: money is spent inside the tool, so a caller at the
            # ceiling is refused rather than billed for a call whose result is then thrown away.
            if spec.spends:
                reads_remaining = budget_module.charge(
                    runtime.search, cfg.runs_collection, user_id=identity.user_id,
                    quota=cfg.read_quota, tool=tool)
            else:
                reads_remaining = budget_module.remaining(
                    runtime.search, cfg.runs_collection, user_id=identity.user_id,
                    quota=cfg.read_quota)

            envelope, usage = spec.call(
                ToolContext(client=runtime.search, cfg=cfg, identity=identity,
                            reads_remaining=reads_remaining,
                            provenance=Provenance(release_id=cfg.release_id)),
                body)
        except BaseException as failure:  # noqa: BLE001 — every path out is a typed refusal
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            return _failure_response(failure, tool=tool)

        # Stamped by the dispatcher rather than trusted to each tool: §7.1 puts `reads_remaining`
        # on **every** envelope, and a tool that forgot would return a plausible zero.
        envelope = envelope.model_copy(update={"reads_remaining": reads_remaining})

        if audit_module.audited(tool):
            audit_module.emit(audit_module.line(
                user_id=identity.user_id, tool=tool, usage=usage,
                latency_ms=timer.elapsed_ms,
                run_id=correlation.get("run_id", ""),
                session_id=correlation.get("session_id", ""),
            ))
        return ToolOutcome(status=200, payload=envelope.model_dump(mode="json"))


def dispatch(runtime: ToolRuntime, tool_name: str, arguments: Mapping[str, Any], *,
             identity: Identity, correlation: Mapping[str, str]) -> ToolOutcome:
    """Name → table → validation → :func:`run_tool`. **The** entry point for every transport.

    Three steps, in this order, because each one's refusal is a different problem:

    1. **the name.** Not in the table → a typed `404` listing what *is* served. A tool that is
       not in this release is *absent*, not empty — the same argument §7.1 makes about results,
       applied to the surface itself.
    2. **the arguments.** Validated against that tool's own model with ``extra="forbid"``, so a
       misspelt parameter is a `400` and never a quietly different query. This is the step the
       risk register (R6) is about: an MCP client that ignored the published input schema is
       refused **here**, server-side, rather than trusted to have read it.
    3. **the call**, with the budget, the audit line and ``reads_remaining`` (:func:`run_tool`).

    Sync throughout: the Qdrant client is sync, and both transports call this from a worker
    thread rather than blocking their event loop.
    """
    spec = runtime.tools.get(tool_name)
    if spec is None:
        available = sorted(runtime.tools)
        _log.warning("tool_not_found", tool=tool_name, available=available)
        return _tool_refusal(
            "tool_not_found",
            f"no tool {tool_name!r} in release {runtime.config.release_id!r}; this release "
            f"serves {available}. A tool that is not here is absent, not empty — §7.2's "
            f"remaining names arrive with the milestones that build them",
            status=404, tool=tool_name, available=available)

    try:
        body = spec.request.model_validate(dict(arguments))
    except ValidationError as invalid:
        return _tool_refusal(
            "invalid_request",
            f"the arguments do not match {tool_name}'s parameters (§7.2)",
            status=400, tool=tool_name,
            problems=[{"field": ".".join(str(part) for part in problem["loc"]),
                       "error": problem["msg"]} for problem in invalid.errors()])

    return run_tool(runtime, spec, body, identity=identity, correlation=correlation)


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
        app.state.search = QdrantClient(url=cfg.qdrant_url, timeout=SEARCH_TIMEOUT_S,
                                        check_compatibility=False)
        # The transport-neutral view of this app. `tools` is the very dict on `app.state`, not a
        # copy, so a suite (or a later milestone) that registers a tool registers it for the MCP
        # surface at the same instant — there is no second table to keep in step (§7.5).
        app.state.runtime = ToolRuntime(config=cfg, search=app.state.search,
                                        tools=app.state.tools)
        _log.info("startup", port=cfg.port, collection=cfg.pages_collection,
                  tools=sorted(app.state.tools), mcp=sorted(app.state.mcp_paths))
        try:
            yield
        finally:
            # SIGTERM: uvicorn stops accepting, drains in flight, then unwinds this (§15 IX).
            _log.info("shutdown", draining="complete")
            app.state.search.close()
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
    # Per app, never per module: a table at import time would be one object shared by every app
    # in the process, which is the module-level mutable store §15.2 bans.
    app.state.tools = tool_table()

    # Added innermost-first: `add_middleware` puts each new one *outside* the last, so the
    # correlation ids are bound before authentication runs and a `401` is correlatable too.
    app.add_middleware(BearerAuth, tokens=cfg.api_tokens)
    app.add_middleware(RequestContext)

    # §15 Factor VII — *"the MCP SSE transport binds the same port"*. One process, one socket,
    # two protocols over it, and the same default-deny middleware in front of both: `/sse` and
    # `/messages/` are not in `PUBLIC_PATHS`, so they need a bearer token like every other
    # non-probe path.
    #
    # Imported here rather than at module scope, and this is the one place in the package where
    # that is deliberate: `vsir/mcp/server.py` imports `dispatch` and `ToolRuntime` from **this**
    # module, because §7.5 requires it to call the identical implementations. A module-scope
    # import back the other way would close that loop. The dependency is one-directional at
    # import time and the MCP surface is the leaf, which is exactly the shape the rule describes.
    from vsir.mcp import server as mcp_server

    app.state.mcp_paths = mcp_server.mount(app)

    @app.get("/console", response_class=HTMLResponse, tags=["console"], responses={
        404: {"description": "this release ships no console page"},
    })
    async def console() -> Any:
        """The operator console for what this release serves — one static page, no build step.

        **Not §13 M7's console.** That is a React + Vite app with a page viewer, region zoom and the
        agent's move-by-move trace, and it needs `fetch`, `read` and the runner to exist. This is
        one file served same-origin, so there is no CORS boundary and no second container to keep in
        step with the API. M7 replaces it rather than growing out of it.

        Served by the app rather than by a sidecar for the same reason `/docs` is: the surface an
        operator actually uses has to be the surface that shipped. A page served from somewhere else
        can disagree with the release it is pointed at, and the first thing that disagreement costs
        is trust in what the page says.
        """
        if not CONSOLE_PAGE.is_file():                    # pragma: no cover — packaging, not logic
            return JSONResponse(status_code=404, content={
                "error": "console_unavailable",
                "detail": f"{CONSOLE_PAGE.name} is missing from the release — the package data "
                          f"declaration in pyproject.toml is what ships it",
            })
        return HTMLResponse(CONSOLE_PAGE.read_text(encoding="utf-8"))

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

    # ── the tools (§7.2, §7.4) ───────────────────────────────────────────────────────────────────

    @app.post("/tools/{tool_name}", tags=["tools"], responses={
        400: {"description": "a typed bound of §7.3 — never a clamp and never a truncation"},
        401: {"description": "no bearer token (§7.4); the probes are the only free paths"},
        404: {"description": "no such tool in this release; the body lists the ones there are"},
        429: {"description": "the per-caller read quota is exhausted (§7.3)"},
        500: {"description": "a bug in this service, named by exception type and nothing more"},
        502: {"description": "the model backend answered unusably"},
        503: {"description": "a backing service did not answer — retryable, never empty (§11.3)"},
    })
    async def call_tool(tool_name: str, request: Request) -> Any:
        """One route for the eight tools of §7.2, each an envelope of §7.1.

        Auth has already happened, in middleware, for every path but the three probes — so there
        is no decorator here to forget and no route that is protected only by having remembered.

        Everything after the JSON parse is :func:`dispatch`, which the MCP surface calls with the
        same runtime: the name lookup, the validation, the budget, the audit line and the typed
        refusals are one implementation and this route adds only the transport (§7.5). The
        dispatch runs in a worker thread, because the Qdrant client is sync and a blocking call
        on the event loop is an outage for every other request in flight.

        The body is written with :func:`~vsir.serve.envelope.wire` rather than handed to
        ``JSONResponse``, so *these* are the bytes the byte-identity criterion compares against —
        one serialiser, and nothing for the two transports to disagree about.
        """
        identity = auth_module.identity_of(request.scope)
        if identity is None:
            # Unreachable behind `BearerAuth`, and here anyway: if this route is ever mounted
            # somewhere the middleware does not cover, the failure must be a refusal rather than
            # an anonymous tool call. Failing closed costs one branch.
            refusal = auth_module.Unauthorized()
            return JSONResponse(status_code=refusal.http_status, content=refusal.to_payload(),
                                headers=refusal.headers)

        try:
            payload = await request.json() if await request.body() else {}
        except ValueError as malformed:
            outcome = _tool_refusal("invalid_json", f"the request body is not JSON: {malformed}",
                                    status=400, tool=tool_name)
        else:
            if not isinstance(payload, dict):
                outcome = _tool_refusal(
                    "invalid_request",
                    f"a tool body is a JSON object of {tool_name}'s parameters, got "
                    f"{type(payload).__name__}",
                    status=400, tool=tool_name)
            else:
                outcome = await run_in_threadpool(
                    dispatch, app.state.runtime, tool_name, payload, identity=identity,
                    correlation=dict(request.scope.get(SCOPE_CORRELATION) or {}))

        return Response(content=outcome.body(), status_code=outcome.status,
                        media_type="application/json")

    # ── ingestion over HTTP: the transport for `vsir ingest` (§6.1, §15 Factor XII) ───────────────

    @app.post("/documents", status_code=202, tags=["ingest"], responses={
        400: {"description": "an empty body, an unknown step, or an unknown VLM backend"},
        401: {"description": "no bearer token (§7.4)"},
        403: {"description": "the release bills a live model and VSIR_ALLOW_PAID is not set"},
        413: {"description": "larger than the spool bound"},
        415: {"description": "the bytes do not begin with %PDF-"},
        500: {"description": "the ingest process could not be started"},
    })
    async def post_document(
        file: UploadFile = File(..., description="the source PDF"),
        until: str = Form("publish", description="stop after this §6.1 step"),
        vlm: str = Form("", description="override VSIR_VLM for this run: `stub` or `gemini`"),
        fixture: str = Form("", description="override VSIR_FIXTURE — the replay directory (D10)"),
        doc_id: str = Form("", description="the revision-stable document id (§5.1)"),
        revision: str = Form("", description="the revision; the operator's value is authoritative"),
        doc_type: str = Form("", description="the document type"),
        subjects: str = Form("", description="comma-separated machine/model subjects (§5.3)"),
        tags: str = Form("", description="comma-separated uploader tags (§5.3)"),
        uploader: str = Form("", description="who supplied the document"),
        request: Request = None,  # type: ignore[assignment]
    ) -> Any:
        """Accept a PDF and start `vsir ingest` on it. **202 and a `run_id`, not a result.**

        The route is a transport and nothing else — see :mod:`vsir.serve.ingest` for why that is
        the whole design rather than a shortcut, and for the two properties an upload gives up that
        a CLI ingest keeps.

        Progress is ``GET /runs/{run_id}``: the control plane, not this process, so a poll works
        from any replica (§6.9, D9). Nothing the run writes is queryable until its blocking gates
        pass — step 10 writes ``is_current=False`` and step 11 is the only thing that flips it
        (I7, §6.7) — so defaulting ``until`` to the full pipeline is safe: a document that fails a
        gate leaves the index exactly as it was.
        """
        identity = auth_module.identity_of(request.scope) if request is not None else None
        body = await file.read()
        try:
            accepted = await run_in_threadpool(
                ingest_module.accept, cfg,
                filename=file.filename or "", body=body, until=until, vlm=vlm, fixture=fixture,
                declared={"doc_id": doc_id, "revision": revision, "doc_type": doc_type,
                          "subjects": subjects, "tags": tags, "uploader": uploader},
                caller=identity.user_id if identity else "")
        except ingest_module.UploadRefused as refusal:
            _log.warning("upload_refused", reason=refusal.code, detail=refusal.message,
                         user_id=identity.user_id if identity else "unknown",
                         **refusal.details)
            return JSONResponse(status_code=refusal.http_status, content=refusal.to_payload())
        return JSONResponse(status_code=202, content=accepted.to_payload())

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

    app.openapi = _described(app)                                    # type: ignore[method-assign]
    return app


def _described(app: FastAPI) -> Callable[[], dict[str, Any]]:
    """The OpenAPI document, with the bearer requirement §7.4 actually enforces written into it.

    FastAPI infers a schema from the routes, and what it cannot infer is the thing this app does in
    middleware: **default deny by path**. Auth is not a per-route `Depends`, deliberately — a
    dependency is opt-in and the route added next milestone would be unauthenticated until somebody
    remembered (see `serve/auth.py`). The cost of that choice is that the generated document
    described an API with no security at all, which is wrong in the direction that matters: a reader
    concludes no token is needed, and Swagger UI shows no *Authorize* button, so every `Try it out`
    comes back 401 with nowhere to put a credential.

    So the requirement is declared here, once, from the same list the middleware reads — every path
    that is not in :data:`~vsir.serve.auth.PUBLIC_PATHS` gets ``security: [{bearerAuth: []}]`` and a
    documented ``401``. Derived rather than annotated: a route added later is covered without
    anyone remembering, which is the same property the middleware has.
    """
    described: dict[str, Any] = {}

    def openapi() -> dict[str, Any]:
        if described:
            return described
        schema = get_openapi(title=app.title, version=app.version,
                             description=app.description, routes=app.routes)
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "One of `VSIR_API_TOKENS` (§7.4). Identity comes from the token and from nothing "
                "else — there is no `X-User-Id` and a client-supplied one is ignored and logged. "
                "Paste the token into **Authorize** and every request below carries it."),
        }
        for path, operations in schema.get("paths", {}).items():
            if path in auth_module.PUBLIC_PATHS:
                continue
            for operation in operations.values():
                if not isinstance(operation, dict):
                    continue
                operation["security"] = [{"bearerAuth": []}]
                operation.setdefault("responses", {}).setdefault("401", {
                    "description": "no bearer token, or one this release does not know. The body "
                                   "names neither which part failed nor which tokens exist (§15.1)",
                })
        described.update(schema)
        return described

    return openapi


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
