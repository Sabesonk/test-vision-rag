# Fix 001 — the window ladder refuses half the corpus, including the pilot document

**Status:** **applied** — see `fixes/README.md` for the two measured deviations
**Files:** `backend/vsir/ingest/window.py` (all of it), `backend/tests/unit/test_window.py` (six tests)
**Spend:** none to apply. Unblocks the M2b re-bill, which is paid.
**Spec touched:** §6.2 (the ladder), §2.5 B (the Level 2 exclusion)

---

## What is wrong

`window.plan()` knows two ways to cut a document and refuses everything else:

* **Level 0** — the whole document in one window, if it is `<= CAP_PAGES_PER_WINDOW` (30) pages
  and `<= MAX_INLINE_BYTES`.
* **Level 1** — one window per chapter, if S1 returned chapter starts **and** every chapter is
  already `<= cap`.
* otherwise — `LadderLevel2Required`, a hard typed refusal. The document does not ingest.

Three consequences, measured rather than reasoned about.

### 1. Half the corpus cannot be ingested

Every PDF under `dilmah_enginnering_usecase/dataset` — 202 files, 5,578 pages, including the three
`.PDF` diagram files — put through the shipped ladder, giving Level 1 the **best possible** break
by feeding it the PDF's own outline (which is strictly better than what S1 can read off rendered
front matter):

| rung | documents | pages |
|---|---|---|
| Level 0 | 174 | 1,108 |
| Level 1 (best case) | 14 | 1,751 |
| **`ladder_level_2_required`** | **14** | **2,719 — 49% of the corpus** |

Eleven of the fourteen refusals declare **no outline at all** — vendor catalogues of 32–116 pages.
The three others have one chapter over the cap. The true figure is worse than 49%, because S1 does
not see the outline: it reads the front matter as images, and `TocEntry.page_no`'s own docstring
records that 0 — *"the model could not see a PDF index"* — is *"the common case for a printed
contents page"*.

Largest refusals:

```
  1440pp  309.9MB  chapter 92pp   Use & Maintenance/TC1AV8M2_1.0.pdf
   384pp    5.8MB  chapter 32pp   Datasheet/240/...sieps80000046l_20_1.pdf
   116pp    1.5MB  no outline     Datasheet/5317/...6020011.pdf
   115pp    2.7MB  no outline     Datasheet/5398/...27JMNF-pdf.pdf
   104pp    7.8MB  no outline     Datasheet/5394/...Catalog_A_Edition_November_2017_IT_EN1.pdf
    92pp    9.7MB  no outline     Datasheet/454/...3110000_Technical_system_catalogue_EN.pdf
    92pp    9.7MB  no outline     Datasheet/5375/...3286410_Catalogo_tecnico_EN.pdf
    87pp    6.7MB  no outline     Datasheet/5373/...datasheet-Brecoflex-100T54280V-168556.pdf
    70pp    3.6MB  no outline     Datasheet/5331/...6502065.pdf
    60pp   11.5MB  no outline     Datasheet/5322/...6153323.pdf
    55pp    1.1MB  chapter 55pp   Use & Maintenance/Attachments/TC1E Schemi funzioni di sicurezza_1.3...
    36pp    9.2MB  no outline     Datasheet/5110/...6402102_EN.pdf
    36pp    1.3MB  no outline     Datasheet/5111/...phoenix-contact-2967620-en.pdf
    32pp    6.2MB  no outline     Datasheet/6449/...l118_h3dk_solid-state_timers_datasheet_en.pdf
```

### 2. The pilot document is one of them, so M2b cannot complete

`TC1E-SF` is 55 pages (over the cap) with a single outline entry (one 55-page chapter, over the
cap). `plan()` refuses it at step 05, before S2 spends anything. **U013 does not unblock when the
PDF and the credential arrive** — it fails one step earlier, on a design decision.

Spec §6.2 asserts the opposite:

> every document in the POC slice (6 documents, 142 pages) ingests without Level 2

The manifest §6.2 cites as its evidence — `data/fixtures/legacy/manifest.json`, `impl`'s `r-poc-5`
run — says otherwise:

