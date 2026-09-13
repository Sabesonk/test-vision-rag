---
type: concept
title: Exact Match and Claim Verification
description: The single exact-match code path — tokenisation mirroring Qdrant's WORD tokenizer, three re-spaced variants, phrase filtering — and the per-(claim, page) verification built on it, with its three verdicts and the bounded present_instead disclosure.
tags: [exact-match, verification, tokenisation, phrase-matching, safety, claims]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-85164da3eb010b967e464903
    resource: repo://backend/tests/unit/test_conformance.py
  - id: openwiki-source-a8cfdf20d05f39a50f004d5a
    resource: repo://backend/tests/unit/test_lookup_pure.py
  - id: openwiki-source-0ded9589ef26f8e328d2b12f
    resource: repo://backend/vsir/core/exact.py
  - id: openwiki-source-f25628da05c2500c892a2b88
    resource: repo://backend/vsir/core/nearmiss.py
  - id: openwiki-source-c1d8da07657b39c62509e79c
    resource: repo://backend/vsir/core/observed_tokens.py
  - id: openwiki-source-2502819f8cf1ad33bfcbbc50
    resource: repo://backend/vsir/core/present_instead.py
  - id: openwiki-source-7ef2725b83a26a39decf7ac6
    resource: repo://backend/vsir/core/tok.py
  - id: openwiki-source-ae74d37101b9e4a33ec059ec
    resource: repo://backend/vsir/core/variants.py
  - id: openwiki-source-8533f6dff657a731a610e1bf
    resource: repo://backend/vsir/core/verify.py
  - id: openwiki-source-46bbcaacf27e1545d30fd654
    resource: repo://backend/vsir/serve/tools/lookup.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Exact Match and Claim Verification

The product guarantee is negative: *a code this service returns is a code printed on the
page.* That is made structural by funnelling everything about exactness through one
function, and by making fuzzy matching impossible rather than discouraged.

## One code path

`exact_filter()` is the only exact-match code path in the codebase. `lookup` uses it,
`verify` uses it, the answer gate uses it through `verify`, and the ingest-time
`codes_in_text` derivation asks the same question of the same index. One code path means
the tool that *found* a page and the check that *confirms* it cannot disagree.

The filter it builds is a disjunction over spellings:

```
should[ must[ MatchPhrase(field, spelling), *scope ] ] for spelling in variants(label)
```

`field` is one of the two text surfaces. `text` is verified by construction — only the
ingest probe writes it — while `vlm_codes` is the opt-in surface whose hits are permanently
unverified. Same code path, same phrase semantics, different trust, expressed as a parameter
rather than a second function so it cannot drift into one.

`is_current` is deliberately *not* added here: each tool injects it server-side, and burying
it in the filter builder would hide it from the one place a reader needs to see it.

### Phrase, not token match

`MatchPhrase` requires the tokens in order and contiguous. `MatchText` would match `sf` and
`1` in any order, so `"SF 1.1A"` would return every page mentioning safety functions — not a
slow path but a wrong answer. `MatchText` and `MatchTextAny` are therefore banned under
`serve/` by a conformance grep.

### Variants, not fuzz

`variants()` returns at most three spellings of the *same characters*: the label as given
with whitespace collapsed, the label with all whitespace removed, and the whitespace-free
form re-spaced at every letter↔digit boundary. `SF 1.1A`, `SF1.1A` and `SF 1.1 A` are one
code, and a lookup finding only one of them would abstain on a label that is printed.

The safety rule is that a variant may only **re-space** characters — never add, drop or
change one — so `K73` can never produce `K78`. `preserves_characters()` states that property
as a callable predicate rather than leaving it in a test file, and it is the only permitted
string normalisation in the codebase: there is no identifier grammar, no normalisation table
and no per-corpus regex.

No similarity measure exists anywhere. The conformance suite refuses a declared fuzzy-matching
dependency (`rapidfuzz`, `fuzzywuzzy`, `thefuzz`, `python-levenshtein`, `jellyfish` …),
refuses fuzzy matching from the standard library, and refuses any model field named `score` —
because a magnitude invites a threshold and a threshold turns "ranked ninth" into "no
results".

### Tokenisation is where this can quietly go wrong

`tok()` mirrors **Qdrant's WORD tokenizer**, because `verify` reasons in Python about what
the index matched. If the two disagreed by one token, `verify` would report *present* where
the index found nothing, or *absent* where it found the page — and the disagreement would be
invisible, since both halves are individually sensible.

So `tok()` keeps runs of alphanumerics, lowercases them, treats everything else as a
separator, preserves order, and keeps tokens as short as one character (`SI3`, `84`, `0020`
all survive). It is Unicode-aware because the corpus is Italian and English. Two behaviours
of the previous implementation are deliberately *not* ported: keeping `84-5140.0020` as one
token, and joining adjacent tokens — the second of which would make `84 5140` matchable as a
unit, a match this system must not be able to make. An integration test measures `tok()`
against a live Qdrant on a fixed corpus of labels, so a store upgrade fails the build rather
than silently changing what `verify` believes.

`token_set()` exists for membership questions — `codes_in_text`, `grounded_rate` — and never
for matching, which is always a phrase.

### The same question asked locally

