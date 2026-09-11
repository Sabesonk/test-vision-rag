"""L4 — one real `vsir ask`, against a real vision model, for the claims replay cannot make.

Almost everything about the loop is provable for free and is proved at L0 and L2: the machine, all
six correction loops, the gate's three outcomes, the budget ceiling, the abstention wording. Two
things are not, and U028 is why this module exists — **five defects between `VSIR_VLM=stub` and a
published document survived 1149 green tests**, because a stub never builds a request, loads a
prompt or opens an SDK client:

* **the loop's own `read` is a call a provider accepts.** Every level below this one hands the
  loop a response frozen under the key it asked for. Here the loop composes the call: the pages
  its triage chose, the question as the caller typed it, the pinned dpi, the schema this release
  declares. A loop whose read cannot be *made* is invisible in replay.
* **the gate holds against a real model's transcription.** The whole design rests on the claim
  that a code a model got wrong is stopped before it reaches a reader. Against a frozen fixture
  that claim is a statement about our own JSON; here the codes are whatever the model reads off
  the sheet, and the assertion is against what the corpus generator says is **printed** — ground
  truth independent of the model, the index and the gate alike.

**What it spends:** the loop's own reads for two questions, bounded by `VSIR_READS_PER_QUESTION`
(so at most six calls, and one is the target for the first question). The ingest in front of them
is free — it replays the frozen S2 corpus (D10) — and the gate's `verify` calls cost nothing.

**Which document.** The pilot `TC1E-SF` is what §13 M6's demo names, and **OQ-1 is still open**:
the PDF is not in the tree. §17's documented fallback is the generated corpus, which is stronger
for the second claim above: every code printed on every page of it is known exactly, from
`vsir.eval.synthetic_pdf`, which is a *fixture generator* and not the code under test.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

import pytest
from qdrant_client import QdrantClient

from vsir.cli import main as cli_main
from vsir.config import load_config
from vsir.core import ids
from vsir.core.tok import tok
from vsir.eval import synthetic_pdf as generator
from vsir.runner import loop as loop_module
from vsir.runner.answer import BADGE_READ_FROM_IMAGE, BADGE_VERIFIED, FORBIDDEN_WORDING
from vsir.serve import app as app_module
from vsir.serve import auth as auth_module

pytestmark = pytest.mark.paid

ROOT = Path(__file__).resolve().parents[3]
CORPUS_PDF = ROOT / "data" / "source" / "synthetic_3window.pdf"
CORPUS_FIXTURE = ROOT / "data" / "fixtures" / "synthetic_3window"

#: Its own ids and its own collections: a paid run must not disturb a corpus another suite is
#: asserting about, and it must not inherit one either.
DOC_ID = "vsir-ask-real"
REVISION = "1.0"
COLLECTION = "vsir_pages_l4_ask"
RUNS = "vsir_runs_l4_ask"

#: The answerable question, and it is the replay suite's own — the loop's handle branch resolves
#: `K119` on the exact surface to page 19 and nowhere else, so the *page selection* is identical
#: to the free run and the only new variable is the model. That is the comparison §13 M6 asks
#: for: *"the same citations as the replay run"*.
QUESTION = generator.ASK_ANSWER_QUESTION
ANSWER_PAGE = 19

#: Deliberately unanswerable, and unanswerable in the way that matters: `K999` is not printed
#: anywhere in this corpus, and two of its pages have no text layer at all. So the honest outcome
#: is an abstention that **names the gap** — never *"not in these documents"* while those pages
#: are unexamined (§8.5) — and never a fabricated citation.
UNANSWERABLE_QUESTION = "where is K999 wired on the guard door interlock"

if os.environ.get("VSIR_ALLOW_PAID") != "1":
    pytest.skip("VSIR_ALLOW_PAID is not 1 — this module spends money and refuses to run without "
                "the explicit opt-in (§12.2)", allow_module_level=True)
if not (os.environ.get("VSIR_VLM_KEY") or "").strip():
    pytest.skip("VSIR_VLM_KEY is unset. A paid layer with no credential fails per call, after "
                "billing whatever it managed to send (§17 OQ-2)", allow_module_level=True)
if not CORPUS_PDF.is_file():
    pytest.skip(f"{CORPUS_PDF} is missing — rebuild it with `python -m vsir.eval.synthetic_pdf`",
                allow_module_level=True)


def page_id(page_no: int) -> str:
    return ids.page_id(DOC_ID, REVISION, page_no)


def printed_on(page_no: int) -> set[str]:
    """Every token printed on that page, from the **generator** — ground truth, not the index.

    This is what makes the gate's verdicts checkable against something neither the model nor
    Qdrant produced: the corpus was drawn by this function's own module, so what is on the sheet
    is known exactly.
    """
    return {token for line in generator.expected_text(page_no) for token in tok(line)}


@pytest.fixture(scope="module")
def published(tmp_path_factory: Any) -> Iterator[str]:
    """The corpus, ingested and published — **for free**, by replaying the frozen S2 responses.

    The ingest is not what this module tests and must not be what it pays for. Afterwards the
    environment is put back to the live backend, because a fixture directory left in it would
    serve a frozen `read` and this module would buy nothing while reporting that it had (§15
    Factor X, D10).
    """
    store = tmp_path_factory.mktemp("l4-ask-documents")
    os.environ.update({"VSIR_COLLECTION": COLLECTION, "VSIR_RUNS_COLLECTION": RUNS,
                       "VSIR_DOC_STORE": str(store)})
    exit_code = cli_main([
        "ingest", str(CORPUS_PDF), "--vlm", "stub", "--fixture", str(CORPUS_FIXTURE),
        "--doc-id", DOC_ID, "--revision", REVISION,
    ])
    assert exit_code == 0, "the free replay ingest did not complete — nothing was billed"

    os.environ["VSIR_VLM"] = "gemini"
    os.environ.pop("VSIR_FIXTURE", None)
    cfg = load_config()
    assert cfg.vlm == "gemini" and not cfg.fixture_dir
    client = QdrantClient(url=cfg.qdrant_url, timeout=60, check_compatibility=False)
    try:
        yield cfg.pages_collection
    finally:
        for name in (cfg.pages_collection, RUNS):
            if client.collection_exists(name):
                client.delete_collection(name)
        client.close()


@pytest.fixture(scope="module")
def runtime(published: str) -> Iterator[Any]:
    """The release's own dispatcher with the live backend behind it (§7.5, §15 Factor XII)."""
    built, client = app_module.runtime_from_env(dict(os.environ))
    try:
        yield built
    finally:
        client.close()


