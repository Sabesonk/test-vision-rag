---
type: subsystem
title: Run Lifecycle, Gates and Publication
description: How an ingest run is recorded in Qdrant, leased, checkpointed per window, stopped and resumed; the five publish gates and the one that may be overridden; the visibility flip; and the three-clause retirement that keeps superseded pages.
tags: [runs, lifecycle, lease, resume, gates, publishing, retirement, exports]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-04b6ef6d0488cd1cd6abc2fe
    resource: repo://backend/vsir/cli.py
  - id: openwiki-source-31f5124ac79834ed431a6185
    resource: repo://backend/vsir/ingest/export.py
  - id: openwiki-source-fadcde690506d03ff98acbfd
    resource: repo://backend/vsir/ingest/gates.py
  - id: openwiki-source-dc74b59971729a18b4bb6624
    resource: repo://backend/vsir/ingest/run.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Run Lifecycle, Gates and Publication

A run's truth lives in the control plane, not in the process. The previous implementation kept
run state in a module-level dict mutated by daemon threads, so a restart stranded a paid run with
no report, no error and nothing to resume from, and no second process could see it at all. Here
`vsir_runs` holds one point per run and one per window, and a second instance can answer
`GET /runs/{run_id}` about a run it never executed.

## Run states and window states

Runs move through `queued`, `running`, `stopped`, `gated`, `published`, `failed`. **Windows have
their own, smaller vocabulary** — `queued`, `running`, `done`, `failed` — because a window is
never *gated* or *published*: those are judgements about a document. What matters for a resume is
whether a window's work is `done` and can be skipped or has to be re-billed.

`gated` is not `failed`. The run finished and the publish gates declined to publish what it
produced, which is the outcome they exist to produce.

## The lease is advisory, and saying so is the design

Qdrant has no compare-and-swap, so claiming a lease cannot be a mutual-exclusion primitive, and
pretending otherwise would be worse than not having one. What makes a duplicated worker *safe* is
elsewhere and structural: the point id is derived from the page id, so a second writer overwrites
rather than doubles, and nothing is queryable until the gates flip visibility. A duplicated worker
is therefore a **cost** bug, not a corruption bug — it re-bills windows. The lease stops that
happening by accident; `--steal` lets an operator override it when a worker has died holding one.

A lease is believed for five minutes and renewed as the run makes progress, so a worker that dies
simply stops renewing and the lease expires rather than needing to be cleaned up.

`claim()` makes two checks **in this order**: first whether a live lease is held by someone else,
then whether the state is resumable. The order matters because "somebody else is on this" has to
be said before "and it is not in the right state anyway" — otherwise an operator racing a live
worker is told about a state machine instead of about the worker.

**`stopped` is the only state a resume takes without `--steal`.** Everything else is either
somebody's live work, a judgement a resume would silently re-litigate, a run that failed for a
reason nobody has read, or a document already serving. `--steal` takes any of them, which is what
makes taking one a decision rather than an accident.

Claiming clears any previous stop rather than carrying it: a run that is running again has not
failed, and a published record still reporting a `sigterm` failure would tell an operator two
contradictory things about the same run. The stop stays in the event stream, where history
belongs.

## Stopping and resuming

A `SIGTERM` is a cooperative shutdown. **The signal handler writes nothing** — it sets a flag, and
the draining code does the writing at a point where nothing else is writing. A handler that wrote
the checkpoint itself would run between two bytecodes of whatever was executing, very often an
in-flight save to the same run point: the handler's `stopped` write could land first and the
interrupted write complete on top of it, leaving the run `running` with a live lease. An operator
would then be told a dead worker held the run, and a resume would refuse without `--steal` — the
exact failure the cooperative shutdown exists to remove.

The drain points are where no control-plane write is in flight: after each window's checkpoint and
at each step boundary. Everything before a drain point is recorded and everything after has not
started, which is what makes "at most one window lost" a property of where those calls are rather
than a hope.

A stop releases the lease rather than leaving it to expire, because a stopped run is one a resume
should be able to take immediately.

A resume buys nothing twice: each extraction response is read from and written to the durable
response cache, so the windows a killed run finished come back under the keys they were billed
under and only the window in flight can be re-billed.

## The five publish gates

Each gate measures the document against **itself** rather than against a declaration an operator
typed somewhere:

| Gate | Metric | Action |
|---|---|---|
| `window_coverage` | pages with an extraction record ÷ page count | **blocks** below 1.0 |
| `offset_check` | windows passing both offset checks | **blocks** on any failure |
| `grounded_rate` | median over pages *with* a text layer | **blocks**, and is the one overridable gate |
| `text_coverage` | pages with text ÷ total | flags `mostly_scanned` |
| `label_monotonic` | printed labels non-decreasing | flags `label_conflict` |

Publication is all-or-nothing, and that part is inherited deliberately: publishing 121 of 122
safety functions and flagging the missing one produces a later measurement of 99.2% that is
**measuring an ingestion bug while looking exactly like a retrieval score**.

