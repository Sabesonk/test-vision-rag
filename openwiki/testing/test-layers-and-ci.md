---
type: testing
title: Test Layers, Conformance and CI
description: The five test layers and the scripts that run them, the conformance greps that enforce the architectural rules no compiler can, the Playwright end-to-end stack, and what CI runs on every commit with no credential anywhere.
tags: [testing, ci, conformance, e2e, playwright, layers, cost-control]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-164e2da859b5277df81c7d94
    resource: repo://.github/workflows/ci.yml
  - id: openwiki-source-85164da3eb010b967e464903
    resource: repo://backend/tests/unit/test_conformance.py
  - id: openwiki-source-208256e77e6a428af3e5132f
    resource: repo://e2e/playwright.config.ts
  - id: openwiki-source-fa1a0bbc32b5e8ec42ac2415
    resource: repo://scripts/test-api.sh
  - id: openwiki-source-7976bb66eba16f8360a331d4
    resource: repo://scripts/test-e2e.sh
  - id: openwiki-source-b355387f28fe86540c318324
    resource: repo://scripts/test-paid.sh
  - id: openwiki-source-848c35eaadf77a0b624f4106
    resource: repo://scripts/test-unit.sh
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Test Layers, Conformance and CI

| Layer | Command | Needs |
|---|---|---|
| L0/L1 + conformance | `scripts/test-unit.sh` | nothing — no Docker, no network |
| L2/L3 | `scripts/test-api.sh` | the Docker test stack |
| E2E | `scripts/test-e2e.sh` | the full stack plus a browser |
| L4 (paid) | `VSIR_ALLOW_PAID=1 scripts/test-paid.sh` | a credential, and deliberate intent |

Every argument reaches the underlying test runner, so a slice is `scripts/test-unit.sh -k
conformance`.

## The lower layers cannot reach a paid API

This is structural rather than a convention. The scripts export the replay backend and the paid
switch off; the compose stacks set the same values in the container environment; and the CI
workflow sets them again at the job level so a future job that forgets the script still cannot
reach a live model. A cache key the fixture does not hold is a typed miss — never a live call and
never an invention.

The first layer also runs the frontend: the component suite and a type-check run after the backend
suite, so the console is part of layer 0/1 rather than a separate thing to remember.

**The paid layer refuses rather than prompts.** It exits non-zero when the paid switch is not set,
and again when no credential is present — the second check exists because a paid layer with no
credential would fail *per call*, after billing whatever it managed to send. An accidental
full-corpus run is a four-figure mistake, so the gate is a refusal.

## Conformance: the rules with no compiler behind them

Every rule in the conformance suite is a defect that reads as reasonable code. Nobody adds a
fuzzy-matching library to make the system wrong; they add it to make a near-miss match, which is
precisely the injury the design exists to prevent. So each rule is executable, runs in the fast
layer, and names the invariant it protects when it fires.

**Scope** is the backend package and the requirement files, plus the container and compose files
for the deployment rules. **Never markdown** — the specification, the plan and the README quote
every banned string, and a suite that scanned them could only be kept green by not writing things
down. Never the suite's own source either, for the same reason: it names what it bans.

The suite guards itself before it guards anything else: it asserts that it found files to scan,
that every subdirectory scan has something to scan, that it never scans markdown, that it excludes
its own source, and that an *injected* violation is caught and its removal clears the suite. A
conformance check that quietly stops finding things is worse than none.

### What is forbidden

| Rule | Why |
|---|---|
| any-order text matching under the serving package | it would return every page carrying a common token instead of the phrase |
| a declared fuzzy-matching dependency | a near-miss match is the injury the design prevents |
| fuzzy matching from the standard library | the same rule, one import away |
| a model field named `score` | a magnitude invites a threshold, and a threshold turns "ranked ninth" into "no results" |
| a floating model alias anywhere | a moving alias silently changes what the cache keys and the collection fingerprint describe |
| any relational database, ORM or migration tool | the vector store is the only store |
| a Postgres service in the test stack, or publishing the dev gRPC port | publishing that port would let a test run read — and its teardown wipe — the dev collection |
| the text-extraction call outside the probe module | a second extractor means the text a claim is verified against is not the text that was indexed |
| the struck legacy identifier-grammar names | the grammar is gone: no regex, no class, no curated exact-match index |
| opening a log file | stdout is the stream and the platform collects it |
| an image tagged `latest` — or untagged, which is the same defect unwritten | a release is a pinned image |
| a credential literal, or a secret set in an image | secrets arrive from the platform at runtime |
| a test-only branch in the production path | the path under test would stop being the path that ships |
| a module-level mutable store | server-held session state is what lets an agent believe it searched a chapter it did not |
| a blocking HTTP client call | a blocking call in an async handler stalls the whole event loop |

