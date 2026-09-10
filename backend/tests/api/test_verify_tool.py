"""L2 — `verify` **over HTTP** (Spec §7.2.4, §7.1 Family B). **F2's tool half.**

The question this tool answers is the one the whole system exists to be trusted about: *is this
code actually printed on the page you are about to cite it from?* F2 is the failure where the
answer is yes and the code is not there, and the guard is structural rather than tested — the
wrapper calls `core/verify.py`, which calls the one `exact_filter`, scoped to one page. There is
no second matcher for a test to catch drifting, because there is no second matcher.

So what this file actually proves is the shape around that: Family B, three states that never
collapse into two, per `(claim, page)` rather than per claim, and a missing page that is a `404`
rather than a verdict.

Every row is read from `data/fixtures/synthetic_pages/expected.json` — the same table
`tests/unit/test_verify_claims.py` asserts against the pure function, so a disagreement between
the two is a finding rather than a re-baseline (C10).
"""
from __future__ import annotations

from typing import Any

import pytest

from vsir.core.status import CHECK_STATES
from vsir.eval import synthetic
from vsir.serve.caps import MAX_VERIFY_PAIRS
from vsir.serve.envelope import ToolEnvelope, VerifyResult

VERIFY = "/tools/verify"

EXPECTED = synthetic.load().expected


def check(served: Any, token_header: dict, claims: list[str], page_ids: list[str]) -> dict:
    response = served.post(VERIFY, json={"claims": claims, "page_ids": page_ids},
                           headers=token_header)
    assert response.status_code == 200, response.text
    return response.json()


def verdicts(payload: dict) -> dict:
    return payload["result"]["claims"]


# ── the §12.3 / §13 M1 verify table, through the wrapper ────────────────────────────────────────

@pytest.mark.parametrize("row", EXPECTED["verify"],
                         ids=lambda row: f"{row['claim']}-{row['status']}")
def test_every_verify_row_of_the_acceptance_table(served, token_header, row):
    """Each row of the corpus's own table, over HTTP. The wrapper adds transport, not judgement."""
    payload = check(served, token_header, [row["claim"]], row["page_ids"])

    assert payload["status"] == "ok"
    verdict = verdicts(payload)[row["claim"]]
    assert verdict["status"] == row["status"]
    if "on" in row:
        assert verdict["page_ids"] == row["on"]
    if "present_instead" in row:
        assert verdict["present_instead"] == row["present_instead"]
    if "reason" in row:
        assert verdict["reason"] == row["reason"]


def test_the_decoy_page_is_absent_not_present(served, token_header):
    """**F2, the tool half.** All three tokens are on p008; the phrase is not.

    This is the row that would go green under any-order matching and must not. `lookup` and
    `verify` ask the index the same question through the same filter, so a `lookup` that refused
    to return this page and a `verify` that confirmed it would be a contradiction the code cannot
    express.
    """
    row = next(row for row in EXPECTED["verify"]
               if row["claim"] == "SF 1.1A" and row["status"] == "absent")

    payload = check(served, token_header, [row["claim"]], row["page_ids"])

    assert verdicts(payload)[row["claim"]]["status"] == "absent"


def test_a_verify_where_every_claim_is_absent_is_ok(served, token_header):
    """**U015's acceptance criterion, and the reason Family B exists** (§7.1).

    Three legitimately-absent claims have no honest shape in a Family A envelope: it would be an
    empty result, which is indistinguishable from an outage — and `empty_is_never_ok` would
    refuse to build it at all. Here the call ran, and the answer is no, three times.
    """
    page = EXPECTED["decoy"]["page_id"]

    payload = check(served, token_header, ["K999", "SF 1.1A", "SF 5.5b"], [page])

    assert payload["status"] == "ok"
    assert [verdict["status"] for verdict in verdicts(payload).values()] == ["absent"] * 3


