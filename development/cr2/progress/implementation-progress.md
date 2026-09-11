# CR2 Implementation Progress — `POST /search`, the flat retrieval surface

**Spec:** `development/cr2/spec/spec.md`
**Plan:** `development/cr2/plan/cr2-implementation-plan.md`
**Branch:** `feat/search-surface-and-document-store`
**Release tag:** (pending — set when S4 and S5 close)

## Rollup

| | |
|---|---|
| **Complete** | **4 / 7 units (57%)** — U033, U034, U035, U036, all shipped 2026-09-11 in `c1d3100`, **before this CR existed** |
| **Current milestone** | **S3 is closed.** The surface, its keyword filters, the operator's view of both, and the document store on the host are all in and green. **S4 has not started** |
| **Latest** | **The CR itself.** This document set was written on 2026-09-11 from the shipped code, because the search surface had no spec, no plan and no progress entry — the code was the only description of it. Every claim in the spec is marked *as-built* (a named test asserts it) or *required* (nothing does), so a reader can tell evidence from intent |
| **Next unit** | **U037 — `vsir search` on the CLI.** Not a convenience: CR1 §4.4 makes the `vsir` CLI *the only supported operational surface*, and the newest surface in the service has no subcommand. By CR1's own definition `/search` is unsupported today, and an operator's only path to it is `curl` with a body containing `@` and `#` |
| **Then** | U038 (a Playwright spec over the Search tab — the 38 console tests are Python assertions over HTML, not a browser) and U039 (`vsir eval search`, gated by CR1 OQ-1) |
| **Read first** | **Spec §7.2 — what the 56 tests do *not* cover**, and §2.4 on why this CR is retrospective |
| **Blocked** | **U039** on CR1 OQ-1 — `data/source/TC1E-SF.pdf` is still absent, so the real-corpus exclusion rate cannot be measured. The arithmetic can still ship against the synthetic set |
| **Not this CR's** | `test_resume.py` fails 5 tests on this branch and did so **before** the seed commit — its fixture deletes the collection its own subprocess ingest created. That file and the 150-page `synthetic_large` corpus are CR1 U025's work, and nothing here touches ingest |

---

## Running what exists

```bash
bash scripts/stack.sh up          # Qdrant, the collection, the API, a seeded document
open http://localhost:8055/console   # → the Search tab
ls var/documents                  # the ingested PDFs, on the host, since U035
```

```bash
# the surface itself, one free call
curl -s -X POST http://localhost:8055/search \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"safety output","limit":2,"include":["summary","codes"]}'
```

| | |
|---|---|
| The surface | `POST /search` — bearer, free of a vision call, absent from MCP |
| The operator's view | <http://localhost:8055/console> → **Search** |
| The published contract | <http://localhost:8055/docs> → `POST /search`, four named examples |
| The CLI | **none — U037** |

---

## Units

<!-- Format:
  - [ ] U0nn Not started
  - [~] U0nn In progress
  - [x] U0nn Complete
  - [!] U0nn Blocked — reason -->

### S1 — the flat surface (spend: none¹)
- [x] U033 `POST /search` — the flat surface: typed status, row content, assembled operations

### S2 — keyword filters (spend: none¹)
- [x] U034 `require_phrases` / `exclude_phrases` through the one exact path, and the branch filter

### S3 — the operator's view and the store (spend: none)
- [x] U035 The document store on the host — `VSIR_DOCUMENTS_DIR`, and a wipe that takes both
- [x] U036 The console's Search tab — **S3 closes here**

### S4 — the supported operational surface (spend: none¹)
- [ ] U037 `vsir search` on the CLI — **next; CR1 §4.4 is violated until it lands**

### S5 — the consumer's proof (spend: none)
- [ ] U038 `e2e/tests/search.spec.ts` — the tab under a browser
- [!] U039 `vsir eval search` — blocked on CR1 OQ-1 for the real numbers; the arithmetic is not

¹ No **vision** call. A text query embeds through the embedding model on every request, exactly as
every `skim_*` rung does (Spec D-S10). There is no release in which this surface makes no provider
call at all.

