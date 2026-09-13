---
type: architecture
title: System Architecture Overview
description: End-to-end shape of VSIR — an eleven-step VLM ingest pipeline turns PDF pages into Qdrant points carrying one dense and two sparse vectors, and eight tools serve them through a single dispatcher shared by HTTP, MCP and the CLI.
tags: [architecture, overview, pipeline, retrieval, qdrant, boundaries, invariants]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-04b6ef6d0488cd1cd6abc2fe
    resource: repo://backend/vsir/cli.py
  - id: openwiki-source-7431613dae8f0b1de9c39510
    resource: repo://backend/vsir/core/indexed.py
  - id: openwiki-source-6f5751f3f39cb35acb313461
    resource: repo://backend/vsir/ingest/index.py
  - id: openwiki-source-2205ae93add6598628c21601
    resource: repo://backend/vsir/serve/app.py
  - id: openwiki-source-a39e8287e8855241fd53d7b0
    resource: repo://backend/vsir/serve/manage.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# System Architecture Overview

VSIR answers engineering questions about scanned and vendor-supplied binders with a
page-cited answer or a typed refusal. The system has three halves that meet at one store:
an **ingest** pipeline that turns a PDF into page records, a **Qdrant** index that holds
one point per page, and a **serving** surface of eight tools plus a runner that composes an
answer only from behind a verification gate.

```
PDF ──► ingest (11 steps) ──► Qdrant: {collection}_{dim}  ──► dispatch ──► HTTP  /tools/*, /ask
         manifest…publish         one point per page          (one table)  MCP   stdio + SSE
                                  dense + lexical + captions               CLI   vsir <tool>
                                ▲
                       vsir_runs (control plane)
```

## The two facts that cut across everything

**The addressable unit is the page.** There is no chunk anywhere in the system. A window is
a page range that exists only because a model has an attention limit, and stitching deletes
it again; it never becomes a retrieval boundary. Documents, revisions, pages and runs are
the units, and a `page_id` is what `fetch`, `read` and `verify` take.

**`VSIR_VLM` selects the extraction backend and the embedding backend together.** One switch
decides whether a release makes live model calls at all, so a run replaying extraction from a
fixture cannot quietly spend on embeddings. See
[Replay and Live Execution Modes](execution-modes.md).

## Package boundaries

| Package | Owns |
|---|---|
| `vsir.config` | the frozen `Config` and the pins that are code rather than configuration |
| `vsir.core` | identifiers, the page record, the `INDEXED` schema, the exact-match surface, verification, health signals, the status enum |
| `vsir.vlm` | the model boundary: two backends, four cache keys, the fixture and control-plane stores |
| `vsir.ingest` | the eleven pipeline steps, the run control plane, the publish gates and the document store |
| `vsir.serve` | the HTTP app, the tool table, the dispatcher, envelopes, caps, auth, budget and audit |
| `vsir.mcp` | the MCP transport over the same dispatcher |
| `vsir.runner` | the question loop: descend, triage, route, draft, gate |
| `vsir.eval` | corpora and the evaluation commands measured against them |
| `frontend/` | the operator console, same-origin by proxy |

`vsir.core` is the layer everything else depends on and which depends on nothing above it:
everything provable without a model call lives there.

## The write path

`vsir ingest` drives eleven named steps in order — `manifest`, `probe`, `render`, `facts`,
`window`, `extract`, `derive`, `stitch`, `embed`, `index`, `publish`. Steps 01–08 are pure
functions of the PDF and the fixture or model responses, which is what lets derivation and
stitching be asserted without a store. The last three are store-backed: step 09 reads the
embedding cache off the index, step 10 writes to it, step 11 flips visibility, so with no
reachable Qdrant all three refuse rather than re-billing vectors the index already holds.

Step 10 writes one Qdrant point per page carrying three surfaces: the fused dense vector,
the `lexical` sparse surface built from extracted text, and the `captions` sparse surface
built from the model's own summaries and topics. Every point is written `is_current=False`;
step 11 is the only thing that flips it, so a run that has not passed its gates cannot
answer.

Two guards sit at the write itself rather than only at boot. The collection fingerprint is
checked as the first thing an upsert does, so a mismatch writes zero points — boot runs once
per process, and a long-lived ingest worker can be handed a configuration that never went
through one. And a small set of payload keys naming a file on disk is refused outright,
because rasters are re-rendered on demand and no payload may point at one.

Step 10's module is also the embedding cache: it reads the vector and `embed_key` already
stored on a page's point, so re-ingesting an unchanged page reuses the vector instead of
buying it again. The store *is* the cache, which adds no state anywhere.

## The index schema

One module-level dict, `INDEXED`, does three jobs: it creates the payload indexes, it gates
every caller filter, and it is asserted against the live collection at boot. One dict rather
than two, because a filter on a field that was never indexed does not fail in Qdrant — it
runs an unindexed scan and skips the filterable-HNSW path, producing a smaller answer that
looks complete. Filtering on anything absent from the dict is therefore a typed `400`, never
a slow path.

Two of the sixteen keys are text surfaces, `text` and `vlm_codes`, and they are reachable
only through the exact-match tools rather than as caller filters. Both are indexed with
phrase matching on, which is what makes precise identifier lookup possible: `"SF 1.1A"`
becomes an ordered phrase rather than a bag of common tokens.

## The read path

Every surface goes through one function. `dispatch()` takes a runtime, a tool name and a
plain dict of arguments and knows nothing about HTTP: it looks the name up in the release's
tool table, validates the arguments against that tool's own Pydantic model with
`extra="forbid"`, and calls `run_tool()`. A name absent from the table is a typed `404`
listing what *is* served — a tool not in this release is absent, not empty. A misspelt
parameter is a `400` rather than a quietly different query, and that validation happens
server-side precisely because an MCP client that ignored the published input schema cannot be
trusted to have read it.

`run_tool()` is where the cross-cutting policy lives, in a fixed order: the cheap precheck
that can be settled from the request alone, then the budget charge for the one tool that
spends, then the call, then `reads_remaining` stamped onto the envelope by the dispatcher
rather than by each tool, then the audit line for the audited tools. Because it is one
function, no tool can arrive with its own idea of auth, of the budget, or of which failures
are which.

The HTTP app publishes each tool on its own path *and* keeps the generic one beneath it, but
both are thin shells over the same `dispatch`. The MCP server calls the same function with the
same runtime, and the CLI one-shots do too, which is why the three surfaces cannot drift.

## Operational shape

The CLI is the supported operational surface: an action that cannot be expressed as a `vsir`
subcommand is not a supported operation. Every command returns an exit code and logs JSON
events to stdout, and a refusal is a non-zero exit with a named reason rather than a warning
followed by a partial success. The same image runs the web process, ingest work and one-off
admin commands, differing only in environment.

## Related pages

- [Ingestion Pipeline](../ingestion/pipeline.md) — the eleven steps in detail
- [The Eight Tools and the Dispatcher](../retrieval/tool-surface.md) — the tool table and what each move does
- [External State and Storage](state-and-storage.md) — the two collections, the document store and what is deliberately not persisted
- [Page Model and Index Schema](../concepts/page-model-and-index-schema.md) — identifiers, the record and `INDEXED`
- [Replay and Live Execution Modes](execution-modes.md) — the one switch and the cache keys
- [Configuration and Boot Self-Check](configuration-and-boot.md) — what must be true before any of this runs
