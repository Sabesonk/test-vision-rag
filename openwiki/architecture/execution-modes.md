---
type: architecture
title: Replay and Live Execution Modes
description: How one environment variable selects both the extraction and the embedding backend, what the four content-addressable cache keys are made of, and how frozen fixtures let the whole pipeline run without a credential or a bill.
tags: [replay, fixtures, caching, vlm, embeddings, cost-control, dev-prod-parity]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-4f4ec51d528193ad998d29e2
    resource: repo://backend/tests/unit/test_cache_keys.py
  - id: openwiki-source-85164da3eb010b967e464903
    resource: repo://backend/tests/unit/test_conformance.py
  - id: openwiki-source-94974397b90495200dfe11e5
    resource: repo://backend/vsir/ingest/embed.py
  - id: openwiki-source-1353375d38e7b12c3339cc29
    resource: repo://backend/vsir/serve/ingest.py
  - id: openwiki-source-73707f81e52dcc80578fddc1
    resource: repo://backend/vsir/vlm/__init__.py
  - id: openwiki-source-b118941ef22f6be1f794edf9
    resource: repo://backend/vsir/vlm/cache.py
  - id: openwiki-source-55e81f3834a13587de05c714
    resource: repo://backend/vsir/vlm/cached.py
  - id: openwiki-source-ca691e6b731c8c2f60424ed3
    resource: repo://backend/vsir/vlm/client.py
  - id: openwiki-source-b54d9a3e9b3bb2ad2872004d
    resource: repo://backend/vsir/vlm/record.py
  - id: openwiki-source-a41233e92a1a6e91bb09541f
    resource: repo://backend/vsir/vlm/stub.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Replay and Live Execution Modes

`VSIR_VLM` is the whole switch. It selects the extraction backend **and** the embedding
backend, so a run that replays extraction from a fixture cannot quietly spend on
embeddings, and there is no second variable to forget. Both modes are the same code path
with a different attached service — not a branch, not a mock, not a test-only import.

| | `VSIR_VLM=stub` (replay) | `VSIR_VLM=gemini` (live) |
|---|---|---|
| extraction and `read` | frozen bodies from `VSIR_FIXTURE`, by cache key | billed calls to `VSIR_VLM_MODEL` |
| embeddings | a deterministic function of the composition | one billed call per page to `VSIR_EMBED_MODEL` |
| credential | none read | `VSIR_VLM_KEY` required, else `vlm_backend_unavailable` |
| a key the store lacks | typed `fixture_miss` — never a live fallback | — |

## The backend is a dict lookup

`vsir.vlm.BACKENDS` maps the `VSIR_VLM` value to a constructor, and `vsir.vlm.backend()`
performs one lookup with no conditional. `vsir.ingest.embed.EMBEDDERS` is the identical
shape for the embedding side. Both backends are imported unconditionally at module import,
so the image contains both and the choice is made at boot from the environment — the same
release runs as the web process, as an ingest worker and in CI, differing only in
configuration. A `VSIR_VLM` value neither table knows raises a typed `vlm_backend_unavailable`
naming the available backends rather than surfacing a `KeyError`.

This is enforced, not merely intended: the conformance suite greps the whole package for
`if TESTING`, `os.environ.get("TESTING")`, `PYTEST_CURRENT_TEST` and `"pytest" in …`, and
fails the build if any appears. A test-only branch would mean the path under test is not
the path that ships.

## The four cache keys

A cache key is a receipt: *has this exact question already been asked of this exact model?*
Every input that can change the answer is on the key, and nothing that cannot.

```
facts_key   = sha256( document content hash ‖ vlm model id ‖ prompt_version )
extract_key = sha256( ordered page image hashes ‖ vlm model id ‖ prompt_version
                      ‖ dpi ‖ schema hash )
read_key    = extract_key inputs ‖ question
embed_key   = sha256( composition_version ‖ embed model id ‖ composed string )
```

Several details are load-bearing:

- **Inputs are length-prefixed before they are joined.** A plain separator is ambiguous —
  `("a|b", "c")` and `("a", "b|c")` would concatenate identically — and one of the inputs,
  `prompt_version`, is operator-supplied. A key two configurations can collide on serves
  one configuration's output as the other's and reports a hit.