---

## Unit detail

### U033 — `POST /search`: the flat surface

**Milestone:** S1 · **Spend:** none¹ · **Status:** `[x]` Complete · **Completed:** 2026-09-11

The service had eight tools and no way to be used as a search engine. The ladder is the right
surface for an agent that is *deciding* — `skim_documents` → `skim_sections` → `skim_pages` →
`fetch`, each rung a named move — and it charges the caller **one inference turn per rung**. For a
consuming system that has already decided it will reason for itself, every one of those turns is
waste: it wants the ranked pages and their content, in one call, and its own reasoning after that.

So `/search` collapses the ladder into one free request. What it does **not** collapse is the
honesty of the row, and that is the whole of the design:

**`status` is the field to branch on, and it is not a second opinion.** It comes from
`lookup.absence()` — the same function the three `skim_*` rungs call. An empty `rows` was otherwise
indistinguishable from an unsearchable scope, which is exactly how a consumer reports *"not in the
documents"* about a page nobody could read (CR1 §7.1, F4). `test_the_absence_rule_is_the_one_the_rungs_use`
pins the agreement rather than the code path, so the two cannot drift apart quietly.

**`query_interpretation` explains the row set.** A caller sends one string and the service splits
it in two before anything is retrieved: `"reset K158"` becomes the phrase filter `K158` — an exact
match over the one code path, so only pages that print it can rank at all — and the prose `reset`,
which is what reaches the embedding. A consumer that cannot see the split cannot tell a scoping
result from a semantic one and will misreport both. Every branch that did **not** run says why
(`weighted_zero`, `nothing_left_to_embed`, `no_query_text`), because *"why didn't it find X?"* is
most often answered by *"the branch that would have found it never ran"*.

**Content is served here though a `skim_*` row withholds it**, and the reason the two differ is
not a relaxation. **P2** — *cheap to triage, expensive to consume* (CR1 §7.1) — keeps page text off a triage row so an agent cannot answer from a search
result instead of choosing a page and paying for it. A caller on this path has declared it is
doing its own reasoning; withholding the text would not make it safer — it would make it call
`fetch` twenty-five times for the same bytes. The bound that remains is **size, not trust**:
`text_chars` caps each row and `text_truncated` says when it cut.

**Every field is `null` unless it was requested.** `text: ""` means the extraction is empty —
which on a scanned page means nobody could read it — and `text: null` means you did not ask. One
falsy default for both is how a consuming system concludes a page is blank.

**`text_usable` is the single flag to gate on**, and it is deliberately **not** `has_text`: an
`untrusted` page *has* text and the text may not be believed. A consumer that composes from
`content.text` without checking it produces a confident wrong part number on exactly the documents
this corpus is hardest about.

**Codes are claims, not verdicts.** `content.codes` is what the model reported, verbatim;
`codes_in_text` is the subset the page's own extraction backs, lowercased and whitespace-collapsed
because that is the form membership was decided in — so **compare them case-insensitively**, or
the comparison finds nothing and reads as *"the text backs none of these codes"*. `verify` settles
a code, and it is free.

**There is no score, and that is not an oversight to be corrected later.** `rank` is an ordinal,
`surface_ranks` publishes each branch's own position (*dense put it 4th, lexical 35th, captions
never found it*) and `best_rank` the best of them. `_total()`'s RRF magnitude stays private in
`skim.py`. A magnitude invites a threshold, a threshold turns *"ranked ninth"* into *"no results"*,
and a fabricated absence is the one failure this system exists to prevent. The conformance grep
fails the build on a field named `score`.

**The operations on each row are assembled, not described.** A `page_id` carries `@` and `#`, so a
consumer that composes its own body eventually encodes one wrong and gets a request that is
well-formed, addresses nothing, and comes back looking like an empty result rather than a client
bug. `spends` is true on exactly one — `comprehend` — so the paid step is never reached by
accident. `expand_section` is omitted when there is no query text to carry, because an affordance
whose whole promise is *"post this verbatim"* must not hand back a body that 400s.

