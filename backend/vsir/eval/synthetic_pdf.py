"""The generated M2a corpus: ``data/source/synthetic_3window.pdf`` and its fixture directory.

M2a has to prove the ingest pipeline before a cent is spent, and Spec §12.1 says the way to do that
is a document the repository owns outright. So this module *builds* one, deterministically, with
the four hazards the later units assert against wired into the page geometry rather than described
in a comment:

* **three windows.** 42 pages with three chapter starts at 1, 15 and 29 — over the 30-page cap, so
  Level 0 is out, and chapter-aligned, so Level 1 answers (§6.2). Every fold is a real fold: two
  sections straddle one (pages 13-17 and 27-31), which is what F8 is about.
* **the off-by-one trap (I4, F7).** The PDF's own page-label table numbers the two front-matter
  pages ``i``/``ii`` and restarts at ``1`` on PDF page 3, so *printed label = PDF index − 2* and
  every page's footer prints it. A derivation that drops ``window.start`` from
  ``abs_page = window.start + page_index - 1`` lands on a page whose footer says something else,
  which is exactly the signature §6.4's second check looks for.
* **the crop trap (F15).** Page 20 carries ``EAO 84-5140.0020`` on a line at the very foot of the
  sheet, below the footer. Render the top 55 % of that page and the code is not in the raster —
  but ``ingest/probe.py`` reads the **full** page, so it is in the text either way.
* **the mixed document (register A1).** Pages 1-2 are rasterised — a scanned cover over a
  born-digital body — and pages 3-8 are short, so the first eight pages average well under
  ``BORN_DIGITAL_MIN_CHARS``. `impl` would have called the whole document scanned and thrown away
  40 perfectly extractable pages on a one-line ``else``. This build extracts unconditionally, and
  a test proves it on this file.
* **the reattribution trap (F6).** The frozen S2 response for page 21 reports a code that is
  printed on page **22** — the model read it off the facing sheet. Both pages are inside window 2,
  which is what §6.5 requires for the code to move to the page whose text contains it, with
  ``moved_from`` recorded on the receiving page.
* **the ungrounded code (I2, F14).** Page 30's response carries a code printed on **no** page — a
  misread, which is the ordinary way a vision model gets a character wrong. It must stay put, count
  against that page's ``grounded_rate``, and never become findable in the exact surface.

The frozen S2 responses are what make step 06 replayable at zero cost (D10). They are keyed by
``extract_key``, so they move when the model id, the prompt version, the dpi **or the S2 schema**
moves — re-run this module after any of those, which is the point: an edit to the schema means the
model was asked a different question and its old answer does not contain the new field.

Run it as a process, which is what keeps it inside the image and out of anyone's laptop (§15
Factor XII):

    python -m vsir.eval.synthetic_pdf

It writes the PDF and the replay fixture, and it is idempotent: the same inputs produce the same
bytes, so re-running it on an unchanged tree is a no-op the ``content_hash`` can be checked against.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Sequence

import pymupdf

from vsir.config import DPI_ANSWER

#: A4 at 72 dpi, the PDF user-space unit.
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0

#: The document, as the fixture's own facts describe it.
DOC_STEM = "synthetic_3window"
DOC_TITLE = "C24 SYNTHETIC SAFETY MANUAL"
DOC_REVISION = "1.0"
DOC_TYPE = "safety_function_list"
DOC_SUBJECT = "C24"
DOC_EFFECTIVITY = "from batch 68"
PAGE_COUNT = 42
#: PDF pages 1-2 are front matter labelled i/ii; page 3 prints "1". Hence label = index - 2.
FRONT_MATTER_PAGES = 2
LABEL_OFFSET = -FRONT_MATTER_PAGES

#: The three chapter starts S1 reports and `window.plan` cuts on — 1-based PDF indices.
CHAPTERS = (
    (1, "Front matter and general information"),
    (15, "Safety functions of the C24 cell"),
    (29, "Electrical references and part numbers"),
)
#: ``(first, last, title)``. Two of them cross a window fold on purpose (13-17 over 14|15,
#: 27-31 over 28|29): stitching has to survive that, and F8 is what happens when it does not.
SECTIONS = (
    (1, 2, "Front matter"),
    (3, 8, "General information and symbols"),
    (9, 12, "Machine layout and access points"),
    (13, 17, "Emergency stop chain"),
    (18, 22, "Guard door interlocks"),
    (23, 26, "Two-hand control and enabling devices"),
    (27, 31, "Light curtain muting"),
    (32, 36, "Safety relay wiring"),
    (37, 42, "Part numbers and suppliers"),
)
#: Rasterised, so PyMuPDF extracts "" from them: the scanned cover of the mixed document.
SCANNED_PAGES = (1, 2)
#: Short enough that pages 1-8 average below the born-digital threshold — the A1 trap.
SHORT_PAGES = tuple(range(3, 9))

#: Page 20's foot. Rendered below the footer, outside the top 55 % of the sheet.
CROP_TRAP_PAGE = 20
CROP_TRAP_LABEL = "EAO 84-5140.0020"
#: The region a naive "read the top of the page" crop would use, normalised (§7.3 `region`).
CROP_TRAP_REGION = (0.0, 0.0, 1.0, 0.55)

#: Where the body text starts and how far apart its lines sit, in points from the top.
_BODY_TOP = 96.0
_BODY_LEADING = 16.0
_LEFT_MARGIN = 56.0
#: The footer prints the page's own label — the independent observation §6.4's second check uses.
_FOOTER_Y = 800.0
_TRAP_Y = 822.0
_FONT = "helv"
_BODY_SIZE = 10.0
_HEADING_SIZE = 12.0
#: The scanned pages are rendered at a low dpi and in grey: it is a fixture, and a 20 MB one would
#: be checked into git forever.
_SCAN_DPI = 110

_SF_SUFFIXES = ("A", "a", "B", "b", "C")


def printed_label(page_no: int) -> str:
    """The label the PDF's own ``/PageLabels`` table gives this 1-based PDF page."""
    if page_no <= FRONT_MATTER_PAGES:
        return "i" * page_no
    return str(page_no + LABEL_OFFSET)


