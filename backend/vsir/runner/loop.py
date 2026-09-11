"""The loop (Spec §8.1) and the six correction loops (§8.3). Net new — `impl` had no runner.

`impl` had one retrieval function and one endpoint per move; the *sequence* lived in whatever
prompt a caller happened to write. This module is that sequence, in code, and §8.1's three
structural properties are meant to be visible in it rather than asserted about it:

* **narrowing is the same move at three zoom levels** — :meth:`Loop.descend` runs
  `skim_documents` → `skim_sections` → `skim_pages`, each one scoped by the row the last one
  handed back (`next.expand`), and each one free;
* **the expensive step happens once, late, after free narrowing** — nothing in this file calls
  `read` before :meth:`Loop.look`, and `look` is reachable only from a triage that produced pages
  or from the vision branch of §8.1;
* **verification happens after drafting, not before** — :meth:`Loop.verify` runs the gate of §8.4
  on a draft that already exists, which is the only order in which the gate can catch anything.

**What the loop is, mechanically.** :data:`~vsir.runner.triage.TRANSITIONS` is the machine; this
module executes it and takes no path that is not in it. Every state is one method, every method
returns one of §8.1's signals, and the successor comes from
:func:`~vsir.runner.triage.next_state`, which **raises** on a pair it has no edge for. So
safeguard 1 — *"on `sufficient: false`, try the `uncertain` pool before widening scope"* — is not
a line of code here that a later edit could reorder: there is no ``(LOOK, INSUFFICIENT) → WIDEN``
edge to reach.

U021 declared every state and almost every edge; this unit added exactly one,
``(WIDEN, EMPTY_NO_TEXT) → VISION_FIRST``, and the reason is in the table beside it: §8.1's second
empty branch has to be reachable from the **end of the ladder** as well as from a descent that
returned nothing, or a triage that rejected every row it was offered abstains while a page nobody
can read sits unexamined (§8.5, F4).

**It holds no state between questions.** :class:`Loop` is created per question and discarded with
the answer; `scope` and `exclude` are parameters it passes to every rung, and the *only* memory of
the previous move is the value in this object's own fields (C11, §15 Factor VI). Nothing here is
module-level, nothing is cached across calls, and two replicas answering the same question make
the same moves because the moves are a function of the question and the corpus.

**Every tool call goes through the caller's dispatcher** (:data:`Dispatch`), never to a tool
function directly. That is what keeps the budget, the audit line, the argument validation and the
typed refusals in one implementation for every surface (§7.5): the loop is a *caller* of the eight
tools of §7.2 and it is not permitted to be a ninth path into them.

**A refusal is never an abstention.** A 503 mid-loop, an exhausted quota, a model that answered
unusably — each ends the loop as a :class:`Refusal` carrying the tool's own status and code, and
`POST /ask` answers under that status. §7.1: *"`error` means retry or report, and never abstain"*,
because an outage rendered as *"not found in these documents"* is our failure delivered as the
caller's fabricated confidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from vsir import logging as vsir_logging
from vsir.config import MAX_READ_PAGES
from vsir.core.record import UNSEARCHABLE_TRUST
from vsir.runner import answer as answer_module
from vsir.runner import route as route_module
from vsir.runner import triage as triage_module
from vsir.runner.answer import Check, Coverage, Draft, Gated, GateUnavailable
from vsir.runner.triage import (ABSTAIN, ANSWER, BUDGET_EXHAUSTED, CANDIDATES, CLEARED,
                                CONTRADICTED, DESCEND, DRAFT, DRAIN_UNCERTAIN, EMPTY_NO_TEXT,
                                EXHAUSTED, INSUFFICIENT, LOOK, NO_PAGES, POOL_EMPTY, SUFFICIENT,
                                TERMINAL, TRIAGE, VERIFY, VISION_FIRST, WIDEN, WIDENED)
from vsir.serve.envelope import ClaimVerdict, PageHit
from vsir.serve.tools.skim import SKIM_LIMIT, decompose

_log = vsir_logging.get_logger(__name__)

#: The hard bound on how many states one question may pass through. Not a timeout and not a retry
#: count: every path through §8.1 is already bounded — a `read` costs a unit of a budget that only
#: decreases, a widen has finitely many rungs to give up, and a contradiction excludes the page it
#: happened on — so reaching this means the machine cycled, which is a bug in this file rather
#: than a hard question. It raises :class:`LoopBounded` (a 500) instead of abstaining, because
#: *"we stopped looking"* is not *"the corpus does not contain it"* (§7.1, §8.5).
MAX_MOVES = 32

# ── the six correction loops of §8.3, named so a trace and a test can name them ─────────────────

#: **0** — a candidate looks wrong in triage → mark `irrelevant`, `exclude` it. Before any spend.
LOOP_0_EXCLUDE = "loop0_exclude"
#: **1** — a code was misread → stamped `absent` **inside `read`**, automatically (§7.2.6). The
#: loop does not perform this one; it observes that it fired, which is the only honest way to
#: record a correction that happens one layer down.
LOOP_1_READ_STAMP = "loop1_read_stamp"
#: **2** — about to assert a claim → `verify(claims, page_ids)` after `read`. The gate (§8.4).
LOOP_2_VERIFY = "loop2_verify"
#: **3** — `sufficient: false` → try the `uncertain` pool, **then** widen and re-skim.
LOOP_3_SOFT_REJECTION = "loop3_soft_rejection"
#: **4** — `verify` contradicts the draft → try a different page.
LOOP_4_DIFFERENT_PAGE = "loop4_different_page"
#: **5** — nothing found **and** `searchable_ratio < 1` → look at the image-only pages, and
#: `lookup(include_unverified=True)`.
LOOP_5_VISION_ESCALATION = "loop5_vision_escalation"

LOOPS: tuple[str, ...] = (LOOP_0_EXCLUDE, LOOP_1_READ_STAMP, LOOP_2_VERIFY,
                          LOOP_3_SOFT_REJECTION, LOOP_4_DIFFERENT_PAGE,
                          LOOP_5_VISION_ESCALATION)

#: The page rung — the one that returns candidates, and the last move of every descent.
PAGES = "skim_pages"

#: The aggregate rungs the descent narrows through before it, widest first (§7.2.1, §8.1).
AGGREGATES: tuple[str, ...] = ("skim_documents", "skim_sections")

#: The three rungs of the descent, in the order §8.1 puts them.
DESCENT: tuple[str, ...] = (*AGGREGATES, PAGES)


class Move(BaseModel):
    """One state the loop passed through, and what it did there — the trace §13 M6 shows.

    It carries no page text, no image bytes and no draft prose: it is the move-by-move record a
    reviewer reads beside the answer, and the answer is where the content is.
    """

    model_config = ConfigDict(extra="forbid")

    step: int
    state: str
    #: The tool called, or the name of the free decision made (`triage`, `route`, `gate`).
    action: str
    #: One line, for a person: what this move decided and on what evidence.
    detail: str = ""
    #: The signal the state was left on — the second half of the edge that was taken.
    signal: str = ""
    #: Whether this move billed a model call. True on exactly the `read` moves (§8.1a).
    spends: bool = False


class TriageRow(BaseModel):
    """One candidate's mark, as §13 M7's triage panel reads it — :class:`Mark`, on the wire.

    Nothing here is new judgment: it is :class:`~vsir.runner.triage.Mark` field for field, and
    the reason it travels is written into that class already — ``matched`` is *"kept beside it so
    a triage table can be reviewed rather than trusted"*. The console **is** that table, so the
    marks are what it must be handed. The alternative is what M7 would otherwise have to do:
    regex the counts out of a :class:`Move`'s prose ``detail`` and have no page ids for the
    `exclude` set at all — a second declaration of this contract, in a language that cannot
    fail a test when the sentence is reworded.

    No `score`, no confidence and no ordering signal beyond ``rank``, which is the ordinal the
    skim already returned (§7.6).
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    mark: Literal["relevant", "uncertain", "irrelevant"]
    #: Which of §8.2's rules produced the mark — one of `triage.REASONS`, never free text.
    reason: str
    #: The candidate's position in the fused list it came from. An ordinal, not a confidence.
    rank: int
    #: The surfaces that found the page, e.g. `["dense", "lexical"]` — the row's own `why`.
    why: list[str] = Field(default_factory=list)
    #: The terms of the question this page's summary actually showed: the **evidence** for the
    #: mark, which is what makes the table reviewable rather than a label to be trusted.
    matched: list[str] = Field(default_factory=list)
    #: Safeguard 4 fired — the page prints a code the question named, so no summary was consulted.
    promoted: bool = False

    @classmethod
    def of(cls, mark: triage_module.Mark) -> "TriageRow":
        return cls(page_id=mark.page_id, mark=mark.mark, reason=mark.reason, rank=mark.rank,
                   why=list(mark.why), matched=list(mark.matched), promoted=mark.promoted)


