"""L0 — Loop 0: the tri-state mark, the fallback pool, and the state machine (Spec §8.2, §8.1).

Triage is the cheapest correction in the system and the only one that runs before money moves, so
almost everything about it is provable here: the four inputs a mark is made from, the three states
it can be in, the pool it must not throw away, and the transition table the loop walks. Nothing in
this file touches a store, a raster, a model or a network — the rows are `PageHit`s built in
memory, which is the shape a skim hands the runner (§7.1).

The safeguards have their own suite (`test_safeguards.py`) because they are the rules a
well-meaning change breaks quietly; this one is about the machinery they bind.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vsir.core.health import TRUST_OK_MIN
from vsir.runner import triage as triage_module
from vsir.runner.triage import (
    IRRELEVANT,
    LEXICAL,
    MARKS,
    REASONS,
    RELEVANT,
    STATES,
    TERMINAL,
    TRANSITIONS,
    UNCERTAIN,
    UnknownTransition,
    empty_signal,
    mark,
    next_state,
    order,
    record,
    terms_of,
    triage,
)
from vsir.serve.envelope import PageHit

SOURCE = Path(triage_module.__file__)

#: A question with prose and no identifier, and one with both. `terms_of` splits them the way the
#: skim did (§7.2.1 ordering rule 1), so the two spellings of *"the query names a code"* agree.
PROSE = "the carton discharge will not restart after an emergency stop reset"
WITH_CODE = "why does K158 not reset"


def hit(page_id: str = "AGG-TEXT@1.0#p001", *, summary: str = "carton discharge interlock",
        why: tuple[str, ...] = ("dense",), rank: int = 1, grounded: float | None = 1.0,
        trust: str = "ok") -> PageHit:
    """One triage row, as `skim_pages` builds it — a summary and four signals, and no page text."""
    return PageHit(page_id=page_id, summary=summary, why=list(why), rank=rank,
                   grounded_rate=grounded, text_trust=trust)


# ── the mark ────────────────────────────────────────────────────────────────────────────────────

def test_every_candidate_gets_exactly_one_of_the_three_marks():
    """§8.2 — tri-state, for every row. Not a filter, not a score, not a boolean."""
    rows = [hit("d@1.0#p001", summary="carton discharge conveyor"),
            hit("d@1.0#p002", summary="hydraulic tank capacity", rank=2),
            hit("d@1.0#p003", summary="", rank=3, trust="no_text", grounded=None),
            hit("d@1.0#p004", summary="lubrication schedule", rank=4, why=("dense", LEXICAL))]
    result = triage(rows, query=PROSE)
    assert len(result.marks) == len(rows)
    assert {one.page_id for one in result.marks} == {row.page_id for row in rows}
    assert all(one.mark in MARKS for one in result.marks)
    assert all(one.reason in REASONS for one in result.marks)


def test_a_summary_that_carries_a_term_of_the_question_is_relevant():
    one = mark(hit(summary="Carton discharge restart interlock"), terms=terms_of(PROSE))
    assert (one.mark, one.reason) == (RELEVANT, "summary_match")
    assert "carton" in one.matched and "discharge" in one.matched


def test_a_trusted_grounded_summary_with_nothing_of_the_question_is_irrelevant():
    """The only route to `irrelevant`: the row can be judged, and it does not answer."""
    one = mark(hit(summary="Hydraulic tank capacity and filter part numbers"),
               terms=terms_of(PROSE))
    assert (one.mark, one.reason) == (IRRELEVANT, "no_overlap")
    assert one.matched == ()


@pytest.mark.parametrize("row, reason", [
    (hit(summary="hydraulic tank", why=("dense", LEXICAL)), "lexical_unshown"),
    (hit(summary="hydraulic tank", trust="untrusted", grounded=0.1), "untrusted_text"),
    (hit(summary="", trust="no_text", grounded=None), "untrusted_text"),
    (hit(summary="hydraulic tank", grounded=TRUST_OK_MIN - 0.01), "weak_grounding"),
    (hit(summary="   ", grounded=1.0), "no_summary"),
])
def test_a_row_that_cannot_be_judged_from_its_summary_is_uncertain_never_irrelevant(row, reason):
    """R1's mitigation, one row at a time: four ways a summary stops being evidence of absence.

    Each of these is a page whose silence proves nothing — the text matched but the summary does
    not show it, the text layer cannot be believed (§5.7), the summary is only partly grounded in
    the page, or there is no summary at all. Dropping any of them is how the answering page is
    excluded and the run abstains on a corpus that contained the answer.
    """
    one = mark(row, terms=terms_of(PROSE))
    assert (one.mark, one.reason) == (UNCERTAIN, reason)


def test_the_mark_is_made_from_the_row_and_never_from_page_text():
    """A triage row has no page text to read, and this module must not acquire another source.

    Two assertions, because they fail differently: the contract has no such field (P2, §7.1), and
    the module imports nothing that could fetch, render or bill one.
    """
    assert "text" not in PageHit.model_fields
    imported = {node.module for node in ast.walk(ast.parse(SOURCE.read_text()))
                if isinstance(node, ast.ImportFrom) and node.module}
    forbidden = [name for name in imported
                 if any(part in name for part in ("vlm", "raster", "tools.read", "tools.fetch"))]
    assert not forbidden, f"triage reached for {forbidden}; a mark costs nothing (§8.2)"


def test_rank_is_carried_but_is_not_a_reason():
    """A fused position is a place in a list. Marking on it would be a threshold nobody chose."""
    close = mark(hit(summary="carton discharge", rank=1), terms=terms_of(PROSE))
    far = mark(hit(summary="carton discharge", rank=99), terms=terms_of(PROSE))
    assert close.mark == far.mark == RELEVANT
    assert (close.rank, far.rank) == (1, 99)


# ── the set ─────────────────────────────────────────────────────────────────────────────────────

def test_the_uncertain_pool_is_retained_and_stays_out_of_exclude():
    """§8.2 — the pool is the whole difference from a binary. It is kept, and it is not excluded."""
    rows = [hit("d@1.0#p001", summary="carton discharge"),
            hit("d@1.0#p002", summary="hydraulic tank", rank=2, trust="no_text", grounded=None),
            hit("d@1.0#p003", summary="hydraulic tank", rank=3),
            hit("d@1.0#p004", summary="filter part numbers", rank=4)]
    result = triage(rows, query=PROSE)
    assert [one.page_id for one in result.uncertain] == ["d@1.0#p002"]
    assert result.exclude == ("d@1.0#p003", "d@1.0#p004")
    assert "d@1.0#p002" not in result.exclude
    assert result.look_set == ("d@1.0#p001",)


def test_the_order_is_total_and_independent_of_the_order_the_rows_arrived_in():
    """§16 — two calls with the same rows produce the same list, whatever order they came in."""
    rows = [hit(f"d@1.0#p{n:03d}", summary="carton discharge" if n % 2 else "hydraulic tank",
                rank=n) for n in range(1, 9)]
    forwards = triage(rows, query=PROSE)
    backwards = triage(list(reversed(rows)), query=PROSE)
    assert [m.page_id for m in forwards.marks] == [m.page_id for m in backwards.marks]
    assert [m.mark for m in forwards.marks] == sorted((m.mark for m in forwards.marks),
                                                      key=MARKS.index)


def test_order_puts_the_three_states_in_the_order_they_are_acted_on():
    marks = [mark(hit("d@1.0#p001", summary="hydraulic tank"), terms=terms_of(PROSE)),
             mark(hit("d@1.0#p002", summary="carton discharge", rank=2), terms=terms_of(PROSE)),
             mark(hit("d@1.0#p003", summary="", rank=3, trust="no_text", grounded=None),
                  terms=terms_of(PROSE))]
    assert [one.mark for one in order(marks)] == [RELEVANT, UNCERTAIN, IRRELEVANT]


def test_an_empty_candidate_list_marks_nothing_and_asks_for_the_empty_branch():
    result = triage([], query=PROSE)
    assert result.marks == () and result.look_set == () and result.exclude == ()
    assert result.signal == triage_module.EMPTY_LOOK_SET
    assert not result.small_set


# ── the terms ───────────────────────────────────────────────────────────────────────────────────

def test_terms_split_identifiers_the_way_the_skim_split_them():
    """`decompose`'s identifiers, imported rather than re-derived (§7.2.1, §5.6)."""
    terms = terms_of(WITH_CODE)
    assert terms.exact and terms.identifiers == ("k158",)
    assert "reset" in terms.prose


