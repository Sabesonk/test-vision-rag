"""The `grounded_rate` distribution report (Spec §11.1, §5.7, R4 · plan U013).

§11.1 gates publication on the **median `grounded_rate` over the pages that have a text layer**,
and pins the bar at ``0.8`` with a parenthesis that is the whole reason this module exists:
*"provisional — set from the M2b distribution, R4."* R18's R4 says the same thing less politely —
*"`grounded_rate ≥ 0.8` is chosen, not derived."* A gate nobody measured is a gate that either
quarantines healthy documents or publishes broken ones, and which of the two it does is unknown
until a real corpus has been counted.

This module is that count. It takes the page records of a document, reports the distribution of
their rates, and says what each candidate threshold would have done to it. It decides nothing:
the number that gates is :data:`vsir.core.health.TRUST_OK_MIN`, in code, and moving it is a
**release** — see *"The recommendation is a proposal, not a switch"* below.

── Three rules it inherits from §5.7, and would be wrong without ────────────────────────────────

1. **A page with no text layer has no rate, and is not a zero.** The `None` is the whole subject of
   `core/health.py`'s docstring: scoring a scanned page 0.0 drags the median under the gate and
   quarantines exactly the documents F4 requires to be *published and unsearchable*. So the
   denominator here is `pages_with_text`, never `page_count`, and :attr:`Distribution.measured`
   drops the `None`s rather than defaulting them.
2. **The median is the gate's own median.** :attr:`Distribution.median` calls
   :func:`vsir.core.health.median` — the same function `ingest/gates.py` scores the document with.
   A report that computed its own would eventually recommend a threshold against a number the gate
   does not use, and the disagreement would surface as a mystery quarantine months later.
3. **A fully scanned document sets nothing.** With no measured page there is no distribution, the
   §11.1 gate is *skipped* rather than failed, and :func:`recommend` returns no threshold and says
   why. It is not a data point about where the bar belongs.

── The recommendation is a proposal, not a switch ───────────────────────────────────────────────

:data:`THRESHOLD_ENV` (``VSIR_GROUNDED_RATE_THRESHOLD``) is read **here, by this report, as the
candidate being evaluated** — "what would this bar have done to this document?" — and nowhere
else. It is deliberately not wired into `ingest/gates.py`, because `core/health.py` already
settled that question: *"a deployment that could re-tune what 'trusted' means would be a deployment
that could turn F14 back on by editing an env var."* The threshold reaches the gate the way a model
id or a prompt version does (§15 Factor III): by editing the pin and shipping a release, which is
reviewable and which the collection fingerprint and the run record both witness.

So the operator loop R4 asks for is: run this report over the M2b ingest, try candidates with
``--threshold``, and open a one-line change to :data:`~vsir.core.health.TRUST_OK_MIN` with the
report's output as the rationale.

── What one document can and cannot settle ──────────────────────────────────────────────────────

`TC1E-SF` is 55 pages and the corpus is 5,505. R4's own mitigation says so: the threshold is
provisional until `vsir eval corpus` (§12.6, U026) re-validates it at scale, and
``vsir publish --override grounded_rate --reason "…"`` exists precisely so a mis-set bar cannot
strand a document silently. Every :class:`Recommendation` carries ``provisional=True`` and says
this in its own rationale, so a number lifted out of this report into a commit message arrives with
the caveat attached.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from vsir.core import health
from vsir.core.record import PageRecord

#: The candidate threshold read by this report — never by the gate. See the module docstring.
THRESHOLD_ENV = "VSIR_GROUNDED_RATE_THRESHOLD"

#: The rungs :func:`recommend` may choose between. A ladder rather than "the median minus 0.05"
#: because the number ends up in a spec table, a docstring and a release note, and a bar of
#: `0.7233` reads as measured to four digits when it is one document's median with a margin.
LADDER: tuple[float, ...] = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)

#: How far below the observed median the recommended rung must sit. A threshold at the median
#: fails half the documents that look like this one, which is not a gate, it is a coin toss.
HEADROOM = 0.05

#: Reported percentiles, by nearest rank (see :meth:`Distribution.percentile`).
PERCENTILES: tuple[int, ...] = (5, 10, 25, 50, 75, 90, 95)

#: Histogram edges, aligned to the trust ladder so `0.2` and `0.8` are bucket boundaries rather
#: than values buried mid-bucket: a reader has to be able to see the `untrusted` and `ok` cuts.
BUCKET_EDGES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

#: How many worst pages the report lists — the same number §11.1's gate evidence lists.
WORST_PAGES = 5

#: Histogram bar column width. The bars are scaled to the widest bucket, never to the page count.
_BAR_WIDTH = 24

#: A `provenance.probe_version` starting with this was written by `ingest/probe.py` running the
#: pinned extractor over a real PDF. R4 asks for the distribution of a **measurement**, and the two
#: checked-in corpora are constructions: the M1 pages are hand-written, and the `impl` baseline's
#: text is the *projection* of the codes the old gate had already proved printed — so its rate is
#: 1.0 on every page by construction, not by measurement. Either would set the gate from its own
#: design. :func:`recommend` therefore refuses to propose a threshold off anything else.
EXTRACTOR_PREFIX = "pymupdf-"


class NoRecords(ValueError):
    """A distribution was asked for over no pages at all. Not the same as a scanned document."""


# ── the rows ────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PageRate:
    """One page's contribution: its rate, or the fact that it has none."""

    page_no: int
    page_id: str
    rate: float | None
    has_text: bool
    text_trust: str

    def as_dict(self) -> dict[str, Any]:
        return {"page_no": self.page_no, "page_id": self.page_id, "grounded_rate": self.rate,
                "has_text": self.has_text, "text_trust": self.text_trust}