**Why it is not a ninth tool.** CR1 §7.2 fixes the agent's surface at eight, and the eight are
*moves*. An agent choosing among nine where one of them is "the same search, but with the lexical
branch turned off" is being offered a knob. Neither of this surface's consumers is choosing a
move — the operator is turning a knob, and the search-engine caller is not using the ladder at
all. So it is off the tool table, absent from MCP, and free.

**Demo evidence** (the dev stack, 2026-09-11, 144 pages seeded):

```
POST /search {"query":"safety output","limit":2,"include":["summary","codes"]}
  status  ok      total 144   returned 2   available 90
  pages_searched 144   searchable_pages 138   pages_without_text 4
  branches_run  ["captions","lexical","dense"]
  row 1  CELL-B-BINDER@1.0#p032  printed "30"  why ["dense","lexical"]
         surface_ranks {"dense":4,"lexical":35}   text_trust ok   text_usable true

POST /search {"scope":{"doc_id":"NO-SUCH-DOC"}}     -> out_of_scope   pages_searched 0
POST /search {"limit":100}                          -> HTTP 400 limit_out_of_range
```

**Tests** — `backend/tests/api/test_search_surface.py`, **56 passed** (verified 2026-09-11 against
the test stack):

```
bash scripts/test-api.sh -k search_surface   ->  56 passed in 10.75s
```

They pin, in groups: ordinals and the absent score · the content parts and their null discipline ·
trust and truncation · paging determinism and `available` · page ranges and negations · every
refusal code · the status rule shared with the rungs · the interpretation and the skipped branches
· typed section rows · the published schema and its four named examples · row identity, thumbnails
and `next` · and the assembled actions actually being accepted by the surfaces they target.

**Invariants closed:** I-S1, I-S2, I-S4, I-S5, I-S6, I-S7. **Failure rows closed:** FS1, FS2,
FS4–FS10.

---

### U034 — Keyword filters, and the filter that is not a scope

**Milestone:** S2 · **Spend:** none¹ · **Status:** `[x]` Complete · **Completed:** 2026-09-11

`require_phrases` and `exclude_phrases` require or forbid a phrase being **printed on the page**,
through the same exact-match path as `lookup` — so `variants()` applies (`"SF 1.1A"` finds
`"SF1.1A"`), matching is phrase matching (`"safety output"` needs those words adjacent and in that
order), and there is no second matcher anywhere in `serve/` (CR1 I3, F1). Each term becomes one
nested `exact_filter`; the terms are ANDed by being separate conditions. Assembling `MatchPhrase`
here instead would have been a place where a spelling could be forgotten — and a forgotten
spelling is a page that silently stops being findable by a filter that looks like it worked.

**The finding that shaped the unit: a content filter is not a scope.** The first implementation
routed the phrase conditions through the scope filter, and an unmatched filter therefore came back
`out_of_scope` — which tells the caller to *widen the scope*, when the scope was never the problem
and the corpus had in fact been searched. Hence `_candidates`' new `branch_must` / `branch_must_not`,
deliberately distinct from `extra_must` / `extra_must_not`: a page range and a negated facet change
which pages were ever candidates and belong in the denominator; a required phrase does not.

```
POST /search {"query":"safety output","require_phrases":["zzz-not-printed-anywhere"]}
  -> not_found   pages_searched 144   searchable_pages 138     (not out_of_scope)
```

**The asymmetry with unreadable pages is deliberate, and both halves are the safe direction.** A
page with no text layer carries nothing for a phrase to match, so `require_phrases` **excludes** it
— silently, because it was never a candidate. The same page is **kept** by `exclude_phrases`,
because it cannot be shown to carry the phrase. A requirement never claims a page qualifies on
evidence nobody could read; an exclusion errs toward showing you a page you may not want.

That silence is what makes the disclosure mandatory rather than decorative: `pages_searched`,
`searchable_pages` and `pages_without_text` are on every response, and a large gap between the
first two is the reason an empty keyword result must not be read as *"the corpus does not contain
this"*. It is the same disclosure the evaluation sets depend on, applied to a filter that can
quietly remove half a scanned binder.

