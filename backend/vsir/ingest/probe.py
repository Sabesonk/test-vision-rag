"""Step 02 — the text layer. **The only writer of the `text` payload field (I2).**

Ported from ``impl/app/textlayer.py``: :func:`probe`, :func:`page_texts` and :func:`content_hash`
survive, with their reasoning. What does **not** survive is the second half of that module —
``gate()``, ``backs()``, ``identifiers_from_text()`` and ``token_set()``'s adjacent-token joins.
I2 makes the gate unnecessary (a code is verified by being *in* this text, structurally, not by a
curated allowlist) and Qdrant's phrase matching plus :func:`vsir.core.variants.variants` makes the
joins wrong: `impl` glued adjacent tokens so ``"SF 1.1A"`` could be found as one key, and the new
index finds it as a phrase over the tokens Qdrant itself produced (§5.6, §2.4).

Three properties this module is responsible for, each of which is a failure row somewhere else:

* **Text always comes from the full page, never a crop (F15).** There is no ``clip`` argument
  anywhere below, and the conformance grep keeps ``get_text(`` out of every other module so a
  second extractor cannot appear. A code near the foot of the sheet is in the text even when the
  raster a reader is looking at was cropped above it.
* **Extraction is unconditional (register A1).** `impl` guarded it with
  ``texts = page_texts(path) if pr.has_text_layer else [""] * pr.page_count``, and that one
  ``else`` destroys the text of every *mixed* document — a scanned cover over a born-digital body
  averages below the threshold on an eight-page sample, so 40 extractable pages come back empty
  with nothing raising. ``page_texts()`` already returns ``""`` for a page that has no text layer,
  so the guard never saved anything it did not also cost.
* **``has_text`` is per page, and ``has_text == false`` implies ``text_trust == "no_text"``**
  (§5.3, §5.7). A page's own text layer is what decides whether it can be verified; the
  document-level sample below decides nothing except what gets reported.

**Why there is no OCR.** In this corpus the text layer is not a convenience, it is *evidence*: its
whole job is to answer "is this code really printed on this page?". An OCR layer answers that with
a guess, and in a corpus with thousands of one-character-apart codes a misread ``K73`` would
"verify" a hallucinated ``K73``. A scanned page yielding ``""`` is worse in coverage and better in
truthfulness — it comes back `not_searchable`, which the tools disclose (F4, §2.2).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from vsir.config import DPI_ANSWER
from vsir.core.record import TextTrust

#: R3, §4.2 — PyMuPDF is the single point of truth for exact search, so which one ran is recorded
#: on every page. A version bump is a re-run of the crop and off-by-one fixtures, not a silent one.
PROBE_VERSION = f"pymupdf-{pymupdf.__version__}"

#: Ported from `impl`: the average character count that says "born digital", over a front sample.
#: It no longer gates extraction (A1) — it only describes the document.
BORN_DIGITAL_MIN_CHARS = 150
PROBE_SAMPLE_PAGES = 8


@dataclass(frozen=True)
class PageProbe:
    """One page's text layer. ``page_no`` is the 1-based **absolute** PDF index."""

    page_no: int
    text: str
    label: str

    @property
    def chars(self) -> int:
        return len(self.text.strip())

    @property
    def has_text(self) -> bool:
        """Any character at all. There is no OCR, so every character here came from the file.

        A threshold would be a guess about how much text a page "should" have, and it would make a
        sparse but genuinely born-digital page — a chapter divider, a title sheet — unsearchable
        for no reason. Emptiness is the only honest line, and PyMuPDF returns exactly ``""`` for a
        page whose content is one big image.
        """
        return self.chars > 0

    @property
    def text_trust(self) -> TextTrust:
        """The provisional trust level. ``no_text`` is final; ``ok`` is not.

        Only two of the four values of §5.7 are knowable here, because the other two are a
        judgement about how well the text layer *matches the page*, and that needs the model's
        reading to compare against. Derivation demotes ``ok`` to ``degraded`` or ``untrusted`` from
        ``grounded_rate`` (U009, `core/health.py`); nothing ever promotes ``no_text``.
        """
        return "ok" if self.has_text else "no_text"


