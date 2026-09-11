"""Step 06 — S2 extraction, and the schema it is demanded in (Spec §5.2, §6.1, §6.3).

**The call that spends the money.** One VLM call per window is ~99 % of extraction spend, so every
decision here is about not making one twice and not keeping a bad one.

Rewritten from ``impl/app/segment.py`` rather than ported: the shape changed. ``units[]`` became
``sections[]``, ``identifiers[]`` became ``codes[]``, and ``summaries`` and ``topics`` are new. What
went with the old shape is everything that encoded knowledge of *this corpus* — ``STRICT_KINDS``,
``key_for_unit``, ``Unit.kind``, ``attrs``, ``refs[]`` (measured at zero reads anywhere in `impl`)
and ``_is_safety()``'s hardcoded keyword list. §5.2 is categorical about it: **no identifier
grammar, no classification enum, no regex taxonomy and no per-corpus keyword list** anywhere in
extraction or derivation.

Three rules shape the rest.

**Presence, never extent.** ``sections[]`` says "this page belongs to the emergency stop chain"; it
never says where that section starts and ends. A window fold can cut straight through a section and
the model on one side of the fold cannot see the other, so any span it gave would be a guess — and
a confident one. Extent is computed after the folds are gone (§6.1 step 08), which is what lets a
section straddle a fold and survive it (F8).

**Verbatim, and the text never comes back.** The model returns structure and codes, never page
text: the text came from PyMuPDF at step 02 and ``ingest/probe.py`` is the only writer of it (I2).
That is what makes step 07 able to *check* the model's codes against what is actually printed.

**Keep the receipt, not your summary of it.** What gets cached is the **verbatim response body**
(§6.3). Caching the derived ``PageRecord`` instead looks equivalent — it is smaller and closer to
what the caller wants — but it makes every downstream change unreplayable: the only way to
re-derive would be to buy the paid call again. Because the receipt is kept, steps 07–10 cost
nothing to change and evaluating a different text extractor is free.

**A bad answer is bisected, never kept.** On the output ceiling, an unterminated body, a
schema-invalid one, or a page index set that is not exactly 1..N, the window is split and re-billed
(§6.2's four triggers, F13 — U007's ladder, exercised here). Never pad, never guess the offset,
never accept a partial window: a truncated 30-page window that is quietly kept loses 30 pages of a
manual and reports success. The floor is one page, which fails typed ``window_unsplittable`` —
there is no depth counter, because §6.2 names that page, not a recursion limit, as the terminus.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vsir import logging as vsir_logging
from vsir.config import DPI_ANSWER
from vsir.ingest import render
from vsir.ingest.probe import Probe
from vsir.ingest.window import (BisectReason, DocumentFacts, Plan, Window, bisect_window)
from vsir.vlm import (EXTRACT, FACTS, Backend, Entry, Request, VlmSchemaInvalid, VlmTruncated,
                      extract_key, facts_key, hint)

_log = vsir_logging.get_logger(__name__)

#: §5.2's eight page kinds. The schema's own value list, not a taxonomy of this corpus: it says
#: what a *sheet of paper* is, and it would read the same for a cookbook. `impl`'s ``UNIT_KINDS``
#: — the ten-way classification of what a page *contains* — is struck (§2.4, C1).
PAGE_KINDS: tuple[str, ...] = ("prose", "table", "schematic", "exploded", "cover", "toc", "index",
                               "blank")

#: The kind a page falls back to when the model reports one that is not in §5.2's list. A facet,
#: so a stray value is normalised rather than re-billing thirty pages over a label.
DEFAULT_PAGE_KIND = "prose"

#: How many opening pages S1 is shown (§6.1 step 04) — ported from `impl`'s ``front_pages=12``.
#:
#: A **pin**, not configuration, and deliberately so: ``facts_key`` is
#: ``sha256(content hash ‖ model ‖ prompt_version)`` and this number is not on it (§6.3), so
#: changing it must be a release that also moves ``prompt_version``. Making it an env var would let
#: a deployment change what S1 saw while the key claimed the answer was unchanged.
S1_HEAD_PAGES = 12

#: Which §6.2 trigger each failure maps to. All four are reachable, and they are not the same
#: event: the ceiling and an unterminated body are the provider cutting the answer off, a
#: schema-invalid body is an answer to a different question, and a broken index set is an answer
#: about pages that were not the ones sent.
CEILING = "max_tokens"
UNTERMINATED = "truncated"
MALFORMED = "schema_invalid"
MISINDEXED = "offset"


class Summary(BaseModel):
    """2-3 sentences on what is SPECIFIC to this page, in one language (D5).

    The binding prompt rule of §5.2 is a property of this field: *"Do not describe the document
    generally."* A summary that describes the manual rather than the page makes every page's dense
    vector look like every other page's, and the `captions` surface stops discriminating at all —
    which is the surface D2 keeps precisely because the new schema finally gives it content.
    """

    model_config = ConfigDict(extra="forbid")

    lang: str = ""
    text: str = ""


class SectionRef(BaseModel):
    """A section this page belongs to. Presence, never extent (§5.2)."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    is_start: bool = False


