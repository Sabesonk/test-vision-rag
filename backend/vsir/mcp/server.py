"""``vision-segmentation-retriever`` — the MCP surface (Spec §7.5, §4.2, D7). Net new.

`impl` has no MCP server, so there is nothing to port and nothing to inherit. What there *is* to
inherit is the mistake this module is shaped to avoid: two surfaces onto the same capability, each
with its own validation, drifting until one of them enforces a bound the other does not. That is
risk **R6** — *"a careless MCP client ignores the safeguards"* — and its answer is D7: **every
rule that matters is server-side.** A prompt-level rule on the raw MCP surface is advisory; the
caps of §7.3, the typed absences of §7.1, `is_current=True` (I7) and the per-caller quota are not,
because they are enforced below the transport where no client can decline them.

So this module holds **no tool logic at all**. It resolves a name in the release's own tool table,
hands the arguments to :func:`vsir.serve.app.dispatch` — the very function `POST /tools/{name}`
calls, with the very same :class:`~vsir.serve.app.ToolRuntime` — and turns the outcome into a
`CallToolResult`. An import-graph test asserts the absence: nothing here imports Qdrant's query
models, `core.exact`, or a tool module directly, because the only way this file can reach a tool
is through the table.

**Byte-identical, and structurally so.** §7.5's *"calling the identical implementations"* is
checked by U015 as: the `tools/call` result for a request is byte-for-byte the HTTP response body
for the same request. That holds because both call :func:`~vsir.serve.envelope.wire` on the same
dict — not because two serialisers were configured to agree.

**Two transports, one of which is not a second server.**

* **SSE** is mounted on the serving app and binds ``$VSIR_PORT`` — §15 Factor VII says so
  outright: *"the MCP SSE transport binds the same port."* One process, one socket, two protocols
  over it, and the same :class:`~vsir.serve.auth.BearerAuth` middleware in front of both. A
  bearer token is required, because this is the network boundary.
* **stdio** is a one-off process (Factor XII), spawned by its client over a pipe. Its identity is
  :func:`~vsir.serve.auth.local_identity` — see that function for why a credential read from the
  same environment the server reads would be ceremony rather than authentication.

**On sticky sessions.** §15.2 bans them, and an SSE session is a connection: the client holds a
stream open and POSTs to it by id, so its messages must reach the replica that holds the stream.
That is *transport* affinity, and it is not what the ban is about — the ban is about **state**
affinity, the server-held retrieval session C11 strikes, a process that remembers what you
searched. This server remembers nothing: `scope` and `exclude` are parameters, `effective_scope`
is echoed back, and a client whose connection is cut and reconnects to a different replica gets
identical answers, because the second replica knows exactly as much as the first did — nothing.
The one thing an MCP session holds is the JSON-RPC channel itself. (Residual, stated: an SSE
deployment behind a load balancer needs connection affinity for that channel. `stdio` has no such
requirement, and neither does `POST /tools/{name}`.)
"""
from __future__ import annotations

import sys

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from starlette.responses import Response
from starlette.routing import Mount, Route
from typing import Any, Mapping

from vsir import __version__
from vsir import logging as vsir_logging
from vsir.serve import auth as auth_module
from vsir.serve.app import (SCOPE_CORRELATION, ToolRuntime, ToolSpec, dispatch, runtime_from_env)
from vsir.serve.auth import Identity

#: §7.5's server name. It is the identity an MCP client shows a user when it lists what is
#: attached, so it names the *service* rather than the process or the release.
SERVER_NAME = "vision-segmentation-retriever"

#: Where the SSE transport lives on the serving app. Both paths are behind `BearerAuth`, because
#: neither is in :data:`~vsir.serve.auth.PUBLIC_PATHS` — the three probes are the whole
#: unauthenticated surface and a route added here does not change that.
SSE_PATH = "/sse"
MESSAGES_PATH = "/messages/"