def test_short_prose_tokens_are_not_terms():
    """A length floor, not a stopword list: the corpus is multilingual (§5.2, D5)."""
    terms = terms_of("why does the arm not go up")
    assert terms.prose == ("does",)
    assert not terms.exact


# ── the state machine (§8.1) ────────────────────────────────────────────────────────────────────

def test_every_transition_names_states_the_machine_declares():
    for (state, signal), target in TRANSITIONS.items():
        assert state in STATES, f"{state} is not a declared state"
        assert target in STATES, f"{state} --{signal}--> {target} leaves the machine"


def test_a_terminal_state_has_no_way_out():
    """`answer` and `abstain` end the question. An edge out of one is a loop that never stops."""
    assert not [pair for pair in TRANSITIONS if pair[0] in TERMINAL]


def test_every_non_terminal_state_is_reachable_from_the_first_one():
    reached, frontier = {triage_module.DESCEND}, [triage_module.DESCEND]
    while frontier:
        state = frontier.pop()
        for (origin, _signal), target in TRANSITIONS.items():
            if origin == state and target not in reached:
                reached.add(target)
                frontier.append(target)
    assert reached == set(STATES), f"unreachable: {sorted(set(STATES) - reached)}"


def test_an_unknown_signal_is_refused_and_names_what_the_state_does_accept():
    """No default edge. A machine that fell through would draft from wherever it happened to be."""
    with pytest.raises(UnknownTransition) as refusal:
        next_state(triage_module.LOOK, "vibes")
    assert "insufficient" in str(refusal.value)


