---
type: interface
title: Operator Console Frontend
description: The React and Vite console — same-origin by proxy with no CORS, the bearer token typed into the page rather than built into the bundle, authenticated rasters via object URLs, the zoom ladder and trust badges, and the tests that keep its types and wording in step with the backend.
tags: [frontend, react, vite, console, security, ui, contract-tests]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-11T14:07:28.402Z
sources:
  - id: openwiki-source-01a77324b60ce32405162146
    resource: repo://backend/tests/unit/test_frontend_client_contract.py
  - id: openwiki-source-e1203af9dfebfe1b0264745d
    resource: repo://frontend/src/api/client.ts
  - id: openwiki-source-68ed2d0cf8ec7e3742c582e4
    resource: repo://frontend/src/auth/token.ts
  - id: openwiki-source-8343b0c1d40c9118d5d43c1b
    resource: repo://frontend/src/components/AgentPanel/AbstentionCard.tsx
  - id: openwiki-source-2f1eee28c9320823a52e8fca
    resource: repo://frontend/src/components/Banner.tsx
  - id: openwiki-source-9498d9ce7d19c7512881a502
    resource: repo://frontend/src/conformance.test.ts
  - id: openwiki-source-07cb06cb4599adbcee7382c9
    resource: repo://frontend/src/hooks/useAsk.ts
  - id: openwiki-source-8662a7da8167d7928c483a8d
    resource: repo://frontend/src/hooks/useRaster.ts
  - id: openwiki-source-40f380e849e55ed9e56fc50d
    resource: repo://frontend/src/lib/badges.ts
  - id: openwiki-source-63b7c49860f74bfb5d0fe80f
    resource: repo://frontend/src/lib/ladder.ts
  - id: openwiki-source-378e3cf05ab0d05d335c68d5
    resource: repo://frontend/vite.config.ts
generated: { by: "claude-code", at: "2026-09-11T14:07:28.402Z" }
---

# Operator Console Frontend

A small Vite + React + TypeScript app that puts a question at the top, the page on the left and
the agent on the right. Three pieces of state live in the root component, and each is there for a
stated reason: the **token**, the **ladder** (where the reader is on the zoom ladder, including
the crop), and the **last response**, held from the mutation rather than refetched because
re-asking a question can spend money.

## Same-origin by proxy, never by CORS

The service has no CORS middleware and must not grow one. Instead the dev and preview servers
proxy the API paths to a configured target, and that target is a **proxy target rather than a base
URL the browser sees**. Three problems disappear together:

- **no CORS boundary** — adding permissive origin headers to a surface whose every route is
  bearer-authenticated would widen the attack surface of the credential for one page's
  convenience;
- **relative image URLs work as sent** — the service returns a relative path for a page raster on
  purpose, because a browser resolves it against the origin it loaded the response from, which is
  the only origin that can serve it;
- **the container's target is not the browser's** — the test stack's target is a hostname that
  resolves only inside the test network: correct as a proxy target, unreachable as a URL handed
  to a browser on the host.

The proxied paths are **listed rather than globbed**, because a catch-all proxy would swallow the
app's own routes and hide a 404 as an API error. The proxy is configured on both the dev server
and the preview server, since the built image runs preview — otherwise the stack would work in dev
and 404 in Docker.

## The token is typed in, never built in

A build-time token variable would be substituted into the bundle and shipped to every browser that
loads the app. Instead the operator types it, and it lives in `sessionStorage` because that dies
with the tab: a shared workstation should not keep a corpus credential across sessions.

This is browser state, not server state — the ban is on a *server-held* session, because a
stateless service can be replicated, and a token in the operator's own tab is the opposite
arrangement: every request carries its own identity and any replica can serve it.

Storage access is wrapped in try/catch: private browsing modes throw on session storage, and an
unauthenticated console is a usable console (the operator retypes the token), so that is a
degradation rather than a failure.

## Authenticated rasters

Every route is bearer-authenticated including the page images, and an `<img src>` sends no
authorization header. The two ways out are a token in the query string — which lands in every
access log, referrer and screenshot — and fetching with the header and minting an object URL over
the bytes. The console does the second.

Ownership is split deliberately: the query cache owns the blob, so two components showing the same
page share one download; an effect owns the URL and revokes it when the blob changes or the
component unmounts, so neither half outlives the other. A raster at a given dpi and region is
treated as immutable — refetching it on a window focus would re-render a PDF page on the server to
get the same bytes back.