class PageOut(BaseModel):
    """One page of a window, as the model reports it."""

    model_config = ConfigDict(extra="forbid")

    #: 1-based **within this excerpt**, not within the book (§6.4). Required, with no default: a
    #: defaulted 0 would map to ``window.start - 1`` and shift the page silently.
    page_index: int
    #: The page label as printed, VERBATIM. Model-read, and cross-checked against the text (§6.5).
    printed_page_no: str = ""
    page_kind: str = DEFAULT_PAGE_KIND
    lang: list[str] = Field(default_factory=list)
    sections: list[SectionRef] = Field(default_factory=list)
    #: One per ``lang`` (D5). Required, because a response that omits the field entirely answered a
    #: different question than the one the schema hash in ``extract_key`` describes.
    summaries: list[Summary]
    #: Every code, tag, part or reference number, VERBATIM. Nothing here reaches a lexical index
    #: except through ``vlm_codes``, which is opt-in and permanently ``verified: false`` (I2, D3).
    codes: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)

    @property
    def kind(self) -> str:
        """``page_kind`` if §5.2 lists it, else the default. Normalised, never invented."""
        return self.page_kind if self.page_kind in PAGE_KINDS else DEFAULT_PAGE_KIND

    @property
    def summary_langs(self) -> tuple[str, ...]:
        return tuple(summary.lang for summary in self.summaries)

    def missing_summary_langs(self) -> tuple[str, ...]:
        """Languages on the page with no summary of their own (D5).

        Reported rather than repaired. The repair would be to blend, and D5 exists because one
        blended IT/EN summary poisons the embedding for both languages.
        """
        return tuple(lang for lang in self.lang if lang not in self.summary_langs)


class WindowOut(BaseModel):
    """One window's worth of pages. The verbatim response is what gets cached (§6.3)."""

    model_config = ConfigDict(extra="forbid")

    pages: list[PageOut]


def schema_hash(schema: Mapping[str, Any] | type[BaseModel]) -> str:
    """A stable digest of the response schema the extraction was demanded in.

    `impl` put a hand-maintained ``SCHEMA_VERSION`` integer in the key, which is only correct while
    somebody remembers to bump it. Hashing the schema itself cannot be forgotten: add a field and
    every window re-bills, which is the honest answer, because the model was asked a different
    question and its old answer does not contain the new field.
    """
    document = schema.model_json_schema() if isinstance(schema, type) else dict(schema)
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: The value that goes into ``extract_key`` (§6.3). Computed, never written down by hand.
S2_SCHEMA_HASH = schema_hash(WindowOut)

#: What :func:`extract` reports as it goes, so an interrupted run leaves a record of where it got
#: to (§6.7's window points, §15 Factor IX). Called **twice per planned window**: once with ``()``
#: as the call is about to be made, and once with the extractions it produced.
#:
#: The second argument is a tuple rather than a single extraction because §6.2's bisection replaces
#: one planned window with its halves, each billed under its own key — and a checkpoint that
#: recorded the parent would name a call that was never made. What the run record ends up holding
#: is what was actually billed.
WindowProgress = Callable[[Window, tuple["WindowExtraction", ...]], None]


