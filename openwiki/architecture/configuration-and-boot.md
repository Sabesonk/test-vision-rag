---
type: architecture
title: Configuration and Boot Self-Check
description: How a VSIR process is configured from the environment alone, which values are pins in code instead, and how the shared boot self-check refuses to start rather than serve a partially correct index.
tags: [configuration, environment-variables, boot-check, health, startup, validation]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-2d60eafee6b3b862b84562b8
    resource: repo://backend/tests/unit/test_doctor.py
  - id: openwiki-source-00e12e09f667d8674b9f2a88
    resource: repo://backend/vsir/config.py
  - id: openwiki-source-1f166a6a750d250e9bccd71b
    resource: repo://backend/vsir/doctor.py
  - id: openwiki-source-ac45219cb616fdd22b513b24
    resource: repo://backend/vsir/logging.py
  - id: openwiki-source-2205ae93add6598628c21601
    resource: repo://backend/vsir/serve/app.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Configuration and Boot Self-Check

Two modules own everything a process knows about itself before it does any work.
`backend/vsir/config.py` turns the environment into one frozen `Config`, and
`backend/vsir/doctor.py` decides whether that configuration, that runtime and that
collection are good enough to serve. They are deliberately small and deliberately
unforgiving: every refusal is named, and no check degrades into a partial service.

## Two kinds of value, and they are not interchangeable

`config.py` holds both, in separate blocks, and the distinction decides whether
changing something is an environment edit or a release.

**Pins** are module constants at the top of the file — raster dpi for indexing and for
answering, the embedding dimensions and concurrency, the fusion surface weights and the
RRF constant, the page caps, the BM25 constants, `COMPOSITION_VERSION` and
`SPARSE_VERSION`. They are properties of the corpus and of the models, identical in
every deployment, and several of them feed cache keys and the collection fingerprint.
None of them is readable from the environment, so no deployment can quietly disagree
with another about how a vector was made.

**Configuration** is the environment and only the environment. Nothing in the codebase
reads `.env`: the file at the repository root is an example a developer sources into a
shell, and its own header says the app never reads it. `load_config()` takes a mapping
(defaulting to `os.environ`) and returns a frozen dataclass; nothing rewrites it after
boot.

## The required set has no fallback

`REQUIRED_ENV` names twelve variables. `_require()` treats an unset variable and a
present-but-blank one identically and raises `MissingConfig`, which carries the offending
variable name. Values that are set but wrong raise `InvalidConfig` with the variable and
the reason — a port outside 1…65535, an embedding dimension that is not one of the three
MRL truncations, a `VSIR_VLM` that is not `gemini` or `stub`, a log level outside the
five, a non-integer quota. There is no coercion and no silent default anywhere on this
path.

The optional set is defaulted in code rather than in a file: the embedding dimension, the
runs collection name, reads per question, the fixture directory, the VLM tier and rate,
the embedding text budget, the document store path, the two safety-facet lists and the VLM
key. `VSIR_VLM_KEY` is optional to `load_config` but required by the boot check when the
Gemini backend is selected — see below.

Two fields are declared `repr=False`: `api_tokens` and `vlm_key`. A frozen dataclass's
`repr` is what a traceback and a naive log line print, so the secrets are excluded from it
at the type level rather than by convention at each call site.

## Derived names, and what a fingerprint describes

Four properties compute the identifiers the rest of the system uses:

- `pages_collection` appends the embedding dimension to the configured stem, so two
  dimensions are two collections rather than two named vectors in one.
- `fingerprint` is the five-field recipe a collection's vectors were made under:
  `embed_model`, `dim`, `distance`, `composition_version`, `sparse_version`.
- `fingerprint_id` is a short digest of that recipe, canonicalised with sorted keys, which
  is what `vsir doctor` prints.
- `replay` is exactly `vlm == "stub" and bool(fixture_dir)` — replay mode is a
  configuration property, never a code branch. See
  [Replay and Live Execution Modes](../architecture/execution-modes.md).

## What reaches a log line

`Config.redacted()` is the only view of a configuration that is logged. It reports the
credential fields as facts about presence — `auth_configured` is a token *count* and
`vlm_key_present` a boolean — and never as values. `scrub_url()` strips userinfo out of
the Qdrant URL before it appears anywhere, replacing it with `***@host:port`, and returns
`<unparseable>` rather than raising on a malformed URL.

Underneath, `logging.redact()` blanks any field whose *name* looks credential-shaped
(`token`, `secret`, `password`, `authorization`, `credential`, `bearer`, plus exact
matches for `key`, `vlm_key`, `auth`). Redacting on the name rather than the value is what
makes a future call site safe by default. That is also why `redacted()` deliberately calls
the token count `auth_configured`: a field named `api_tokens` would have been blanked, and
a count is not a credential. Every line is JSON on stdout, one event per line, carrying
`release_id` and `level`; the correlation context adds `run_id`, `session_id`,
`request_id` and `tool` and holds nothing else.

