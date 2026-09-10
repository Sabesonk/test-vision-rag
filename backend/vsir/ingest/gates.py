"""Step 11's judgement — the five publish gates of Spec §11.1. Rewritten from ``impl/app/pipeline.py``.

`impl` ran four gates and published all-or-nothing on them. The all-or-nothing part is right and is
kept, for the reason its own guide gives:

    Suppose you publish 121 of 122 safety functions and flag the missing one. Later someone
    measures the system … the answer comes back 99.2%. **But that number is measuring an
    ingestion bug, not retrieval quality** — and it looks exactly like a retrieval score.

The four gates themselves are not kept. Two are struck outright (§2.4, §2.5 B): ``allowlist``,
which was hardcoded ``"pass": True`` and never enforced anything — `TC1E-PERIODIC` published with
54% of its identifiers withheld and passed it cleanly — and ``class_totality``, which asserted that
every identifier carried a class from the identifier grammar that C1 deletes. ``page_coverage`` and
``segment_coverage`` compared against numbers an operator typed into `corpus.yaml`, which the guide
records could not even be *expressed* over HTTP (guide 10 §4.2), so over the UI path the coverage
gate had no expectation and passed on any non-zero count.

What replaces them is five gates that measure the document against **itself** rather than against a
declaration, and that distinguish *blocking* from *disclosing*:

===================  =========================================  ==========================
gate                 metric                                     action
===================  =========================================  ==========================
``window_coverage``  pages with an S2 record ÷ page count        **block** below 1.0
``offset_check``     windows passing both §6.4 checks (I4)       **block** on any failure
``grounded_rate``    median over pages **with** ``has_text``     **block**, overridable
``text_coverage``    pages with ``has_text`` ÷ total             flag ``mostly_scanned``
``label_monotonic``  printed labels non-decreasing               flag ``label_conflict``
===================  =========================================  ==========================

**The two flagging gates are the interesting ones, and they must never block.** A fully scanned
document has no text layer to be grounded in, so `grounded_rate` is not *failed* there — it is
**not evaluated at all** (:data:`GateReport.skipped`), and the document publishes and answers
`not_searchable`. Quarantining it instead is F4: the agent is told *"that part doesn't exist"*
about a page that is in the document and simply cannot be searched. `label_monotonic` is the same
argument one step down: front matter numbered ``i, ii`` followed by ``1, 2, …`` is a normal manual,
a genuinely conflicting sequence is worth disclosing, and neither is worth refusing to publish.

**Only `grounded_rate` is overridable** (:data:`OVERRIDABLE`). It is the one gate that is a
judgement — the threshold is provisional and set from the M2b distribution (R4) — so a mis-set
number must not be able to strand a good document silently. The other two blocking gates are not
judgements: `window_coverage` below 1.0 means pages are missing from the index, and a failed
`offset_check` means the pipeline cannot say which sheet a record describes. Nothing an operator
types makes either of those safe, so neither takes an override.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from vsir.core import health
from vsir.core.record import PageRecord

#: §11.1 — the `grounded_rate` median a document must reach. **Provisional (R4)**: it is
#: `health.TRUST_OK_MIN` rather than a second literal on purpose. Two thresholds for one judgement
#: would let a page be individually trusted inside a document the gate refuses to publish, and
#: U013 sets this from the M2b distribution by moving one number.
GROUNDED_RATE_MIN = health.TRUST_OK_MIN

#: Below this share of pages with a text layer, the document is flagged `mostly_scanned`. A pin,
#: not configuration: it labels a document for a reader, and a deployment that could re-tune what
#: "mostly" means would make the flag mean something different in each environment.
MOSTLY_SCANNED_BELOW = 0.5

#: The five gates of §11.1, in evaluation order.
WINDOW_COVERAGE = "window_coverage"
OFFSET_CHECK = "offset_check"
GROUNDED_RATE = "grounded_rate"
TEXT_COVERAGE = "text_coverage"
LABEL_MONOTONIC = "label_monotonic"
GATES: tuple[str, ...] = (WINDOW_COVERAGE, OFFSET_CHECK, GROUNDED_RATE, TEXT_COVERAGE,
                          LABEL_MONOTONIC)

#: The gates `vsir publish --override <gate>` accepts. Exactly one, and the reason is in the module
#: docstring: the other two blocking gates are not judgements about a threshold.
OVERRIDABLE: tuple[str, ...] = (GROUNDED_RATE,)

#: Document-level disclosure flags. A closed list, because a flag nothing sets and a flag nothing
#: reads are the same bug and only one of them is visible (the same rule as `derive.DERIVE_FLAGS`).
FLAG_MOSTLY_SCANNED = "mostly_scanned"
FLAG_LABEL_CONFLICT = "label_conflict"
#: Stamped on **every page** of a run released past a held gate (§11.1, §4.4). A page-level flag
#: rather than a document-level one, because it travels with the evidence: whoever reads the page
#: later sees that a gate was overridden without having to find the run.
FLAG_PUBLISHED_WITH_OVERRIDE = "published_with_override"
GATE_FLAGS: tuple[str, ...] = (FLAG_MOSTLY_SCANNED, FLAG_LABEL_CONFLICT)

#: How many worst pages `grounded_rate` lists when it blocks. §11.1 says "list worst pages"; a cap
#: keeps a held 1,440-page manual's run record readable, and the run record is what a reviewer
#: opens to decide whether to override.
WORST_PAGES = 10


class OverrideRefused(ValueError):
    """``--override`` named a gate that does not take one, or was not accompanied by a reason."""

    code = "override_refused"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


@dataclass(frozen=True)
class WindowOutcome:
    """What one window of §6.2's ladder did, as the gates need to see it.

    Separate from ``ingest.window.Window`` because the gate's question is not *"which pages was
    this window given"* but *"did it come back, and did §6.4 believe it"*. A window that was
    bisected and re-billed is a **pass** carrying ``bisected=True``: the repair worked, the record
    says it happened, and F13's ladder is not a defect to hold a document for.
    """

    start: int
    end: int
    pages_returned: int = 0
    offset_ok: bool = True
    #: Which of §6.4's two checks failed — `structural`, `independent_observation`, `coverage`.
    check: str = ""
    detail: str = ""
    bisected: bool = False
    attempts: int = 1

    @property
    def label(self) -> str:
        return f"{self.start}-{self.end}"

    def as_dict(self) -> dict[str, Any]:
        return {"window": [self.start, self.end], "pages_returned": self.pages_returned,
                "offset_ok": self.offset_ok, "check": self.check, "detail": self.detail,
                "bisected": self.bisected, "attempts": self.attempts}

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "WindowOutcome":
        """Rebuild from a `vsir_runs` window point — what `vsir gates rerun` reads (§6.7, D9)."""
        span = payload.get("window") or [payload.get("start", 0), payload.get("end", 0)]
        return cls(start=int(span[0]), end=int(span[1]),
                   pages_returned=int(payload.get("pages_returned", 0)),
                   offset_ok=bool(payload.get("offset_ok", True)),
                   check=str(payload.get("check", "")), detail=str(payload.get("detail", "")),
                   bisected=bool(payload.get("bisected", False)),
                   attempts=int(payload.get("attempts", 1)))


@dataclass(frozen=True)
class GateResult:
    """One gate's verdict, its number, and the evidence behind it.

    ``evidence`` is a list of JSON-able rows rather than a rendered string because it is read by
    three different things — the CLI's table, the run record over HTTP, and a reviewer deciding
    whether to override — and a sentence formatted for one of them is unusable to the other two.
    """

    name: str
    passed: bool
    blocking: bool
    detail: str
    metric: float | None = None
    threshold: float | None = None
    #: True when the gate was **not evaluated**. Distinct from ``passed``: §11.1 skips
    #: `grounded_rate` entirely at zero text coverage, and reporting that as a pass would claim a
    #: measurement nobody made (§5.7's `None` rule, one level up).
    skipped: bool = False
    flag: str = ""
    evidence: tuple[Any, ...] = ()

    @property
    def blocks(self) -> bool:
        """Whether this result, on its own, stops the publish."""
        return self.blocking and not self.passed and not self.skipped

    def as_dict(self) -> dict[str, Any]:
        return {"pass": self.passed, "blocking": self.blocking, "detail": self.detail,
                "metric": self.metric, "threshold": self.threshold, "skipped": self.skipped,
                "flag": self.flag, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class GateReport:
    """The five results. Nothing here writes anything — the decision and the act are separate.

    That separation is what makes `vsir gates rerun` possible: the gates are a pure function of
    what is in the index and the control plane, so re-evaluating them costs nothing and cannot
    have a side effect on a document somebody is deciding about.
    """

    results: tuple[GateResult, ...] = ()

    def __getitem__(self, name: str) -> GateResult:
        for result in self.results:
            if result.name == name:
                return result
        raise KeyError(f"no such gate: {name!r} (expected one of {list(GATES)})")

    @property
    def flags(self) -> tuple[str, ...]:
        """The document-level disclosure flags the flagging gates raised, in gate order."""
        return tuple(result.flag for result in self.results if result.flag and not result.passed)

    @property
    def failures(self) -> tuple[str, ...]:
        """Every blocking gate that failed, overrides not considered."""
        return tuple(result.name for result in self.results if result.blocks)

    def blocking(self, overrides: Iterable[str] = ()) -> tuple[str, ...]:
        """The failures still standing after ``overrides``. Empty means publishable."""
        released = set(overrides)
        return tuple(name for name in self.failures if name not in released)

    def publishable(self, overrides: Iterable[str] = ()) -> bool:
        return not self.blocking(overrides)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """``gate_results`` as the run record of §6.9 carries it."""
        return {result.name: result.as_dict() for result in self.results}

    @classmethod
    def from_mapping(cls, stored: Mapping[str, Mapping[str, Any]]) -> "GateReport":
        """Rebuild from a stored run record, so `runs show` prints what was actually decided."""
        return cls(results=tuple(
            GateResult(name=name, passed=bool(row.get("pass", False)),
                       blocking=bool(row.get("blocking", False)), detail=str(row.get("detail", "")),
                       metric=row.get("metric"), threshold=row.get("threshold"),
                       skipped=bool(row.get("skipped", False)), flag=str(row.get("flag", "")),
                       evidence=tuple(row.get("evidence") or ()))
            for name, row in stored.items()))


def check_override(gate: str, reason: str) -> None:
    """§4.4 — an override names an overridable gate and carries a reason, or it is refused.

    The reason is not optional and is not defaulted. It is the only record of *why* a document
    with a failing gate is in the index, it goes into the run record and onto every page, and a
    default string would make it indistinguishable from a reason somebody actually gave.
    """
    if gate not in OVERRIDABLE:
        raise OverrideRefused(
            f"{gate!r} does not take an override. §11.1 offers exactly one, "
            f"{list(OVERRIDABLE)}: it is the gate whose threshold is a provisional judgement "
            f"(R4). {WINDOW_COVERAGE!r} failing means pages are missing from the index and "
            f"{OFFSET_CHECK!r} failing means the pipeline cannot say which sheet a record "
            f"describes — no reason an operator types makes either of those publishable",
            gate=gate, overridable=list(OVERRIDABLE))
    if not reason.strip():
        raise OverrideRefused(
            f"--override {gate} needs --reason: the reason is recorded in the run and stamped on "
            f"every page as {FLAG_PUBLISHED_WITH_OVERRIDE!r}, and it is the only thing that will "
            f"later explain why this document is in the index with a failing gate",
            gate=gate)


# ── the individual gates ─────────────────────────────────────────────────────────────────────────

def window_coverage(records: Sequence[PageRecord], page_count: int,
                    windows: Sequence[WindowOutcome] = ()) -> GateResult:
    """Pages with an S2 record ÷ page count. **Must be 1.0 after retries** (§11.1).

    Counted from the records themselves rather than by summing what the windows reported, because
    the two can disagree and only one of them is what will be in the index. A window that says it
    returned 14 forms and produced 13 records is exactly the hole this gate exists to catch.
    """
    covered = {record.page_no for record in records if 1 <= record.page_no <= page_count}
    metric = (len(covered) / page_count) if page_count else 0.0
    missing = sorted(set(range(1, page_count + 1)) - covered)
    passed = page_count > 0 and not missing
    detail = (f"{len(covered)}/{page_count} page(s) carry an S2 record"
              if passed else
              f"{len(covered)}/{page_count} page(s) carry an S2 record; "
              f"{len(missing)} missing — a document is published whole or not at all, because "
              f"half a manual in the index reports the pipeline's own incompleteness as a "
              f"property of the corpus")
    evidence = tuple(
        {"window": [w.start, w.end],
         "missing": [n for n in missing if w.start <= n <= w.end]}
        for w in windows if any(w.start <= n <= w.end for n in missing)
    ) or tuple({"page_no": n} for n in missing[:WORST_PAGES])
    return GateResult(name=WINDOW_COVERAGE, passed=passed, blocking=True, detail=detail,
                      metric=round(metric, 6), threshold=1.0, evidence=evidence)


def offset_check(windows: Sequence[WindowOutcome]) -> GateResult:
    """Every window passed **both** of §6.4's checks (I4). Any failure blocks (F7).

    The gate is a re-assertion, not the check itself: `ingest/derive.py` runs both checks as each
    window is derived and raises rather than emitting records for a window it cannot place, and
    §6.2's repair is to bisect and re-bill. What reaches here is the outcome — so a window that
    could not be repaired is still named, and the document does not publish around it.
    """
    failing = tuple(w for w in windows if not w.offset_ok)
    passed = bool(windows) and not failing
    metric = ((len(windows) - len(failing)) / len(windows)) if windows else 0.0
    bisected = tuple(w for w in windows if w.bisected)
    if not windows:
        detail = ("no window outcome was recorded, so I4 was never proved — the offset is proved "
                  "on every window or the document does not publish")
    elif passed:
        detail = (f"{len(windows)} window(s) passed both §6.4 checks"
                  + (f"; {len(bisected)} bisected and re-billed ({', '.join(w.label for w in bisected)})"
                     if bisected else ""))
    else:
        detail = (f"{len(failing)} of {len(windows)} window(s) failed §6.4: "
                  + "; ".join(f"{w.label} ({w.check or 'offset'})" for w in failing)
                  + " — bisect and re-bill, never pad and never guess the offset")
    return GateResult(name=OFFSET_CHECK, passed=passed, blocking=True, detail=detail,
                      metric=round(metric, 6), threshold=1.0,
                      evidence=tuple(w.as_dict() for w in failing))


def grounded_rate(records: Sequence[PageRecord], document: health.DocumentHealth) -> GateResult:
    """The median over pages **with a text layer** ≥ :data:`GROUNDED_RATE_MIN` (§11.1, §5.7).

    **Skipped entirely at zero text coverage.** Not failed, not defaulted to 0.0 and not scored
    against an absent median: there is nothing to be grounded in, so there is nothing to measure,
    and a fully scanned document publishes and answers `not_searchable` (F4, D3).
    """
    if document.fully_scanned:
        return GateResult(
            name=GROUNDED_RATE, passed=True, blocking=True, skipped=True,
            metric=None, threshold=GROUNDED_RATE_MIN,
            detail=(f"skipped: {document.page_count} page(s), none with a text layer. There is "
                    f"nothing to ground codes in, so there is nothing to measure — the document "
                    f"publishes and answers not_searchable rather than being quarantined (F4)"))
    median = document.grounded_median
    passed = median is not None and median >= GROUNDED_RATE_MIN
    # The worst pages are listed **only when the gate holds the document**. §11.1 asks for them as
    # the material a reviewer decides an override on; on a document that published they would be a
    # list of the five best-behaved pages in the corpus, which reads like a warning and is not one.
    worst = [] if passed else sorted(
        ((record.content.grounded_rate, record.page_no, record.page_id) for record in records
         if record.content.grounded_rate is not None),
        key=lambda row: (row[0], row[1]),
    )[:WORST_PAGES]
    detail = (f"median {median} over the {document.pages_with_text} page(s) with a text layer "
              f"(the {document.page_count - document.pages_with_text} without one rate None and "
              f"are ignored by the aggregate, §5.7)")
    if not passed:
        detail += (f" — below {GROUNDED_RATE_MIN}. Held for review: release it with "
                   f"`vsir publish --override {GROUNDED_RATE} --reason \"…\"`, which records the "
                   f"reason in the run and flags every page {FLAG_PUBLISHED_WITH_OVERRIDE}")
    return GateResult(name=GROUNDED_RATE, passed=passed, blocking=True, detail=detail,
                      metric=median, threshold=GROUNDED_RATE_MIN,
                      evidence=tuple({"page_id": page_id, "page_no": page_no, "grounded_rate": rate}
                                     for rate, page_no, page_id in worst))


def text_coverage(document: health.DocumentHealth) -> GateResult:
    """Pages with `has_text` ÷ total. **Never blocks** — it flags `mostly_scanned` (§11.1).

    The number is `searchable_ratio` (§5.7), which is also what `skim_documents` returns to the
    agent: the blind spot is disclosed at ingest and again at every query, from one computation.
    """
    ratio = document.searchable_ratio
    flagged = ratio < MOSTLY_SCANNED_BELOW
    detail = (f"{document.pages_with_text}/{document.page_count} page(s) have a text layer "
              f"(searchable_ratio {ratio:.2f})")
    if flagged:
        detail += (f" — under {MOSTLY_SCANNED_BELOW}, so the document is flagged "
                   f"{FLAG_MOSTLY_SCANNED} and published. This gate never blocks: an unsearchable "
                   f"page that is in the index answers not_searchable, and one that is not in the "
                   f"index answers 'that part does not exist' (F4)")
    return GateResult(name=TEXT_COVERAGE, passed=not flagged, blocking=False, detail=detail,
                      metric=round(ratio, 6), threshold=None,
                      flag=FLAG_MOSTLY_SCANNED)


def _numeric_label(printed: str) -> int | None:
    """The printed label as an integer, or ``None`` when it is not one.

    Roman front matter, ``A-1`` appendix numbering and an empty label all return `None` and are
    **skipped** rather than compared. A manual that runs ``i, ii, 1, 2, …`` is normal, and a
    monotonicity check that ranked ``ii`` against ``1`` would flag every document in the corpus —
    which is the fastest way to make a disclosure flag mean nothing.
    """
    stripped = printed.strip()
    return int(stripped) if stripped.isdigit() else None


def label_monotonic(records: Sequence[PageRecord]) -> GateResult:
    """Printed labels non-decreasing. **Never blocks** — it flags `label_conflict` (§11.1).

    Compared over the pages whose label is a plain integer, in page order. A decrease is a real
    signal — two chapters numbered from 1, or a page whose label was misread — and it is worth
    telling a reader about. It is not worth refusing to publish a manual over, because the label
    is a *display* fact: `page_no` is what everything addresses (§5.1).
    """
    numbered = [(record.page_no, record.content.printed_page_no,
                 _numeric_label(record.content.printed_page_no))
                for record in sorted(records, key=lambda r: r.page_no)]
    read = [(page_no, printed, value) for page_no, printed, value in numbered if value is not None]
    conflicts: list[dict[str, Any]] = []
    for (before_no, before_label, before), (after_no, after_label, after) in zip(read, read[1:]):
        if after < before:
            conflicts.append({"page_no": after_no, "printed_page_no": after_label,
                              "after_page_no": before_no, "after_printed_page_no": before_label})
    passed = not conflicts
    detail = (f"{len(read)} page(s) carry a numeric printed label"
              + (f", non-decreasing across all of them" if passed else
                 f"; {len(conflicts)} decrease(s) — flagged {FLAG_LABEL_CONFLICT}, never blocked: "
                 f"the printed label is a display fact, and page_no is what every citation "
                 f"addresses (§5.1)"))
    return GateResult(name=LABEL_MONOTONIC, passed=passed, blocking=False, detail=detail,
                      metric=float(len(conflicts)), threshold=0.0, flag=FLAG_LABEL_CONFLICT,
                      evidence=tuple(conflicts[:WORST_PAGES]))


# ── the five, together ───────────────────────────────────────────────────────────────────────────

def evaluate(*, records: Sequence[PageRecord], page_count: int,
             windows: Sequence[WindowOutcome] = (),
             document: health.DocumentHealth | None = None) -> GateReport:
    """Run all five gates of §11.1 over one document's finished records.

    ``document`` defaults to the health recomputed from the records, which is what
    `vsir gates rerun` does: the gates are then a pure function of what is **in the index**, so
    re-evaluating them needs nothing that was held in the ingesting process's memory (§15 VI).
    """
    ordered = sorted(records, key=lambda record: record.page_no)
    if document is None:
        document = health.document_health([record.content.grounded_rate for record in ordered],
                                          [record.has_text for record in ordered])
    return GateReport(results=(
        window_coverage(ordered, page_count, windows),
        offset_check(windows),
        grounded_rate(ordered, document),
        text_coverage(document),
        label_monotonic(ordered),
    ))


@dataclass(frozen=True)
class Decision:
    """What :func:`decide` concluded: publish or hold, and everything a reader needs to see why."""

    report: GateReport
    overrides: tuple[str, ...] = ()
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def publish(self) -> bool:
        return self.report.publishable(self.overrides)

    @property
    def blocked_by(self) -> tuple[str, ...]:
        return self.report.blocking(self.overrides)


def decide(report: GateReport, overrides: Iterable[str] = ()) -> Decision:
    """Fold the report and the overrides into one publish/hold decision and the flags to stamp."""
    released = tuple(dict.fromkeys(overrides))
    flags = report.flags + ((FLAG_PUBLISHED_WITH_OVERRIDE,) if released else ())
    return Decision(report=report, overrides=released, flags=flags)


__all__ = [
    "FLAG_LABEL_CONFLICT", "FLAG_MOSTLY_SCANNED", "FLAG_PUBLISHED_WITH_OVERRIDE", "GATES",
    "GATE_FLAGS", "GROUNDED_RATE", "GROUNDED_RATE_MIN", "LABEL_MONOTONIC", "MOSTLY_SCANNED_BELOW",
    "OFFSET_CHECK", "OVERRIDABLE", "TEXT_COVERAGE", "WINDOW_COVERAGE", "WORST_PAGES", "Decision",
    "GateReport", "GateResult", "OverrideRefused", "WindowOutcome", "check_override", "decide",
    "evaluate", "grounded_rate", "label_monotonic", "offset_check", "text_coverage",
    "window_coverage",
]
