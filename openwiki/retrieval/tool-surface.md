---
type: subsystem
title: The Eight Tools and the Dispatcher
description: The release's one tool table and the single dispatch function HTTP, MCP and the CLI all call — the ladder of eight moves from NARROW through COMPREHEND, what each tool takes, refuses and discloses, and the one row that spends money.
tags: [tools, dispatcher, agent-moves, api-contract, budget, lookup, verify, fetch, read]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-2205ae93add6598628c21601
    resource: repo://backend/vsir/serve/app.py
  - id: openwiki-source-f3c8f53a314038c5017f3907
    resource: repo://backend/vsir/serve/inputs.py
  - id: openwiki-source-ede571807cb2209f95beb4c5
    resource: repo://backend/vsir/serve/tools/fetch.py
  - id: openwiki-source-46bbcaacf27e1545d30fd654
    resource: repo://backend/vsir/serve/tools/lookup.py
  - id: openwiki-source-42b24bc9f9f0ef48e6e9a285
    resource: repo://backend/vsir/serve/tools/read.py
  - id: openwiki-source-b74c260390379e1db5de0952
    resource: repo://backend/vsir/serve/tools/resolve.py
  - id: openwiki-source-4abee845e703249c8a5fd62e
    resource: repo://backend/vsir/serve/tools/verify.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# The Eight Tools and the Dispatcher

Eight tools, one table, one dispatcher. Adding a tool is adding a row, so no tool can arrive with
its own idea of authentication, of the budget, or of which failures are which.

## The ladder

The table's row order is the ladder rather than the alphabet, because an agent reading the tool
list for the first time is choosing a **move**:

| Move | Tool | What it answers | Spends |
|---|---|---|---|
| NARROW | `skim_documents` | which binder? | no |
| NARROW | `skim_sections` | which chapter? | no |
| NARROW | `skim_pages` | which pages? | no |
| JUMP | `lookup` | which pages print this exact label? | no |
| FOLLOW | `resolve` | what page id does this printed label open? | no |
| CHECK | `verify` | is this code printed on this page? | no |
| LOOK | `fetch` | give me the material of pages I chose | no |
| COMPREHEND | `read` | answer this question about these pages | **yes** |

## The table row

Each row declares a name, its request model, the implementation, the envelope it returns, whether
it spends, an optional request-only precheck, and the description an agent reads when choosing.

The response type is **published and never applied**: the route declares it in its documented
responses and returns the serialiser's raw bytes. Handing it to the framework as a response model
would put a second serialiser on the response path, and byte-identity between transports is only
meaningful while there is exactly one.

The description is one string used as both the protocol tool description and the route summary,
because a tool described two ways is a tool two clients understand differently.

The runtime the dispatcher takes holds no transport: the configuration, a search client, the tool
table itself (the very dict, not a copy), and memoised backend handles for embedding and the
model. A release that registers a tool registers it once, for every surface at once.

The outcome carries an **HTTP status even when nobody is speaking HTTP**, because that is the
vocabulary the bounds and outage rules are written in — and the protocol surface maps it onto its
own error flag rather than inventing a second taxonomy for the same events.

## Dispatch, in three steps

1. **The name** — absent from the table is a typed `404` listing what *is* served. A tool not in
   this release is absent, not empty.
2. **The arguments** — validated against that tool's own model with extra fields forbidden, so a
   misspelt parameter is a `400` and never a quietly different query. This happens server-side
   precisely because a client that ignored the published schema cannot be trusted to have read it.
3. **The call** — with the budget, the audit line and the remaining-read count.

Then `run_tool` applies the cross-cutting policy in a fixed order: the precheck that can be settled
from the request alone, the budget charge for the one spending tool, the call, the remaining count
stamped onto the envelope by the dispatcher rather than by each tool, and the audit line for the
audited tools.

The precheck exists for one reason and needs to: a caller that named four pages must not have a
read taken off its quota to be told it named four pages.

## Request models declare shape; bounds live elsewhere

The input models carry **not a single numeric or pattern constraint**, and that is the design.
Each bound has to produce its own switchable code, and a framework-level constraint would turn a
named refusal into a generic validation error with a JSON pointer — the same information in a shape
nothing can branch on. So the models declare shape and meaning, and the caps module declares
bounds; a field that looks unconstrained is constrained one layer in, under a name the caller can
act on.

Every field carries a real description rather than a source comment, because the schema is
published to both transports: a note visible only to a developer reading the source is invisible
to the model calling the tool.

## The tools

### JUMP — `lookup`

The exact surface: a phrase filter over the page's own extracted text, whose only writer is the
ingest probe. A hit is verified by construction, and a code the model invented is not merely
unlikely to be found — it is **unfindable**.

