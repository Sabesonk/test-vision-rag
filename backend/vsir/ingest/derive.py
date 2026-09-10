"""Step 07 — derivation. Where the two streams meet, and every claim gets checked (§6.1, §6.4-6.5).

Rewritten from ``impl/app/segment.py::to_pages``. Two things have been running side by side since
step 02 and neither has seen the other: PyMuPDF has the **text** of each page, the model has its
**reading** of each page. This step puts the claim next to the evidence.

What is ported is the join and the offset. What is deleted is the gate.

**The offset is the most dangerous line in the pipeline** — get it wrong and every ``page_no``,
``page_id``, citation and summary shifts, and nothing else errors. `impl` computed it correctly and
then *logged a warning and dropped the page* when the index fell outside the window, which is a
silent 1-page hole in a manual. §6.4 requires **two independent checks** instead, and this module
runs both:

1. **structural** — the window returned exactly the indices it was given, ``1..N`` (shared with
   step 06, :func:`vsir.ingest.extract.page_index_problem`, so one function decides it);
2. **independent observation** — a model-read ``printed_page_no`` on a page that has text must be
   printed on **this** page. If it is printed on a neighbour's page instead, that is the
   off-by-one signature: raise :class:`OffsetError` and bisect (§6.2's fourth trigger).

**One observation is no longer enough to raise (fixes/002).** The asymmetry §6.4 assumed — *"a
false positive costs one re-billed window"* — does not hold: :func:`_neighbours_printing` reads the
**whole document**, not the window, so the predicate is invariant under bisection and the repair
reaches the same verdict all the way down to ``window_unsplittable``. Since ``offset_check`` is
blocking and deliberately not overridable, one bare numeral cost the document plus roughly eight
paid windows on the way down. Measured over the real corpus, a single witness fires on 22 pages
across 11 of the 98 documents that declare ``/PageLabels``, and every one is a false positive of
the form ``label '1' printed on [2], not on p1``.

What replaces it is §6.4's own argument, stated exactly. *"A genuine shift moves every page of the
window"* — so under a real shift **no page can confirm its own label**, and a page that does
confirm its own label is direct evidence of alignment that one stray numeral must not outvote.
:func:`check_offset` therefore refuses on :data:`OFFSET_WITNESSES` witnesses, **or** on a single
witness when nothing in the window confirms itself. That keeps every false positive out and keeps
sensitivity even where one page of the window carries the only legible label — the legacy
`TC1E-SF` window, whose other 29 labels are printed nowhere in the projected text.

**The gate is gone (§2.4, §2.5 B).** `impl` classified every identifier against nine regexes, kept
the ones a curated allowlist backed, and wrote the rest to `withheld.jsonl`. None of that is here:
no identifier grammar, no ``classify``, no ``key_for_unit``, no keyword list, no ``class_totality``
page-unit, no merge of text-harvested identifiers into the model's. I2 makes it unnecessary — a
code is findable because it is **in the page's `text`**, which `ingest/probe.py` alone writes, and
nothing the model says can put it there. What survives of the gate's *purpose* is a **number**:
``grounded_rate``, plus the ``codes_in_text`` list C8 promises Part A, both computed structurally
in `core/health.py`.

**Reattribution (F6).** Attention bleeds across a fold: a code the model reports on page *i*
sometimes belongs to *i±1*. Where the code is absent from *i*'s text and present in exactly one
adjacent page's text **within the same window**, the sighting moves there and ``moved_from``
records where it came from. Where it is printed nowhere it stays put, counts against *i*'s
``grounded_rate``, and never enters the exact surface — because the exact surface is `text`, and
the model never writes `text`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from vsir import logging as vsir_logging
from vsir.config import DPI_ANSWER
from vsir.core import health, ids
from vsir.core.exact import printed_in
from vsir.core.record import (MovedCode, PageContent, PageRecord, Provenance, Summary, TextTrust)
from vsir.core.tok import tok
from vsir.ingest.extract import Extraction, PageOut, WindowExtraction, page_index_problem, page_kind
from vsir.ingest.manifest import Manifest
from vsir.ingest.probe import Probe
from vsir.ingest.window import Window, WindowError, bisect_window

_log = vsir_logging.get_logger(__name__)

#: The §6.2 trigger an offset failure bisects under. Named here so the reason a window was split
#: is the same string in the log, the run record and `extract.py`'s own bisection path.
OFFSET = "offset"

#: How many pages of one window must show the off-by-one signature for §6.4 check (2) to raise on
#: witnesses alone (fixes/002). Two, because a false positive is isolated by nature: a lone
#: witness is a bare numeral that happens to occur on a neighbour's sheet.
#:
#: This is the *sufficient* count, not the only route to a refusal — a single witness still
#: refuses when no page of the window confirms its own label, which is what a real shift looks
#: like at any window size. See :func:`check_offset`.
#:
#: Not configurable: a threshold an operator can lower to 1 is the bug this closed, and one they
#: can raise is a shift the pipeline agrees to miss.
OFFSET_WITNESSES = 2

#: The disclosure flags derivation can put on a page. A closed list, because a flag nothing sets
#: and a flag nothing reads are the same bug and only one of them is visible.
FLAG_NO_TEXT = "no_text"
FLAG_UNGROUNDED_CODES = "ungrounded_codes"
FLAG_CODES_REATTRIBUTED = "codes_reattributed"
FLAG_AMBIGUOUS_REATTRIBUTION = "ambiguous_reattribution"
FLAG_LABEL_AMBIGUOUS = "label_ambiguous"
FLAG_LABEL_INTERPOLATED = "label_interpolated"
DERIVE_FLAGS: tuple[str, ...] = (FLAG_NO_TEXT, FLAG_UNGROUNDED_CODES, FLAG_CODES_REATTRIBUTED,
                                 FLAG_AMBIGUOUS_REATTRIBUTION, FLAG_LABEL_AMBIGUOUS,
                                 FLAG_LABEL_INTERPOLATED)


class OffsetError(WindowError):
    """§6.4 — the window's pages are not the pages it was given (I4).

    A :class:`~vsir.ingest.window.WindowError` because it is one: the repair is §6.2's, bisect and
    re-bill, and the CLI already turns that family into a named non-zero refusal. It carries its
    own class and code so an operator can tell "the model answered about the wrong pages" apart
    from "the model's answer did not parse".
    """

    code = "offset_check_failed"


@dataclass(frozen=True)
class SectionSighting:
    """*"This page belongs to this section"* — presence, never extent (§5.2).

    Carries the **canonical key** rather than only the title, because that key is what makes a
    section survive a window fold: two calls that never saw each other reported the same section
    and stitching has to recognise it as one (§6.1 step 08, F8).
    """

    page_no: int
    title: str
    key: str
    is_start: bool


@dataclass(frozen=True)
class Move:
    """One code that changed pages (§6.5, F6). Kept beside the records for the log and the demo."""

    code: str
    from_page_no: int
    to_page_no: int
    window: tuple[int, int]


@dataclass(frozen=True)
class Label:
    """A page's printed label and how much it may be believed (§6.5).

    ``candidates`` is non-empty **only** when the page carries two readings it cannot arbitrate
    between, and then ``printed`` is empty: F5 is what happens when something picks one anyway.
    """

    printed: str = ""
    verified: bool = False
    interpolated: bool = False
    candidates: tuple[str, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return bool(self.candidates)


@dataclass(frozen=True)
class DerivedPage:
    """One page's record, and the section sightings stitching still has to resolve.

    The record is complete but for ``section_id``, ``series_id`` and ``content.sections``: extent
    is document-wide and cannot be known until every window has returned (§6.1 step 08).
    """

    record: PageRecord
    sightings: tuple[SectionSighting, ...]

    @property
    def page_no(self) -> int:
        return self.record.page_no


@dataclass(frozen=True)
class Derivation:
    """Step 07's output: one record per page, the document's health, and what moved."""

    pages: tuple[DerivedPage, ...]
    health: health.DocumentHealth
    moves: tuple[Move, ...] = ()
    #: The windows re-billed by §6.4's second check during this run, as ``(start, end)`` pairs.
    bisected: tuple[tuple[int, int], ...] = ()

    @property
    def records(self) -> tuple[PageRecord, ...]:
        return tuple(page.record for page in self.pages)

    def page(self, page_no: int) -> DerivedPage:
        for page in self.pages:
            if page.page_no == page_no:
                return page
        raise KeyError(f"no derived page {page_no}")

    @property
    def ungrounded(self) -> tuple[tuple[int, str], ...]:
        """``(page_no, code)`` for every code the model reported that no page's text backs."""
        return tuple(
            (page.page_no, code)
            for page in self.pages
            for code in page.record.content.codes
            if " ".join(code.split()).lower() not in page.record.content.codes_in_text
        )


