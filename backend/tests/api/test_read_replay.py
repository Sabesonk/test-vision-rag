"""L2 — `POST /tools/read` end to end, over a really ingested document, for nothing (§7.2.6, D10).

The unit that spends, proved without spending. Every row here runs the shipped path — the HTTP
route, the dispatcher, the budget, the document store, the renderer at the pinned dpi and the
`core/verify.py` stamp — and the only thing standing in for Gemini is a frozen response served by
cache key, which is production's own code path with a different attached service (§15 Factor IV).

**Nothing below computes what it asserts.** The extract, the codes, the stamps and the flags all
come out of `data/fixtures/synthetic_3window/expected.json`, written beside the frozen responses
before this tool existed. C10's rule applies to a stamp exactly as it applies to a page count: a
number a test derives from the code under test cannot fail, it can only re-baseline itself.

`impl` could not run this test at all. Its `read()` returned a 503 for every page because the
raster path on the record was stale (register **A5**), and there was no fixture mechanism — so
the only way to see whether a read worked was to buy one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
EXPECTED = json.loads(
    (REPO / "data/fixtures/synthetic_3window/expected.json").read_text(encoding="utf-8"))
READ = EXPECTED["read"]
CASES = READ["cases"]


def case(name: str) -> dict:
    return CASES[name]


def ask(rastered: Any, name: str) -> Any:
    """Run one frozen case through the served tool, by the pages and question it was frozen for."""
    row = case(name)
    return rastered.read(rastered.page_ids(*row["pages"]), row["question"])


def stamps_of(payload: dict) -> list[dict]:
    return payload["result"]["codes"]


# ── the case §7.2.6's own example is drawn from ─────────────────────────────────────────────────

def test_a_read_answers_and_every_code_comes_back_stamped(rastered: Any):
    """The whole contract in one call: an extract, a stamped code table, and `sufficient`."""
    row = case("answer")
    response = ask(rastered, "answer")

    assert response.status_code == 200, response.text
    payload = response.json()
    # Family B: `status` says the **call** ran. The answer lives in `result` (§7.1).
    assert payload["status"] == "ok"
    assert payload["result"]["extract"] == row["extract"]
    assert payload["result"]["sufficient"] is row["sufficient"]
    assert [code["raw"] for code in stamps_of(payload)] == row["codes"], (
        "the codes come back in the order the model emitted them, verbatim and unsorted")


def test_every_stamp_matches_the_table_written_before_the_tool_existed(rastered: Any):
    """C10 — `present`, `absent` with `present_instead`, and the pages each verdict is about.

    ``K152`` is the deliberate misread: pages 19 and 20 print ``K119`` and ``K120``, so the stamp
    is `absent` and the disclosure beside it is a **prefix lookup over observed tokens** (F16) —
    *"different part"*, never a nearest match, and structurally unable to be returned as the code.
    """
    row = case("answer")
    payload = ask(rastered, "answer").json()

    for stamp, expected in zip(stamps_of(payload), row["stamps"]):
        assert stamp["raw"] == expected["raw"]
        assert stamp["status"] == expected["status"]
        assert stamp["page_ids"] == rastered.page_ids(*expected["pages"])
        assert stamp["present_instead"] == expected["present_instead"]


def test_the_flags_are_the_ones_the_table_declares(rastered: Any):
    """Server-derived, from a closed list. `unverified_codes` because one code did not check out."""
    assert ask(rastered, "answer").json()["result"]["flags"] == case("answer")["flags"]


def test_page_provenance_lists_every_requested_page_with_its_trust(rastered: Any):
    """§7.2.6 — the disclosure that makes an `unverifiable` legible rather than mysterious."""
    row = case("answer")
    provenance = ask(rastered, "answer").json()["result"]["page_provenance"]

    assert [page["page_id"] for page in provenance] == rastered.page_ids(*row["pages"])
    assert {page["text_trust"] for page in provenance} == {"ok"}


# ── the two answers a boolean cannot tell apart (§7.2.6) ────────────────────────────────────────

def test_pages_that_do_not_answer_the_question_come_back_insufficient(rastered: Any):
    """*"Wrong pages"*, said out loud. The call is still `ok`: it ran, and the answer is *not here*.

    Without `sufficient` this response and *"the answer is no"* are the same empty extract, and
    §7.2.6 is explicit about the consequence — the agent *"will compose an answer from a page
    that never contained one"*.
    """
    response = ask(rastered, "wrong_pages")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["result"]["sufficient"] is False
    assert payload["result"]["extract"] == ""
    assert payload["result"]["codes"] == []


def test_an_insufficient_read_is_never_an_error_and_never_an_absence(rastered: Any):
    """Family B, and the reason it exists (§7.1). A 4xx here would make our shape the agent's
    conclusion: *"the call failed"* is not *"these pages do not answer it"*."""
    payload = ask(rastered, "wrong_pages").json()

    assert "error" not in payload
    assert payload["result"]["page_provenance"], "the pages that were read are still disclosed"


# ── the scanned page: `unverifiable`, forever (R2, §7.2.6) ──────────────────────────────────────

def test_on_a_page_with_no_text_layer_every_code_is_unverifiable(rastered: Any):
    """§7.2.6, verbatim — *"On a page with no text layer **every** code is `unverifiable`"*.

    Including ``K119``, which is genuinely printed on page 19 of this same document. The check is
    per `(code, page)`: a page nobody can read cannot support a code that lives next door, and
    saying `absent` here would turn our blind spot into the agent's confident denial.
    """
    row = case("scanned")
    payload = ask(rastered, "scanned").json()

    assert [(code["raw"], code["status"]) for code in stamps_of(payload)] == [
        (stamp["raw"], stamp["status"]) for stamp in row["stamps"]]
    assert {code["status"] for code in stamps_of(payload)} == {"unverifiable"}
    assert {code["reason"] for code in stamps_of(payload)} == {"no_text"}


def test_the_scanned_read_says_so_in_its_flags_and_its_provenance(rastered: Any):
    """Two disclosures of the same fact, for two readers: a switch, and a person (F4)."""
    payload = ask(rastered, "scanned").json()

    assert payload["result"]["flags"] == case("scanned")["flags"]
    assert {page["text_trust"] for page in payload["result"]["page_provenance"]} == {"no_text"}


# ── the dpi is the server's, and it is on the audit line and nowhere else (§7.2.6, §7.4) ────────

def test_a_caller_cannot_choose_the_dpi(rastered: Any):
    """Refused by name, not ignored. `dpi` is a ``read_key`` input, so a caller that could set it
    could bill the same question three times (§6.3, F19)."""
    row = case("answer")
    response = rastered.client.post(
        "/tools/read", headers=rastered.header,
        json={"page_ids": rastered.page_ids(*row["pages"]), "question": row["question"],
              "dpi": 400})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_the_render_dpi_is_220_and_is_recorded_on_the_audit_line(rastered: Any, log_stream: Any):
    """§7.4's ten-field line, and the dpi field of it. The **response** carries no dpi at all —
    cost and mechanics go to the audit log, and the caller gets `reads_remaining` (§7.4)."""
    from conftest import log_events

    ask(rastered, "answer")
    audited = [event["audit"] for event in log_events(log_stream)
               if event.get("event") == "audit" and event["audit"]["tool"] == "read"]

    assert audited, "one append-only audit line per `read` (§7.4)"
    assert audited[-1]["dpi"] == READ["dpi"] == 220
    assert audited[-1]["page_ids"] == rastered.page_ids(*case("answer")["pages"])


def test_no_cost_and_no_question_reach_the_response_body(rastered: Any):
    """§7.4 — *"a `usd_estimate` beside the verification stamps is noise next to the fields that
    must not be missed"*. The agent gets one integer, and it is `reads_remaining`."""
    payload = ask(rastered, "answer").json()

    assert set(payload) == {"status", "result", "reads_remaining", "provenance"}
    assert isinstance(payload["reads_remaining"], int)
    assert "usd" not in json.dumps(payload).lower()


