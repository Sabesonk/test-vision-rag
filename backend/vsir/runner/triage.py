"""Loop 0 — tri-state triage, the five safeguards, and the state machine they bind (Spec §8.2).

Every candidate a skim returns is marked `relevant` | `uncertain` | `irrelevant` **from its
summary row, for free, before any money is spent**. Nothing in this module reads page text, opens
a raster, embeds anything or calls a model: the four inputs are the four fields a triage row
carries — ``summary``, ``why``, ``grounded_rate`` and ``text_trust`` — and that is the whole
budget of the cheapest correction there is.

**Why three states and not two.** A binary keep/drop discards the fallback pool, so the only
repair left for a wrong drop is to re-skim from scratch — and the summary that hid the answer will
hide it again. `uncertain` is the memory that makes `sufficient: false` cost one more look instead
of one more search (§8.2, §8.3 Loop 3).

**The safeguards are one definition, read twice.** :data:`SAFEGUARDS` is the text; this module
enforces it and :mod:`vsir.runner.prompt` prints it into the system prompt. §8.2 requires both —
*"enforced in the system prompt and in the runner's state machine"* — and R6 is the reason: a
prompt-level rule is advisory the moment a client drives the raw MCP surface, so the rule that
matters is the one in the machine.

**Every judgement here errs toward carrying a candidate forward**, and that asymmetry is R1's
mitigation rather than timidity. Marking a page `uncertain` that turns out to be useless costs a
place in a pool that is only drained when the answer was not found; marking the answering page
`irrelevant` produces an abstention on a corpus that contained the answer — the one failure the
`uncertain` pool, *"do not filter a small set"* and `why: lexical` exist to prevent.

**Nothing here matches.** The overlap between a query's terms and a summary's tokens decides
whether to *look*; it never decides whether a code is printed on a page. That question has one
answer and one code path — :func:`~vsir.core.exact.exact_filter` over `variants()` (I3, §5.6) —
and a mark from this module can never reach a response as a hit, a citation or a claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from vsir import logging as vsir_logging
from vsir.core.health import TRUST_OK_MIN
from vsir.core.record import UNSEARCHABLE_TRUST
from vsir.core.tok import tok
from vsir.serve.envelope import PageHit
from vsir.serve.tools.skim import decompose

_log = vsir_logging.get_logger(__name__)

# ── the three marks (§8.2) ──────────────────────────────────────────────────────────────────────

#: Proceed to the look step — `fetch` or `read`, as :mod:`vsir.runner.route` decides.
RELEVANT = "relevant"
#: The fallback pool. Not looked at now; drained **before** the scope is widened (safeguard 1).
UNCERTAIN = "uncertain"
#: `exclude` on every subsequent skim, so the same page is not re-offered and re-rejected.
IRRELEVANT = "irrelevant"

#: The whole vocabulary, and in the order a triage table is read. A fourth value would be a
#: fallback pool nobody drains; a third state collapsed into two is the binary §8.2 forbids.
MARKS: tuple[str, ...] = (RELEVANT, UNCERTAIN, IRRELEVANT)

#: Why a row was marked the way it was — closed, like `read`'s flags, because a reason nothing
#: sets is a column a reviewer cannot act on. Every mark carries exactly one of these.
REASON_EXACT_HIT = "exact_hit"              # safeguard 4: the query's identifier, found lexically
REASON_SMALL_SET = "small_set"              # safeguard 2: ≤ SMALL_SET_MAX candidates, read them all
REASON_SUMMARY_MATCH = "summary_match"      # the summary carries a term of the query
REASON_LEXICAL_UNSHOWN = "lexical_unshown"  # the text matched, the summary does not show it
REASON_UNTRUSTED_TEXT = "untrusted_text"    # the page's text layer cannot be believed (§5.7)
REASON_WEAK_GROUNDING = "weak_grounding"    # the summary is only partly grounded in the page
REASON_NO_SUMMARY = "no_summary"            # there is no summary to judge the page from
REASON_NO_OVERLAP = "no_overlap"            # a trusted summary, and nothing of the query in it
REASONS: tuple[str, ...] = (REASON_EXACT_HIT, REASON_SMALL_SET, REASON_SUMMARY_MATCH,
                            REASON_LEXICAL_UNSHOWN, REASON_UNTRUSTED_TEXT,
                            REASON_WEAK_GROUNDING, REASON_NO_SUMMARY, REASON_NO_OVERLAP)

#: The `why` value that is a hard signal (§8.2 safeguard 3). Spelled as `skim` spells it, because
#: a second name for the lexical surface is a safeguard that silently stops firing.
LEXICAL = "lexical"

#: *"With ≤3 candidates, read them all"* (safeguard 2). Three, not five: it is the `read` cap
#: (`MAX_READ_PAGES`), so the safeguard can always be honoured in one call on either route.
SMALL_SET_MAX = 3

#: The shortest prose token that counts as a term of the query.
#:
#: A length floor rather than a stopword list, and the reason is the corpus: summaries are
#: multilingual (§5.2, D5), so an English stopword list would strip nothing from a German summary
#: and would quietly make *"nach"* and *"oder"* into evidence of relevance while *"the"* was
#: dropped from the English one. A floor is language-neutral and errs in the safe direction — a
#: function word that survives it can only carry a page **forward**, never drop one.
MIN_TERM_CHARS = 4

# ── the five safeguards (§8.2), stated once ─────────────────────────────────────────────────────

#: The five rules of §8.2's table, verbatim in substance and in its order. :mod:`vsir.runner.prompt`
#: renders them into the system prompt and this module enforces them; the test suite asserts that
#: both consumers see the same five, which is what *"binding on the prompt and on the state
#: machine"* has to mean if it is to mean anything (§8.2, R6).
SAFEGUARDS: tuple[tuple[str, str], ...] = (
    ("rejections stay soft",
     "On `sufficient: false`, try the `uncertain` pool BEFORE widening scope. A rejection is a "
     "statement about the pages that were looked at, not about the corpus."),
    ("do not filter a small set",
     f"With {SMALL_SET_MAX} candidates or fewer, read them all. There is nothing to triage: "
     f"filtering a set this size can only remove the answer."),
    ("use `why` as a signal",
     "A `lexical` hit on an exact code outranks a dense-only hit. `why` says which surface found "
     "the page, and a printed code found in the page's own text is the strongest signal there is."),
    ("auto-promote exact hits",
     "When the query contains an exact identifier and the hit's `why` is `lexical`, mark it "
     "`relevant` without evaluating the summary. The page prints the code that was asked for."),
    ("tri-state is mandatory",
     "Mark every candidate `relevant`, `uncertain` or `irrelevant` — never keep/drop. The "
     "`uncertain` pool is what makes a rejection cost one more look instead of a new search."),
)


# ── the query, as terms a summary can be read against ───────────────────────────────────────────

@dataclass(frozen=True)
class Terms:
    """A question, reduced to the terms a one-line summary could plausibly show.

    ``identifiers`` is :func:`~vsir.serve.tools.skim.decompose`'s — the same split the skim itself
    ran, imported rather than re-derived so *"the query contains an exact identifier"* means the
    same thing in the safeguard as it did in the search (§7.2.1 ordering rule 1).
    """

    identifiers: tuple[str, ...]
    #: Prose tokens at or above :data:`MIN_TERM_CHARS`, tokenised as the index tokenises (§5.6).
    prose: tuple[str, ...]

    @property
    def exact(self) -> bool:
        """Whether safeguard 4 is even in play: does the question name an identifier at all."""
        return bool(self.identifiers)

    @property
    def all(self) -> tuple[str, ...]:
        """Every term, identifiers first. What a summary's tokens are intersected with."""
        return self.identifiers + self.prose


