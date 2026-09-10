"""The two response families (Spec §7.1, I5). Ported and re-shaped from ``impl/app/api_models.py``.

`impl` had one envelope and it could not express the thing that matters most. Its own docstring
called an empty ``200`` *"the agent's designed abstention path"*, and a `verify` in which every
claim is legitimately `absent` has no honest shape in that design: it is neither an error nor a
result, so it comes back looking like "nothing found" — which is what an outage also looks like.

So there are **two families**, because *"did you find anything?"* and *"here is the verdict you
asked for"* are different questions:

**Family A — search and absence** (`skim_documents`, `skim_sections`, `skim_pages`, `lookup`,
`resolve`). These can be empty, so they carry the typed-absence machinery, and a validator makes an
empty ``ok`` **impossible** rather than merely discouraged.

**Family B — material and verdicts** (`fetch`, `read`, `verify`). These are never empty: the call
either ran or it did not, and the answer lives in per-item states. A `verify` with three `absent`
verdicts is ``status: ok`` — the call worked, and the answer is no.

Two things `impl` shipped are deliberately **not** ported: every curated-keyword filter field
(C1, C2), and ``Hit.fused``, the RRF sum. A fused float is a similarity score under another name,
and §7.6 refuses to return one. An ordinal ``rank`` stays, and is required: a position is not a
confidence.
"""
from __future__ import annotations

import json
from typing import Any, Generic, Literal, Mapping, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vsir.core.record import SCHEMA_VERSION, Summary, TextTrust
from vsir.core.status import CHECK_STATES, Status

#: §7.1 — a **server** constant. `cap` controls how many hits come back and nothing else, so a
#: trust signal a client could flip by passing `cap=200` would be worse than no signal at all.
WEAK_ABS = 20


def wire(payload: Mapping[str, Any]) -> bytes:
    """One envelope → the bytes a caller receives, on **every** transport (§7.5).

    §7.5 requires the MCP server to call the identical implementations, and U015's acceptance
    sharpens that into a property anybody can check: the `tools/call` result for a given request
    is **byte-identical** to the HTTP response body for the same request. Two serialisers cannot
    make that true by agreement — they make it true until one of them gains an ``indent`` — so
    there is one, and both transports call it.

    The settings are Starlette's ``JSONResponse.render`` verbatim, because the HTTP half is the
    surface that already exists and moving *it* would be a wire change for every caller:
    ``ensure_ascii=False`` (so a printed label with a diacritic goes out as the character rather
    than an escape), ``allow_nan=False`` (``NaN`` is not JSON, and a silent one would be a body no
    strict parser accepts), and the compact separators.

    Key order is **insertion order** — the field order of the Pydantic model — and not sorted. A
    response's field order is part of what a reviewer diffs, and §7.1 declares the fields in a
    deliberate order: `status` first, because it is the field a caller switches on.
    """
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=None,
                      separators=(",", ":")).encode("utf-8")


def weakness(total: int, scope_pages: int) -> bool:
    """``total > max(WEAK_ABS, 0.25 * scope_pages)`` — the `weak` / `needs_scope` rule (§7.1).

    Depends only on the size of the match set and the size of the scope searched. ``lookup("3")``
    unscoped matches most of the corpus, so it is `weak` at any `cap`.
    """
    return total > max(WEAK_ABS, 0.25 * scope_pages)


class Provenance(BaseModel):
    """What produced this response (§15 Factor V).

    Distinct from ``core.record.Provenance``, which is what produced a *page*: this one answers
    "which release, which run, which schema answered me", so any answer traces to the exact code
    and configuration behind it.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = ""
    release_id: str
    schema_version: int = SCHEMA_VERSION


class ImageRef(BaseModel):
    """A **reference** to a page raster. Never the pixels (§7.1, D12, P2).

    Roughly sixty bytes, and it renders nothing until something dereferences it — so a ten-row skim
    is still one small JSON response, and the caller never has to construct a URL. The actual
    bytes exist in exactly one place in the whole surface: ``fetch`` with ``inline=true``. A
    ``bytes_b64`` in a skim row would let the agent answer from the search result instead of
    choosing and then paying, which is the failure P2 exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    thumb_url: str = ""
    dpi: int
    width: int = 0
    height: int = 0


