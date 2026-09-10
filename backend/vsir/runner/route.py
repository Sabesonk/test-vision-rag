"""§8.1a — where the answer comes from: the image, by one of two routes, chosen deliberately.

**No answer in this system is composed from text alone.** Narrowing is text-driven because triage
must be cheap (P2), but the draft is written against a page raster: on a schematic there are no
sentences to reason over, only a drawing. There are two ways to put that raster in front of a
vision model and this module makes the choice between them — for free, before either one is
called, and with no model call of its own.

| | `fetch` — **the agent looks** | `read` — **a sub-model looks** |
|---|---|---|
| who sees the pixels | the calling agent | Gemini, server-side, at the pinned dpi 220 |
| reason across pages | yes, one context | no, one independent extract per page |
| ask a follow-up | free | re-bills the whole vision call |
| zoom into a corner | yes — `region` at 300/400 | no |
| cost | the agent's own context | the entire paid budget |

**Default: `fetch`.** When the runner is itself vision-capable it looks at the page — the human
move this design is copied from, and the reason `fetch` exists at all. `read` is for
**delegation**: a caller that is not vision-capable, or an agent whose context cannot hold another
raster. §8's SA-4 settles the wording clash: §8.2's *"`relevant` → `read`"* is the generic verb for
the look step, and §8.1a's bolded *"Default: `fetch`"* governs the route.

**The safety consequence, and it is why this module can be honest about defaulting to the free
route.** Correction Loop 1 — automatic per-code stamping — lives *inside* `read` (§7.2.6). Take
the `fetch` route and it does not happen: the agent has read codes off a raster with nothing
checking them. That is precisely why the answer gate is server-side and unconditional (§8.4, I8,
U022) — on either route, no code reaches a rendered answer that `verify` did not clear for the
page it is cited on. A route decision is never a trust decision here.

Nothing in this module is configuration. Whether the caller can see is a property of *the caller*,
not of the deployment, and it arrives as an argument (§15 Factor VI): the service holds no session
in which a previous call's capability could be remembered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from vsir.config import MAX_READ_PAGES
from vsir.serve.caps import MAX_FETCH_PAGES

#: The two routes, and the third possibility that is not a route: a look that cannot happen.
FETCH = "fetch"
READ = "read"
ROUTES: tuple[str, ...] = (FETCH, READ)

#: Why the route is what it is. Closed, and printed beside every decision — *"we chose `read`"*
#: without *"because you cannot see"* is a decision a reviewer has to reverse-engineer.
REASON_DEFAULT_FETCH = "default_fetch"                # §8.1a's default: the agent looks
REASON_NOT_VISION_CAPABLE = "caller_not_vision_capable"
REASON_CONTEXT_BUDGET = "context_budget"              # delegation keeps the agent's context small
REASON_ZOOM = "zoom_required"                         # only `fetch` has a `region` (§7.2.5)
REASON_ZOOM_UNAVAILABLE = "zoom_requires_vision"      # …and `read` cannot crop, so there is none
REASON_BUDGET_EXHAUSTED = "budget_exhausted"          # delegation is needed and unaffordable (§8.4)
REASON_DEFERRED = "deferred_over_cap"                 # past the route's §7.3 cap: a second call's
REASONS: tuple[str, ...] = (REASON_DEFAULT_FETCH, REASON_NOT_VISION_CAPABLE,
                            REASON_CONTEXT_BUDGET, REASON_ZOOM, REASON_ZOOM_UNAVAILABLE,
                            REASON_BUDGET_EXHAUSTED, REASON_DEFERRED)


@dataclass(frozen=True)
class Caller:
    """What the runner knows about **who is asking**, and the only inputs to the route.

    ``image_slots`` is the caller's own context expressed in the unit that matters here: how many
    more page rasters it can hold. A token estimate would be this service guessing at a model it
    does not host — §8.1a puts a raster at *"~1–2k tokens per image"* and the caller is the only
    party that knows what that leaves. Zero slots is the *"keep the agent's context small on a
    long trace"* case, and it routes to `read` exactly as a blind caller does.

    ``reads_remaining`` is the envelope's field (§7.1), not a count kept here: the runner reads it
    off the last response it received, so the budget in the decision is the budget the server will
    enforce (§8.4).
    """

    reads_remaining: int
    #: Can the caller look at a raster itself? Default yes — §8.1a's default is the whole point.
    vision_capable: bool = True
    #: How many more rasters its context can hold. Default: `fetch`'s own cap, since a caller
    #: that could not hold one `fetch` could not have asked for one (§7.3).
    image_slots: int = MAX_FETCH_PAGES


@dataclass(frozen=True)
class Decision:
    """A route and the reason for it. ``route is None`` means **neither route is available**."""

    route: str | None
    reason: str

    @property
    def spends(self) -> bool:
        """Whether taking this route bills a model call. `fetch` never does (§7.2.5)."""
        return self.route == READ

    @property
    def cap(self) -> int:
        """The §7.3 page cap of the chosen route — 3 for `read`, 5 for `fetch`."""
        return MAX_READ_PAGES if self.route == READ else MAX_FETCH_PAGES


@dataclass(frozen=True)
class Route:
    """One candidate's route, for the per-page table a reviewer reads."""

    page_id: str
    route: str | None
    reason: str