def section_key(title: str) -> str:
    """The canonical key two windows independently arrive at for the same section (F8).

    Slug-and-lowercase, and nothing else: it must not be a grammar (§5.2), and it must be stable
    under the punctuation and casing drift between two calls that saw two halves of one section —
    ``"Emergency stop chain"`` and ``"Emergency Stop Chain"`` are one section.
    """
    return ids.slug(title).lower()


# ── §6.4, check 2 — the independent observation ─────────────────────────────────────────────────

def _neighbours_printing(label: str, page_no: int, probed: Probe) -> tuple[int, ...]:
    """Which of ``page_no``'s immediate neighbours print ``label``, if any."""
    found = []
    for other in (page_no - 1, page_no + 1):
        if 1 <= other <= probed.page_count and printed_in(tok(probed.page(other).text), label):
            found.append(other)
    return tuple(found)


def offset_observation(form: PageOut, page_no: int, probed: Probe) -> tuple[int, ...]:
    """§6.4 check (2) for one page: the neighbours that print this page's label instead of it.

    Empty when the check passes, when the page has no text to check against, or when the model
    read no label. A non-empty result is the off-by-one signature and nothing else: the label the
    model read while looking at *this* sheet is printed on the sheet **next to** it.
    """
    label = form.printed_page_no.strip()
    page = probed.page(page_no)
    if not label or not page.has_text:
        return ()
    if printed_in(tok(page.text), label):
        return ()
    return _neighbours_printing(label, page_no, probed)


