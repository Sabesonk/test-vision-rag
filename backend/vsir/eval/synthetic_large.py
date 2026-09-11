"""The generated M8 corpus: ``data/source/synthetic_large.pdf`` and its replay fixture.

M8 has to prove three things that only a *long* run can show — that a `SIGTERM` mid-extraction
loses at most one window, that `--resume` finishes without re-billing what the killed run already
bought, and that a document with no structure to cut on still plans (U025). Spec §13 M8 says which
document to prove them on, and says it twice: **a generated large PDF, not the 1,440-page manual**.
§6.2 adds the reason in one line — *"the manual now ingests, but a resume test wants a
deterministic corpus, not a large one."*

So this module builds one, on the same terms as :mod:`vsir.eval.synthetic_pdf`: deterministic
bytes, a frozen S1 and one frozen S2 response per window, and an acceptance table checked in
beside them so no number can be re-baselined by the code under test (C10).

It differs from the M2a corpus in exactly one way that matters, and it is the reason it exists as
a second corpus rather than as more pages of the first:

* **it declares no contents page.** ``toc: []``, so :func:`vsir.ingest.window.plan` has no chapter
  boundary to cut on and lands on **Level 2** — the fold at the cap that `fixes/001` restored to
  v1 after the exclusion refused 48 % of the real corpus (§2.5, §6.2). 150 pages at a 30-page cap
  is five windows of exactly thirty, which is both the ≥ 3 window checkpoints U025's acceptance
  asks for and the only place in the tree where the Level 2 rung is exercised end to end.

Everything else is deliberately plain. There is no off-by-one trap, no crop trap, no
reattribution, no ungrounded code and no scanned page: M2a's corpus carries all six and proves
them, and repeating them here would mean a resume test that fails for a reason that has nothing
to do with resuming. Every page is born-digital, every reported code is printed on the page that
reports it, and every page's footer prints its own number — so the document publishes cleanly and
what a kill interrupts is the only variable.

The printed label **is** the PDF index here, for the same reason: §6.4's offset proof is M2a's to
make, and this corpus's job is to be long, not to be tricky. The proof still runs — check (2)
matches model-read labels against their own page's text on all 150 pages — it simply has no trap
to catch.

Run it as a process, which is what keeps it inside the image and out of anyone's laptop (§15
Factor XII):

    python -m vsir.eval.synthetic_large

It writes the PDF and the replay fixture, and it is idempotent: the same inputs produce the same
bytes, so re-running it on an unchanged tree is a no-op.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

import pymupdf

from vsir.config import DPI_ANSWER

#: A4 at 72 dpi, the PDF user-space unit — the same sheet the M2a corpus uses.
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0

DOC_STEM = "synthetic_large"
DOC_TITLE = "L90 CELL MAINTENANCE COMPENDIUM"
DOC_REVISION = "1.3"
DOC_TYPE = "manual"
DOC_SUBJECT = "L90"
DOC_EFFECTIVITY = "from batch 41"

#: 150 pages at the 30-page cap is five windows. Five, and not four or three, because U025's
#: acceptance wants *at least three* checkpoints and a kill has to be able to land in the middle
#: of the run rather than at either end of it — the interesting case is a resume that has both
#: finished windows behind it and unstarted ones in front.
PAGE_COUNT = 150

#: **No contents page.** The one property this corpus has that M2a's does not, and the whole
#: reason it plans at Level 2. An empty tuple rather than an omitted constant so the absence is
#: something a reader can see and a test can name.
TOC: tuple[dict[str, object], ...] = ()

#: Where the body text starts and how far apart its lines sit, in points from the top.
_BODY_TOP = 96.0
_BODY_LEADING = 16.0
_LEFT_MARGIN = 56.0
_FOOTER_Y = 800.0
_FONT = "helv"
_BODY_SIZE = 10.0
_HEADING_SIZE = 12.0

#: The nine subject areas the compendium runs through, **in contiguous blocks**. The corpus has
#: section structure in its *text* while declaring none in its *outline* — which is the shape a
#: vendor catalogue has, and the shape that made the ladder refuse 14 real documents before
#: `fixes/001`.
AREAS = (
    "Hydraulic power unit",
    "Pneumatic supply and lockout",
    "Spindle drive and encoder",
    "Tool changer carousel",
    "Chip conveyor and coolant",
    "Axis lubrication",
    "Enclosure interlocks",
    "Pallet shuttle",
    "Control cabinet cooling",
)

#: Pages per area — **17, and deliberately coprime with the 30-page cap**. The area boundaries
#: then fall at 17, 34, 51, 68, 85, 102, 119 and 136 while the window folds fall at 30, 60, 90
#: and 120, so no boundary coincides with a fold and five of the nine sections straddle one. That
#: is F8 on this corpus: a section reassembled from sightings in two windows that never saw each
#: other, which is exactly what §5.2's deletion of section *extent* made possible and what the
#: Level 2 fold relies on (§6.2).
AREA_PAGES = 17

#: Every twenty-fifth sheet is a parts table rather than prose — enough variety that the
#: `captions` surface has something to discriminate on, and few enough that nothing here needs a
#: table of its own to explain.
_TABLE_EVERY = 25


def area_of(page_no: int) -> str:
    """The subject area of one page: contiguous blocks of :data:`AREA_PAGES`, last one short."""
    return AREAS[min((page_no - 1) // AREA_PAGES, len(AREAS) - 1)]


def printed_label(page_no: int) -> str:
    """This corpus prints its own PDF index. No offset, and the docstring says why."""
    return str(page_no)


def page_kind_of(page_no: int) -> str:
    """One of §5.2's eight, as a model would read this sheet."""
    return "table" if page_no % _TABLE_EVERY == 0 else "prose"