def chapter_of(page_no: int) -> tuple[int, str]:
    """``(ordinal, title)`` of the chapter this page falls in — 1-based ordinal."""
    found = 1, CHAPTERS[0][1]
    for ordinal, (start, title) in enumerate(CHAPTERS, start=1):
        if page_no >= start:
            found = ordinal, title
    return found


def section_of(page_no: int) -> str:
    for first, last, title in SECTIONS:
        if first <= page_no <= last:
            return title
    raise ValueError(f"page {page_no} is in no section: the table must cover the document")


def _codes(page_no: int) -> dict[str, str]:
    """The codes printed on one page. Deterministic in the page number, and mostly unique to it."""
    chapter, _ = chapter_of(page_no)
    return {
        "sf": f"SF {chapter}.{page_no}{_SF_SUFFIXES[page_no % len(_SF_SUFFIXES)]}",
        "k": f"K{100 + page_no}",
        "b": f"B{200 + page_no}",
        "si": f"SI{1 + page_no % 4}",
        "q": f"Q{50 + page_no}",
        "s": f"S{300 + page_no}",
        "eao": f"EAO 84-5140.{1000 + page_no:04d}",
    }


def body_lines(page_no: int) -> tuple[str, ...]:
    """The page's text, as a person would read it top to bottom. The footer is added separately."""
    if page_no in SCANNED_PAGES:
        return ()
    code = _codes(page_no)
    if page_no in SHORT_PAGES:
        return (section_of(page_no), f"{code['k']} - {code['si']}")
    _, chapter_title = chapter_of(page_no)
    return (
        chapter_title,
        section_of(page_no),
        f"{code['sf']}) {_purpose(page_no)} ---> Category 3 PL=D Reached",
        f"{code['b']} --> {code['k']} - {code['si']}",
        "(B&R X20SI4100 - Safe Dig. In.- 2 channel wiring)",
        f"{code['q']}  (TELEMECANIQUE LC1-D38BL)",
        f"{code['s']} (Emergency stop button in control panel)",
        f"{code['eao']}   SCHNEIDER ZB4-BS844",
        f"The stop category is verified at commissioning and after",
        f"every replacement of {code['k']} on the {section_of(page_no).lower()}.",
    )


