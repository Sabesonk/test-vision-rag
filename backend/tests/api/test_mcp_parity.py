"""L2 — the MCP surface, over stdio **and** SSE (Spec §7.5, §4.2, D7, R6).

§7.5 asks for one thing and the plan sharpens it into two checks anybody can run:

* **byte-identical.** The `tools/call` result for a request is byte-for-byte the HTTP response
  body for the same request, on both transports. Not *equivalent JSON* — the same bytes, because
  a re-serialisation is where a second contract starts.
* **no second implementation.** An import-graph assertion, plus object identity: the callable the
  MCP server reaches through the tool table **is** the callable the HTTP route reaches, and
  `vsir/mcp/server.py` imports nothing it would need to answer a query itself.

Behind both is R6: *a careless MCP client ignores the safeguards.* It cannot, because the
safeguards are not on this surface. `is_current=True`, the `INDEXED` gate, the typed absences and
the per-caller budget are enforced under :func:`vsir.serve.app.dispatch`, below the transport,
where a client has nothing to decline (D7).

The stdio suite spawns **real processes** — `python -m vsir mcp --stdio` — because the acceptance
criterion about shared state is only meaningful across process boundaries, and because a spawned
process is what an MCP client actually does.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from vsir.eval import synthetic
from vsir.mcp import server as mcp_server
from vsir.serve import app as app_module
from vsir.serve.app import create_app
from vsir.serve.tools import lookup as lookup_module
from vsir.serve.tools import verify as verify_module

from conftest import TEST_TOKEN, serve_env

EXPECTED = synthetic.load().expected
LOOKUP_LABEL = EXPECTED["compact_labels"][0]["label"]
LOOKUP_PAGE = EXPECTED["compact_labels"][0]["page_id"]

MCP_SOURCE = Path(mcp_server.__file__)
#: How long a spawned stdio server may take to answer before the suite calls it hung. Generous:
#: it runs the §4.3 boot self-check against a real Qdrant before it reads its first frame.
CALL_TIMEOUT_S = 60


# ── driving the two transports ──────────────────────────────────────────────────────────────────

def stdio_env(**overrides: str) -> dict[str, str]:
    """The child's environment: this process's, with the test stack's configuration on top.

    Merged rather than replaced, because a bare ``env`` would drop ``PATH`` and the virtualenv
    the child needs to import `vsir` at all.
    """
    return {**os.environ, **serve_env(**overrides)}


async def _stdio_calls(calls: list[tuple[str, dict]], **env: str) -> list[Any]:
    """Spawn one `vsir mcp --stdio` process, run ``calls`` through it, and return the results.

    One process per invocation of this helper, so a test that wants two processes asks twice.
    """
    params = StdioServerParameters(command=sys.executable, args=["-m", "vsir", "mcp", "--stdio"],
                                   env=stdio_env(**env))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return [await session.call_tool(name, arguments) for name, arguments in calls]


def stdio_calls(calls: list[tuple[str, dict]], **env: str) -> list[Any]:
    return asyncio.run(asyncio.wait_for(_stdio_calls(calls, **env), CALL_TIMEOUT_S))


async def _stdio_tools() -> Any:
    params = StdioServerParameters(command=sys.executable, args=["-m", "vsir", "mcp", "--stdio"],
                                   env=stdio_env())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialised = await session.initialize()
            return initialised, await session.list_tools()


@contextlib.contextmanager
def sse_app(**overrides: str) -> Iterator[str]:
    """Run the **serving app** on an ephemeral port and yield its base URL.

    Deliberately `create_app` and not a second application: §15 Factor VII pins the SSE transport
    to the port the HTTP surface binds, so the thing under test has to be the app that also
    serves `POST /tools/{name}` — one process, one socket, both protocols.
    """
    import uvicorn

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(create_app(serve_env(**overrides)), host="127.0.0.1",
                                           port=port, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "the SSE app did not start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)


async def _sse_call(base_url: str, name: str, arguments: dict, token: str = TEST_TOKEN) -> Any:
    async with sse_client(f"{base_url}{mcp_server.SSE_PATH}",
                          headers={"Authorization": f"Bearer {token}"}) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


def sse_call(base_url: str, name: str, arguments: dict, token: str = TEST_TOKEN) -> Any:
    return asyncio.run(asyncio.wait_for(_sse_call(base_url, name, arguments, token),
                                        CALL_TIMEOUT_S))


def http_body(name: str, arguments: dict) -> bytes:
    """The same call over `POST /tools/{name}`, as raw bytes. The thing MCP must match."""
    with TestClient(create_app(serve_env())) as client:
        response = client.post(f"/tools/{name}", json=arguments,
                               headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        return response.content


def text_of(result: Any) -> str:
    assert len(result.content) == 1, "one text block per call — the envelope, whole"
    return result.content[0].text


# ── the declaration (§7.5) ──────────────────────────────────────────────────────────────────────

def test_the_mcp_server_declares_the_releases_tools_and_no_others(served_collection):
    """`tools/list` is the release's table — a tool that is not built is not advertised."""
    initialised, listing = asyncio.run(asyncio.wait_for(_stdio_tools(), CALL_TIMEOUT_S))

    assert initialised.server_info.name == mcp_server.SERVER_NAME == \
        "vision-segmentation-retriever"
    assert initialised.instructions == mcp_server.INSTRUCTIONS
    assert sorted(tool.name for tool in listing.tools) == sorted(app_module.tool_table())
    assert sorted(tool.name for tool in listing.tools) == ["lookup", "verify"]


