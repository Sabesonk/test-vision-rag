---
type: evaluation
title: Evaluation Corpora and Quality Gates
description: The checked-in corpora and replay fixtures, what re-keys them, and the four eval commands measured against them — the acceptance table, the adversarial abstention eval, the five corpus metrics with their pinned gates, and the grounded-rate distribution report.
tags: [evaluation, fixtures, corpora, gates, metrics, safety, test-data]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-12T16:01:50.652Z
sources:
  - id: openwiki-source-65e12d40e0372ef5fbf9a0f2
    resource: repo://backend/vsir/eval/abstention.py
  - id: openwiki-source-1d3f8b68896f1219662408ef
    resource: repo://backend/vsir/eval/acceptance.py
  - id: openwiki-source-c428bd051fbd7aa57897dc87
    resource: repo://backend/vsir/eval/corpus.py
  - id: openwiki-source-96cb96888c1de02cfc2e2548
    resource: repo://backend/vsir/eval/grounded_rate.py
  - id: openwiki-source-4c14bced2ccf1c6e75c3fa53
    resource: repo://backend/vsir/eval/legacy.py
  - id: openwiki-source-1d62e40fb1f532163d96b2f5
    resource: repo://backend/vsir/eval/synthetic_large.py
  - id: openwiki-source-4394ffdf5b7202faaa627b6c
    resource: repo://backend/vsir/eval/synthetic_pdf.py
  - id: openwiki-source-fa33ac9c4acabd8a1773314c
    resource: repo://backend/vsir/eval/synthetic.py
  - id: openwiki-source-9c5ac854e711aa574f95eb94
    resource: repo://backend/vsir/runner/loop.py
  - id: openwiki-source-b118941ef22f6be1f794edf9
    resource: repo://backend/vsir/vlm/cache.py
generated: { by: "claude-code", at: "2026-09-12T16:01:50.652Z" }
---

# Evaluation Corpora and Quality Gates

Four corpora live under `data/fixtures/`, and four commands measure against them. The rule
that runs through all of it: **no measurement is written down in the evaluation code.** Every
number a corpus produces is read out of a checked-in expectation file, so there is no line in
an eval module that could be edited to turn a red row green. The only literals in these
modules are the *gates* — the spec's own thresholds — and those are pinned in code precisely
so relaxing one is a reviewable release rather than an environment edit.

## The corpora

| Directory | What it is | Spends |
|---|---|---|
| `synthetic_pages/` | hand-written page text, no PDF — the exact surface proved on its own, plus `expected.json` and `corpus_truth.json` | nothing |
| `synthetic_3window/` | a generated 42-page PDF and its frozen extraction fixture | nothing |
| `synthetic_large/` | a generated 150-page PDF with no contents page, for resume testing | nothing |
| `legacy/` | 19 extraction responses the previous implementation already paid for, plus its exports | nothing |
| `TC1E-SF/`, `live/` | the pilot document and the receipts of a real ingest | already paid |

### The hand-written corpus

One file per page, each carrying only the two things a human can supply — the page's **text**
and the model's **claims** — with the page record derived from them. A hand-written record
could contradict itself (`has_text: true` with empty text, a `codes_in_text` that is not a
subset of `codes`, a rate that follows from neither), so the fixture is deliberately a page
rather than a record. Its points carry an empty vector map, which is honest: this corpus
exercises the exact surface and nothing that ranks.

### The generated PDFs

`python -m vsir.eval.synthetic_pdf` builds the 42-page corpus deterministically, with six
hazards wired into the page geometry rather than described in a comment: three windows over
the page cap with sections straddling folds; a page-label table that makes the printed label
differ from the PDF index, so a derivation that drops the window start lands on a page whose
footer disagrees; a code printed below the footer, invisible in a top-crop raster but present
in the full-page text extraction; a scanned cover over a born-digital body, so a detector that
judged the document from its first pages would discard 40 extractable ones; a code the model
read off the facing sheet, which must move to the page whose text carries it; and a code
printed on no page at all, which must stay put and count against that page's grounded rate.

`python -m vsir.eval.synthetic_large` builds a 150-page companion that differs in exactly one
way that matters: it declares **no contents page**, so the window planner has no chapter
boundary to cut on and falls to the fold-at-the-cap rung — five windows of exactly thirty,
which is both enough checkpoints for a resume test and the only place that rung is exercised
end to end. Everything else is deliberately plain, because a resume test that fails for an
unrelated reason is not a resume test.