@dataclass(frozen=True)
class Candidate:
    """What one candidate threshold would have done to one document."""

    threshold: float
    #: Whether §11.1's blocking gate would pass. ``None`` where the gate is **skipped** — a fully
    #: scanned document is published and answers `not_searchable` (F4), so neither pass nor fail
    #: is the honest word for it.
    document_passes: bool | None
    #: Pages whose own rate is under the bar. Not what the gate scores — the gate scores the
    #: median — but it is what a reviewer looking at an override sees.
    pages_below: int
    share_below: float
    #: ``median - threshold``: the margin the document would have published with. ``None`` where
    #: there is no median.
    headroom: float | None

    def as_dict(self) -> dict[str, Any]:
        return {"threshold": self.threshold, "document_passes": self.document_passes,
                "pages_below": self.pages_below, "share_below": round(self.share_below, 6),
                "headroom": None if self.headroom is None else round(self.headroom, 6)}


@dataclass(frozen=True)
class Recommendation:
    """A proposal for :data:`~vsir.core.health.TRUST_OK_MIN`, with the reasoning attached."""

    threshold: float | None
    rationale: str
    #: The highest rung this document's own median could carry at :data:`HEADROOM`. Reported
    #: beside the recommendation because it is the evidence, and because it is **not** the same
    #: number — see :func:`recommend` on why one document may lower the bar and not raise it.
    supported: float | None = None
    #: Always true for a single document (R4). U026 re-validates at corpus scale.
    provisional: bool = True
    #: The pin as this release ships it, so the report can say whether anything would change.
    current: float = health.TRUST_OK_MIN

    @property
    def changes_the_pin(self) -> bool:
        return self.threshold is not None and self.threshold != self.current

    def as_dict(self) -> dict[str, Any]:
        return {"threshold": self.threshold, "rationale": self.rationale,
                "supported": self.supported, "provisional": self.provisional,
                "current_pin": self.current, "changes_the_pin": self.changes_the_pin}