def test_the_published_input_schema_is_the_http_request_model(served_collection):
    """One declaration, two surfaces (§7.5).

    A hand-written JSON Schema beside the Pydantic model would be a second thing to update, and
    the failure is silent: an MCP client validating against a stale schema sends what it was told
    to and is refused by a server that never advertised the change.
    """
    _initialised, listing = asyncio.run(asyncio.wait_for(_stdio_tools(), CALL_TIMEOUT_S))
    published = {tool.name: tool.input_schema for tool in listing.tools}

    for name, spec in app_module.tool_table().items():
        assert published[name] == spec.request.model_json_schema()
    assert published["lookup"]["additionalProperties"] is False  # `extra="forbid"`, advertised
    assert set(published["verify"]["required"]) == {"claims", "page_ids"}


def test_every_declared_tool_carries_a_description_an_agent_can_choose_on():
    """§8.2 — the agent picks a move from these words, so an empty one is a silent failure."""
    for tool in mcp_server.tool_definitions(app_module.tool_table()):
        assert tool.description and len(tool.description) > 120, tool.name


# ── byte identity, on both transports (U015's acceptance criterion) ─────────────────────────────

@pytest.mark.parametrize("name,arguments", [
    ("lookup", {"label": LOOKUP_LABEL}),
    ("lookup", {"label": EXPECTED["suggest"]["label"]}),
    ("verify", {"claims": ["K73"], "page_ids": ["SYN-M1@1.0#p006"]}),
], ids=["lookup-ok", "lookup-not_found", "verify-absent"])
def test_stdio_result_is_byte_identical_to_the_http_body(served_collection, name, arguments):
    """The criterion, as bytes. Both sides call one serialiser on one dict (§7.5)."""
    expected = http_body(name, arguments)
    [result] = stdio_calls([(name, arguments)])

    assert text_of(result).encode("utf-8") == expected
    assert result.is_error is False


def test_sse_result_is_byte_identical_to_the_http_body(served_collection):
    """The same, over the transport that binds the serving port (§15 Factor VII)."""
    expected = http_body("lookup", {"label": LOOKUP_LABEL})

    with sse_app() as base_url:
        result = sse_call(base_url, "lookup", {"label": LOOKUP_LABEL})

    assert text_of(result).encode("utf-8") == expected


def test_the_structured_content_is_the_same_envelope(served_collection):
    """`structuredContent` is the parsed text and not a second rendering of it."""
    [result] = stdio_calls([("lookup", {"label": LOOKUP_LABEL})])

    assert result.structured_content == json.loads(text_of(result))
    assert result.structured_content["hits"][0]["page_id"] == LOOKUP_PAGE


