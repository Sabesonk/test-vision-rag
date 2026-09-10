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
can arrive with its own idea of auth, of the budget, or of which failures are which. The table
holds all eight tools of §7.2 — the three `skim_*` rungs, `lookup`, `resolve`, `verify`, `fetch`
and, from U020, `read`, the one row that spends. A name that is not in the table is a typed `404`
naming what is, never a 501-shaped silence.

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

import base64
import binascii
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from dataclasses import dataclass
from typing import (Any, AsyncIterator, Awaitable, Callable, Iterator, Literal, Mapping,
                    MutableMapping, Sequence)

from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.openapi.utils import get_openapi
from pydantic.json_schema import models_json_schema
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               StreamingResponse)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from starlette.concurrency import run_in_threadpool

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.config import DPI_INDEX, LOOKUP_CAP, Config, load_config
from vsir.doctor import QDRANT_UNAVAILABLE, BootRefused, assert_boot_ok, run_boot_checks
from vsir.ingest import embed as embed_module
from vsir.ingest import export as export_module
from vsir.ingest import run as run_module
from vsir.serve import audit as audit_module
from vsir.serve import auth as auth_module
from vsir.serve import budget as budget_module
from vsir.serve import ingest as ingest_module
from vsir.serve import raster_cache
from vsir.serve.audit import Usage
from vsir.serve.auth import BearerAuth, Identity
from vsir.serve.caps import ALLOWED_DPI, ToolError, validate_fetch_megapixels
from vsir.serve import errors
from vsir.serve import manage
from vsir.serve.envelope import (DocHit, FetchResult, LookupHit, PageHit, Provenance,
                                 ReadResult, ResolveHit, SearchResponse, SectionHit,
                                 ToolEnvelope, VerifyResult, wire)
from vsir.serve.inputs import (FetchRequest, LookupRequest, ReadRequest, ResolveRequest,
                               SkimAggregateRequest, SkimDocumentsRequest,
                               SkimPagesRequest, SkimSectionsRequest, ToolRequest,
                               VerifyRequest)
from vsir.serve.tools.fetch import INCLUDE_ALL, PART
from vsir.serve.tools.fetch import fetch as fetch_tool
from vsir.serve.tools.lookup import lookup as lookup_tool
from vsir.serve.tools.read import precheck as read_precheck
from vsir.serve.tools.read import read as read_tool
from vsir.serve.tools.resolve import resolve as resolve_tool
from vsir.serve.tools.skim import SKIM_LIMIT
from vsir.serve.tools.skim import skim_documents as skim_documents_tool
from vsir.serve.tools.skim import skim_pages as skim_pages_tool
from vsir.serve.tools.skim import skim_sections as skim_sections_tool
from vsir.serve.tools.verify import verify as verify_tool
from vsir import vlm as vlm_module
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
#: `EmbedUnavailable` is here for the same reason and not as an afterthought: `skim_pages` is the
#: first tool that needs a **model** to answer, so a release with no embedding credential must
#: refuse that one rung as an outage while `lookup`, `verify` and `resolve` go on working (§11.3).
VLM_UNAVAILABLE: tuple[type[BaseException], ...] = (VlmUnavailable, VlmCallFailed,
                                                    embed_module.EmbedUnavailable)

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


class ToolCard(BaseModel):
    """One tool, as the index describes it — the move, the path, and whether it spends."""

    model_config = ConfigDict(extra="forbid")

    name: str
    move: str = Field(description="The §7.2 move this tool is — NARROW, JUMP, FOLLOW, CHECK, "
                                  "LOOK, COMPREHEND. What an agent is really choosing between.")
    path: str = Field(description="Its own route. `POST` a JSON object of its parameters.")
    spends: bool = Field(description="Whether calling it costs money. Exactly one tool does.")
    description: str = Field(description="The same text published as the MCP tool description "
                                         "and the route's OpenAPI summary — one string, so a "
                                         "tool cannot be described two ways.")


class ServiceIndex(BaseModel):
    """`GET /` — what this service is, what it serves, and where the credential goes.

    The last gap in a self-documenting API. `/openapi.json` has described every path since U014,
    and an integrator has to *know to ask for it*: the base URL answered `404`, which is the one
    response that teaches nothing. A service that can be discovered from its own root needs no
    onboarding document to get as far as the second request.

    It carries **no corpus data** — no document, no page, no run, no token — which is what makes
    it free to read, on exactly the argument §7.4 makes for `/openapi.json`: what it contains is
    the shape of the interface, and reading the shape authorises nothing.
    """

    model_config = ConfigDict(extra="forbid")

    service: str
    release_id: str
    version: str
    description: str = Field(description="What this service refuses to do, in one line. The "
                                         "premise the rest of the surface enforces.")
    documentation: dict[str, str] = Field(
        description="Where the interface describes itself: the OpenAPI document and the two pages "
                    "that render it, plus the operator console. All free to read.")
    authentication: dict[str, str] = Field(
        description="How to authenticate, and what identity is derived from. There is no "
                    "`X-User-Id` — a client-supplied one is ignored and logged (§7.4).")
    tools: list[ToolCard] = Field(
        description="The eight moves of §7.2 **in ladder order**, not alphabetical: an agent "
                    "reading this list for the first time is choosing a move, and the order is "
                    "the order the moves narrow in.")
    paths: dict[str, str] = Field(
        description="Every route this release serves, with what it is for. Derived from the app's "
                    "own router, so a route added later appears here without anyone remembering.")


class ControlError(errors.ErrorResponse):
    """A typed refusal from the control-plane surface (§11.3) — `ErrorResponse` plus `run_id`.

    Named and distinct, always. An unknown run is `run_not_found` and a store that did not answer
    is `qdrant_unavailable`: the first is a fact about the request, the second is somebody else's
    outage, and collapsing them into one empty body is how a caller retries the wrong thing.

    A **subclass** rather than its own model, since `serve/errors.py` exists: this surface refuses
    in the same shape as every other one, and two independent declarations of `{error, detail}` is
    how a client ends up with two error types for one contract. All this row adds is the field
    that is genuinely its own.
    """

    run_id: str = Field(
        default="",
        description="The run the refusal is about, where the request named one.")


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
# The eight input schemas moved to `serve/inputs.py` — see that module's note for why. They are
# re-exported here because this is the name every caller already imports them under (the suite,
# `mcp/server.py` via the table, and the one-shot CLI), and because `ToolSpec.request` is typed
# against `ToolRequest`: an import in one place is the seam, a rename across the suite is churn.


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
    #: The embedding backend, as a factory rather than an instance. A `lookup` must not pay for a
    #: model client it will never use, and a release configured for Gemini with no credential must
    #: still serve every free tool that does not embed — so the refusal happens when a query is
    #: actually embedded, as a `503 vlm_unavailable`, and not at boot (§11.3).
    embedder: Callable[[], Any] = lambda: None
    #: The VLM backend, on the same terms and for the same reason: `read` is the only tool that
    #: needs one, and §11.3 requires every free tool to keep working while it is unreachable. A
    #: factory means that failure lands on `read` as a `503` instead of on start-up.
    vlm: Callable[[], Any] = lambda: None