# ── the distribution ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Distribution:
    """The `grounded_rate` distribution of one document, and every reading taken off it."""

    doc_id: str
    revision: str
    pages: tuple[PageRate, ...]
    #: Every distinct ``provenance.probe_version`` behind these pages. What wrote the text layer
    #: decides whether the rates are a measurement at all — see :data:`EXTRACTOR_PREFIX`.
    probe_versions: tuple[str, ...] = ()

    @property
    def measured_by_the_extractor(self) -> bool:
        """True where every page's text layer came from the pinned extractor over a real PDF."""
        return bool(self.probe_versions) and all(
            version.startswith(EXTRACTOR_PREFIX) for version in self.probe_versions)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def pages_with_text(self) -> int:
        return sum(1 for page in self.pages if page.has_text)

    @property
    def pages_without_text(self) -> int:
        return self.page_count - self.pages_with_text

    @property
    def measured(self) -> tuple[float, ...]:
        """The rates that exist, ascending. The `None`s are dropped, never defaulted (§5.7)."""
        return tuple(sorted(page.rate for page in self.pages if page.rate is not None))

    @property
    def fully_scanned(self) -> bool:
        """No page has a text layer, so §11.1 skips the gate rather than failing it (F4)."""
        return self.pages_with_text == 0

    @property
    def median(self) -> float | None:
        """The **gate's** median — :func:`vsir.core.health.median`, not a second implementation."""
        return health.median(page.rate for page in self.pages)

    @property
    def searchable_ratio(self) -> float:
        return health.searchable_ratio([page.has_text for page in self.pages])

    @property
    def minimum(self) -> float | None:
        measured = self.measured
        return measured[0] if measured else None

    @property
    def maximum(self) -> float | None:
        measured = self.measured
        return measured[-1] if measured else None

    @property
    def mean(self) -> float | None:
        measured = self.measured
        return sum(measured) / len(measured) if measured else None

    def percentile(self, p: int | float) -> float | None:
        """The ``p``-th percentile by **nearest rank** — always a value the corpus actually has.

        Interpolating would report a rate no page holds, which on 55 pages is a made-up number
        dressed as a measurement. Nearest rank is `rates[ceil(p/100 · n) - 1]`, so `p=0` and `p=100`
        are the minimum and maximum and every other answer is some page's own rate.
        """
        if not 0 <= p <= 100:
            raise ValueError(f"percentile {p} is not within 0..100")
        measured = self.measured
        if not measured:
            return None
        rank = max(1, math.ceil(p / 100 * len(measured)))
        return measured[rank - 1]

    def histogram(self) -> tuple[tuple[float, float, int], ...]:
        """``(low, high, count)`` per :data:`BUCKET_EDGES` bucket; the last one includes `1.0`."""
        edges = BUCKET_EDGES
        buckets = []
        for index in range(len(edges) - 1):
            low, high = edges[index], edges[index + 1]
            last = index == len(edges) - 2
            count = sum(1 for rate in self.measured
                        if low <= rate < high or (last and rate == high))
            buckets.append((low, high, count))
        return tuple(buckets)

    def trust_counts(self) -> dict[str, int]:
        """Pages per `text_trust` level, as the records carry it (§5.7)."""
        counts: dict[str, int] = {"ok": 0, "degraded": 0, "untrusted": 0, "no_text": 0}
        for page in self.pages:
            counts[page.text_trust] = counts.get(page.text_trust, 0) + 1
        return counts

    def worst(self, limit: int = WORST_PAGES) -> tuple[PageRate, ...]:
        """The lowest-rating pages that have a rate, ties broken by page number."""
        rated = [page for page in self.pages if page.rate is not None]
        return tuple(sorted(rated, key=lambda page: (page.rate, page.page_no))[:limit])

    def at(self, threshold: float) -> Candidate:
        """What ``threshold`` would have done here."""
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold {threshold} is not a share within 0..1")
        median = self.median
        measured = self.measured
        below = sum(1 for rate in measured if rate < threshold)
        return Candidate(
            threshold=threshold,
            # Skipped, not passed: §11.1 does not score a document with nothing to measure.
            document_passes=None if self.fully_scanned or median is None else median >= threshold,
            pages_below=below,
            share_below=(below / len(measured)) if measured else 0.0,
            headroom=None if median is None else median - threshold,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "revision": self.revision,
            "probe_versions": list(self.probe_versions),
            "measured_by_the_extractor": self.measured_by_the_extractor,
            "page_count": self.page_count,
            "pages_with_text": self.pages_with_text,
            "pages_without_text": self.pages_without_text,
            "searchable_ratio": round(self.searchable_ratio, 6),
            "median": self.median,
            "mean": self.mean,
            "min": self.minimum,
            "max": self.maximum,
            "percentiles": {str(p): self.percentile(p) for p in PERCENTILES},
            "histogram": [{"low": low, "high": high, "pages": count}
                          for low, high, count in self.histogram()],
            "text_trust": self.trust_counts(),
            "worst_pages": [page.as_dict() for page in self.worst()],
        }