class Preview(BaseModel):
    """An aggregate row's thumbnail: the group's best-ranked matched page, or page 1.

    The fallback is the useful case. A ``searchable_ratio: 0.00`` row is the agent's blind spot,
    and a thumbnail is how a person eyeballs an image-only binder without paying for a `read`.
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    thumb_url: str = ""


class NextMoves(BaseModel):
    """The affordances on a hit — what a caller can do *next* without inventing a URL.

    ``suggest`` is what keeps a `not_found` honest: `lookup("alarm 152")` finds no phrase, so the
    status stays `not_found` and ``suggest: ["skim_pages"]`` says a different **move** could still
    answer. Inventing a seventh status for "no, but try this" is the alternative, and it would make
    every caller's switch statement wrong.

    ``tokens_observed`` is the **evidence** for that suggestion, and §7.1 asks for it in the same
    sentence: *"it returns `status: not_found` with `next.suggest: ["skim_pages"]` and the tokens
    that did occur."* A suggestion with nothing behind it is a shrug the agent has to take on
    trust; `["alarm", "152"]` says which words the corpus really contains, so the caller can tell
    *"the phrase is not printed, but both words are here"* from *"none of this is in the corpus"*
    without spending a `skim` to find out. It rides inside `next` rather than at the top level
    because it is part of the affordance, not part of the result.
    """

    model_config = ConfigDict(extra="forbid")

    expand: dict = Field(default_factory=dict)
    neighbours: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    suggest: list[str] = Field(default_factory=list)
    #: The words of the query that **do** occur somewhere in the searched scope's text. Never a
    #: near-miss code and never a candidate answer: these are the caller's own tokens, echoed back
    #: because they were found, not tokens the corpus offered in place of the label (F16).
    tokens_observed: list[str] = Field(default_factory=list)


class DocScopeStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    searchable_ratio: float


class ScopeStats(BaseModel):
    """What was actually searched — the denominator behind `weak`, and the blind spot made visible.

    ``pages_no_text`` is why F4 cannot happen quietly: a scope of 40 pages of which 40 have no text
    layer is not "nothing matched", it is "nothing was searchable".
    """

    model_config = ConfigDict(extra="forbid")

    pages: int = 0
    pages_no_text: int = 0
    docs: list[DocScopeStat] = Field(default_factory=list)


# ── Hit models — one per rung, so no field is ambiguous (§7.1) ───────────────────────────────────

#: The ordinal a group carries when **no page of it was ranked** — a disclosure row (§5.7, F4),
#: not a result. Ranks are 1-based everywhere in this surface, so zero cannot be confused with a
#: position; `pages_matched` is 0 beside it and the row sorts after every group that did match.
UNRANKED = 0


class DocHit(BaseModel):
    """*"Which binder?"* — hands back a scope to descend into, and carries no `page_id` at all.

    ``next.expand`` is that scope, and it is why the row needs no `page_id`: §7.1 says the row's
    *"job is to hand back a **scope** to descend into (`next.expand`)"*, so the caller passes the
    dict straight back as the next rung's ``scope`` argument rather than assembling one from
    ``doc_id`` and hoping the key is spelled the way `INDEXED` spells it.
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    title: str = ""
    doc_type: str = ""
    pages_matched: int = 0
    #: The best position any page of this group reached in the fused list. :data:`UNRANKED` on a
    #: disclosure row — a document that matched nothing and is returned anyway (§5.7).
    best_rank: int
    #: pages with a text layer ÷ pages. The agent's blind spot, as a number (§5.7).
    searchable_ratio: float = 0.0
    summary: str = ""
    preview: Preview | None = None
    next: NextMoves | None = None