def terms_of(query: str) -> Terms:
    """Split a question into the terms triage reads a summary against.

    Identifiers keep their tokenised spelling — ``"K158"`` → ``k158`` — because the summary is
    compared token-for-token and :func:`~vsir.core.tok.tok` is the one tokeniser in this codebase
    that agrees with the index (§5.6, F3).
    """
    split = decompose(query or "")
    identifiers = tuple(dict.fromkeys(token for word in split.identifiers for token in tok(word)))
    prose = tuple(dict.fromkeys(token for token in tok(split.prose)
                                if len(token) >= MIN_TERM_CHARS and token not in identifiers))
    return Terms(identifiers=identifiers, prose=prose)


# ── one mark ────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Mark:
    """One candidate's verdict: the state, why it is in that state, and what it was judged on.

    ``matched`` is the terms of the question the summary actually showed — the evidence for the
    mark, kept beside it so a triage table can be reviewed rather than trusted, and so the
    telemetry of §8.2 is evaluation data rather than a label with no provenance.
    """

    page_id: str
    mark: str
    reason: str
    rank: int
    why: tuple[str, ...]
    matched: tuple[str, ...] = ()
    #: Safeguard 4 fired: the summary was never evaluated, because it did not need to be.
    promoted: bool = False

    @property
    def lexical(self) -> bool:
        """Whether the lexical surface found this page — safeguard 3's ordering signal."""
        return LEXICAL in self.why

    def as_event(self) -> dict[str, Any]:
        """The flat shape telemetry records: `query → page → relevant?` plus its evidence."""
        return {"page_id": self.page_id, "mark": self.mark, "reason": self.reason,
                "rank": self.rank, "why": list(self.why), "matched": list(self.matched),
                "promoted": self.promoted}