Bounds: ten terms (`too_many_phrase_terms`, refused not truncated — past ten a caller is writing a
query, and `query` is the parameter for that), and an empty term is `phrase_empty` rather than
dropped, because a caller that sent `["", "safety"]` and got the results of `["safety"]` was
filtered on something it did not ask for.

**Tests** — 11 of the 56, including phrase-vs-loose-token semantics, the `variants()` spellings,
the unreadable-page exclusion, requiring and excluding the same phrase, and an assertion that the
filters reach the index through `core/exact` and nowhere else.

**Invariants closed:** I-S3, I-S8. **Failure rows closed:** FS3, FS11.

---

### U035 — The document store on the host

**Milestone:** S3 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-11

**Nothing was ever baked into the image** — the build context is `backend/`, so `data/` is
unreachable at build time, and CR1 U029 already kept the source PDFs outside it. What changed here
is only *where that store lives*: it was a **named** volume, which on macOS and Windows sits inside
the Docker VM, so *"where did my document go?"* had no answer a person could `ls` and replacing a
corrupt PDF meant a round trip through `docker cp`.

It is now `${VSIR_DOCUMENTS_DIR:-./var/documents}`, bind-mounted at `/srv/documents`, git-ignored,
and documented in `.env.example` with the one Linux caveat that matters (the image `chown`s
`/srv/documents` at build, a bind mount shadows that, so `sudo chown -R 10001:10001 var/documents`
once).

**`stack.sh down --wipe` empties it in the same breath as it drops the index.** `down -v` no longer
reaches a host directory, and a wipe that took the index and left the documents would leave a store
describing a corpus that is no longer indexed — every `page_id` in it unresolvable, and nothing
saying why. `find "$documents" -mindepth 1 -delete` keeps `rm` off the mount point itself, because
the compose mount expects the directory to exist.

**Page rasters are still never persisted** (CR1 §4.2) — there were no image files to move.

**Failure row closed:** FS13.

---

### U036 — The console's Search tab

**Milestone:** S3 · **Spend:** none · **Status:** `[x]` Complete · **Completed:** 2026-09-11

The console generates every tool form from `/openapi.json` and writes none of them out by hand —
that is the load-bearing decision in the file, and it is why a parameter added to a tool appears in
the UI with its documentation, having been typed nowhere but `serve/inputs.py`.

**The Search tab is the deliberate exception.** `/search` is not a tool, so it is not choosing a
move and a generated form would be the wrong shape for it: what an operator wants here is content
toggles, a page-range pair and the fusion's weights, laid out for somebody turning a knob. So its
parameter names *are* written in this file — and because they are, `test_console.py` pins the one
list that could silently fall behind (`const PARTS` against `retrieval.PARTS`). The block that
draws it sits **below** the API section, so the scan that keeps that section's promise is not
looking at honest literals inside this one.

What it shows: the status and the next action it implies, the interpretation panel, per-row
thumbnails fetched with the bearer token an `<img>` tag cannot carry, click-to-expand row detail,
the assembled operations with the billing one marked, and a scope builder whose keys come from
`/openapi.json` — so the page cannot offer a facet the server would refuse.

It is still **one free path** (`auth.CONSOLE_PATHS`), which is a security property rather than a
preference: a build step would produce a bundle, a bundle needs a free path per asset, and every
one of those is a line in the unauthenticated surface.

**Tests** — `backend/tests/api/test_console.py`, **38 passed** (18 added here; verified 2026-09-11).

**Failure row closed:** FS12.

---

### U037 — `vsir search` on the CLI

**Milestone:** S4 · **Spend:** none¹ · **Status:** `[ ]` Not started

**This is the open finding that matters most in this CR.** CR1 §4.4 and §15 Factor XII say the
`vsir` CLI is *the only supported operational surface* — *"a corrective action that cannot be
expressed as a `vsir` subcommand is not a supported operation"*. `/search` has no subcommand. The
newest surface in the service is, by CR1's own definition, unsupported, and an operator's only path
to it is a hand-written `curl` body containing `@` and `#`.