Derivation and the near-miss generator need to ask the identical question of a string in hand,
before a page has been indexed at all, so `contains_phrase()` and `printed_in()` live beside
the filter: `variants()` for the spellings, `tok()` for the tokens, and contiguity for the
phrase. Contiguity and order are the whole content of phrase matching — a set-membership test
would match `sf` and `1` anywhere on the page.

## Verification

`verify_claims(claims, page_ids)` answers *is this code actually printed on the page you are
about to cite it from?*

**Per `(claim, page)`, never per claim.** A draft citing two pages must not be able to let a
code from the neighbouring page through, so every pair is checked and `page_checks()` returns
the whole matrix. That matrix — not the folded verdict — is what the answer gate consumes,
because "is this code verified on the page this sentence cites?" is a question about a pair.

It builds no matcher of its own: it calls `exact_filter` scoped to one page and counts.

### Three verdicts, and `unverifiable` is never `absent`

| Verdict | Means | Carries |
|---|---|---|
| `present` | at least one page carries the code | the pages it is present on, and only those |
| `absent` | at least one page was checked and none carried it | the pages the absence is asserted over, plus `present_instead` |
| `unverifiable` | nothing could be checked | a shared `reason`, or `mixed` where the pages disagree |

A page is uncheckable when it is not current, has no text layer, or has an untrusted
extraction. Folding that into `absent` would convert the system's blind spot into the agent's
confident denial — telling an agent a code is *not* on a page nobody could read. `not_current`
is `unverifiable` for the same reason: the page was not checked, and the code may well be
printed on it. The answer gate rejects a draft carrying an unverified code, which is the
correct outcome for one citing a superseded or unpublished page — and an outcome it can only
reach because this reads `unverifiable` rather than `absent`.

A `page_id` that is not in the collection is a `404 page_not_found` rather than any verdict:
an `absent` about a page that does not exist would be a statement about nothing.

A `verify` in which every claim is `absent` is a perfectly good successful call — the call ran
and the answer is no.

## `present_instead`: a bounded disclosure, never a suggestion

Beside an `absent` verdict the caller may be told what *is* on the page. The mechanism is
deliberately weak, and each part of that weakness is the point:

- **a prefix, never a distance.** The only question asked is which observed tokens start with
  this string, answered by binary search over a sorted tuple. `K73` can surface `K78` because
  they share the prefix `k7`, and can never surface `Q78` or `K8`.
- **bounded truncation.** At most two characters come off the claim, and no prefix shorter
  than two characters is ever tried — without the floor, `K73` would fall back to `k` and
  disclose every contactor in the document.
- **capped and labelled.** At most five, the claim itself excluded, presented as *"different
  part"* and never as *"did you mean"*.

The inventory it reads is display-only and structurally unreachable from `lookup`: the lookup
module does not import it, and a test asserts that its import graph never will. A `lookup` that
could consult the inventory could return a near miss as a hit.

## The observed-token inventory

Per document, the set of tokens the **text layer** actually carries. Three properties make it
safe, all structural:

- it is built from `text` and nothing else — never from model-claimed codes — so a code the
  model asserted and the text never backed can never be disclosed as what is there instead;
- only *searchable* pages contribute, so a garbled extraction's debris (`rai1` for *rail*) is
  not offered as a "different part" beside an absent verdict;
- the code-like heuristic is a token containing at least one digit — crude on purpose,
  because there is no identifier grammar anywhere, and because a miss costs a disclosure
  rather than an answer.

When verification is not handed a document-level inventory it builds a **local** one from the
pages named in the call, and returns none at all if those pages span two documents — merging
them would let a code from one binder be disclosed as what is "instead" on a page of another.

## Near misses: the adversarial input

The safety evaluation needs codes that are one character from real ones, and generates them
from whatever corpus is indexed by mutating tokens from the observed-token inventory. Three
properties are load-bearing:

- **exactly one character differs** — a substitution, never an insertion, deletion or
  transposition — so each fake is the hardest possible case for a matcher that is even
  slightly fuzzy, and *"this must return nothing"* is unambiguous;
- **no fake is printed anywhere, in any spelling.** A mutation landing on a real code, or on a
  phrase the corpus prints, is not a near miss: `sf5` mutating to `sf1` has the boundary-spaced
  variant `sf 1`, which really is printed inside `SF 1.1A`, and `lookup` returning that page
  would be *right*. Every variant of every candidate is checked against the corpus text;
- **it is deterministic** — no RNG, no seed, the same corpus yields the same fakes in the same
  order, because a safety test that samples differently each run turns an intermittent defect
  into an intermittent build.

Each fake carries the real token it came from, because a near miss without its source is
unauditable: the first question when the evaluation fails is *one character off what?*

## Related pages

- [Page Model and Index Schema](page-model-and-index-schema.md) — the `text` field, its writer, and the trust levels
- [The Eight Tools and the Dispatcher](../retrieval/tool-surface.md) — `lookup` and `verify` as moves
- [The Agentic Runner and Answer Gate](../retrieval/agentic-runner.md) — how the pair matrix gates a draft
- [Evaluation Corpora and Quality Gates](../evaluation/corpora-fixtures-and-gates.md) — the abstention evaluation this generator feeds
