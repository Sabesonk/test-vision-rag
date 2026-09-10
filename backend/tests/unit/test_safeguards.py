"""L0 — the five safeguards of Spec §8.2, in the state machine **and** in the system prompt.

§8.2 lists five rules and says they are *"binding on the system prompt"*; the unit that builds the
runner makes them binding on the machine as well, because R6 is exactly the case where the prompt
is not enough: a client driving the raw MCP surface never reads it. So every safeguard here is
asserted twice — once as behaviour, once as text — and one test asserts that the two statements
come from the same definition, since two copies of a rule are one rule and one stale copy.

The order below is §8.2's table, top to bottom.
"""
from __future__ import annotations

from vsir.runner import prompt as prompt_module
from vsir.runner import triage as triage_module
from vsir.runner.prompt import PromptInputs, build, digest, safeguards
from vsir.runner.triage import (
    DRAIN_UNCERTAIN,
    INSUFFICIENT,
    IRRELEVANT,
    LEXICAL,
    LOOK,
    MARKS,
    RELEVANT,
    SAFEGUARDS,
    SMALL_SET_MAX,
    TRANSITIONS,
    UNCERTAIN,
    WIDEN,
    mark,
    next_state,
    order,
    terms_of,
    triage,
)
from vsir.serve.envelope import PageHit

PROSE = "the carton discharge will not restart after an emergency stop reset"
WITH_CODE = "where is K158 wired"


def hit(page_id: str = "d@1.0#p001", *, summary: str = "hydraulic tank capacity",
        why: tuple[str, ...] = ("dense",), rank: int = 1, grounded: float | None = 1.0,
        trust: str = "ok") -> PageHit:
    return PageHit(page_id=page_id, summary=summary, why=list(why), rank=rank,
                   grounded_rate=grounded, text_trust=trust)


def rows(count: int) -> list[PageHit]:
    """``count`` candidates that every rule would otherwise mark `irrelevant`."""
    return [hit(f"d@1.0#p{n:03d}", summary="hydraulic tank capacity", rank=n)
            for n in range(1, count + 1)]


# ── 1 · rejections stay soft ────────────────────────────────────────────────────────────────────

def test_sufficient_false_drains_the_uncertain_pool_before_widening_the_scope():
    """The safeguard, as the one row of the transition table it has to be (§8.2, §8.3 Loop 3).

    In a hand-written loop this is an ordering between two branches, and an ordering is what a
    later edit reverses without any test noticing. Here it is data: `look` on `insufficient` goes
    to the pool, and there is no edge from `look` to `widen` to add by accident.
    """
    assert next_state(LOOK, INSUFFICIENT) == DRAIN_UNCERTAIN
    assert (LOOK, INSUFFICIENT) in TRANSITIONS
    assert WIDEN not in {TRANSITIONS[pair] for pair in TRANSITIONS if pair[0] == LOOK}


def test_widening_is_reachable_only_after_the_pool_is_empty():
    into_widen = {pair[0] for pair, target in TRANSITIONS.items() if target == WIDEN}
    assert into_widen == {DRAIN_UNCERTAIN}
    assert next_state(DRAIN_UNCERTAIN, triage_module.POOL_EMPTY) == WIDEN


# ── 2 · do not filter a small set ───────────────────────────────────────────────────────────────

def test_a_set_of_three_or_fewer_is_never_filtered():
    """*"With ≤3 candidates, read them all"* — so none is `irrelevant` and all are looked at."""
    for count in (1, 2, SMALL_SET_MAX):
        result = triage(rows(count), query=PROSE)
        assert result.irrelevant == (), f"{count} candidate(s) were filtered"
        assert len(result.look_set) == count
        assert result.small_set
        assert {one.reason for one in result.marks} == {"small_set"}


def test_the_safeguard_stops_at_the_boundary():
    """Four candidates is a set worth triaging, and the same rows are marked `irrelevant`."""
    result = triage(rows(SMALL_SET_MAX + 1), query=PROSE)
    assert not result.small_set
    assert len(result.irrelevant) == SMALL_SET_MAX + 1
    assert result.exclude == tuple(f"d@1.0#p{n:03d}" for n in range(1, SMALL_SET_MAX + 2))


def test_a_small_set_still_keeps_the_reason_a_promoted_row_earned():
    """Safeguard 2 lifts the rows that need lifting and rewrites nothing else."""
    result = triage([hit("d@1.0#p001", why=("dense", LEXICAL)), hit("d@1.0#p002", rank=2)],
                    query=WITH_CODE)
    reasons = {one.page_id: one.reason for one in result.marks}
    assert reasons["d@1.0#p001"] == "exact_hit"
    assert reasons["d@1.0#p002"] == "small_set"


# ── 3 · use `why` as a signal ───────────────────────────────────────────────────────────────────

def test_at_equal_rank_a_lexical_hit_is_ordered_above_a_dense_only_one():
    """§8.2 — *"a `lexical` hit on an exact code outranks a dense-only hit"*, as a sort key."""
    dense = mark(hit("d@1.0#p001", summary="carton discharge", why=("dense",), rank=7),
                 terms=terms_of(PROSE))
    lexical = mark(hit("d@1.0#p002", summary="carton discharge", why=("dense", LEXICAL), rank=7),
                   terms=terms_of(PROSE))
    assert dense.mark == lexical.mark == RELEVANT
    assert [one.page_id for one in order([dense, lexical])] == ["d@1.0#p002", "d@1.0#p001"]
    assert [one.page_id for one in order([lexical, dense])] == ["d@1.0#p002", "d@1.0#p001"]


