---
type: operations
title: Local Stack, Docker and Deployment
description: How VSIR is packaged and run — one hardened image with three process types, the dev and test compose stacks with their ports, volumes and one-off admin services, the stack lifecycle script, and the deployment rules the arrangement holds to.
tags: [docker, compose, deployment, operations, ports, images, hardening]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-600e7dce49b27b22f5486b40
    resource: repo://backend/Dockerfile
  - id: openwiki-source-f011a030ad13c406633402c0
    resource: repo://docker-compose.test.yml
  - id: openwiki-source-b79fbbd921df689b4bbdc82f
    resource: repo://docker-compose.yml
  - id: openwiki-source-cc3f1d0259a2efebbe62cecf
    resource: repo://frontend/Dockerfile
  - id: openwiki-source-823297e013120d7d9437dfe7
    resource: repo://scripts/stack.sh
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Local Stack, Docker and Deployment

## One image, three process types

The web process, ingest work and every one-off admin command run from the **same image and
release**, differing only in environment. The image's entrypoint is the `vsir` binary, so the web
service is a *subcommand* rather than a server invocation — which matters because the boot
self-check runs inside that subcommand before anything binds, so a misconfigured stack fails to
start rather than serving.

### Hardening, and where each property is set

| Property | Set where |
|---|---|
| base pinned **by digest**, not tag | a build argument in the Dockerfile |
| non-root **uid 10001**, no login shell | a `useradd` in the runtime stage |
| runs with a **read-only root filesystem** | the run command and both compose stacks |
| writable `tmpfs` at `/tmp` | the run command and the compose services |
| **hash-pinned** dependency install | a lock file installed with `--require-hashes` |
| no build tooling in the runtime layer | a separate build stage whose venv is copied forward |
| no configuration or secret baked in | nothing is set in the image; boot refuses a missing variable |
| tagged with the release id, never `latest` | the documented build command and both stacks |

The base is pinned by digest because a tag moves and a digest does not. `--require-hashes` makes a
substituted artefact a *build* failure rather than a runtime surprise. Unbuffered output keeps the
JSON event stream flowing to stdout as it happens.

One directory is created and `chown`ed in the image: the document store's mount point. That has to
be in the image rather than only in compose, because Docker initialises a fresh named volume from
whatever is at the mount point in the image, ownership included — with nothing there the directory
is created root-owned and a container running as uid 10001 cannot write to its own volume. The
symptom was found by running the stack: the first seed refused with an unwritable-store error at
the deposit step, correctly and unhelpfully. It is the one writable path outside `/tmp` that a
read-only root filesystem allows.

The console image is built the same way — base pinned by digest, lockfile installed with `npm ci`
so a mismatch fails the build — and it serves with the framework's **preview server rather than a
static file server**, which is load-bearing: the API proxy is declared on both the dev and preview
servers precisely so the container is same-origin with the service. Swapping in a generic web
server would move that proxy into a second configuration file and break dev/prod parity.

## The dev stack

| Service | Role | Host port |
|---|---|---|
| `qdrant` | the store | `127.0.0.1:6353` → 6333 |
| `init` | one-off: create the collection and assert the schema | — |
| `api` | the web process | `127.0.0.1:8055` → 8000 |
| `seed` | one-off: ingest the generated corpus in replay | — |
| `console` | the operator console | `127.0.0.1:5173` (overridable) |

Ports are deliberately unusual, and bound to loopback. The machine this was built on already runs
a store on the conventional ports and something on 8000, and a stack that quietly answered from
the wrong instance is worse than one that will not start.

`init` exists because the server refuses a payload schema that does not match the index schema —
and "does not exist" does not match — so on a fresh volume the collection has to be built before
the server can boot. It is an admin process of the same image rather than a branch inside the
server.

The stack **spends nothing**: it runs the replay backend, which serves frozen responses by cache
key and refuses a missing one as a typed miss rather than calling a model.

Two volume mounts:

- `./data` **read-only** — the corpus and the frozen fixtures are inputs, and nothing in the
  pipeline writes there because the exports stream from the index and touch no filesystem;
- the document store **writable**, as a **host directory rather than a named volume**, so ingested
  PDFs are visible where the operator works. A named volume is outside the image either way, but
  on macOS and Windows it lives inside the Docker VM — so "where did my document go?" had no
  answer a person could list, and replacing a corrected PDF meant a round trip through a copy
  command. On Linux the container uid must be able to write it; the image's `chown` is shadowed by
  a bind mount, so that ownership is set once on the host.

The VLM credential is absent from both the image and the compose file: it is interpolated from the
environment and appears in no log line or response.

## The test stack

A separate compose file, same image, differing in environment and ports.

| Service | Role | Host port |
|---|---|---|
| `test-qdrant` | the store | `6335` → 6333 |
| `backend-test` | the web process | `8001` → 8000 |
| `test-init` / `test-seed` | one-off admin runs (behind the `e2e` profile) | — |
| `frontend-test` | the console (behind the `e2e` profile) | `5174` → 5173 |

The store port is **6335 and never 6334**, because 6334 is the dev instance's gRPC port and
colliding with it would let a test run read and wipe dev data. The store version is pinned to the
same version as dev and production, because phrase matching requires it and a store that differs
between environments is a correctness difference rather than a convenience.

**The test stack's bearer token comes from a different variable than the dev stack's**, and that
is deliberate. Compose interpolates from the developer's own environment file, which is where a
real token lives, so reading the production variable made the stack's credential whatever happened
to be in an untracked file — and the suites assert about the credential the container was handed.
The test conftest resolves the same variable name, so overriding it means overriding both or
neither.

The dev stack takes the opposite decision on purpose: it reads the *same* variable the CLI and a
direct server run read, so there is one token for one machine. Copying the test stack's split here
would divide the answer to "which token?" in two, and whichever an operator reached for, one of
them would fail.

## The lifecycle script

`scripts/stack.sh` wraps the dev stack: `up` (build, start, create the collection, seed a
document), `up --no-seed`, `status` (probes, tools, documents and the token the **running
container** actually has), `seed [PDF]`, `logs`, `vsir …` (any subcommand in the stack's own
image), `down`, and `down --wipe` to drop the index.

Two details worth knowing: the token is resolved lazily, after the stack is up, because before
that there is no container to ask; and it reads JSON with a small Python helper rather than
requiring a JSON CLI tool, since a stack script that needs something installed is a stack script
that does not run.

## Related pages

- [Configuration and Boot Self-Check](../architecture/configuration-and-boot.md) — what the environment must supply
- [External State and Storage](../architecture/state-and-storage.md) — what the volumes hold
- [Test Layers, Conformance and CI](../testing/test-layers-and-ci.md) — how the test stack is driven
- [VSIR Quickstart](../quickstart.md) — bringing the stack up for the first time
