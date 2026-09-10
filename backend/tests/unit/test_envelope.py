"""L0 — the two envelope families (Spec §7.1, I5, §7.6).

The load-bearing assertions here are negative: an empty `ok` must be **impossible**, a `verify`
where every claim is `absent` must be **fine**, `weak` must not move when a caller changes `cap`,
and no response model anywhere may carry a field named `score` or image bytes.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from vsir.core.status import Status
from vsir.serve import envelope as env
from vsir.serve.envelope import (
    WEAK_ABS,
    ClaimVerdict,
    DocHit,
    FetchImage,
    FetchPage,
    FetchResult,
    ImageRef,
    LookupHit,
    NextMoves,
    PageHit,
    Preview,
    Provenance,
    ResolveHit,
    ScopeStats,
    SearchResponse,
    SectionHit,
    ToolEnvelope,
    VerifyResult,
    weakness,
)

PROV = Provenance(release_id="dev-0", run_id="01J0", schema_version=1)
HIT = LookupHit(page_id="D@1#p001", page_no=1, verified=True, text_trust="ok")

RESPONSE_MODELS = [
    DocHit, SectionHit, PageHit, LookupHit, ResolveHit, ImageRef, Preview, NextMoves,
    ScopeStats, Provenance, ClaimVerdict, VerifyResult, FetchPage, FetchResult,
]


# ── Family A — absence is typed (I5) ────────────────────────────────────────────────────────────

def test_an_empty_ok_is_impossible():
    with pytest.raises(ValidationError, match="never be `ok`"):
        SearchResponse[LookupHit](status=Status.OK, provenance=PROV)


@pytest.mark.parametrize("status", [s for s in Status if s is not Status.OK])
def test_every_other_status_may_be_empty(status):
    """Four absences and an error, each a different instruction to the caller."""
    response = SearchResponse[LookupHit](status=status, provenance=PROV)

    assert response.hits == []
    assert response.status == status


def test_an_ok_with_only_unverified_hits_is_valid():
    """D3 — `vlm_codes` is the only recall on a scanned page, and it is still a result."""
    response = SearchResponse[LookupHit](
        status=Status.OK, unverified_hits=[HIT.model_copy(update={"verified": False})],
        provenance=PROV,
    )

    assert response.hits == []
    assert response.unverified_hits[0].verified is False


def test_the_validator_survives_optimisation():
    """A raise, not an `assert`: `python -O` strips asserts, and I5 must not be strippable."""
    source = (env.__file__ and open(env.__file__, encoding="utf-8").read()) or ""

    assert "raise ValueError" in source
    assert "assert " not in source.split("def empty_is_never_ok")[1].split("return self")[0]


def test_total_is_the_set_size_not_the_page_of_it():
    """A caller must be able to tell "20 of 400" from "20 of 20"."""
    response = SearchResponse[LookupHit](status=Status.OK, hits=[HIT], total=400, capped=True,
                                         provenance=PROV)

    assert response.total == 400
    assert len(response.hits) == 1
    assert response.capped is True


# ── `weak` is a server signal, not a caller's ───────────────────────────────────────────────────

def test_weak_does_not_move_with_the_callers_cap():
    """§7.1 — a trust signal a client could flip by passing `cap=200` is worse than none."""
    assert WEAK_ABS == 20
    for cap in (5, 20, 200, 10_000):
        assert weakness(total=21, scope_pages=80) is True, cap


@pytest.mark.parametrize(
    ("total", "pages", "expected"),
    [
        (21, 80, True),     # max(20, 20) = 20, and 21 > 20
        (20, 80, False),    # exactly at the bound is not weak
        (21, 400, False),   # max(20, 100) = 100: 21 hits in a 400-page scope is precise
        (101, 400, True),
        (21, 0, True),      # an empty scope: the absolute floor is what applies
        (0, 0, False),
    ],
)
def test_the_weakness_rule(total, pages, expected):
    assert weakness(total, pages) is expected


# ── Family B — the call ran; the answer is in `result` ──────────────────────────────────────────

def test_a_verify_where_every_claim_is_absent_is_ok():
    """The shape Family B exists for: the call worked, and the answer is no."""
    result = VerifyResult(claims={
        "K158": ClaimVerdict(status="absent"),
        "K73": ClaimVerdict(status="absent", present_instead=["K78"]),
        "SF 9.9": ClaimVerdict(status="unverifiable", reason="no_text"),
    })

    tool = ToolEnvelope[VerifyResult](status="ok", result=result, provenance=PROV)

    assert tool.status == "ok"
    assert {v.status for v in tool.result.claims.values()} == {"absent", "unverifiable"}


def test_the_three_check_states_are_the_only_ones():
    with pytest.raises(ValidationError):
        ClaimVerdict(status="probably")
    with pytest.raises(ValidationError):
        ClaimVerdict(status="not_found")


def test_present_instead_is_a_separate_field_from_the_verdict():
    """F16 — a near miss is a disclosure beside `absent`, never the match itself."""
    verdict = ClaimVerdict(status="absent", present_instead=["K78"])

    assert verdict.status == "absent"
    assert verdict.page_ids == []


# ── §7.6 refusals, as structure ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", RESPONSE_MODELS)
def test_no_response_model_declares_a_score(model):
    assert "score" not in model.model_fields
    assert not any("score" in name for name in model.model_fields)


@pytest.mark.parametrize("model", RESPONSE_MODELS)
def test_no_response_model_carries_image_bytes(model):
    """P2, D12 — `bytes_b64` exists only on `fetch`, which is not one of these."""
    assert not any(name in {"bytes_b64", "bytes", "image_b64"} for name in model.model_fields)


@pytest.mark.parametrize(("model", "field"), [(DocHit, "best_rank"), (SectionHit, "best_rank"),
                                              (PageHit, "rank")])
def test_rank_is_a_required_ordinal(model, field):
    """A position is not a confidence — and it is required, not optional."""
    assert model.model_fields[field].is_required()
    assert model.model_fields[field].annotation is int


def test_only_fetchs_image_may_carry_pixels_and_it_is_a_different_model():
    """P2 as two types rather than as a convention (§7.1, §7.2.5, D12).

    `ImageRef` — what every triage row carries — cannot grow a `bytes_b64` even by accident,
    because `extra="forbid"` makes adding one a validation error rather than a wider row. The
    bytes live on `FetchImage`, which only `fetch` returns, and which additionally carries the
    `region` a crop is of.
    """
    assert "bytes_b64" in FetchImage.model_fields
    assert "bytes_b64" not in ImageRef.model_fields
    assert "region" in FetchImage.model_fields and "region" not in ImageRef.model_fields

    with pytest.raises(ValidationError):
        ImageRef(url="/pages/D%401%23p001/image?dpi=150", dpi=150, bytes_b64="iVBORw0KGgo")


def test_a_fetched_image_says_no_pixels_travelled_rather_than_dropping_the_field():
    """`inline=false` returns the reference only — as an explicit `None`, not a missing key.

    A field that disappears makes a generated client's type optional-by-omission, and the console
    and the runner both switch on it. What P2 requires is that the *bytes* are not there.
    """
    reference = FetchImage(url="/pages/D%401%23p001/image?dpi=150", dpi=150, width=1240,
                           height=1754)

    assert reference.bytes_b64 is None
    assert "bytes_b64" in reference.model_dump()
    assert reference.model_dump()["bytes_b64"] is None
    assert FetchImage(url="u", dpi=150, bytes_b64="iVBORw0KGgo").bytes_b64


def test_a_fetched_page_distinguishes_not_asked_for_from_empty():
    """`include` controls the parts, and `None` is not `""` (§7.2.5).

    A page whose text layer is genuinely blank returns `text: ""`; a caller that asked only for
    the image gets `text: null`. Collapsing them would make *"I did not ask"* read as *"there is
    nothing there"* — the F4 injury, one rung along.
    """
    image_only = FetchPage(page_id="D@1#p001", text_trust="no_text")
    blank_text = FetchPage(page_id="D@1#p002", text="", text_trust="ok")

    assert image_only.text is None and blank_text.text == ""
    assert image_only.summary is None
    # F4's disclosure is not optional on this rung: a scanned page's empty `text` has to be
    # readable as "no text layer" without a second call.
    assert "text_trust" in FetchPage.model_fields
    assert FetchResult().pages == []


def test_an_image_reference_carries_no_pixels():
    ref = ImageRef(url="/pages/D%401%23p001/image?dpi=150", thumb_url="…?dpi=72", dpi=150,
                   width=1240, height=1754)

    assert "bytes_b64" not in ref.model_dump()
    assert set(ref.model_dump()) == {"url", "thumb_url", "dpi", "width", "height"}


def test_an_aggregate_row_hands_back_a_scope_not_a_citation():
    """§7.1 — `DocHit` and `SectionHit` answer "which binder / which chapter", not "which page"."""
    assert "page_id" not in DocHit.model_fields
    assert "page_id" not in SectionHit.model_fields
    assert "preview" in DocHit.model_fields and "preview" in SectionHit.model_fields


def test_an_aggregate_row_still_carries_a_thumbnail():
    """A `searchable_ratio: 0.00` row is the blind spot; a thumbnail is how a person sees it."""
    hit = DocHit(doc_id="D", best_rank=1, searchable_ratio=0.0,
                 preview=Preview(page_id="D@1#p001", thumb_url="…?dpi=72"))

    assert hit.preview.thumb_url


def test_the_scope_is_echoed_because_the_service_holds_no_session():
    """F8, C11 — the caller's scope is the whole truth about what was searched."""
    response = SearchResponse[LookupHit](status=Status.OK, hits=[HIT],
                                         effective_scope={"doc_id": ["TC1E-SF"]},
                                         scope_stats=ScopeStats(pages=55, pages_no_text=2),
                                         provenance=PROV)

    assert response.effective_scope == {"doc_id": ["TC1E-SF"]}
    assert response.scope_stats.pages_no_text == 2


