"""L0 — the answer gate (Spec §8.4, I8): per `(claim, page)`, server-side, and unconditional.

This is the last thing between a model's sentence and a person's eyes, and it is the invariant the
whole build exists to reach: **no code is rendered that `verify` did not clear for the page it is
cited on.** Everything below is free — the `verify` calls are a fake here so that each of §8.4's
three outcomes can be produced deliberately — and every row is a statement about the shipped
function rather than about an environment.

Four properties are asserted structurally rather than by example, because they are the ones a
well-meaning change would quietly break:

* the gate makes **one call per `(claim, page)` pair** and returns the log, so *"was this code
  checked against the page it is cited on?"* is answerable without reading the prose;
* it **does not branch on the route** — the same draft gated as a `read` and as a `fetch` produces
  the identical verdicts, which is what §8.4's *unconditional* has to mean given that the default
  `fetch` route skips Loop 1's automatic stamp (§8.1a);
* a **rejected draft renders nothing at all**, and the rejection does not echo the code;
* a check that **could not run** is not a verdict (§7.1, §11.3) — an outage must never arrive as
  *"that code is not on the page"*.
"""
from __future__ import annotations

from typing import Mapping

import pytest

from vsir.core.verify import ABSENT, PRESENT, UNVERIFIABLE
from vsir.runner.answer import (
    BADGE_READ_FROM_IMAGE,
    BADGE_VERIFIED,
    WARNING_UNVERIFIABLE,
    Claim,
    Draft,
    GateUnavailable,
    claims_from,
    codes_in,
    gate,
)
from vsir.serve.envelope import ClaimVerdict

P019, P020 = "SYN@1.0#p019", "SYN@1.0#p020"


def verdicts(table: Mapping[tuple[str, str], ClaimVerdict], *, log: list | None = None):
    """A fake `verify`, and the whole reason this suite is free.

    It answers per `(claim, page)` because that is the shape the real one has (§7.2.4 folds a
    matrix), and it records every pair it was asked about — so a test can assert on the calls the
    gate made and not only on what came back.
    """
    def verify(claim: str, page_id: str) -> ClaimVerdict:
        if log is not None:
            log.append((claim, page_id))
        return table.get(
            (claim, page_id),
            ClaimVerdict(status=ABSENT, page_ids=[page_id], present_instead=[], reason=""))

    return verify


def present(*page_ids: str) -> ClaimVerdict:
    return ClaimVerdict(status=PRESENT, page_ids=list(page_ids))


def absent(page_id: str, *, instead: tuple[str, ...] = ()) -> ClaimVerdict:
    return ClaimVerdict(status=ABSENT, page_ids=[page_id], present_instead=list(instead))


def unverifiable(reason: str = "no_text") -> ClaimVerdict:
    return ClaimVerdict(status=UNVERIFIABLE, page_ids=[], reason=reason)


def draft(*claims: Claim, text: str = "B219 closes before K119 is monitored.",
          route: str = "read", pages: tuple[str, ...] = (P019,)) -> Draft:
    return Draft(text=text, claims=list(claims), pages=list(pages), route=route)


# ── §8.4's three outcomes ────────────────────────────────────────────────────────────────────────

def test_a_present_code_renders_with_the_verified_badge():
    """*"`present` → render"*. The strongest thing this system can say about a code (I2)."""
    gated = gate(draft(Claim(code="K119", page_ids=[P019])),
                 verify=verdicts({("K119", P019): present(P019)}))

    assert gated.cleared
    assert [(one.code, one.page_id, one.status, one.badge) for one in gated.rendered] == [
        ("K119", P019, PRESENT, BADGE_VERIFIED)]
    assert gated.answer().text == "B219 closes before K119 is monitored."
    assert gated.answer().warnings == [], "nothing to warn about: every code was checked"


def test_an_unverifiable_code_renders_carrying_the_read_from_image_badge():
    """*"`unverifiable` → render with the badge"*. A page nobody could read is disclosed, not hidden.

    The badge's wording is asserted as a literal because it is the product's contract with a
    reader and M7 renders it as load-bearing UI (§13 M7): *"read from image, not text-verified"*.
    """
    gated = gate(draft(Claim(code="C24", page_ids=[P019])),
                 verify=verdicts({("C24", P019): unverifiable()}))

    assert gated.cleared, "an unchecked code is rendered — with its badge — and never dropped"
    assert gated.rendered[0].status == UNVERIFIABLE
    assert gated.rendered[0].badge == "read from image, not text-verified"
    assert gated.answer().warnings == [WARNING_UNVERIFIABLE], (
        "the amber warning of §13 M7 is raised once for the answer, not once per claim")