class SectionHit(BaseModel):
    """*"Which chapter?"* — likewise a scope, not a citation."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str = ""
    page_range: tuple[int, int] | None = None
    pages_matched: int = 0
    best_rank: int
    preview: Preview | None = None
    next: NextMoves | None = None


class PageHit(BaseModel):
    """A page from a skim. ``why`` names the surfaces that found it — the fusion, explained."""

    model_config = ConfigDict(extra="forbid")

    page_id: str
    printed_page_no: str = ""
    summary: str = ""
    summary_lang: str = ""
    page_kind: str = "prose"
    #: e.g. `["dense", "lexical"]`, or `["dense"]` alone for an image-only query (D12).
    why: list[str] = Field(default_factory=list)
    rank: int
    flags: list[str] = Field(default_factory=list)
    #: `None` where `has_text` is false — nothing to be grounded in (§5.7).
    grounded_rate: float | None = None
    text_trust: TextTrust = "no_text"
    image: ImageRef | None = None
    next: NextMoves | None = None


class LookupHit(BaseModel):
    """An exact hit. ``verified`` is a boolean **about the surface it came from** — nothing else.

    ``text`` is verified by construction, because `ingest/probe.py` is its only writer (I2), so a
    hit there is ``verified: true``. ``vlm_codes`` is opt-in and permanently ``verified: false``
    (D3). The three-state `present | absent | unverifiable` vocabulary belongs to per-claim checks
    and is never spelled as a boolean here.
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    page_no: int
    printed_page_no: str = ""
    page_kind: str = "prose"
    verified: bool
    text_trust: TextTrust = "no_text"
    image: ImageRef | None = None
    next: NextMoves | None = None


class ResolveHit(BaseModel):
    """A saved citation, reopened. Unfiltered on purpose, so an old link still resolves."""

    model_config = ConfigDict(extra="forbid")

    page_id: str
    printed_page_no: str = ""
    label_verified: bool = False
    #: True when the page number was inferred from its neighbours rather than read off the page.
    interpolated: bool = False
    image: ImageRef | None = None


HitT = TypeVar("HitT", DocHit, SectionHit, PageHit, LookupHit, ResolveHit)


class SearchResponse(BaseModel, Generic[HitT]):
    """Family A. An empty ``ok`` is impossible — the validator is I5's enforcement.

    ``total`` is the size of the **set** that matched, not ``len(hits)``: a caller that pages
    through a capped result must be able to tell "20 of 400" from "20 of 20", because the first is
    a scoping problem and the second is an answer.
    """

    model_config = ConfigDict(extra="forbid")

    status: Status
    hits: list[HitT] = Field(default_factory=list)
    #: `vlm_codes` hits only, every one `verified: false`, and **never merged into `hits`** (D3).
    unverified_hits: list[LookupHit] = Field(default_factory=list)
    total: int = 0
    #: `total > cap`: `hits` is one page of the set, not the set.
    capped: bool = False
    weak: bool = False
    needs_scope: bool = False
    next: NextMoves | None = None
    #: Echoed back, because the service holds no session: the caller's scope is the whole truth
    #: about what was searched (F8, C11, §15 Factor VI).
    effective_scope: dict = Field(default_factory=dict)
    scope_stats: ScopeStats = Field(default_factory=ScopeStats)
    reads_remaining: int = 0
    provenance: Provenance

    @model_validator(mode="after")
    def empty_is_never_ok(self) -> "SearchResponse[HitT]":
        """I5 — a raise, not an `assert`: `python -O` strips asserts, and this must not be strippable.

        An empty ``ok`` is the single most dangerous response this system could return, because it
        is indistinguishable from a backend that failed silently. One of the four absences of
        §7.1 always says which kind of nothing this is.
        """
        if self.status == Status.OK and not (self.hits or self.unverified_hits):
            raise ValueError(
                "an empty result can never be `ok` (I5): use one of "
                f"{[s.value for s in Status if s is not Status.OK]}"
            )
        return self


