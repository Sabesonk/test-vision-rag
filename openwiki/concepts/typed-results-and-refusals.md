---
type: concept
title: Typed Results and Refusals
description: Why nothing found is never an empty 200 — the six-value status enum with its four distinct absences, the two envelope families, the single refusal shape published in the schema, and caps that refuse by name rather than clamping or truncating.
tags: [api-contract, error-handling, absences, envelopes, caps, safety]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-88594d62d68c1fc754281ef9
    resource: repo://backend/vsir/core/status.py
  - id: openwiki-source-16d63de929cfb74005fd1d16
    resource: repo://backend/vsir/serve/caps.py
  - id: openwiki-source-d9236955bd8a5085e7b11479
    resource: repo://backend/vsir/serve/envelope.py
  - id: openwiki-source-6b2705c4398f891df88bb80a
    resource: repo://backend/vsir/serve/errors.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Typed Results and Refusals

An empty `200` is the single most dangerous response this system could return, because it
is indistinguishable from a backend that failed silently. Everything on this page exists to
make that response impossible and to replace it with something a caller can act on.

## Four kinds of nothing

The status enum has six values, four of which are absences, and each one is a different
instruction to the caller:

| Status | Means | What the caller should do |
|---|---|---|
| `ok` | there is something to return | use it |
| `not_found` | searched, genuinely absent | abstain — unless the envelope's `next.suggest` says another *move* could still answer |
| `not_searchable` | the candidate pages have no text layer | escalate to vision; do **not** conclude the part does not exist |
| `out_of_scope` | no document matched the filters | re-orient and widen: the corpus was never asked |
| `found_only_in_superseded` | it exists, in a revision that is not current | surface the revision and let the caller decide |
| `error` | an outage or a refusal | retry or report, and **never** abstain |

Collapsing these into an empty list makes the agent guess, and an outage returned as an
absence is the service's failure rendered as the caller's fabricated confidence.

A per-item check has its own three-value vocabulary — `present`, `absent`, `unverifiable` —
deliberately neither a boolean nor this enum. "Is this code on this page?" has three answers,
and `unverifiable` is the one a boolean would have to lie about.

## Two envelope families

*Did you find anything?* and *here is the verdict you asked for* are different questions, so
there are two shapes.

**Family A — search and absence** (`skim_documents`, `skim_sections`, `skim_pages`, `lookup`,
`resolve`). These can legitimately be empty, so they carry the typed-absence machinery. A
model validator makes an empty `ok` **impossible**: it raises rather than asserting, because
`python -O` strips asserts and this must not be strippable.

Family A also carries, beside the hits:

- `total`, the size of the **set** that matched rather than `len(hits)` — a caller must be able
  to tell "20 of 400" from "20 of 20", because the first is a scoping problem and the second is
  an answer — plus `capped` when the two differ;
- `weak` and `needs_scope`, computed server-side from the match-set size against the scope size,
  so a client cannot flip a trust signal by asking for a larger cap;
- `unverified_hits`, the opt-in model-claimed surface, never merged into `hits`;
- `effective_scope`, echoed back because the service holds no session — the caller's scope is
  the whole truth about what was searched;
- `superseded`, populated only under `found_only_in_superseded`, which is the evidence for the
  one absence that is not an abstention.

**Family B — material and verdicts** (`fetch`, `read`, `verify`). These are never empty: the
call either ran or it did not, and the answer lives in per-item states. `status` says whether
the *call* ran, not what it found — so a `verify` with three `absent` verdicts is `status: ok`,
because the call worked and the answer is no.

Two things are deliberately absent from both families: any curated-keyword filter field, and
the fused RRF sum. A fused float is a similarity score under another name. An ordinal `rank`
stays and is required — a position is not a confidence.

### One serialiser

`wire()` turns an envelope into the bytes a caller receives on **every** transport, so the MCP
`tools/call` result is byte-identical to the HTTP response body for the same request. Two
serialisers could only make that true by agreement, and would stay true until one of them gained
an `indent`. Key order is model field order rather than sorted, because `status` first is
deliberate: it is the field a caller switches on.

## One refusal shape

Every surface refuses the same way: `{"error": <code>, "detail": <prose>, …}`. The code is the
contract — an agent switches on `fetch_budget_exceeded`, not on prose — and `error` and `detail`
are guaranteed present and string-typed so a client can branch without a null check.