def test_a_lexical_hit_is_never_marked_irrelevant_even_when_its_summary_shows_nothing():
    """The signal as a floor: the page's own text matched, so the summary is not the whole page."""
    one = mark(hit(why=("dense", LEXICAL)), terms=terms_of(PROSE))
    assert (one.mark, one.reason) == (UNCERTAIN, "lexical_unshown")


# ── 4 · auto-promote exact hits ─────────────────────────────────────────────────────────────────

def test_an_exact_identifier_found_lexically_bypasses_triage():
    """§8.2 — the query names a code and the page's text prints it. There is nothing to judge."""
    one = mark(hit(why=[LEXICAL]), terms=terms_of(WITH_CODE))
    assert (one.mark, one.reason, one.promoted) == (RELEVANT, "exact_hit", True)
    assert one.matched == ("k158",)


def test_the_promotion_ignores_the_summary_entirely():
    """A promoted row is not evaluated, so the worst possible summary cannot demote it."""
    one = mark(hit(summary="", why=[LEXICAL], trust="no_text", grounded=None),
               terms=terms_of(WITH_CODE))
    assert (one.mark, one.promoted) == (RELEVANT, True)


def test_both_halves_of_the_condition_are_required():
    """A code with no lexical hit, and a lexical hit with no code in the query: neither promotes."""
    dense_only = mark(hit(why=("dense",)), terms=terms_of(WITH_CODE))
    no_identifier = mark(hit(why=[LEXICAL]), terms=terms_of(PROSE))
    assert not dense_only.promoted and dense_only.mark != RELEVANT
    assert not no_identifier.promoted


# ── 5 · tri-state is mandatory ──────────────────────────────────────────────────────────────────

def test_the_vocabulary_is_three_states_and_a_pass_can_produce_all_three():
    """Not keep/drop: a run over ordinary rows lands in each state, and in no fourth one."""
    result = triage([hit("d@1.0#p001", summary="carton discharge restart"),
                     hit("d@1.0#p002", summary="hydraulic tank", rank=2, why=("dense", LEXICAL)),
                     hit("d@1.0#p003", summary="hydraulic tank", rank=3),
                     hit("d@1.0#p004", summary="filter part numbers", rank=4)],
                    query=PROSE)
    assert MARKS == (RELEVANT, UNCERTAIN, IRRELEVANT)
    assert {one.mark for one in result.marks} == set(MARKS)
    assert len(result.relevant) + len(result.uncertain) + len(result.irrelevant) == 4


# ── the same five rules, in the prompt (§8.2: binding on both) ──────────────────────────────────

def test_the_prompt_carries_all_five_safeguards():
    text = build(PromptInputs(tools=("lookup", "read"), reads_per_question=3))
    for name, rule in SAFEGUARDS:
        assert name in text, f"the prompt does not state the safeguard {name!r}"
        assert rule in text, f"the prompt states {name!r} in different words than the machine"
    assert len(SAFEGUARDS) == 5


def test_the_prompt_and_the_machine_read_the_same_definition():
    """One statement, two consumers. A safeguard edited once is edited in both places."""
    assert safeguards().count("**") == 2 * len(SAFEGUARDS)
    assert safeguards() in build(PromptInputs())


def test_the_prompt_states_the_tri_state_rule_and_the_two_routes():
    text = build(PromptInputs(tools=("fetch", "read"), reads_per_question=2))
    for word in ("`relevant`", "`uncertain`", "`irrelevant`"):
        assert word in text
    assert "**Default: `fetch`.**" in text
    assert "2 `read` call(s)" in text
    assert "429 budget_exhausted" in text
    assert 'not in these documents' in text.lower()


def test_a_caller_that_cannot_see_is_told_the_look_step_is_read():
    blind = build(PromptInputs(vision_capable=False))
    assert "You cannot see a raster" in blind
    assert "**Default: `fetch`.**" not in blind


def test_the_prompt_is_byte_identical_for_identical_inputs():
    """A prompt is a cache-key input wherever one reaches a paid call (§6.3, F11)."""
    inputs = PromptInputs(tools=("fetch", "lookup", "read"), reads_per_question=3,
                          vision_capable=True, scope=("TC1E-SF",))
    first, second = build(inputs), build(PromptInputs(
        tools=("fetch", "lookup", "read"), reads_per_question=3, vision_capable=True,
        scope=("TC1E-SF",)))
    assert first == second
    assert digest(first) == digest(second)
    assert digest(first) != digest(build(PromptInputs(tools=("fetch", "lookup", "read"),
                                                      reads_per_question=2, scope=("TC1E-SF",))))


def test_the_prompt_version_is_its_own_and_is_not_the_extraction_prompt_version():
    """§6.3 — bumping this must not re-key a single frozen S2 response."""
    from vsir.vlm.client import PROMPT_DIGESTS

    assert prompt_module.RUNNER_PROMPT_VERSION not in PROMPT_DIGESTS
