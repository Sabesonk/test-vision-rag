---
type: interface
title: HTTP API Surface
description: Every route the FastAPI app serves and the default-deny bearer middleware in front of them — probes, per-tool routes, the ask loop, the corpus and run surfaces, streamed exports, metrics, page rasters and the upload transport — plus the shared budget ledger and the ten-field audit line.
tags: [http, api, routes, authentication, budget, audit, probes, openapi]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-2205ae93add6598628c21601
    resource: repo://backend/vsir/serve/app.py
  - id: openwiki-source-0952bb843e5dc2d82b8d2c8e
    resource: repo://backend/vsir/serve/audit.py
  - id: openwiki-source-6e916bb8d762873e87835dc9
    resource: repo://backend/vsir/serve/auth.py
  - id: openwiki-source-852169b548961ba08154a339
    resource: repo://backend/vsir/serve/budget.py
  - id: openwiki-source-1353375d38e7b12c3339cc29
    resource: repo://backend/vsir/serve/ingest.py
  - id: openwiki-source-a39e8287e8855241fd53d7b0
    resource: repo://backend/vsir/serve/manage.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# HTTP API Surface

The app is built by a factory that runs the boot self-check **before anything is bound**, so a
half-configured process never serves. Everything below is either a free documentation/probe path
or behind a bearer token.

## Authentication is middleware, and it is default-deny

The previous implementation exposed eleven endpoints and checked a credential on none of them —
including the vision call that spends money and the delete that removed a document. Anyone who
could reach the port could bill the account or delete the corpus.

Three decisions make the replacement hold:

**Default deny by path, in middleware — not a dependency per route.** A per-route dependency is
opt-in: the route added next is unauthenticated until somebody remembers, and nothing fails when
they do not. Here the only unauthenticated paths are an explicit set, and everything else —
including a route that does not exist yet — requires a token. Forgetting to protect a new route is
impossible, because protection is not something a route opts into.

The free set is deliberately **three sets rather than one**, because each is free for a different
reason and may only grow for its own:

- **probes** (`/health`, `/ready`, `/metrics`) — an orchestrator holds no token, and a liveness
  probe that could fail on a credential rotation would turn a secret rotation into a restart loop;
- **documentation** (`/`, `/openapi.json`, `/docs`, `/redoc`, and the OAuth redirect) — a browser
  cannot attach an `Authorization` header to a plain navigation, so an authenticated docs page is
  a 401 and nothing else. This does not open the API: the document declares a bearer requirement
  on every operation, so *Authorize* is where the reader's own token goes and every *Try it out*
  is an ordinary authenticated request. The root is here because it returns the *shape* of the
  interface and no corpus data — a root answering 404 was the one response that taught an
  integrator nothing;
- **the console** — one static page of markup, which then asks the operator for a credential.

Anything that returns corpus data, a run, a raster or prose belongs in none of them.

**Identity comes from the token and nothing else.** There is no user header, no query parameter
and no body field: a caller who could name itself could name somebody else, and the audit log
exists precisely to say who spent the money. Client identity headers are read *only* to report on
the event stream that they were ignored.

**The credential is never compared, held as a secret or logged.** A presented token is reduced to
a domain-separated SHA-256 prefix and that digest is looked up among the configured tokens'
digests — so the comparison is between two hashes rather than two secrets, and the identity that
reaches the audit line is by construction not the credential. The cost is that an operator sees
`caller-9f2a…` rather than a name; the mapping from digest to human lives with whoever issued the
token.

## Liveness and readiness answer different questions

`GET /health` says *this process is up*. It touches no backing service and must **not** fail
because the store is unreachable: if it did, a store outage would become a fleet-wide restart loop
that outlasts the outage.

`GET /ready` says *this instance can serve correct answers right now*: the boot checks pass, the
store is reachable, and the pinned index schema is present. It is red on a **failure or on a check
that could not conclude**, and it carries a named reason — somebody else's outage and this
deployment awaiting its first ingest are different facts. The checks are re-run per probe rather
than cached from start-up, so a schema that drifts under a running process turns that instance red
instead of leaving it answering, and they run in a worker thread because blocking the event loop
on a probe would be its own outage.

## The tools: nine routes, one transport, one dispatcher

Each of the eight tools gets its own path, and the generic `POST /tools/{tool_name}` stays
registered beneath them.

The named routes exist for the **description**, not the dispatch. One generic operation published
an untyped body for eight tools whose parameters have nothing in common, so the docs showed a
single "tool name plus JSON" form and a generated client got one untyped call. Named routes
publish each tool's own request schema and its own envelope.

This does not create a second implementation: every named route is a two-line closure over the
same transport, and they are generated **from the tool table in a loop** rather than hand-written,
so a tool cannot get a route without being in the table or be in the table without getting a
route. Registration order decides matching, so the eight literal paths win and the generic one
catches every other name — which is the behaviour it should keep, because an unknown name is a
typed 404 listing what *is* served.

The named routes deliberately do **not** validate their own bodies with typed parameters: a typed
parameter would answer a misspelt field with a framework-level 422 and a JSON pointer, while the
contract is a code an agent can switch on. The schema is published separately and the dispatcher
stays the only validator on either transport.

## `POST /ask`