```
doc_id             pages level windows
TC1E-SF               55     2       2     <- the pilot, ingested at Level 2
LTC1AV81              34     1      12
TC1E-PERIODIC         25     0       1
TC1AV8M2-LIFTING      24     0       1
DS-5549-EATON          3     0       1
CE-TC1AV8              1     0       1
```

One of the six needs Level 2, and it is the one M2b is built on. `data/fixtures/TC1E-SF/expected.json`
— normative, and blocking if the first ingest disagrees — declares `window_ranges: [[1,30],[31,55]]`.
That is a blind 30-page fold. The shipped `plan()` cannot produce it under any input.

### 3. No floor on window size: one document bills 30x what it should

`chapter_ranges` bounds a chapter above (the cap) and never packs small ones together.
`ETC1AV81.PDF` declares **8,187 outline entries** over 592 pages, which cut into **592 one-page
windows** — 592 S2 calls where about 20 do the same work. `impl`'s own manifest shows the same
shape already biting: `LTC1AV81`, 34 pages, ran **12** windows at Level 1.

---

## Why the exclusion can be lifted

§2.5 B excludes Level 2 because `impl`'s Level 2 was a blind cut that **had to run sequentially
with a carry chain** — *"batch 2 needs to know what batch 1 ended with"*
(`impl/pipeline-guide/04-windowing-and-keys.md` §5). That is a correct description of `impl`.

It is no longer a description of this codebase. `impl`'s model reported section **extent**, so a
window that began mid-section had to be told where it was. §5.2 deleted extent: `sections[]` is
**presence per page**, and §6.1 step 08 computes extent as `(min, max)` over sightings keyed by
`derive.section_key`. `ingest/stitch.py`'s own docstring works the example —

```
window 1 (1-14):   "Emergency stop chain" on 13, 14
window 2 (15-28):  "Emergency stop chain" on 15, 16, 17
stitch:            one section, pages 13-17, one section_id on all five
```

— and calls it *"what makes cutting the document safe"*. Two windows that never saw each other
reassemble one section. **The carry chain's reason was removed along with `units[]`; the exclusion
stayed behind.**

Nothing else about a fold is unsafe here. A window is a page range, not a chunk — it is never a
retrieval boundary, the index unit is the page, and F8 (a section straddling a fold) is precisely
what stitching already handles. What is *not* reintroduced is the sequential dependency, so
`Plan.parallel` stays true at every rung.

---

## The change

All of it is in `backend/vsir/ingest/window.py`.

### 1. Two new helpers, above `plan()`

```python
def split_oversized(ranges: Iterable[tuple[int, int]], cap: int) -> tuple[tuple[int, int], ...]:
    """Fold a range longer than ``cap`` into ``cap``-page windows, filling before spilling.

    This is the fold `impl` called Level 2, without the part that made it unsafe there. Its carry
    chain existed because `impl`'s model reported section **extent** — "batch 2 needs to know what
    batch 1 ended with". §5.2 deleted extent: `sections[]` is presence per page and step 08
    computes ``(min, max)`` over sightings, so two windows that never saw each other reassemble
    one section (F8). The reason for the chain was removed with the schema; the fold is safe
    without it and stays parallelisable.

    Fill-before-spill rather than even parts: it is one comparison instead of two divisions, and
    it is what `impl` did, so `data/fixtures/TC1E-SF/expected.json`'s ``[[1,30],[31,55]]`` — written
    from the spec before the ingest, and normative — is reproduced exactly rather than approached.
    """
    out: list[tuple[int, int]] = []
    for start, end in ranges:
        at = start
        while at <= end:
            out.append((at, min(at + cap - 1, end)))
            at += cap
    return tuple(out)


def pack(ranges: Iterable[tuple[int, int]], cap: int) -> tuple[tuple[int, int], ...]:
    """Merge consecutive ranges into windows of at most ``cap`` pages.

    The cap bounds a window above and nothing bounded it below, so a densely outlined document
    billed one call per sheet: `ETC1AV81` declares 8,187 bookmarks over 592 pages and cut into 592
    one-page windows where 20 do the same work, and `impl`'s 34-page `LTC1AV81` ran 12. Packing is
    greedy and order-preserving, so the page set is unchanged and every boundary it keeps is still
    a chapter boundary.
    """
    packed: list[tuple[int, int]] = []
    for start, end in ranges:
        if packed and end - packed[-1][0] + 1 <= cap:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    return tuple(packed)


def inline_cap(page_count: int, size_bytes: int, cap: int) -> int:
    """``cap``, reduced where the file is too large to hand over ``cap`` pages at a time.

    Ported from `impl` as a ceiling on Level 0 and kept here as a bound on **every** rung. As a
    refusal it only pushed the document to a rung that refused too; as a bound it does the thing
    it was for.

    It measures the **source PDF** while `extract_window` sends **rendered PNGs**, so it is
    conservative rather than exact. A raster-bytes budget is the honest replacement and is a
    follow-up, not this fix.
    """
    if size_bytes <= MAX_INLINE_BYTES or page_count < 1:
        return cap
    return max(1, min(cap, int(MAX_INLINE_BYTES // (size_bytes / page_count))))
```