@dataclass(frozen=True)
class WindowExtraction:
    """One window's verbatim response, parsed — and how it came to be this window."""

    window: Window
    key: str
    out: WindowOut
    entry: Entry

    @property
    def origin(self) -> str:
        """``replay`` or ``model`` — which service answered, not which code path ran (D10)."""
        return self.entry.origin

    @property
    def page_forms(self) -> int:
        return len(self.out.pages)

    @property
    def sightings(self) -> int:
        """Section sightings — presence reports, not sections. Step 08 turns them into sections."""
        return sum(len(page.sections) for page in self.out.pages)

    @property
    def codes(self) -> int:
        """Code strings as returned: not deduplicated, not sorted, not classified (§5.2)."""
        return sum(len(page.codes) for page in self.out.pages)


@dataclass(frozen=True)
class Extraction:
    """Step 06's output: the plan as it ended up, and one response per final window."""

    plan: Plan
    windows: tuple[WindowExtraction, ...]

    @property
    def page_forms(self) -> int:
        return sum(window.page_forms for window in self.windows)

    @property
    def bisections(self) -> tuple[str, ...]:
        """The triggers that split a window during this run, in order. Empty on a clean run."""
        return tuple(w.window.bisected_from for w in self.windows if w.window.bisected_from)

    def page_form(self, page_no: int) -> PageOut:
        """The form for one **absolute** PDF page. The offset is applied here, once (§6.4)."""
        for extraction in self.windows:
            window = extraction.window
            if window.start <= page_no <= window.end:
                for page in extraction.out.pages:
                    if window.absolute(page.page_index) == page_no:
                        return page
        raise KeyError(f"no page form for PDF page {page_no}")


def page_index_problem(out: WindowOut, window: Window) -> str:
    """§6.4 check (1), the **structural** one: the indices are exactly 1..N, each once.

    Returns a description, or ``""`` when the window is sound. This is half of the offset proof and
    the half that belongs to the response's own integrity — it is also what "never accept a partial
    window" means in code (F13): a 30-page window that comes back with 22 forms has lost eight
    pages of a manual, and nothing else in the pipeline would notice.

    Check (2) — the *independent observation* that a model-read ``printed_page_no`` phrase-matches
    **this** page's text rather than a neighbour's — needs the text layer, so it lives with
    derivation (§6.5, U009). Both are required.
    """
    indices = sorted(page.page_index for page in out.pages)
    if indices == list(range(1, window.pages + 1)):
        return ""
    duplicates = sorted({i for i in indices if indices.count(i) > 1})
    outside = sorted({i for i in indices if not 1 <= i <= window.pages})
    missing = sorted(set(range(1, window.pages + 1)) - set(indices))
    return (
        f"window {window.start}-{window.end} expected page_index 1..{window.pages}, got "
        f"{len(indices)} form(s)"
        + (f"; missing {missing}" if missing else "")
        + (f"; duplicated {duplicates}" if duplicates else "")
        + (f"; outside the window {outside}" if outside else "")
    )


def parse(entry: Entry, window: Window) -> WindowOut:
    """The verbatim body → a validated :class:`WindowOut`, or a typed bisection trigger.

    The three failures are told apart because they are different events and only one of them means
    the prompt is wrong: an unterminated body is the provider's output ceiling reached mid-JSON, a
    valid body of the wrong shape is an answer to a different question, and a sound body whose
    indices are not 1..N is an answer about pages that were not the ones sent.
    """
    try:
        document = json.loads(entry.body)
    except json.JSONDecodeError as failure:
        raise VlmSchemaInvalid(
            f"window {window.start}-{window.end}: the response body is not complete JSON "
            f"({failure.msg} at char {failure.pos} of {len(entry.body)}) — the output ceiling was "
            f"reached mid-answer, so bisect and re-bill (§6.2)",
            cache_key=entry.key, reason=UNTERMINATED, body_bytes=len(entry.body),
        ) from failure
    try:
        out = WindowOut.model_validate(document)
    except ValidationError as failure:
        raise VlmSchemaInvalid(
            f"window {window.start}-{window.end}: the response does not validate against the S2 "
            f"schema this key was built from ({failure.error_count()} error(s), first: "
            f"{failure.errors()[0].get('loc')} {failure.errors()[0].get('msg')})",
            cache_key=entry.key, reason=MALFORMED, errors=failure.error_count(),
        ) from failure
    if problem := page_index_problem(out, window):
        raise VlmSchemaInvalid(f"{problem} — bisect and re-bill, never pad and never guess the "
                               f"offset (§6.2, §6.4)",
                               cache_key=entry.key, reason=MISINDEXED, detail=problem)
    return out


