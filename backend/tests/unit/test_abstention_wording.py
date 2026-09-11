"""L0 — the constrained abstention wording (Spec §8.5). The words are part of the contract.

§8.5 forbids one sentence and requires a shape. *"Not in these documents"* is unavailable while
``pages_no_text_read < scope_stats.pages_no_text``, because a corpus with unexamined image-only
pages **has not been searched** — and an abstention that sounds complete is a fabricated absence
in the one direction nobody audits. The honest wording names the gap: the documents searched, the
pages searched, and how many image-only pages nobody looked at.

Two things make this testable at L0 rather than only end to end. The coverage numbers come from
``scope_stats``, which every Family A envelope already carries (§7.1), so
:class:`~vsir.runner.answer.Coverage` is built from a payload and nothing else; and the
prohibition is checked on the **composed string** by
:func:`~vsir.runner.answer.assert_wording`, so a future edit that adds a reassuring closing
sentence is caught by the same line that catches a mis-set flag.
"""
from __future__ import annotations

import pytest

from vsir.runner.answer import (
    FORBIDDEN_WORDING,
    INSUFFICIENT,
    NO_PAGES,
    NOT_FOUND,
    REASONS,
    REJECTED,
    SCOPE_EXHAUSTED,
    Coverage,
    abstention,
    assert_wording,
)


def payload(*, pages: int, docs: tuple[tuple[str, float], ...], no_text: int = 0) -> dict:
    """A Family A envelope's ``scope_stats``, as a rung really reports it (§7.1)."""
    return {"scope_stats": {"pages": pages, "pages_no_text": no_text,
                            "docs": [{"doc_id": doc, "searchable_ratio": ratio}
                                     for doc, ratio in docs]}}


BLIND = Coverage.of(payload(pages=54, no_text=14,
                            docs=(("TC1E-SF", 1.0), ("LTC1AV81", 1.0), ("CE-TC1AV8", 0.0))))
SEARCHABLE = Coverage.of(payload(pages=12, docs=(("TC1E-SF", 1.0),)))


# ── the one prohibition (§8.5) ──────────────────────────────────────────────────────────────────

def test_not_in_these_documents_is_absent_while_image_only_pages_are_unread():
    """The literal string, asserted as a literal. This is the sentence §8.5 names."""
    said = abstention(BLIND, reason=NOT_FOUND)

    assert FORBIDDEN_WORDING not in said.text.lower(), said.text
    assert said.image_only_unexamined == 14
    assert said.pages_no_text_read == 0


def test_the_honest_wording_names_the_documents_and_the_unexamined_count():
    """§8.5's own example: the searchable text of two binders, and 14 unexamined pages in a third."""
    said = abstention(BLIND, reason=NOT_FOUND)

    assert "TC1E-SF" in said.text and "LTC1AV81" in said.text
    assert "14 image-only page(s) in CE-TC1AV8 were not examined" in said.text, said.text
    assert "54 page(s) searched across 3 document(s)" in said.text, (
        "the plan requires the coverage numbers: 14 unexamined means something different beside "
        "54 pages than beside 1,440")
    assert said.blind_documents == ["CE-TC1AV8"]


def test_the_sentence_becomes_available_once_every_image_only_page_was_examined():
    """Only then. The rule is an inequality over two numbers, not a judgement about effort."""
    read_all = BLIND.looked_at(14)
    said = abstention(read_all, reason=NOT_FOUND)

    assert read_all.complete and read_all.unexamined == 0
    assert FORBIDDEN_WORDING in said.text.lower(), said.text
    assert "All 14 image-only page(s) in scope were examined" in said.text
    assert said.pages_no_text_read == 14


def test_a_fully_searchable_scope_may_say_it_outright():
    """No image-only page means no gap, and the strongest honest wording is available."""
    said = abstention(SEARCHABLE, reason=NOT_FOUND)

    assert FORBIDDEN_WORDING in said.text.lower()
    assert "Every page in scope has a text layer" in said.text


def test_assert_wording_raises_on_the_forbidden_sentence_and_names_both_numbers():
    """The guard, called directly — a raise, never an ``assert``: ``python -O`` strips asserts."""
    with pytest.raises(ValueError, match="pages_no_text_read"):
        assert_wording(f"Nothing found — it is {FORBIDDEN_WORDING}.", BLIND)

    # The same string is fine once the pages have been read: the wording is not banned, the
    # *claim* is, and the claim is only false while the gap is open.
    assert_wording(f"Nothing found — it is {FORBIDDEN_WORDING}.", BLIND.looked_at(14))