## One caller, three properties enforced in one place

The typed API client enforces what would otherwise be asked of each component:

- **every request carries the token**;
- **a refusal is a refusal** — a non-2xx becomes a typed error carrying the service's own `error`
  code, and the UI shows a banner rather than an empty list;
- **`inline` is `false` on every fetch**, pinned in one place so no component can undo it, because
  an accidental inline fetch would move megabytes through JSON twice.

## Refusals and absences are rendered, not swallowed

A failed call renders the service's own error code and detail, and says whether it is worth
retrying, because the retryable flag rides on an outage refusal's body. A store-unavailable
response rendered as an empty list would tell an operator the corpus holds nothing, which is the
same confusion the four typed absences exist to prevent, one layer up.

The status badges keep the absences distinct for the same reason: *searched and absent* and
*those pages have no text layer* are two different instructions — abstain versus escalate to
vision — so they are two visually distinct badges with two different action lines.

An **abstention is neither an error nor an empty result**, and the card reads that way. What makes
it trustworthy is the coverage: how much was searched, how much had no text layer, and how many
image-only pages nobody looked at. That last number is rendered as the headline of a warning
rather than a table row, and the documents those pages are in are named — while it is above zero
the system may not claim the corpus was exhausted, because nobody has been to the pages where the
answer would be.

## The trust badges

Three states, and only two of them render:

- **verified** — the code is printed in the page's own extracted text, whose only writer is the
  ingest probe. The strongest claim the system makes.
- **read from image, not text-verified** — nobody could check it. The badge *is* the disclosure,
  and the wording is the service's own constant rather than a paraphrase.
- **absent** — never renders at all. A code the gate found is not on the page it is cited on
  rejects the whole draft, so there is no badge for it and the mapping returns nothing.

Colours are **tone names, never values**: a component asks for a tone and the stylesheet turns it
into a CSS variable.

## Asking is a mutation

The ask call is modelled as a mutation rather than a query, and that is not a technicality: a
query is something the client library may repeat on focus, reconnect or remount, and this call
runs the loop, which may take the paid route. A question must be asked because somebody asked it.
A caller that looked at the raster itself can submit its own draft — still a mutation, because
nothing is spent but the gate runs and its verdict is the answer.

## The zoom ladder

Four rungs — corpus, binder, chapter, page — and below the page a region at escalated dpi, which
is part of the same gesture rather than a separate control because above the pinned answer dpi a
full page exceeds the megapixel bound and a crop is the only thing that can be rendered.

The ladder is kept as pure state for two reasons: climbing **up** must clear everything below (a
document id left behind when the operator returns to the corpus would silently scope the next
search to a binder whose name is no longer on screen), and jumping straight to a page is the
gesture a draft's citations use, from a component that knows a page id and nothing else.

## Two test layers keep it honest

**A frontend conformance suite** enforces the rules no compiler catches and no component test
would notice, because each is about *every* file: no written `any` (the type checker catches an
inferred one and says nothing about a written one), no raw hex colour in a component (a badge
whose colour is written inline can be restyled by someone who has not read what it means), and no
inline flag or reading of image bytes outside the type that declares them. The scanner itself
asserts that it reached the source, because a conformance check that quietly stops finding things
is worse than none.

**A backend contract test** compares the console's TypeScript envelope types against the Pydantic
models **field by field, in both directions**. No code generator runs: a generator would be a
build step someone forgets to re-run, and it could only catch a field the service *added* — this
also catches a field the console believes in that the service has never sent, which is how a panel
renders `undefined` in production and nobody finds out until an operator reads it. The comparison
is by field name, which is the honest limit of reading TypeScript with a regular expression and is
where the value is anyway.

Three things beyond the field sets are pinned there because each is **a string a person reads**
rather than a shape a compiler checks: the schema version, the two badge labels, and the amber
warning. A paraphrase in the browser would be a change to a product contract made silently, in the
one place nobody greps.

## Related pages

- [HTTP API Surface](http-api.md) — the routes this app calls
- [Typed Results and Refusals](../concepts/typed-results-and-refusals.md) — the absences and refusals it renders
- [The Agentic Runner and Answer Gate](../retrieval/agentic-runner.md) — the loop behind the ask panel
- [Test Layers, Conformance and CI](../testing/test-layers-and-ci.md) — where these suites run