# ── Family B — the call ran, and the answer is in `result` ───────────────────────────────────────

class ClaimVerdict(BaseModel):
    """One `(claim, page)` verdict (§7.2.4).

    Three states, and collapsing `unverifiable` into `absent` is the failure this shape prevents:
    it tells the agent *"that code is not on the page"* about a page it could not read.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["present", "absent", "unverifiable"]
    page_ids: list[str] = Field(default_factory=list)
    #: A capped prefix lookup over observed tokens, labelled "different part" — never a distance,
    #: never a nearest match, and structurally unable to be returned as the match itself (F16).
    present_instead: list[str] = Field(default_factory=list)
    #: Why it could not be checked, e.g. `no_text`.
    reason: str = ""


class VerifyResult(BaseModel):
    """claim → verdict. Every claim `absent` is a perfectly good ``ok`` — that is the point."""

    model_config = ConfigDict(extra="forbid")

    claims: dict[str, ClaimVerdict] = Field(default_factory=dict)


class FetchImage(BaseModel):
    """The raster as `fetch` returns it: **always** a reference, and the pixels when asked (§7.2.5).

    The one place in the whole surface where image bytes travel. :class:`ImageRef` — what a triage
    row carries — cannot grow a ``bytes_b64`` even by accident, because it is a different model
    with ``extra="forbid"``; that is P2 expressed as two types rather than as a convention.

    ``bytes_b64`` is ``None`` rather than absent when ``inline=false``, and that is deliberate: a
    field that disappears makes a generated client's type optional-by-omission, and the console and
    the runner both switch on it. ``None`` says *"no pixels travelled"* in a shape a typed caller
    can read; what matters for P2 is that the bytes are not there, not that the key is not.

    ``width`` and ``height`` are the **rendered** size here, unlike on an `ImageRef` where they
    stay 0 — by the time this model exists the raster has been made, so reporting its size costs
    nothing and is what lets a caller lay the image out before it dereferences the URL.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    dpi: int
    #: The normalised crop this raster is of, or ``None`` for the full page (D6).
    region: list[float] | None = None
    width: int = 0
    height: int = 0
    #: Present when ``inline=true`` (the default) — an agent needs the pixels in its context, and
    #: an MCP client cannot follow a URL (§7.2.5).
    bytes_b64: str | None = None


class FetchPage(BaseModel):
    """One page's material (§7.2.5). Material instead of an answer — that is the whole move.

    Each part is ``None`` when ``include`` did not ask for it, which is not the same as empty: a
    page whose text layer is genuinely blank returns ``text: ""``, and a caller that asked only for
    the image gets ``text: null``. Collapsing the two would make *"I did not ask"* look like
    *"there is nothing there"*.

    ``text_trust`` is **always** disclosed, and it is the one field here that §7.2.5's example does
    not show. It is F4 applied to this rung: dropping ``"image"`` from ``include`` makes `fetch` a
    cheap text read, and on a scanned page a cheap text read returns ``""`` — which reads as *"the
    page is blank"* unless something says the page has no text layer. `PageHit` and `LookupHit`
    both carry it for the same reason (§5.7, §7.1).
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    image: FetchImage | None = None
    #: `ingest/probe.py`'s extraction of the full page, verbatim — never a crop's text (I2, F15).
    text: str | None = None
    summary: Summary | None = None
    text_trust: TextTrust = "no_text"


class FetchResult(BaseModel):
    """`fetch`'s Family B result: the pages, in the order the caller named them (§7.1)."""

    model_config = ConfigDict(extra="forbid")

    pages: list[FetchPage] = Field(default_factory=list)