def _purpose(page_no: int) -> str:
    """A one-line description that differs page by page, so no two pages read the same."""
    return f"{section_of(page_no).upper()} STAGE {page_no + LABEL_OFFSET}"


def footer(page_no: int) -> str:
    """Printed at the foot of every page, and outside the crop trap's region on purpose."""
    return f"Page {printed_label(page_no)} of {PAGE_COUNT + LABEL_OFFSET}   ·   " \
           f"{DOC_TITLE}   ·   rev {DOC_REVISION}   ·   {DOC_EFFECTIVITY}"


def expected_text(page_no: int) -> tuple[str, ...]:
    """Every line the text layer of this page carries, in reading order."""
    if page_no in SCANNED_PAGES:
        return ()
    lines = [*body_lines(page_no), footer(page_no)]
    if page_no == CROP_TRAP_PAGE:
        lines.append(CROP_TRAP_LABEL)
    return tuple(lines)


def _draw_text_page(page: pymupdf.Page, page_no: int) -> None:
    lines = body_lines(page_no)
    heading = 1 if page_no not in SHORT_PAGES else 0
    for index, line in enumerate(lines):
        size = _HEADING_SIZE if index < heading else _BODY_SIZE
        page.insert_text((_LEFT_MARGIN, _BODY_TOP + index * _BODY_LEADING), line,
                         fontname=_FONT, fontsize=size)
    page.insert_text((_LEFT_MARGIN, _FOOTER_Y), footer(page_no), fontname=_FONT, fontsize=8.0)
    if page_no == CROP_TRAP_PAGE:
        page.insert_text((_LEFT_MARGIN, _TRAP_Y), CROP_TRAP_LABEL, fontname=_FONT, fontsize=9.0)


def _scan_lines(page_no: int) -> tuple[str, ...]:
    """What the rasterised front matter *shows*. None of it reaches a text layer — that is the
    point: these pages are the scanned cover a mixed document starts with."""
    if page_no == 1:
        return (DOC_TITLE, f"Revision {DOC_REVISION}", f"Valid {DOC_EFFECTIVITY}",
                "SCANNED COVER SHEET - NO TEXT LAYER")
    return ("This sheet was photocopied onto the front of the manual.",
            "It carries no text layer, so nothing on it can be verified.",
            "There is no OCR anywhere in this system (Spec §2.2).")


def draw_scanned_page(target: pymupdf.Page, page_no: int) -> None:
    """Draw the sheet in a scratch document, rasterise it, and paste the pixels back.

    A scan is pixels. Rendering the text and inserting the *image* is the only way to build a page
    that genuinely has no text layer — writing white text or omitting the text would give a page
    that is blank rather than one that is unreadable, and those two behave differently at every
    later step.
    """
    with pymupdf.open() as scratch:
        sheet = scratch.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        for index, line in enumerate(_scan_lines(page_no)):
            sheet.insert_text((_LEFT_MARGIN, 200.0 + index * 24.0), line,
                              fontname=_FONT, fontsize=14.0)
        pixels = sheet.get_pixmap(dpi=_SCAN_DPI, colorspace=pymupdf.csGRAY)
    target.insert_image(pymupdf.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT), pixmap=pixels)


def toc_entries() -> tuple[dict[str, object], ...]:
    """The chapter list S1 reports for this document, in the shape `window.plan` consumes."""
    return tuple({"title": title, "page_no": start} for start, title in CHAPTERS)