def mark(hit: PageHit, *, terms: Terms) -> Mark:
    """Mark one candidate, from its row alone (§8.2).

    The order of the rules is the order of the argument:

    1. **Safeguard 4** — the question named an identifier and the lexical surface found this page.
       The page prints the code that was asked for, so the summary is not consulted at all; a
       summary that fails to mention a code the page prints is common and is not evidence.
    2. **The summary shows a term of the question** → `relevant`.
    3. **The summary cannot be believed to have shown it** → `uncertain`, and there are four ways
       to get here: the lexical surface matched but the summary does not show why (R1's exact
       case — the summary omitted the line that mattered), the text layer is unsearchable, the
       summary is only partly grounded in the page (§5.7), or there is no summary at all.
    4. Otherwise → `irrelevant`: a trusted, grounded summary that carries nothing of the question.

    Note what is **not** an input: page text (a triage row has none, P2), a raster, a rank
    threshold, and any model call. `rank` is carried onto the mark for ordering and is never a
    reason — a fused position is a place in a list, not a judgement about a page.
    """
    why = tuple(hit.why)
    if terms.exact and LEXICAL in why:
        return Mark(page_id=hit.page_id, mark=RELEVANT, reason=REASON_EXACT_HIT, rank=hit.rank,
                    why=why, matched=terms.identifiers, promoted=True)

    tokens = set(tok(hit.summary))
    matched = tuple(term for term in terms.all if term in tokens)
    if matched:
        return Mark(page_id=hit.page_id, mark=RELEVANT, reason=REASON_SUMMARY_MATCH,
                    rank=hit.rank, why=why, matched=matched)

    if LEXICAL in why:
        # Safeguard 3 as a floor: the page's own text matched and its summary does not say so, so
        # the summary is demonstrably not a complete account of the page. Not `relevant` — a
        # prose query can match a common word lexically — but never `irrelevant` either.
        return Mark(page_id=hit.page_id, mark=UNCERTAIN, reason=REASON_LEXICAL_UNSHOWN,
                    rank=hit.rank, why=why)
    if hit.text_trust in UNSEARCHABLE_TRUST:
        return Mark(page_id=hit.page_id, mark=UNCERTAIN, reason=REASON_UNTRUSTED_TEXT,
                    rank=hit.rank, why=why)
    if hit.grounded_rate is not None and hit.grounded_rate < TRUST_OK_MIN:
        return Mark(page_id=hit.page_id, mark=UNCERTAIN, reason=REASON_WEAK_GROUNDING,
                    rank=hit.rank, why=why)
    if not hit.summary.strip():
        return Mark(page_id=hit.page_id, mark=UNCERTAIN, reason=REASON_NO_SUMMARY,
                    rank=hit.rank, why=why)
    return Mark(page_id=hit.page_id, mark=IRRELEVANT, reason=REASON_NO_OVERLAP, rank=hit.rank,
                why=why)