def test_the_three_states_never_collapse_into_two(served, token_header):
    """§7.2.4 — `unverifiable` is not a kind of `absent`, and the distinction is the deliverable.

    Telling an agent *"that code is not on the page"* about a page nobody could read converts our
    blind spot into its confident denial. One call, three pages, three different reasons for not
    being able to answer — and each one says which.
    """
    no_text = EXPECTED["no_text"]
    untrusted = EXPECTED["untrusted"]
    superseded = next((row for row in EXPECTED["verify"]
                       if row.get("reason") == "not_current"), None)

    states = {}
    for row in (no_text, untrusted):
        payload = check(served, token_header, [row["label"]], [row["page_id"]])
        states[row["label"]] = verdicts(payload)[row["label"]]
    assert states[no_text["label"]] == {"status": "unverifiable", "page_ids": [],
                                        "present_instead": [], "reason": "no_text"}
    assert states[untrusted["label"]]["reason"] == "untrusted"

    assert superseded is not None, "the corpus must carry an is_current:false page (I7)"
    payload = check(served, token_header, [superseded["claim"]], superseded["page_ids"])
    assert verdicts(payload)[superseded["claim"]]["reason"] == "not_current"


def test_a_verdict_is_per_claim_and_page_not_per_claim(served, token_header):
    """I8 — a draft citing `p001–p002` must not let a code from the neighbouring page through.

    The verdict names the page the evidence is actually on, so the answer gate can reject a
    sentence that cites the other one.
    """
    row = next(row for row in EXPECTED["verify"] if row["claim"] == "K158")

    payload = check(served, token_header, [row["claim"]], row["page_ids"])

    verdict = verdicts(payload)[row["claim"]]
    assert verdict["status"] == "present"
    assert verdict["page_ids"] == row["on"]
    assert len(row["page_ids"]) == 2 and len(verdict["page_ids"]) == 1


def test_present_instead_is_a_different_part_and_never_the_match(served, token_header):
    """F16 — `K73` on a page that prints `K78`: `absent`, plus what *is* there, labelled as other.

    A near-miss returned as the match is the injury the design exists to prevent, and the shape
    is what makes it structurally impossible: `present_instead` sits inside an `absent` verdict,
    so it cannot be read as a confirmation however carelessly a client renders it.
    """
    row = next(row for row in EXPECTED["verify"] if row["claim"] == "K73")

    payload = check(served, token_header, [row["claim"]], row["page_ids"])

    verdict = verdicts(payload)[row["claim"]]
    assert verdict["status"] == "absent"
    assert verdict["present_instead"] == row["present_instead"]
    assert row["claim"].lower() not in verdict["present_instead"]


def test_a_verify_uncited_page_reports_absent(served, token_header):
    """F2's named test — a code that is real elsewhere in the corpus is `absent` *here*.

    `K158` is genuinely printed on p001. Asked about p008 it is `absent`, because the question is
    about a pair and never about the corpus.
    """
    payload = check(served, token_header, ["K158"], [EXPECTED["decoy"]["page_id"]])

    assert verdicts(payload)["K158"]["status"] == "absent"


# ── the envelope (§7.1 Family B) ────────────────────────────────────────────────────────────────

def test_the_envelope_is_family_b_and_validates_as_the_declared_model(served, token_header):
    """`status` says whether the **call** ran; the verdicts live in `result`.

    Family B carries `reads_remaining` and `provenance` and — per §7.1's model — no
    `effective_scope` and no `scope_stats`: there is no scope to echo, because the caller named
    the pages outright.
    """
    payload = check(served, token_header, ["K158"], [EXPECTED["verify"][0]["page_ids"][0]])

    parsed = ToolEnvelope[VerifyResult].model_validate(payload)

    assert parsed.status == "ok"
    assert set(payload) == {"status", "result", "reads_remaining", "provenance"}
    assert payload["provenance"] == {"run_id": "", "release_id": "test", "schema_version": 1}
    assert isinstance(payload["reads_remaining"], int)


