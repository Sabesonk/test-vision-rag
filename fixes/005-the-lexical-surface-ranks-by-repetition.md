# Fix 005 — the lexical surface ranks by repetition, not by relevance

**Status:** **applied**
**Files:** `backend/vsir/ingest/sparse.py` (rewritten), `ingest/index.py`, `ingest/fingerprint.py`,
`serve/tools/skim.py`, `core/indexed.py`, `config.py`; tests `test_sparse.py`, `test_fingerprint.py`,
`test_doctor.py`, `tests/api/test_indexed_collection.py`, `tests/api/conftest.py`
**Spend:** none to apply. No re-embedding — the dense vectors are untouched. But **every existing
collection is refused at boot**; see *Migration*.
**Spec touched:** §2.4 (`app/sparse.py` — *port as-is*), §5.3, §6.6, D2. Spec corrections **C16**
and **C17** carry the change; nothing here was decided against the spec without amending it.

---

## What is wrong

The `lexical` and `captions` surfaces stored **raw term counts** and let Qdrant's `Modifier.IDF`
supply the rest. IDF is one of BM25's three factors. The other two — term-frequency **saturation**
and **length normalisation** — were absent, so within one page the score rose *linearly and without
bound* with repetition, and a long page was never penalised for being long.

That is not a subtle degradation. It is the wrong page, and the branch cannot be re-weighted out of
it because the defect is inside the branch's own arithmetic.

### The measurement

The one real ingest the project has — `SICK-DETECTOR-BOX@3.0`, the UE410 operating instructions,
56 pages, frozen under `data/fixtures/live/` — scored against the query
*"Safeguard Detector individual sensors"*, using the shipped `vsir.core.tok.tok` and Qdrant's own
IDF formula `ln(1 + (N − n + 0.5) / (n + 0.5))`:

| weighting | rank of page 46 | top five |
|---|---|---|
| **raw term frequency** (as shipped) | **9th** | 17, 11, 29, 14, 22 |
| saturation only (`b = 0`) | 3rd | 11, 22, 46, 17, 29 |
| length normalisation only | 5th | 17, 11, 14, 29, 46 |
| **BM25 tf component** (this fix) | **2nd** | 11, **46**, 22, 17, 14 |

Page 46 is 1,390 characters, 254 tokens, and is the **only page in the document that prints
`individual sensors` at all**. The pages that beat it print `sensors` 13, 9, 9 and 8 times and do
not contain the phrase. `individual` carries idf 2.79 against `sensors`' 0.693 — the rare term was
already weighted four times heavier, and it still lost, because thirteen linear occurrences of a
common word on a 256-token page outscore one occurrence of a rare one.

Both halves are load-bearing: neither alone puts the page where it belongs, which is why `k1` and
`b` are both pinned and both asserted.

### Why it was never caught

Every sparse assertion in the suite was about **shape** — indices sorted, values positive, the
tokenizer agreeing with the phrase index, `Modifier.IDF` declared on the collection. Not one was
about **order**. A ranking defect is invisible to a suite that never ranks two pages against each
other, and the fixture corpora could not have shown it anyway: `synthetic_pages` is 30 hand-written
pages of roughly equal length with no repetition to exploit.

## Why raw counts were chosen, and what survives

The original module's reasoning is quoted in its own docstring and the operative half of it is
correct:

> Qdrant's `Modifier.IDF` computes inverse document frequency across the collection **at query
> time**, so we never hold a corpus statistic ourselves. Otherwise ingesting one new document
> shifts the IDF of every term and silently stales every sparse vector already in the index.

**That property is preserved exactly.** The document side now stores

```
value(t, D) = tf(t,D) · (k1 + 1) / (tf(t,D) + k1 · (1 − b + b · |D| / avg_len))
```

and ingesting a document still changes **no stored value**, because `|D|` is a property of the
document itself and `avg_len` is a **released pin**, not a live measurement. The idf factor is
still never computed locally — `Modifier.IDF` stays mandatory, and `core/indexed.py` still refuses
a collection that does not declare it.

What is given up is that a pin drifts from the corpus it describes as the corpus grows. The drift
is bounded (it moves every weight in the same direction and the length penalty stays monotone), it
is visible in `config.py`, and correcting it is a release rather than a hot edit — which is the
same bargain `COMPOSITION_VERSION` already makes for the dense side.

## The change

1. **`sparse.build()` is gone**, replaced by two names that cannot be confused:
   - `build_document(text, *, avg_len)` — BM25's tf component. `avg_len` is keyword-only with **no
     default**, because the two surfaces are an order of magnitude apart in document length and a
     default would let a caller weight captions against the lexical statistic without saying so.
   - `build_query(text)` — **1.0 per distinct term**. Qdrant scores `Σ idf(t)·q(t)·d(t)`, so with
     `q(t) = 1` what it computes *is* BM25, checkable against the literature in one line.

   A surviving `build()` would be a correctly-spelled function that silently produces the defect
   above: a query built with document weights applies `k1` twice, a document built with query
   weights loses saturation, and **both mistakes present identically — as worse neighbours**. A
   stale call site should be an `AttributeError`, not a wrong float in a vector. One test asserts
   the name is absent.

2. **Colliding slots sum their saturated weights, not their counts.** Two distinct terms sharing a
   blake2b slot are two terms, each saturating on its own; adding the counts first would treat them
   as one term with `tf₁ + tf₂` and over-saturate the pair.