def order(marks: Sequence[Mark]) -> tuple[Mark, ...]:
    """The order the look step consumes marks in — safeguard 3, made into a sort key.

    ``(state, not lexical, rank, page_id)``: the three states in the order they are acted on,
    then *"a `lexical` hit outranks a dense-only hit"* — which is the tie-break the safeguard
    asks for and is why it is compared **before** ``rank`` rather than after. ``page_id`` last so
    the order is total: two calls with the same rows produce the same list (§16).
    """
    return tuple(sorted(marks, key=lambda m: (MARKS.index(m.mark), not m.lexical, m.rank,
                                              m.page_id)))


# ── the set ─────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Triage:
    """One triage pass over one skim's candidates. A value — the runner holds it, we do not."""

    query: str
    marks: tuple[Mark, ...]
    #: Whether safeguard 2 applied to this set (≤ :data:`SMALL_SET_MAX` candidates).
    small_set: bool = False

    def of(self, state: str) -> tuple[Mark, ...]:
        return tuple(m for m in self.marks if m.mark == state)

    @property
    def relevant(self) -> tuple[Mark, ...]:
        return self.of(RELEVANT)

    @property
    def uncertain(self) -> tuple[Mark, ...]:
        """The fallback pool. Retained, never discarded — draining it is safeguard 1's move."""
        return self.of(UNCERTAIN)

    @property
    def irrelevant(self) -> tuple[Mark, ...]:
        return self.of(IRRELEVANT)

    @property
    def look_set(self) -> tuple[str, ...]:
        """The pages the look step takes, in order. `relevant` only — the pool waits."""
        return tuple(m.page_id for m in self.relevant)

    @property
    def exclude(self) -> tuple[str, ...]:
        """What goes into the next skim's ``exclude`` — the `irrelevant` page ids, and only those.

        The `uncertain` pool is deliberately **not** here: excluding it would delete the fallback
        the tri-state exists to keep, and the next skim would be free to return the same rows the
        runner has already decided it cannot yet judge (§8.2).
        """
        return tuple(m.page_id for m in self.irrelevant)

    @property
    def signal(self) -> str:
        """What this pass tells the machine: is there anything to look at (:data:`LOOK_SET`)."""
        return LOOK_SET if self.look_set else EMPTY_LOOK_SET


def triage(hits: Sequence[PageHit], *, query: str) -> Triage:
    """Mark a whole skim's candidates, then apply the one safeguard that is about the **set**.

    Safeguard 2 — *"do not filter a small set"* — cannot be decided from a row, only from how many
    rows there are, so it is applied here: with :data:`SMALL_SET_MAX` candidates or fewer every
    row is `relevant` and none is `irrelevant`. *"Read them all"* is exactly that; a small set
    left half in the pool would still be a filtered small set, and the pool would be drained on
    the next `sufficient: false` anyway, one paid call later.
    """
    terms = terms_of(query)
    marks = [mark(hit, terms=terms) for hit in hits]
    small = 0 < len(marks) <= SMALL_SET_MAX
    if small:
        marks = [m if m.mark == RELEVANT
                 else Mark(page_id=m.page_id, mark=RELEVANT, reason=REASON_SMALL_SET,
                           rank=m.rank, why=m.why, matched=m.matched, promoted=m.promoted)
                 for m in marks]
    return Triage(query=query, marks=order(marks), small_set=small)