#: What an MCP client is told this server is for. It is the first thing an agent reads, so it
#: leads with the guarantee (§1.1) and the one refusal a caller most needs to expect.
INSTRUCTIONS = (
    "Engineering-document retrieval over segmented, indexed page images. A code returned by "
    "these tools is a code printed on the page: the exact surface is a phrase match over the "
    "extracted text layer, which no model output can write to, so a code a model invented is "
    "not merely unlikely to be found — it is unfindable.\n\n"
    "Nothing matched is never an empty success. It is one of four typed absences — `not_found`, "
    "`not_searchable`, `out_of_scope`, `found_only_in_superseded` — and each implies a different "
    "next move; `error` means retry or report, and never abstain. A `not_found` that a different "
    "move could still answer carries `next.suggest`.\n\n"
    "Every call is independent: this service holds no session. Pass `scope` on each call and "
    "read `effective_scope` back to see what was actually searched."
)

_log = vsir_logging.get_logger(__name__)


def tool_definitions(tools: Mapping[str, ToolSpec]) -> list[types.Tool]:
    """The release's tool table → MCP tool declarations (§7.5).

    The input schema is the tool's **own Pydantic model**, published as JSON Schema. Not a
    hand-written schema beside it: a second declaration of the same parameters is a second thing
    to update, and the failure mode is silent — an MCP client validating against a stale schema
    sends what it was told to send and is refused by a server that never advertised the change.
    One declaration, two surfaces, and ``extra="forbid"`` on the model means a misspelt parameter
    is a typed `400` on both of them.
    """
    return [
        types.Tool(name=spec.name,
                   description=spec.description,
                   input_schema=spec.request.model_json_schema())
        for spec in sorted(tools.values(), key=lambda spec: spec.name)
    ]


async def _call_tool(runtime: ToolRuntime, identity: Identity, correlation: Mapping[str, str],
                     params: types.CallToolRequestParams) -> types.CallToolResult:
    """One ``tools/call`` → :func:`~vsir.serve.app.dispatch` → a `CallToolResult`.

    In a worker thread, because the Qdrant client is sync and blocking this event loop would stall
    every other message on the same connection.

    ``isError`` is the transport's word for *"the call did not run"* and it is set from the
    dispatcher's HTTP status, so the two surfaces classify the same event the same way. A typed
    refusal — `filter_unknown_key`, `page_not_found`, `budget_exhausted`, `qdrant_unavailable` —
    is an error on both. A `not_found` is **not**: the call ran perfectly and the answer is that
    the code is not printed in the searched scope, which is the single most important thing this
    service says (§7.1, I5).
    """
    outcome = await anyio.to_thread.run_sync(
        lambda: dispatch(runtime, params.name, params.arguments or {},
                         identity=identity, correlation=correlation))
    return types.CallToolResult(
        # The bytes of the HTTP body, verbatim (§7.5). One serialiser, so this is a fact about
        # the code rather than a convention two transports agreed on.
        content=[types.TextContent(type="text", text=outcome.body().decode("utf-8"))],
        # The same dict, for a client that would rather not re-parse the text. No `outputSchema`
        # is declared: §7.1's envelope is generic over five hit models, and a JSON Schema of it
        # here would be a second declaration of the response contract with nothing keeping it
        # honest.
        structured_content=dict(outcome.payload),
        is_error=outcome.refused,
    )


