---
type: subsystem
title: The Agentic Runner and Answer Gate
description: The question-answering loop as a state machine — descend, tri-state triage under five safeguards, route to fetch or the paid read, draft, and the unconditional per-(claim, page) answer gate — with the constrained abstention wording that cannot claim a corpus was exhausted.
tags: [runner, agent-loop, triage, answer-gate, abstention, safety, state-machine]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-534e4ac83a73c93b9b36afbd
    resource: repo://backend/vsir/runner/answer.py
  - id: openwiki-source-9c5ac854e711aa574f95eb94
    resource: repo://backend/vsir/runner/loop.py
  - id: openwiki-source-994140ee65957830a9e50279
    resource: repo://backend/vsir/runner/prompt.py
  - id: openwiki-source-ce2020f7c3237d4bb589159a
    resource: repo://backend/vsir/runner/route.py
  - id: openwiki-source-37e1999acb30646216549dff
    resource: repo://backend/vsir/runner/triage.py
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# The Agentic Runner and Answer Gate

The runner is the sequence *in code*: narrow, triage, look once, draft, gate. Its three structural
properties are meant to be visible in the module rather than asserted about it — narrowing is the
same move at three zoom levels, the expensive step happens once and late after free narrowing, and
verification happens **after** drafting, which is the only order in which a gate can catch
anything.

## It is a state machine, as data

The transition table *is* the machine; the loop executes it and takes no path that is not in it.
Every state is one method, every method returns one signal, and the successor comes from a lookup
that **raises** on a pair it has no edge for.

That matters for one rule in particular. "On an insufficient read, drain the uncertain pool
**before** widening scope" is, in a hand-written loop, one line a later edit can reorder with no
test noticing. Here it is a row a test reads directly, and widening is reachable only *through*
the drain state — there is no edge from an insufficient look straight to widening for someone to
add by accident.

States: descend, triage, look, drain-uncertain, widen, vision-first, draft, verify, and the two
terminals answer and abstain. Signals are **observations the loop can make for free** from an
envelope it already has; no signal requires a call that was not going to happen anyway.

One edge exists specifically so the vision branch is reachable from the *end* of the ladder as
well as from a descent that returned nothing: a triage that rejects every row it was offered would
otherwise abstain while a page nobody can read sits unexamined.

A move counter bounds the whole thing, and exceeding it raises rather than abstaining — that state
is a bug, not an answer.

## It holds no state between questions

The loop object is created per question and discarded with the answer. Scope and exclusions are
parameters passed to every rung, nothing is module-level, nothing is cached across calls, and two
replicas answering the same question make the same moves because the moves are a function of the
question and the corpus.

**Every tool call goes through the caller's dispatcher**, never to a tool function directly. The
runner is a *caller* of the eight tools and is not permitted to become a ninth path into them —
which is what keeps the budget, the audit line, the argument validation and the typed refusals in
one implementation for every surface.

## A refusal is never an abstention

An outage mid-loop, an exhausted quota, or a model that answered unusably ends the loop as a
refusal carrying the tool's own status and code. An outage rendered as "not found in these
documents" would be the service's failure delivered as the caller's fabricated confidence.

## Triage: three marks, five safeguards

Every candidate is marked `relevant`, `uncertain` or `irrelevant` **from its summary row, for
free, before any money is spent**. Nothing in the triage module reads page text, opens a raster,
embeds anything or calls a model — its whole input is four fields already on the row: the summary,
which surfaces found the page, the grounded rate and the text trust.

**Three states rather than two**, because a binary keep/drop discards the fallback pool, leaving
re-searching from scratch as the only repair for a wrong drop — and the summary that hid the answer
will hide it again. The uncertain pool is the memory that makes an insufficient read cost one more
*look* instead of one more *search*.

Every judgement errs toward carrying a candidate forward, and the asymmetry is deliberate: marking
a useless page uncertain costs a place in a pool that is only drained when the answer was not
found, while marking the answering page irrelevant produces an abstention on a corpus that
contained the answer.

Each mark carries exactly one reason from a **closed** list, because a reason nothing sets is a
column a reviewer cannot act on.

The five safeguards are **one definition read twice**: the triage module holds the text and
enforces it, and the prompt module prints it into the system prompt. Two statements of a rule stay
the same rule only when there is one statement.

1. **Rejections stay soft** — drain the uncertain pool before widening. A rejection is a statement
   about the pages looked at, not about the corpus.
2. **Do not filter a small set** — with three candidates or fewer, read them all; filtering a set
   that size can only remove the answer.
3. **Use the surface signal** — a lexical hit on an exact code outranks a dense-only hit.
4. **Auto-promote exact hits** — when the query contains an identifier and the hit was found
   lexically, mark it relevant without evaluating the summary: the page prints the code that was
   asked for.
5. **Tri-state is mandatory** — never keep/drop.

**Nothing in triage matches.** Query-term overlap with a summary decides whether to *look*; it
never decides whether a code is printed on a page. That question has one answer and one code path,
and a triage mark can never reach a response as a hit, a citation or a claim.

## The route: two ways to put a raster in front of a model