def _trigger(failure: Exception) -> BisectReason:
    """Which of §6.2's four triggers a failure is. Never a guess: each carries its own reason."""
    if isinstance(failure, VlmTruncated):
        return CEILING
    reason = getattr(failure, "details", {}).get("reason", MALFORMED)
    return reason if reason in (UNTERMINATED, MALFORMED, MISINDEXED) else MALFORMED


def _rasters(source: Path, window: Window, *, content_hash: str,
             dpi: int) -> tuple[tuple[str, ...], tuple[bytes, ...]]:
    """The window's page image hashes and its PNGs, in absolute page order — one render, two uses.

    The hashes are what ``extract_key`` is built from and the PNGs are what the model is shown, and
    they come from the same call so the key cannot describe a different image than the one sent.
    """
    rendered = render.render_pages(source, window.page_numbers, dpi=dpi,
                                  content_hash=content_hash)
    return tuple(r.sha256 for r in rendered), tuple(r.png for r in rendered)


def extract_window(backend: Backend, window: Window, *, source: str | Path, content_hash: str,
                   page_count: int, vlm_model: str, prompt_version: str,
                   dpi: int = DPI_ANSWER) -> tuple[WindowExtraction, ...]:
    """One window through the boundary — bisecting and re-billing on any of §6.2's four triggers.

    Returns a tuple because a bisection replaces one window with its halves, each with its **own**
    key. `impl` merged the halves and cached the result under the *parent's* key, so the repair was
    invisible on the next run; here the key is built from the page image hashes, so each half's key
    is already a fact about the pages it actually covers, and filing a merged answer under a key no
    single call produced would falsify the receipt.
    """
    path = Path(source)
    hashes, images = _rasters(path, window, content_hash=content_hash, dpi=dpi)
    key = extract_key(hashes, vlm_model=vlm_model, prompt_version=prompt_version, dpi=dpi,
                      schema_hash=S2_SCHEMA_HASH)
    label = f"S2 {window.start}-{window.end}"
    request = Request(namespace=EXTRACT, key=key, stage="s2", schema=WindowOut, images=images,
                      hint=hint(start=window.start, end=window.end, page_count=page_count),
                      label=label)
    try:
        entry = backend.generate(request)
        out = parse(entry, window)
    except (VlmTruncated, VlmSchemaInvalid) as failure:
        reason = _trigger(failure)
        # `bisect_window` raises `window_unsplittable` at one page, which is §6.2's terminus: the
        # run fails naming the page rather than publishing a window the model never described.
        left, right = bisect_window(window, reason)
        _log.warning("s2_bisect", cache_key=key, reason=reason, window=[window.start, window.end],
                     halves=[[left.start, left.end], [right.start, right.end]],
                     detail=str(failure))
        common = dict(source=path, content_hash=content_hash, page_count=page_count,
                      vlm_model=vlm_model, prompt_version=prompt_version, dpi=dpi)
        return (extract_window(backend, left, **common)
                + extract_window(backend, right, **common))

    _log.info("s2_window", cache_key=key, origin=entry.origin, window=[window.start, window.end],
              page_forms=len(out.pages), sightings=sum(len(p.sections) for p in out.pages),
              codes=sum(len(p.codes) for p in out.pages), bisected_from=window.bisected_from)
    return (WindowExtraction(window=window, key=key, out=out, entry=entry),)


