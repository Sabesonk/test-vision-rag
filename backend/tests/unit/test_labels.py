"""L0/L1 — printed labels and their precedence (Spec §6.5, F5).

F5 is *"the agent follows a cross-reference to the wrong page"*, and the way that happens is a
label something picked. So the rule under test is narrow: where two readings of a page's printed
label disagree and the page cannot arbitrate between them, **both** come back and the label
itself is empty. A single silent pick is the failure, not the imprecision.

The corpus is built for this: its own `/PageLabels` table numbers the front matter `i`/`ii` and
restarts at `1` on PDF page 3, so `label = index - 2` everywhere and nothing about the printed
numbering can be inferred from the PDF index.
"""
from __future__ import annotations

import pytest

from vsir.ingest.derive import Label, attribute_label, interpolate_labels


# ── precedence: text-layer-confirmed > model-read > interpolated ────────────────────────────────

def test_a_label_the_page_prints_is_confirmed():
    label = attribute_label("13", "13", "… Page 13 of 40 · rev 1.0", has_text=True)

    assert label == Label(printed="13", verified=True)


def test_a_model_read_label_the_page_does_not_print_is_kept_but_unverified():
    """Kept, because it is the only reading there is; unverified, because nothing backs it."""
    label = attribute_label("7-12", "", "a page whose footer is a graphic", has_text=True)

    assert label.printed == "7-12"
    assert label.verified is False
    assert label.interpolated is False


def test_the_files_own_label_table_confirms_a_page_with_no_text_layer():
    """A scanned sheet has no text to check against, and the PDF still declares its label.

    That declaration is a mechanical readout of a structure the file carries — not a model
    reading and not something derived from the page's content — so it stands on its own.
    """
    label = attribute_label("", "ii", "", has_text=False)

    assert label == Label(printed="ii", verified=True)


def test_the_model_agreeing_with_the_label_table_is_confirmation_without_a_text_layer():
    assert attribute_label("ii", "ii", "", has_text=False) == Label(printed="ii", verified=True)


def test_a_page_with_no_reading_at_all_has_no_label():
    assert attribute_label("", "", "some text", has_text=True) == Label()


def test_whitespace_is_collapsed_and_nothing_else_is_normalised():
    """The only permitted normalisation (§5.2). `7-12` never becomes `88`."""
    assert attribute_label("  7 - 12 ", "", "…", has_text=True).printed == "7 - 12"


# ── ambiguity resolves to a list, never a pick (F5) ─────────────────────────────────────────────

def test_ambiguous_label_returns_list_never_silent_pick():
    """AC, and the F5 row: two readings the page cannot arbitrate → a **list**, and no label.

    `printed_page_no` is deliberately left empty. Putting either candidate there — even with
    `label_verified=False` beside it — is a pick, and everything downstream that renders a
    citation reads that field.
    """
    label = attribute_label("7-12", "12", "a page whose footer is a graphic", has_text=True)

    assert label.ambiguous is True
    assert label.candidates == ("7-12", "12")
    assert label.printed == ""
    assert label.verified is False


def test_a_page_printing_both_readings_is_also_ambiguous():
    """Two labels genuinely on the sheet is ambiguity too — picking the first is still a pick."""
    label = attribute_label("7-12", "12", "7-12 … continued from 12", has_text=True)

    assert label.candidates == ("7-12", "12")
    assert label.printed == ""


def test_the_text_layer_breaks_a_tie_when_it_prints_exactly_one_of_them():
    """This is what "text-layer-confirmed **>** model-read" means: evidence, not a preference."""
    assert attribute_label("A-4", "12", "… sheet A-4 …", has_text=True) == Label(printed="A-4",
                                                                                 verified=True)
    assert attribute_label("A-4", "12", "… page 12 …", has_text=True) == Label(printed="12",
                                                                               verified=True)