No answer in this system is composed from text alone. Narrowing is text-driven because triage must
be cheap, but the draft is written against a page raster — on a schematic there are no sentences
to reason over, only a drawing.

| | `fetch` — the agent looks | `read` — a sub-model looks |
|---|---|---|
| who sees the pixels | the calling agent | the model, server-side, at the pinned dpi |
| reason across pages | yes, one context | no, an independent extract per page |
| ask a follow-up | free | re-bills the whole vision call |
| zoom into a corner | yes, a region at higher dpi | no |
| cost | the agent's own context | the paid budget |

**The default is `fetch`** — the human move this design copies. `read` is for *delegation*: a
caller that cannot see, or an agent whose context cannot hold another raster. The route decision
is made for free, before either call, with no model call of its own.

The safety consequence is why the module can be honest about defaulting to the free route: the
automatic per-code stamping lives *inside* `read`, so on the fetch route it does not happen and
the agent has read codes off a raster with nothing checking them. That is exactly why the gate is
server-side and unconditional. **A route decision is never a trust decision here.**

Whether the caller can see is a property of the caller rather than of the deployment, so it
arrives as an argument: the service holds no session in which a previous call's capability could
be remembered.

## The answer gate

The gate is the last thing between a model's sentence and a person's eyes. It is
**unconditional**, per `(claim, page)`, and there is no flag to skip it:

```
for code in codes_in_draft:
    v = verify([code], [cited_page_id])
    present      → render
    unverifiable → render with the "read from image, not text-verified" badge
    anything else → reject the whole draft
```

Two things a real implementation has to settle:

- **A claim cited on more than one page is checked against each of them** — one call per pair,
  never one call over the set — and the verdicts are folded. That is what makes the call log an
  answer to *"was this code checked against the page it is cited on?"* rather than *"was it checked
  somewhere?"*
- **A failed check is not a verdict.** An unavailable verifier raises rather than producing an
  absence.

A claim with no cited page is a rejection with no page to name, which is the only honest outcome:
a code asserted over nothing has nothing to verify it against.

The gate does not ask which route produced the draft, and it **re-checks** the stamps a paid read
already applied rather than trusting them.

**A rejection never echoes the code it rejected**, and a rejected draft returns no prose at all. A
body saying "K153 is not printed on p019" would put the misread code in front of the caller in the
one place a person is reading for an answer, and a UI that renders a rejection field is one style
change away from rendering it as the answer. The count, the page and the observed tokens present
instead are enough to act on. For the same reason the gate logs the *distribution* and never the
codes, keeping draft codes off the event stream.

## The abstention is composed, not chosen

An abstention is built from the coverage rather than selected from a list of sentences, in three
clauses always in the same order: **what was done** (per a closed list of reasons, never "this
does not exist"), **the numbers** (how many pages across how many documents), and **the gap** —
the count of image-only pages not examined and the documents they are in.

The phrase *"not in these documents"* is a named constant and is **forbidden** while unexamined
image-only pages remain, because a corpus with unexamined image-only pages has not been searched,
and an abstention that sounds complete is a fabricated absence in the one direction nobody audits.
The composer asserts the wording rule against the string it just built.

Two cases are handled explicitly rather than falling through: when **nothing** was searched the
text says so and draws no conclusion about the corpus, because a completeness claim over zero
pages is the same fabricated absence arrived at from the other end; and only when every image-only
page in scope *was* examined, or every page has a text layer, is the permitted wording used.

## Where the loop can spend, and what bounds it

One paid step, `read`, reached at most through the look state. Two ceilings bound it, both the
server's: a per-question limit and a per-caller daily quota. The loop tracks the remaining count
off every envelope that comes back, and a question that needs another look with none left ends as
a refusal rather than as an answer from pages the model said did not answer.

The explain mode runs the free half only — the descent, the triage and the route — and spends
nothing on any path.

## The system prompt

The prompt module renders text and does nothing else: no call, no state, no configuration read. It
is the second reader of the safeguards, so a safeguard edited in one place is edited in both.

It is **deterministic by construction** — the same inputs render byte-identical text and the
digest is over those bytes — because a prompt is a cache-key input wherever a released prompt
reaches a paid call, and a prompt that varied with dict ordering would be a prompt whose cache hits
were lies.

It lives in Python rather than as a packaged file, unlike the extraction prompts: those are inputs
to a *billed* call and are pinned by digest to a released version, while this one is composed per
question from the tools a release actually serves and the budget in force. Putting it under the
same version label would re-key every frozen extraction response in the repository whenever a
safeguard's wording changed, so it carries its own label.

The prompt's own file says why the prompt is not enough: prompt-level rules are advisory the
moment a client drives the raw protocol surface. Everything that must not be optional is
server-side, and the text tells the model what the server will do to it rather than asking it to
be careful.

## Related pages

- [Exact Match and Claim Verification](../concepts/exact-match-and-verification.md) — the verdicts the gate consumes
- [The Eight Tools and the Dispatcher](tool-surface.md) — the moves the loop makes
- [HTTP API Surface](../interfaces/http-api.md) — the ask route
- [Operator Console Frontend](../interfaces/operator-console.md) — how badges and abstentions are rendered