def check_offset(extraction: WindowExtraction, probed: Probe) -> None:
    """Both checks of §6.4 over one window. Raises :class:`OffsetError`, or returns.

    Structural first, because it is free and because an index set that is not ``1..N`` makes the
    absolute page of every form meaningless — there would be nothing sound to run check (2) on.

    Check (2) then weighs **every** page of the window before deciding, rather than raising on the
    first observation (fixes/002). Each page with a model-read label and a text layer falls into
    one of three states, and only two of them are evidence:

    * **confirms itself** — the label is printed on this page. Direct evidence the window is
      *aligned*.
    * **witness** — the label is printed on a neighbour and not here. Evidence of a shift.
    * **printed nowhere** — a misread, and evidence of nothing either way. It is
      ``test_a_label_printed_nowhere_is_a_misread_not_a_shift``'s case, and it must not dilute
      either side: on the legacy `TC1E-SF` window, 29 of 30 labels are printed nowhere in the
      projected text, so counting them as agreement would silence the one page that can see.

    A window is refused when the witnesses reach :data:`OFFSET_WITNESSES`, **or** when there is at
    least one witness and *no page confirms itself*. The second clause is §6.4's own argument
    stated exactly — *"a genuine shift moves every page of the window"*, so under a real shift
    nothing can confirm its own label — and it is what keeps sensitivity where only one page of
    the window carries a legible label. Without it, bisecting a genuinely shifted window would
    terminate by **accepting** its single pages instead of reaching ``window_unsplittable``, the
    opposite of §6.2's terminus.

    Conversely a page that does confirm its own label is direct evidence of alignment, and one
    stray numeral cannot outvote it: that is the shape of all 22 false positives fixes/002
    measured, and of `DS-5549-EATON`'s ``3 / 3`` tokenising to ``[3, 3]`` on its neighbour.

    A tolerated witness is logged rather than swallowed — it is the only trace that the check saw
    something — and the line carries the fields the refusal would have, so a corpus sweep can
    count them without re-running the check.
    """
    window = extraction.window
    if problem := page_index_problem(extraction.out, window):
        raise OffsetError(f"{problem} — §6.4 check (1), the structural one: the window did not "
                          f"answer about the pages it was given",
                          window=[window.start, window.end], check="structural",
                          cache_key=extraction.key, reason=OFFSET)

    witnesses: list[dict[str, Any]] = []
    confirms_self = 0
    for form in extraction.out.pages:
        page_no = window.absolute(form.page_index)
        label = form.printed_page_no.strip()
        page = probed.page(page_no)
        if not label or not page.has_text:
            continue
        if printed_in(tok(page.text), label):
            confirms_self += 1
            continue
        if elsewhere := _neighbours_printing(label, page_no, probed):
            witnesses.append({"page_no": page_no, "page_index": form.page_index,
                              "label": form.printed_page_no, "printed_on": list(elsewhere)})

    if not witnesses:
        return

    shifted = len(witnesses) >= OFFSET_WITNESSES or confirms_self == 0
    if not shifted:
        lone = witnesses[0]
        _log.info("offset_singleton", window=[window.start, window.end],
                  check="independent_observation", witnesses=len(witnesses),
                  confirms_self=confirms_self, required=OFFSET_WITNESSES,
                  cache_key=extraction.key, **lone)
        return

    first = witnesses[0]
    raise OffsetError(
        f"window {window.start}-{window.end}: {len(witnesses)} of its pages read a label that is "
        f"printed on a neighbour instead — the model read page label "
        f"\"{first['label']}\" on its page_index {first['page_index']} — PDF page "
        f"{first['page_no']} — but that label is printed on page(s) {first['printed_on']}, not on "
        f"{first['page_no']}. That is the off-by-one signature (§6.4 check 2): bisect and re-bill, "
        f"never pad and never guess the offset",
        window=[window.start, window.end], check="independent_observation",
        page_no=first["page_no"], page_index=first["page_index"], label=first["label"],
        printed_on=first["printed_on"], witnesses=len(witnesses),
        confirms_self=confirms_self, witness_pages=[w["page_no"] for w in witnesses],
        cache_key=extraction.key, reason=OFFSET,
    )