**The two flagging gates must never block.** A fully scanned document has no text layer to be
grounded in, so the grounded-rate gate is not *failed* there — it is **not evaluated at all**, and
the document publishes and answers as not-searchable. Quarantining it instead would tell an agent
"that part doesn't exist" about a page that is in the document and simply cannot be searched.
Non-monotonic labels are the same argument one step down: front matter numbered `i, ii` followed
by `1, 2, …` is a normal manual, a genuinely conflicting sequence is worth disclosing, and neither
is worth refusing to publish.

**Only `grounded_rate` is overridable.** It is the one gate that is a judgement — its threshold is
provisional — so a mis-set number must not be able to strand a good document silently. The other
two blocking gates are not judgements: window coverage below 1.0 means pages are missing from the
index, and a failed offset check means the pipeline cannot say which sheet a record describes.
Nothing an operator types makes either safe, so neither takes an override. An override requires a
reason and is refused for any other gate.

The gate threshold is `TRUST_OK_MIN` itself rather than a second literal: two thresholds for one
judgement would let a page be individually trusted inside a document the gate refuses to publish.

`gates rerun` re-evaluates against pages **read back out of the index**, which is what makes the
re-evaluation honest — the gates then judge the document that is actually stored rather than the
one the ingesting process believed it stored.

## Publish: gate, flip, stamp, retire, count, record

The ordering *is* the invariant:

1. **gates first**, because a run that has not passed them cannot answer. A blocked publish saves
   the run as `gated` with the blocking gates named, and zero pages of that document are queryable
   — a half-published document would make every coverage measurement report the pipeline's own
   incompleteness as a property of the corpus;
2. **the flip** — a filtered `set_payload` that sets visibility for the run's points. This is the
   pipeline's only writer of a current page: step 10 writes every point not-current and the index
   module refuses a record arriving claiming otherwise. It is idempotent (a filter and a constant)
   and it is retried;
3. **disclosure flags**, stamped on the pages;
4. **retirement**;
5. **the count**, read back from the index;
6. **`published_at` last**, because it is the claim that the flip completed, and a recorded
   publish time in front of a half-applied flip is precisely the half-finished run this ordering
   exists to prevent.

Retirement sits *between* the flip and the record because deleting a stale point before the new
one is current would leave a window in which the document is not in the index at all.

## Retirement: three clauses, all scoped

1. Points of the **same** `(doc_id, revision)` from an *earlier* run are **deleted** — that is
   what stops totals doubling and stale pages staying findable.
2. Points of the **previously current other revision** are demoted and **kept** — they are what a
   `found_only_in_superseded` result reads from.
3. Points of any other document are never touched, structurally: every filter this path builds
   carries the document's own `doc_id`.

A blanket "delete every point whose run id is not the current run" would pass the first clause's
test and destroy the second's evidence, which is why clauses 2 and 3 each have their own
acceptance test. The retirement report goes into the run record, so the evidence that the delete
happened and the evidence that the other revision was kept are the same record — neither can be
claimed without the other being visible.

`vsir retire <doc_id>` is **demotion, never deletion**: pages stop answering and stay recorded, so
what a superseded-revision result surfaces and what an audit of a past answer is checked against
both survive. A retirement that deleted would make every citation a reader already holds
unverifiable. It replaces a delete route deliberately: withdrawing a document is an operator
action, not a caller's, so it is a one-off admin process rather than a verb any bearer token can
reach. It is idempotent — a filtered write of a constant.

## The exports

Two artefacts are **generated from the index and streamed** rather than written to disk:
`labels.jsonl`, one line per page, and `observed_tokens.jsonl`, one line per document. The
previous implementation wrote a directory from the CLI path and *never* from the HTTP path, so an
upload ingest gave the downstream team nothing at all, and what was written sat on one instance's
disk where a second replica could not serve it. Reading from the index makes any instance able to
serve any run's export, and makes the export a projection of what is actually stored rather than
of what one process remembered.

The withheld-identifiers file is gone with the allowlist gate that produced it: a code the text
layer does not back is not withheld from an index, it is simply absent from the backed-codes list
and counted against the page's grounded rate.

The export's safety flag is computed from two **configured** sources — the uploader's document
type and the model's own topics — rather than from a grammar or a compiled-in keyword list, and a
test asserts by AST scan that no keyword list exists in the module. The flag is advisory metadata:
never a gate, never a filter default, and never a reason to hide a page.

## Related pages

- [Ingestion Pipeline](pipeline.md) — the steps this lifecycle wraps
- [External State and Storage](../architecture/state-and-storage.md) — the control-plane record kinds
- [The vsir Command Line](../interfaces/cli.md) — `runs show`, `gates rerun`, `publish --override`, `retire`
- [HTTP API Surface](../interfaces/http-api.md) — the run and export routes
- [Evaluation Corpora and Quality Gates](../evaluation/corpora-fixtures-and-gates.md) — the report behind the grounded-rate threshold
