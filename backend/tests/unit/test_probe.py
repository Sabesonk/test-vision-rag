"""L0/L1 — step 02, the text layer (Spec §6.1, I2, F15, register A1).

This is the module every later verification rests on: `verify` compares a claim against the text
this produces, so a page whose text is wrong or missing is a page where a wrong answer becomes
confidently sayable. Three of the assertions here are failure rows rather than unit tests —
`test_probe_extracts_text_on_a_mixed_document` (A1), `test_crop_trap_full_text_extracted` (F15)
and the `has_text == false` implication (§5.7).
"""
from __future__ import annotations

import pymupdf
import pytest

from vsir.config import DPI_ANSWER
from vsir.eval import synthetic_pdf as generator
from vsir.ingest import probe, render


@pytest.fixture(scope="module")
def probed(request):
    return probe.run(request.getfixturevalue("synthetic_pdf"))


def test_every_page_is_probed(probed, expected):
    assert probed.page_count == expected["page_count"]
    assert len(probed.pages) == expected["page_count"]
    assert [page.page_no for page in probed.pages] == list(range(1, expected["page_count"] + 1))


def test_the_probe_records_the_pinned_extractor(probed):
    """R3, §4.2 — PyMuPDF is the single point of truth for exact search, so which one ran is on
    every page. A version bump re-runs the crop and off-by-one fixtures; it is never incidental."""
    assert probed.probe_version == f"pymupdf-{pymupdf.__version__}"
    assert probed.probe_version.startswith("pymupdf-1.28.2")


def test_probe_extracts_text_on_a_mixed_document(probed, expected):
    """Register A1 — the one `else` that throws a mixed document's text away.

    `impl` guarded extraction with an eight-page sample. This corpus is built to defeat exactly
    that: a rasterised cover plus six short pages average below the born-digital threshold, so
    `impl` would have returned 42 empty strings and quarantined nothing, silently.
    """
    mixed = expected["mixed_document"]

    assert probed.sample_chars_per_page < mixed["born_digital_min_chars"]
    assert probe.BORN_DIGITAL_MIN_CHARS == mixed["born_digital_min_chars"]

    extracted = [page.page_no for page in probed.pages if page.has_text]
    assert len(extracted) == expected["page_count"] - len(expected["pages_without_text"])
    assert probed.has_text_layer is True


def test_a_page_with_no_text_layer_is_no_text(probed, expected):
    """§5.7 — `has_text == false` implies `text_trust == "no_text"`, and nothing promotes it."""
    without = [page.page_no for page in probed.pages if not page.has_text]

    assert without == expected["pages_without_text"]
    for page_no in without:
        page = probed.page(page_no)
        assert page.text.strip() == ""
        assert page.text_trust == "no_text"
    for page in probed.pages:
        assert (page.text_trust == "no_text") == (not page.has_text)


def test_the_searchable_ratio_is_the_documents_blind_spot(probed, expected):
    """§5.7 — pages with a text layer ÷ pages, on every `skim_documents` row."""
    searchable = expected["page_count"] - len(expected["pages_without_text"])

    assert probed.pages_with_text == searchable
    assert probed.searchable_ratio == pytest.approx(searchable / expected["page_count"])


def test_the_text_is_verbatim_and_complete(probed):
    """Every line the generator printed, in reading order, with nothing added or dropped.

    Stronger than "the text is non-empty": it is the only check that would catch a layout mode
    that silently reorders a table, which is the failure `page_texts` uses layout mode to avoid.
    """
    for page in probed.pages:
        printed = [line for line in page.text.splitlines() if line.strip()]
        assert printed == list(generator.expected_text(page.page_no)), f"page {page.page_no}"


def test_crop_trap_full_text_extracted(probed, expected, synthetic_pdf):
    """F15 — a code is never invisible because it was cropped away.

    Page 20 prints `EAO 84-5140.0020` below the footer. Render the top 55 % of that sheet and the
    code is not in the raster; the probe reads the **full** page, so it is in the text regardless.
    """
    trap = expected["crop_trap"]
    text = probed.page(trap["page"]).text

    assert trap["label"] in text
    assert trap["bbox_top_fraction"] > trap["region"][3], "the crop must actually cut the label off"

    cropped = render.render_page(synthetic_pdf, trap["page"], dpi=DPI_ANSWER,
                                 region=trap["region"])
    full = render.render_page(synthetic_pdf, trap["page"], dpi=DPI_ANSWER)
    assert cropped.height < full.height
    assert cropped.png != full.png


def test_page_texts_never_clips(synthetic_pdf, expected):
    """The same page, extracted through the public helper: still the whole sheet (F15)."""
    trap = expected["crop_trap"]

    texts = probe.page_texts(synthetic_pdf)
    assert len(texts) == expected["page_count"]
    assert trap["label"] in texts[trap["page"] - 1]


def test_the_printed_labels_are_the_files_own(probed, expected):
    """§6.5 — the PDF's `/PageLabels` table, read mechanically. Not a grammar, not a model."""
    assert {str(page.page_no): page.label for page in probed.pages} == expected["printed_labels"]

    first = expected["first_labelled_page"]
    assert probed.page(first).label == "1"
    assert probed.page(first - 1).label != "1"


def test_the_content_hash_is_the_files_bytes(probed, synthetic_pdf, tmp_path):
    """The delta gate: one changed byte re-bills the document, and nothing else does."""
    import hashlib

    assert probed.content_hash == hashlib.sha256(synthetic_pdf.read_bytes()).hexdigest()

    edited = tmp_path / "edited.pdf"
    edited.write_bytes(synthetic_pdf.read_bytes() + b"\n% one more byte\n")
    assert probe.content_hash(edited) != probed.content_hash


def test_s2_input_mode_describes_the_call_that_actually_happens(probed):
    """Register A3 — `impl` returned `render@300` for a mode no code path implemented, inside a
    cache key. Extraction sees rasters at the pinned answer dpi, so this is now a fact."""
    assert probed.s2_input_mode == f"render@{DPI_ANSWER}"


def test_a_page_outside_the_document_raises_rather_than_returning_a_neighbour(probed):
    """§6.4 — returning page 41 for a request for page 43 is how an off-by-one goes unnoticed."""
    with pytest.raises(IndexError):
        probed.page(0)
    with pytest.raises(IndexError):
        probed.page(probed.page_count + 1)


def test_a_document_with_no_text_at_all_probes_and_publishes(tmp_path):
    """F4 — a fully scanned document is `not_searchable`, never quarantined and never an error."""
    scanned = tmp_path / "scanned.pdf"
    with pymupdf.open() as doc:
        for page_no in (1, 2):
            generator.draw_scanned_page(
                doc.new_page(width=generator.PAGE_WIDTH, height=generator.PAGE_HEIGHT), page_no)
        scanned.write_bytes(doc.tobytes(deflate=True, no_new_id=True))

    result = probe.run(scanned)

    assert result.page_count == 2
    assert result.pages_with_text == 0
    assert result.has_text_layer is False
    assert result.searchable_ratio == 0.0
    assert all(page.text_trust == "no_text" for page in result.pages)