def extract(backend: Backend, *, source: str | Path, plan: Plan, probed: Probe, vlm_model: str,
            prompt_version: str, dpi: int = DPI_ANSWER,
            progress: WindowProgress | None = None) -> Extraction:
    """Step 06 over a whole plan. The windows are independent, so nothing is carried between them.

    Level 0 and Level 1 cut on the document's own structure, which is what makes them
    parallelisable (§6.2); the fan-out itself arrives with the run control plane (U011), and this
    function stays a plain in-order loop so that a bisection amends the plan deterministically.

    ``progress`` is :data:`WindowProgress` — how a kill mid-extraction leaves a record of where it
    got to. It is reported **as each window finishes** rather than after the loop, because a
    checkpoint written at the end is a checkpoint that never survives the event it exists for
    (§15 Factor IX, F17, U025).
    """
    extractions: tuple[WindowExtraction, ...] = ()
    for window in plan.windows:
        if progress is not None:
            progress(window, ())
        billed = extract_window(backend, window, source=source,
                                content_hash=probed.content_hash,
                                page_count=probed.page_count, vlm_model=vlm_model,
                                prompt_version=prompt_version, dpi=dpi)
        if progress is not None:
            progress(window, billed)
        extractions += billed
    final = Plan(plan.level, tuple(e.window for e in extractions))
    if not final.covers(probed.page_count):
        # Unreachable through `bisect_window`, which preserves the page set by construction. It is
        # asserted anyway because this is the one place a lost page would not raise anywhere else.
        raise VlmSchemaInvalid(
            f"the extracted windows do not cover pages 1-{probed.page_count} exactly once: "
            f"{[[w.window.start, w.window.end] for w in extractions]}",
            reason=MISINDEXED, page_count=probed.page_count,
        )
    return Extraction(plan=final, windows=extractions)


def document_facts(backend: Backend, *, source: str | Path, probed: Probe, vlm_model: str,
                   prompt_version: str, dpi: int = DPI_ANSWER,
                   head_pages: int = S1_HEAD_PAGES) -> tuple[DocumentFacts, Entry]:
    """Step 04 — S1 document facts, cached per **document** under ``facts_key`` (§6.3, register B2).

    One cheap call whose contents list is the sole input to the branch that decides how much S2
    costs. `impl` neither caches nor persists it, so every re-run re-bills it and a future call
    returning a different contents list silently re-picks the ladder and re-bills every window
    behind it. Caching it is what makes the ladder reproducible.

    A truncated or schema-invalid S1 raises rather than bisecting: there is no window to split, and
    the honest answer is that the document's structure was not read.
    """
    path = Path(source)
    pages = range(1, min(head_pages, probed.page_count) + 1)
    rendered = render.render_pages(path, pages, dpi=dpi, content_hash=probed.content_hash)
    key = facts_key(probed.content_hash, vlm_model=vlm_model, prompt_version=prompt_version)
    request = Request(
        namespace=FACTS, key=key, stage="s1", schema=DocumentFacts,
        images=tuple(r.png for r in rendered),
        hint=f"These are the opening {len(rendered)} of {probed.page_count} pages.",
        label=f"S1 {path.name}",
    )
    entry = backend.generate(request)
    try:
        facts = DocumentFacts.model_validate_json(entry.body)
    except ValidationError as failure:
        raise VlmSchemaInvalid(
            f"S1 {path.name}: the response does not validate against the document-facts schema "
            f"({failure.error_count()} error(s))",
            cache_key=key, reason=MALFORMED, errors=failure.error_count(),
        ) from failure
    _log.info("s1_facts", cache_key=key, origin=entry.origin, head_pages=len(rendered),
              toc_entries=len(facts.toc), lang=list(facts.lang))
    return facts, entry


def page_kind(raw: str) -> str:
    """§5.2's eight, or the default. Exposed so derivation normalises exactly once (U009)."""
    return raw if raw in PAGE_KINDS else DEFAULT_PAGE_KIND