### 2. `plan()` — replace the body

```python
def plan(page_count: int, *, toc: Iterable[TocEntry | Mapping[str, Any]] = (),
         size_bytes: int = 0, cap: int = CAP_PAGES_PER_WINDOW, document: str = "") -> Plan:
    """The ladder: Level 0 whole, Level 1 on the document's own structure, Level 2 a fold.

    Every rung produces windows of at most ``cap`` pages covering 1..``page_count`` exactly once,
    and every rung is parallel. The difference between them is only **where the boundaries come
    from** — the document itself, its chapters, or the cap — which is what the rung number is
    for and what the run record reports.
    """
    if page_count < 1:
        raise WindowError(f"a document has at least one page, got {page_count}",
                          document=document, page_count=page_count)

    cap = inline_cap(page_count, size_bytes, cap)

    if page_count <= cap:
        return Plan(0, (Window(1, page_count, 0),))

    chapters = chapter_ranges(toc, page_count)
    if chapters:
        return Plan(1, tuple(Window(start, end, 1)
                             for start, end in pack(split_oversized(chapters, cap), cap)))

    # No structure to cut on, so the cap is the only boundary there is. Not `impl`'s rung: no
    # carry chain, no sequential dependency — see `split_oversized`.
    return Plan(2, tuple(Window(start, end, 2)
                         for start, end in split_oversized(((1, page_count),), cap)))
```

### 3. Three small edits in the same file

```python
#: Level 2 is a fold at the cap. It is **not** `impl`'s rung: §5.2 deleted section extent from the
#: model, so the carry chain that forced `impl`'s Level 2 to run sequentially has nothing left to
#: carry (§6.2, and fixes/001).
MAX_LADDER_LEVEL = 2
```

```python
    @property
    def parallel(self) -> bool:
        """Always true, at every rung.

        Level 0/1 windows are independent because they cut on the document's own structure, and
        Level 2's are independent because v1's fold has no carry chain. A rung that could not run
        in parallel would be one that had re-introduced extent into the model's schema.
        """
        return True
```

`LadderLevel2Required` — **keep the class.** It becomes unreachable from `plan()`, but
`WindowUnsplittable` inherits from the same `WindowError` family and `cli.py:1806` catches that
family. Amend its docstring to say it is retained for the error taxonomy and is no longer raised,
rather than deleting a code an operator may already be switching on.

---

## Effect

| | before | after |
|---|---|---|
| documents ingestible | 174 / 202 | **202 / 202** |
| pages ingestible | 1,108 / 5,578 (20%) | **5,578 / 5,578** |
| `ETC1AV81` windows | 592 | 20 |
| `TC1E-SF` windows | refuses | **(1,30), (31,55)** |
| corpus windows (approx.) | n/a | ~200 |

The `TC1E-SF` row is exact, and it is the point of the fix: `[[1,30],[31,55]]` is byte-for-byte
what `data/fixtures/TC1E-SF/expected.json` already declares. The normative acceptance table starts
agreeing with the code instead of contradicting it, and U013's re-bill becomes a command.

---

## What breaks

### Six tests in `backend/tests/unit/test_window.py`

All six assert the old refusal, so they are rewrites, not repairs. The refusal was the behaviour;
removing it is the fix.

