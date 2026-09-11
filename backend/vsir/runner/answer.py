"""The answer gate (Spec §8.4, I8) and the constrained abstention wording (§8.5). Net new.

**This module is the last thing between a model's sentence and a person's eyes**, and it is the
reason every earlier guard reaches the answer. `impl` had nothing like it: its `read` endpoint
returned the model's extract straight to the caller with a per-code boolean beside it, so a
plausible wrong part number arrived as prose with a `false` in a field a UI could forget to render.

Two functions, and they are the two halves of §1.1's guarantee:

:func:`gate` — **server-side and unconditional, per `(claim, page)`.** Every code in the draft is
checked against the page it is cited on, by one `verify` call per pair, and the three outcomes are
the three §8.4 declares: `present` renders, `unverifiable` renders **with the badge**, anything
else **rejects the draft**. Unconditional because the default `fetch` route skips Loop 1's
automatic stamp (§8.1a): on that route the agent has read codes off a raster with nothing checking
them, and a `fetch`-first runner without this gate would be the fastest path to the one failure
§1.1 exists to prevent. So the gate does not ask which route produced the draft, does not trust
`read`'s stamps (it re-checks them), and cannot be skipped by a flag — there is no flag.

:func:`abstention` — **the wording, constrained.** *"Not in these documents"* is forbidden while
`pages_no_text_read < scope_stats.pages_no_text`, because a corpus with unexamined image-only
pages has not been searched, and an abstention that sounds complete is a fabricated absence in the
one direction nobody audits. The honest wording names the gap: the documents searched, the pages
searched, and the count of image-only pages nobody looked at.

**Why a rejection never echoes the code it rejected.** §8.4 hands ``present_instead`` to
``reject_draft`` and it is disclosed here — but the code itself is not, and the response carries
no prose at all when a draft is rejected. A body that said *"K153 is not printed on p019"* puts
the misread code in front of the caller in the one place a person is reading for an answer, and a
UI that renders a rejection field is one CSS change away from rendering it as the answer. The
count, the page and the observed tokens are enough to act on; the code goes nowhere, exactly as
`verify` keeps draft codes off the event stream (§15.1, §7.2.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from vsir import logging as vsir_logging
from vsir.core.observed_tokens import is_code_like
from vsir.core.tok import tok
from vsir.core.verify import ABSENT, PRESENT, UNVERIFIABLE
from vsir.serve.envelope import ClaimVerdict

_log = vsir_logging.get_logger(__name__)

# ── the two badges (§8.4, §11.2, and M7's load-bearing UI) ──────────────────────────────────────

#: The code is printed in the page's own extracted text, which `ingest/probe.py` is the only
#: writer of (I2). The strongest thing this system can say about a code.
BADGE_VERIFIED = "verified"

#: §8.4's wording, verbatim, because it is asserted as a literal by the L0 suite and rendered as
#: a badge by the console: the code could **not** be checked — no text layer, an untrusted
#: extraction, or a page that is not current — and the answer is disclosing that rather than
#: hiding it. Rewording this string is a change to the product's contract with a reader.
BADGE_READ_FROM_IMAGE = "read from image, not text-verified"

BADGES: tuple[str, ...] = (BADGE_VERIFIED, BADGE_READ_FROM_IMAGE)

#: The badge each rendered verdict carries. `absent` is not here: it never renders.
BADGE_OF: Mapping[str, str] = {PRESENT: BADGE_VERIFIED, UNVERIFIABLE: BADGE_READ_FROM_IMAGE}

#: The amber warning of §13 M7, raised on the answer as a whole when any code was rendered with
#: the *read from image* badge. One warning, not one per claim: what a reader needs to know is
#: that this answer contains a code nobody could check, and the per-claim badge says which.
WARNING_UNVERIFIABLE = ("one or more codes in this answer were read from the page image and could "
                        "not be checked against extracted text")


# ── the draft, and what a gated answer looks like ───────────────────────────────────────────────

class Claim(BaseModel):
    """One code the draft asserts, and the pages it is asserted **over** (§8.4, I8).

    ``page_ids`` is a list rather than one id because a draft written from a two-page `read`
    legitimately cites both sheets, and I8 is *"verified against the page it is cited on"* — so
    every pair is checked and the verdict names the page the evidence actually sits on. A claim
    with no page is refused by :func:`gate`: a code asserted over nothing cannot be verified, and
    rendering it would be the whole failure.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    page_ids: list[str] = Field(default_factory=list)