# ── §6.5 — printed labels ───────────────────────────────────────────────────────────────────────

def _collapse(value: str) -> str:
    return " ".join(value.split())


def attribute_label(model_label: str, file_label: str, text: str, *, has_text: bool) -> Label:
    """§6.5's precedence for one page: text-layer-confirmed > model-read > (interpolated, later).

    Two independent readings exist and neither is the model's alone: the model's
    ``printed_page_no``, and the PDF's own ``/PageLabels`` table, which `ingest/probe.py` reads
    mechanically off the file. Where they agree, or where the page's text prints one of them,
    the label is **confirmed**. Where they disagree and the page cannot arbitrate, both are
    returned as candidates and the label itself is left empty — F5 is an agent following a
    cross-reference to the wrong page because something picked one (§6.5).

    Interpolation is not decided here: it needs the neighbours' resolved labels, so
    :func:`interpolate_labels` fills the pages this function leaves empty.
    """
    tokens = tok(text) if has_text else []
    candidates: list[str] = []
    for reading in (_collapse(model_label), _collapse(file_label)):
        if reading and reading not in candidates:
            candidates.append(reading)

    if not candidates:
        return Label()

    if len(candidates) > 1:
        confirmed = [c for c in candidates if printed_in(tokens, c)]
        if len(confirmed) == 1:
            return Label(printed=confirmed[0], verified=True)
        # Either the page prints neither reading, or it prints both. Both are ambiguity: the
        # second is a sheet carrying two labels, and picking one is as wrong as guessing.
        return Label(candidates=tuple(candidates))

    only = candidates[0]
    # The file's own label table is evidence about this page in the same way its text is — a
    # mechanical readout, not a reading. The model's label alone, on a page whose text neither
    # confirms nor contradicts it, is a reading and says so.
    #
    # But `/PageLabels` is a readout of the **container**, and writers emit a plain 1..N table
    # regardless of what is printed on the sheet — so where the page has a text layer that does
    # not print the label, the page is the better witness and this is not verification
    # (fixes/003). Without the `has_text` guard the two halves of §6.4/§6.5 contradict each other
    # on the same evidence: `check_offset` calls a label absent from this page's text a fatal
    # off-by-one, while this stamped ``verified: true`` on it. On the 22 pages fixes/002 measured,
    # both fired at once.
    verified = printed_in(tokens, only) or (only == _collapse(file_label) and not has_text)
    return Label(printed=only, verified=verified)