def from_records(records: Sequence[PageRecord]) -> Distribution:
    """The distribution of one document's page records, in page order.

    Every record must name the same ``(doc_id, revision)``: a median across two documents is not a
    document's median, and a median across two revisions of one document scores pages the publish
    gate never evaluates together (§6.7). Both are refused by name rather than averaged.
    """
    if not records:
        raise NoRecords("no page records: a distribution over nothing is not a measurement")
    documents = {(record.doc_id, record.revision) for record in records}
    if len(documents) != 1:
        named = ", ".join(f"{doc_id}@{revision}" for doc_id, revision in sorted(documents))
        raise NoRecords(
            f"records span {len(documents)} (doc_id, revision) pairs — {named}. §11.1 gates one "
            f"document at a time, so a distribution over several is a number nothing gates on; "
            f"report them one at a time"
        )
    doc_id, revision = documents.pop()
    pages = tuple(
        PageRate(page_no=record.page_no, page_id=record.page_id,
                 rate=record.content.grounded_rate, has_text=record.has_text,
                 text_trust=str(record.text_trust))
        for record in sorted(records, key=lambda record: record.page_no)
    )
    return Distribution(
        doc_id=doc_id, revision=revision, pages=pages,
        probe_versions=tuple(sorted({record.provenance.probe_version for record in records})),
    )


# ── the reading ─────────────────────────────────────────────────────────────────────────────────

def sweep(distribution: Distribution,
          thresholds: Iterable[float] = LADDER) -> tuple[Candidate, ...]:
    """Every candidate threshold's verdict on this document, in ascending threshold order."""
    return tuple(distribution.at(threshold) for threshold in sorted(set(thresholds)))