@dataclass(frozen=True)
class ToolSpec:
    """One row of the table: the name, its shapes on the wire, the call, and whether it spends."""

    name: str
    request: type[ToolRequest]
    call: Callable[[ToolContext, Any], tuple[BaseModel, Usage]]
    #: The envelope this tool returns, declared so the per-tool route of §7.4 can **publish** it.
    #: A column on the table rather than a lookup beside it, for the reason `request` is one: the
    #: table is the release's single declaration of its surface, and a second mapping from name to
    #: response type is a second thing to forget when a tool is added.
    #:
    #: It is published and never *applied* — the route declares it under ``responses={200: ...}``
    #: and returns raw bytes from :func:`~vsir.serve.envelope.wire`. Handing it to FastAPI as
    #: ``response_model`` would put a second serialiser on the response path, and the byte-identity
    #: criterion between HTTP and MCP (§7.5) is only meaningful while there is exactly one.
    response: type[BaseModel] | None = None
    #: Charges the per-caller `read` quota before running (§7.3). Only `read` sets it (§7.2.6).
    spends: bool = False
    #: Bounds that can be settled from the request alone, run **before** the quota is charged.
    #: Only a spending tool needs one, and it needs one badly: a caller that named four pages
    #: must not have a read taken off its quota to be told it named four pages (§7.3, F18).
    precheck: Callable[[Any], None] | None = None
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
    #: The embedding backend for the query side of a skim, memoised per process by
    #: :func:`query_embedder`. A backend handle like ``search``, not state: it holds a connection
    #: and a pinned model id, and nothing about a caller, a session or a previous call (§15 VI).
    embedder: Callable[[], Any] = lambda: None
    #: The VLM backend `read` calls, memoised per process by :func:`vlm_backend`. Same terms.
    vlm: Callable[[], Any] = lambda: None


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


def _call_skim_pages(context: ToolContext, body: SkimPagesRequest) -> tuple[BaseModel, Usage]:
    """The adapter for §7.2.1's page rung. Decodes the image, and adds no behaviour."""
    image = _skim_image(body)
    response = skim_pages_tool(
        context.client, context.cfg.pages_collection,
        query=body.query, image=image, scope=body.scope, exclude=body.exclude, limit=body.limit,
        embedder=context.embedder(),
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )
    return response, Usage.free()


def _skim_image(body: SkimPagesRequest | SkimAggregateRequest) -> bytes | None:
    """The base64 of a photographed panel → bytes, or a typed refusal naming the field.

    Decoded **here** rather than in the tool, because it is a property of the transport:
    `serve/tools/skim.py` takes bytes, the way `ingest/embed.py` does, and a malformed encoding is
    the caller's request being wrong rather than the search being empty. One function for all
    three rungs, so a photograph is refused identically whichever one receives it.
    """
    if not body.image:
        return None
    try:
        image = base64.b64decode(body.image, validate=True)
    except (binascii.Error, ValueError):
        raise ToolError(
            "image_invalid",
            "image is base64 of the photograph's bytes (§7.2.1, D12) and this did not decode",
            field="image", length=len(body.image),
        ) from None
    if not image:
        raise ToolError("image_invalid", "image decoded to zero bytes", field="image")
    return image


def _call_skim_documents(context: ToolContext,
                         body: SkimDocumentsRequest) -> tuple[BaseModel, Usage]:
    """§7.2.1's document rung. The same adapter shape, and no ``limit`` to pass on."""
    response = skim_documents_tool(
        context.client, context.cfg.pages_collection,
        query=body.query, image=_skim_image(body), scope=body.scope, exclude=body.exclude,
        embedder=context.embedder(),
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )
    return response, Usage.free()


def _call_skim_sections(context: ToolContext,
                        body: SkimSectionsRequest) -> tuple[BaseModel, Usage]:
    """§7.2.1's section rung — the same fused candidates, grouped by ``section_id``."""
    response = skim_sections_tool(
        context.client, context.cfg.pages_collection,
        query=body.query, image=_skim_image(body), scope=body.scope, exclude=body.exclude,
        embedder=context.embedder(),
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )
    return response, Usage.free()


def _call_resolve(context: ToolContext, body: ResolveRequest) -> tuple[BaseModel, Usage]:
    """§7.2.3, and the shortest adapter in the table: a label in, a list of candidates out."""
    response = resolve_tool(
        context.client, context.cfg.pages_collection, body.printed_label,
        doc_id=body.doc_id or None,
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )
    return response, Usage.free()


def _call_fetch(context: ToolContext, body: FetchRequest) -> tuple[BaseModel, Usage]:
    """§7.2.5. The first adapter that hands the tool the whole ``cfg`` and not one collection name.

    `fetch` needs three things this release keeps in separate places — the page index, the run
    record that says which bytes those pages were indexed from (§6.9), and the document store the
    bytes are in (U029) — and all three are named by configuration. Passing ``cfg`` keeps the
    resolution chain inside the tool, where `GET /pages/{page_id}/image` shares it, rather than
    reassembling it per transport.

    The only adapter that returns a real :class:`Usage`: `fetch` is **free** (§8.1a — it costs the
    agent's own context) and it is still audited, because the shared §7.4 line tracks image-byte
    movement rather than spend.
    """
    return fetch_tool(
        context.client, context.cfg, body.page_ids,
        include=body.include, dpi=body.dpi, region=body.region, inline=body.inline,
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )


def _call_read(context: ToolContext, body: ReadRequest) -> tuple[BaseModel, Usage]:
    """§7.2.6 — the only adapter that hands a tool the **model** boundary.

    ``context.vlm()`` is built on first use and refuses by name when it cannot be: no credential,
    or `VSIR_VLM=stub` with no fixture directory. That refusal arrives here rather than at boot on
    purpose (§11.3) — every free tool must keep answering while the model backend is unreachable,
    and it only can if nothing but this line depends on one existing.

    The dpi is not passed, because there is nothing to pass: it is pinned at 220 inside the tool
    and it is an input to ``read_key`` (§7.2.6, §6.3).
    """
    return read_tool(
        context.client, context.cfg, body.page_ids, body.question,
        backend=context.vlm(),
        provenance=context.provenance, reads_remaining=context.reads_remaining,
    )


#: What each tool is *for*, in the words an agent needs to choose between them. Kept beside the
#: table rather than lifted from the Python docstrings: those explain the implementation to a
#: maintainer, and a tool description explains a **move** to a caller (§7.2, §8.2).
SKIM_PAGES_DESCRIPTION = (
    "NARROW. Triage rows for a question or a photograph — at most 10 pages (25 with `limit`), "
    "ordered by rank alone. `rank` is an ordinal and there is no score anywhere in the response; "
    "`why` names the branches that found the row (`dense` = the page's image+text vector, "
    "`lexical` = its extracted text, `captions` = its generated summary), and a `lexical` hit is "
    "harder evidence than a `dense` one. A printed code in the query is split out and matched as "
    "an exact phrase rather than embedded, so `\"reset K158\"` means pages about reset that print "
    "K158. `image` is base64 and may be sent with or without words; an image-only query runs the "
    "dense branch alone and every row says `why: [\"dense\"]`. `exclude` drops pages you have "
    "already rejected — the service holds no memory of them. Every row carries an `image.url` and "
    "a `next` to expand into the section or step to a neighbour, and **no row carries page text "
    "or image bytes**: choose a page, then pay for it with `fetch` or `read`. Free."
)
SKIM_DOCUMENTS_DESCRIPTION = (
    "NARROW, top rung. *Which binder?* — the same page search as `skim_pages`, grouped by "
    "document, so one chatty manual cannot occupy every slot and bury the binder that answers. "
    "At most 10 rows, ordered by `best_rank` then by how many of its pages matched. A row is a "
    "**scope, not a citation**: it carries no `page_id`, and `next.expand` is the dict to pass "
    "back as the next rung's `scope`. Every row states `searchable_ratio` — the share of that "
    "binder that has a text layer at all — and **a binder at 0.00 is returned even when nothing "
    "in it matched**, with `pages_matched: 0` and a thumbnail: it is the one place a scanned "
    "document can be seen, and concluding a part does not exist from a search that could not "
    "read it is the mistake this row exists to prevent. Free."
)
SKIM_SECTIONS_DESCRIPTION = (
    "NARROW, middle rung. *Which chapter?* — the same page search grouped by section, with each "
    "row's `page_range` and, in `next.expand`, the scope that opens it. At most 10 rows, ordered "
    "by `best_rank` then by pages matched; a page that straddles two sections counts in both. "
    "Like `skim_documents` it carries no `page_id` and no page text — descend to `skim_pages` "
    "for those. Free."
)
RESOLVE_DESCRIPTION = (
    "FOLLOW. A printed page label — `\"8\"`, `\"Page 8 of 55\"` — to the `page_id` that opens it, "
    "for following a cross-reference you read on a page. Each candidate says whether the page's "
    "own text prints that label (`label_verified`) and whether the number was inferred from the "
    "pages either side rather than read off this one (`interpolated`). **An ambiguous label "
    "returns every candidate**, never a pick: two binders that both number a page 8 are a "
    "question for you, and choosing for you is how an answer ends up citing the wrong page. Pass "
    "`doc_id` to narrow. Free."
)
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
FETCH_DESCRIPTION = (
    "LOOK. The material of pages you have already chosen — the page image, its extracted text "
    "and its summary — instead of an answer, so you can reason across them, keep the evidence "
    "and ask a follow-up without paying again. **Free**: it calls no model. At most 5 pages and "
    "12 megapixels per call, and an over-budget call is a typed refusal naming the bound, never "
    "a truncated page list. `dpi` is one of 36, 72, 150 (the default), 220, 300, 400; above 220 "
    "a normalised `region` [x0,y0,x1,y1] is required, because detail that fine is about part of "
    "a page. `inline` defaults to true and returns the pixels as `bytes_b64` beside the URL; "
    "`inline=false` returns the URL only. Dropping \"image\" from `include` makes this a cheap "
    "text/summary read — and every page still reports `text_trust`, so a scanned page's empty "
    "`text` cannot be mistaken for a blank page. Use `read` only when you need a model to "
    "interpret the image."
)
READ_DESCRIPTION = (
    "COMPREHEND. **The one tool that costs money.** A directed vision read of at most 3 pages you "
    "have already chosen, at a pinned 220 dpi you cannot change, answering one question. Returns "
    "a bounded `extract`, a `codes` table and `sufficient` — and nothing that decides anything "
    "for you. Every code the model emits is phrase-checked against that page's own extracted "
    "text before you see it, and stamped `present`, `absent` (with `present_instead` — a "
    "different part, never a nearest match) or `unverifiable`; on a page with no text layer every "
    "code is `unverifiable`, which is the honest answer and not a defect. **`sufficient` is the "
    "field to read first**: `false` means these pages do not answer the question, which is a "
    "different fact from an answer of 'no' and is your signal to look elsewhere rather than to "
    "compose from what came back. A fourth page is a typed 400 naming the bound; an exhausted "
    "quota is a 429, never a truncated page list. Prefer `fetch` when you can look at the page "
    "yourself — `read` is for delegating a bounded sub-answer, and it is the step that bills."
)
VERIFY_DESCRIPTION = (
    "CHECK. Is each of these codes actually printed on each of these pages? Per (claim, page), "
    "so a draft citing two pages cannot borrow the neighbouring page's evidence. Three verdicts: "
    "`present`, `absent` (with up to five `present_instead` codes observed on the page — a "
    "different part, never a nearest match), and `unverifiable` (no text layer, an untrusted "
    "extraction, or a page that is not current) — which is never the same as `absent`. Every "
    "claim absent is still a successful call. Free."
)