def test_every_verdict_uses_the_one_check_vocabulary(served, token_header):
    """One vocabulary, in `verify` and in `read`'s per-code stamps: `present | absent | unverifiable`."""
    pages = [row["page_ids"][0] for row in EXPECTED["verify"]]
    claims = sorted({row["claim"] for row in EXPECTED["verify"]})

    payload = check(served, token_header, claims, sorted(set(pages)))

    assert {verdict["status"] for verdict in verdicts(payload).values()} <= set(CHECK_STATES)
    assert "verified" not in str(payload)  # a boolean belongs to a `lookup` hit, never here


def test_verify_is_free(served, token_header):
    """§7.2.4 heading — `verify(claims, page_ids)` **(free)**. It bills nothing and audits nothing."""
    page = EXPECTED["verify"][0]["page_ids"][0]

    first = check(served, token_header, ["K158"], [page])
    second = check(served, token_header, ["K158"], [page])

    assert first["reads_remaining"] == second["reads_remaining"]


# ── the typed refusals (§7.1, §7.3) ─────────────────────────────────────────────────────────────

def test_a_missing_page_id_is_404_page_not_found(served, token_header):
    """§7.1, and U015's acceptance criterion — *"never an empty result"*.

    An `absent` about a page that does not exist is a statement about nothing, and `unverifiable`
    would hint the page might carry the code after all. Both are worse than saying so.
    """
    response = served.post(VERIFY, json={"claims": ["K158"], "page_ids": ["SYN-M1@1.0#p999"]},
                           headers=token_header)

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "page_not_found"
    assert body["page_ids"] == ["SYN-M1@1.0#p999"]
    assert "result" not in body and "claims" not in body


def test_one_missing_page_refuses_the_whole_call(served, token_header):
    """Not a partial answer: a caller that named four pages and got three verdicts would not
    notice, and would cite the three as though the fourth had been checked."""
    good = EXPECTED["verify"][0]["page_ids"][0]

    response = served.post(VERIFY, json={"claims": ["K158"],
                                         "page_ids": [good, "SYN-M1@1.0#p998"]},
                           headers=token_header)

    assert response.status_code == 404
    assert response.json()["page_ids"] == ["SYN-M1@1.0#p998"]


def test_a_malformed_page_id_is_a_400_and_not_a_404(served, token_header):
    """A citation this service cannot parse is the caller's bug; a page it does not hold is a
    fact about the corpus. A caller retries them differently, so they stay different."""
    response = served.post(VERIFY, json={"claims": ["K158"], "page_ids": ["page eight"]},
                           headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "page_id_invalid"


@pytest.mark.parametrize("body", [
    {"claims": [], "page_ids": ["SYN-M1@1.0#p001"]},
    {"claims": ["K158"], "page_ids": []},
])
def test_an_empty_list_is_a_typed_400(served, token_header, body):
    """A verdict map with no verdicts in it reads as *"nothing to answer for"*, which is the one
    thing an answer gate must never conclude by accident (I8)."""
    response = served.post(VERIFY, json=body, headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "verify_empty"


def test_too_many_pairs_is_a_typed_400_naming_the_bound(served, token_header):
    """The work is the **product** of the two lists, so the bound is on the product (§7.3's family)."""
    page = EXPECTED["verify"][0]["page_ids"][0]
    claims = [f"K{index}" for index in range(MAX_VERIFY_PAIRS + 1)]

    response = served.post(VERIFY, json={"claims": claims, "page_ids": [page]},
                           headers=token_header)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "verify_budget_exceeded"
    assert body["limit"] == MAX_VERIFY_PAIRS
    assert body["requested"] == len(claims)


def test_verify_takes_no_image(served, token_header):
    """I2, I3 — a photograph may *find* a candidate page; it can never *confirm* a code."""
    response = served.post(VERIFY, json={"claims": ["K158"], "page_ids": ["SYN-M1@1.0#p001"],
                                         "image": "data:image/png;base64,AAAA"},
                           headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert "image" in str(response.json()["problems"])