def recommend(distribution: Distribution, *, ladder: Iterable[float] = LADDER,
              headroom: float = HEADROOM, current: float = health.TRUST_OK_MIN) -> Recommendation:
    """What this document's distribution supports as :data:`~vsir.core.health.TRUST_OK_MIN`.

    **The asymmetry, which is the whole judgement.** The supported ceiling is the highest rung at
    least ``headroom`` below the observed median. The *recommendation* is that ceiling capped at
    the pin the release already ships, because the two directions are not equally evidenced by one
    document:

    * **Lowering is evidenced.** A document whose median sits under the pin is direct evidence
      that real documents rate lower than the pin assumed — which is R4's first named injury, a
      gate that *"quarantines good documents"*.
    * **Raising is not.** One document rating well says nothing about the next one. Moving the bar
      up to fit it would be fitting a gate over 5,505 pages to 55 of them, and every document it
      then held would be held on a sample of one. The ceiling is still reported, as the evidence
      it is; adopting it is a decision for `vsir eval corpus` at corpus scale (§12.6, U026).

    Three distributions recommend nothing at all, and all three are findings rather than
    thresholds:

    * **not measured by the extractor** — the rates are a property of how the corpus was built
      rather than of a text layer somebody extracted (:data:`EXTRACTOR_PREFIX`). The ceiling is
      still computed and reported, because it is a fact about the corpus; it is simply not
      evidence about the gate;
    * **fully scanned** — no page has a text layer, §11.1 skips the gate, and a document that is
      never scored says nothing about where the bar belongs (F4);
    * **median below the lowest rung** — the document itself is what R3 describes, a
      `grounded_rate` collapse where the extractor missed the text. Lowering the bar to admit it
      would delete the only signal that detects a broken extractor. That is a finding about the
      ingest, not a threshold.
    """
    median = distribution.median
    if distribution.fully_scanned or median is None:
        return Recommendation(
            threshold=None,
            current=current,
            rationale=(
                f"{distribution.doc_id}@{distribution.revision}: {distribution.page_count} page(s), "
                f"none with a text layer. §11.1 skips the grounded_rate gate entirely here — the "
                f"document publishes and answers not_searchable (F4) — so it is never scored and "
                f"sets no threshold. Measure a document that has text."
            ),
        )
    rungs = sorted(rung for rung in ladder if rung <= median - headroom)
    supported = rungs[-1] if rungs else None

    if not distribution.measured_by_the_extractor:
        versions = ", ".join(distribution.probe_versions) or "none recorded"
        return Recommendation(
            threshold=None,
            supported=supported,
            current=current,
            rationale=(
                f"{distribution.doc_id}@{distribution.revision}: median {median:.4f}, but the text "
                f"layer behind it was not written by the pinned extractor (probe_version: "
                f"{versions}). R4 asks for the distribution of a real ingest, and a constructed "
                f"corpus reports its own construction: the M1 pages are hand-written, and the "
                f"`impl` baseline's text is the projection of codes the old gate had already "
                f"proved printed, so every page rates 1.0 by definition. This sets no threshold — "
                f"run the report over a `{EXTRACTOR_PREFIX}…` ingest."
            ),
        )
    if supported is None:
        return Recommendation(
            threshold=None,
            current=current,
            rationale=(
                f"{distribution.doc_id}@{distribution.revision}: median {median:.4f} over "
                f"{distribution.pages_with_text} page(s) with text is below every rung of the "
                f"ladder at {headroom} headroom. That is R3 — the extractor is the single point of "
                f"truth for exact search, and a collapse looks exactly like this. Treat it as a "
                f"finding about the ingest; do not lower the bar to admit it."
            ),
        )

    # One document may lower the bar and may not raise it — see the docstring.
    chosen = min(supported, current)
    candidate = distribution.at(chosen)
    direction = (
        f"{supported} is the highest rung at least {headroom} below that median, and the pin "
        f"already ships {current}: raising it to fit one document would fit a gate over 5,505 "
        f"pages to {distribution.page_count} of them, so the recommendation stays at {chosen}."
        if supported > current else
        f"{chosen} is the highest rung at least {headroom} below that median — under the {current} "
        f"the pin ships, which is direct evidence the bar was set above what real documents rate."
        if supported < current else
        f"{chosen} is the highest rung at least {headroom} below that median, which is exactly the "
        f"pin this release ships: the document confirms it rather than moving it."
    )
    return Recommendation(
        threshold=chosen,
        supported=supported,
        current=current,
        rationale=(
            f"{distribution.doc_id}@{distribution.revision}: median {median:.4f} over "
            f"{distribution.pages_with_text} of {distribution.page_count} page(s) with a text "
            f"layer. {direction} At {chosen}, {candidate.pages_below} page(s) "
            f"({candidate.share_below:.1%}) rate under the bar individually and the document "
            f"publishes with headroom {candidate.headroom:.4f}. Provisional: one document of "
            f"{distribution.page_count} pages is a small sample for a gate over 5,505 (R4) — "
            f"`vsir eval corpus` re-validates it, and `vsir publish --override grounded_rate` "
            f"means a mis-set bar cannot strand a document silently."
        ),
    )


def env_threshold(environ: dict[str, str] | None = None) -> float | None:
    """The candidate threshold from :data:`THRESHOLD_ENV`, or ``None`` when it is unset.

    A value that is not a share within 0..1 is a named refusal rather than a silent default: an
    operator who typed `80` meant `0.8`, and reporting against `80` would show every page failing.
    """
    raw = ((environ if environ is not None else os.environ).get(THRESHOLD_ENV) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{THRESHOLD_ENV}={raw!r} is not a number — it is a share within 0..1, "
                         f"so 0.8 rather than 80") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{THRESHOLD_ENV}={raw} is not a share within 0..1 — 0.8 rather than 80")
    return value


# ── the report ──────────────────────────────────────────────────────────────────────────────────