# ── the safeguards are below the transport, not on it (D7, R6) ──────────────────────────────────

def test_a_typed_refusal_reaches_mcp_under_the_same_code(served_collection):
    """An `INDEXED` violation is refused server-side on both surfaces, with one code (I6, F10).

    This is R6's answer in one assertion: a client that ignored the published schema and passed
    an unindexed filter key does not get a slower answer or a narrower one — it gets the same
    typed `400` an HTTP caller gets, because the gate is under the dispatcher.
    """
    arguments = {"label": LOOKUP_LABEL, "scope": {"content.text": "x"}}

    [result] = stdio_calls([("lookup", arguments)])

    assert result.is_error is True
    body = json.loads(text_of(result))
    assert body["error"] == "filter_unknown_key"
    assert body["keys"] == ["content.text"]
    assert text_of(result).encode("utf-8") == http_body("lookup", arguments)


def test_a_not_found_is_not_an_mcp_error(served_collection):
    """A typed absence is a **successful** call, on this transport too (§7.1, I5).

    Marking it `isError` would tell an MCP client the tool broke, and a client that retried a
    broken tool would be retrying a correct answer.
    """
    [result] = stdio_calls([("lookup", {"label": EXPECTED["suggest"]["label"]})])

    assert result.is_error is False
    body = json.loads(text_of(result))
    assert body["status"] == "not_found"
    assert body["next"]["suggest"] == ["skim_pages"]


def test_a_page_not_found_is_an_error_on_mcp_too(served_collection):
    """§7.1 — a missing `page_id` is a refusal, never a verdict, on either transport."""
    [result] = stdio_calls([("verify", {"claims": ["K158"],
                                        "page_ids": ["SYN-M1@1.0#p999"]})])

    assert result.is_error is True
    assert json.loads(text_of(result))["error"] == "page_not_found"


def test_an_unknown_tool_over_mcp_is_the_typed_404(served_collection):
    """A tool this release does not serve is *absent*, and the body lists what is served."""
    [result] = stdio_calls([("read", {"page_ids": ["SYN-M1@1.0#p001"], "question": "?"})])

    assert result.is_error is True
    body = json.loads(text_of(result))
    assert body["error"] == "tool_not_found"
    assert body["available"] == ["lookup", "verify"]


def test_is_current_is_injected_on_the_mcp_surface_too(served_collection):
    """I7 — a client that asks for unpublished pages is overridden, and told it was overridden."""
    [result] = stdio_calls([("lookup", {"label": EXPECTED["superseded"][0]["label"],
                                        "scope": {"is_current": False}})])

    body = json.loads(text_of(result))
    assert body["effective_scope"]["is_current"] is True
    assert body["hits"] == []


# ── stateless: nothing is shared, across calls or across processes ──────────────────────────────

def test_two_calls_with_different_scope_echo_different_effective_scope(served_collection):
    """One process, two calls: the second is not narrowed by the first (§7.5, C11, F8)."""
    wide, narrow = stdio_calls([
        ("lookup", {"label": LOOKUP_LABEL}),
        ("lookup", {"label": LOOKUP_LABEL, "scope": {"doc_id": "NO-SUCH-DOC"}}),
    ])

    assert json.loads(text_of(wide))["effective_scope"] == {"is_current": True}
    assert json.loads(text_of(narrow))["effective_scope"] == {"doc_id": "NO-SUCH-DOC",
                                                              "is_current": True}
    assert json.loads(text_of(wide))["status"] == "ok"
    assert json.loads(text_of(narrow))["status"] == "out_of_scope"


def test_two_processes_share_no_state(served_collection):
    """U015's acceptance criterion — *"asserted across two processes"*.

    Two servers, one scoped and one not, and then the **same** unscoped call again in a third:
    if either process had remembered anything, the third answer would differ from the first.
    """
    [scoped] = stdio_calls([("lookup", {"label": LOOKUP_LABEL,
                                        "scope": {"doc_id": "NO-SUCH-DOC"}})])
    [unscoped] = stdio_calls([("lookup", {"label": LOOKUP_LABEL})])
    [again] = stdio_calls([("lookup", {"label": LOOKUP_LABEL})])

    assert json.loads(text_of(scoped))["effective_scope"]["doc_id"] == "NO-SUCH-DOC"
    assert "doc_id" not in json.loads(text_of(unscoped))["effective_scope"]
    assert text_of(again) == text_of(unscoped)