@dataclass(frozen=True)
class Look:
    """The look step, planned: one route, the pages this call takes, and the ones it defers.

    ``deferred`` is not a refusal and not a truncation — it is the pages that do not fit the
    route's cap and that a **second** call would take. The runner is the party that decides
    whether to make that second call, because on the `read` route it costs another unit of the
    per-question budget (§8.4) and on the `fetch` route it costs nothing.
    """

    decision: Decision
    pages: tuple[str, ...]
    deferred: tuple[str, ...] = ()

    @property
    def route(self) -> str | None:
        return self.decision.route

    @property
    def spends(self) -> bool:
        return self.decision.spends


def decide(caller: Caller, *, pages: int = 1, zoom: bool = False) -> Decision:
    """§8.1a's routing decision. **No VLM call, no raster, no store read** — four comparisons.

    In order:

    1. **A zoom is a `fetch`.** `read` renders one pinned dpi and has no `region` (§7.2.6), so a
       candidate that needs a corner enlarged has exactly one route — and a caller that cannot
       see has none, which is said rather than silently downgraded to a full-page `read`.
    2. **Delegation is required** when the caller cannot look, or when looking would not fit in
       what it has left. Both are §8.1a's *"`read` is for delegation"*, arriving by different
       doors.
    3. **Delegation is unaffordable** when the read budget is spent: the honest answer is that
       there is no route, which the loop turns into `429 budget_exhausted` (§8.4) rather than a
       silent extra call or a fetch the caller cannot hold.
    4. **Otherwise `fetch`** — the default, and the only branch that needs no justification.
    """
    if zoom:
        return (Decision(FETCH, REASON_ZOOM) if caller.vision_capable
                else Decision(None, REASON_ZOOM_UNAVAILABLE))
    if not caller.vision_capable:
        return (Decision(READ, REASON_NOT_VISION_CAPABLE) if caller.reads_remaining > 0
                else Decision(None, REASON_BUDGET_EXHAUSTED))
    if pages > caller.image_slots:
        return (Decision(READ, REASON_CONTEXT_BUDGET) if caller.reads_remaining > 0
                else Decision(None, REASON_BUDGET_EXHAUSTED))
    return Decision(FETCH, REASON_DEFAULT_FETCH)


def plan(page_ids: Sequence[str], caller: Caller, *, zoom: bool = False) -> Look:
    """Route a whole look set, and split it at the route's cap.

    The decision is made **once for the set** and not once per page: `fetch`'s advantage is that
    both pages are in one context (§8.1a), so a set answered half by one route and half by the
    other would be the worst of each — a paid call that cannot be followed up beside a raster the
    agent cannot cross-reference with it.
    """
    pages = tuple(dict.fromkeys(page_ids))
    decision = decide(caller, pages=len(pages), zoom=zoom)
    if decision.route is None:
        return Look(decision=decision, pages=(), deferred=pages)
    return Look(decision=decision, pages=pages[:decision.cap], deferred=pages[decision.cap:])


def routes(page_ids: Sequence[str], caller: Caller, *, zoom: bool = False) -> tuple[Route, ...]:
    """The same decision, per candidate — the table `vsir ask --explain` prints.

    Every row carries the set's route, because that is what will actually happen to it; the rows
    beyond the cap carry ``None`` and the route's own reason is not theirs to claim.
    """
    look = plan(page_ids, caller, zoom=zoom)
    deferred = set(look.deferred)
    return tuple(
        Route(page_id=page_id,
              route=None if page_id in deferred else look.route,
              reason=(REASON_DEFERRED if page_id in deferred and look.route is not None
                      else look.decision.reason))
        for page_id in dict.fromkeys(page_ids)
    )