def build_document() -> pymupdf.Document:
    """The PDF in memory. Metadata dates are fixed so two builds produce the same bytes."""
    doc = pymupdf.open()
    for page_no in range(1, PAGE_COUNT + 1):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        if page_no in SCANNED_PAGES:
            draw_scanned_page(page, page_no)
        else:
            _draw_text_page(page, page_no)
    doc.set_metadata({
        "title": DOC_TITLE,
        "author": "vsir.eval.synthetic_pdf",
        "subject": DOC_SUBJECT,
        "keywords": "synthetic,m2a,fixture",
        "creator": "vsir",
        "producer": "vsir.eval.synthetic_pdf",
        "creationDate": "D:20260101000000Z",
        "modDate": "D:20260101000000Z",
    })
    # The label table is the printed numbering, and it is what makes the off-by-one trap real
    # rather than notional: `i`, `ii`, then a restart at 1 on PDF page 3.
    doc.set_page_labels([
        {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
        {"startpage": FRONT_MATTER_PAGES, "prefix": "", "style": "D", "firstpagenum": 1},
    ])
    # A real manual has bookmarks. v1 does not read them for the ladder — that is register A6, and
    # §20.1 leaves it open — so they are here for fidelity, not as an input to anything.
    doc.set_toc([[1, title, start] for start, title in CHAPTERS])
    return doc


def write_pdf(destination: Path) -> bytes:
    """Build and write the PDF; return its bytes.

    ``no_new_id=True`` is what makes the build reproducible: without it PyMuPDF mints a fresh
    ``/ID`` on every save, the file hash changes, and with it ``facts_key`` and the name of the
    frozen S1 response beside it. A fixture whose identity changes every time it is regenerated is
    not a fixture. The file is only rewritten when its bytes differ, so a re-run on an unchanged
    tree touches nothing.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with build_document() as doc:
        data = doc.tobytes(deflate=True, garbage=4, no_new_id=True)
    if not destination.exists() or destination.read_bytes() != data:
        destination.write_bytes(data)
    return data


def document_facts() -> dict[str, object]:
    """The frozen S1 response for this document (§6.1 step 04), as the fixture replays it.

    It is what a generalised S1 prompt would return from the front matter: the title and the
    effectivity copied verbatim off the cover, the languages, and the chapter list that picks the
    ladder. Nothing here is derived from the page *content* by a rule — it is a recorded answer.
    """
    return {
        "title": DOC_TITLE,
        "revision": DOC_REVISION,
        "doc_type": DOC_TYPE,
        "subjects": [DOC_SUBJECT],
        "lang": ["en"],
        "effectivity_basis": DOC_EFFECTIVITY,
        "toc": [dict(entry) for entry in toc_entries()],
    }


# ── the frozen S2 responses (step 06, D10) ──────────────────────────────────────────────────────
#
# What a generalised S2 prompt would return for these rasters, recorded rather than derived by a
# rule: this is a *fixture*, so it is a transcript of an answer, and the pipeline reading it must
# not be able to tell it apart from a live one. Everything below is deterministic in the page
# number for exactly one reason — the corpus has to be reproducible byte for byte (§16).

#: The bare part numbers printed on every full page, in reading order. Reported without the vendor
#: name because the vendor name is not part of the code: "B&R X20SI4100" prints a manufacturer and
#: a part, and §5.2's instruction is to copy the code verbatim, not the line it sits on.
VENDOR_CODES = ("X20SI4100", "LC1-D38BL", "ZB4-BS844")

#: The reattribution trap (F6, §6.5). Page 21's response carries page 22's ``K`` code — the model
#: read it off the facing sheet. Both pages are inside window 2 (15-28), which is the condition
#: §6.5 puts on the move: a code only travels to a page whose text contains it, and only within
#: the window that saw both.
REATTRIBUTED_PAGE = 21
REATTRIBUTED_FROM_PAGE = 22

#: The ungrounded code (I2, F14). Printed on no page of this document: a misread, which is the
#: ordinary way a vision model gets a character wrong. It must stay on page 30, count against that
#: page's ``grounded_rate``, and never become findable in the exact surface.
UNGROUNDED_PAGE = 30
UNGROUNDED_CODE = "K999"

#: Which §5.2 page kind each section reads as. Eight kinds describe a *sheet of paper*, so this
#: table is a property of how the fixture is drawn, not a taxonomy of any corpus.
SECTION_PAGE_KINDS = MappingProxyType({
    "Safety relay wiring": "schematic",
    "Part numbers and suppliers": "table",
})


def page_kind_of(page_no: int) -> str:
    """One of §5.2's eight, as a model would read this sheet."""
    if page_no == 1:
        return "cover"
    if page_no in SCANNED_PAGES:
        return "prose"
    return SECTION_PAGE_KINDS.get(section_of(page_no), "prose")


def page_codes(page_no: int) -> tuple[str, ...]:
    """Every code the model reports on this page, in reading order — verbatim, unsorted.

    Not deduplicated and not sorted, because §5.2 is explicit that the response is verbatim and
    unclassified: sorting is the first step toward normalising, and `impl`'s prompt says why in one
    line — a one-character change names a different component.
    """
    if page_no in SCANNED_PAGES:
        return ()
    code = _codes(page_no)
    if page_no in SHORT_PAGES:
        return (code["k"], code["si"])
    reported = [code["sf"], code["b"], code["k"], code["si"], VENDOR_CODES[0], code["q"],
                VENDOR_CODES[1], code["s"], code["eao"], VENDOR_CODES[2]]
    if page_no == CROP_TRAP_PAGE:
        reported.append(CROP_TRAP_LABEL)
    if page_no == REATTRIBUTED_PAGE:
        reported.append(_codes(REATTRIBUTED_FROM_PAGE)["k"])
    if page_no == UNGROUNDED_PAGE:
        reported.append(UNGROUNDED_CODE)
    return tuple(reported)


def page_summary(page_no: int) -> str:
    """2-3 sentences on what is SPECIFIC to this page (§5.2's binding prompt rule, D5).

    Specific, and provably so: every sentence names this page's own label and its own codes, so no
    two pages of the fixture get the same summary. A generic description would make every page's
    dense vector look like every other page's and the `captions` surface stop discriminating at
    all, which is the surface D2 keeps because this field finally gives it content.
    """
    label = printed_label(page_no)
    if page_no == 1:
        return ("This is the scanned cover sheet of the manual. It shows the title, the revision "
                "and the validity statement, and it carries no text layer at all.")
    if page_no in SCANNED_PAGES:
        return ("This sheet was photocopied onto the front of the manual and carries no text "
                "layer. It states that nothing printed on it can be verified against extracted "
                "text.")
    code = _codes(page_no)
    section = section_of(page_no)
    if page_no in SHORT_PAGES:
        return (f"Page {label} is a short reference sheet in the {section.lower()} section. It "
                f"carries only {code['k']} and {code['si']}.")
    return (f"Page {label} covers {_purpose(page_no).lower()} within the {section.lower()} "
            f"section. It names {code['k']} as the monitored relay, {code['si']} as the safe "
            f"input channel and {code['q']} as the contactor, with the two-channel wiring printed "
            f"beside them. The stop category is recorded as verified at commissioning and after "
            f"every replacement of {code['k']}.")


def page_topics(page_no: int) -> tuple[str, ...]:
    """A few short lowercase labels for what the page is about (§5.2)."""
    if page_no == 1:
        return ("cover sheet", "revision")
    if page_no in SCANNED_PAGES:
        return ("front matter",)
    section = section_of(page_no).lower()
    if page_no in SHORT_PAGES:
        return (section, "reference")
    return (section, "wiring", "stop category")


def page_form(page_no: int, *, window_start: int) -> dict[str, object]:
    """One ``PageOut``, as the model would return it for this sheet.

    ``page_index`` is **window-local**: the excerpt's first page is 1 whatever the document calls
    it, which is the whole reason §6.4's offset proof exists. The printed label is left empty on
    the scanned sheets because nothing is printed on them — their ``i``/``ii`` comes from the PDF's
    own label table, which is the text layer's evidence and not the model's (§6.5).
    """
    return {
        "page_index": page_no - window_start + 1,
        "printed_page_no": "" if page_no in SCANNED_PAGES else printed_label(page_no),
        "page_kind": page_kind_of(page_no),
        "lang": ["en"],
        "sections": [{"title": section_of(page_no),
                      "is_start": any(first == page_no for first, _, _ in SECTIONS)}],
        "summaries": [{"lang": "en", "text": page_summary(page_no)}],
        "codes": list(page_codes(page_no)),
        "topics": list(page_topics(page_no)),
    }


def window_out(start: int, end: int) -> dict[str, object]:
    """One ``WindowOut`` for the inclusive PDF page range ``start..end``."""
    return {"pages": [page_form(page_no, window_start=start)
                      for page_no in range(start, end + 1)]}


def window_body(start: int, end: int) -> str:
    """The verbatim response body, as it is frozen into the fixture.

    Indented and key-sorted so a reviewer can read the diff when the corpus is regenerated. That
    formatting is part of the body and therefore part of what replay serves — which is correct:
    the body is the receipt, and reformatting a receipt for display makes it somebody's summary.
    """
    return json.dumps(window_out(start, end), indent=2, sort_keys=True) + "\n"


def _trap_top_fraction(pdf: Path) -> float:
    """Where the crop-trap label actually sits on the sheet, measured from the built file.

    Recorded rather than asserted from ``_TRAP_Y``: the constant is a text *baseline* and what
    matters is the glyph box, so the honest number is the one the finished PDF reports.
    """
    with pymupdf.open(pdf) as doc:
        page = doc[CROP_TRAP_PAGE - 1]
        boxes = page.search_for(CROP_TRAP_LABEL)
        if len(boxes) != 1:
            raise ValueError(f"the crop trap must appear exactly once on page {CROP_TRAP_PAGE}, "
                             f"found {len(boxes)}")
        return round(boxes[0].y0 / page.rect.height, 6)


def expected_table(pdf: Path, *, page_hashes: Sequence[str]) -> dict[str, object]:
    """The acceptance numbers for this corpus, checked in beside it so none can be re-baselined.

    Spec §12.3's table is absolute, not comparative (C10). The same rule applies here: the demo and
    the L1 suite read these numbers, they do not compute them.
    """
    return {
        "doc_id": "synthetic-3window",
        "revision": DOC_REVISION,
        "page_count": PAGE_COUNT,
        "windows": [[1, 14], [15, 28], [29, 42]],
        "ladder_level": 1,
        "pages_without_text": list(SCANNED_PAGES),
        "label_offset": LABEL_OFFSET,
        "first_labelled_page": FRONT_MATTER_PAGES + 1,
        "printed_labels": {str(n): printed_label(n) for n in range(1, PAGE_COUNT + 1)},
        "mixed_document": {
            "sample_pages": 8,
            "born_digital_min_chars": 150,
            "comment": "pages 1-8 average below the threshold; impl would extract nothing (A1)",
        },
        "crop_trap": {
            "page": CROP_TRAP_PAGE,
            "label": CROP_TRAP_LABEL,
            "region": list(CROP_TRAP_REGION),
            # The label's own top edge, as a fraction of the page. Below the region's bottom edge,
            # which is what makes the crop a real crop rather than a described one (F15).
            "bbox_top_fraction": _trap_top_fraction(pdf),
        },
        "sections": [{"first": a, "last": b, "title": t} for a, b, t in SECTIONS],
        "straddling_sections": ["Emergency stop chain", "Light curtain muting"],
        "render": {"dpi": DPI_ANSWER, "page_sha256": list(page_hashes)},
        "extraction": {
            "windows": 3,
            "page_forms": PAGE_COUNT,
            "page_kinds": {str(n): page_kind_of(n) for n in range(1, PAGE_COUNT + 1)},
            "codes_per_page": {str(n): len(page_codes(n)) for n in range(1, PAGE_COUNT + 1)},
            # F6: the code the model read off the facing sheet, and where it is really printed.
            "reattribution": {
                "page": REATTRIBUTED_PAGE,
                "code": _codes(REATTRIBUTED_FROM_PAGE)["k"],
                "from_page": REATTRIBUTED_FROM_PAGE,
            },
            # I2/F14: reported by the model, printed nowhere. Must never become findable.
            "ungrounded": {"page": UNGROUNDED_PAGE, "code": UNGROUNDED_CODE},
        },
    }


def _page_hashes(pdf: Path) -> list[str]:
    # Imported here rather than at module scope: this module is the *producer* of the corpus the
    # pipeline consumes, and a top-level import would make the two circular in the reader's head.
    from vsir.ingest import render

    return [render.render_page(pdf, n, dpi=DPI_ANSWER).sha256 for n in range(1, PAGE_COUNT + 1)]


def build(source_dir: Path, fixture_dir: Path, *, vlm_model: str, prompt_version: str) -> dict:
    """Write the PDF, the frozen S1 and S2 responses, and the acceptance table. Returns a report.

    The keys are computed with the pipeline's own functions rather than re-derived here, which is
    the only way a fixture and the code that reads it can be guaranteed to agree: if
    ``extract_key``'s inputs change, this module writes the responses under the new names on the
    next run and the old ones stop being found — a typed ``fixture_miss`` rather than a stale hit.
    """
    from vsir.ingest import extract as extract_module
    from vsir.ingest import probe as probe_module
    from vsir.ingest import window as window_module
    from vsir import vlm

    pdf = source_dir / f"{DOC_STEM}.pdf"
    data = write_pdf(pdf)
    content_hash = probe_module.content_hash(pdf)

    facts_key = vlm.facts_key(content_hash, vlm_model=vlm_model, prompt_version=prompt_version)
    facts_path = vlm.write(fixture_dir, vlm.FACTS, facts_key,
                           json.dumps(document_facts(), indent=2, sort_keys=True) + "\n")

    page_hashes = _page_hashes(pdf)
    plan = window_module.plan(PAGE_COUNT, toc=toc_entries(), size_bytes=len(data),
                              document=DOC_STEM)
    extract_keys: dict[str, str] = {}
    for window in plan.windows:
        key = vlm.extract_key(
            page_hashes[window.start - 1:window.end],
            vlm_model=vlm_model, prompt_version=prompt_version, dpi=DPI_ANSWER,
            schema_hash=extract_module.S2_SCHEMA_HASH,
        )
        vlm.write(fixture_dir, vlm.EXTRACT, key, window_body(window.start, window.end))
        extract_keys[f"{window.start}-{window.end}"] = key

    expected_path = fixture_dir / "expected.json"
    expected_path.write_text(
        json.dumps(expected_table(pdf, page_hashes=page_hashes), indent=2, sort_keys=True) + "\n"
    )
    return {
        "pdf": str(pdf),
        "bytes": len(data),
        "content_hash": content_hash,
        "facts_key": facts_key,
        "facts": str(facts_path),
        "extract_keys": extract_keys,
        "s2_schema_hash": extract_module.S2_SCHEMA_HASH,
        "expected": str(expected_path),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vsir.eval.synthetic_pdf",
        description="Generate data/source/synthetic_3window.pdf and its replay fixture.",
    )
    root = _repo_root()
    parser.add_argument("--source-dir", type=Path, default=root / "data" / "source")
    parser.add_argument("--fixture-dir", type=Path,
                        default=root / "data" / "fixtures" / DOC_STEM)
    parser.add_argument("--vlm-model", default="", help="defaults to VSIR_VLM_MODEL")
    parser.add_argument("--prompt-version", default="", help="defaults to VSIR_PROMPT_VERSION")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from vsir.config import load_config

    cfg = load_config()
    report = build(
        args.source_dir, args.fixture_dir,
        vlm_model=args.vlm_model or cfg.vlm_model,
        prompt_version=args.prompt_version or cfg.prompt_version,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - the module is a process, and this is its entry
    sys.exit(main())