# ── the state machine (§8.1, §8.2, §8.3 Loops 0 and 3) ──────────────────────────────────────────

#: The rungs, then the marks, then the look — §8.1's diagram, left to right.
DESCEND = "descend"
TRIAGE = "triage"
LOOK = "look"
#: Safeguard 1's state: the `uncertain` pool becomes the look set, and no new search is run.
DRAIN_UNCERTAIN = "drain_uncertain"
WIDEN = "widen"
#: §8.1's second empty branch: the scope holds pages with no text, so vision goes first.
VISION_FIRST = "vision_first"
DRAFT = "draft"
VERIFY = "verify"
#: The two terminals. `answer` is reached only through the gate of §8.4 (I8, U022).
ANSWER = "answer"
ABSTAIN = "abstain"

STATES: tuple[str, ...] = (DESCEND, TRIAGE, LOOK, DRAIN_UNCERTAIN, WIDEN, VISION_FIRST,
                           DRAFT, VERIFY, ANSWER, ABSTAIN)
TERMINAL: frozenset[str] = frozenset({ANSWER, ABSTAIN})

#: The signals a state is left on. Each one is an **observation** the loop can make for free from
#: an envelope it already has — no signal here requires a call that was not going to happen.
CANDIDATES = "candidates"                # a skim returned rows
EMPTY_SEARCHABLE = "empty_searchable"    # nothing found, and the scope was searchable
EMPTY_NO_TEXT = "empty_no_text"          # nothing found, and the scope has image-only pages
LOOK_SET = "look_set"                    # triage produced pages to look at
EMPTY_LOOK_SET = "empty_look_set"        # triage produced none
SUFFICIENT = "sufficient"                # `read` said these pages answer the question
INSUFFICIENT = "insufficient"            # `read` said they do not (§8.3 Loop 3)
POOL_EMPTY = "pool_empty"                # the `uncertain` pool is drained
CONTRADICTED = "contradicted"            # `verify` disagrees with the draft (§8.3 Loop 4)
CLEARED = "cleared"                      # every claim cleared the gate (§8.4)
WIDENED = "widened"                      # there was a wider scope to search
EXHAUSTED = "exhausted"                  # there was not
BUDGET_EXHAUSTED = "budget_exhausted"    # `VSIR_READS_PER_QUESTION` is spent (§8.4)
NO_PAGES = "no_pages"                    # the vision branch found no image-only page either

#: The whole machine, as data. §8.1's diagram and §8.3's six loops, with **one** row that is the
#: reason this table exists rather than a chain of `if`s:
#:
#:     ``(LOOK, INSUFFICIENT) → DRAIN_UNCERTAIN``
#:
#: Safeguard 1 is *"on `sufficient: false`, try the `uncertain` pool **before** widening scope"*,
#: and in a hand-written loop that ordering is one line that a later edit can reorder without any
#: test noticing. Here it is a row a test reads directly, and widening is reachable only through
#: :data:`DRAIN_UNCERTAIN` — there is no ``(LOOK, INSUFFICIENT) → WIDEN`` edge to add by accident.
TRANSITIONS: Mapping[tuple[str, str], str] = {
    (DESCEND, CANDIDATES): TRIAGE,
    (DESCEND, EMPTY_SEARCHABLE): ABSTAIN,
    (DESCEND, EMPTY_NO_TEXT): VISION_FIRST,
    (TRIAGE, LOOK_SET): LOOK,
    (TRIAGE, EMPTY_LOOK_SET): DRAIN_UNCERTAIN,
    (LOOK, SUFFICIENT): DRAFT,
    (LOOK, INSUFFICIENT): DRAIN_UNCERTAIN,
    (LOOK, BUDGET_EXHAUSTED): ABSTAIN,
    (DRAIN_UNCERTAIN, CANDIDATES): LOOK,
    (DRAIN_UNCERTAIN, POOL_EMPTY): WIDEN,
    (WIDEN, WIDENED): DESCEND,
    # §8.1's second empty branch, reachable from the **end** of the ladder as well as from a
    # descent that found nothing (U022). The diagram's *"TRIAGE empty · pages have no text →
    # `fetch` / `read` the image-only pages first"* is not only about a descent that returned no
    # rows: a descent whose rows triage rejects wholesale arrives at the same place, and
    # abstaining there while a page nobody can read sits unexamined is concluding absence from a
    # corpus that was never searched (§8.5, F4). So the last widening looks before it gives up.
    (WIDEN, EMPTY_NO_TEXT): VISION_FIRST,
    (WIDEN, EXHAUSTED): ABSTAIN,
    (VISION_FIRST, CANDIDATES): LOOK,
    (VISION_FIRST, NO_PAGES): ABSTAIN,
    (DRAFT, CANDIDATES): VERIFY,
    (VERIFY, CLEARED): ANSWER,
    (VERIFY, CONTRADICTED): TRIAGE,
}