def test_an_absent_code_rejects_the_whole_draft_and_nothing_is_rendered():
    """*"anything else → reject the draft"*. Not the code — **the draft** (§8.4).

    A draft with one uncleared code is not partially rendered: the sentence was written from an
    evidence set that turned out not to hold, so no part of it is the answer.
    """
    gated = gate(draft(Claim(code="K119", page_ids=[P019]),
                       Claim(code="K152", page_ids=[P019])),
                 verify=verdicts({("K119", P019): present(P019),
                                  ("K152", P019): absent(P019, instead=("k119", "k120"))}))

    assert not gated.cleared
    assert [one.present_instead for one in gated.rejections] == [["k119", "k120"]], (
        "the rejection carries `present_instead` — what the page really prints (F16)")
    with pytest.raises(ValueError, match="rejected"):
        gated.answer()


def test_a_rejection_never_echoes_the_code_it_rejected():
    """The misread code appears **nowhere** in what a caller receives.

    A body that said *"K152 is not printed on p019"* would put the misread code in front of the
    caller in the one place a person is reading for an answer, and a UI that renders a rejection
    field is one CSS change away from rendering it as the answer. The pair is still visible in
    the call log — with an empty ``claim`` — so the check is auditable without the disclosure.
    """
    gated = gate(draft(Claim(code="K152", page_ids=[P019])),
                 verify=verdicts({("K152", P019): absent(P019, instead=("k120",))}))

    serialised = [one.model_dump_json() for one in gated.rejections]
    assert not any("K152" in body or "k152" in body for body in serialised), serialised
    assert "code" not in gated.rejections[0].model_dump(), (
        "there is no field on a rejection for the code — that is the point, not an omission")
    assert [(row.claim, row.status) for row in gated.checks] == [("", ABSENT)], (
        "the `(claim, page)` row survives with its claim redacted: the call is auditable")


# ── the call log (I8's evidence) ─────────────────────────────────────────────────────────────────

def test_the_gate_makes_one_verify_call_per_claim_and_page_pair():
    """I8 is *"against the page it is cited on"*, so a claim on two pages is checked twice.

    One call over the set would answer *"is this code somewhere in these pages?"*, which is the
    question that lets a code from the neighbouring sheet through (§7.2.4's own argument).
    """
    log: list[tuple[str, str]] = []
    gated = gate(draft(Claim(code="K119", page_ids=[P019, P020]),
                       Claim(code="SI4", page_ids=[P019, P020]),
                       pages=(P019, P020)),
                 verify=verdicts({("K119", P019): present(P019),
                                  ("K119", P020): absent(P020),
                                  ("SI4", P019): present(P019),
                                  ("SI4", P020): present(P020)}, log=log))

    assert log == [("K119", P019), ("K119", P020), ("SI4", P019), ("SI4", P020)]
    assert len(gated.checks) == 4
    assert gated.cleared, "present on one cited page is enough for the claim to be true of the set"
    assert [one.page_id for one in gated.rendered] == [P019, P019], (
        "the verdict names the page the evidence sits on, not the first page cited")


def test_the_fold_prefers_present_then_absent_then_unverifiable():
    """:mod:`vsir.core.verify`'s fold order, deliberately identical (§7.2.4).

    A claim cited on a readable page and a scanned one is `absent` **about the readable one**
    rather than badged as unreadable: `absent` beats `unverifiable` when a page was really
    checked, and pretending otherwise would badge a fabricated code as *read from image*.
    """
    gated = gate(draft(Claim(code="K999", page_ids=[P019, P020]), pages=(P019, P020)),
                 verify=verdicts({("K999", P019): unverifiable(),
                                  ("K999", P020): absent(P020, instead=("k120",))}))

    assert not gated.cleared
    assert gated.rejections[0].page_id == P020


# ── unconditional: the same gate on both routes (§8.1a, §8.4) ────────────────────────────────────