def interpolate_labels(labels: Sequence[Label]) -> tuple[Label, ...]:
    """Fill an unlabelled page from the pages either side of it, and **say that you did**.

    The only inference permitted is the one that is bracketed on both sides: neighbours that are
    plain integers two apart put exactly one integer between them. `impl` interpolated from the
    *nearest* sibling and a delta, which extrapolates — and §6.5's numbering note is the reason
    not to: no ``printed + offset = pdf`` formula exists in this corpus, because the offset
    changes at every chapter. A bracket is not a formula; it is a page with nowhere else to be.

    Every interpolated label carries ``interpolated=True`` and ``verified=False``, all the way to
    the payload, so nothing downstream can mistake it for something that was read.
    """
    filled = list(labels)
    for index, label in enumerate(filled):
        if label.printed or label.ambiguous or index == 0 or index == len(filled) - 1:
            continue
        before, after = filled[index - 1].printed, filled[index + 1].printed
        if not (before.isdigit() and after.isdigit()):
            continue
        if int(after) - int(before) == 2:
            filled[index] = Label(printed=str(int(before) + 1), verified=False, interpolated=True)
    return tuple(filled)


# ── §6.5 — code reattribution ───────────────────────────────────────────────────────────────────

@dataclass
class _Working:
    """One page under construction. Mutable, and local to this module by design."""

    page_no: int
    form: PageOut
    text: str
    has_text: bool
    tokens: tuple[str, ...]
    extract_key: str
    codes: list[str] = field(default_factory=list)
    moved_from: list[MovedCode] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def flag(self, name: str) -> None:
        if name not in self.flags:
            self.flags.append(name)


def _reattribute(pages: Sequence[_Working], window: Window,
                 page_id_of: Callable[[int], str]) -> tuple[Move, ...]:
    """§6.5 (F6) — move each sighting to the page whose text carries it, within this window.

    Three outcomes, and only the first one moves anything:

    * **printed here** — the ordinary case; the sighting stays and grounds.
    * **printed on exactly one adjacent page of this window** — the sighting moves there and the
      receiving page records ``moved_from``. The window bound is §6.5's: a code two windows away
      was seen by a different call, so "the model read it off the facing sheet" is not what
      happened.
    * **anything else** — printed nowhere, or printed on *both* neighbours. It stays put and
      counts against this page's ``grounded_rate``. Both neighbours printing it is ambiguity, and
      resolving ambiguity by picking a side is the shape of F5; the page says
      ``ambiguous_reattribution`` instead.
    """
    by_page = {page.page_no: page for page in pages}
    moves: list[Move] = []

    for page in pages:
        for code in page.form.codes:
            if printed_in(page.tokens, code):
                page.codes.append(code)
                continue
            adjacent = [
                other for other in (page.page_no - 1, page.page_no + 1)
                if other in by_page and printed_in(by_page[other].tokens, code)
            ]
            if len(adjacent) == 1:
                moves.append(Move(code=code, from_page_no=page.page_no, to_page_no=adjacent[0],
                                  window=(window.start, window.end)))
                continue
            page.codes.append(code)
            if adjacent:
                page.flag(FLAG_AMBIGUOUS_REATTRIBUTION)

    for move in moves:
        target = by_page[move.to_page_no]
        if not any(_collapse(code).lower() == _collapse(move.code).lower()
                   for code in target.codes):
            target.codes.append(move.code)
        target.moved_from.append(MovedCode(code=move.code,
                                           from_page_id=page_id_of(move.from_page_no)))
        target.flag(FLAG_CODES_REATTRIBUTED)
    return tuple(moves)


# ── the step ────────────────────────────────────────────────────────────────────────────────────