#: The **move** each tool is, from §7.2's own headings — the word an agent is really choosing
#: between. Used as the named route's OpenAPI summary, so `/docs` reads as the ladder it is
#: (NARROW → JUMP → FOLLOW → CHECK → LOOK → COMPREHEND) rather than eight alphabetised verbs.
_LADDER_MOVE = {
    "skim_documents": "NARROW", "skim_sections": "NARROW", "skim_pages": "NARROW",
    "lookup": "JUMP", "resolve": "FOLLOW", "verify": "CHECK", "fetch": "LOOK",
    "read": "COMPREHEND (the paid step)",
}


#: What each OpenAPI tag group **is**, published as `openapi_tags` so `/docs` explains its own
#: sections. Swagger renders seven headings, and until this existed they were seven bare words —
#: a reader could see that `corpus` and `runs` were different groups and not what either was for,
#: which is the same failure the untyped tool body was: the information existed and the document
#: did not carry it.
#:
#: The order is the order Swagger renders them in, and it is the order somebody meets the service:
#: what is it → is it up → put a document in → see what went in → find something → look at a page.
OPENAPI_TAGS: list[dict[str, Any]] = [
    {"name": "service", "description":
        "**Start here.** `GET /` is the service index: the release, every path, the eight tools "
        "in ladder order, and where the credential goes. Free to read, like the description "
        "itself — it names the surface and returns no corpus data."},
    {"name": "probes", "description":
        "Liveness, readiness and metrics (§15.1, §11.4). **Free, and the only free paths that "
        "are not documentation**: an orchestrator has to reach them before anything is "
        "configured. `/health` is green whenever the process can answer — it MUST NOT fail on a "
        "backing-service outage, because a restart does not fix somebody else's Qdrant. `/ready` "
        "is the one that goes red for that."},
    {"name": "ingest", "description":
        "Putting a document in (§6.1). `POST /documents` is a **transport and nothing else**: it "
        "spools the bytes and runs `vsir ingest`, the same subcommand from the same image, so "
        "there is no second pipeline (§15 Factor XII, register E1). It answers `202` and a "
        "`run_id`, never a result — progress is `GET /runs/{run_id}`, which reads the control "
        "plane rather than this process, so a poll works from any replica."},
    {"name": "corpus", "description":
        "Reading what the index **contains** — documents, their revisions, and their pages "
        "(§5.1–5.3, §5.7). Queries over the collections ingestion already writes, so they cannot "
        "drift from what a search sees. All read-only: retirement is §6.7's and runs inside a "
        "publish, where the run record is its evidence.\n\nThe addressable unit is the **page**, "
        "under the `page_id` of §5.2 — there is no chunk in this system, by design: a window is a "
        "page range that stitching deletes again and never becomes a retrieval boundary."},
    {"name": "runs", "description":
        "The run control plane (§6.9) and the two streamed exports (§6.8). `GET /runs` is the "
        "history; `GET /runs/{run_id}` is one whole record — state, step, gates, overrides, lease, "
        "cost, retirement. **`gated` is not `failed`**: the run finished and §11.1's gates "
        "declined to publish what it produced, which is the outcome they exist to produce."},
    {"name": "tools", "description":
        "The eight moves of §7.2, each on its own path, in ladder order: **NARROW** "
        "(`skim_documents` → `skim_sections` → `skim_pages`), **JUMP** (`lookup`), **FOLLOW** "
        "(`resolve`), **CHECK** (`verify`), **LOOK** (`fetch`), and **COMPREHEND** (`read`) — the "
        "one tool that spends.\n\nTwo properties to rely on. **Nothing matched is a typed "
        "absence, never an empty `200`** — `not_found`, `not_searchable`, `out_of_scope` and "
        "`found_only_in_superseded` are different facts and an agent acts differently on each "
        "(§7.1). And **every bound is a refusal with its own code**, never a clamp and never a "
        "truncation, so a caller is told what it broke rather than silently given less (§7.3)."},
    {"name": "pages", "description":
        "The page raster, rendered on demand and **never persisted** (§4.2) — the "
        "browser-renderable half of `fetch`. Same dpi tiers and same typed refusals as §7.3: "
        "above 220 dpi a `region` is required, because a full page at 400 exceeds the megapixel "
        "bound."},
    {"name": "console", "description":
        "The operator console — one static page, served same-origin so there is no CORS boundary "
        "and no second container. Free because a browser cannot attach a credential to a plain "
        "navigation; the page then asks for one and every call it makes carries it."},
]


def tool_table() -> dict[str, ToolSpec]:
    """The tools this release exposes — over HTTP at ``POST /tools/{tool_name}`` and over MCP.

    A function, not a module constant, for the reason §15.2 bans a module-level mutable store: a
    dict at import time is one object shared by every app in the process, and a test that pointed
    one app at a different table would be changing every other app's. Each :func:`create_app`
    gets its own, parked on ``app.state`` and handed to the :class:`ToolRuntime`.

    All eight of §7.2 are here from U020. A name that is *not* in the table is a typed `404`
    listing what is served, because a tool that is not in this release is absent, not empty —
    the same argument §7.1 makes about results, applied to the surface itself.

    The order of the rows is the order of the ladder, not alphabetical: an agent reading the tool
    list for the first time is choosing a **move**, and `skim_documents` → `skim_sections` →
    `skim_pages` → `lookup` → `resolve` → `verify` → `fetch` → `read` is the narrowing ladder,
    then jump, follow, check, look, and only then the step that spends (§7.2, §8.1).
    """
    return {
        "skim_documents": ToolSpec(name="skim_documents", request=SkimDocumentsRequest,
                                   call=_call_skim_documents,
                                   response=SearchResponse[DocHit],
                                   description=SKIM_DOCUMENTS_DESCRIPTION),
        "skim_sections": ToolSpec(name="skim_sections", request=SkimSectionsRequest,
                                  call=_call_skim_sections,
                                  response=SearchResponse[SectionHit],
                                  description=SKIM_SECTIONS_DESCRIPTION),
        "skim_pages": ToolSpec(name="skim_pages", request=SkimPagesRequest, call=_call_skim_pages,
                               response=SearchResponse[PageHit],
                               description=SKIM_PAGES_DESCRIPTION),
        "lookup": ToolSpec(name="lookup", request=LookupRequest, call=_call_lookup,
                           response=SearchResponse[LookupHit],
                           description=LOOKUP_DESCRIPTION),
        "resolve": ToolSpec(name="resolve", request=ResolveRequest, call=_call_resolve,
                            response=SearchResponse[ResolveHit],
                            description=RESOLVE_DESCRIPTION),
        "verify": ToolSpec(name="verify", request=VerifyRequest, call=_call_verify,
                           response=ToolEnvelope[VerifyResult],
                           description=VERIFY_DESCRIPTION),
        # Free (§8.1a, SA-9) and audited anyway: the §7.4 line beside `read`'s tracks image-byte
        # movement, which is the resource this tool actually consumes.
        "fetch": ToolSpec(name="fetch", request=FetchRequest, call=_call_fetch,
                          response=ToolEnvelope[FetchResult],
                          description=FETCH_DESCRIPTION),
        # The one row with `spends=True`, and therefore the one row with a `precheck`: the budget
        # is charged before the call, so every bound that can be checked without the store is
        # checked before the charge (§7.3, F18).
        "read": ToolSpec(name="read", request=ReadRequest, call=_call_read, spends=True,
                         response=ToolEnvelope[ReadResult],
                         precheck=lambda body: read_precheck(body.page_ids, body.question),
                         description=READ_DESCRIPTION),
    }


