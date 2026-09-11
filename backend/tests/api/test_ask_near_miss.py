"""L3 — the adversarial run at the answer surface: 100 fabricated codes, asked as questions.

This is §12.4's eval one layer up. U006 asserts that `lookup` and `verify` never return a
near-miss code; this asserts the property the product is actually sold on: **no answer this
service renders cites a code that is not printed on the page it is cited from** (§1.1, I8). It is
the injury the whole design exists to prevent, so a failure here is P0 and not a test to relax.

The 100 questions are built from :func:`~vsir.core.nearmiss.near_misses` — the same generator the
abstention eval uses, fed the really-ingested corpus's own observed tokens, so every fake shares a
prefix with something the document prints and differs from it by one character. `K152` for `K120`
is the ordinary way a vision model gets a schematic wrong, and each of these is that mistake made
deliberately.

**Why a green run here is evidence and not paralysis.** A suite that never answered anything would
pass this trivially, so the last two rows are controls: the real question still answers in one
paid read, and a fabricated code that a `read` really did emit is rejected by the gate rather than
rendered. The first proves the loop can answer; the second proves the gate is what stops it.
"""
from __future__ import annotations

import json
from typing import Any

from vsir.core.nearmiss import near_misses
from vsir.core.observed_tokens import Inventory
from vsir.eval.synthetic_pdf import ASK_ANSWER_QUESTION, ASK_REJECTED_QUESTION
from vsir.runner import loop as loop_module
from vsir.serve import app as app_module
from vsir.serve import auth as auth_module

#: §12.4's count, and the plan's: *"feeding all 100 `near_misses(n=100)` as questions"*.
FAKES = 100


def runner(asking: Any) -> Any:
    """The loop, over the really ingested corpus, through the release's own dispatcher."""
    runtime = asking.runtime

    def call(tool: str, payload: Any) -> Any:
        return app_module.dispatch(runtime, tool, dict(payload),
                                   identity=auth_module.local_identity("cli"), correlation={})

    def run(question: str, **arguments: Any) -> Any:
        return loop_module.run(question, call=call,
                               reads_per_question=runtime.config.reads_per_question,
                               sink=None, **arguments)

    return run


def observed(rastered: Any) -> Inventory:
    """The corpus's own observed-token inventory, off the run's §6.8 export.

    The fakes have to be near misses of **this** document or the exercise is meaningless: a code
    that shares no prefix with anything printed is refused by a plain phrase match and proves
    nothing about the gate. Read over the shipped export route rather than rebuilt here, so the
    tokens are the ones the corpus really published.
    """
    response = rastered.client.get(
        f"/runs/{rastered.record['run_id']}/export/observed_tokens.jsonl",
        headers=rastered.header)
    assert response.status_code == 200, response.text
    # One line per **document** (§6.8), each carrying the whole sorted token list.
    rows = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    tokens = sorted({str(token) for row in rows for token in (row.get("tokens") or ())})
    assert tokens, response.text
    return Inventory(doc_id=str(rows[0].get("doc_id") or ""), tokens=tuple(tokens))


def test_no_fabricated_code_is_ever_cited_in_a_rendered_answer(asking: Any,
                                                              rastered: Any):
    """The 100, each asked as a question. None is answered, and none appears as a claim.

    What happens to each one is itself worth reading: the exact surface has no page printing the
    code, the ladder's every branch is filtered by that phrase to nothing, and two pages of this
    document have no text layer — so the loop escalates to vision (Loop 5) rather than concluding
    the corpus does not contain it, and then refuses to invent a response for a page set no
    fixture was frozen for (D10). At no point is a plausible neighbour offered as the answer.
    """
    run = runner(asking)
    inventory = observed(rastered)
    fakes = [one.fake for one in near_misses(inventory, n=FAKES)]
    assert len(fakes) == FAKES, f"the generator produced {len(fakes)} of {FAKES}"

    answered: list[str] = []
    cited: list[tuple[str, str]] = []
    for fake in fakes:
        assert fake not in inventory, f"{fake} is an observed token of this corpus after all"
        outcome = run(f"where is {fake} wired")
        if outcome.answered:
            answered.append(fake)
            cited.extend((fake, claim.code) for claim in outcome.answer.claims
                         if claim.code.lower() == fake.lower())
        assert not any(claim.code.lower() == fake.lower()
                       for claim in (outcome.answer.claims if outcome.answer else ())), fake
        assert not any(row.claim.lower() == fake.lower() and row.status == "present"
                       for row in outcome.checks), (
            f"{fake} was checked and came back `present`, which would mean the exact surface "
            f"disagrees with the corpus it indexed (F2, I3)")

    assert not cited, cited
    assert not answered, (
        f"{len(answered)} fabricated code(s) produced an answer: {answered[:5]}")


def test_a_fabricated_code_is_never_disclosed_as_its_own_near_miss(asking: Any,
                                                                   rastered: Any):
    """F16 at the answer surface: `present_instead` is what the page prints, never the claim.

    A rejection discloses the observed tokens sharing a prefix with the code that failed — and if
    the claim itself could appear there, a caller reading the rejection would find the fabricated
    code presented as *"different part"*, which is the disclosure becoming the injury.
    """
    run = runner(asking)

    for one in near_misses(observed(rastered), n=10):
        outcome = run(f"where is {one.fake} wired")
        for rejection in outcome.rejections:
            assert one.fake.lower() not in [
                token.lower() for token in rejection.present_instead], one.fake


def test_the_real_question_still_answers_so_this_suite_is_not_green_by_paralysis(asking: Any):
    """The control. A loop that refused everything would pass every row above.

    Same corpus, same instance, one question whose code **is** printed: one paid read, an answer,
    and every code in it badged `verified` against the page it is cited on.
    """
    outcome = runner(asking)(ASK_ANSWER_QUESTION)

    assert outcome.answered and outcome.reads == 1
    assert [claim.status for claim in outcome.answer.claims] == ["present"] * 3
    assert {row.status for row in outcome.checks} == {"present"}


def test_a_misread_the_model_really_emitted_is_stopped_by_the_gate_and_not_by_the_fixture(
        asking: Any):
    """The strongest row in this file, and the only one where the fake gets all the way in.

    The frozen response for page 20 names `K152` — the misread — so the loop obtains it from a
    real `read`, drafts a sentence containing it, and is then stopped by the gate: the draft is
    rejected whole, `K152` appears in nothing the caller receives, and the disclosure is `k120`,
    which is what the page really prints. Every other row here is stopped earlier; this one is
    stopped by I8.
    """
    outcome = runner(asking)(ASK_REJECTED_QUESTION)

    assert not outcome.answered
    assert "K152" not in json.dumps(
        {"abstention": outcome.abstention.model_dump() if outcome.abstention else None,
         "checks": [row.model_dump() for row in outcome.checks],
         "rejections": [one.model_dump() for one in outcome.rejections]})
    assert [one.present_instead for one in outcome.rejections] == [["k120"]]
    assert outcome.abstention.reason == "rejected"
