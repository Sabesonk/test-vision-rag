# Fix 008 — a `sparse_version` change has no supported migration

**Status:** **applied**
**Files:** `backend/vsir/ingest/resparse.py` (new), `backend/vsir/ingest/index.py`,
`backend/vsir/cli.py`; tests `tests/unit/test_resparse.py` (new, 16),
`tests/api/test_resparse_migration.py` (new, 6); `AGENTS.md`. Plus the one pre-existing failure
this uncovered: `backend/vsir/eval/synthetic_pdf.py` and the `ask_vision` replay fixture it
generates (see the last section).
**Spend:** none to apply, and none to run — that is the entire point of it.
**Spec touched:** none. §6.6's refusal is unchanged and this does not weaken it; §15 Factor XII is
what makes the repair a subcommand. **Plan:** §4c **P10**, closed.

---

## What is wrong

`fixes/005` made the sparse recipe client-side and versioned — `SPARSE_VERSION` is the fifth field
of the §6.6 fingerprint — so every collection built before it is refused at boot, on the read path
as well as the write path. That refusal is correct and this fix does not touch it. A BM25
collection and a raw-term-frequency collection are byte-identical in shape, declare the same
`Modifier.IDF`, pass every check in `core/indexed.py`, and differ only in what the stored floats
*mean*; serving one as the other returns worse neighbours and no error.

What was missing is **the other half: a supported way to say yes.**

Without one the only path is delete-and-re-ingest, and that is the wrong price by an order of
magnitude — for a reason that is not visible from the command:

> deleting the collection deletes the **embedding cache** with it.

The cache *is* the index. `index.cached_vectors` reuses a dense vector only from the point already
in the collection (register B5, closed deliberately by adding no state anywhere), so dropping the
collection drops every vector the system could have reused. A change whose entire content is
arithmetic over text that is already stored therefore becomes a **full live re-embed of every
page**. Worse, `VSIR_VLM` selects the embedding backend too (§15 Factor X), so the obvious cheap
move — re-ingest in replay — would overwrite real `gemini-embedding-2` vectors with `stub:` hash
vectors instead. Two documents and 58 pages is pennies. The 208-document corpus is a bill and an
outage.

And §15 Factor XII is explicit that an operational action with no `vsir` subcommand **is not a
supported operation**: no laptop-only script, no live collection surgery. So the state of the
system was that a release could put every collection into a condition the release itself had no
supported way to repair.

## The change

`vsir migrate sparse`, in `ingest/resparse.py`. It scrolls the collection, re-derives both sparse
surfaces from payload that is already stored, writes back **only those two vectors**, and then
restamps the fingerprint.

```bash
vsir migrate sparse --dry-run   # scan and report; writes nothing
vsir migrate sparse             # rebuild, then restamp
```

Nothing is re-embedded, no model is called, no raster is rendered, and the dense vector is never
even fetched — `scroll` names the two sparse surfaces explicitly, which bounds the migration's
memory and makes "did this re-embed anything?" answerable by reading one line.

**It derives the vectors from `index.sparse_vectors`, the function the write path itself calls.**
That function was extracted from `index._vectors` in this change for exactly that purpose. A second
implementation of the same recipe would agree on the day it was written and drift on the day the
recipe changed — which is the only day it is ever used.

### The refusal, which is the part that matters

A migration that rebuilt sparse vectors under *any* fingerprint change would be considerably more
dangerous than no migration at all: it would stamp the new recipe onto a collection whose **dense**
vectors were made by a different model, which is precisely the in-place mix §6.6 forbids, and it
would do so while looking like a repair. So `plan_migration` compares field by field and proceeds
**only** when `sparse_version` is the sole difference:

```
REFUSED  migration_unsupported: this migration rebuilds the sparse surfaces only, and the
fingerprint also differs in ['embed_model'] (embed_model: stored 'gemini-embedding-2' !=
configured 'gemini-embedding-001'). Those fields describe how the **dense** vector was made, and
no stored payload can re-derive one … The remedy for a dense change is unchanged: a NEW
collection, a full re-embed, an alias swap. Nothing was written
```

The message names only the *unrepairable* fields. Naming `sparse_version` alongside them would send
the operator back to the migration that is already refusing them.

Three more refusals, each of them a state that would otherwise be repaired into something worse:

| refusal | why it is not an agreement |
|---|---|
| the fingerprint already matches | rewriting every vector to the value it already holds costs a full pass to achieve nothing, and makes a real migration indistinguishable from a no-op in the logs |
| no fingerprint is recorded | there is no statement of how the vectors were made, so there is nothing to migrate *from*; a collection that merely exists is not evidence about which model made it |
| a payload this release cannot read | one skipped page is a page on the old recipe inside a collection stamped with the new one — the same silent mix, one page wide, and undetectable afterwards because the stamp says it is fine |

### Ordering is the crash-safety argument

The fingerprint point is rewritten **last**, after every page. A kill halfway therefore leaves the
*old* fingerprint over a partly-rebuilt collection: the boot check goes on refusing, nothing serves
a mixed index, and re-running the command repairs it, because deriving a sparse vector from a
payload is idempotent. The other order would publish a collection claiming to be migrated while
half of it was not — the one outcome worse than the refusal this started from.
`test_the_fingerprint_is_written_last` asserts the call order rather than describing it.