class TriageTable(BaseModel):
    """The tri-state pass the loop finished on, and the `exclude` set it built (§8.2, §13 M7).

    **The last pass, not every pass.** A question that drained the pool or widened triages more
    than once, and each pass is already recorded as its own :class:`Move` in the trace; this is
    the table that decided the answer, which is the one a reviewer is looking at the answer
    beside. ``exclude`` is the loop's *cumulative* set rather than this pass's `irrelevant` ids,
    because that is what the next skim was actually sent — and after Loop 4 it also contains the
    page a rejected claim was cited on.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = ""
    rows: list[TriageRow] = Field(default_factory=list)
    #: The page ids that go into the next rung's ``exclude`` — the `irrelevant` ones, and never
    #: the `uncertain` pool: excluding the pool would delete the fallback the tri-state exists to
    #: keep (§8.2).
    exclude: list[str] = Field(default_factory=list)
    #: Safeguard 2 applied to this set: three candidates or fewer, so none was filtered.
    small_set: bool = False


class Refusal(BaseModel):
    """A typed refusal that ended the loop, with the status the surface answers under.

    The payload is the refusing tool's own body (`{"error": …, "detail": …, …}`), passed through
    rather than re-worded: `budget_exhausted`, `qdrant_unavailable` and `vlm_unavailable` are
    three different next moves for the caller (§11.3), and the loop is not a place that should be
    able to blur them.
    """

    model_config = ConfigDict(extra="forbid")

    status: int
    error: str
    detail: str = ""
    payload: dict = Field(default_factory=dict)

    @classmethod
    def of(cls, outcome: Any, *, tool: str) -> "Refusal":
        payload = dict(outcome.payload or {})
        return cls(status=int(outcome.status),
                   error=str(payload.get("error") or "tool_refused"),
                   detail=str(payload.get("detail") or f"{tool} refused"),
                   payload=payload)


class LoopBounded(RuntimeError):
    """:data:`MAX_MOVES` states without reaching a terminal. A bug here, never an abstention."""


#: One tool call, through the caller's dispatcher: ``(tool_name, arguments) -> outcome``, where the
#: outcome carries ``status`` (HTTP, on every transport), ``payload`` and ``refused``. Typed
#: loosely on purpose: `vsir.serve.app` imports **this** module, so naming its `ToolOutcome` here
#: would be an import cycle — and the loop genuinely needs nothing from it but those three fields.
Dispatch = Callable[[str, Mapping[str, Any]], Any]


@dataclass(frozen=True)
class Outcome:
    """Everything one question produced. A value: the loop that made it is already discarded."""

    question: str
    #: The terminal state — :data:`~vsir.runner.triage.ANSWER` or
    #: :data:`~vsir.runner.triage.ABSTAIN` — or the state a refusal happened in.
    state: str
    answer: answer_module.Answer | None = None
    abstention: answer_module.Abstention | None = None
    refusal: Refusal | None = None
    trace: tuple[Move, ...] = ()
    #: Which of §8.3's six loops fired, in order of first firing.
    loops: tuple[str, ...] = ()
    #: The gate's call log — one row per `(claim, page)` pair actually verified (§8.4).
    checks: tuple[Check, ...] = ()
    #: Paid `read` calls this question made. One is the target (§8.4).
    reads: int = 0
    #: The caller's standing quota after the last call, off the last envelope (§7.1).
    reads_remaining: int = 0
    route: str | None = None
    #: The tri-state pass the loop finished on, and the `exclude` set it built (§8.2, §13 M7).
    #: ``None`` when nothing was ever triaged — a submitted draft, or an abstention that happened
    #: before a rung returned a candidate. An empty table and *no table* are different facts.
    triage: TriageTable | None = None
    coverage: Coverage = Coverage()
    #: The scope the loop finished on — after descending, and after any widening. Echoed back to
    #: the caller because this service holds no session: the scope is the whole truth about what
    #: was searched, and it has to travel with the answer (F8, C11, §15 Factor VI).
    effective_scope: Mapping[str, Any] = field(default_factory=dict)
    #: The gate's full output, including rejections. Held for the trace and the tests; the
    #: response body renders :attr:`answer` and never a rejected draft (§8.4).
    gated: Gated | None = None

    @property
    def answered(self) -> bool:
        return self.answer is not None

    @property
    def rejections(self) -> tuple[answer_module.Rejection, ...]:
        return self.gated.rejections if self.gated is not None else ()


def as_hits(payload: Mapping[str, Any]) -> tuple[PageHit, ...]:
    """`lookup`'s hits, as triage rows — §8.1's *"handle? yes → lookup → TRIAGE"*.

    A `lookup` hit is a page whose **extracted text** verifiably contains the phrase that was
    asked for (I2, I3), so ``why`` is ``["lexical"]``: the lexical surface is what found it, and
    saying so is what lets safeguard 4 — *"query contains an exact identifier + hit `why` is
    `lexical` → bypass triage"* — fire on this branch without a second rule (§8.2). The summary is
    empty because a `LookupHit` carries none, and it is not consulted: the page prints the code
    that was asked for.
    """
    return tuple(
        PageHit(page_id=str(hit.get("page_id") or ""),
                printed_page_no=str(hit.get("printed_page_no") or ""),
                page_kind=str(hit.get("page_kind") or "prose"),
                why=[triage_module.LEXICAL],
                rank=rank,
                text_trust=hit.get("text_trust") or "no_text")
        for rank, hit in enumerate(payload.get("hits") or (), start=1)
        if hit.get("page_id")
    )


@dataclass
class Loop:
    """One question's pass through §8.1's machine. Created per question, discarded with it.

    Mutable, and the mutation is the point: this object *is* the loop's working memory — the scope
    it has descended to, the pages it has excluded, the candidates it is holding, what it has
    spent. None of it outlives the call, none of it is shared between callers, and none of it is
    at module level (C11, §15 Factor VI, and the AST scan in the conformance suite).
    """

    question: str
    call: Dispatch
    reads_per_question: int
    #: **The caller's** scope, and it is never widened away: the caller asked for it (F8, C11).
    #: What widening gives up is the loop's *own* narrowing — see :attr:`zoom`.
    given: dict[str, Any] = field(default_factory=dict)
    excluded: list[str] = field(default_factory=list)
    limit: int = SKIM_LIMIT
    #: Triage telemetry (§8.2, §11.4). ``None`` disables it and changes nothing else.
    sink: triage_module.Sink | None = triage_module.log_sink

    #: How many of the two aggregate rungs the descent narrows through — the zoom level, and the
    #: only thing :meth:`widen` changes. Starting at both, it goes to one (the binder alone) and
    #: then to none (the caller's scope, searched flat), and there is nothing wider than that.
    #:
    #: This is what makes *"widen and re-skim"* terminate. Dropping a key out of a scope the
    #: descent then re-derives is not widening at all: the next descent asks the same section
    #: rung for the same best row and puts it straight back, which is a loop that narrows exactly
    #: as fast as it widens and never reaches a terminal state.
    zoom: int = len(AGGREGATES)
    #: The scope the last descent actually searched, for the echoed ``effective_scope``.
    scope: dict[str, Any] = field(default_factory=dict)
    #: One image-only page per blind binder, from the document rung's disclosure row
    #: (`preview.page_id`, §7.1). The floor under Loop 5: it is what makes the escalation
    #: possible on a question whose every word is a code nothing prints.
    previews: list[str] = field(default_factory=list)

    state: str = DESCEND
    hits: tuple[PageHit, ...] = ()
    triaged: triage_module.Triage | None = None
    look_set: tuple[str, ...] = ()
    #: The pages the most recent look actually covered — the draft's citations.
    looking: tuple[str, ...] = ()
    looked: list[str] = field(default_factory=list)
    coverage: Coverage = Coverage()
    reads: int = 0
    #: The caller's standing quota, off the last envelope. ``-1`` until the first call, because
    #: *"not asked yet"* and *"none left"* must not be the same value on the first route decision.
    quota: int = -1
    moves: list[Move] = field(default_factory=list)
    loops: list[str] = field(default_factory=list)
    read_result: Mapping[str, Any] | None = None
    draft: Draft | None = None
    gated: Gated | None = None
    refusal: Refusal | None = None
    route: str | None = None
    #: The reason a terminal abstention would give, when neither a rejection nor an insufficient
    #: read has already settled it (:meth:`reason`).
    stopped: str = answer_module.NOT_FOUND
    rejected: int = 0
    insufficient: bool = False

    # ── the shared plumbing ─────────────────────────────────────────────────────────────────────

    def note(self, action: str, detail: str, *, spends: bool = False) -> None:
        self.moves.append(Move(step=len(self.moves) + 1, state=self.state, action=action,
                               detail=detail, spends=spends))

    def fired(self, loop: str) -> None:
        """Record that one of §8.3's loops fired. First firing only — the order is what informs."""
        if loop not in self.loops:
            self.loops.append(loop)

    def dispatch(self, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """One tool call. ``None`` means it was refused and :attr:`refusal` now says how.

        The quota is read off **every** envelope, free or paid, because §7.1 puts
        ``reads_remaining`` on all of them and the route decision has to be made against the
        budget the server will actually enforce rather than against the loop's own count (§8.4).
        """
        outcome = self.call(tool, dict(arguments))
        if outcome.refused:
            self.refusal = Refusal.of(outcome, tool=tool)
            self.note(tool, f"REFUSED {self.refusal.error}: {self.refusal.detail}")
            return None
        payload = outcome.payload
        if "reads_remaining" in payload:
            self.quota = int(payload["reads_remaining"])
        return payload

    @property
    def budget_left(self) -> int:
        """The lower of the two ceilings — §8.4's per-question one and §7.3's per-caller quota.

        A route planned against the larger of them plans a call the server refuses; planned
        against the smaller it reports the truth: `read` is available, or it is not.
        """
        per_question = max(0, self.reads_per_question - self.reads)
        return per_question if self.quota < 0 else min(per_question, self.quota)

    @property
    def caller(self) -> route_module.Caller:
        """Who is looking, for §8.1a's route decision — and it is **not** vision-capable.

        The party that writes the draft in this loop is this process: Python, holding an envelope.
        It cannot look at a raster, so §8.1a's *"or when the caller is not vision-capable"* is the
        branch that applies and `read` — delegation to a sub-model — is the route. That is not a
        downgrade of §8.1a's default; it is the default's own condition (*"when the runner is
        itself a vision-capable model, it looks at the page"*) being false here. A vision-capable
        agent takes the `fetch` route in **its own** context and brings its draft back through
        :func:`gate_submitted`, which is why §8.4 is server-side and unconditional.
        """
        return route_module.Caller(reads_remaining=self.budget_left, vision_capable=False)

    # ── DESCEND (§8.1) ──────────────────────────────────────────────────────────────────────────

    def descend(self) -> str:
        """*"handle? yes → lookup"*, otherwise the three free rungs. Ends with page candidates.

        The handle branch is first because it is the cheapest and the strongest: a question naming
        a printed code can be answered by asking the exact surface which pages print it, and a hit
        there is a page whose own text carries the phrase (I2, I3). A `not_found` from `lookup` is
        **not** the end — §7.1 puts `next.suggest` on it precisely because a different *move* can
        still answer, and abstaining on a phrasing accident is F6's injury — so the descent
        continues into the ladder.

        The empty branch is chosen on the image-only pages that are **still unexamined** rather
        than on ``pages_no_text`` raw. The two are the same number on the first descent, which is
        the case §8.1 describes; they differ only after Loop 5 has already looked, and there the
        refinement is what stops the loop escalating a second time to pages it has read (§8.5's
        inequality is over the same two numbers).
        """
        # The caller's scope is in force from the first call, and it is what
        # ``effective_scope`` echoes on the handle branch — which searches inside it and
        # narrows no further (F8, C11).
        self.scope = dict(self.given)
        handles = decompose(self.question).identifiers
        if handles and not self.looked and self.zoom == len(AGGREGATES):
            payload = self.dispatch("lookup", {"label": handles[0],
                                               "scope": dict(self.given)})
            if payload is None:
                return ""
            self.coverage = self.coverage.merge(Coverage.of(payload))
            found = as_hits(payload)
            self.note("lookup", f"handle {handles[0]!r} → status {payload['status']} · "
                                f"{len(found)} page(s) print it · total {payload['total']}")
            if found:
                self.hits = found
                return CANDIDATES
            suggest = (payload.get("next") or {}).get("suggest") or []
            self.note("lookup", f"no page prints that phrase — descending the ladder instead "
                                f"(next.suggest {suggest})")

        scope = dict(self.given)
        rungs = (*AGGREGATES[:self.zoom], PAGES)
        payload: Mapping[str, Any] | None = None
        for rung in rungs:
            arguments: dict[str, Any] = {"query": self.question, "scope": dict(scope),
                                         "exclude": list(self.excluded)}
            if rung == PAGES:
                arguments["limit"] = self.limit
            payload = self.dispatch(rung, arguments)
            if payload is None:
                return ""
            self.coverage = self.coverage.merge(Coverage.of(payload))
            rows = payload.get("hits") or []
            self.note(rung, f"zoom {self.zoom} · scope {dict(scope) or {}} → status "
                            f"{payload['status']} · {len(rows)} row(s) · total "
                            f"{payload['total']} · weak {str(payload['weak']).lower()}")
            if rung == AGGREGATES[0]:
                self.remember_blind_spots(payload)
            if rung != PAGES:
                scope = self.descend_into(scope, payload)
        self.scope = scope

        self.hits = tuple(PageHit.model_validate(hit)
                          for hit in ((payload or {}).get("hits") or ()))
        if self.hits:
            return CANDIDATES
        return triage_module.empty_signal(self.coverage.unexamined)

    def descend_into(self, scope: Mapping[str, Any],
                     payload: Mapping[str, Any]) -> dict[str, Any]:
        """The next rung's scope: this rung's best row's ``next.expand``, added to what we hold.

        The **runner** picks the group to descend into and no tool ever does (§7.6). The rows are
        already ordered by ``(best_rank, -pages_matched)``, so *"the first one"* is a decision
        about the published ranking rather than a second ranking of our own.
        """
        hits = list(payload.get("hits") or ())
        expand = (hits[0].get("next") or {}).get("expand") if hits else None
        return {**scope, **expand} if expand else dict(scope)

    def remember_blind_spots(self, payload: Mapping[str, Any]) -> None:
        """Keep the one page per blind binder the document rung already handed us (§7.1, F4).

        A `searchable_ratio: 0.00` row is *"the one place a scanned document can be seen"*, and it
        carries a `preview.page_id` for exactly that reason. Keeping it costs nothing — the call
        has already happened — and it is what lets Loop 5 escalate on a question whose every word
        is a code the corpus does not print, where a second skim would be filtered by that code
        and come back with nothing to look at.
        """
        for row in (payload.get("hits") or ()):
            if float(row.get("searchable_ratio") or 0.0) >= 1.0:
                continue
            page_id = str(((row.get("preview") or {}).get("page_id")) or "")
            if page_id and page_id not in self.previews:
                self.previews.append(page_id)

    # ── TRIAGE (Loop 0, §8.2) ───────────────────────────────────────────────────────────────────

    def triage(self) -> str:
        """Mark the candidates, and carry the `irrelevant` ones into the next skim's ``exclude``.

        Pages already looked at are dropped before marking rather than excluded after: they are
        not candidates any more, and leaving them in would let safeguard 2 (*"do not filter a
        small set"*) re-promote a page whose `read` has already been paid for.
        """
        seen = set(self.looked) | set(self.excluded)
        pending = tuple(hit for hit in self.hits if hit.page_id not in seen)
        result = triage_module.triage(pending, query=self.question)
        self.triaged = result
        triage_module.record(result, sink=self.sink, question=self.question)
        if result.exclude:
            self.fired(LOOP_0_EXCLUDE)
            self.excluded.extend(page for page in result.exclude if page not in self.excluded)
        self.look_set = result.look_set
        self.note("triage",
                  f"{len(result.marks)} candidate(s) → relevant {len(result.relevant)} · "
                  f"uncertain {len(result.uncertain)} (the pool, retained) · irrelevant "
                  f"{len(result.irrelevant)}"
                  f"{' · safeguard 2: ≤3 candidates, none filtered' if result.small_set else ''}")
        return result.signal

    # ── LOOK (§8.1a, §7.2.6) ────────────────────────────────────────────────────────────────────

    def look(self) -> str:
        """The one expensive move, planned by §8.1a, capped by §7.3, and made once.

        The route is decided for the **whole set** rather than per page (:func:`route.plan`), and
        the pages past the route's cap are *deferred*, never silently truncated: the loop is the
        party that decides whether to make a second call, and on this route a second call is
        another unit of §8.4's budget.

        No route means no budget, and that is a **refusal** rather than an abstention: §8.4 asks
        for `429 budget_exhausted`, *"never a silent extra call and never an answer composed from
        a page the model said did not answer"*. The machine still takes its
        ``(LOOK, budget_exhausted) → ABSTAIN`` edge — there is nowhere else to go — and the
        refusal beside it is what the surface answers with.
        """
        look = route_module.plan(self.look_set, self.caller)
        self.route = look.route
        if look.route is None:
            self.note("route", f"no route: {look.decision.reason} · budget_left "
                               f"{self.budget_left} (per-question {self.reads_per_question}, "
                               f"caller quota {self.quota})")
            self.refusal = Refusal(
                status=429, error="budget_exhausted",
                detail=f"the per-question read budget is spent: {self.reads} of "
                       f"{self.reads_per_question} used (VSIR_READS_PER_QUESTION), caller quota "
                       f"{max(0, self.quota)}. This is a refusal and not an abstention — the "
                       f"pages that would answer were never looked at (§8.4)",
                payload={"error": "budget_exhausted", "reads": self.reads,
                         "reads_per_question": self.reads_per_question})
            return BUDGET_EXHAUSTED
        self.note("route", f"{look.route} over {list(look.pages)} · {look.decision.reason}"
                           f"{f' · deferred {list(look.deferred)}' if look.deferred else ''}")

        payload = self.dispatch("read", {"page_ids": list(look.pages), "question": self.question})
        if payload is None:
            return ""
        self.reads += 1
        result = payload["result"]
        self.read_result = result
        self.looking = look.pages
        self.looked.extend(page for page in look.pages if page not in self.looked)
        scanned = sum(1 for one in (result.get("page_provenance") or ())
                      if str(one.get("text_trust") or "no_text") in UNSEARCHABLE_TRUST)
        self.coverage = self.coverage.looked_at(scanned)
        stamps = result.get("codes") or []
        if any(str(stamp.get("status")) == "absent" for stamp in stamps):
            # Loop 1, observed rather than performed: the stamp happened inside `read` (§7.2.6),
            # automatically, and this is the only place a trace can say that it fired.
            self.fired(LOOP_1_READ_STAMP)
        self.note("read", f"{len(look.pages)} page(s) at the pinned dpi · sufficient "
                          f"{str(result['sufficient']).lower()} · {len(stamps)} code(s) stamped · "
                          f"flags {result.get('flags') or []} · {scanned} page(s) image-only",
                  spends=True)
        if not result["sufficient"]:
            self.insufficient = True
            self.fired(LOOP_3_SOFT_REJECTION)
            return INSUFFICIENT
        return SUFFICIENT

    # ── DRAFT (§8.1 — after the look, before any check) ─────────────────────────────────────────

    def make_draft(self) -> str:
        """The draft: the sub-model's own bounded extract, and every code in it, unchecked.

        Nothing is rewritten and nothing is added — see :attr:`~vsir.runner.answer.Answer.text`.
        The claims are the union of what `read` declared and what its sentence actually contains
        (:func:`~vsir.runner.answer.claims_from`), because a code that appears in the prose and
        not in the ``codes`` list would otherwise reach a reader with nothing having checked it.
        """
        result = self.read_result or {}
        pages = list(self.looking)
        claims = answer_module.claims_from(result.get("codes") or [],
                                           text=str(result.get("extract") or ""), pages=pages)
        self.draft = Draft(text=str(result.get("extract") or ""), claims=list(claims),
                           pages=pages, route=route_module.READ,
                           sufficient=bool(result.get("sufficient")))
        self.note("draft", f"{len(self.draft.text)} character(s) from {len(pages)} page(s) · "
                           f"{len(claims)} claim(s) to check "
                           f"({len(result.get('codes') or [])} declared by `read`)")
        return CANDIDATES

    # ── VERIFY (the gate, §8.4, I8) ─────────────────────────────────────────────────────────────

    def verify(self) -> str:
        """The gate, unconditionally, per `(claim, page)`. Loop 2, and Loop 4 on a contradiction.

        A `verify` that could not run is not a verdict (:class:`GateUnavailable`): the loop ends
        as a refusal carrying the tool's own status, because a check we could not make must never
        become *"that code is not on the page"* (§7.1, §11.3).
        """
        if self.draft is None:
            raise LoopBounded("the gate was reached with no draft to gate")
        self.fired(LOOP_2_VERIFY)
        try:
            self.gated = answer_module.gate(self.draft, verify=self.verifier())
        except GateUnavailable as unavailable:
            self.refusal = unavailable.refusal or Refusal(
                status=503, error="verify_unavailable", detail=str(unavailable))
            self.note("gate", f"REFUSED {self.refusal.error}: the check could not run, so no "
                              f"verdict exists — this is an error and never an abstention (§7.1)")
            return ""
        self.note("gate", f"{len(self.gated.checks)} (claim, page) check(s) · rendered "
                          f"{len(self.gated.rendered)} · rejected {len(self.gated.rejections)} · "
                          f"badges {sorted(set(self.gated.badges))}")
        if self.gated.cleared:
            return CLEARED

        # Loop 4 — *"`verify` contradicts the draft → try a different page"*. The pages the
        # rejected claims were cited on are excluded, so the re-triage cannot offer them again,
        # and the draft that carried them is discarded whole (§8.4): not one code of it renders.
        self.rejected += len(self.gated.rejections)
        self.fired(LOOP_4_DIFFERENT_PAGE)
        self.excluded.extend(one.page_id for one in self.gated.rejections
                             if one.page_id and one.page_id not in self.excluded)
        self.draft = None
        self.note("gate", f"draft rejected — {len(self.gated.rejections)} claim(s) the check "
                          f"would not clear. Excluding the page(s) they were cited on and trying "
                          f"a different page; not one word of that draft renders")
        return CONTRADICTED

    def verifier(self) -> answer_module.Verifier:
        """The gate's one check, wired to the dispatcher — one `verify` call per `(claim, page)`.

        Bound here rather than accepted as an argument, so there is no parameter on this surface
        through which a caller could hand the gate a check of its own: §8.4 is server-side, and a
        pluggable verifier would be the flag §8.4 says does not exist.
        """
        def verify(claim: str, page_id: str) -> ClaimVerdict:
            outcome = self.call("verify", {"claims": [claim], "page_ids": [page_id]})
            payload = dict(outcome.payload or {})
            if outcome.refused:
                raise GateUnavailable(
                    f"the gate's check did not run: {payload.get('error')}",
                    claim=claim, page_id=page_id,
                    refusal=Refusal.of(outcome, tool="verify"))
            verdicts = (payload.get("result") or {}).get("claims") or {}
            if claim not in verdicts:
                raise GateUnavailable(
                    "the gate's check returned no verdict for the claim it asked about",
                    claim=claim, page_id=page_id,
                    refusal=Refusal(status=502, error="verify_incomplete",
                                    detail="`verify` returned no verdict for the claim the gate "
                                           "asked about, so there is nothing to gate on"))
            if "reads_remaining" in payload:
                self.quota = int(payload["reads_remaining"])
            return ClaimVerdict.model_validate(verdicts[claim])

        return verify

    # ── DRAIN_UNCERTAIN and WIDEN (Loop 3, safeguard 1) ─────────────────────────────────────────

    def drain(self) -> str:
        """Safeguard 1: look again **with what is already in hand**, and run no new search.

        This is the whole reason triage is tri-state. A binary keep/drop would have discarded the
        `uncertain` rows, and the only repair left for a wrong drop is a re-skim — which returns
        the same summaries that hid the answer the first time (§8.2).

        Two pools, in this order, and the order is the only judgement in this method:

        1. the **`relevant` pages that have not been looked at yet** — a triage of ten candidates
           against a three-page read cap defers seven of them, and those are not a fallback, they
           are the rest of the answer to the same question;
        2. then the **`uncertain` pool**, which is safeguard 1's own instruction.

        Widening comes only after both are empty, which is what *"try `uncertain` **before**
        widening scope"* means — and it is the table's edge, not this method's ``if``: there is no
        ``(LOOK, INSUFFICIENT) → WIDEN`` transition to reach.
        """
        seen = set(self.looked) | set(self.excluded)
        held = self.triaged.relevant + self.triaged.uncertain if self.triaged else ()
        pool = [one.page_id for one in held if one.page_id not in seen]
        if not pool:
            self.note("drain", "the fallback pool is empty — widening is the next move, and only "
                               "now (safeguard 1)")
            return POOL_EMPTY
        self.fired(LOOP_3_SOFT_REJECTION)
        self.look_set = tuple(pool[:MAX_READ_PAGES])
        held = len(pool) - len(self.look_set)
        self.note("drain", f"draining the pool before widening: {list(self.look_set)}"
                           f"{f' · {held} held back by the read cap' if held else ''}")
        return CANDIDATES

    def widen(self) -> str:
        """Zoom out one rung and re-descend — Loop 3's second half.

        Widening is giving up **the loop's own narrowing**, never the caller's scope: at zoom 2
        the descent picks a binder and then a chapter inside it, at zoom 1 the binder alone, at
        zoom 0 the caller's scope searched flat. The exclusions survive every step, so each
        re-skim is asked a strictly wider question and answers with rows the last one could not
        reach.

        When there is no rung left to give up, the corpus has been searched at its widest and the
        honest outcome is an abstention naming what was covered (§8.5).
        """
        if self.zoom > 0:
            self.zoom -= 1
            self.note("widen", f"zooming out to {self.zoom} aggregate rung(s) — "
                               f"{'the binder alone' if self.zoom else 'the whole scope, flat'} "
                               f"· re-skimming with {len(self.excluded)} exclusion(s)")
            self.fired(LOOP_3_SOFT_REJECTION)
            return WIDENED
        # The ladder is spent, and before giving up: is there a page nobody could read? §8.1's
        # second empty branch belongs here too. A triage that rejected every row it was offered
        # has found nothing, and abstaining while an image-only page sits unexamined is
        # concluding absence from a corpus that was never searched (§8.5's own inequality).
        # Once, because Loop 5 records that it fired and a second escalation would re-offer the
        # pages the first one already read.
        if self.coverage.unexamined and LOOP_5_VISION_ESCALATION not in self.loops:
            self.note("widen", f"the ladder is spent, and {self.coverage.unexamined} image-only "
                               f"page(s) have still not been looked at — vision first, then a "
                               f"conclusion (§8.1, §8.5)")
            return EMPTY_NO_TEXT
        self.stopped = answer_module.SCOPE_EXHAUSTED
        self.note("widen", f"the scope is already as wide as it goes ({dict(self.given) or {}}) — "
                           f"there is nothing wider to search")
        return EXHAUSTED

    # ── VISION_FIRST (Loop 5, §8.1's second empty branch) ───────────────────────────────────────

    def vision_first(self) -> str:
        """Loop 5: nothing found **and** the scope holds pages nobody can read — look at those.

        Both moves §8.3 asks for, in the order that makes the second one useful:

        1. **`lookup(include_unverified=True)`** — the opt-in `vlm_codes` surface, where a code a
           model read off a scanned page lives (D3). Those hits are permanently
           ``verified: false`` and can never be an answer, but they are the one text-shaped
           pointer *into* the blind spot;
        2. **the escalation itself** — a skim of each blind binder **scoped to the pages that have
           no text layer at all** (`has_text: False`, an indexed key of §5.4), plus the one page
           per binder the document rung already disclosed (:meth:`remember_blind_spots`).

        **Two things about that scope, and both are the point of this branch.** It is a *coverage*
        query rather than a relevance one: `has_text: False` names the blind spot by construction,
        so the escalation reaches those pages whether or not they happen to rank in the top ten of
        a prose search — and under-escalating here is how an abstention gets written about pages
        the loop could have looked at (F4, R1). And the query drops the **identifiers**, because an
        image-only page has no text: a query carrying a printed code is filtered — by the exact
        phrase, correctly — to nothing on exactly the pages being reached for. When the question is
        nothing *but* a code the prose is empty and there is no skim to make, which is why the
        disclosed preview page is kept as the floor.

        Nothing here relaxes the exact surface: no code is matched loosely anywhere, and no page
        found this way can support a claim on its own — every code read off it comes back
        `unverifiable` and renders with the *read from image* badge, or not at all (§8.4, R2).

        §8.5 is why this branch exists at all: while these pages are unexamined, *"not in these
        documents"* is a sentence this system is not allowed to say.
        """
        self.fired(LOOP_5_VISION_ESCALATION)
        split = decompose(self.question)
        label = split.identifiers[0] if split.identifiers else self.question
        payload = self.dispatch("lookup", {"label": label, "scope": dict(self.given),
                                           "include_unverified": True})
        if payload is None:
            return ""
        unverified = [str(hit.get("page_id") or "")
                      for hit in (payload.get("unverified_hits") or ())]
        self.note("lookup", f"include_unverified=True on {label!r} → {len(unverified)} "
                            f"unverified hit(s) on the `vlm_codes` surface — a pointer into the "
                            f"blind spot, never an answer (D3)")

        candidates = [page for page in unverified if page]
        for doc_id in (self.coverage.blind_docs or self.coverage.docs):
            if len(candidates) >= MAX_READ_PAGES or not split.prose.strip():
                break
            rows = self.dispatch("skim_pages", {"query": split.prose,
                                                "scope": {**self.given, "doc_id": doc_id,
                                                          "has_text": False},
                                                "exclude": list(self.excluded),
                                                "limit": self.limit})
            if rows is None:
                return ""
            # Every row is image-only by construction; the trust check is kept as the belt, so a
            # page that reached this list some other way still cannot be treated as searchable.
            blind = [str(hit.get("page_id") or "") for hit in (rows.get("hits") or ())
                     if str(hit.get("text_trust") or "no_text") in UNSEARCHABLE_TRUST]
            self.note("skim_pages", f"{doc_id}: the pages with no text layer, asked with the "
                                    f"prose alone ({split.prose!r}) → "
                                    f"{len(rows.get('hits') or ())} row(s), {len(blind)} of them "
                                    f"image-only")
            candidates.extend(page for page in blind if page)
        candidates.extend(self.previews)

        seen = set(self.looked) | set(self.excluded)
        pending = [page for page in dict.fromkeys(candidates) if page and page not in seen]
        if not pending:
            self.stopped = answer_module.NO_PAGES
            self.note("vision", "no image-only page to look at either — the blind spot is "
                                "disclosed and there is nothing in it to read")
            return NO_PAGES
        self.look_set = tuple(pending[:MAX_READ_PAGES])
        self.note("vision", f"escalating to vision on {list(self.look_set)} — the pages the text "
                            f"search could not read")
        return CANDIDATES

    # ── the driver ──────────────────────────────────────────────────────────────────────────────

    def step(self) -> str:
        """Run the current state, and return the signal it produced. One state, one method."""
        return {
            DESCEND: self.descend,
            TRIAGE: self.triage,
            LOOK: self.look,
            DRAFT: self.make_draft,
            VERIFY: self.verify,
            DRAIN_UNCERTAIN: self.drain,
            WIDEN: self.widen,
            VISION_FIRST: self.vision_first,
        }[self.state]()

    def reason(self) -> str:
        """Which of §8.5's reasons an abstention here would give, most specific first.

        A rejected draft outranks everything: the corpus **did** hold candidate pages and the
        answer was refused because its codes did not check out, which is a different thing for a
        reader to know than *"nothing matched"*. An insufficient read comes next — the pages were
        looked at and they do not answer — and only then the reason the terminal state recorded.
        """
        if self.rejected:
            return answer_module.REJECTED
        if self.insufficient:
            return answer_module.INSUFFICIENT
        return self.stopped

    def triage_table(self) -> TriageTable | None:
        """The pass the loop finished on, as :class:`TriageTable` — or ``None`` if it never ran.

        ``None`` and an empty table say different things and the console renders them
        differently: *"nothing was ever offered to triage"* is a descent that found no candidate,
        and *"three rows, all `irrelevant`"* is a triage that rejected what it was offered. §7.1's
        rule about the four absences is the same rule one layer in.
        """
        if self.triaged is None:
            return None
        return TriageTable(
            query=self.triaged.query,
            rows=[TriageRow.of(mark) for mark in self.triaged.marks],
            exclude=list(self.excluded),
            small_set=self.triaged.small_set,
        )

    def outcome(self) -> Outcome:
        """The loop's result, composed once at the end from what the states recorded."""
        answered = self.state == ANSWER and self.gated is not None and self.gated.cleared
        abstained = self.state == ABSTAIN and self.refusal is None
        return Outcome(
            question=self.question,
            state=self.state,
            answer=self.gated.answer() if answered else None,
            abstention=(answer_module.abstention(self.coverage, reason=self.reason(),
                                                 rejected=self.rejected)
                        if abstained else None),
            refusal=self.refusal,
            trace=tuple(self.moves),
            loops=tuple(self.loops),
            checks=self.gated.checks if self.gated is not None else (),
            reads=self.reads,
            reads_remaining=max(0, self.quota),
            route=self.route,
            triage=self.triage_table(),
            coverage=self.coverage,
            effective_scope=dict(self.scope),
            gated=self.gated,
        )

    def drive(self) -> Outcome:
        """§8.1's machine, executed: state → signal → :func:`next_state`, until a terminal.

        The bound is :data:`MAX_MOVES` and reaching it raises. An unknown ``(state, signal)`` pair
        raises too — :class:`~vsir.runner.triage.UnknownTransition`, from the table rather than
        from here — because a machine that fell through to *"keep going"* would answer from
        wherever it happened to be, which is how a runner drafts from pages triage rejected.
        """
        moves = 0
        while self.state not in TERMINAL:
            if moves >= MAX_MOVES:
                raise LoopBounded(
                    f"{MAX_MOVES} moves without reaching a terminal state on "
                    f"{self.question!r}; the machine cycled: "
                    f"{[move.state for move in self.moves]}")
            moves += 1
            signal = self.step()
            if signal:
                self.moves[-1] = self.moves[-1].model_copy(update={"signal": signal})
                self.state = triage_module.next_state(self.state, signal)
            if self.refusal is not None:
                # A refused tool call, or a budget that is spent. Never an abstention: an outage
                # reported as an absence is our failure delivered as the caller's fabricated
                # confidence (§7.1, §11.3).
                break
        outcome = self.outcome()
        _log.info("ask", state=self.state, moves=len(self.moves), loops=list(self.loops),
                  reads=self.reads, reads_remaining=outcome.reads_remaining, route=self.route,
                  answered=outcome.answered, rejected=self.rejected,
                  checks=len(outcome.checks),
                  refusal=self.refusal.error if self.refusal else "",
                  pages_no_text=self.coverage.pages_no_text,
                  pages_no_text_read=self.coverage.pages_no_text_read)
        return outcome


def run(question: str, *, call: Dispatch, reads_per_question: int,
        scope: Mapping[str, Any] | None = None, exclude: Sequence[str] = (),
        limit: int = SKIM_LIMIT,
        sink: triage_module.Sink | None = triage_module.log_sink) -> Outcome:
    """Answer one question, or abstain, or refuse — §8.1 end to end. The entry point.

    ``call`` is the caller's dispatcher, so every move is a real tool call with the release's
    budget, audit line and typed refusals in front of it (§7.5). ``reads_per_question`` is §8.4's
    hard ceiling; the caller's standing quota is read off the envelopes and the lower of the two
    binds. ``scope`` and ``exclude`` are the caller's, echoed into every rung and held nowhere
    (C11).

    A question with no words is refused before any call: an empty query is a `400` from the rungs
    themselves, and reaching that conclusion after three round trips would be a worse version of
    the same refusal.
    """
    if not (question or "").strip():
        return Outcome(question=question, state=ABSTAIN,
                       refusal=Refusal(status=400, error="question_required",
                                       detail="`POST /ask` needs a question: the loop of §8.1 "
                                              "narrows against one and `read` is keyed on it "
                                              "(§6.3, F19)"))
    return Loop(question=question, call=call, reads_per_question=reads_per_question,
                given=dict(scope or {}), excluded=list(exclude), limit=limit, sink=sink).drive()


def gate_submitted(draft: Draft, *, question: str, call: Dispatch,
                   reads_remaining: int = 0) -> Outcome:
    """Gate a draft the **calling agent** wrote — §8.1a's `fetch` route, through the same gate.

    This is the other half of §8.1a, and the reason §8.4 is *unconditional*. A vision-capable
    agent takes the free route: it `fetch`es the rasters, looks at them itself, and writes the
    draft in its own context. Correction Loop 1 — the automatic per-code stamp — lives inside
    `read` and therefore **did not happen** on that route: the agent has read codes off a picture
    with nothing checking them. So the draft comes back here, and the identical gate runs on it,
    per `(claim, page)`, before one word of it is rendered.

    Nothing about this path is cheaper for the gate and nothing about it is trusted: the same
    :func:`~vsir.runner.answer.gate`, the same `verify` calls, the same rejection, the same
    refusal when a check cannot run. The only difference in the outcome is ``route``, which is
    recorded and never branched on.

    **The claims are re-derived from the draft, not taken from the caller** — and that is the
    difference between a gate and a formality. §8.4 gates *"the codes in the draft"*, so a caller
    that listed two of the three codes its own sentence contains would otherwise have the third
    rendered with nothing having checked it: the caller declaring the claim set would make the
    gate's coverage the caller's choice, on precisely the route where §8.1a says nothing else
    checked anything. So :func:`~vsir.runner.answer.claims_from` runs here exactly as it runs
    after a `read`, over the union of what was declared and what the prose carries.
    """
    loop = Loop(question=question, call=call, reads_per_question=0, sink=None)
    loop.quota = reads_remaining
    loop.state = VERIFY
    loop.draft = draft.model_copy(update={"claims": list(answer_module.claims_from(
        [{"code": claim.code, "page_ids": list(claim.page_ids)} for claim in draft.claims],
        text=draft.text, pages=list(draft.pages)))})
    loop.route = draft.route
    signal = loop.verify()
    if signal:
        loop.moves[-1] = loop.moves[-1].model_copy(update={"signal": signal})
        loop.state = ANSWER if signal == CLEARED else ABSTAIN
    return loop.outcome()