def run(runtime: Any, question: str) -> Any:
    """One question through the shipped loop — the same call `POST /ask` and `vsir ask` make."""
    def call(tool: str, arguments: Any) -> Any:
        return app_module.dispatch(runtime, tool, dict(arguments),
                                   identity=auth_module.local_identity("l4-ask-real"),
                                   correlation={})

    return loop_module.run(question, call=call,
                           reads_per_question=runtime.config.reads_per_question, sink=None)


@pytest.fixture(scope="module")
def answered(runtime: Any) -> Any:
    """**The paid run.** One question, and the loop spends what §8.4's ceiling allows."""
    return run(runtime, QUESTION)


@pytest.fixture(scope="module")
def abstained(runtime: Any) -> Any:
    """**The second paid run**, and it may spend nothing: the code is printed nowhere."""
    return run(runtime, UNANSWERABLE_QUESTION)


# ── the loop's read is a call a provider accepts (the half replay cannot claim) ─────────────────

def test_a_real_ask_completes_and_the_pages_are_the_ones_the_replay_run_read(answered: Any):
    """§13 M6's L4 acceptance: *"the same citations as the replay run"*.

    The page selection is settled by the exact surface — the question names `K119`, which page 19
    prints and no other page does — so if the citations moved, the retrieval moved, and this is
    the row that would say so.
    """
    assert answered.refusal is None, answered.refusal
    assert answered.state in {"answer", "abstain"}
    assert answered.reads >= 1, "the loop has to have looked at something to answer at all"
    looked = [move for move in answered.trace if move.spends]
    assert looked and all(move.action == "read" for move in looked)
    assert [move.state for move in answered.trace[:2]] == ["descend", "triage"]
    # The page the loop **read**, which is what "the same citations as the replay run" is about.
    # Asserted on the read move rather than on the checks, because a model that named no code
    # legitimately produces an empty check log and would make a citation assertion vacuous.
    assert page_id(ANSWER_PAGE) in looked[0].detail or [
        move for move in answered.trace if move.action == "route"
        and page_id(ANSWER_PAGE) in move.detail], (
        f"the loop read something other than page {ANSWER_PAGE}: the retrieval moved, and this "
        f"row is the one that says so")


