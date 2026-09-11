"""L2/L3 — `POST /ask`'s triage table: Loop 0's marks, on the wire (§8.2, §13 M7).

The console's triage panel is the one surface that shows a *free* decision. Everything else a
reviewer sees in an answer is downstream of money having been spent: the extract came from a
`read`, the badges came from the gate's `verify` calls. The marks came from nothing but the rows
the skim already returned — and they decided which page the money was spent on.

So the panel has to be a table and not a sentence. Until this unit the only triage information
that left the process was one line of prose inside a trace `Move.detail`, and the `exclude` set's
page ids were nowhere in the body at all; a console built on that would be regexing a sentence
for the counts and guessing at the ids. `Mark`'s own docstring already said why the evidence
travels beside the mark — *"so a triage table can be reviewed rather than trusted"*.

**Nothing here re-implements the marking.** Every assertion compares the table against something
else the same response already said — the trace's own counts, the answer's citations, the pages
the loop excluded — so a table that disagreed with the loop it came from is what fails, and a
change to §8.2's rules moves both halves at once or fails here.
"""
from __future__ import annotations

import re
from typing import Any

from vsir.eval.synthetic_pdf import ASK_ANSWER_QUESTION, ASK_REJECTED_QUESTION
from vsir.runner.triage import IRRELEVANT, MARKS, REASONS, RELEVANT, UNCERTAIN

#: The counts the `triage` move already states in prose. Parsed **only** here, in the test, which
#: is the point: the console never has to, and if this sentence is reworded the table is still the
#: contract and this row is what notices.
COUNTS = re.compile(r"relevant (\d+) · uncertain (\d+) \(the pool, retained\) · irrelevant (\d+)")


def triage_of(payload: dict) -> dict:
    table = payload["triage"]
    assert table is not None, ("the loop triaged at least once on this question, so the table is "
                               "the table and not `null`")
    return table


def test_the_table_is_the_marks_the_loop_really_made(asking: Any):
    """The rows agree with the counts the trace's own `triage` move printed for a person."""
    payload = asking.ask(ASK_ANSWER_QUESTION).json()

    moves = [move for move in payload["trace"] if move["action"] == "triage"]
    assert moves, payload["trace"]
    stated = COUNTS.search(moves[-1]["detail"])
    assert stated, moves[-1]["detail"]

    rows = triage_of(payload)["rows"]
    counted = {mark: len([row for row in rows if row["mark"] == mark]) for mark in MARKS}
    assert (counted[RELEVANT], counted[UNCERTAIN], counted[IRRELEVANT]) == (
        int(stated.group(1)), int(stated.group(2)), int(stated.group(3)))


def test_every_row_carries_the_rule_that_marked_it_and_the_evidence_it_was_marked_on(asking: Any):
    """§8.2's reason is a closed list, and `matched` is what makes the mark reviewable.

    A row whose `reason` were free text would be a label to be trusted; a row with a reason from
    :data:`REASONS` and the question's own terms beside it is one a reviewer can disagree with.
    """
    rows = triage_of(asking.ask(ASK_ANSWER_QUESTION).json())["rows"]

    assert rows
    for row in rows:
        assert row["mark"] in MARKS, row
        assert row["reason"] in REASONS, row
        assert row["rank"] >= 1, "an ordinal from the fused list, never a score (§7.6)"
        assert isinstance(row["why"], list) and isinstance(row["matched"], list), row
        assert "score" not in row and "fused" not in row, row


def test_the_exclude_set_is_the_irrelevant_pages_and_never_the_uncertain_pool(asking: Any):
    """§8.2: the pool is *retained*. Excluding it would delete the fallback it exists to be.

    The tri-state's whole argument is that `uncertain` is not a rejection, and this is where a
    reviewer can see that: the ids the next rung was told to skip are the `irrelevant` ones.
    """
    table = triage_of(asking.ask(ASK_ANSWER_QUESTION).json())

    irrelevant = {row["page_id"] for row in table["rows"] if row["mark"] == IRRELEVANT}
    pool = {row["page_id"] for row in table["rows"] if row["mark"] == UNCERTAIN}
    assert irrelevant <= set(table["exclude"]), (
        "every page the pass marked `irrelevant` goes into the next rung's `exclude`")
    assert not (pool & set(table["exclude"])), (
        "and the pool never does — draining it is safeguard 1's move (§8.2)")


def test_the_page_the_read_was_spent_on_is_a_relevant_row_of_the_table(asking: Any):
    """The table is *why* the money went where it went — the free decision behind the paid one."""
    payload = asking.ask(ASK_ANSWER_QUESTION).json()

    relevant = {row["page_id"] for row in triage_of(payload)["rows"]
                if row["mark"] == RELEVANT}
    assert payload["answer"]["citations"], payload
    for page_id in payload["answer"]["citations"]:
        assert page_id in relevant, (
            "a citation from a page triage did not mark `relevant` would mean the loop drafted "
            "from a page it had already decided against")


def test_a_submitted_draft_has_no_table_because_nothing_was_triaged(asking: Any):
    """`null`, not an empty table: *"nothing was offered"* and *"nothing survived"* differ.

    §8.1a's `fetch` route searches nothing — the caller already looked — so there is no pass to
    show, and an empty table here would read as a triage that rejected everything.
    """
    page_id = asking.page_id(19)
    payload = asking.gate(ASK_REJECTED_QUESTION, draft={
        "text": "The sheet names K152.",
        "claims": [{"code": "K152", "page_ids": [page_id]}],
        "pages": [page_id],
    }).json()

    assert payload["status"] == "abstained"
    assert payload["triage"] is None, payload["triage"]


def test_the_table_carries_no_page_text_and_no_image_bytes(asking: Any):
    """P2 and I2 at this surface too: a mark is a verdict about a row, not a copy of the page."""
    table = triage_of(asking.ask(ASK_ANSWER_QUESTION).json())

    body = repr(table)
    assert "bytes_b64" not in body and "thumb_url" not in body
    assert "Category 3 PL=D Reached" not in body, "page 19's own text belongs to no triage row"