def _working(extraction: WindowExtraction, probed: Probe) -> tuple[_Working, ...]:
    """One window's forms joined to their pages. The join key is the absolute page number.

    Whole-page set membership, not positional agreement — the consequence `impl`'s guide names and
    D6 defers: a page-level join confirms **presence**, never attribution within the sheet.
    """
    window = extraction.window
    pages = []
    for form in sorted(extraction.out.pages, key=lambda f: f.page_index):
        page_no = window.absolute(form.page_index)
        probe_page = probed.page(page_no)
        pages.append(_Working(
            page_no=page_no, form=form, text=probe_page.text, has_text=probe_page.has_text,
            tokens=tuple(tok(probe_page.text)), extract_key=extraction.key,
        ))
    return tuple(pages)


def derive_window(extraction: WindowExtraction, *, probed: Probe, doc: Manifest,
                  ) -> tuple[tuple[_Working, ...], tuple[Move, ...]]:
    """One window through step 07: both offset checks, then reattribution. No records yet.

    Records are built document-wide, because label interpolation and the health aggregate both
    need pages this window cannot see.
    """
    check_offset(extraction, probed)
    pages = _working(extraction, probed)
    moves = _reattribute(pages, extraction.window,
                         lambda page_no: ids.page_id(doc.doc_id, doc.revision, page_no))
    return pages, moves


def _record(page: _Working, *, label: Label, trust: TextTrust, rate: float | None,
            grounded: Sequence[str], doc: Manifest, doc_lang: Sequence[str], run_id: str,
            release_id: str, probe_version: str, vlm_model: str, prompt_version: str,
            dpi: int) -> PageRecord:
    """One finished page record (§5.3), less the section ids stitching will add."""
    page_id = ids.page_id(doc.doc_id, doc.revision, page.page_no)
    flags = list(page.flags)
    if not page.has_text:
        flags.append(FLAG_NO_TEXT)
    if len(grounded) < len(page.codes):
        flags.append(FLAG_UNGROUNDED_CODES)
    if label.ambiguous:
        flags.append(FLAG_LABEL_AMBIGUOUS)
    if label.interpolated:
        flags.append(FLAG_LABEL_INTERPOLATED)

    return PageRecord(
        **doc.facets(),
        # I7 — written False and left False. Only the publish gates of §6.7 flip it (U011).
        is_current=False,
        page_kind=page_kind(page.form.page_kind),
        lang=list(page.form.lang or doc_lang),
        page_no=page.page_no,
        has_text=page.has_text,
        text_trust=trust,
        run_id=run_id,
        # I2 — verbatim from `ingest/probe.py`, the only writer of this field. Nothing the model
        # returned is on this line, and the L1 provenance test asserts exactly that.
        text=page.text,
        # D3 — the opt-in surface. Every hit from it is permanently `verified: false`.
        vlm_codes=" ".join(page.codes),
        content=PageContent(
            printed_page_no=label.printed,
            label_verified=label.verified,
            interpolated=label.interpolated,
            label_candidates=list(label.candidates),
            summaries=[Summary(lang=s.lang, text=s.text) for s in page.form.summaries],
            topics=list(page.form.topics),
            sections=[],          # stitching's, once the folds are gone (§6.1 step 08)
            codes=list(page.codes),
            codes_in_text=health.codes_in_text(grounded),
            moved_from=list(page.moved_from),
            grounded_rate=rate,
            flags=sorted(set(flags)),
        ),
        provenance=Provenance(
            page_id=page_id, run_id=run_id, release_id=release_id,
            extract_key=page.extract_key, probe_version=probe_version,
            vlm_model=vlm_model, prompt_version=prompt_version, dpi=dpi,
        ),
    )