def test_the_loop_spent_no_more_than_the_per_question_ceiling(answered: Any, runtime: Any):
    """§8.4's hard ceiling, against a real model rather than against a fixture's cooperation."""
    assert answered.reads <= runtime.config.reads_per_question
    assert answered.reads_remaining >= 0


# ── the gate holds against a real model's transcription ─────────────────────────────────────────

def test_every_code_in_the_answer_is_actually_printed_on_the_page_it_is_cited_from(answered: Any):
    """I8, checked against the corpus generator and not against the index or the model.

    A `present` verdict means the phrase is in the page's extracted text; this asserts the
    stronger thing — that it is **on the sheet** — using the module that drew the sheet. A code
    the model misread cannot pass both, which is the whole point of §1.1.
    """
    if not answered.answered:
        # Not a skip: a live model that read the sheet and still said `sufficient: false` is a
        # legitimate outcome, and the thing to assert about it is that nothing was rendered from
        # a read the model itself disowned (§7.2.6, §8.4) — never that the row did not apply.
        assert answered.abstention is not None
        assert answered.abstention.reason in {"insufficient", "rejected", "not_found",
                                              "scope_exhausted", "no_pages"}
        assert not [move for move in answered.trace if move.state == "draft"] or \
            answered.rejections, (
            "a draft was written and neither rendered nor rejected, which is a third outcome the "
            "gate does not have")
        return

    for claim in answered.answer.claims:
        assert claim.badge in (BADGE_VERIFIED, BADGE_READ_FROM_IMAGE)
        if claim.status != "present":
            continue
        page_no = int(claim.page_id.rsplit("#p", 1)[-1])
        printed = printed_on(page_no)
        assert set(tok(claim.code)) <= printed, (
            f"{claim.code!r} cleared the gate as `present` on page {page_no}, and that page does "
            f"not print it. Either the exact surface disagrees with the corpus (F2, I3) or the "
            f"gate cleared a claim it should have rejected (I8)")


def test_a_code_the_model_misread_never_reaches_the_answer(answered: Any):
    """The failure the product exists to prevent, on a real transcription.

    Whatever the model emitted, the codes that **render** are exactly the ones a check cleared:
    every one of them has a `(claim, page)` row in the gate's log with a status that renders. A
    code with no row, or with an `absent` row, is a code that did not get out.
    """
    rendered = {(claim.code, claim.page_id) for claim in
                (answered.answer.claims if answered.answered else ())}
    cleared = {(row.claim, row.page_id) for row in answered.checks
               if row.claim and row.status in {"present", "unverifiable"}}

    assert rendered <= cleared, sorted(rendered - cleared)
    for row in answered.checks:
        if row.status == "absent":
            assert row.claim == "", "a rejected claim is never echoed, not even in the call log"


def test_an_unanswerable_question_abstains_with_coverage_numbers_and_fabricates_nothing(
        abstained: Any):
    """§13 M6's other L4 row, and §8.5 against a live model.

    `K999` is printed nowhere. The loop may look at the image-only pages — that is Loop 5 doing
    its job — but it may not answer, and it may not say the corpus does not contain it while any
    of those pages is unexamined.
    """
    assert abstained.refusal is None, abstained.refusal
    assert not abstained.answered, (
        "a live model produced an answer for a code that is printed on no page of this document")
    assert abstained.abstention is not None
    text = abstained.abstention.text
    assert str(abstained.abstention.pages_searched) in text
    if abstained.abstention.image_only_unexamined:
        assert FORBIDDEN_WORDING not in text.lower(), text
    assert "K999" not in text and "k999" not in text.lower(), (
        "the abstention names what was searched, never the code that was not found")