### One case that looks like nothing to do

`update_vectors` has no way to express removal, and an omitted name means *leave it alone*. So a
surface that had a vector and whose source text the new recipe scores no terms for is deleted
explicitly, not skipped — otherwise a vector built by the old recipe would be stranded on the one
page where the migration appeared to have no work.

## What breaks

- **Nothing on the wire.** No response model, no envelope, no frontend type, no spec section.
  `_vectors` is a pure refactor: the points step 10 writes are byte-identical.
- **No invariant, cap or refusal is weakened.** §6.6 still refuses; this adds the supported way to
  stop being refused, and refuses itself in every case where stopping would be wrong.
- `index.sparse_vectors` is new public API on a module that had `build_point` as its only vector
  entry point.

## Verifying it

```bash
bash scripts/test-unit.sh     # L0/L1 + the §12.5 conformance greps
bash scripts/test-api.sh      # L2/L3, including tests/api/test_resparse_migration.py
```

The unit suite is mostly about what was **not** written and in what order — a fake store is a
better witness to both than a container. The L2 suite covers the four things only Qdrant can
vouch for: that `update_vectors` **replaces** a named sparse vector rather than merging into it
(a merge would leave every weight too large by exactly the old raw count, and no assertion about
our own code could find that), that `delete_vectors` really removes one and the point survives,
that the dense vector and the payload come through untouched, and the round trip itself — refused
at boot, migrated, accepted.

The demo is that round trip, against a real 31-point collection seeded in the pre-`fixes/005`
state:

```
── vsir doctor (before) ──
"failed_checks": ["collection_fingerprint"] · "differences":
    {"sparse_version": ["raw-term-frequency", "bm25-v1"]}

── vsir migrate sparse ──
recipe       sparse_version 'raw-term-frequency' -> 'bm25-v1'
             (fingerprint b32e867dc83e61c3 -> 22877f531eec095d)
scanned      31 point(s)
rebuilt      31 point(s): 30 lexical, 30 captions
spend        none: both surfaces are a pure function of the stored payload, so no model was
             called and no dense vector was read or rewritten

── vsir doctor (after) ──       exit 0
── vsir migrate sparse (again) ──
REFUSED  migration_unsupported: the stored fingerprint already matches this release
```

## Rollback

Revert the commit. The subcommand disappears; nothing else does, because `_vectors` delegating to
`sparse_vectors` produces the same points either way. A collection already migrated stays migrated
and stays servable — its vectors are what this release's ingest would have written.

## What this does not fix

**A migration for a `composition_version`, `embed_model`, `dim` or `distance` change is still
absent, and is a different problem.** Those cannot be re-derived from payload at any price; the
remedy stays a new collection, a full re-embed and an alias swap. What is missing there is not
arithmetic but an **alias**, so the swap can happen without a window where nothing answers — and
`config.pages_collection` is a computed name, not an alias, today. Not recorded as a new defect
because §6.6 already prescribes that path; recorded here because the shape of this fix might
otherwise read as a promise about the other four fields.

## One pre-existing failure this uncovered, and fixed

Running the full L2 suite for this change found **five failures that had nothing to do with it** —
confirmed pre-existing by stashing this work and reproducing them at `c2d5645`. All five were one
cause, and it was `fixes/005` catching up with a corner of the replay corpus four suites away.

`synthetic_pdf.py`'s `ask_vision` entry freezes Loop 5's escalation to the two image-only pages,
and the loop takes their **order from the `skim_pages` ranking**. §6.3 makes page order an input to
`read_key` — deliberately, because a model shown the same sheets in a different order is being
asked a different question. BM25 flipped the ranking, the loop asked `(1, 2)` where the frozen
response was keyed on `(2, 1)`, and all five tests that reach the vision escalation — across
`test_ask_near_miss.py`, `test_ask_replay.py` and `test_correction_loops.py` — stopped with
`fixture_miss`.

That is **D10 working**: a miss is typed and replay never invents a response or makes a live call.
The repair is at the source — the `pages` tuple in the generator's spec table, its prose reordered
to match, `python -m vsir.eval.synthetic_pdf --vlm-model gemini-3.8-flash --prompt-version s2-v1`,
and the `expected.json` row it regenerates. Every other key came back byte-identical, which is what
confirms the pins were right.

Two things worth keeping:

- **The generator does not prune.** The superseded `(2, 1)` fixture stayed on disk, unreferenced,
  and had to be deleted by hand. A stale frozen response that nothing asks for is harmless; one
  that something *starts* asking for again is not.
- **Regenerating with the wrong pins re-keys everything, silently.** `.env` carries
  `VSIR_PROMPT_VERSION=s2-v2` while the committed corpus is `s2-v1`, so the first regeneration
  produced a complete parallel fixture set beside the real one and reported success. Pass the pins
  explicitly.

Recorded as plan §4c **P12**. Making Loop 5 order its escalation set by page rather than by rank
would make the call stable under any future ranking change — that is a behaviour change to the
answer loop, so it is the owner's call rather than this fix's.