The unit is small and its shape is fixed by register **E1**: the subcommand builds a
`SearchRequest` and nothing else — no second assembly of the filter, no second validator — and a
parity test asserts the CLI and the HTTP body return the same rows for the same arguments. The
typed status must be **printed**, not rendered as a blank table: a CLI that prints nothing for four
different facts is the terminal's version of the empty list this whole surface exists to abolish.

Plan §4 U037 carries the full requirement list.

---

### U038 — The Search tab under a browser

**Milestone:** S5 · **Spend:** none · **Status:** `[ ]` Not started

`e2e/` has no spec that opens the Search tab. The 38 console tests are Python assertions over
served HTML — they prove the markup contains what it should, not that a browser renders a typed
absence with its next action or that a clicked operation works. U024's Playwright replay suite is
where that proof belongs, and it spends nothing.

---

### U039 — `vsir eval search`

**Milestone:** S5 · **Spend:** none · **Status:** `[!]` Blocked — CR1 OQ-1

Two properties are asserted today and neither is measured: that `/search` agrees with `skim_pages`,
and what the keyword filters' unreadable-page exclusion actually costs. The second is the number
Spec §4.4's disclosure exists to make visible, and nothing states it.

Blocked only for the **real** numbers: `data/source/TC1E-SF.pdf` is still absent (CR1 OQ-1). The
arithmetic can ship against the synthetic ground-truth set, and must carry CR1 U026's finding
verbatim — **`0/0` is `None` and a named skip, never `1.00`**, because a zero denominator is the
one accident that turns an absent corpus into a perfect safety score.

---

## Defects found while writing this CR

Neither breaks a build; both mislead somebody who trusts the output.

| # | Defect | Unit | Why it matters |
|---|---|---|---|
| **P-S1** | **A `/search` bound violation names a surface the caller never called.** `limit: 100` is refused `limit_out_of_range` with the detail *"skim_pages returns between 1 and 25 rows, got 100"* — `validate_skim_limit` is shared with the rungs and its message is written for them | U033 | The code is right and actionable; the message sends an integrator reading it to `skim_pages`'s documentation for a parameter of `/search`. One string, and the shared validator needs the surface's name passed in |
| **P-S2** | **`MAX_OFFSET` is 200 while the candidate pool cannot exceed 150.** Three branches at `BRANCH_DEPTH = 50` fuse at most 150 distinct pages, so offsets 151–200 are always empty and are accepted rather than refused | U033 | Harmless today because `available` reports the true edge on every response — but the bound's own argument is that *"an offset past the pool can only return nothing"*, and one stretch of the accepted range does exactly that. Tracked as OQ-S2 rather than fixed blind: lowering it is a published-contract change |

---

## Notes

### Why this CR is retrospective
The code shipped on 2026-09-11 in `c1d3100`, on a branch, with no CR describing it. The spec, plan
and this record were written **from** the implementation the same day. Spec §2.4 marks every
normative statement *as-built* (a named test asserts it) or *required* (nothing does) so the
document cannot be mistaken for intent. Plan §1.3 does the same for the units.

### What this CR depends on and does not claim
`found_only_in_superseded` on `/search` works through `envelope.SupersededIn`,
`lookup.absence(..., superseded=)` and `Candidates.superseded` — all three from **CR1 U025**'s
revision work, written in a parallel worktree. `/search` consumes them and built none of them. That
is also why the seed commit is a branch and not `main`: the two changes were not separable in the
working tree, and committing the search surface alone would not have imported.

### Suite state on this branch
`test_search_surface.py` 56 passed · `test_console.py` 38 passed (both verified 2026-09-11).
`test_resume.py` fails 5 tests and **did so before the seed commit** — its fixture deletes the
collection its own subprocess ingest created. That file and the 150-page `synthetic_large` corpus
are CR1 U025's unfinished work; nothing in this CR touches ingest.