def query_embedder(cfg: Config) -> Callable[[], Any]:
    """A memoised embedding backend for one process — built on first use, then held.

    The same shape as the Qdrant client and for the same reason: it is a **backend handle**, so
    building one per request would open an SDK client per request, and building one at boot would
    make a release configured for Gemini refuse to start without a credential even though every
    tool but this one is free and works without it. Nothing about a caller or a previous call is
    kept, so this is a connection pool and not the session state §15.2 bans.

    A failure to build is raised at the call, where :func:`_failure_response` turns
    :class:`~vsir.ingest.embed.EmbedUnavailable` into `503 vlm_unavailable` — an outage, never an
    empty result (§11.3).
    """
    held: list[Any] = []

    def backend() -> Any:
        if not held:
            held.append(embed_module.embedder(cfg))
        return held[0]

    return backend


def vlm_backend(cfg: Config) -> Callable[[], Any]:
    """A memoised VLM backend for one process — built on first use, then held.

    :func:`query_embedder`'s shape, for the same three reasons: building one per request would
    open an SDK client per request, building one at boot would make a release refuse to start
    without a credential even though seven of the eight tools are free and need none, and a held
    backend is a connection pool rather than the session state §15.2 bans.

    The fourth reason is this one's alone and it is §11.3's row: *"Gemini unreachable → `503
    vlm_unavailable` on `read`; every free tool keeps working."* That sentence is only true if
    nothing but `read` ever calls this — so :class:`~vsir.vlm.cache.VlmUnavailable` is raised at
    the call, where :func:`_failure_response` turns it into the `503` the row asks for.
    """
    held: list[Any] = []

    def backend() -> Any:
        if not held:
            held.append(vlm_module.backend(cfg))
        return held[0]

    return backend


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
    return ToolRuntime(config=cfg, search=client, tools=tool_table(),
                       embedder=query_embedder(cfg), vlm=vlm_backend(cfg)), client


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
    if isinstance(failure, (VlmError, embed_module.EmbedError)):
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
            # Before the charge, never after: a bound that can be settled from the request alone
            # must not cost a read to discover. `read` with four pages is a `400` naming the
            # bound and a quota that is exactly where it was (§7.3, F18).
            if spec.precheck is not None:
                spec.precheck(body)
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
                            provenance=Provenance(release_id=cfg.release_id),
                            embedder=runtime.embedder, vlm=runtime.vlm),
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
                                        tools=app.state.tools,
                                        embedder=query_embedder(cfg), vlm=vlm_backend(cfg))
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
        openapi_tags=OPENAPI_TAGS,
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

    @app.get("/", response_model=ServiceIndex, tags=["service"],
             summary="the service index — what this is, what it serves, where the token goes")
    async def index() -> ServiceIndex:
        """The root, which used to be a `404` — the one response that teaches nothing.

        **Derived, never hand-listed.** The tool cards come from `app.state.tools` and the path
        table from `app.routes`, so a tool or a route added next milestone appears here without
        anybody remembering to add it — the same property the auth middleware has, and for the
        same reason: a list maintained by hand is a list that is wrong by the second release.

        Free to read, and that is a deliberate extension of :data:`~vsir.serve.auth.DOC_PATHS`
        rather than a hole in it: this body is the *shape* of the interface — paths, tool names,
        where a credential goes — and contains no document, no page, no run and no token. §7.4
        already makes that argument for `/openapi.json`; a reader who can see the path list is
        exactly as far from the corpus as one who can see the OpenAPI document, which is to say
        one `401` away.
        """
        described = {
            "GET /": "this index",
            "GET /health": "liveness — green whenever the process can answer (§15.1)",
            "GET /ready": "readiness — boot checks passed, Qdrant reachable, schema present",
            "GET /metrics": "Prometheus, recomputed from the control plane on every scrape",
            "GET /openapi.json": "the interface, described in full",
            "GET /docs": "Swagger UI — Authorize with your token, then Try it out",
            "GET /redoc": "the same document, rendered for reading",
            "GET /console": "the operator console",
            "POST /documents": "ingest a PDF — 202 and a run_id, never a result (§6.1)",
            "GET /documents": "the corpus — every document, its revisions, its searchable ratio",
            "GET /documents/{doc_id}": "one document and every revision of it",
            "GET /documents/{doc_id}/pages": "one revision's page inventory, with page_ids",
            "GET /runs": "the ingest history — state, step, and which gate refused",
            "GET /runs/{run_id}": "one whole run record (§6.9)",
            "GET /runs/{run_id}/export/labels.jsonl": "the label export, streamed (§6.8)",
            "GET /runs/{run_id}/export/observed_tokens.jsonl": "the observed-token inventory",
            "GET /pages/{page_id}/image": "the page raster, rendered on demand, never persisted",
        }
        # Derived from the router, so the table cannot silently fall behind the surface. The
        # descriptions above are prose and the paths below are the truth; a route with no prose
        # still appears, with its summary or its own name.
        for route_object in app.routes:
            path = getattr(route_object, "path", "")
            for method in sorted(getattr(route_object, "methods", set()) or set()):
                if method in ("HEAD", "OPTIONS") or not path:
                    continue
                key = f"{method} {path}"
                if key not in described:
                    described[key] = (getattr(route_object, "summary", "")
                                      or getattr(route_object, "name", "") or "")

        return ServiceIndex(
            service="vision-segmentation-retriever",
            release_id=cfg.release_id,
            version=__version__,
            description=(
                "A code this service returns is a code printed on the page. Nothing matched is "
                "one of four typed absences, never an empty 200 — an empty success is "
                "indistinguishable from a fabricated abstention."),
            documentation={
                "openapi": "/openapi.json", "swagger": "/docs", "redoc": "/redoc",
                "console": "/console",
            },
            authentication={
                "scheme": "Bearer",
                "header": "Authorization: Bearer <token>",
                "tokens": "one of VSIR_API_TOKENS (§7.4)",
                "identity": "derived from the token — caller-<sha256(token)[:12]>, never the "
                            "token itself and never a client-supplied header",
                "free_paths": ", ".join(sorted(auth_module.PUBLIC_PATHS)),
            },
            tools=[
                ToolCard(name=name, move=_LADDER_MOVE.get(name, ""), path=f"/tools/{name}",
                         spends=spec.spends, description=spec.description)
                for name, spec in app.state.tools.items()
            ],
            paths=described,
        )

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
    # **Nine routes, one transport, one dispatcher.** Each of the eight tools gets its own path —
    # `POST /tools/lookup`, `POST /tools/read` — and `POST /tools/{tool_name}` stays behind them.
    #
    # Why the named routes exist. The generic route is the right *implementation* and it was the
    # wrong *description*: one OpenAPI operation with an untyped body, so `/docs` showed a single
    # "tool_name + JSON" form for eight tools whose parameters have nothing in common, and a client
    # generated from `/openapi.json` got one `call_tool(name, dict)` with no types on either side.
    # An integrator had to read our source to learn that `read` takes `question` and `fetch` takes
    # `dpi`. Named routes publish each tool's own schema, and Swagger renders eight real forms.
    #
    # Why "one route and a table" is not violated by this. That rule was always about the
    # *implementation* — register **E1**, §15 Factor XII, and §7.5's requirement that MCP and HTTP
    # cannot drift. Every one of these routes is a two-line closure over :func:`_serve_tool`, and
    # every one of them reaches the tools through :func:`dispatch` with the same runtime, so the
    # name lookup, the validation, the budget, the audit line and the typed refusals remain one
    # implementation. They are generated **from the table** in a loop rather than hand-written
    # eight times, so a tool cannot get a route without being in the table, and a tool cannot be in
    # the table without getting a route.
    #
    # Why the generic route survives underneath. Registration order decides matching, so the
    # literal paths win for the eight names and `{tool_name}` catches everything else — which is
    # exactly the behaviour it should keep: an unknown name is a typed `404` listing what *is*
    # served (a tool absent from this release is absent, not empty). It also keeps every existing
    # client, the one-shot CLI and the MCP parity suite working unchanged.

    async def _serve_tool(tool_name: str, request: Request) -> Response:
        """The transport for every tool, named or generic. Everything else is :func:`dispatch`.

        Auth has already happened, in middleware, for every path but the three probes — so there
        is no decorator here to forget and no route that is protected only by having remembered.

        **This function does not validate the body, and that is deliberate.** The named routes
        publish their request schema through ``openapi_extra`` rather than declaring a typed
        parameter, because a typed parameter would hand validation to FastAPI and FastAPI's
        failure is a `422` with a JSON pointer. §7.3's contract is that a bad request comes back
        as a **typed code an agent can switch on** — `invalid_request` naming the field — and
        `dispatch` is where that happens, for both transports. So the schema is published and the
        validation stays in one place; the two would otherwise disagree the moment a route was
        reached through the path the other client uses.

        The dispatch runs in a worker thread, because the Qdrant client is sync and a blocking
        call on the event loop is an outage for every other request in flight.

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

    def _register_tool_route(spec: ToolSpec) -> None:
        """One named route for one row of the table. Called in a loop, never written out by hand.

        ``openapi_extra`` carries the request body by ``$ref`` and :func:`_described` puts the
        referenced schema in ``components`` — see :func:`_serve_tool` for why the body is not a
        typed parameter, and :attr:`ToolSpec.response` for why the envelope is published under
        ``responses`` rather than applied as ``response_model``.
        """
        statuses = (*errors.TOOL_STATUSES, 429) if spec.spends else errors.TOOL_STATUSES
        documented: dict[int | str, dict[str, Any]] = dict(errors.responses(*statuses))
        if spec.response is not None:
            documented[200] = {
                "model": spec.response,
                "description": "the envelope of §7.1 — `status` says whether the **call** ran, "
                               "never what it found",
            }

        @app.post(f"/tools/{spec.name}", tags=["tools"], name=f"tool_{spec.name}",
                  # Set explicitly, because FastAPI derives one from the handler function and
                  # every one of these is the same closure — so the generated ids would have been
                  # `named_tool_tools_lookup_post` and friends, which is what a generated client
                  # calls its methods. The tool's own name is the only sensible one.
                  operation_id=spec.name,
                  summary=f"{_LADDER_MOVE.get(spec.name, '')} — {spec.name}".lstrip(" —"),
                  description=spec.description, response_model=None, responses=documented,
                  openapi_extra={"requestBody": {
                      "required": True,
                      "content": {"application/json": {
                          "schema": {"$ref": f"#/components/schemas/{spec.request.__name__}"}}},
                  }})
        async def named_tool(request: Request, _tool: str = spec.name) -> Response:
            return await _serve_tool(_tool, request)

    for _spec in app.state.tools.values():
        _register_tool_route(_spec)

    @app.post("/tools/{tool_name}", tags=["tools"], include_in_schema=False, responses=dict(
        errors.responses(*errors.TOOL_STATUSES, 404, 429,
                         **{"404": "no such tool in this release; the body lists the ones there "
                                   "are"})))
    async def call_tool(tool_name: str, request: Request) -> Any:
        """The catch-all beneath the eight named routes — an unknown name's typed `404`.

        ``include_in_schema=False`` because the eight named routes above now *are* the published
        surface, and leaving this in the document would describe every tool twice: once properly
        and once as an untyped body, which is the confusion the named routes were added to end.
        It stays **mounted**, and it stays the route that answers a name this release does not
        serve (§7.1 applied to the surface itself) as well as every client written against it.
        """
        return await _serve_tool(tool_name, request)
    # ── the page raster: `fetch`'s browser-renderable half (§7.2.5, §7.4) ────────────────────────

    def _rendered(page_id: str, dpi: int, region: Sequence[float] | None) -> Any:
        """``page_id`` → the raster, with every §7.3 bound in front of it. Sync, by design.

        Both blocking things it does are blocking: Qdrant's client is sync and PyMuPDF is C. The
        route awaits it in a worker thread, because a 220-dpi render on the event loop is an outage
        for every other request in flight.

        The megapixel bound applies here too, and it is not `fetch`'s bound borrowed for company:
        rendering is the memory spike §15.1 names, and a *single* page can exceed 12 MP — an
        E-size drawing at 220 dpi is over seventy. One bound, one code, both surfaces.
        """
        raster_cache.validate_raster_request(dpi, region)
        resolved = raster_cache.resolve_page(app.state.search, cfg, page_id)
        validate_fetch_megapixels(
            raster_cache.megapixels(resolved, dpi=dpi, region=region))
        return raster_cache.raster(resolved, dpi=dpi, region=region)

    @app.get(raster_cache.PAGE_IMAGE_PATH, tags=["pages"], responses={
        200: {"content": {raster_cache.PNG_MEDIA_TYPE: {}},
              "description": "the page raster, rendered on demand and never persisted (§4.2)"},
        304: {"description": "the caller's `If-None-Match` matches this raster's digest"},
        400: {"model": errors.ErrorResponse,
              "description": "a typed bound of §7.3 — `dpi_not_allowed`, `dpi_requires_region`, "
                             "`region_invalid`, `page_id_invalid`"},
        401: {"description": "no bearer token (§7.4) — a raster is never served without one"},
        404: {"model": errors.ErrorResponse,
              "description": "`page_not_found`, or `page_not_current` for a superseded page"},
        503: {"model": errors.ErrorResponse,
              "description": "`document_not_stored` / `document_hash_mismatch` — the page is "
                             "indexed and its bytes are not here (§11.3)"},
    })
    async def page_image(page_id: str, request: Request, dpi: str = str(DPI_INDEX),
                         region: str = "") -> Any:
        """The page raster, rendered on demand — ported from `impl`'s `/api/v1/page-image/{id}`.

        What is ported is the idea of a URL a browser `<img>` can point at. What is not is where
        the bytes came from: `impl` read a PNG that step 03 had written for every page at both
        dpis, so the path went stale, `read()` returned 503 for every page (register **A5**), and
        an instance could only answer about files its own replica happened to have. Here nothing is
        on disk — `page_id` resolves to the source document (U029) and the raster is made now and
        cached in memory (§4.2, §15 Factor VI).

        **`dpi` is read as a string on purpose.** Declared as `int`, a `?dpi=abc` would be
        FastAPI's own 422 with a validation array in it; §7.3 says every bound on this parameter is
        a typed 400 whose ``error`` an agent can switch on, and *"that is not a dpi"* belongs in
        the same family as *"that dpi is not allowed"*.

        **ETag, and a 304.** The digest is the raster's own SHA-256, which is already computed for
        `extract_key` (§6.3), so a console scrolling a hundred thumbnails re-validates instead of
        moving a hundred images again. It is honest under a re-ingest: different bytes render to a
        different digest, so the browser's copy stops matching by construction.

        No audit line. §7.4 audits `read` and `fetch` — the two *tools* — and widening that set is
        widening an append-only schema, so this logs its own event with the same facts instead
        (page, dpi, bytes, whether it rendered) and the audit stream keeps its shape.
        """
        identity = auth_module.identity_of(request.scope)
        if identity is None:                    # unreachable behind `BearerAuth`; fails closed
            refusal = auth_module.Unauthorized()
            return JSONResponse(status_code=refusal.http_status, content=refusal.to_payload(),
                                headers=refusal.headers)

        correlation = dict(request.scope.get(SCOPE_CORRELATION) or {})
        with vsir_logging.correlate(tool="page_image",
                                    **{k: v for k, v in correlation.items() if v}):
            try:
                resolved_dpi = int(str(dpi).strip())
            except ValueError:
                outcome = _failure_response(ToolError(
                    "dpi_not_allowed",
                    f"dpi is one of {list(ALLOWED_DPI)}, got {dpi!r}",
                    allowed=list(ALLOWED_DPI), requested=str(dpi)), tool="page_image")
                return Response(content=outcome.body(), status_code=outcome.status,
                                media_type="application/json")

            before = raster_cache.cache_info()
            try:
                crop = raster_cache.region_of_query(region)
                raster = await run_in_threadpool(_rendered, page_id, resolved_dpi, crop)
            except BaseException as failure:  # noqa: BLE001 — every path out is typed (§11.3)
                if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                    raise
                outcome = _failure_response(failure, tool="page_image")
                return Response(content=outcome.body(), status_code=outcome.status,
                                media_type="application/json")

            etag = f'"{raster.sha256}"'
            rendered = raster_cache.renders(before, raster_cache.cache_info())
            _log.info("page_image", tool="page_image", user_id=identity.user_id,
                      page_id=raster_cache.page_id_of_path(page_id), dpi=resolved_dpi,
                      region=list(crop) if crop else None, width=raster.width,
                      height=raster.height, bytes=len(raster.png), rendered=bool(rendered),
                      cache=raster_cache.cache_info())
            headers = {
                "etag": etag,
                # Revalidate every time: a `page_id` does not name the bytes it was rendered from
                # (a re-ingest of the same revision keeps the id, §6.7), so a max-age would let a
                # browser show a superseded page. The ETag makes revalidation cheap.
                "cache-control": "private, max-age=0, must-revalidate",
            }
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers=headers)
            return Response(content=raster.png, media_type=raster_cache.PNG_MEDIA_TYPE,
                            headers=headers)

    # ── ingestion over HTTP: the transport for `vsir ingest` (§6.1, §15 Factor XII) ───────────────

    @app.post("/documents", status_code=202, tags=["ingest"], responses=errors.responses(
        400, 401, 403, 413, 415, 500, 503,
        **{"400": "an empty body, an unknown step, or an unknown VLM backend",
           "500": "the ingest process could not be started",
           "503": "the document store is missing or not writable (§4.2, U029)"}))
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


    # ── the corpus: what is in the index (§5.1–5.3, §5.7) ────────────────────────────────────────
    # `POST /documents` above put documents in; these three are how anything finds out what went
    # in. See `serve/manage.py` for why they are queries over the collections ingestion already
    # writes and never a second source of truth — and for why the units are documents, revisions
    # and **pages** rather than chunks, which this system deliberately does not have.
    #
    # All three are read-only. Retirement is §6.7's, and it runs *inside* a publish where the run
    # record is its evidence; a bare "retire this revision" endpoint would be the one call on this
    # surface that silently changes what every future search returns, so it is not here.

    def _manage_failure(failure: BaseException, *, route: str) -> JSONResponse:
        """A management refusal, in the same typed shape as a tool's (§11.3).

        Reusing :func:`_failure_response` rather than writing a second mapping: `document_not_found`
        and `qdrant_unavailable` mean exactly what they mean on the tool surface, and a caller must
        not have to learn this service's refusals twice.
        """
        outcome = _failure_response(failure, tool=route)
        return JSONResponse(status_code=outcome.status, content=outcome.payload)

    @app.get("/documents", response_model=manage.DocumentList, tags=["corpus"],
             summary="the corpus — every document in the index",
             responses=errors.responses(400, 401, 500, 503))
    async def list_documents(
        limit: int = Query(manage.DEFAULT_PAGE_SIZE, description=(
            f"Documents to describe, 1…{manage.MAX_DOCUMENTS}. Each row costs two exact facets "
            f"and a scroll, so this is a real bound and not a page size.")),
    ) -> Any:
        """Every document held, with its revisions and its §5.7 searchable ratio.

        The ratio is on this row deliberately: it is the number that decides whether `lookup` can
        answer for this document at all, and an operator reviewing an ingest is exactly the person
        who needs to see a 0.00 before an agent reports 'not found' from it (§7.1).
        """
        try:
            return await run_in_threadpool(
                manage.documents, app.state.search, cfg.pages_collection, limit=limit)
        except Exception as failure:  # noqa: BLE001 — mapped to §11.3's typed refusals
            return _manage_failure(failure, route="list_documents")

    @app.get("/documents/{doc_id}", response_model=manage.DocumentRow, tags=["corpus"],
             summary="one document, and every revision of it",
             responses=errors.responses(401, 404, 500, 503))
    async def get_document(doc_id: str) -> Any:
        """One document. A `404 document_not_found` when the id is not in the index.

        The superseded revisions are listed and not hidden: §6.7 **keeps** them (F9), their pages
        are still reachable by `page_id`, and a surface that showed only the current one would
        make the history of a document look like it never had one.
        """
        try:
            return await run_in_threadpool(
                manage.document, app.state.search, cfg.pages_collection, doc_id)
        except Exception as failure:  # noqa: BLE001
            return _manage_failure(failure, route="get_document")

    @app.get("/documents/{doc_id}/pages", response_model=manage.PageList, tags=["corpus"],
             summary="one revision's page inventory",
             responses=errors.responses(400, 401, 404, 500, 503))
    async def list_document_pages(
        doc_id: str,
        revision: str | None = Query(None, description=(
            "Which revision to list. Omitted resolves to the published one and echoes back which "
            "that was — the fact that changes under a caller when somebody publishes a new one.")),
        limit: int = Query(manage.DEFAULT_PAGE_SIZE,
                           description=f"Rows, 1…{manage.MAX_PAGE_SIZE}."),
        offset: int = Query(0, description=(
            "Start at this `page_no`. A page number rather than an opaque cursor, so the order is "
            "total and paging cannot re-shuffle or skip a row (§6.8's argument).")),
    ) -> Any:
        """The pages of one revision, in `page_no` order, each with its `page_id` and raster URL.

        This is the list a document browser renders and the list an operator checks an ingest
        against: `has_text=false` on a run of pages is what a `searchable_ratio` below 1.00 is
        *made of*, and seeing which pages they are is the difference between "this scan is poor"
        and "pages 40–52 failed to render".
        """
        try:
            return await run_in_threadpool(
                manage.pages, app.state.search, cfg.pages_collection, doc_id,
                revision=revision, limit=limit, offset=offset)
        except Exception as failure:  # noqa: BLE001
            return _manage_failure(failure, route="list_document_pages")
    @app.get("/runs", response_model=manage.RunList, tags=["runs"],
             summary="the run history — what has been ingested, and how it ended",
             responses=errors.responses(400, 401, 500, 503))
    async def list_runs(
        limit: int = Query(manage.DEFAULT_PAGE_SIZE,
                           description=f"Rows, 1…{manage.MAX_PAGE_SIZE}. Newest first."),
        doc_id: str = Query("", description="Only this document's runs."),
        state: str = Query("", description=(
            "Only runs in this state: `queued`, `running`, `stopped`, `gated`, `published`, "
            "`failed`. `gated` is the interesting one — a run that finished and whose gates "
            "refused to publish it.")),
    ) -> Any:
        """The history `GET /runs/{run_id}` could not give you, because it needs an id you have.

        A summary per run rather than the §6.9 record: which gate refused is the whole content of
        a `gated` run, so `failed_gates` is named here and everything else is one `GET` away.
        """
        try:
            return await run_in_threadpool(
                manage.runs, app.state.control, cfg.runs_collection,
                limit=limit, doc_id=doc_id, state=state)
        except Exception as failure:  # noqa: BLE001 — mapped to §11.3's typed refusals
            return _manage_failure(failure, route="list_runs")

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

        # The eight named tool routes publish their body by `$ref` rather than as a typed
        # parameter (see `_serve_tool` for why), and a `$ref` FastAPI never saw is a dangling
        # pointer: Swagger renders an empty form and a code generator fails outright. So the
        # request models are put in `components.schemas` from the **table**, under the same
        # `ref_template` the routes point at. Generated together in one call rather than one model
        # at a time, so a type shared by two bodies — `PART`, the annotated field aliases — lands
        # once and both bodies reference the same definition.
        requested = [(spec.request, "validation") for spec in app.state.tools.values()]
        if requested:
            _, generated = models_json_schema(
                requested, ref_template="#/components/schemas/{model}")
            schema.setdefault("components", {}).setdefault("schemas", {}).update(
                generated.get("$defs", {}))

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