def test_the_composer_cannot_emit_a_sentence_the_rule_forbids():
    """:func:`abstention` calls the guard on every path, so no reason can slip past it."""
    for reason in REASONS:
        said = abstention(BLIND, reason=reason)
        assert FORBIDDEN_WORDING not in said.text.lower(), (reason, said.text)
        assert said.reason == reason


# ── what each reason says it did, and never that something does not exist ───────────────────────

@pytest.mark.parametrize("reason, phrase", [
    (NOT_FOUND, "Not found in the searchable text of"),
    (SCOPE_EXHAUSTED, "no wider scope"),
    (NO_PAGES, "no image-only page was available to look at"),
    (INSUFFICIENT, "do not answer this"),
    (REJECTED, "rejected"),
])
def test_each_reason_states_what_was_done(reason: str, phrase: str):
    """Five different instructions to the caller — retry wider, escalate, rephrase, or stop.

    Collapsing them into one sentence is the same mistake §7.1 refuses about the four absences:
    the caller has to guess which repair applies, and guessing wrong looks like the corpus is
    empty.
    """
    said = abstention(BLIND, reason=reason)

    assert phrase in said.text, said.text


def test_a_rejected_abstention_counts_the_claims_and_names_none_of_them():
    """The gate rejected a draft, and the codes it named are not disclosed here either (§8.4)."""
    said = abstention(SEARCHABLE, reason=REJECTED, rejected=2)

    assert said.rejected_claims == 2
    assert "codes it cited are not printed on the pages" in said.text
    assert "code" not in {field for field in said.model_dump()}


def test_an_unknown_reason_is_refused_rather_than_rendered_as_prose():
    """A reason nothing declared would render as an empty lead clause — a sentence with no claim."""
    with pytest.raises(ValueError, match="abstention reasons"):
        abstention(SEARCHABLE, reason="because_we_gave_up")


# ── the coverage numbers themselves (§5.7, §7.1) ────────────────────────────────────────────────

def test_coverage_is_read_off_the_envelope_and_never_recounted():
    """``scope_stats`` is the search's own report of what it searched (§7.1)."""
    assert BLIND.pages == 54
    assert BLIND.pages_no_text == 14
    assert BLIND.docs == ("TC1E-SF", "LTC1AV81", "CE-TC1AV8")
    assert BLIND.blind_docs == ("CE-TC1AV8",), "searchable_ratio < 1 is the blind-spot signal"


def test_merging_two_rungs_keeps_the_widest_scope_that_was_searched():
    """A loop that widened searched more than its final rung reports (§8.5's numbers, honestly)."""
    merged = SEARCHABLE.merge(BLIND)

    assert merged.pages == 54, "the maximum, not the last: widening searched more"
    assert merged.pages_no_text == 14
    assert set(merged.docs) == {"TC1E-SF", "LTC1AV81", "CE-TC1AV8"}


def test_looked_at_is_a_value_and_never_a_mutation():
    """The runner's own tally, and the only field it contributes (§15 Factor VI)."""
    once = BLIND.looked_at(2)

    assert once.pages_no_text_read == 2 and BLIND.pages_no_text_read == 0
    assert once.unexamined == 12
    assert once.looked_at(20).unexamined == 0, "the gap is floored at zero, never negative"


def test_an_empty_document_list_still_produces_a_sentence_with_a_subject():
    """A scope that matched no document is *"the scope searched"* and never an empty phrase."""
    said = abstention(Coverage(), reason=NOT_FOUND)

    assert said.text.startswith("Not found in the searchable text of the scope searched.")


def test_a_coverage_that_counted_nothing_claims_no_completeness():
    """§8.5's inequality is satisfied by `0 < 0` being false, and that is not a licence.

    A scope where no page was searched has nothing to be complete about, so the sentence is
    unavailable here too — reached from the other end. Found reviewing the M6 gate: the check is
    an inequality, and an empty coverage passes it while asserting the strongest thing the
    surface can say.
    """
    said = abstention(Coverage(), reason=NOT_FOUND)

    assert FORBIDDEN_WORDING not in said.text.lower(), said.text
    assert "No page was searched, so nothing follows about the corpus" in said.text
    assert said.pages_searched == 0
