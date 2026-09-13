---
type: interface
title: MCP Server Surface
description: The Model Context Protocol surface — the same eight tools over stdio and SSE with no tool logic of its own, the corpus published as a resource plus templates rather than a ninth tool, and per-transport identity and authentication.
tags: [mcp, transport, sse, stdio, resources, parity, agents]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-d2e29ba91f19c31cfc945483
    resource: repo://backend/tests/api/test_mcp_parity.py
  - id: openwiki-source-46c66ca8e712868c5a2391bc
    resource: repo://backend/vsir/mcp/server.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# MCP Server Surface

The MCP server holds **no tool logic at all**. It resolves a name in the release's own tool table,
hands the arguments to the same dispatch function the HTTP tool routes call with the same runtime,
and turns the outcome into a protocol result.

That shape is the answer to a specific risk: a careless MCP client ignoring the safeguards. It
cannot, because the safeguards are not on this surface. Current-revision scoping, the filter gate,
the caps, the typed absences and the per-caller budget are all enforced beneath the dispatcher,
below the transport, where a client has nothing to decline. A prompt-level rule on a raw MCP
surface is advisory; these are not.

## Byte-identical, and structurally so

The `tools/call` result for a request is **byte for byte** the HTTP response body for the same
request, on both transports. That holds because both call the one serialiser on the same dict —
not because two serialisers were configured to agree. The test checks bytes rather than
equivalent JSON, because a re-serialisation is where a second contract starts.

"No second implementation" is asserted two ways: by object identity — the callable the MCP server
reaches through the tool table *is* the callable the HTTP route reaches — and by an **import-graph
assertion** that this module imports nothing it would need to answer a query itself: no store
query models, no exact-match module, no tool module directly. The only way the file can reach a
tool is through the table.

The stdio suite spawns **real processes**, because the property about shared state is only
meaningful across process boundaries and because a spawned process is what an MCP client actually
does.

## Tool declarations come from the tool's own model

Each declaration's input schema is the tool's own Pydantic model published as JSON Schema, never a
hand-written schema beside it. A second declaration of the same parameters is a second thing to
update and its failure is silent: a client validating against a stale schema sends what it was
told to send and is refused by a server that never advertised the change. One declaration, two
surfaces — and because the models forbid extra fields, a misspelt parameter is a typed refusal on
both.

## The corpus is a resource, not a ninth tool

The tool surface is fixed at the same eight tools as HTTP, and that is not an accident of wording:
the eight are an agent's **moves**, and an agent choosing among nine where one of them is "list
the corpus" is choosing between a search and a filing cabinet. MCP already has the right concept —
a resource is context a client reads and attaches, not an action the model decides to take.

So the document listing becomes one concrete resource, `vsir://corpus`, and the per-document URIs
are declared as **templates** a client fills from the ids it found there. Enumerating a resource
per document would make listing cost a facet and a scroll per row on every call and would flood a
client's picker with a thousand entries for a thousand binders; the concrete listing stays O(1).

Because a resource is read whole — there is no limit parameter on a URI — the document bound lives
in the code, and a corpus larger than it is browsed over HTTP where the caller can page.

Resources resolve through the **same management functions the HTTP routes call**, so what a
resource reports and what the corresponding route reports cannot differ: they are one function
called twice. They are read-only for the HTTP surface's reason and for one more that is specific
here — a resource is fetched by a client without the model choosing to, so a mutating resource
would be a change to the corpus that nothing in the conversation asked for.

## Two transports, and only one of them is a server

**SSE** is mounted on the serving app and binds the serving port — one process, one socket, two
protocols over it, one readiness probe and one set of resource limits. It is added *inside* the
app factory after the auth middleware, so both of its paths are default-deny like every other
non-probe path: the middleware protects them rather than a decision taken in the MCP module. A
bearer token is required, because this is the network boundary.

The caller identity is read **once, when the stream opens**, from what the middleware
authenticated, so two clients with two tokens are two callers with two budgets on one process and
neither can name itself.

**stdio** is a one-off process spawned by its own client over a pipe. It needs no credential: it
runs from the release's own image with the release's own configuration, and the operator running
it could equally run a publish. Its identity in the audit line and the budget ledger is a stable
local process name rather than a token digest.

## On sticky sessions

Server-held sessions are banned, and an SSE session *is* a connection: the client holds a stream
open and posts to it by id, so its messages must reach the replica holding the stream. That is
**transport** affinity, and it is not what the ban is about — the ban is about **state** affinity,
a process that remembers what you searched.

This server remembers nothing: scope and exclusions are parameters, the effective scope is echoed
back, and a client whose connection is cut and reconnects to a different replica gets identical
answers because the second replica knows exactly as much as the first did, which is nothing. The
residual is stated rather than hidden: an SSE deployment behind a load balancer needs connection
affinity for the JSON-RPC channel itself. Neither stdio nor the HTTP tool routes have that
requirement.

## Related pages

- [The Eight Tools and the Dispatcher](../retrieval/tool-surface.md) — the table both transports read
- [HTTP API Surface](http-api.md) — the other transport over the same dispatcher
- [Typed Results and Refusals](../concepts/typed-results-and-refusals.md) — the serialiser that makes byte-identity possible
- [The vsir Command Line](cli.md) — the third surface over the same dispatcher
