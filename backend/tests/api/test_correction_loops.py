"""L2/L3 — all six correction loops of Spec §8.3, each fired by a crafted scenario.

Six loops, six independently named tests, and none of them asserts that a loop *exists*: each one
puts the corpus in the state that triggers it and then reads what the loop did off the trace.

| # | Trigger | Correction | Scenario here |
|---|---|---|---|
| 0 | a candidate looks wrong in triage | mark `irrelevant`, `exclude` it | a question about hydraulics, in a safety manual |
| 1 | a code was misread | stamped `absent` **inside `read`** | the frozen response that names `K152` |
| 2 | about to assert a claim | `verify(claims, page_ids)` | every answered question |
| 3 | `sufficient: false` | try `uncertain`, **then** widen | `SI4`'s ten pages, the first three of which do not answer |
| 4 | `verify` contradicts the draft | try a different page | the same `K152` |
| 5 | nothing found **and** `searchable_ratio < 1` | look at the image-only pages | a question naming a code the corpus does not print |

The loop is driven **in process** through the release's own dispatcher rather than over HTTP, for
one reason: a scenario that ends in a typed refusal — a fixture the corpus was never given, a
budget that is spent — returns a refusal body, and the trace is what these tests are about. The
dispatcher, the collection, the document store and the frozen responses are the same ones
`test_ask_replay.py` reaches over the route, so nothing here is a second implementation of
anything; it is the same call with the transport taken off.
"""
from __future__ import annotations

from typing import Any

from vsir.eval.synthetic_pdf import (
    ASK_ANSWER_QUESTION,
    ASK_LADDER_QUESTION,
    ASK_REJECTED_QUESTION,
    ASK_WIDENED_QUESTION,
)
from vsir.runner import loop as loop_module
from vsir.runner.loop import (
    LOOP_0_EXCLUDE,
    LOOP_1_READ_STAMP,
    LOOP_2_VERIFY,
    LOOP_3_SOFT_REJECTION,
    LOOP_4_DIFFERENT_PAGE,
    LOOP_5_VISION_ESCALATION,
    LOOPS,
    MAX_MOVES,
)
from vsir.serve import app as app_module
from vsir.serve import auth as auth_module

#: A code of a shape this corpus uses and prints nowhere: every `K` is `K1xx`, so `K999` cannot
#: be on a page. It is the near-miss shape of §12.4, used here to force §8.1's empty branch.
UNPRINTED_CODE = "K999"


def run(asking: Any, question: str, **arguments: Any) -> Any:
    """One question through §8.1's machine, over the really ingested corpus."""
    runtime = asking.runtime

    def call(tool: str, payload: Any) -> Any:
        return app_module.dispatch(runtime, tool, dict(payload),
                                   identity=auth_module.local_identity("cli"), correlation={})

    return loop_module.run(question, call=call,
                           reads_per_question=runtime.config.reads_per_question,
                           sink=None, **arguments)


def moves(outcome: Any, action: str) -> list[Any]:
    return [move for move in outcome.trace if move.action == action]


def bounded(outcome: Any) -> None:
    """Every scenario terminates, and well inside the machine's own bound (:data:`MAX_MOVES`)."""
    assert len(outcome.trace) <= MAX_MOVES, [move.state for move in outcome.trace]
    assert outcome.state in {"answer", "abstain"} or outcome.refusal is not None


# ── Loop 0 · the cheapest correction: before any spend (§8.2) ───────────────────────────────────

def test_loop_0_marks_a_wrong_candidate_irrelevant_and_excludes_it_from_the_next_skim(
        asking: Any):
    """A safety manual holds nothing about hydraulic accumulators, and triage says so for free.

    Every candidate the chosen chapter offered is marked `irrelevant`, and the *next* skim carries
    them in `exclude` — so the same rows are not re-offered and re-rejected. The whole correction
    happens before a cent is committed, which is §8.2's first sentence.
    """
    outcome = run(asking, ASK_WIDENED_QUESTION)

    assert LOOP_0_EXCLUDE in outcome.loops
    triaged = moves(outcome, "triage")
    assert triaged and triaged[0].signal == "empty_look_set"
    assert "irrelevant 5" in triaged[0].detail, triaged[0].detail
    # The exclusion is visible in the re-skim: 5 rejected rows, then 15 by the third descent.
    widened = moves(outcome, "widen")
    assert "re-skimming with 5 exclusion(s)" in widened[0].detail, widened[0].detail
    assert [move.action for move in outcome.trace[:5]].count("read") == 0, (
        "the whole correction happened before any spend: five moves of narrowing and triage, "
        "and not one of them billed anything (§8.2)")
    bounded(outcome)