def codes_of(page_no: int) -> dict[str, str]:
    """The codes printed on one page — unique to it, and printed before they are reported."""
    return {
        "m": f"M{1000 + page_no}",
        "hz": f"HZ-{page_no:03d}",
        "p": f"P{7000 + page_no * 3}",
        "t": f"T{page_no % 12 + 1}",
    }


def body_lines(page_no: int) -> tuple[str, ...]:
    """The page's text as a person reads it, top to bottom. The footer is added separately."""
    code = codes_of(page_no)
    area = area_of(page_no)
    if page_kind_of(page_no) == "table":
        return (
            f"{area} — spare parts",
            f"{code['m']}   assembly, complete            1 off",
            f"{code['p']}   seal kit                      2 off",
            f"{code['hz']}  hazard notice, adhesive       1 off",
            f"torque class {code['t']} applies to every fastener listed above.",
        )
    return (
        area,
        f"Procedure {code['m']} — {area.lower()} inspection",
        f"Isolate the unit and confirm {code['hz']} is displayed at the access panel.",
        f"Replace seal set {code['p']} whenever the housing is opened.",
        f"Tighten to torque class {code['t']} and record the value in the log.",
        f"Re-test before release; {code['m']} is not considered complete until the",
        f"reading has been countersigned on the {area.lower()} sheet.",
    )


def footer(page_no: int) -> str:
    """Printed at the foot of every page — §6.4 check (2)'s independent observation."""
    return (f"Page {printed_label(page_no)} of {PAGE_COUNT}   ·   {DOC_TITLE}   ·   "
            f"rev {DOC_REVISION}   ·   {DOC_EFFECTIVITY}")


def expected_text(page_no: int) -> tuple[str, ...]:
    """Every line the text layer of this page carries, in reading order."""
    return (*body_lines(page_no), footer(page_no))


def _draw_page(page: pymupdf.Page, page_no: int) -> None:
    for index, line in enumerate(body_lines(page_no)):
        size = _HEADING_SIZE if index == 0 else _BODY_SIZE
        page.insert_text((_LEFT_MARGIN, _BODY_TOP + index * _BODY_LEADING), line,
                         fontname=_FONT, fontsize=size)
    page.insert_text((_LEFT_MARGIN, _FOOTER_Y), footer(page_no), fontname=_FONT, fontsize=8.0)


def build_document() -> pymupdf.Document:
    """The PDF in memory. Metadata dates are fixed so two builds produce the same bytes.

    **No `set_toc` and no `set_page_labels`.** The M2a corpus sets both; this one sets neither,
    and the omission is the corpus. A bookmark list would not change the plan — v1 does not read
    bookmarks for the ladder, which is register A6 — but leaving one here would make the file
    look structured to a reader who then could not see why it planned at Level 2.
    """
    doc = pymupdf.open()
    for page_no in range(1, PAGE_COUNT + 1):
        _draw_page(doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT), page_no)
    doc.set_metadata({
        "title": DOC_TITLE,
        "author": "vsir.eval.synthetic_large",
        "subject": DOC_SUBJECT,
        "keywords": "synthetic,m8,fixture",
        "creator": "vsir",
        "producer": "vsir.eval.synthetic_large",
        "creationDate": "D:20260101000000Z",
        "modDate": "D:20260101000000Z",
    })
    return doc