def test_the_empty_branch_is_chosen_by_coverage_not_by_guess():
    """§8.1's two empty rows, and §8.5's reason for the second one."""
    assert empty_signal(0) == triage_module.EMPTY_SEARCHABLE
    assert next_state(triage_module.DESCEND, empty_signal(0)) == triage_module.ABSTAIN
    assert empty_signal(14) == triage_module.EMPTY_NO_TEXT
    assert next_state(triage_module.DESCEND, empty_signal(14)) == triage_module.VISION_FIRST


# ── telemetry (§8.2, §11.4) ─────────────────────────────────────────────────────────────────────

def test_marks_reach_telemetry_as_one_event_per_page():
    """Evaluation data is `query → page → relevant?`; an aggregate cannot be joined back."""
    written: list[dict] = []
    result = triage([hit("d@1.0#p001", summary="carton discharge"),
                     hit("d@1.0#p002", summary="hydraulic tank", rank=2)], query=PROSE)
    assert record(result, sink=written.append, session_id="s-1") == 2
    assert [event["page_id"] for event in written] == ["d@1.0#p001", "d@1.0#p002"]
    assert {event["query"] for event in written} == {PROSE}
    assert all(event["session_id"] == "s-1" for event in written)
    assert all(event["mark"] in MARKS for event in written)


def test_the_loop_proceeds_with_telemetry_disabled():
    """§8.2 — *"never as a mandatory tool call"*. With no sink there is nothing to fail.

    The marks are in the value the caller already holds, so recording them is an observation and
    never a step: the look set, the pool and the machine's next state are identical either way.
    """
    rows = [hit("d@1.0#p001", summary="carton discharge"),
            hit("d@1.0#p002", summary="hydraulic tank", rank=2),
            hit("d@1.0#p003", summary="filter part numbers", rank=3),
            hit("d@1.0#p004", summary="filter part numbers", rank=4)]
    result = triage(rows, query=PROSE)
    assert record(result, sink=None) == 0
    assert result.look_set == ("d@1.0#p001",)
    assert next_state(triage_module.TRIAGE, result.signal) == triage_module.LOOK