# ── Loop 1 · the automatic stamp, inside `read` (§7.2.6) ────────────────────────────────────────

def test_loop_1_stamps_a_misread_code_absent_inside_read_without_being_asked(asking: Any):
    """The correction the loop does not perform: it happens one layer down, automatically.

    The frozen response for page 20 names `K152` — a plausible misread of `K120`, which is what a
    vision model does when a character on a schematic is ambiguous. `read` stamps it `absent`
    against the page's own text before the loop ever sees it (§7.2.6 Loop 1), and the loop records
    that the stamp fired.
    """
    outcome = run(asking, ASK_REJECTED_QUESTION)

    assert LOOP_1_READ_STAMP in outcome.loops
    read = moves(outcome, "read")[0]
    assert "unverified_codes" in read.detail, read.detail
    assert read.spends, "this is the one move in the whole loop that bills a model call"
    bounded(outcome)


# ── Loop 2 · the deliberate check, after the draft (§8.4) ───────────────────────────────────────

def test_loop_2_verifies_every_claim_after_the_draft_and_never_before_it(asking: Any):
    """Verification happens **after** drafting — §8.1's third structural property.

    Before it, there is nothing to verify but the model's word; after it, every code in the
    sentence is checked against the page it is cited on. The order is visible in the trace, and
    the calls are visible in the gate's own log.
    """
    outcome = run(asking, ASK_ANSWER_QUESTION)

    assert LOOP_2_VERIFY in outcome.loops
    states = [move.state for move in outcome.trace]
    assert states.index("draft") < states.index("verify")
    assert len(outcome.checks) == 3, outcome.checks
    assert {row.status for row in outcome.checks} == {"present"}
    assert outcome.answered
    bounded(outcome)


# ── Loop 3 · a rejection stays soft (§8.2 safeguard 1) ──────────────────────────────────────────

def test_loop_3_drains_the_uncertain_pool_before_it_widens_the_scope(asking: Any):
    """Safeguard 1, asserted on the **call order**: the pool, then — only then — a wider scope.

    `SI4` is printed on ten pages of this document and the read cap takes three. Those three say
    `sufficient: false`, so the loop looks again at what it already had in hand rather than
    searching afresh: the three candidates the cap deferred. That second look answers, so no
    widening happens at all — which is the point of trying the pool first.
    """
    outcome = run(asking, ASK_LADDER_QUESTION)

    assert LOOP_3_SOFT_REJECTION in outcome.loops
    actions = [move.action for move in outcome.trace]
    assert actions.count("read") == 2 and outcome.reads == 2
    assert "drain" in actions and "widen" not in actions, (
        "the pool answered, so the scope was never widened — safeguard 1 in one line")
    assert actions.index("drain") < actions.index("read", actions.index("drain")), (
        "the drain is what produced the second look")
    assert outcome.answered
    bounded(outcome)


def test_loop_3_widens_only_after_the_pool_is_empty_and_zooms_out_one_rung_at_a_time(
        asking: Any):
    """The second half of Loop 3, and the reason widening is a *zoom level* rather than a key.

    Dropping a key out of a scope the descent then re-derives is not widening: the next descent
    asks the same section rung for the same best row and puts it straight back. So the loop gives
    up one **rung** — both aggregates, then the binder alone, then the caller's scope searched
    flat — and there is nothing wider than the last of those.
    """
    outcome = run(asking, ASK_WIDENED_QUESTION)

    assert LOOP_3_SOFT_REJECTION in outcome.loops
    widened = moves(outcome, "widen")
    assert [move.signal for move in widened] == [
        "widened", "widened", "empty_no_text", "exhausted"], [move.detail for move in widened]
    assert "1 aggregate rung(s)" in widened[0].detail
    assert "0 aggregate rung(s)" in widened[1].detail
    assert "have still not been looked at" in widened[2].detail, (
        "the ladder is spent, and §8.1's second empty branch fires from its **end** as well: a "
        "page nobody can read is looked at before anything is concluded (§8.5)")
    assert "nothing wider to search" in widened[3].detail, (
        "and only then — with every image-only page examined — does it give up")
    drained = moves(outcome, "drain")
    assert drained[0].signal == "pool_empty", "there was nothing in hand, so it had to widen"
    assert outcome.trace.index(widened[0]) > outcome.trace.index(drained[0])
    bounded(outcome)


# ── Loop 4 · the gate contradicts the draft (§8.4) ──────────────────────────────────────────────