def test_a_reading_contained_in_the_other_cannot_break_the_tie():
    """`7-12` tokenises to `[7, 12]`, so a page printing it prints `12` as well (§5.6).

    Both readings are then confirmed, which is ambiguity rather than a win for the longer one:
    preferring it would be a rule about label shapes, and §5.2 has no such rule.
    """
    label = attribute_label("7-12", "12", "… 7-12 …", has_text=True)

    assert label.candidates == ("7-12", "12")
    assert label.printed == ""


def test_two_readings_that_are_the_same_string_are_not_ambiguous():
    assert attribute_label("13", " 13 ", "", has_text=False) == Label(printed="13", verified=True)


# ── interpolation, and its disclosure ───────────────────────────────────────────────────────────

def test_an_unlabelled_page_between_two_numbers_is_interpolated_and_says_so():
    filled = interpolate_labels([Label(printed="11", verified=True), Label(),
                                 Label(printed="13", verified=True)])

    assert filled[1] == Label(printed="12", verified=False, interpolated=True)
    assert filled[0].interpolated is False


def test_interpolation_never_extrapolates_past_the_end():
    """`impl` inferred from the nearest sibling and a delta, which extrapolates (§6.5)."""
    filled = interpolate_labels([Label(), Label(printed="2", verified=True), Label()])

    assert filled[0] == Label()
    assert filled[2] == Label()


def test_an_unbracketed_gap_is_left_unlabelled():
    """Two pages missing between the neighbours is not one page with nowhere else to be."""
    filled = interpolate_labels([Label(printed="11", verified=True), Label(), Label(),
                                 Label(printed="14", verified=True)])

    assert [label.printed for label in filled] == ["11", "", "", "14"]


def test_a_chapter_relative_neighbour_gives_no_bracket():
    """`7-11` and `7-13` do not put `7-12` between them by arithmetic — there is no formula."""
    filled = interpolate_labels([Label(printed="7-11"), Label(), Label(printed="7-13")])

    assert filled[1] == Label()


def test_an_ambiguous_page_is_not_quietly_filled_in():
    """Interpolating over an ambiguity would resolve it by the back door."""
    filled = interpolate_labels([Label(printed="11"), Label(candidates=("a", "b")),
                                 Label(printed="13")])

    assert filled[1].candidates == ("a", "b")
    assert filled[1].printed == ""


# ── on the corpus ───────────────────────────────────────────────────────────────────────────────

def test_every_page_of_the_corpus_carries_the_label_the_fixture_records(derived, expected):
    """AC: the labels are the fixture's, offset and all — `label = PDF index - 2` (I4, F7)."""
    observed = {str(page.page_no): page.record.content.printed_page_no for page in derived.pages}

    assert observed == expected["printed_labels"]
    assert observed[str(expected["first_labelled_page"])] == "1"


def test_no_page_of_the_corpus_needed_a_pick_or_an_inference(derived):
    """A sound document should produce neither an ambiguity nor an interpolation."""
    assert not [page.page_no for page in derived.pages if page.record.content.label_candidates]
    assert not [page.page_no for page in derived.pages if page.record.content.interpolated]
    assert all(page.record.content.label_verified for page in derived.pages)


def test_the_scanned_pages_take_their_label_from_the_file_not_the_model(derived, extracted):
    """The model reports nothing for a sheet with nothing printed on it; the file still does."""
    _doc, probed, _facts, _plan, extraction = extracted
    form = extraction.windows[0].out.pages[0]

    assert form.printed_page_no == ""
    assert probed.page(1).label == "i"
    assert derived.page(1).record.content.printed_page_no == "i"
    assert derived.page(1).record.content.label_verified is True


@pytest.mark.parametrize("flag", ["label_ambiguous", "label_interpolated"])
def test_no_label_disclosure_flag_fires_on_the_corpus(derived, flag):
    assert not [page.page_no for page in derived.pages if flag in page.record.content.flags]
