# fixes/

Defects found in the shipped ingest pipeline (§6.1 steps 01-11) by auditing it against the real
corpus rather than against the fixtures. One file per fix: the evidence, the change, what it
breaks, how to verify, how to roll back.

A fix here is **proposed until applied**. The status line at the top of each file is the truth.

## Register

| # | Fix | Files | Status |
|---|---|---|---|
| **001** | [The window ladder refuses half the corpus, including the pilot document](001-window-ladder-refuses-half-the-corpus.md) | `ingest/window.py` | **applied** |
| 002 | §6.4 check (2) raises on one witness, and the repair cannot change the verdict | `ingest/derive.py` | **applied** |
| 003 | `label_verified` is true where the page's own text disagrees | `ingest/derive.py` | **applied** |
| 004 | S1 is asked for a table of contents the file already declares (register A6) | `ingest/probe.py`, `cli.py` | not written up |

Applied in the register's order — 002, 003, then 001. 004 changes only which input `plan()` gets,
so it wanted 001 already in, which it now is.

**Two deviations from the write-ups, both measured rather than argued:**

1. **`pack()` has a floor rather than filling to the cap.** Filling greedily also merges chapters
   that are already the right size — the synthetic corpus's three 14-page chapters become two
   28-page windows — which makes **Level 1's boundaries come from the cap rather than from the
   chapters**, the one thing that distinguishes the rungs. A floor on the merge
   (`MIN_WINDOW_PAGES`, a third of the cap) reaches the same counts on every document 001
   measured, because in all of them the offending chapters are the small ones: `ETC1AV81`
   592 → 20, `LTC1AV81` 12 → 2, `TC1E-SF` unchanged at `(1, 30), (31, 55)`. It also leaves
   `data/fixtures/synthetic_3window/` **byte-identical**, so the fixture regeneration 001 budgeted
   for was not needed and the seven test files that assert on its folds at 14|15 and 28|29 did not
   have to move.
2. **002's predicate is not a flat `witnesses >= 2`.** A flat threshold loses sensitivity where a
   window has one legible label: `TC1E-SF`'s ported window carries 30 labels of which 29 are
   printed nowhere, so a genuine one-page shift yields exactly **one** witness — and a flat rule
   accepted it, and accepted every half on the way down a bisection, so §6.2's terminus was
   reached by agreeing with a shifted window instead of by naming a page. `check_offset` refuses
   on two witnesses **or** on one when *nothing in the window confirms its own label*, which is
   §6.4's own argument — *"a genuine shift moves every page of the window"* — stated exactly.

**Verification.** `scripts/sweep-corpus.py <corpus-root>` is 001's corpus sweep as a script: no
key, no Qdrant, no spend. On `~/Documents/dilmah_enginnering_usecase` — 208 documents, 5,630 pages:

| | before (add5a97) | after |
|---|---|---|
| documents that plan | 194 / 208 | **208 / 208** |
| pages refused | **2,719 (48%)** | 0 |
| windows billed | 1,510 | 369 |
| coverage / cap / parallelism violations | — | **0** |

`bash scripts/test-unit.sh` → **1109 passed** (1064 before: four rewrites, nine new tests).

## How these were found

The pipeline's own predicates were run over every PDF in
`dilmah_enginnering_usecase/dataset` — 202 files, 5,578 pages, including the three uppercase
`.PDF` diagram files that a case-sensitive glob misses. Each finding below is a measurement on
that corpus, not an inference from reading the code.

## 002 — one witness is not enough (summary)

§6.4 check (2) reads the page label the model reported and raises `OffsetError` if that label is
not phrase-present in the page's own text but **is** present on a neighbour's. Simulated across
the corpus using each file's own `/PageLabels` as the model's reading — a mechanical ground truth
for what is printed — it fires on **22 pages across 11 of the 98 documents that declare labels**.
Every one is false: the page really is that page. The cause is bare numerals, `label '1' printed
on [2], not on p1` — the token is not in page 1's text layer and happens to occur on page 2.

The part that makes it block rather than cost: `_neighbours_printing` reads `probed`, the **whole
document**, not the window. The predicate is therefore **invariant under bisection** — the repair
re-bills both halves and reaches the same verdict, down to `window_unsplittable`. `offset_check`
is a blocking gate and is deliberately not in `OVERRIDABLE`, so one ordinary page costs the
document plus roughly eight paid windows on the way down. §6.4's stated asymmetry — *"a false
positive costs one re-billed window"* — is the assumption that does not hold.

The fix comes from §6.4's own argument. It says *"a genuine shift moves every page of the window,
so the first observation is as good as the twentieth."* True — and therefore a **second witness is
always available on a real shift**, while a false positive is isolated by nature. Require two:
`OFFSET_WITNESSES = 2`, collect the observations across the window, log a structured
`offset_singleton` for a lone one and return. Sensitivity on a real shift is unchanged; all 22
measured false positives disappear.

`test_a_label_printed_nowhere_is_a_misread_not_a_shift` already covers "printed nowhere". The case
with no test is "printed on a neighbour **and** genuinely this page's label".

## 003 — `label_verified` where the page disagrees (summary)

`derive.attribute_label` ends:

```python
verified = printed_in(tokens, only) or only == _collapse(file_label)
```

When the model returns no label, the file's `/PageLabels` entry is accepted as **verified** even
though the page's own text does not print it. A `/PageLabels` table is a mechanical readout of the
*container*, and writers emit a plain 1..N table regardless of what is on the sheet.

On the same 22 pages as 002, one code path stamps `label_verified: true` while the other calls the
identical evidence a fatal off-by-one. Make them agree — the page is the better witness where it
has a text layer:

```python
verified = printed_in(tokens, only) or (only == _collapse(file_label) and not has_text)
```

## 004 — the file already has the table of contents (summary)

Register item A6, still open. The chapter list that picks the rung comes only from S1, the model
reading rendered front matter, and `TocEntry.page_no`'s docstring records that 0 — no usable PDF
index — is *"the common case for a printed contents page"*. Meanwhile `doc.get_toc()` usually
carries the real thing with real indices: 14 documents in this corpus declare a usable outline,
covering 1,751 pages.

An outline is the same class of evidence as `/PageLabels` — a mechanical readout of a structure
the file declares, not a reading and not a grammar (§5.2 permits it for exactly that reason). Read
it in `probe._read()`, which already has the document open, carry it as `Probe.outline_starts`,
and prefer it over `facts.toc` at the `cli.py` windowing call with a `toc_source` field on the
step-05 log line. Free, deterministic, and it removes an uncached model call from the branch that
decides how much S2 costs.