class UnknownTransition(KeyError):
    """A signal this state has no edge for. Raised, never defaulted (§11.3's argument, applied).

    A machine that fell through to *"keep going"* would answer from wherever it happened to be,
    which is how a runner ends up drafting from pages triage rejected.
    """


def next_state(state: str, signal: str) -> str:
    """The one legal successor, or a named refusal. The only reader of :data:`TRANSITIONS`."""
    try:
        return TRANSITIONS[(state, signal)]
    except KeyError:
        raise UnknownTransition(
            f"no transition from {state!r} on {signal!r}; §8.1's machine leaves {state!r} on "
            f"{sorted(s for (st, s) in TRANSITIONS if st == state)}") from None


def empty_signal(pages_no_text: int) -> str:
    """§8.1's two empty branches, chosen by coverage rather than by guess.

    *"TRIAGE empty · scope WAS searchable → ABSTAIN, naming what was searched"* versus *"TRIAGE
    empty · pages have no text → `fetch` / `read` the image-only pages first"*. The number comes
    from ``scope_stats.pages_no_text``, which every Family A envelope already carries (§7.1) — so
    the branch costs nothing, and §8.5 forbids the abstention while those pages are unread.
    """
    return EMPTY_NO_TEXT if pages_no_text > 0 else EMPTY_SEARCHABLE


# ── telemetry (§8.2, §11.4) ─────────────────────────────────────────────────────────────────────

#: The event name a triage mark is recorded under. One event per mark: this is evaluation data —
#: *"query → page → relevant?"* — and an aggregate row cannot be joined back to the page it judged.
TRIAGE_EVENT = "triage_mark"

Sink = Callable[[Mapping[str, Any]], None]


def log_sink(event: Mapping[str, Any]) -> None:
    """The default sink: one JSON line per mark on stdout (§15 Factor XI, §11.4).

    ``debug`` rather than ``info``, for the reason the per-rung skim line is `debug`: ten lines
    per question is a volume an operator opts into, and §11.4 asks for triage marks as evaluation
    data, not as an operational record. The audit log — the record of what was **spent** — is
    `serve/audit.py`'s and is `info`, because nothing about triage costs anything.
    """
    _log.debug(TRIAGE_EVENT, **dict(event))


def record(result: Triage, *, sink: Sink | None = log_sink, **fields: Any) -> int:
    """Write the marks to telemetry and return how many were written.

    ``sink=None`` **disables** telemetry, and the loop is unaffected: the marks are already in the
    :class:`Triage` value the caller is holding, so recording them is an observation and never a
    step. That is §8.2's *"written to telemetry as free evaluation data — never as a mandatory
    tool call"* made structural — there is no call here to fail, and nothing downstream reads
    what this function wrote.
    """
    if sink is None:
        return 0
    for one in result.marks:
        sink({"query": result.query, "small_set": result.small_set, **one.as_event(), **fields})
    return len(result.marks)