class Draft(BaseModel):
    """A candidate answer, **before** the gate. Nothing renders this; the gate's output renders.

    ``route`` is §8.1a's — `read` when a sub-model looked and `fetch` when the calling agent did.
    It is recorded and **never branched on**: the gate treats both identically, which is the
    property §8.4 calls unconditional and the acceptance criteria assert by forcing each route
    with the same draft.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    claims: list[Claim] = Field(default_factory=list)
    #: The pages the draft was written from, in the order they were looked at — the citations.
    pages: list[str] = Field(default_factory=list)
    route: Literal["read", "fetch"] = "read"
    #: What the look step said about these pages answering the question (§7.2.6). `False` is not
    #: the gate's business — the loop acts on it (Loop 3) — and it is carried so a trace can show
    #: which draft the answer came from.
    sufficient: bool = True


class RenderedClaim(BaseModel):
    """One code that cleared the gate, with the badge it cleared under."""

    model_config = ConfigDict(extra="forbid")

    code: str
    #: The page the verdict is about: the one carrying the code for `present`, the cited page for
    #: `unverifiable` — never a page the claim was not checked against.
    page_id: str
    status: Literal["present", "unverifiable"]
    badge: str


class Rejection(BaseModel):
    """A claim the gate refused, **without the code** — see the module docstring."""

    model_config = ConfigDict(extra="forbid")

    page_id: str
    #: The capped prefix lookup over observed tokens, labelled *"different part"* (F16). This is
    #: the actionable half of a rejection: the code was not printed, and these were.
    present_instead: list[str] = Field(default_factory=list)
    reason: str = ""


class Check(BaseModel):
    """One `(claim, page)` verification the gate actually made — the call log, in the response.

    It is in the body on purpose. §8.4's requirement is that every rendered code was checked, and
    the only way a caller (or a test) can hold us to that without reading the prose is to see the
    calls. ``claim`` is empty on a row whose verdict was `absent`, because that row is a rejection
    and a rejection never echoes its code — the pair is still visible, the code is not.
    """

    model_config = ConfigDict(extra="forbid")

    claim: str = ""
    page_id: str
    status: Literal["present", "absent", "unverifiable"]


class Answer(BaseModel):
    """The only prose this system renders, and only what the gate cleared (§8.4, §7.6)."""

    model_config = ConfigDict(extra="forbid")

    #: The look step's own words — a sub-model's bounded extract on the `read` route, the calling
    #: agent's draft on the `fetch` route. **Never rewritten here.** A function that paraphrased a
    #: technical answer would be composing one, which is the refusal of §7.6, and a paraphrase is
    #: also where a cleared code turns into an uncleared one.
    text: str
    #: The pages the answer is from, in look order.
    citations: list[str] = Field(default_factory=list)
    claims: list[RenderedClaim] = Field(default_factory=list)
    #: :data:`WARNING_UNVERIFIABLE` when any claim rendered under the *read from image* badge.
    warnings: list[str] = Field(default_factory=list)
    route: Literal["read", "fetch"] = "read"


class Abstention(BaseModel):
    """§8.5's honest nothing: the wording, and the numbers that make it honest.

    The fields are named for the things they count, and ``pages_no_text`` is spelled exactly as
    the envelope spells it (§7.1's ``scope_stats.pages_no_text``) — *"one name for one thing"*.
    ``pages_no_text_read`` is the runner's tally of how many of those pages were actually put in
    front of a vision model, and the inequality between the two is what :func:`assert_wording`
    enforces.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    #: Why the loop stopped: one of :data:`REASONS`.
    reason: str
    #: The documents that were searched, by ``doc_id``.
    searched: list[str] = Field(default_factory=list)
    pages_searched: int = 0
    pages_no_text: int = 0
    pages_no_text_read: int = 0
    #: The image-only pages nobody looked at — ``pages_no_text - pages_no_text_read``, floored.
    image_only_unexamined: int = 0
    #: The documents those unexamined pages are in — the *"in CE-TC1AV8"* of §8.5's example.
    blind_documents: list[str] = Field(default_factory=list)
    #: How many claims the gate rejected, when that is why this is an abstention. The codes
    #: themselves are not here, for the reason :class:`Rejection` gives.
    rejected_claims: int = 0


# ── the gate (§8.4, I8) ─────────────────────────────────────────────────────────────────────────

#: One `(claim, page)` check: the claim, the page, and the verdict `verify` returned. The gate is
#: handed this rather than a store handle, so the call goes through whatever the caller's tool
#: surface is — the dispatcher on both transports — and there is no second path to `verify` here.
Verifier = Callable[[str, str], ClaimVerdict]


class GateUnavailable(RuntimeError):
    """A `verify` call the gate needed did not run: an outage, a missing page, a bad id.

    Raised rather than folded into a verdict, and that is §7.1's rule applied at the last
    possible moment: *"`error` means retry or report, and **never** abstain"*. A gate that read a
    failed check as `absent` would reject good drafts during an outage; one that read it as
    `unverifiable` would badge an unchecked code as *read from image* and render it. Neither is a
    verdict, so neither is available — the loop surfaces the refusal it came with.
    """

    def __init__(self, detail: str, *, claim: str, page_id: str, refusal: Any = None) -> None:
        super().__init__(detail)
        self.claim = claim
        self.page_id = page_id
        #: The transport-neutral refusal, so the caller re-raises somebody else's 503 as a 503.
        self.refusal = refusal


@dataclass(frozen=True)
class Gated:
    """The gate's whole output: what renders, what was refused, and every check that was made."""

    draft: Draft
    rendered: tuple[RenderedClaim, ...]
    rejections: tuple[Rejection, ...]
    checks: tuple[Check, ...]

    @property
    def cleared(self) -> bool:
        """Whether the draft may be rendered. One rejection is enough to stop all of it (§8.4)."""
        return not self.rejections

    @property
    def badges(self) -> tuple[str, ...]:
        return tuple(claim.badge for claim in self.rendered)

    def answer(self) -> Answer:
        """The rendered answer. Refuses to build one for a rejected draft — a raise, not an `if`.

        :class:`ValueError` rather than a silent empty answer, and never an ``assert``: ``python
        -O`` strips asserts, and I8 must not be strippable (the same argument §7.1's
        ``empty_is_never_ok`` makes about an empty ``ok``).
        """
        if not self.cleared:
            raise ValueError(
                f"the answer gate rejected {len(self.rejections)} claim(s) (§8.4, I8): a draft "
                f"carrying a code `verify` did not clear is not rendered, in part or in whole"
            )
        warnings = [WARNING_UNVERIFIABLE] if BADGE_READ_FROM_IMAGE in self.badges else []
        return Answer(text=self.draft.text, citations=list(self.draft.pages),
                      claims=list(self.rendered), warnings=warnings, route=self.draft.route)


def codes_in(text: str) -> tuple[str, ...]:
    """Every code-like token in a draft's prose, in order of appearance, de-duplicated.

    §8.4 gates *"the codes in the draft"*, and the model's ``codes`` list is what it **says** it
    read — not necessarily what its sentence contains. A code that appears in the extract and not
    in the list would reach a reader unchecked, which is I8 with a hole in it, so the union of the
    two is what the gate is given (:func:`claims_from`).

    *Code-like* is :func:`~vsir.core.observed_tokens.is_code_like` over :func:`~vsir.core.tok.tok`
    — the same definition `decompose()` splits a query with and `observed_tokens` builds an
    inventory with. Not a grammar (§5.2 prohibits one) and not a per-corpus regex: a token with a
    digit in it.

    **One narrowing, and it removes nothing a check could catch:** a token of digits alone is not
    collected here. *"Category 3"*, *"stage 17"*, *"2 channel wiring"* — a bare number in a
    sentence is a quantity, and on a sheet covered in numbers it is `present` on essentially any
    page, so gating it costs a call and tells a reader nothing while putting `3 — verified` in an
    answer beside a real part number. It is not a rule about what a code may look like: a code the
    model **declared** is checked exactly as it spelled it, digits and all, and this scan only
    supplements that list. Over-collecting past that point is still safe and still done — a word
    wrongly called a code is a word sent to the exact surface, which answers about it honestly.
    """
    return tuple(dict.fromkeys(
        token for token in tok(text)
        if is_code_like(token) and not token.isdigit()
    ))


def claims_from(codes: Sequence[Mapping[str, Any]], *, text: str,
                pages: Sequence[str]) -> tuple[Claim, ...]:
    """The claims a draft asserts: what the look step declared, plus what its prose contains.

    ``codes`` is `read`'s stamped list (§7.2.6) or a caller's own; each entry contributes its
    ``page_ids`` when it has them — the pages the stamp is about — and falls back to every page the
    draft was written from. A stamp is `unverifiable` precisely when no page could be checked, so
    it has no pages of its own and the fallback is the honest set: the pages that were looked at.

    The order is the declared codes first, then the ones only the prose carried, because that is
    the order a reader meets them in and the trace is read beside the answer.
    """
    claims: dict[str, Claim] = {}
    for entry in codes:
        code = str(entry.get("raw") or entry.get("code") or "").strip()
        if not code:
            continue
        cited = [str(page_id) for page_id in (entry.get("page_ids") or ())] or list(pages)
        claims[code] = Claim(code=code, page_ids=cited)
    declared = {token for code in claims for token in tok(code)}
    for token in codes_in(text):
        if token not in declared and token not in claims:
            claims[token] = Claim(code=token, page_ids=list(pages))
    return tuple(claims.values())


def _fold(verdicts: Sequence[tuple[str, ClaimVerdict]]) -> tuple[str, str, ClaimVerdict]:
    """Fold one claim's per-page verdicts into the one that decides whether it renders.

    :mod:`vsir.core.verify`'s fold order, deliberately identical: `present` wins over everything,
    because one page carrying the code makes the claim true of the pages it is cited on; `absent`
    beats `unverifiable` only when a page was actually checked, so a claim cited on a readable
    page and a scanned one is `absent` about the readable one rather than badged as unreadable.
    """
    for page_id, verdict in verdicts:
        if verdict.status == PRESENT:
            return PRESENT, page_id, verdict
    for page_id, verdict in verdicts:
        if verdict.status == ABSENT:
            return ABSENT, page_id, verdict
    page_id, verdict = verdicts[0]
    return UNVERIFIABLE, page_id, verdict


def gate(draft: Draft, *, verify: Verifier) -> Gated:
    """§8.4, executed. One `verify` call per `(claim, page)`; three outcomes; no fourth.

    ::

        for code in codes_in_draft:
            v = verify([code], [cited_page_id]).result[code]
            if   v.status == "present":      render(code)
            elif v.status == "unverifiable": render(code, badge="read from image, …")
            else:                            reject_draft(code, v.present_instead)

    The pseudocode is the spec's and the loop below is it, with the two things a real
    implementation has to settle:

    * **a claim cited on more than one page** is checked against each of them — one call per pair,
      never one call over the set — and the verdicts are folded by :func:`_fold`. That is what
      makes the call log an answer to *"was this code checked against the page it is cited on?"*
      rather than to *"was it checked somewhere?"*;
    * **a failed check is not a verdict** (:class:`GateUnavailable`). §7.1: an outage returned as
      an absence is our failure rendered as the caller's fabricated confidence.

    A claim with no page is a rejection with no page to name, which is the only honest outcome: a
    code asserted over nothing has nothing to verify it against.
    """
    rendered: list[RenderedClaim] = []
    rejections: list[Rejection] = []
    checks: list[Check] = []
    for claim in draft.claims:
        if not claim.page_ids:
            rejections.append(Rejection(page_id="", reason="no_cited_page"))
            continue
        verdicts = [(page_id, verify(claim.code, page_id)) for page_id in claim.page_ids]
        status, page_id, verdict = _fold(verdicts)
        checks.extend(
            Check(claim="" if one.status == ABSENT else claim.code, page_id=cited,
                  status=one.status)
            for cited, one in verdicts
        )
        if status == ABSENT:
            rejections.append(Rejection(page_id=page_id,
                                        present_instead=list(verdict.present_instead),
                                        reason=verdict.reason or ABSENT))
            continue
        rendered.append(RenderedClaim(code=claim.code, page_id=page_id, status=status,
                                      badge=BADGE_OF[status]))
    # The distribution and never the codes, for the reason `serve/tools/verify.py` logs the same
    # way: a per-claim line would put draft codes on the event stream (§15.1).
    _log.info("answer_gate", route=draft.route, claims=len(draft.claims), checks=len(checks),
              rendered=len(rendered), rejected=len(rejections),
              unverifiable=sum(1 for one in rendered if one.status == UNVERIFIABLE),
              cleared=not rejections)
    return Gated(draft=draft, rendered=tuple(rendered), rejections=tuple(rejections),
                 checks=tuple(checks))


# ── the abstention (§8.5) ───────────────────────────────────────────────────────────────────────

#: The phrase §8.5 forbids while image-only pages are unread, lowercased for comparison. Held as a
#: constant because both the composer and its assertion have to mean the same string, and because
#: the L0 suite asserts on **this** name rather than on a copy of the words.
FORBIDDEN_WORDING = "not in these documents"

#: Why the loop had nothing to say. Each one is a different instruction to the caller, in the same
#: sense §7.1's four absences are, and each gets its own opening clause below.
NOT_FOUND = "not_found"                  # searched, and the searchable text holds nothing
SCOPE_EXHAUSTED = "scope_exhausted"      # widened as far as there is corpus, still nothing
NO_PAGES = "no_pages"                    # the vision branch found no image-only page either
INSUFFICIENT = "insufficient"            # every page looked at said it does not answer
REJECTED = "rejected"                    # every draft carried a code the gate would not clear
REASONS: tuple[str, ...] = (NOT_FOUND, SCOPE_EXHAUSTED, NO_PAGES, INSUFFICIENT, REJECTED)

#: The opening clause per reason. None of them asserts absence from *the corpus* — they assert
#: what was done: searched, widened, looked at, refused. The completeness claim is made once, at
#: the end, and only when :class:`Coverage` says it is true.
_LEAD: Mapping[str, str] = {
    NOT_FOUND: "Not found in the searchable text of {docs}.",
    SCOPE_EXHAUSTED: "Not found in the searchable text of {docs}, and there is no wider scope "
                     "left to search.",
    NO_PAGES: "Nothing in {docs} matched, and no image-only page was available to look at.",
    INSUFFICIENT: "The pages looked at in {docs} do not answer this.",
    REJECTED: "A draft answer was written from {docs} and rejected: the codes it cited are not "
              "printed on the pages it cited them from.",
}


@dataclass(frozen=True)
class Coverage:
    """What was actually searched, and how much of it nobody could read (§5.7, §7.1, §8.5).

    Built from the envelopes the loop already received — ``scope_stats`` on every Family A
    response — so the numbers in an abstention are the numbers the search reported, not a second
    count of our own. ``pages_no_text_read`` is the one field the runner contributes: how many of
    the image-only pages it put in front of a vision model.
    """

    docs: tuple[str, ...] = ()
    pages: int = 0
    pages_no_text: int = 0
    pages_no_text_read: int = 0
    #: The documents holding pages with no text layer — `searchable_ratio < 1` on a `DocHit`.
    blind_docs: tuple[str, ...] = ()

    @property
    def unexamined(self) -> int:
        """The gap §8.5 is about, floored at zero: image-only pages nobody has looked at."""
        return max(0, self.pages_no_text - self.pages_no_text_read)

    @property
    def complete(self) -> bool:
        """Whether *"not in these documents"* is available at all. Almost always it is not."""
        return self.unexamined == 0

    def looked_at(self, pages: int) -> "Coverage":
        """Record image-only pages that have now been examined. A value, never a mutation."""
        from dataclasses import replace

        return replace(self, pages_no_text_read=self.pages_no_text_read + max(0, pages))

    def merge(self, other: "Coverage") -> "Coverage":
        """Fold in another rung's stats — the **widest** scope searched, not the last one.

        A loop that widened after `sufficient: false` searched more than its final rung reports,
        and an abstention that named only the narrow scope would understate what was covered
        while overstating what was concluded. So pages are taken at their maximum and the
        document lists are unioned; ``pages_no_text_read`` is the runner's own tally and is added
        nowhere but :meth:`looked_at`.
        """
        return Coverage(
            docs=tuple(dict.fromkeys(self.docs + other.docs)),
            pages=max(self.pages, other.pages),
            pages_no_text=max(self.pages_no_text, other.pages_no_text),
            pages_no_text_read=max(self.pages_no_text_read, other.pages_no_text_read),
            blind_docs=tuple(dict.fromkeys(self.blind_docs + other.blind_docs)),
        )

    @classmethod
    def of(cls, payload: Mapping[str, Any]) -> "Coverage":
        """One Family A envelope → the coverage it reports (§7.1's ``scope_stats``).

        ``blind_docs`` comes from the per-document ``searchable_ratio`` rows, which is why the
        document rung is worth descending through even when the answer is on one page: it is the
        only place the corpus says which binder nobody can read (§5.7, F4).
        """
        stats = payload.get("scope_stats") or {}
        docs = [str(row.get("doc_id") or "") for row in (stats.get("docs") or ())]
        blind = [str(row.get("doc_id") or "") for row in (stats.get("docs") or ())
                 if float(row.get("searchable_ratio") or 0.0) < 1.0]
        return cls(docs=tuple(doc for doc in docs if doc), pages=int(stats.get("pages") or 0),
                   pages_no_text=int(stats.get("pages_no_text") or 0),
                   blind_docs=tuple(doc for doc in blind if doc))


def _names(docs: Sequence[str]) -> str:
    """*"TC1E-SF and LTC1AV81"* — §8.5's own phrasing, and *"the scope searched"* for none."""
    names = [doc for doc in dict.fromkeys(docs) if doc]
    if not names:
        return "the scope searched"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def abstention(coverage: Coverage, *, reason: str = NOT_FOUND,
               rejected: int = 0) -> Abstention:
    """§8.5's wording, composed from the coverage rather than chosen from a list of sentences.

    Three clauses, always in this order:

    1. **what was done**, per ``reason`` — never *"this does not exist"*;
    2. **the numbers**: how many pages were searched, of how many documents;
    3. **the gap**: the count of image-only pages that were not examined and the documents they
       are in — or, when there is no gap, the sentence §8.5 permits and only then.

    The example in §8.5 is clause 1 plus clause 3: *"Not found in the searchable text of TC1E-SF
    and LTC1AV81. 14 image-only pages in CE-TC1AV8 were not examined."* Clause 2 is added because
    the plan requires the abstention to **name the coverage numbers**, and *"14 unexamined"* means
    something different beside 20 pages than beside 1,440.
    """
    if reason not in REASONS:
        raise ValueError(f"{reason!r} is not one of §8.5's abstention reasons: {list(REASONS)}")
    clauses = [_LEAD[reason].format(docs=_names(coverage.docs))]
    clauses.append(f"{coverage.pages} page(s) searched across "
                   f"{len(set(doc for doc in coverage.docs if doc))} document(s).")
    if coverage.unexamined:
        clauses.append(f"{coverage.unexamined} image-only page(s) in "
                       f"{_names(coverage.blind_docs or coverage.docs)} were not examined — "
                       f"look at them with `fetch` or `read` before concluding anything about "
                       f"the corpus.")
    elif not coverage.pages:
        # Nothing was counted, so there is no completeness to claim. This is the scope reporting
        # that it searched nothing — a `not_found` over an empty scope, or a rung that answered
        # with a default `scope_stats` — and *"not in these documents"* about zero pages would be
        # the same fabricated absence §8.5 forbids, arrived at from the other end.
        clauses.append("No page was searched, so nothing follows about the corpus — widen the "
                       "scope or check that this release has a published document.")
    elif coverage.pages_no_text:
        clauses.append(f"All {coverage.pages_no_text} image-only page(s) in scope were examined, "
                       f"so this is {FORBIDDEN_WORDING}.")
    else:
        clauses.append(f"Every page in scope has a text layer, so this is "
                       f"{FORBIDDEN_WORDING}.")
    text = " ".join(clauses)
    assert_wording(text, coverage)
    return Abstention(
        text=text, reason=reason,
        searched=[doc for doc in dict.fromkeys(coverage.docs) if doc],
        pages_searched=coverage.pages,
        pages_no_text=coverage.pages_no_text,
        pages_no_text_read=coverage.pages_no_text_read,
        image_only_unexamined=coverage.unexamined,
        blind_documents=[doc for doc in dict.fromkeys(coverage.blind_docs) if doc],
        rejected_claims=max(0, rejected),
    )


def assert_wording(text: str, coverage: Coverage) -> None:
    """§8.5's one prohibition, enforced on the composed string. A raise, never an ``assert``.

    Called by :func:`abstention` on every path, so the composer cannot emit a sentence the rule
    forbids, and exported so the surface above can re-check anything it did not compose itself.
    The check is on the **string**, not on the branch that produced it: a future edit that adds a
    reassuring closing sentence is caught by the same line that catches a mis-set flag.
    """
    if FORBIDDEN_WORDING in text.lower() and not coverage.complete:
        raise ValueError(
            f"§8.5 forbids {FORBIDDEN_WORDING!r} while pages_no_text_read "
            f"({coverage.pages_no_text_read}) < scope_stats.pages_no_text "
            f"({coverage.pages_no_text}): {coverage.unexamined} image-only page(s) in "
            f"{_names(coverage.blind_docs or coverage.docs)} have not been examined, so the "
            f"corpus has not been searched and an abstention that sounds complete is a "
            f"fabricated absence"
        )