- **`extract_key` is keyed on ordered page image hashes**, so the key depends on the pixels
  the model will actually see and two windows of one document cannot collide. Order matters
  because a model shown the same pages in a different order is being asked a different
  question.
- **`read_key` adds the question**, which is why `read` does not let a caller choose the
  dpi: a caller-controlled dpi would be a free way to vary the key and bill the same
  question three times.
- **`embed_key` has no `dim` input.** A dimension change is a change of *collection*, so two
  dimensions never share a namespace to be confused inside; the fingerprint guards that, not
  this key.
- **`VSIR_VLM_TIER` is on none of them.** Batch and standard produce the same output, so
  putting the tier in a key would re-bill a whole corpus for taking a discount.

Keys are addressed under three namespaces — `facts`, `extract`, `read` — one per *call*
rather than per model, so two calls asking different questions cannot collide even if their
keys somehow did. The namespace is part of the derived control-plane point id, not merely a
payload field.

## Two stores, and who may write to each

`FixtureStore` is replay's half: a read-only content-addressable directory of frozen
responses, checked into the repository. It is read-only by design — replay that could fill
its own cache would freeze a single accidental live call into the repository as though it
had been reviewed. A missing key raises `FixtureMiss`, which names the namespace, the key
and the directory. Each response is addressed by its key alone, with no revision, run id or
document id in the path, because the key already carries the content hash.

`ControlPlaneStore` is production's half, living beside the run in the `vsir_runs`
collection under `kind: vlm_cache`. It fills itself from calls that have already been paid
for. A write failure is swallowed and logged — a store that will not take an entry costs the
*next* run a re-bill and costs this one nothing — while a failure on the way out is left to
raise, because guessing "probably not cached" during an outage is how an outage becomes an
unmetered afternoon.

The sole writer into a fixture directory is the module-level `write()` function, kept off
`FixtureStore` deliberately: the store a running process holds cannot write, and only the
corpus generator and an explicit `--record` run may add to a fixture.

An `Entry` keeps the **verbatim** body plus `finish_reason` and `usage`. Caching a processed
record instead would look equivalent and would make every downstream change unreplayable,
because re-deriving would mean buying the paid call again.

## The stub backend

`StubBackend` serves frozen responses out of one read-only directory by key, and does three
things deliberately *not*:

- it never makes a live call on a miss, which would turn a free CI run into a billed one;
- it never fabricates a response, which would make every downstream green test a statement
  about data no model produced;
- it never looks at the pixels. The rasters are on the request because the *key* was
  computed from them; a stub that inspected images would be a second extractor with its own
  opinions inside the path the tests trust.

`VSIR_VLM=stub` with no `VSIR_FIXTURE`, or with a path that is not a directory, is refused by
name as `vlm_backend_unavailable` rather than skipped — a suite that quietly asserted nothing
would be worse than one that stopped.

Replay can also reproduce a *truncation*. When the provenance sidecar records a response the
provider cut off at the output ceiling, the stub raises `VlmTruncated`, so the bisect-and-
re-bill repair path is exercised by the frozen corpus instead of only by a paid run.

## The live backend

`GeminiBackend` is built only from a configuration that carries `VSIR_VLM_KEY`; without one
it refuses `vlm_backend_unavailable` up front rather than failing per call. Its credential
field is `repr=False`, so no traceback or log line can carry it.

Three guards sit in front of a call:

- **the tier.** Anything but `standard` raises `vlm_tier_unsupported`, and the refusal notes
  that because the tier is not a key input a run started on standard can be finished on batch
  for free once that path exists.
- **the pin, re-verified at the point of spend.** `_pinned()` refuses a model id ending in
  `-latest` again here, outside the retry ladder, because a long-lived worker's configuration
  may never have been through a boot check. When a provider repoints a floating alias the key
  string does not change but the model behind it does, and the cache then serves extractions
  from a different model under a name claiming otherwise.