class ReadCode(BaseModel):
    """One code the vision model emitted, stamped against the page's own text (§7.2.6, Loop 1).

    **The same three states `verify` uses, because it is the same check.** The stamp is not this
    model's opinion and not the vision model's claim: it is
    :func:`~vsir.core.verify.verify_claims`' verdict, transcribed. One vocabulary, one meaning,
    one implementation — a second phrase-checker here would be free to disagree with the index it
    is checking, which is exactly what F2 is about.

    ``raw`` is the code **as the model returned it**, never normalised. That is what makes an
    `absent` stamp legible: *"the model read `K153`, and `K153` is not printed on this page"* is a
    statement about a transcription error, and correcting the string first would hide the very
    thing the stamp exists to expose.
    """

    model_config = ConfigDict(extra="forbid")

    raw: str
    status: Literal["present", "absent", "unverifiable"]
    #: The pages the stamp is about: the ones carrying it for `present`, the ones actually checked
    #: for `absent`. Empty for `unverifiable`, where no page could be checked at all.
    page_ids: list[str] = Field(default_factory=list)
    #: Observed tokens sharing a prefix, labelled *"different part"* — never a nearest match, and
    #: never returnable as the code itself (F16). Only ever on an `absent` stamp.
    present_instead: list[str] = Field(default_factory=list)
    #: Why it could not be checked, e.g. `no_text`. Only ever on an `unverifiable` stamp.
    reason: str = ""


class PageProvenance(BaseModel):
    """One page the read actually saw, and how far its text layer can be trusted (§7.2.6, §5.7).

    Every requested page appears, including one whose ``text_trust`` makes every code on it
    permanently `unverifiable` (R2). That is the disclosure, not a gap: an agent that cannot see
    which of the three pages was the scanned one cannot tell *"this code is not printed here"*
    from *"nobody could read this page"*.
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    text_trust: TextTrust = "no_text"


class ReadResult(BaseModel):
    """`read`'s Family B result (§7.2.6) — the one tool that spends, and it still never answers.

    ``sufficient`` is **mandatory and has no default**. §7.2.6: without it *"the agent cannot
    separate 'the answer is no' from 'wrong page', and will compose an answer from a page that
    never contained one"* — and a field that defaults to `True` when a model omits it defaults to
    the dangerous one. A response the model did not put it in fails to parse instead.

    There is no `score`, no confidence and no ranking (§7.6), and there is nothing here that says
    which page to read next: **retrieval judgment never happens inside `read`** — that would make
    the engine the answerer.
    """

    model_config = ConfigDict(extra="forbid")

    #: The model's bounded answer from these pages, in the document's words. Empty when the pages
    #: do not answer the question — an honest empty extract, never a padded one.
    extract: str = ""
    codes: list[ReadCode] = Field(default_factory=list)
    #: Whether these pages answer the question **on their own**. Mandatory (see the class note).
    sufficient: bool
    #: Server-derived disclosures about the read, from the closed list in
    #: :data:`~vsir.serve.tools.read.READ_FLAGS`. Never the model's, and never a free-text note.
    flags: list[str] = Field(default_factory=list)
    page_provenance: list[PageProvenance] = Field(default_factory=list)


ResultT = TypeVar("ResultT", bound=BaseModel)


class ToolEnvelope(BaseModel, Generic[ResultT]):
    """Family B. ``status`` says whether the **call** ran — not what it found.

    A missing `page_id` is a ``404 page_not_found`` and a backend failure is a 5xx, because a failed
    call returned as an empty call turns our outage into the agent's fabricated abstention.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error"]
    result: ResultT
    reads_remaining: int = 0
    provenance: Provenance


#: Re-exported so a tool module does not have to reach into `core.status` for the vocabulary.
__all__ = [
    "CHECK_STATES", "WEAK_ABS", "ClaimVerdict", "DocHit", "DocScopeStat", "FetchImage",
    "FetchPage", "FetchResult", "ImageRef", "LookupHit", "NextMoves", "PageHit", "PageProvenance",
    "Preview", "Provenance", "ReadCode", "ReadResult", "ResolveHit", "ScopeStats",
    "SearchResponse", "SectionHit", "Status", "Summary", "ToolEnvelope", "VerifyResult",
    "weakness", "wire",
]