Both generators run as a process, which keeps them inside the image rather than on someone's
laptop, and both are idempotent: the same inputs produce the same bytes.

### What re-keys a fixture, and what happens when it is stale

The frozen extraction responses are stored under the content-addressable cache keys, so they
move when the **VLM model id**, the **prompt version**, the **dpi** or the **extraction schema**
moves. That is the point: an edit to the schema means the model was asked a different question,
and its old answer does not contain the new field.

A stale fixture is a typed `fixture_miss` and a non-zero exit, never a stale hit and never a
live fallback. The remedy is to re-run the generator, delete the files under the old keys, and
keep every test environment on the same ids as the live environment.

A **`read` fixture keys on one more thing: the order of its pages** — and that makes an `ask`
replay fixture a hostage to retrieval. The key joins the page image hashes *in the order they
were given* before hashing them with the question, and that is deliberate rather than an
oversight: a model shown the same two sheets in a different order is being asked a different
question, so a key that sorted them would replay one answer for both. What closes the circuit is
that the runner's vision escalation does not choose that order either — it takes the pages in the
order a `skim_pages` ranking returned them. A change to the **fusion** therefore reorders a
`read` call underneath a suite that never mentions ranking.

The synthetic corpus records one such change rather than describing it. The BM25 rewrite of the
sparse surfaces flipped the two image-only sheets of the `ask_vision` case from `(2, 1)` to
`(1, 2)`; the key moved with them; and five tests across three `ask` suites failed with
`fixture_miss` — in suites away from the change that caused them, and only when a later fix ran
the layer that reaches them. The typed miss is the replay contract working exactly as designed,
because the alternative was a stale hit or a silent live call. What it costs is the diagnosis:
the failure names the key, not the ranking that moved it, and the repair is at the generator,
with the superseded file deleted by hand. A fixture whose key depends on a ranking is worth
knowing about *before* the ranking is tuned.

### The ported baseline

The `legacy/` fixture brings a previous implementation's paid receipts into the repository
read-only: 19 extraction responses in the **old** schema, the accepted-label baseline, a
negative set of model-emitted codes the text layer never backed, the run manifest, one page of
verbatim recorded text, and a ledger of every ported file with its sha256 so integrity can be
proved even where the source tree is not mounted.

One export run is pinned, with the reason recorded: of the five kept, only three published
every document, and of those only one is the run the checked-in code produces — the others
withheld labels a later fix backs, so their negative set is polluted by a defect already fixed.

Because there is no PDF, what can be recovered is an **observable projection** of the text
layer: for each page, the identifier strings the old gate found *in that page's text*. The name
is the promise — nothing the model said is in it.

These raw responses are deliberately **not** a replay directory: they answer the old schema
under the old cache key, so replaying them would be a lie; an adapter renames them for the unit
suite instead.

## `vsir eval acceptance`

The acceptance table as something a reviewer runs: one row per assertion, with the expectation
beside the measurement, in three sections.

- **SYNTHETIC** — the hand-written corpus. Always available, always runs.
- **PARITY** — the ported baseline, plus its negative row, plus a **GAINS** report. Gains are
  printed and never failed: a code the old grammar dropped that the phrase index now finds is
  a gain to record, not a diff to reconcile.
- **REAL** — the pilot document, whose table is checked in *ahead of* the ingest. The rows that
  assert the table's own faithfulness to the spec run today; the rows that need real extracted
  text **skip by name**, and the skip count is printed in the summary, because a permanent skip
  nobody notices is its own failure mode.

The direction a literal points is the rule: measurements are read from the checked-in files,
while the *spec's* own text — the label list and its order, the page and window counts, the
weak-absence constant — is written down here and asserted **against** the checked-in table, so
a table that had drifted from the spec would make every measurement below it meaningless.

Every section seeds a collection of its own, queries it and drops it. Nothing touches the
serving collection and nothing can reach a model.

## `vsir eval abstention`

One hundred codes, each one character from a code the indexed corpus really prints, put through
the exact surface and through the check that confirms it. None may return a page; none may be
handed back as what is there instead. The metric is `abstention_correctness`, gated at **1.00**.

Two things this command does that a unit test cannot: it can be pointed at a corpus that is not
a fixture (`--corpus indexed` runs against whatever the configured collection currently holds,
reading only — no upsert, no delete, no collection creation), and it reports the *number* with
the leaks named if there are any.