def test_every_response_carries_the_release_that_produced_it():
    """§15 Factor V — any answer traces to the exact code and configuration behind it."""
    for response in (SearchResponse[LookupHit](status=Status.NOT_FOUND, provenance=PROV),
                     ToolEnvelope[VerifyResult](status="ok", result=VerifyResult(),
                                                provenance=PROV)):
        assert response.provenance.release_id == "dev-0"
        assert response.provenance.schema_version == 1


def test_a_response_refuses_an_unknown_field():
    with pytest.raises(ValidationError):
        SearchResponse[LookupHit](status=Status.NOT_FOUND, provenance=PROV, fused=0.5)


def test_the_hit_type_is_declared_as_the_five_rungs():
    """§7.1's `HitT` is a *constrained* TypeVar: those five models and nothing else.

    Pydantic does not police the constraint at subscription time — `SearchResponse[Rogue]` builds a
    class — so the declaration is the contract and the value check below is the enforcement.
    """
    assert env.HitT.__constraints__ == (DocHit, SectionHit, PageHit, LookupHit, ResolveHit)


def test_a_hit_of_the_wrong_rung_is_rejected():
    """The enforcement that bites: a `lookup` response cannot carry a document row."""
    with pytest.raises(ValidationError):
        SearchResponse[LookupHit](status=Status.OK, hits=[DocHit(doc_id="D", best_rank=1)],
                                  provenance=PROV)


def test_reads_remaining_is_on_both_families():
    """Cost goes to the audit log; the caller gets one integer (§7.4)."""
    assert "reads_remaining" in SearchResponse.model_fields
    assert "reads_remaining" in ToolEnvelope.model_fields
    assert not any("usd" in name or "cost" in name for name in SearchResponse.model_fields)