3. **Four pinned parameters in `config.py`.** `k1 = 1.2` and `b = 0.75` are BM25's canonical values
   and Qdrant's own defaults. `avg_len` is per surface — 256.0 tokens for `lexical`, 16.0 for
   `captions` — and is the one number that is an observation rather than a convention.

4. **`avg_len = 0` is refused with a named error** rather than dividing by it. Unchecked it is a
   `ZeroDivisionError` in step 10 — *after* the S2 spend and after every embedding has been bought.

5. **`sparse_version` is the fifth fingerprint field (§6.6).** This is the part that matters
   operationally. A BM25 collection and a raw-term-frequency collection are byte-identical in
   shape, declare the same `Modifier.IDF`, and pass every schema check in `core/indexed.py` — they
   differ only in *what the stored floats mean*. A process configured for one and serving the other
   returns worse neighbours and no error, which is precisely the silent failure the fingerprint
   exists to prevent. Without the field, this fix would itself become a §6.6-class defect.

### How the two `avg_len` figures are evidenced, and how well

Both come from `data/fixtures/live/`, the frozen receipts of the only real ingest — and they are
**not equally well evidenced**, which the constant's comment now says out loud:

| | measured | n | pin |
|---|---|---|---|
| `lexical` | SICK mean 260 / median 231; BES mean 215 | 58 pages | 256.0 |
| `captions` | 10 and 15 tokens after `dedupe` | **2 pages** | 16.0 |

The captions pin rounds **up** from what those two pages measure, deliberately: under-penalising
length on a surface already weighted 0.4 costs recall it was added to provide, while
over-penalising it silently removes the channel — and `captions` was the surface that in `impl`
never had content at all (D2). Two pages is thin and the pin should be revisited as a release when
a larger paid ingest lands.

For contrast, the hand-written `synthetic_pages` captions measure mean 4.9 / median 4, and the
synthetic S2 receipts measure 38–56 tokens **before** `dedupe`. Neither is evidence about
production: one is fixture prose, the other is not what the surface indexes.

## Migration

**The fingerprint refuses every collection written before this fix**, on the read path as well as
the write path — `ingest/fingerprint.require` guards the upsert, and `doctor.check_collection_fingerprint`
fails `/ready` for a process that only serves. That is F11 working as designed: the alternative is
a process embedding queries under one recipe against vectors built under another, whose only
symptom is worse neighbours, which is indistinguishable from a thin corpus.

The refusal names `sparse_version` and both values, so the message is actionable.

**For every fixture corpus this costs nothing**: re-create the collection and re-ingest under
`VSIR_VLM=stub` + `VSIR_FIXTURE=…` (D10), no model call.

**For the one live collection it is not free, and not for the reason it looks like.** The S2
receipts replay from `data/fixtures/live/` for nothing — but `VSIR_VLM` selects the *embedding*
backend too (§15 Factor X), so a replay re-ingest would overwrite real `gemini-embedding-2`
vectors with `stub:` hash vectors. And there is no embedding cache outside the collection itself:
`embed_document` reuses a vector only from the point already in the index, so deleting the
collection deletes the cache and the re-embed is a live call. Two documents and 58 pages is
pennies; at corpus scale it is not.

The cheap path exists and is not built: both sparse surfaces are derived **entirely from payload
already stored** — `text`, and `summaries[] + topics` through `dedupe` — so they can be recomputed
with no model call and no re-embed at all: scroll the collection, rebuild the two sparse vectors,
`update_vectors`, then rewrite the fingerprint point. That is a `vsir` subcommand nobody has
written, and §15 Factor XII means an operational action without one **is not supported** — no
laptop-only script, no live collection surgery. Recorded as plan **§4c P10** rather than invented
here.

## What breaks

- **Four test files**, all updated in this change; `test_sparse.py` grew from 9 assertions about
  shape to 19 that include order.
- **Two docstrings in the API layer** that described the stored values as raw counts. The
  assertions were about `Modifier.IDF` and still hold.
- **No frontend, wire-contract or envelope change.** No response model gains or loses a field; RRF
  is still ranks-only, so no similarity value is computed, stored or returned (§7.6).

## Verifying it

```bash
bash scripts/test-unit.sh        # L0/L1 + the §12.5 conformance greps
bash scripts/test-api.sh         # L2/L3 — the collection, the fingerprint gate, the rungs
```

The ranking measurement is `backend/tests/unit/test_sparse.py::test_the_page_that_prints_the_phrase_loses_to_pages_that_repeat_a_common_word`.
It carries the document as a table of per-page term counts rather than as text, because the S2
receipts it was derived from are a paid artefact and are not in the repository. To re-derive the
table from a `text.json` receipt:

```bash
backend/.venv/bin/python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "backend")
from vsir.core.tok import tok
pages = json.loads(pathlib.Path(
    "data/fixtures/live/SICK-DETECTOR-BOX@3.0/text.json").read_text())["pages"]
for p in pages:
    t = tok(p["text"])
    print((p["page_no"], len(t), t.count("safeguard"), t.count("individual"),
           t.count("sensors")))
PY
```

## Rollback

Revert the six source files and bump `SPARSE_VERSION` back to a value naming raw counts (**not**
by deleting the field — deleting it would make the collections written under this fix
indistinguishable again). The rewrite is confined to `sparse.py`'s two builders and their three
call sites; nothing else reads a sparse value.