@pytest.mark.parametrize("route", ["read", "fetch"])
def test_the_gate_runs_identically_on_the_read_and_fetch_routes(route: str):
    """§8.4 is unconditional **because** the `fetch` route skips Loop 1's automatic stamp.

    On the `fetch` route the calling agent has read codes off a raster with nothing checking them
    (§8.1a), so a gate that trusted a route would be a gate that trusts the one path with no
    check behind it. Forcing each route with the same draft is the assertion the plan asks for.
    """
    claims = (Claim(code="K119", page_ids=[P019]), Claim(code="K152", page_ids=[P019]))
    table = {("K119", P019): present(P019), ("K152", P019): absent(P019, instead=("k120",))}

    gated = gate(draft(*claims, route=route), verify=verdicts(table))

    assert not gated.cleared, f"the {route} route is gated exactly as the other one is"
    assert [(row.claim, row.page_id, row.status) for row in gated.checks] == [
        ("K119", P019, PRESENT), ("", P019, ABSENT)]


def test_the_route_is_recorded_on_the_answer_and_never_read_by_the_gate():
    """The route is provenance, not a branch: it survives onto the answer and changes nothing."""
    verify = verdicts({("K119", P019): present(P019)})
    read = gate(draft(Claim(code="K119", page_ids=[P019]), route="read"), verify=verify)
    fetch = gate(draft(Claim(code="K119", page_ids=[P019]), route="fetch"), verify=verify)

    assert read.answer().route == "read" and fetch.answer().route == "fetch"
    assert read.rendered == fetch.rendered


# ── an outage is never a verdict (§7.1, §11.3) ───────────────────────────────────────────────────

def test_a_check_that_could_not_run_is_not_an_absent_verdict():
    """:class:`GateUnavailable`, propagated. Never `absent`, and never `unverifiable`.

    Reading a failed check as `absent` would reject good drafts during an outage; reading it as
    `unverifiable` would badge an unchecked code as *read from image* and render it. Neither is a
    verdict, so the gate refuses to produce one.
    """
    def unavailable(claim: str, page_id: str) -> ClaimVerdict:
        raise GateUnavailable("the index did not answer", claim=claim, page_id=page_id)

    with pytest.raises(GateUnavailable):
        gate(draft(Claim(code="K119", page_ids=[P019])), verify=unavailable)


def test_a_claim_cited_on_no_page_is_rejected_rather_than_rendered():
    """A code asserted over nothing has nothing to verify it against, so it cannot render."""
    gated = gate(draft(Claim(code="K119", page_ids=[])), verify=verdicts({}))

    assert not gated.cleared
    assert gated.rejections[0].reason == "no_cited_page"
    assert gated.checks == (), "there was no pair to check, so no call was made"


# ── what counts as a claim (§8.4's *"codes in the draft"*) ───────────────────────────────────────

def test_a_code_in_the_prose_that_the_model_did_not_declare_is_still_gated():
    """I8 with a hole in it would be gating the model's ``codes`` list and not its sentence."""
    claims = claims_from([{"raw": "K119", "status": PRESENT, "page_ids": [P019]}],
                         text="K119 is monitored, and so is K152.", pages=[P019])

    assert [one.code for one in claims] == ["K119", "k152"], (
        "the union, declared first: the undeclared one arrives as the index's own token")
    assert all(one.page_ids == [P019] for one in claims)


def test_a_declared_code_is_not_gated_twice_under_its_own_tokens():
    """A multi-token code — ``EAO 84-5140.1019`` — is one claim, checked as the phrase it is."""
    claims = claims_from([{"raw": "EAO 84-5140.1019", "status": PRESENT, "page_ids": [P019]}],
                         text="The button is EAO 84-5140.1019 on that sheet.", pages=[P019])

    assert [one.code for one in claims] == ["EAO 84-5140.1019"]


def test_a_bare_number_in_the_prose_is_not_a_claim():
    """*"Category 3"*, *"stage 17"*: a number in a sentence is a quantity, not a printed code.

    It is `present` on essentially any page of a technical document, so gating it costs a call and
    tells a reader nothing, while putting `3 — verified` in an answer beside a real part number.
    A code the model **declared** is still checked exactly as it spelled it.
    """
    prose = "SF 2.19C reaches Category 3 PL=D at stage 17 with 2 channel wiring"

    assert codes_in(prose) == ("19c",), (
        "`2`, `3` and `17` are numbers in a sentence; `19c` is the tail of a printed label and "
        "is collected, because a token with a letter in it can carry a misread")


def test_an_unverifiable_stamp_falls_back_to_the_pages_that_were_looked_at():
    """A stamp with no pages of its own is a page nobody could check — cite what was read."""
    claims = claims_from([{"raw": "C24", "status": UNVERIFIABLE, "page_ids": []}],
                         text="C24 SYNTHETIC SAFETY MANUAL", pages=[P019, P020])

    assert claims[0].page_ids == [P019, P020]
