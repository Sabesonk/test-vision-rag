---
type: quickstart
title: VSIR Quickstart
description: What VSIR is, how to set up the pinned Python environment and configuration, how to bring up the free local stack, and which wiki page answers which kind of question.
tags: [quickstart, setup, onboarding, routing, local-development]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-823297e013120d7d9437dfe7
    resource: repo://scripts/stack.sh
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# VSIR Quickstart

VSIR answers an engineering question about a machine binder with a **page-cited answer or an
honest refusal**, never a plausible wrong one. A vision model extracts page facts, pages are
indexed into Qdrant as one dense plus two sparse surfaces, and eight tools serve them over HTTP,
MCP and a CLI.

## Set up

Python **3.11** is the floor, and the `vsir` console script is the supported operational surface.
Install the project into a virtual environment and it lands on the PATH.

Two packaging details matter and are easy to get wrong by hand: the extraction prompts and the
console page are **package data**, shipped inside the wheel. Both are read at runtime from a path
resolved relative to the module, and both are release artefacts rather than documentation — the
prompt text is hashed into the cache keys, so the file that shipped must be the file the receipts
refer to. Left out of the wheel, a live ingest fails partway and the console route refuses, while
a source tree works perfectly and every test stays green because replay never loads a prompt.

Bare `pytest` runs the fast layer only: the test paths are pinned to the unit directory, and the
API and paid scripts name their directories explicitly, so no Docker-bound or paid test can be
picked up by the fast layer.

## Configure

Configuration is the environment and only the environment — nothing reads the example file for
you. Copy it, fill it in and load it into the shell, then run the boot self-check: it prints the
release id, the resolved model ids and the index fingerprint, and refuses by name on a floating
model alias or a missing variable.

See [Configuration and Boot Self-Check](architecture/configuration-and-boot.md).

## Bring up the local stack

`scripts/stack.sh up` builds the image (the same Dockerfile as production and the test stack),
starts the store, creates the collection, starts the API and seeds a 42-page corpus. **It spends
nothing**: the stack runs the replay backend, so frozen responses are served by cache key and a
missing key is a typed refusal rather than a model call.

`up --no-seed` leaves the index empty. `up --live` is the deliberate opposite: it exports the live
backend, the paid switch and the *released* prompt version, refuses outright when no credential is
loaded, prints what an ingest will now cost — and **seeds nothing**, so no money is spent by
accident.

`status` prints the probes, the tools, the documents and the token the running container actually
has; `seed`, `logs`, `vsir …`, `down` and `down --wipe` do what their names say.

See [Local Stack, Docker and Deployment](operations/local-stack-and-deployment.md).

## Where to look

| If you want to… | Read |
|---|---|
| understand the shape of the whole system | [System Architecture Overview](architecture/overview.md) |
| know what must be set before anything runs | [Configuration and Boot Self-Check](architecture/configuration-and-boot.md) |
| run without spending money, or understand what does spend | [Replay and Live Execution Modes](architecture/execution-modes.md) |
| know what is stored, where, and what happens when it is missing | [External State and Storage](architecture/state-and-storage.md) |
| add or change a field on a page | [Page Model and Index Schema](concepts/page-model-and-index-schema.md) |
| understand how a code is matched and confirmed | [Exact Match and Claim Verification](concepts/exact-match-and-verification.md) |
| know what a caller gets when nothing was found | [Typed Results and Refusals](concepts/typed-results-and-refusals.md) |
| follow a PDF from upload to a queryable page | [Ingestion Pipeline](ingestion/pipeline.md) |
| change how pages are grouped or extracted | [Windowing and VLM Extraction](ingestion/vlm-extraction-and-windows.md) |
| change how a page is embedded or ranked at index time | [Embedding and the Three Retrieval Surfaces](ingestion/embedding-and-sparse-surfaces.md) |
| resume a killed run, or understand why a document will not publish | [Run Lifecycle, Gates and Publication](ingestion/run-control-plane-and-publishing.md) |
| add a tool or understand what each one does | [The Eight Tools and the Dispatcher](retrieval/tool-surface.md) |
| tune or explain a ranking | [Search, Fusion and Ranking](retrieval/search-and-fusion.md) |
| understand how an answer is composed and gated | [The Agentic Runner and Answer Gate](retrieval/agentic-runner.md) |
| call the service over HTTP | [HTTP API Surface](interfaces/http-api.md) |
| attach it to an MCP client | [MCP Server Surface](interfaces/mcp-server.md) |
| operate it from a terminal | [The vsir Command Line](interfaces/cli.md) |
| work on the console | [Operator Console Frontend](interfaces/operator-console.md) |
| run the tests, or understand a conformance failure | [Test Layers, Conformance and CI](testing/test-layers-and-ci.md) |
| measure quality, or regenerate a fixture | [Evaluation Corpora and Quality Gates](evaluation/corpora-fixtures-and-gates.md) |

## Two facts worth knowing before reading anything else

**The addressable unit is the page.** There is no chunk: a window is a page range created by the
model's attention limit and deleted again by stitching.

**One variable decides whether a release costs money.** It selects the extraction backend and the
embedding backend together, so a run replaying extraction cannot quietly spend on embeddings.