def build_server(runtime: ToolRuntime, identity: Identity,
                 correlation: Mapping[str, str] | None = None) -> Server:
    """An MCP server bound to one caller. Built per stdio process and per SSE connection.

    Per connection rather than once per app, and that is the whole trick behind carrying an
    identity onto a transport that has no place to put one: the identity is established when the
    connection is authenticated and captured in this closure, so `tools/call` never has to fish it
    back out of a session table. It also means there is no session table.
    """
    bound = dict(correlation or {})

    async def on_list_tools(_context: Any,
                            _params: Any = None) -> types.ListToolsResult:
        tools = tool_definitions(runtime.tools)
        _log.debug("mcp_list_tools", tools=[tool.name for tool in tools],
                   user_id=identity.user_id)
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(_context: Any,
                           params: types.CallToolRequestParams) -> types.CallToolResult:
        return await _call_tool(runtime, identity, bound, params)

    return Server(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


# ── SSE: mounted on the serving app, on the serving port (§15 Factor VII) ───────────────────────

def mount(app: Any) -> tuple[str, ...]:
    """Add ``GET /sse`` and ``POST /messages/`` to the serving app. Returns the paths it added.

    Mounted on the FastAPI app rather than run as a second server, because Factor VII says the
    SSE transport binds the same port — one socket, one readiness probe, one set of resource
    limits. It is added *inside* :func:`~vsir.serve.app.create_app`, after `BearerAuth`, so both
    paths are default-deny like every other non-probe path: the middleware is what protects them,
    not a decision taken here.
    """
    transport = SseServerTransport(MESSAGES_PATH)

    async def handle_sse(request: Any) -> Response:
        """Open the stream, then run a server bound to *this* connection's caller.

        The identity is read once, here, from what the middleware authenticated — so two clients
        with two tokens are two callers with two budgets on one process, and neither can name
        itself (§7.4).
        """
        identity = auth_module.identity_of(request.scope)
        if identity is None:  # unreachable behind `BearerAuth`; failing closed costs one branch
            refusal = auth_module.Unauthorized()
            return Response(content=refusal.detail, status_code=refusal.http_status,
                            headers=refusal.headers)
        correlation = dict(request.scope.get(SCOPE_CORRELATION) or {})
        runtime: ToolRuntime = request.app.state.runtime
        _log.info("mcp_sse_open", user_id=identity.user_id, transport="sse",
                  tools=sorted(runtime.tools))
        try:
            async with transport.connect_sse(request.scope, request.receive,
                                             request._send) as (read, write):
                server = build_server(runtime, identity, correlation)
                await server.run(read, write, server.create_initialization_options())
        finally:
            _log.info("mcp_sse_close", user_id=identity.user_id, transport="sse")
        # The SSE response has already been sent by `connect_sse`; Starlette needs a return value.
        return Response(status_code=200)

    app.router.routes.append(Route(SSE_PATH, endpoint=handle_sse, methods=["GET"]))
    app.router.routes.append(Mount(MESSAGES_PATH, app=transport.handle_post_message))
    return (SSE_PATH, MESSAGES_PATH)


# ── stdio: a one-off process (§15 Factor XII) ───────────────────────────────────────────────────

#: The process type in the audit line and the budget ledger for a stdio server.
STDIO_PROCESS = "mcp-stdio"


async def serve_stdio(runtime: ToolRuntime, identity: Identity) -> None:
    """Speak MCP over stdin/stdout until the client closes the pipe."""
    server = build_server(runtime, identity)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def run_stdio(env: Mapping[str, str]) -> None:
    """The ``vsir mcp --stdio`` process: boot check, one connection, then exit.

    **Nothing is printed on stdout but protocol.** Under `vsir serve` stdout *is* the event stream
    (§15 Factor XI); here it is the JSON-RPC channel, and one non-frame on it — a banner, or a
    perfectly good ``boot_check_ok`` — is a parse error at the client. So the stream moves to
    stderr **first**, before the boot check runs, and the operator still gets every event: the
    two outputs are separated, not one of them silenced.
    """
    # Before anything logs, including the §4.3 checks: a boot refusal on stdout would be the
    # first thing a client sees and it cannot read it.
    vsir_logging.configure(release_id=(env.get("VSIR_RELEASE_ID") or "").strip() or "unknown",
                           level=(env.get("VSIR_LOG_LEVEL") or "INFO").strip(),
                           stream=sys.stderr)
    runtime, client = runtime_from_env(dict(env))
    identity = auth_module.local_identity(STDIO_PROCESS)
    _log.info("mcp_stdio_open", user_id=identity.user_id, transport="stdio",
              tools=sorted(runtime.tools), collection=runtime.config.pages_collection)
    try:
        anyio.run(serve_stdio, runtime, identity)
    finally:
        _log.info("mcp_stdio_close", user_id=identity.user_id, transport="stdio")
        client.close()
