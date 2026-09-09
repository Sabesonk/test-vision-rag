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

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vsir.core.record import SCHEMA_VERSION, TextTrust
from vsir.core.status import CHECK_STATES, Status

#: §7.1 — a **server** constant. `cap` controls how many hits come back and nothing else, so a
#: trust signal a client could flip by passing `cap=200` would be worse than no signal at all.
WEAK_ABS = 20


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
    """

    model_config = ConfigDict(extra="forbid")

    expand: dict = Field(default_factory=dict)
    neighbours: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    suggest: list[str] = Field(default_factory=list)


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

class DocHit(BaseModel):
    """*"Which binder?"* — hands back a scope to descend into, and carries no `page_id` at all."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    title: str = ""
    doc_type: str = ""
    pages_matched: int = 0
    best_rank: int
    #: pages with a text layer ÷ pages. The agent's blind spot, as a number (§5.7).
    searchable_ratio: float = 0.0
    summary: str = ""
    preview: Preview | None = None


class SectionHit(BaseModel):
    """*"Which chapter?"* — likewise a scope, not a citation."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str = ""
    page_range: tuple[int, int] | None = None
    pages_matched: int = 0
    best_rank: int
    preview: Preview | None = None


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
    "CHECK_STATES", "WEAK_ABS", "ClaimVerdict", "DocHit", "DocScopeStat", "ImageRef", "LookupHit",
    "NextMoves", "PageHit", "Preview", "Provenance", "ResolveHit", "ScopeStats", "SearchResponse",
    "SectionHit", "Status", "ToolEnvelope", "VerifyResult", "weakness",
]
