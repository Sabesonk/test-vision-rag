---
type: interface
title: The vsir Command Line
description: The operator surface — boot check, ingest, the run control plane, migrations, publishing, retirement, the eight tool one-shots, the runner, demos and evaluations — with exit-code semantics and which commands can spend money.
tags: [cli, operations, commands, exit-codes, tooling]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-372d006f03a1aeeeb3cb0656
    resource: repo://backend/tests/api/test_one_shot_parity.py
  - id: openwiki-source-04b6ef6d0488cd1cd6abc2fe
    resource: repo://backend/vsir/cli.py
  - id: openwiki-source-6e916bb8d762873e87835dc9
    resource: repo://backend/vsir/serve/auth.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# The vsir Command Line

`vsir` is the supported operational surface: an action that cannot be expressed as a subcommand
is not a supported operation. Every command returns an exit code and logs JSON events to stdout,
and a refusal is a non-zero exit with a named reason rather than a warning followed by a partial
success.

`main()` parses, configures logging **from the raw environment before any check runs** — the boot
self-check reports a missing or malformed log level and needs a working logger to report with —
installs the signal handler, and runs exactly one command.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success — **including a typed absence** |
| `1` | a refusal: a bound, a missing document, an unavailable backend, a failed assertion |
| `130` | interrupted |

A typed absence exiting 0 is load-bearing: a lookup that searched and found nothing said so
correctly, which is a successful call, and it is what lets a demonstration chain commands with
`&&` the way a reviewer expects. Only a refusal — a bound, a not-found, an outage — is non-zero.

## Commands by job

### Check and serve

- **`doctor`** — the boot self-check. Prints the release id, resolved model ids and index
  fingerprint; refuses a floating model alias or a missing variable. `--create-collection` builds
  the pages collection from the index schema first and then asserts the live schema back against
  it, as a one-off admin process rather than live surgery.
- **`serve`** — binds the configured port and serves the HTTP surface. The boot self-check runs
  first, so a refusal exits non-zero with **no socket bound**.
- **`mcp`** — the MCP surface. `--sse` is the serving app (the SSE transport binds the serving
  port); `--stdio` is a one-off process speaking JSON-RPC on stdin and stdout.

### Ingest and the control plane

- **`ingest`** — the pipeline. `--until` stops after any named step, `--vlm` and `--fixture`
  override the backend and replay directory for one run, `--record` freezes the run's responses,
  and `--resume` continues an existing run. The PDF argument is optional with `--resume`, which
  resolves the file from the document store by the run's own document and revision — which is what
  makes an uploaded run resumable after the instance that accepted it is gone.
- **`runs show`** — the run record, read from the control plane.
- **`gates rerun`** — re-evaluate the publish gates against the index. Free, and changes nothing.
- **`publish`** — release a document a gate is holding. The reason is recorded in the run and
  every page is flagged as published with an override.
- **`retire`** — withdraw a document from service: every page is set not-current and **kept**.
  Deletion is not offered, because a retired page is what a superseded-revision result reads and
  what an audit of an answer already given is checked against.
- **`migrate`** — in-place repairs to a collection this release refuses at boot. Only what can be
  re-derived from stored payload is offered.
- **`documents`** — the document store: what it holds, and resolving a page id to bytes.

### The eight tool one-shots

`skim documents|sections|pages`, `lookup`, `resolve`, `verify`, `fetch`, `read` — each one call
through **the release's own dispatcher**, so a one-shot runs the same code path the HTTP route
runs. Their identity in the audit line and the budget ledger is a local process identity rather
than a bearer-token digest.

A test asserts this rather than trusting it: the one-shot's output is compared **byte for byte**
against the HTTP response body for the same request, in-process so it is visible which callable
answered. A property that holds only on reading is a property that stops holding the first time
somebody adds a convenience to the CLI.

### The runner

- **`ask`** — narrow, look once, draft, and answer only what the answer gate cleared.
- **`ask --explain`** — the free half: the descent, the tri-state triage and the route. Spends
  nothing on any path.

### Demos and evaluations

- **`demo exact`** — the exact surface: variants, the one filter, the tokenizer and the caps.
- **`demo narrow`** — a query narrowed to page rows, the image reference dereferenced, `fetch`
  with and without pixels, a crop, every bound as a typed refusal, and the raster cache proved
  evictable.
- **`eval acceptance | abstention | corpus`** — the three evaluations. See
  [Evaluation Corpora and Quality Gates](../evaluation/corpora-fixtures-and-gates.md).

## What can spend money

Only two commands can make a billed model call, and only under the live backend:

- **`ingest`** — the document-facts call, one call per window, and one embedding call per page.
  `VSIR_ALLOW_PAID` does **not** gate this: a CLI ingest is already a deliberate act, and the
  variable guards the upload boundary instead.
- **`ask`** and **`read`** — the one tool that spends, bounded by the per-question and per-caller
  ceilings.

Everything else is free on every path, in both modes. Under the replay backend even the two above
cost nothing, because responses are served from a fixture by cache key and a missing key is a
typed refusal rather than a live call.

## `--json` moves the event stream

With `--json`, **nothing is printed on stdout but the envelope**. The rule is the same one the
stdio MCP transport follows and for the same reason: under `serve`, stdout *is* the event stream,
and a flag that declares stdout the machine surface makes a perfectly good boot event a parse
error at whatever is reading it.

The stream moves to stderr **before the boot check runs**, so a boot refusal is still reported in
full. The two outputs are separated, never one of them silenced. Without `--json` the output is a
human rendering and stdout stays the event stream, unchanged.

Because `--json` prints the dispatcher's own response bytes rather than a re-rendering, piping a
one-shot into a JSON processor is a reading of the wire contract — and a re-serialisation anywhere
in the CLI leg would show up as a diff in the parity test.

## Related pages

- [Ingestion Pipeline](../ingestion/pipeline.md) — what `ingest` drives
- [Run Lifecycle, Gates and Publication](../ingestion/run-control-plane-and-publishing.md) — `runs`, `gates`, `publish`, `retire`
- [The Eight Tools and the Dispatcher](../retrieval/tool-surface.md) — the shared implementation behind the one-shots
- [Evaluation Corpora and Quality Gates](../evaluation/corpora-fixtures-and-gates.md) — the `eval` commands
- [VSIR Quickstart](../quickstart.md) — getting the CLI onto a PATH