def write_pdf(destination: Path) -> bytes:
    """Build and write the PDF; return its bytes. ``no_new_id`` is what makes it reproducible."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with build_document() as doc:
        data = doc.tobytes(deflate=True, garbage=4, no_new_id=True)
    if not destination.exists() or destination.read_bytes() != data:
        destination.write_bytes(data)
    return data


def document_facts() -> dict[str, object]:
    """The frozen S1 response (§6.1 step 04) — and the empty ``toc`` is its whole point.

    This is what a generalised S1 prompt returns from the front matter of a document that has no
    contents page: the title and the effectivity copied verbatim, the language, and **no chapter
    list**, because there is none to read. Everything downstream follows from that one empty
    array — the ladder has nothing to cut on and folds at the cap (§6.2).
    """
    return {
        "title": DOC_TITLE,
        "revision": DOC_REVISION,
        "doc_type": DOC_TYPE,
        "subjects": [DOC_SUBJECT],
        "lang": ["en"],
        "effectivity_basis": DOC_EFFECTIVITY,
        "toc": [dict(entry) for entry in TOC],
    }


# ── the frozen S2 responses (step 06, D10) ──────────────────────────────────────────────────────

def page_summary(page_no: int) -> str:
    """2-3 sentences on what is SPECIFIC to this page (§5.2's binding prompt rule, D5)."""
    code = codes_of(page_no)
    area = area_of(page_no)
    if page_kind_of(page_no) == "table":
        return (f"Page {page_no} is the spare-parts table for the {area.lower()}. It lists "
                f"{code['m']} as the complete assembly and {code['p']} as the seal kit, under "
                f"torque class {code['t']}.")
    return (f"Page {page_no} carries procedure {code['m']} for the {area.lower()}. It requires "
            f"hazard notice {code['hz']} at the access panel and seal set {code['p']} whenever "
            f"the housing is opened, tightened to torque class {code['t']}.")


def page_codes(page_no: int) -> tuple[str, ...]:
    """Every code the model reports on this page, verbatim and in reading order.

    All four are **printed on this page** (see :func:`body_lines`), so every page's
    ``grounded_rate`` is 1.0 and the document publishes. M2a's corpus is where an ungrounded code
    is proved (I2, F14); a resume test that failed its grounded-rate gate would be a resume test
    that proved nothing about resuming.
    """
    code = codes_of(page_no)
    return (code["m"], code["hz"], code["p"], code["t"])


def page_topics(page_no: int) -> tuple[str, ...]:
    return (area_of(page_no).lower(),
            "parts" if page_kind_of(page_no) == "table" else "procedure")


def page_form(page_no: int, *, window_start: int) -> dict[str, object]:
    """One ``PageOut`` as the model would return it. ``page_index`` is **window-local** (§6.4)."""
    return {
        "page_index": page_no - window_start + 1,
        "printed_page_no": printed_label(page_no),
        "page_kind": page_kind_of(page_no),
        "lang": ["en"],
        "sections": [{"title": area_of(page_no),
                      "is_start": area_of(page_no) != area_of(page_no - 1) if page_no > 1
                      else True}],
        "summaries": [{"lang": "en", "text": page_summary(page_no)}],
        "codes": list(page_codes(page_no)),
        "topics": list(page_topics(page_no)),
    }


def window_out(start: int, end: int) -> dict[str, object]:
    """One ``WindowOut`` for the inclusive PDF page range ``start..end``."""
    return {"pages": [page_form(page_no, window_start=start)
                      for page_no in range(start, end + 1)]}


def window_body(start: int, end: int) -> str:
    """The verbatim response body, as it is frozen into the fixture — the receipt, not a summary."""
    return json.dumps(window_out(start, end), indent=2, sort_keys=True) + "\n"


def expected_table(*, windows: Sequence[tuple[int, int]], level: int,
                   extract_keys: dict[str, str], facts_key: str,
                   content_hash: str) -> dict[str, object]:
    """The acceptance numbers for this corpus, checked in beside it so none can be re-baselined.

    Absolute, not comparative (C10). The suite reads ``level: 2`` and ``windows`` from here; it
    does not ask `plan()` what it decided and then agree with it.
    """
    return {
        "doc_id": "synthetic-large",
        # What the **document** says about itself — printed in every footer and reported by S1.
        "printed_revision": DOC_REVISION,
        # What the **manifest** derives, which is what the index is keyed on. §6.1 step 01 takes
        # facets from the filename, the file's metadata and the uploader, and this corpus
        # declares none of them in a filename — so the revision defaults, and the model's
        # reading is kept as a cross-check rather than silently minting a second document.
        "revision": "1.0",
        "doc_type": DOC_TYPE,
        "page_count": PAGE_COUNT,
        "content_hash": content_hash,
        "facts_key": facts_key,
        # Level 2 — the fold at the cap, because `toc` is empty (§6.2, fixes/001). This is the
        # one corpus in the tree that reaches that rung. The key is `ladder_level` because that
        # is what `cli._assertions` reads: the table is a contract with the demo, not a private
        # note, so it uses the demo's names.
        "ladder_level": level,
        "windows": [list(window) for window in windows],
        "extract_keys": dict(extract_keys),
        "toc_entries": len(TOC),
        # Every page is born-digital and every reported code is printed, so the document
        # publishes with no flag and nothing is skipped. The empty list is a claim, not an
        # omission: `_assertions` checks it against the probe on every run.
        "pages_without_text": [],
        "pages_with_text": PAGE_COUNT,
        "searchable_ratio": 1.0,
        "grounded_median": 1.0,
        "codes_per_page": len(page_codes(1)),
        # A code carried by exactly one page — what a `lookup` in the L2 suite pins.
        "unique_code": codes_of(PAGE_COUNT // 2)["m"],
        "unique_code_page": PAGE_COUNT // 2,
    }


def _page_hashes(pdf: Path) -> list[str]:
    # Imported here rather than at module scope, exactly as `synthetic_pdf` does: this module is
    # the *producer* of the corpus the pipeline consumes.
    from vsir.ingest import render

    return [render.render_page(pdf, n, dpi=DPI_ANSWER).sha256 for n in range(1, PAGE_COUNT + 1)]


def build(source_dir: Path, fixture_dir: Path, *, vlm_model: str, prompt_version: str) -> dict:
    """Write the PDF, the frozen S1 and S2 responses, and the acceptance table. Returns a report.

    The keys are computed with the pipeline's own functions rather than re-derived here, which is
    the only way a fixture and the code that reads it can be guaranteed to agree: if
    ``extract_key``'s inputs change, this module writes the responses under the new names on the
    next run and the old ones stop being found — a typed ``fixture_miss`` rather than a stale hit.
    """
    from vsir import vlm
    from vsir.ingest import extract as extract_module
    from vsir.ingest import probe as probe_module
    from vsir.ingest import window as window_module

    pdf = source_dir / f"{DOC_STEM}.pdf"
    data = write_pdf(pdf)
    content_hash = probe_module.content_hash(pdf)

    facts_key = vlm.facts_key(content_hash, vlm_model=vlm_model, prompt_version=prompt_version)
    vlm.write(fixture_dir, vlm.FACTS, facts_key,
              json.dumps(document_facts(), indent=2, sort_keys=True) + "\n")

    page_hashes = _page_hashes(pdf)
    plan = window_module.plan(PAGE_COUNT, toc=TOC, size_bytes=len(data), document=DOC_STEM)
    if plan.level != 2:
        # The corpus exists to reach Level 2. A build that quietly produced a Level 0 or Level 1
        # document would leave `test_ladder_level_2` asserting about a rung it never ran.
        raise ValueError(f"{DOC_STEM} must plan at Level 2 and planned at {plan.level}: the "
                         f"corpus declares no contents page, so the cap is the only boundary")
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
    expected_path.write_text(json.dumps(
        expected_table(windows=[(w.start, w.end) for w in plan.windows], level=plan.level,
                       extract_keys=extract_keys, facts_key=facts_key,
                       content_hash=content_hash),
        indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "pdf": str(pdf),
        "bytes": len(data),
        "content_hash": content_hash,
        "level": plan.level,
        "facts_key": facts_key,
        "extract_keys": extract_keys,
        "s2_schema_hash": extract_module.S2_SCHEMA_HASH,
        "expected": str(expected_path),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vsir.eval.synthetic_large",
        description="Generate data/source/synthetic_large.pdf and its replay fixture.",
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