| test | becomes |
|---|---|
| `test_ladder_level_2_required_when_s1_found_no_chapter` | a 1,440-page document with no chapter folds into 48 Level 2 windows, `covers()` true, `parallel` true |
| `test_ladder_level_2_required_when_one_chapter_is_over_the_cap` | 80 pages / two 40-page chapters -> `[(1,30),(31,40),(41,70),(71,80)]` |
| `test_the_level_two_rung_cannot_be_reached_by_configuration` | rename; assert `MAX_LADDER_LEVEL == 2` and that the fold carries no state between windows |
| `test_level_one_cuts_on_the_chapters_and_covers_the_front_matter` | packing merges (1,14)+(15,28); expect `[(1,28),(29,42)]` |
| `test_a_file_too_large_to_send_whole_leaves_level_zero` | `plan(10, size_bytes=MAX_INLINE_BYTES+1)` no longer raises: `inline_cap` -> 9, so `[(1,9),(10,10)]` |
| `test_the_synthetic_corpus_plans_exactly_three_windows` | see fixtures below |

Add three new ones alongside:

* `test_a_dense_outline_packs_instead_of_billing_one_call_per_page` — 592 one-page chapters -> 20 windows.
* `test_the_pilot_document_folds_into_the_expected_windows` — 55 pages, one chapter -> `[(1,30),(31,55)]`, asserted against `data/fixtures/TC1E-SF/expected.json` rather than a literal.
* `test_every_rung_covers_the_document_exactly_once` — property test over page counts and chapter shapes: `Plan.covers()` holds and no window exceeds the cap.

### One fixture, regenerated at zero spend

`data/fixtures/synthetic_3window/` is keyed by `extract_key`, which is built from each window's
ordered page image hashes. Changing the windowing changes the keys, so replay misses with a typed
`fixture_miss`. Regeneration is free — stub VLM, the U013 recorder:

```bash
export VSIR_FIXTURE=data/fixtures/synthetic_3window
vsir ingest data/source/synthetic_3window.pdf --vlm stub \
  --record data/fixtures/synthetic_3window --until extract
vsir ingest data/source/synthetic_3window.pdf --vlm stub --until stitch   # round-trips
```

Check first whether packing collapses that corpus below three windows. If it does, widen the
generated chapters in `eval/synthetic_pdf.py` so the corpus still exercises three — do not weaken
the packer to preserve a fixture.

`data/fixtures/TC1E-SF/expected.json` needs **no** change.

### Documents to amend

* **Spec §6.2** — the whole "What is excluded, and what it costs" block. Replace with the fold and
  the argument above. Note that its claim about the POC slice was contradicted by
  `data/fixtures/legacy/manifest.json`, which records `TC1E-SF` at `level: 2`.
* **Spec §2.5 B** — strike the Level 2 exclusion; keep the entry, marked superseded, with the
  reason (extent left the schema).
* **§20.1 register, item A6** — the outline is the natural ToC source and is fix 004.
* `development/cr1/progress/implementation-progress.md` — U013's blocker entry: OQ-1 and OQ-2 are
  both closed (the PDF is on this machine, the key is in `.env`); what actually blocked it was this.

---

## Verifying it

```bash
bash scripts/test-unit.sh -k window          # the six rewrites + three new
bash scripts/test-unit.sh                    # 1067 today; expect the same count green
export VSIR_FIXTURE=data/fixtures/synthetic_3window
vsir ingest data/source/synthetic_3window.pdf --vlm stub --until window
```

Then the check that motivated the fix — the corpus sweep, which needs no key and no Qdrant:

```python
# every PDF under the dataset, through the shipped plan()
from vsir.ingest import probe, window
plan = window.plan(p.page_count, toc=toc, size_bytes=p.size_bytes, document=doc_id)
assert plan.covers(p.page_count) and all(w.pages <= 30 for w in plan.windows)
```

Expected: 202 of 202 documents plan, zero refusals, no window over 30 pages, every plan covering
its document exactly once.

---

## Rollback

Single file, no data migration, nothing persisted changes shape. Revert `window.py` and the tests.
Anything already ingested under the new windowing keeps working — `extract_key` is derived from
the pages a window actually covers, so old and new windows simply have different keys and the old
receipts stay valid for the windows that produced them.

## Order

Apply **002** (offset check, two witnesses) and **003** (`label_verified`) first: both are small,
independent of this one, and touch no fixture. This fix is the one with test and fixture churn.
