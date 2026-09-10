"""L0/L1 — code reattribution (Spec §6.5, F6, I2).

F6 is *"cites a page for a code that is on its neighbour"*. It happens because attention bleeds
across a window fold: the model looks at the facing sheet and reports what it saw there. The
repair is to move the sighting to the page whose text actually carries the code, and to **say
that it moved** — `content.moved_from` is what makes the move auditable rather than a quiet
correction.

The corpus wires the case in: page 21's frozen response carries page 22's `K` code, and both
pages are inside window 2, which is the condition §6.5 puts on the move.

The other half is I2's, and it is the half that matters more: a code grounded in **no** page's
text does not move anywhere, does not enter `codes_in_text`, and can never be found — because the
exact surface is `text`, and derivation does not write `text`.
"""
from __future__ import annotations

from vsir.core import ids
from vsir.core.exact import printed_in
from vsir.core.tok import tok, token_set
from vsir.ingest import derive as dv


def test_code_reattributed_records_moved_from(derived, expected):
    """AC, and the F6 row: the code moved to the page that prints it, with its origin recorded."""
    trap = expected["extraction"]["reattribution"]
    donor = derived.page(trap["page"]).record
    receiver = derived.page(trap["from_page"]).record

    assert [moved.model_dump() for moved in receiver.content.moved_from] == [{
        "code": trap["code"],
        "from_page_id": ids.page_id(donor.doc_id, donor.revision, trap["page"]),
    }]
    assert trap["code"] not in donor.content.codes
    assert dv.FLAG_CODES_REATTRIBUTED in receiver.content.flags
    assert dv.FLAG_CODES_REATTRIBUTED not in donor.content.flags


def test_the_move_is_reported_beside_the_records(derived, expected):
    """The demo and the run record read this, so it is part of the output, not a log line."""
    trap = expected["extraction"]["reattribution"]

    assert [(move.code, move.from_page_no, move.to_page_no) for move in derived.moves] == [
        (trap["code"], trap["page"], trap["from_page"])]
    assert derived.moves[0].window == (15, 28)


def test_the_donor_page_is_not_penalised_for_a_code_that_left(derived, expected):
    """The sighting was wrong about the page, not about the document — so it costs nothing.

    Leaving it behind would mark down a page whose text is perfectly sound, and `grounded_rate`
    is meant to say *"the extraction on this page is broken"*.
    """
    trap = expected["extraction"]["reattribution"]

    assert derived.page(trap["page"]).record.content.grounded_rate == 1.0
    assert derived.page(trap["from_page"]).record.content.grounded_rate == 1.0


def test_the_moved_code_is_in_the_receiving_pages_codes_in_text(derived, expected):
    """It grounds where it landed, which is the point of moving it."""
    trap = expected["extraction"]["reattribution"]
    receiver = derived.page(trap["from_page"]).record

    assert trap["code"].lower() in receiver.content.codes_in_text
    assert trap["code"] in receiver.text
    # And still exactly once in `codes`: the receiving page had already reported it itself.
    assert receiver.content.codes.count(trap["code"]) == 1


# ── the code that is grounded nowhere (I2, F14) ─────────────────────────────────────────────────

def test_an_ungrounded_code_stays_put_and_costs_its_page(derived, expected):
    """AC: printed on no page ⇒ it stays, lowers `grounded_rate`, and enters no exact surface."""
    loose = expected["extraction"]["ungrounded"]
    page = derived.page(loose["page"]).record

    assert loose["code"] in page.content.codes
    assert loose["code"].lower() not in page.content.codes_in_text
    assert page.content.grounded_rate == 10 / 11
    assert dv.FLAG_UNGROUNDED_CODES in page.content.flags
    assert not page.content.moved_from


def test_an_ungrounded_code_is_in_no_pages_text_and_so_in_no_pages_codes_in_text(derived,
                                                                                 expected):
    """I2 — `lookup` searches `text`, so a code no page prints is unreachable by construction."""
    loose = expected["extraction"]["ungrounded"]

    assert not [page.page_no for page in derived.pages if loose["code"] in page.record.text]
    assert not [page.page_no for page in derived.pages
                if loose["code"].lower() in page.record.content.codes_in_text]