def _rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def report(distribution: Distribution, *, thresholds: Iterable[float] = LADDER,
           proposed: float | None = None) -> str:
    """The printed report: the distribution, the sweep, the recommendation, and the pin.

    Deterministic text over deterministic inputs — the same records print the same bytes, so the
    output belongs in a run report and in a commit message verbatim.
    """
    lines: list[str] = []
    add = lines.append

    add(f"grounded_rate distribution — {distribution.doc_id}@{distribution.revision} "
        f"(Spec §11.1, §5.7, R4)")
    add("")
    if not distribution.measured_by_the_extractor:
        add("")
        add("  ⚠ NOT A MEASUREMENT. The text layer behind these rates was not written by the")
        add(f"    pinned extractor (probe_version: "
            f"{', '.join(distribution.probe_versions) or 'none recorded'}). R4 is set from a real")
        add("    ingest; a constructed corpus reports its own construction. Read on for the shape,")
        add("    not for the threshold.")
    add("")
    add(f"  pages                {distribution.page_count}")
    add(f"  with a text layer    {distribution.pages_with_text}"
        f"   (searchable_ratio {distribution.searchable_ratio:.4f})")
    add(f"  without one          {distribution.pages_without_text}"
        f"   rate None, ignored by every aggregate (§5.7)")
    add("")
    if distribution.fully_scanned:
        add("  no page has a text layer: there is nothing to ground codes in, so §11.1 skips the")
        add("  gate rather than failing it — the document publishes and answers not_searchable (F4).")
    else:
        add(f"  median  {_rate(distribution.median)}    mean {_rate(distribution.mean)}    "
            f"min {_rate(distribution.minimum)}    max {_rate(distribution.maximum)}")
        add("")
        add("  percentiles (nearest rank, over the pages with a text layer)")
        add("    " + "  ".join(f"p{p:02d} {_rate(distribution.percentile(p))}"
                               for p in PERCENTILES))
        add("")
        add("  histogram")
        buckets = distribution.histogram()
        widest = max((count for _, _, count in buckets), default=0)
        for low, high, count in buckets:
            edge = "]" if high == BUCKET_EDGES[-1] else ")"
            note = ""
            if high == health.TRUST_UNTRUSTED_BELOW:
                note = "  untrusted"
            elif low == health.TRUST_OK_MIN:
                note = "  ok"
            # Scaled to the widest bucket so the column stays aligned on 55 pages and on 5,505.
            bar = "█" * round(count / widest * _BAR_WIDTH) if widest else ""
            add(f"    [{low:.1f}, {high:.1f}{edge}  {bar:<{_BAR_WIDTH}} {count:>4}{note}")

    counts = distribution.trust_counts()
    add("")
    add("  text_trust   " + "   ".join(f"{name} {counts.get(name, 0)}"
                                       for name in ("ok", "degraded", "untrusted", "no_text")))

    worst = distribution.worst()
    if worst:
        add("")
        add(f"  worst {len(worst)} page(s)")
        for page in worst:
            add(f"    {page.page_id}  page {page.page_no:>4}  rate {_rate(page.rate)}  "
                f"{page.text_trust}")

    add("")
    add("  candidate thresholds — what each would have done to this document")
    add("    threshold   document   headroom   pages below")
    for candidate in sweep(distribution, thresholds):
        verdict = {True: "publish", False: "HOLD", None: "skipped"}[candidate.document_passes]
        pin = "  ← the pin" if candidate.threshold == health.TRUST_OK_MIN else ""
        add(f"    {candidate.threshold:>9.2f}   {verdict:<8}   "
            f"{_rate(candidate.headroom):>8}   {candidate.pages_below:>3} "
            f"({candidate.share_below:>6.1%}){pin}")

    if proposed is not None:
        candidate = distribution.at(proposed)
        verdict = {True: "publish", False: "HOLD", None: "skipped"}[candidate.document_passes]
        add("")
        add(f"  {THRESHOLD_ENV}={proposed} → {verdict}, headroom {_rate(candidate.headroom)}, "
            f"{candidate.pages_below} page(s) below")

    suggestion = recommend(distribution)
    add("")
    ceiling = "" if suggestion.supported is None else f"   supported ceiling {suggestion.supported}"
    add(f"  recommendation  {suggestion.threshold if suggestion.threshold is not None else 'none'}"
        f"   (the pin ships {suggestion.current}){ceiling}")
    for line in _wrap(suggestion.rationale, 92):
        add(f"    {line}")
    add("")
    if suggestion.threshold is None:
        pass
    elif suggestion.changes_the_pin:
        add(f"  Adopting it is a RELEASE, not a hot edit: change vsir.core.health.TRUST_OK_MIN to")
        add(f"  {suggestion.threshold} and ship it. {THRESHOLD_ENV} is read by this report only — a")
        add(f"  deployment that could re-tune what \"trusted\" means could turn F14 back on by")
        add(f"  editing an env var (§5.7, §15 Factor III).")
    elif suggestion.threshold is not None:
        add(f"  The pin already is {suggestion.current}: this document confirms it rather than "
            f"moving it.")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    """A minimal greedy wrap. `textwrap` would do, but the report's indentation is its own."""
    out: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        out.append(line)
    return out