Three things it does not do, each a wrong answer if it did:

- **it does not rank.** The result is a set in reading order, and `total` is the size of the set
  rather than the number returned, because a caller paging a capped result must tell "20 of 400"
  from "20 of 20";
- **it does not let the cap touch the weakness signal** — a trust signal a client could flip by
  asking for a bigger page would be worse than no signal;
- **it does not merge the two surfaces.** The opt-in model-claimed surface is returned separately,
  permanently unverified. Those hits are the only recall there is on a scanned page, and they are
  never evidence.

The `present_instead` inventory is unreachable from here by module boundary, asserted by an
import-graph test: a lookup that consulted it could return a near miss as a match.

### FOLLOW — `resolve`

A *printed* label — what a person reads in a footer — turned into an addressable page id, with two
disclosures that are as much of the answer as the id: whether the page's own text prints that
label, and whether the label was **interpolated** from the pages either side rather than read off
this one.

**Ambiguity returns every candidate.** Two documents both printing "8", or a manual restarting its
numbering each chapter, produce two hits and not a silent pick — a resolver that chooses for the
agent is how a cross-reference is followed to the wrong page and then cited.

A page whose own label is ambiguous answers to *every* reading of it rather than none.

The mechanism is index-side: the label is asked of the phrase index, and the document facet is
computed by the index. The earlier implementation scrolled a fixed number of points and filtered
in Python, so a page beyond that bound was reported as not found without ever being looked at.
Nothing in this module scrolls.

**A citation is not a label**: when the citation as typed matches nothing, its digit-bearing words
are probed as labels in their own right, and every candidate is still confirmed against the whole
citation.

### CHECK — `verify`

A move the agent makes at the moment it matters — about the code it is about to write, against the
page it is about to cite. The module is a wrapper: every verdict comes from the shared verification
function asking the same question `lookup` asks, scoped to one page, so the tool that found a page
and the check that confirms it cannot disagree.

It is a Family B envelope, and that is the whole reason that family exists: three legitimately
absent claims are a successful call whose answer is no. Forced into the search family it would be
an empty result, indistinguishable from an outage.

Two failures are deliberately *not* verdicts: an unknown page id is a `404`, and an unparseable
one is a `400` — because saved citations arrive from outside this service, so a malformed one is
the caller's bug and gets named.

**No image, ever.** A photograph may find a candidate page; it can never confirm a code.

### LOOK — `fetch`

Material instead of an answer: the pixels, the text and the summary of pages the caller chose,
kept, so a follow-up costs nothing. It reasons about nothing, ranks nothing and calls no model.
Splitting looking from comprehending is what lets an agent choose a page and *then* decide whether
it is worth money.

It is never empty: the pages were named outright, so either every named page comes back or it is a
typed refusal. **A partial result is refused specifically** — an over-budget call does not return
five of six pages, because a caller that reasoned over five would not know which one it never saw.

Every bound is checked **before anything is rendered**, from predicted sizes rather than measured
pixmaps, because a budget enforced after allocation has already paid for what it refuses.

### COMPREHEND — `read`

The one tool that spends. Pages the caller already chose, one question, a bounded answer, and codes
stamped **by the service** against the page's own text rather than claimed by the model.

- **The stamp is the shared verification, not a second implementation of it** — one vocabulary,
  one meaning, one code path.
- **`unverifiable` exists.** A boolean cannot say "nobody could read this page"; on a page with no
  text layer every code is unverifiable, which is the honest answer rather than a gap.
- **`sufficient` is mandatory**, because "these pages do not answer this" and "the answer is no"
  are the difference between looking again and stopping.
- **Nothing is withheld and nothing is classified.** A code that failed its check is *returned,
  stamped* — dropping it hides a transcription error from the only party that can act on it.
- **The dpi is pinned and is not a parameter**, because it is a cache-key input: a caller that
  could raise it would bill the same question three times for one answer. Choosing a dpi is what
  the free tool is for.

**Retrieval judgement never happens here**: the module chooses no page, ranks nothing and suggests
nothing. It is handed pages and a question, and it answers about those pages or says it cannot —
an engine that picked its own evidence would be the answerer.

## Related pages

- [Search, Fusion and Ranking](search-and-fusion.md) — what the narrowing rungs run
- [Typed Results and Refusals](../concepts/typed-results-and-refusals.md) — the envelopes and bounds
- [The Agentic Runner and Answer Gate](agentic-runner.md) — a caller that composes these moves
- [HTTP API Surface](../interfaces/http-api.md) and [MCP Server Surface](../interfaces/mcp-server.md) — the transports
- [The vsir Command Line](../interfaces/cli.md) — the one-shot form