Two of these go beyond a regular expression. The module-state rule is *also* an AST scan that
looks for a module-level container binding that is actually written to, with a planted offender
proving the scan works. And the image-tag rule resolves build arguments before judging a
reference, skipping one supplied by configuration, so an argument-pinned digest is recognised as
pinned.

One invariant is deliberately **not** grepped: that only the probe writes the page text field
cannot be a string search, because the indexing module legitimately upserts a payload containing
that key. The real check is the extraction-call rule paired with an assertion that each record's
text equals the probe's text for that page across the whole fixture.

## L2/L3

Brings up the store and the backend from the test compose file — the same image as production,
differing only in environment and ports — runs the API suite, and always tears the stack down with
volumes removed, because a test run starts from an empty collection or it is not a test.

## End to end

The script brings the whole stack up behind a compose profile, waits for readiness, runs the
browser suite headless and tears down. `--up` leaves it running; any other argument reaches the
browser test runner.

Four operational details are worth not rediscovering:

- **The console port has an override** because a developer machine may already publish the pinned
  one, and the value has to reach three places at once: the published port, the readiness wait and
  the browser's base URL.
- **The fixture is a variable**, so moving the whole run to another corpus is one change and no
  test edit. The host path and the container path are two variables for one directory, because the
  compose file mounts the data directory read-only at a different path.
- **The read quota is raised for this layer.** A browser run asks several whole questions and each
  may spend several reads; here a leaked read would only make a later test fail for what an earlier
  one spent. The ceiling itself is exercised on its own instance in the API layer.
- **One worker.** One suite really stops the store's container to prove the outage path, and a
  second worker asking a question at that moment would be asserting about an outage it did not
  arrange.

There is deliberately **no web-server block** in the browser configuration: the console under test
is a container built from the console image and served the way a release serves it, sharing a
network with the same backend image production runs. A web-server block would quietly substitute a
host dev server for both, and the suite would stop being evidence about anything that ships.

In CI the suite forbids focused tests and retries once; on a developer's machine it does neither,
because a focused test reaching CI is a suite that silently stopped covering the rest, and a retry
locally hides a flake someone should see.

## CI

Two jobs on every push and pull request, both on a **pinned** runner image rather than a rolling
one — a runner that moves under a green build is the same defect one layer out. A superseded run
tells you nothing about the commit that replaced it, so in-progress runs are cancelled per branch.

- **L0/L1 + conformance** — installs the development dependency set and runs the unit script. This
  job is also the gate that keeps fuzzy matching, score fields, floating model ids and the struck
  legacy names out of the tree.
- **L2/L3** — runs the API script, which builds the image and brings up the stack. Both dependency
  resolutions are therefore exercised per run: the development set here, and the hash-locked set
  the image installs.

The abstention evaluation is then re-run as **its own named step**. It has already run inside the
suite; the few seconds are spent so the run summary says whether the safety evaluation passed
rather than burying it among the dots. That step covers both halves: the evaluation as assertions,
and the shipped evaluation *subcommands* driven inside the same managed stack, so the command an
operator runs is exercised on every commit and not only the library behind it.

**The workflow references no secret anywhere**, and the paid layer is not run there at all.

## Related pages

- [Evaluation Corpora and Quality Gates](../evaluation/corpora-fixtures-and-gates.md) — what the named evaluation step measures
- [Replay and Live Execution Modes](../architecture/execution-modes.md) — why the lower layers are free
- [Local Stack, Docker and Deployment](../operations/local-stack-and-deployment.md) — the stacks these scripts drive
- [Operator Console Frontend](../interfaces/operator-console.md) — the frontend suites in layer 0/1