# ── the corpora this can read ───────────────────────────────────────────────────────────────────

def _from_payload_file(path: Path) -> tuple[PageRecord, ...]:
    """Page records from a JSON array or a JSONL file of ``PageRecord.to_payload()`` payloads.

    Strict on purpose: the rows are validated by the shipped model rather than read field by field,
    so a file that is not what the index holds is a named failure instead of a distribution over
    whatever keys happened to parse.
    """
    raw = path.read_text(encoding="utf-8")
    stripped = raw.lstrip()
    if stripped.startswith("["):
        rows = json.loads(raw)
    else:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not isinstance(rows, list):
        raise NoRecords(f"{path}: expected a JSON array or JSONL of page payloads")
    return tuple(PageRecord.from_payload(row) for row in rows)


def _corpus(arguments: argparse.Namespace) -> tuple[PageRecord, ...]:
    if arguments.records:
        return _from_payload_file(Path(arguments.records))
    if arguments.legacy:
        from vsir.eval import legacy

        baseline = legacy.load()
        # The pilot document by default: it is the one §12.3 states an acceptance table
        # for, and the one U013's re-bill re-ingests under the new schema.
        return baseline.records(arguments.doc_id or legacy.EXPECTED_DOCUMENTS[0])
    from vsir.eval import synthetic

    corpus = synthetic.load()
    return corpus.current_records(release_id="report")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vsir.eval.grounded_rate",
        description="Report the grounded_rate distribution of one document and what each "
                    "candidate publish threshold would do to it (Spec §11.1, R4).",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--records", metavar="PATH", default="",
                        help="a JSON array or JSONL file of PageRecord payloads — what an ingest "
                             "wrote, read back out of the index")
    source.add_argument("--legacy", action="store_true",
                        help="the ported `impl` baseline of §12.1 (see --doc-id)")
    source.add_argument("--synthetic", action="store_true",
                        help="the §13 M1 corpus (the default)")
    parser.add_argument("--doc-id", default="", help="which document of a multi-document corpus")
    parser.add_argument("--threshold", type=float, default=None,
                        help=f"a candidate threshold to score explicitly (or {THRESHOLD_ENV})")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    try:
        proposed = arguments.threshold if arguments.threshold is not None else env_threshold()
        records = _corpus(arguments)
        if arguments.doc_id and not arguments.legacy:
            records = tuple(record for record in records if record.doc_id == arguments.doc_id)
        distribution = from_records(records)
    except (NoRecords, ValueError, FileNotFoundError) as exc:
        print(f"grounded_rate report refused: {exc}", file=sys.stderr)
        return 2

    if arguments.json:
        payload = distribution.as_dict()
        payload["candidates"] = [candidate.as_dict() for candidate in sweep(distribution)]
        payload["recommendation"] = recommend(distribution).as_dict()
        if proposed is not None:
            payload["proposed"] = distribution.at(proposed).as_dict()
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(report(distribution, proposed=proposed))
    return 0


__all__ = [
    "BUCKET_EDGES", "EXTRACTOR_PREFIX", "HEADROOM", "LADDER", "PERCENTILES", "THRESHOLD_ENV",
    "WORST_PAGES",
    "Candidate", "Distribution", "NoRecords", "PageRate", "Recommendation",
    "env_threshold", "from_records", "main", "recommend", "report", "sweep",
]


if __name__ == "__main__":  # pragma: no cover - the module is a process, and this is its entry
    sys.exit(main())