- **the prompt.** `prompt()` loads the stage's text and checks it against `PROMPT_DIGESTS`,
  which this release populates for `s2-v2` only. A prompt is part of the release, so editing
  the prompt files without registering a version is refused as `prompt_unavailable`. Replay
  never reaches this function at all — the prompt version lives in the cache key and nowhere
  else, which is how fixtures frozen under an older version keep working.

Calls are paced by a `TokenBucket` sized from `VSIR_VLM_RPM` and retried up to
`MAX_ATTEMPTS` with exponential backoff. The retryable set covers HTTP statuses *and*
`httpx` transport failures: a connection that never produced a reply is definitionally worth
retrying, and the comment records three live runs lost to exactly that gap — one of them
after S2 had already been paid for.

## Caching and recording wrap the boundary

`CachingBackend` sits in front of whichever backend was selected: it reads the store, calls
the inner backend on a miss, and writes the answer back. It wraps the *stub* too, deliberately
— caching replay saves nothing, but a cache only present when the expensive backend is
selected would be a code path the free test levels never exercise, and the resume it exists
for would be proven only by a run nobody can afford.

`RecordingBackend` wraps a backend and freezes each response verbatim under the key the call
was made with. Wrapping the boundary rather than a step is what makes both wrappers correct:
extraction is called from two places and bisection makes more calls mid-flight, so anything
wired per step would miss the halves of a bisected window — the very run whose receipts are
worth keeping. Recording is a flag on one `vsir ingest` run and never a configuration value,
because an ambient record mode would accumulate responses from runs nobody meant to freeze.
The recorder never substitutes a body: every response comes from the wrapped backend,
unexamined.

## The embedding side of the switch

`StubEmbedder` does not replay a frozen response — 1,536 floats would be unreviewable and no
more truthful than a hash — it computes the vector as a deterministic function of the
composition. That buys the two properties the tests need: the same composition always gives
the same vector, and a changed composition gives a different one. This is safe here and would
not be for extraction, because nothing downstream asserts what a vector *means*; every path
that can reach an answer goes through the exact surface over probe-extracted text.

`StubEmbedder` namespaces its model id as `stub:<model>` so a stub vector and a live vector
can never share an `embed_key`. Before that prefix existed, a collection seeded under `stub`
and re-ingested under `gemini` reused every hash vector, billed nothing, and reported them as
*reused* — a run that looked like a successful production re-embed had bought no embedding at
all. The operator's own model id still reaches `_pinned()`, so the `-latest` refusal is
unaffected.

`GeminiEmbedder` takes the same credential as the VLM. Both live backends build their SDK
client lazily behind a lock, because the embedding step fans batches out over a thread pool
and an unguarded lazy build races: two threads both see `None`, the second assignment orphans
the first client, and the thread still holding it fails mid-run after the extraction spend.

## Which paths can bill

Only a live backend bills, and only from these places: the S1 and S2 extraction calls, the
`read` tool, and one embedding call per page. Everything else in the system — every other
tool of the ladder, every search, every verification — is free in both modes.

`VSIR_ALLOW_PAID` is read in exactly one place in the application, `check_spend_allowed` at
the `POST /documents` boundary, and it refuses a live-configured release with `403
spend_not_permitted` rather than letting an upload discover the bill by accident. A
`stub`-configured release takes uploads with no switch at all, because replay is free by
construction. The CLI is deliberately not gated by it: `vsir ingest --vlm gemini` bills
either way, because a CLI ingest is already a deliberate act.

## Related pages

- [Configuration and Boot Self-Check](configuration-and-boot.md) — where `VSIR_VLM` is parsed and `replay` is derived
- [Windowing and VLM Extraction](../ingestion/vlm-extraction-and-windows.md) — what the extraction calls ask for and how a bad response is repaired
- [Embedding and the Three Retrieval Surfaces](../ingestion/embedding-and-sparse-surfaces.md) — the composition `embed_key` hashes
- [Evaluation Corpora and Quality Gates](../evaluation/corpora-fixtures-and-gates.md) — the fixture directories and what re-keys them
- [Test Layers, Conformance and CI](../testing/test-layers-and-ci.md) — how the lower layers are kept away from a paid API