## The boot self-check

`BOOT_CHECKS` is one ordered tuple of seven callables, and it is the *only* list. `vsir
doctor` runs it and returns an exit code; server start runs it through `assert_boot_ok()`
and raises `BootRefused` before a port is bound. A configuration the CLI refuses cannot be
one the server accepts, because there is no second list to keep in step.

| Check | Refuses when |
|---|---|
| `required_env` | a required variable is unset or blank — and `VSIR_VLM_KEY` is added to the required list exactly when `VSIR_VLM=gemini` |
| `model_ids_pinned` | `VSIR_VLM_MODEL` or `VSIR_EMBED_MODEL` ends in `-latest` |
| `config_valid` | `load_config` raises; on success its facts are the redacted configuration |
| `python_runtime` | the interpreter is below the 3.11 floor |
| `dependencies` | one of the pinned distributions is not installed |
| `collection_schema` | the live payload schema disagrees with `INDEXED` |
| `collection_fingerprint` | the recorded recipe differs from the configured one |

`run_boot_checks()` runs every check even after one fails, because the exit code is what
refuses the boot and hiding the remaining failures only costs the person fixing them
another round trip. `assert_boot_ok()` emits one event per check — `boot_check_ok`,
`boot_check_unavailable` or `boot_check_failed` — and then raises if any failed.

### Three statuses, two policies

A check returns `OK`, `FAIL` or `UNAVAILABLE`, and the third is the load-bearing one. An
unreachable Qdrant or a collection that does not exist yet did not conclude that anything
is *wrong*; it concluded nothing. Boot refuses on `FAIL` only, so a backing-service outage
cannot become a fleet-wide restart loop that outlasts it. Readiness is red on `FAIL` **or**
`UNAVAILABLE`, carrying a named reason (`qdrant_unavailable` or `index_not_ready`), so the
instance leaves the load balancer while the outage lasts. The boot check's Qdrant timeout
is two seconds — a boot check is not a place to hang.

`GET /ready` re-runs the whole list per probe rather than caching the start-up result, so a
schema that drifts under a running process turns that instance red instead of leaving it
answering; it runs in a worker thread because the check list is the sync one shared with
the CLI.

### The two checks that read the store

`check_collection_schema` asserts the live collection against the one `INDEXED` dict — the
same dict that creates the payload indexes — so a dropped index or a half-finished manual
migration becomes a named refusal instead of a quietly narrower filter. A collection that
does not exist is `UNAVAILABLE` and names the remedy (`vsir doctor --create-collection`);
only a collection that exists and disagrees fails.

`check_collection_fingerprint` covers the half Qdrant cannot answer. `dim` and `distance`
are readable off a live collection, but `embed_model` and `composition_version` are not
observable from one at all, so the recipe is recorded on a `kind: fingerprint` point in the
control plane and compared there. This refuses the *boot* and not merely the write, because
a serving process configured for a different recipe embeds the query with one model and
compares it against vectors made by another: no error, no log line, only worse neighbours.
A collection nobody has ingested into yet has no record and passes; a record that exists but
cannot say whether it matches — wrong kind, or a missing field — is drift and fails.

### Creating the collection

`vsir doctor --create-collection` builds the pages collection from `INDEXED` and then runs
the assertion, so it is create-then-check in one command. It is an admin process of the same
image and release as everything else, which is why the dev and test compose stacks run it as
a one-off `init` service rather than letting the server create its own collection — see
[Local Stack, Docker and Deployment](../operations/local-stack-and-deployment.md).

### What `doctor` reports

`report()` prints the release id, the Python version, the two dpi pins, the distance, the
composition and sparse versions, and — when the configuration parses — the resolved model
ids, the fingerprint and its digest, the two collection names, the VLM backend and whether
the process is in replay. A refused configuration reports `None` for the fingerprint rather
than a guess, because the configuration is what the fingerprint is computed from.

The exit event name distinguishes outcomes an operator greps for: `doctor_ok` only when
every check concluded, `doctor_inconclusive` when one was `UNAVAILABLE`, and
`doctor_refused` with `failed_checks` on a refusal.

## Related pages

- [Replay and Live Execution Modes](execution-modes.md) — the `VSIR_VLM` switch and the fixture requirement
- [External State and Storage](state-and-storage.md) — what the collections and the document store hold
- [Page Model and Index Schema](../concepts/page-model-and-index-schema.md) — the `INDEXED` dict the schema check asserts against
- [Local Stack, Docker and Deployment](../operations/local-stack-and-deployment.md) — how these variables are supplied in a running stack