@dataclass(frozen=True)
class Probe:
    """The whole document's text layer, plus the fingerprint every cache key is anchored to."""

    page_count: int
    size_bytes: int
    content_hash: str
    pages: tuple[PageProbe, ...]
    probe_version: str = PROBE_VERSION

    def page(self, page_no: int) -> PageProbe:
        """The 1-based page. Raises rather than returning a neighbour — see §6.4."""
        if not 1 <= page_no <= self.page_count:
            raise IndexError(f"page {page_no} is outside 1..{self.page_count}")
        return self.pages[page_no - 1]

    @property
    def texts(self) -> tuple[str, ...]:
        """Every page's text in absolute page order — what derivation joins the model output to."""
        return tuple(page.text for page in self.pages)

    @property
    def pages_with_text(self) -> int:
        return sum(1 for page in self.pages if page.has_text)

    @property
    def searchable_ratio(self) -> float:
        """§5.7 — pages with a text layer ÷ pages. The agent's blind spot, made a number."""
        return self.pages_with_text / self.page_count if self.page_count else 0.0

    @property
    def sample_chars_per_page(self) -> int:
        """`impl`'s front-sample average, kept for reporting. It gates nothing (A1)."""
        sample = self.pages[:PROBE_SAMPLE_PAGES]
        return sum(page.chars for page in sample) // max(1, len(sample))

    @property
    def has_text_layer(self) -> bool:
        """Document level, and deliberately *not* the front-sample average.

        `impl` answered this from the first eight pages and a mixed document came out "scanned".
        Now that every page is probed there is no reason to sample: the document has a text layer
        if any of its pages does, and the per-page answer is what anything downstream uses.
        """
        return self.pages_with_text > 0

    @property
    def s2_input_mode(self) -> str:
        """What S2 actually receives, and it is the same for every document (§6.1 step 06).

        Kept from `impl` (§2.4) but made truthful. `impl` returned ``"render@300"`` for a scanned
        document and there was no 300 dpi path anywhere in the system — register A3, a claim the
        code could not honour, sitting inside a cache key. Extraction now always sees rendered
        rasters at the pinned answer dpi, so this describes the call rather than guessing at it,
        and ``extract_key`` names the ``dpi`` directly instead of naming a mode (§6.3).
        """
        return f"render@{DPI_ANSWER}"


def content_hash(path: Path) -> str:
    """SHA-256 of the file's bytes — the delta gate for the whole system.

    Change one byte of the PDF and every cache key anchored here changes with it, which re-bills
    the document exactly when it should be re-billed and never otherwise (§6.3).
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> tuple[list[str], list[str]]:
    """One pass over the file: every page's text and every page's label.

    `impl` opened the PDF three times for this (``probe``, ``page_texts``, ``render_pdf``) and its
    own register says one pass would do (A2). Opening once also removes a way for the two lists to
    disagree about how many pages there are.
    """
    with pymupdf.open(path) as doc:
        texts, labels = [], []
        for page in doc:
            # **No ``clip``.** The whole page, always (F15).
            texts.append(page.get_text("text", flags=pymupdf.TEXT_PRESERVE_WHITESPACE))
            labels.append(page.get_label() or "")
    return texts, labels


def page_texts(path: Path) -> list[str]:
    """Verbatim text per page, in **layout mode**. Ported as-is, including the reason.

    Layout mode is not cosmetic. PDF stores text as positioned runs with no notion of columns, so
    the default reading order flattens tables: on `impl`'s safety-function list the role header row
    came back as one detached run — ``INPUT INPUT LOGIC LOGIC LOGIC LOGIC OUTPUT`` — severed from
    the tags beneath it, which is the same failure the graph team predicted for the PLC I/O card
    tables. ``TEXT_PRESERVE_WHITESPACE`` keeps the column structure.
    """
    return _read(Path(path))[0]


def page_labels(path: Path) -> list[str]:
    """The PDF's own ``/PageLabels`` table, one entry per page, ``""`` where the file declares none.

    A mechanical readout of a structure the file carries — not a grammar, not a model reading, and
    not something derived from the page's content. It is the strongest form of §6.5's
    "text-layer-confirmed label", and it exists here so the demo and derivation have a printed
    label to check the model's ``printed_page_no`` against without inventing a rule for one.
    """
    return _read(Path(path))[1]


def run(path: str | Path) -> Probe:
    """Probe a PDF: the fingerprint, and every page's text and label. One pass, no branches."""
    source = Path(path)
    texts, labels = _read(source)
    return Probe(
        page_count=len(texts),
        size_bytes=source.stat().st_size,
        content_hash=content_hash(source),
        pages=tuple(
            PageProbe(page_no=index, text=text, label=labels[index - 1])
            for index, text in enumerate(texts, start=1)
        ),
    )