It has a **control row**, and an evaluation of absences needs one: a corpus that answered
nothing at all would pass every assertion above, so the real codes the fakes were mutated from
are looked up too and every one must come back. Without it a broken index is indistinguishable
from a perfectly abstaining one.

A run that cannot measure prints `abstention_correctness: not measured` and exits non-zero —
0 of 0 is never 1.00.

## `vsir eval corpus` and the five gates

The full metric catalogue, read off a published index against a checked-in ground-truth file.

| Metric | Gate | Shortfall is |
|---|---|---|
| `code_precision` | = 1.00 | a **P0 stop** |
| `code_recall` | ≥ 0.95 | a failure, and **BLOCKED** below 0.90 |
| `abstention_correctness` | = 1.00 | a **P0 stop** |
| `alarm_label_hit` | ≥ 0.99 | a failure |
| `xref_resolve` | ≥ 0.99 | a failure |

Two of the five are stops and three are targets, because precision is a safety property and
must be perfect while recall is a measured target — and the difference is visible in the output,
in the exit code, and in what a re-baseline may touch. The `abstention_correctness` floor is
pinned in two modules and the two are **asserted equal at import**, so one number cannot become
two answers.

**Both ratios are counted over `(code, page)` pairs**, not per code. A code found on the right
page and also on a wrong one would score as a whole code found under a per-code reading, and the
injury this system exists to prevent is the wrong *page*. Pair counting is the only reading
under which a precision of 1.00 means what it says.

Each row prints its denominator and `1/denominator` — the smallest non-zero shortfall the set
can register — and a set whose resolution is coarser than its gate's tolerance is marked
**underpowered**. Four cross-reference tokens can *fail* a 0.99 gate and cannot evidence it, and
saying so beside a green row is the difference between a measurement and a decoration. A safety
metric is never marked underpowered — "no miss in n" is exactly what a 1.00 gate asks — it is
reported with its `n`.

**A skip is not a pass.** A ground-truth file may declare a set `unavailable` with a reason, and
that set skips with the reason printed; a set with neither rows nor a stated reason is a refusal,
because "the file is not there" and "the file says this set is unavailable" are different things.
A report is green only when nothing was refused, nothing failed, **and something was measured** —
every set skipping by name is honest output and is not a passing report.

The command reads only: no ingest step, no model call on any path, and with `--corpus indexed`
it creates, upserts and deletes nothing. It also re-validates the publish threshold against
whatever is indexed and prints the list of paths the ported baseline says nothing about, so a
green report is never read as coverage of them.

### Re-baselining

The gates may be re-baselined exactly once, from a real measurement, with a recorded rationale.
That permission is expressed so it cannot be taken silently: a re-baseline record carries the
corpus it was measured on, the measurement itself and the rationale, and it is refused when any
of those is missing, when it moves nothing, when it lands below the blocking floor, and — always
— when it would lower a safety floor. No rationale buys a precision under 1.00. Every
re-baseline departs from the spec's own number rather than from a previous re-baseline, so
"exactly once" holds by construction. The table is **empty in this release** and the report says
so.

## The grounded-rate distribution report

The publish gate's threshold is *chosen, not derived*, and this report is the count that would
justify it: it takes a document's page records, reports the distribution of their rates, and says
what each candidate threshold would have done. It decides nothing.

Three rules it inherits and would be wrong without: a page with no text layer has **no rate and
is not a zero**, so the denominator is pages-with-text; the median is computed by the same
function the publish gate scores with, so a recommendation can never be made against a number the
gate does not use; and a fully scanned document sets nothing — with no measured page there is no
distribution, the gate is skipped rather than failed, and no threshold is recommended.

`VSIR_GROUNDED_RATE_THRESHOLD` is read **here, by this report, as the candidate being evaluated**
and nowhere else. It is deliberately not wired into the publish gate: the threshold reaches the
gate the way a model id does, by editing the pin and shipping a release.

## Related pages

- [Replay and Live Execution Modes](../architecture/execution-modes.md) — the cache keys these fixtures are stored under
- [Test Layers, Conformance and CI](../testing/test-layers-and-ci.md) — where these commands run automatically
- [Exact Match and Claim Verification](../concepts/exact-match-and-verification.md) — the near-miss generator feeding the abstention eval
- [The vsir Command Line](../interfaces/cli.md) — how these commands are invoked
- [Run Lifecycle, Gates and Publication](../ingestion/run-control-plane-and-publishing.md) — the publish gates the threshold report is about