`CODES_BY_STATUS` documents which codes arrive under which HTTP status (400 for the bounds and
malformed requests, 401, 403 `spend_not_permitted`, 404 for unknown tool/page/run/document, 413,
415, 429 `budget_exhausted`, 500, 502 for model and embedding failures, 503 for store and backend
outages) and is published in the schema's own description, so it cannot be read without being
seen. It is documentation rather than a validated enum, because `caps.py` and the tools own their
codes and a second declaration would drift.

The refusal model is the **one** model in the service with `extra="allow"`, and the inversion is
deliberate. Everywhere else a silently ignored field is how a caller is told, with a straight
face, that the corpus does not contain what they misspelled. A refusal is the opposite: its
details *name the bound that was hit* — `limit` and `requested` on a cap, `retryable` on an
outage, `tool` on a tool refusal, `available` on an unknown tool name — and those keys differ per
code. Forbidding them would drop the numbers a caller needs to make the next attempt correct.

## Caps refuse, they never clamp

Each cap is a typed `400` naming its bound. The reason is specific: a `read` silently trimmed
from four pages to three answers a question about pages the caller did not ask about and reports
success; a `dpi` quietly clamped from 400 to 220 returns an image the caller cannot read the part
number off and reports success. In both cases the caller has no way to know, so the failure
surfaces as a wrong answer downstream instead of an error here.

| Bound | Value | Refusal |
|---|---|---|
| `read` pages | 1…3 | `read_empty` / `read_page_cap_exceeded` |
| `read` question | non-empty | a directed call is required |
| `fetch` pages | ≤ 5 | `fetch_page_cap_exceeded` |
| `fetch` rasters | ≤ 12 MP | `fetch_budget_exceeded` |
| dpi | one of 36, 72, 150, 220, 300, 400 | `dpi_not_allowed` |
| dpi above 220 | needs a `region` | `dpi_requires_region` |
| region | normalised, `x0<x1`, `y0<y1` | `region_invalid` |
| `verify` | 1…200 `(claim, page)` **pairs** | `verify_empty` / `verify_budget_exceeded` |
| `skim_pages` limit | 1…25 | `limit_out_of_range` |
| scope keys | present in `INDEXED` | `filter_unknown_key` |

Several of these carry an argument worth keeping:

- **`read` with no pages is refused** rather than answered, because it would charge the caller's
  quota to send a question with no pixels behind it — from which any answer is the model's prior
  knowledge, the one thing this system exists to keep out of an answer. An empty **question** is
  refused for a second reason too: the question is an input to the read cache key, so an empty one
  would key every question about a page set to the same entry.
- **dpi is a money bound.** A full page at 400 dpi is megapixels of raster and tokens of vision
  input, which is why detail that fine must be about a *part* of the page.
- **A malformed region is refused rather than clamped.** Clamping `[0, 0, 2, 2]` to the page
  would return a different crop from the one asked for and call it success.
- **`verify` is bounded on the product**, because the work is `claims × pages` index counts.
  An empty list is a `400` naming which one was empty: a verdict map with no verdicts reads as
  "nothing to answer for", which is the one thing an answer gate must never conclude by accident.
- **`skim_pages`'s limit is a triage bound, not a cost bound**, and is refused for exactly that
  reason: a caller asking for a hundred rows has misunderstood the move it is making, and quietly
  returning twenty-five would let it believe it had seen a hundred. `lookup`'s `cap` has no upper
  bound for the opposite reason — there it bounds a page of a *set*.

`ToolError` carries the code, the message, an HTTP status and the details; the HTTP layer maps it
to a response, and the same error reaches the MCP and CLI surfaces unchanged.

## Related pages

- [The Eight Tools and the Dispatcher](../retrieval/tool-surface.md) — where these caps are applied
- [HTTP API Surface](../interfaces/http-api.md) — how a refusal becomes a response
- [The Agentic Runner and Answer Gate](../retrieval/agentic-runner.md) — the abstention path and its constraints
- [Operator Console Frontend](../interfaces/operator-console.md) — how the console renders a refusal rather than empty state
- [Exact Match and Claim Verification](exact-match-and-verification.md) — the three-state check vocabulary