def test_loop_4_tries_a_different_page_when_the_gate_contradicts_the_draft(asking: Any):
    """*"`verify` contradicts the draft → try a different page"*, and the page that carried it is
    excluded so the re-triage cannot offer it again.

    The draft dies whole: not one code of it renders, including the two the gate had cleared. What
    follows is the loop looking elsewhere — and finding nothing, which is why this question ends
    in an abstention that names its rejection rather than in an answer.
    """
    outcome = run(asking, ASK_REJECTED_QUESTION)

    assert LOOP_4_DIFFERENT_PAGE in outcome.loops
    contradicted = [move for move in outcome.trace if move.signal == "contradicted"]
    assert len(contradicted) == 1, [move.signal for move in outcome.trace]
    assert outcome.state == "abstain" and not outcome.answered
    assert outcome.abstention.reason == "rejected"
    assert outcome.rejections and outcome.rejections[0].present_instead == ["k120"], (
        "what page 20 really prints, disclosed as a prefix lookup and never as a match (F16)")
    # The page the rejected claim was cited on is out of play for the rest of the question.
    after = [move for move in outcome.trace if move.state == "triage"][-1]
    assert "0 candidate(s)" in after.detail, after.detail
    bounded(outcome)


# ── Loop 5 · nothing found, and the scope is not fully searchable (§8.3, §8.5) ──────────────────

def test_loop_5_escalates_to_vision_and_asks_the_unverified_surface_when_nothing_is_searchable(
        asking: Any):
    """Both moves §8.3 asks for, on a question the text surface cannot answer at all.

    `K999` is printed on no page, so every branch of every rung is filtered to nothing — and two
    pages of this document have no text layer, which is the difference between *"the corpus does
    not contain it"* and *"the corpus was not searched"*. So the loop asks the opt-in `vlm_codes`
    surface for a pointer into the blind spot and then **looks at the pages themselves**.
    """
    outcome = run(asking, f"where is {UNPRINTED_CODE} wired")

    assert LOOP_5_VISION_ESCALATION in outcome.loops
    vision = [move for move in outcome.trace if move.state == "vision_first"]
    unverified = [move for move in vision if move.action == "lookup"]
    assert unverified and "include_unverified=True" in unverified[0].detail
    escalated = [move for move in vision if move.action == "vision"]
    assert escalated and "escalating to vision" in escalated[0].detail, escalated
    assert any("image-only" in move.detail for move in vision)
    bounded(outcome)


def test_loop_5_does_not_fire_when_the_scope_was_fully_searched(asking: Any):
    """*"nothing found **and** `searchable_ratio < 1`"* — the conjunction, not either half.

    Scoped to a chapter that is entirely text, an empty result means the searchable text really
    does not carry it, and there is nothing to escalate to. Firing here would spend a paid read on
    pages the caller has been told are readable.
    """
    outcome = run(asking, f"where is {UNPRINTED_CODE} wired",
                  scope={"section_id": [f"vsir-raster@1.0#s005"]})

    assert LOOP_5_VISION_ESCALATION not in outcome.loops
    assert outcome.reads == 0, "nothing was looked at, so nothing was billed"
    assert outcome.state == "abstain"
    bounded(outcome)


# ── the set, and the bound ──────────────────────────────────────────────────────────────────────

def test_every_loop_of_8_3_fires_somewhere_in_this_suite(asking: Any):
    """The six are a set, and a seventh would be a correction nothing declared.

    Two scenarios cover five of them between them; Loop 0 needs a question the corpus has nothing
    to say about. Run together here so a loop that stopped firing cannot hide behind another
    test's pass.
    """
    fired: set[str] = set()
    for question in (ASK_REJECTED_QUESTION, ASK_LADDER_QUESTION, ASK_WIDENED_QUESTION):
        outcome = run(asking, question)
        fired |= set(outcome.loops)
        bounded(outcome)

    assert fired == set(LOOPS), sorted(set(LOOPS) - fired)


def test_a_question_that_finds_nothing_still_terminates_and_spends_at_most_the_ceiling(
        asking: Any):
    """Every path through §8.1 is bounded: the budget only decreases and the exclusions only grow.

    :data:`MAX_MOVES` is a bug detector rather than a policy — reaching it means the machine
    cycled — so the assertion is that a question with no answer anywhere lands well inside it.
    """
    outcome = run(asking, "pneumatic valve island manifold pressure switch")

    bounded(outcome)
    assert outcome.reads <= asking.config.reads_per_question
    assert len(outcome.trace) < MAX_MOVES