def test_the_ungrounded_code_does_reach_the_opt_in_surface_and_only_that_one(derived, expected):
    """D3 — `vlm_codes` is the model's reading, opt-in, and its hits are always unverified.

    This is the one place a hallucinated code is visible at all, which is deliberate: an operator
    investigating *why* a page claims something needs to see what the model said.
    """
    loose = expected["extraction"]["ungrounded"]
    page = derived.page(loose["page"]).record

    assert loose["code"] in page.vlm_codes
    assert loose["code"] not in page.text


# ── the rules of the move ───────────────────────────────────────────────────────────────────────

def test_a_code_only_moves_within_the_window_that_saw_both_pages(extracted):
    """§6.5's window bound: a code two windows away was seen by a different call.

    Page 14 is the last page of window 1 and page 15 the first of window 2. A code page 14's
    response reports which is printed on page 15 does **not** move — the model that read page 14
    never saw page 15, so "it read it off the facing sheet" is not what happened.
    """
    doc, probed, _facts, _plan, extraction = extracted
    window_one = extraction.windows[0]
    # A code printed on page 15 and on neither of page 14's own neighbours, so the only page it
    # could move to is the one on the far side of the fold. Chosen from the text rather than
    # written down, so the test cannot drift from the corpus.
    across = sorted(token_set(probed.page(15).text)
                    - token_set(probed.page(14).text)
                    - token_set(probed.page(13).text))[0]

    assert not printed_in(tok(probed.page(14).text), across)
    forms = [
        form.model_copy(update={"codes": [*form.codes, across]})
        if window_one.window.absolute(form.page_index) == 14 else form
        for form in window_one.out.pages
    ]
    import dataclasses
    tampered = dataclasses.replace(
        extraction,
        windows=(dataclasses.replace(window_one,
                                     out=window_one.out.model_copy(update={"pages": forms})),
                 *extraction.windows[1:]))

    derivation = dv.derive(tampered, probed=probed, doc=doc)

    # The corpus's own trap still fires inside window 2; nothing crosses the fold at 14|15.
    assert [(move.from_page_no, move.to_page_no) for move in derivation.moves] == [(21, 22)]
    assert across in derivation.page(14).record.content.codes
    assert not derivation.page(15).record.content.moved_from
    # It cost page 14 its grounded_rate, which is the disclosure: the sighting is unbacked here.
    assert derivation.page(14).record.content.grounded_rate < 1.0


def test_a_code_printed_on_both_neighbours_is_not_moved_by_a_coin_flip(extracted):
    """Ambiguity is disclosed, never resolved by picking a side (the shape of F5).

    The vendor part numbers are printed on every full page, so a page reporting one it does not
    print has two equally good candidates either side. It keeps the sighting, flags the
    ambiguity, and pays for it in `grounded_rate` — which is the honest reading: this page's
    extraction really did claim something its own text does not carry.
    """
    import dataclasses

    doc, probed, _facts, _plan, extraction = extracted
    window = extraction.windows[1]
    # Page 20's own EAO code is printed on page 20 alone; give it to page 21 instead… then take
    # page 21's text out of the running by choosing a code printed on 20 AND 22.
    both = "SCHNEIDER"
    assert both in probed.page(20).text and both in probed.page(22).text
    stripped = probed.page(21).text.replace(both, "")
    assert both not in stripped

    forms = [
        form.model_copy(update={"codes": [both]})
        if window.window.absolute(form.page_index) == 21 else form
        for form in window.out.pages
    ]
    tampered = dataclasses.replace(
        extraction,
        windows=(extraction.windows[0],
                 dataclasses.replace(window, out=window.out.model_copy(update={"pages": forms})),
                 extraction.windows[2]))

    class _Blanked:
        """The probe, with page 21's copy of the shared token removed. Nothing else changes."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def page(self, page_no):
            page = self._inner.page(page_no)
            return page if page_no != 21 else dataclasses.replace(page, text=stripped)

        @property
        def pages(self):
            return tuple(self.page(n) for n in range(1, self._inner.page_count + 1))

    derivation = dv.derive(tampered, probed=_Blanked(probed), doc=doc)
    page = derivation.page(21).record

    assert derivation.moves == ()
    assert page.content.codes == [both]
    assert dv.FLAG_AMBIGUOUS_REATTRIBUTION in page.content.flags
    assert page.content.grounded_rate == 0.0