# ── replay never invents (D10) ──────────────────────────────────────────────────────────────────

def test_a_question_nobody_froze_is_a_typed_miss_and_never_an_answer(rastered: Any):
    """The refusal the whole replay design exists to make loud.

    A stub that fell back to the model would turn a free suite into a billed one; a stub that
    synthesised a plausible answer would make every green row above a statement about data no
    model ever produced. So an unfrozen key is `fixture_miss`, surfaced as a `502` because the
    backend answered unusably rather than because the pages hold nothing (§11.3).
    """
    row = case("answer")
    response = rastered.read(rastered.page_ids(*row["pages"]),
                            "a question no fixture was ever frozen for")

    assert response.status_code == 502
    assert response.json()["error"] == "fixture_miss"


def test_the_frozen_key_is_the_one_the_tool_computes(rastered: Any, log_stream: Any):
    """The receipt, end to end: the key in `expected.json` is the key the served call looked up.

    This is what makes the acceptance table above meaningful. If the tool computed some other key
    the responses would simply miss, so a green suite already implies it — but the assertion says
    *which* inputs are on the receipt, and it fails loudly if a future change adds one.
    """
    from conftest import log_events

    ask(rastered, "answer")
    keys = {event.get("cache_key") for event in log_events(log_stream)
            if event.get("event") in ("read", "vlm_replay")}

    assert case("answer")["cache_key"] in keys


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_frozen_case_is_reachable_over_http(rastered: Any, name: str):
    """All four, through the route — so a case that stopped being replayable cannot go unnoticed."""
    response = ask(rastered, name)

    assert response.status_code == 200, response.text
    assert response.json()["result"]["sufficient"] is case(name)["sufficient"]
