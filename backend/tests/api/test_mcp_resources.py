"""L2 — the corpus as MCP resources (§7.5, §5.1–5.3).

`GET /documents` had no MCP counterpart, and the obvious fix was the wrong one: a ninth tool.
§7.5 fixes the tool surface at *the same eight tools* as HTTP, and that is a statement about what
an agent chooses between — the eight are **moves**, and "list the corpus" is not a move, it is
context. MCP's own answer is a resource, so that is what this is.

Two things are asserted, and the second is the one that matters:

* the tool table is **still eight** — adding a browsable corpus did not add a tool;
* reading `vsir://corpus` returns the **same bytes** as `GET /documents`, because both go through
  `serve/manage.py` and :func:`~vsir.serve.envelope.wire`. The parity suite next door asserts that
  property for tools; a resource that computed its own counts would be a second source of truth
  for what the index contains, which is exactly what a management surface must not be.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from vsir.mcp import server as mcp_server
from vsir.serve import app as app_module

from conftest import serve_env
from test_mcp_parity import CALL_TIMEOUT_S, http_body, sse_app, stdio_env


async def _stdio_resources(uris: list[str], **env: str) -> tuple[Any, Any, list[Any]]:
    """One `vsir mcp --stdio` process: list the resources, the templates, then read ``uris``."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "vsir", "mcp", "--stdio"],
                                   env=stdio_env(**env))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_resources()
            templates = await session.list_resource_templates()
            contents = [await session.read_resource(uri) for uri in uris]
            return listed, templates, contents


def stdio_resources(uris: list[str], **env: str) -> tuple[Any, Any, list[Any]]:
    return asyncio.run(asyncio.wait_for(_stdio_resources(uris, **env), CALL_TIMEOUT_S))


def text_of(result: Any) -> str:
    assert len(result.contents) == 1, "one JSON document per resource"
    return result.contents[0].text


def flatten(failure: BaseException) -> str:
    """Every message in a possibly-nested ``ExceptionGroup``, joined.

    The MCP client raises a refusal inside two layers of `TaskGroup`, so ``str(group)`` is
    *"unhandled errors in a TaskGroup"* and says nothing about the refusal. The code and the
    message are in the leaf, and the leaf is what these tests are about.
    """
    if isinstance(failure, BaseExceptionGroup):
        return " ".join(flatten(inner) for inner in failure.exceptions)
    return str(failure)


def test_the_corpus_is_a_resource_and_not_a_ninth_tool(served_collection):
    """The tool surface stays at the eight of §7.2 — this is the constraint the design respects."""
    listed, templates, _ = stdio_resources([])

    assert [resource.name for resource in listed.resources] == ["corpus"]
    assert str(listed.resources[0].uri).rstrip("/") == mcp_server.CORPUS_URI
    assert len(app_module.tool_table()) == 8


def test_the_per_document_uris_are_templates_a_client_fills_in(served_collection):
    """Templates rather than a resource per document: `resources/list` stays O(1).

    A thousand-binder corpus must not put a thousand entries in a client's picker, and it must
    not cost a facet and a scroll per row on every list.
    """
    _, templates, _ = stdio_resources([])

    declared = {template.uri_template for template in templates.resource_templates}
    assert declared == {"vsir://documents/{doc_id}", "vsir://documents/{doc_id}/pages"}


def test_reading_the_corpus_is_byte_identical_to_the_http_listing(served_collection):
    """One implementation, two surfaces — the property §7.5 asserts for tools, kept for resources.

    Byte-identity and not "the same document": a resource that re-serialised, rounded a ratio or
    ordered revisions differently would pass an equality check on parsed JSON and still be a
    second answer to *"what does this index contain"*.
    """
    _, _, contents = stdio_resources([mcp_server.CORPUS_URI])

    assert text_of(contents[0]).encode("utf-8") == _http_get("/documents")


def test_reading_one_document_is_byte_identical_to_its_http_route(served_collection):
    _, _, contents = stdio_resources(["vsir://documents/SYN-M1"])

    assert text_of(contents[0]).encode("utf-8") == _http_get("/documents/SYN-M1")


def test_reading_a_documents_pages_is_byte_identical_to_its_http_route(served_collection):
    _, _, contents = stdio_resources(["vsir://documents/SYN-M1/pages"])

    assert text_of(contents[0]).encode("utf-8") == _http_get("/documents/SYN-M1/pages")


def test_an_unknown_resource_is_a_refusal_and_never_an_empty_document(served_collection):
    """A document that was never ingested and one whose pages all failed are different facts."""
    with pytest.raises(Exception) as refused:
        stdio_resources(["vsir://documents/NOPE"])

    reported = flatten(refused.value)
    assert "NOPE" in reported
    assert "GET /documents lists the ids there are" in reported


def test_an_unknown_scheme_names_what_the_server_does_serve(served_collection):
    """A refusal that lets the next attempt be correct rather than a retry of the same mistake."""
    with pytest.raises(Exception) as refused:
        stdio_resources(["vsir://nonsense"])

    reported = flatten(refused.value)
    assert "nonsense" in reported
    assert "vsir://corpus" in reported and "vsir://documents/{doc_id}" in reported


def test_the_resources_need_a_bearer_token_over_sse(served_collection):
    """SSE is the network boundary, so the corpus is not readable without a credential (§7.4)."""
    with sse_app() as base_url:
        import httpx

        refused = httpx.get(f"{base_url}{mcp_server.SSE_PATH}",
                            headers={"Authorization": "Bearer wrong"}, timeout=10)
        assert refused.status_code == 401


def test_the_resource_handlers_reach_the_store_only_through_manage(served_collection):
    """The import-graph rule of the parity suite, extended to resources.

    `mcp/server.py` gained the ability to answer *"what is in the index"*, and the rule that keeps
    that honest is the one that already keeps `tools/call` honest: it holds no query logic of its
    own. It calls `serve/manage.py` — the very functions the HTTP routes call — so it has no
    filter, no count and no scroll anywhere in it.
    """
    import ast

    tree = ast.parse(mcp_server.__file__ and open(mcp_server.__file__).read())
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}

    assert not called & {"count", "scroll", "retrieve", "query_points", "search", "facet"}
    assert {"documents", "document", "pages"} <= called, \
        "the resources must resolve through serve/manage.py and not a query of their own"


def _http_get(path: str) -> bytes:
    """The same question over HTTP, as raw bytes. The thing a resource must match."""
    from fastapi.testclient import TestClient

    from conftest import TEST_TOKEN
    from vsir.serve.app import create_app

    with TestClient(create_app(serve_env())) as client:
        return client.get(path, headers={"Authorization": f"Bearer {TEST_TOKEN}"}).content