The runner's loop over HTTP, and **the only surface that may return prose**. It descends the
narrowing rungs (or asks the exact surface directly when the question names a printed code),
triages candidates for free, spends one read on the pages that survive, drafts from that read's
own words, and runs the answer gate over every code in the draft. A caller that looked at the
pages itself can pass its own `draft` and have the identical gate run on it, spending nothing.

Its body is validated in the route rather than by a typed parameter for the same reason the tool
routes are, and the loop runs in a worker thread because it makes a series of blocking calls.

## Corpus and run surfaces

`GET /documents`, `GET /documents/{doc_id}` and `GET /documents/{doc_id}/pages` answer what the
index *contains*. They are **queries over the collections ingestion already writes** — page rows
from the page index, revision and run facts from the control plane — computing nothing ingestion
did not record and storing nothing of their own, so they cannot drift from what a search sees and
every replica answers identically.

Counts are **exact** throughout, at some latency cost: a management surface is where somebody
decides whether an ingest was correct, and an estimated page count short by two is
indistinguishable from an ingest that dropped two pages.

Nothing on this surface mutates. Retirement runs *inside* a publish, where it is one clause of a
transition with the run record as its evidence; a bare "retire this revision" endpoint would be
the one call here that silently changes what every future search returns.

`GET /runs` is the history and `GET /runs/{run_id}` one whole record.

## The streamed exports

`GET /runs/{run_id}/export/{artefact}.jsonl` serves the two artefacts **generated from the index**.
Nothing is written to the instance's filesystem and there is nothing on it to read: a generator
produces NDJSON as the store answers, so the response holds one chunk of pages at a time. The
first line is pulled *before* the response starts, so an unknown artefact is a typed 404 rather
than a 200 whose body turns out to be a traceback.

## `GET /metrics`

Two gauges, computed from the control plane on each scrape rather than counted in the process. An
in-memory counter would report a different number per replica and reset on every deploy, which
measures the deployment rather than the corpus.

## `POST /documents` is a transport, not a pipeline

The route does not implement ingestion — it spools the bytes, validates what it can refuse
cheaply, and runs the same subcommand an operator would, from the same image and release. Two code
paths for one operation is how an upload ingest silently did less than the whole job. The caller
gets `202` and a run id immediately; progress is the run route, which reads the control plane
rather than this process, so a poll works from any replica.

Two properties an operator is giving up are stated rather than hidden. It makes the web process
briefly stateful, because the PDF library needs a file — the spool is removed when the child exits
however it exits, and the durable copy is the document store's. And it moves the spend decision to
whoever can reach the port, which is why the route refuses outright when the release is configured
for a live model without the paid switch. There are no token scopes, so that switch is
per-release rather than per-caller: a caller who can spend can spend everything the release
allows.

## `GET /pages/{page_id}/image`

The browser-renderable half of `fetch`, with the same dpi tiers and the same typed refusals.
Rasters are rendered on demand and never persisted. The page id contains a `#`, so the URL form is
percent-encoded in exactly one place and read back in exactly one place.

## The budget and the audit line

**A quota in process memory is not a quota.** The web process scales horizontally, so a counter in
a dict is N counters that each reset on deploy — three replicas turn a fifty-read ceiling into 150
and a rolling restart into unbounded. The ledger is therefore a point in the control plane, the
only durable thing replicas share.

The ledger is **advisory**, exactly like the ingest lease and for the same reason: with no
compare-and-swap, two concurrent reads from one caller can both observe the same remaining count.
The over-spend is bounded by one caller's own concurrency, it is a cost bug rather than a
correctness bug, and the alternative is a fourth backing service to make a fifty-call quota exact.

The window is a **UTC day**. A lifetime quota exhausts and never recovers, which is a
decommissioning rather than a quota, and anything shorter needs a scheduler to explain it. The
period key is part of the point id, so a new day is a new point — no sweeper, no cron, no expiry
to get wrong. Exhaustion is `429`, never a truncated result: a read silently trimmed to what fits
answers about pages the caller did not ask for and reports success.

Exactly one audit line is emitted per `read` and per `fetch`, with exactly **ten** fields: caller,
run, session, tool, page ids, dpi, input and output tokens, cache hit, latency.

- **Cost goes in that line, never in a response body.** The agent gets one integer, the remaining
  read count. The operator's question ("who spent this, on which pages, and did the cache save
  it?") and the agent's ("how many reads have I left?") are different questions and get different
  channels.
- **Only the two consuming tools are audited.** A line per free call would bury the records that
  matter; free tools still log at debug level, so the stream is not silent about them.
- **The schema is exactly ten fields and an eleventh is refused** in the constructor rather than in
  a review checklist, because an audit stream carrying page text is a copy of the corpus in a log
  aggregator with a log aggregator's retention.
- **The fields are nested under one key**, partly so "exactly ten fields" is assertable on one
  object, and partly because the redactor blanks credential-shaped *names* — a top-level
  `input_tokens` would arrive on the stream as `***`.

## Related pages

- [The Eight Tools and the Dispatcher](../retrieval/tool-surface.md) — what the tool routes call
- [Typed Results and Refusals](../concepts/typed-results-and-refusals.md) — the response and refusal shapes
- [MCP Server Surface](mcp-server.md) — the same tools on another transport
- [Run Lifecycle, Gates and Publication](../ingestion/run-control-plane-and-publishing.md) — what the run routes report
- [Operator Console Frontend](operator-console.md) — the browser client for these routes