def derive(extraction: Extraction, *, probed: Probe, doc: Manifest,
           run_id: str = "", release_id: str = "", vlm_model: str = "", prompt_version: str = "",
           dpi: int = DPI_ANSWER, doc_lang: Sequence[str] = (),
           reextract: Callable[[Window], Iterable[WindowExtraction]] | None = None,
           ) -> Derivation:
    """Step 07 over a whole extraction: ``WindowOut`` + probe text → one record per page.

    ``reextract`` is how §6.4's *"raise and bisect"* completes. An offset failure is a §6.2
    trigger like any other, and the repair is the same one step 06 makes: split the window, re-bill
    the halves, derive those instead. **No record is emitted for the shifted window** — the halves
    replace it entirely. A caller that passes no ``reextract`` (a test, a replay of a frozen
    fixture, an inspection run) gets the :class:`OffsetError` itself, which is the honest answer
    when there is nothing available to re-bill with.
    """
    working: list[_Working] = []
    moves: list[Move] = []
    bisected: list[tuple[int, int]] = []

    def take(one: WindowExtraction) -> None:
        try:
            pages, moved = derive_window(one, probed=probed, doc=doc)
        except OffsetError as failure:
            if reextract is None:
                raise
            window = one.window
            left, right = bisect_window(window, OFFSET)
            # The refusal's own details win over the defaults: it knows which check fired and on
            # which page, and both keys overlap with what a bisection would otherwise report.
            _log.warning("derive_bisect", **{
                "reason": OFFSET, "window": [window.start, window.end],
                "halves": [[left.start, left.end], [right.start, right.end]],
                "detail": str(failure), **failure.details})
            bisected.append((window.start, window.end))
            for half in (left, right):
                for replacement in reextract(half):
                    take(replacement)
            return
        working.extend(pages)
        moves.extend(moved)

    for one in extraction.windows:
        take(one)

    working.sort(key=lambda page: page.page_no)
    seen_pages = [page.page_no for page in working]
    if seen_pages != list(range(1, probed.page_count + 1)):
        # The guard against a *large* shift, and the reason §6.4's second check only has to look
        # at the immediate neighbours. `abs = window.start + page_index - 1` can be wrong by one
        # and still produce a sound-looking document; it cannot be wrong by more without two
        # windows claiming the same pages, which is this assertion. A hole here is the one
        # failure that shows up as a *smaller correct answer* rather than as an error (F17).
        raise OffsetError(
            f"derivation produced {len(seen_pages)} page(s) for a {probed.page_count}-page "
            f"document: {sorted(set(range(1, probed.page_count + 1)) - set(seen_pages))} missing",
            page_count=probed.page_count, derived=len(seen_pages), check="coverage",
        )

    labels = interpolate_labels([
        attribute_label(page.form.printed_page_no, probed.page(page.page_no).label, page.text,
                        has_text=page.has_text)
        for page in working
    ])
    grounded = [health.grounded_codes(page.codes, page.text) for page in working]
    rates = [health.grounded_rate(len(page.codes), len(found), has_text=page.has_text)
             for page, found in zip(working, grounded)]
    document = health.document_health(rates, [page.has_text for page in working])

    pages = tuple(
        DerivedPage(
            record=_record(
                page, label=label, rate=rate,
                trust=health.demote(health.page_trust(rate, has_text=page.has_text),
                                    document.text_trust),
                grounded=found, doc=doc, doc_lang=doc_lang, run_id=run_id,
                release_id=release_id, probe_version=probed.probe_version, vlm_model=vlm_model,
                prompt_version=prompt_version, dpi=dpi,
            ),
            sightings=tuple(
                SectionSighting(page_no=page.page_no, title=ref.title,
                                key=section_key(ref.title), is_start=ref.is_start)
                for ref in page.form.sections if section_key(ref.title)
            ),
        )
        for page, label, rate, found in zip(working, labels, rates, grounded)
    )

    _log.info("derive", pages=len(pages), moves=len(moves), bisected=bisected,
              grounded_median=document.grounded_median, text_trust=document.text_trust,
              searchable_ratio=round(document.searchable_ratio, 4),
              labels_verified=sum(1 for p in pages if p.record.content.label_verified),
              labels_ambiguous=sum(1 for p in pages if p.record.content.label_candidates))
    return Derivation(pages=pages, health=document, moves=tuple(moves),
                      bisected=tuple(bisected))


def probe_texts(probed: Probe) -> Mapping[int, str]:
    """``page_no → text``, for the I2 provenance assertion of §12.5.

    Exposed here rather than written out in the test, because the assertion is about *this*
    module: the check is that every record derivation emits carries the probe's text unchanged,
    and a test that built its own expectation from the same source would prove nothing.
    """
    return {page.page_no: page.text for page in probed.pages}