# ── SSE is on the serving port, behind the serving auth ─────────────────────────────────────────

def test_the_sse_paths_are_on_the_serving_app(served):
    """§15 Factor VII — no second server and no second port: `/sse` is a route of this app."""
    paths = {getattr(route, "path", "") for route in served.app.router.routes}

    assert mcp_server.SSE_PATH in paths
    assert mcp_server.MESSAGES_PATH.rstrip("/") in {path.rstrip("/") for path in paths}
    assert served.app.state.mcp_paths == (mcp_server.SSE_PATH, mcp_server.MESSAGES_PATH)


@pytest.mark.parametrize("path", ["/sse", "/messages/"])
def test_the_mcp_paths_need_a_bearer_token(served, path):
    """Default deny: the three probes are the whole unauthenticated surface (§7.4, §15.1).

    Both MCP paths were protected the moment they were mounted, because protection is middleware
    and not something a route opts into.
    """
    assert served.get(path).status_code == 401
    assert served.post(path).status_code == 401


def test_an_sse_connection_with_a_wrong_token_is_refused():
    """A syntactically fine credential that is not configured buys nothing (§7.4)."""
    with sse_app() as base_url:
        with pytest.raises(Exception):
            sse_call(base_url, "lookup", {"label": LOOKUP_LABEL}, token="not-a-configured-token")


# ── no second implementation (U015's import-graph criterion) ────────────────────────────────────

def _imports(source: Path) -> set[str]:
    """Every module name this file imports, dotted and flattened."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_the_mcp_server_reaches_the_tools_only_through_the_shared_dispatcher():
    """The import graph, asserted: this file cannot answer a query, so it cannot answer one wrong.

    It imports `vsir.serve.app` — the table and the dispatcher the HTTP route uses — and it
    imports **no** tool module, no `core.exact`, and no Qdrant query model. There is therefore
    nowhere in it for a second phrase filter, a second cap check or a second status rule to live.
    """
    imported = _imports(MCP_SOURCE)

    assert "vsir.serve.app" in imported
    assert {"vsir.serve.app.dispatch", "vsir.serve.app.ToolRuntime"} <= imported

    forbidden = [name for name in imported
                 if name.startswith(("vsir.serve.tools", "vsir.core.exact", "vsir.core.verify",
                                     "qdrant_client"))]
    assert not forbidden, f"the MCP server must not reach a tool except through the table: {forbidden}"


def test_the_mcp_and_http_surfaces_call_the_same_objects():
    """Identity, not resemblance: the callables are the same objects on both paths (§7.5)."""
    table = app_module.tool_table()

    assert table["lookup"].call is app_module._call_lookup
    assert table["verify"].call is app_module._call_verify
    # ... and those adapters call the tool modules themselves, with nothing in between.
    assert app_module.lookup_tool is lookup_module.lookup
    assert app_module.verify_tool is verify_module.verify


def test_the_mcp_runtime_is_the_serving_apps_own_table(served):
    """One table per release, shared by both surfaces — not a copy that could drift.

    Registering a tool on the app registers it for MCP in the same instant, which is what makes
    "no second code path" a property of the object graph rather than of a convention.
    """
    assert served.app.state.runtime.tools is served.app.state.tools

    definitions = mcp_server.tool_definitions(served.app.state.runtime.tools)
    assert [tool.name for tool in definitions] == sorted(served.app.state.tools)


def test_the_mcp_server_defines_no_tool_of_its_own():
    """No function in this module builds a filter, counts, or scrolls — it has no store to ask."""
    tree = ast.parse(MCP_SOURCE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}

    assert not called & {"count", "scroll", "retrieve", "query_points", "search", "facet"}
