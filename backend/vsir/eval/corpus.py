"""The §12.6 corpus evaluation and the D11 gates (Spec §12.6, §3 D11, §12.2 L5 · plan U026).

§12.6 is a five-row table: four ground-truth sets, five metrics, and a number each one has to
clear. D11 supplies the numbers and one sentence that decides the whole shape of this module —
*"Precision is a safety property and must be perfect; recall is a measured target."* So two of the
five gates are **stops** and three are targets, and the difference is visible in the output, in
the exit code and in what a re-baseline is allowed to touch.

`vsir eval corpus` is the command. It reads a published index and a checked-in ground-truth file
and prints one row per metric with the measurement beside the gate. It is the last unit of the
plan, and it is the only place the whole catalogue is measured rather than asserted.

── Where the numbers come from, and where they do not ──────────────────────────────────────────

The same rule `vsir eval acceptance` runs under (C10): **no measurement is written down in this
module.** Every code, every alarm number and every citation comes out of a checked-in
``corpus_truth.json`` authored from the document's own pages, and the only literals here are
**D11's gates**, which are the spec's text and are pinned in code deliberately — the same reason
:data:`~vsir.eval.abstention.CORRECTNESS_GATE` is (relaxing one should be a reviewable release,
never an environment edit). :data:`D11` and that constant are asserted equal at import, so the two
pins of ``abstention_correctness`` cannot drift.

── The two ratios, and why both are counted over (code, page) pairs ────────────────────────────

§12.6 words them per code — *"a code `lookup` returns is the printed code"*, *"printed codes
findable by `lookup`"* — and this module counts both over **occurrences**: one register row is one
(code, page) pair. A code found on the right page and also on a wrong one would score as a whole
code found under a per-code reading, and §1.1's injury is *the wrong page*, not the wrong code.
Pair-level counting is the only reading under which `code_precision = 1.00` means what §12.6 says
it means.

Both denominators are printed beside the ratio, and so is ``1/denominator`` — the smallest
non-zero miss a set can register. A set whose resolution is coarser than its gate's tolerance is
marked **underpowered**: four cross-reference tokens can *fail* a 0.99 gate and cannot evidence
it, and saying so beside a green row is the difference between a measurement and a decoration.

── Re-baselining, which is the one thing C10 is actually about ─────────────────────────────────

§12.6 permits these numbers to be *"re-baselined exactly once, from the M2b measurement, with a
recorded rationale"*. :func:`gates` is that permission, expressed so it cannot be taken silently:
a :class:`Rebaseline` carries the corpus it was measured on, the measurement, and a rationale, and
:class:`RebaselineRefused` is raised for a record missing any of them, for one that changes
nothing, and for one that would lower a **safety** floor. Precision is not a measured target — no
rationale buys a `code_precision` under 1.00 — and a re-baseline always departs from D11's own
number, never from a previously re-baselined one, so "exactly once" holds by construction.

:data:`REBASELINED` is empty in this release and the report says so: M2b's re-bill is U013, and it
is blocked on OQ-1.

── What it will not do ─────────────────────────────────────────────────────────────────────────

It **reads**. §11.4 asks for a report over the gauges and run records the pipeline already emits,
and this one triggers no ingest step and reaches no model on any path — with ``--corpus indexed``
it does not create, upsert or delete anything, and with ``--corpus synthetic`` it seeds a
collection of its own from checked-in page text and drops it in a ``finally``. There is no branch
here that could call a VLM, which `tests/api/test_eval_corpus_gates.py` holds to with a spy rather
than with a docstring.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from vsir.core import health, ids
from vsir.core.nearmiss import DEFAULT_SAMPLE
from vsir.core.record import UNSEARCHABLE_TRUST, PageRecord
from vsir.eval import abstention, current_payloads, grounded_rate, legacy, synthetic
from vsir.serve.caps import ToolError
from vsir.serve.envelope import Provenance, Status
from vsir.serve.tools.lookup import effective_scope, lookup, scope_filter
from vsir.serve.tools.resolve import resolve

#: The four verdicts a metric row can carry. `SKIP` is a first-class outcome — a set with no
#: ground truth has to be visible and must never be counted as a pass — and `BLOCKED` is D11's
#: own word for a `code_recall` under 0.90: worse than a failed target, and not the same thing as
#: the P0 stop a precision miss is.
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
BLOCKED = "BLOCKED"

#: The corpora the command can be pointed at, matching `vsir eval abstention`'s two.
CORPORA = ("synthetic", "indexed")

#: The infix naming the collection ``--corpus synthetic`` creates and drops. Its own, so this
#: command cannot disturb either other eval's corpus or a suite's.
EPHEMERAL = "eval_corpus"

#: The ground-truth file's name inside a corpus fixture directory, and the environment variable
#: that relocates it (§15 Factor III — a fixture path is deployment-varying, never a constant).
TRUTH_FILE = "corpus_truth.json"
TRUTH_ENV = "VSIR_CORPUS_TRUTH"

#: The `cap` every register and alarm `lookup` is made at. Not the default 20: `cap` bounds the
#: *page of the set* a caller is shown (§7.1), and a display bound left in place would score a
#: code printed on 30 pages as ten recall misses. §12.3 itself asks for `cap=200`, so this is a
#: cap the contract already contemplates rather than a number invented here.
CORPUS_CAP = 200

#: The four §12.6 sets, in the order they print, and the metric(s) each one produces.
SETS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "component_register": ("code_precision", "code_recall"),
    "near_miss": ("abstention_correctness",),
    "alarm_catalogue": ("alarm_label_hit",),
    "cross_references": ("xref_resolve",),
})


class TruthMissing(FileNotFoundError):
    """No ground-truth file for this corpus. A named refusal, never an empty set of rows.

    An eval that scored zero rows would report `0/0` and could be read as a pass; §12.6's whole
    point is that a set without ground truth **skips by name**. That distinction only survives if
    "the file is not there" and "the file says this set is unavailable" are different things.
    """


class TruthInvalid(ValueError):
    """The ground-truth file is there and does not describe the corpus it claims to."""


class RebaselineRefused(ValueError):
    """A gate was moved without the record C10 requires, or moved somewhere it may not go."""


# ── D11, as the spec states it ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Bound:
    """One metric's gate as §12.6's table states it: the floor, the stop, and the block."""

    #: The value at or above which the metric passes.
    floor: float
    #: A shortfall is a **P0 stop** — the injury, not a regression. `code_precision` because
    #: §12.6 says so in as many words; `abstention_correctness` because §12.4 states the same
    #: stake for its own failure ("the injury the whole design exists to prevent").
    p0: bool = False
    #: Below this the run is `BLOCKED` rather than merely failing. D11 gives one: recall at 0.90.
    block_below: float | None = None

    @property
    def safety(self) -> bool:
        """A floor of 1.00 on a P0 metric is a safety property, not a measured target (§12.6)."""
        return self.p0 and self.floor >= 1.0


#: **Spec §3 D11, transcribed.** The origin every gate is measured from and every re-baseline
#: departs from. Nothing in this module writes to it.
D11: Mapping[str, Bound] = MappingProxyType({
    "code_precision": Bound(floor=1.00, p0=True),
    "code_recall": Bound(floor=0.95, block_below=0.90),
    "abstention_correctness": Bound(floor=1.00, p0=True),
    "alarm_label_hit": Bound(floor=0.99),
    "xref_resolve": Bound(floor=0.99),
})

# Two pins of one number are one drift away from two answers. §12.4's command already holds
# `abstention_correctness` at 1.00 and this table restates it, so they are checked against each
# other at import rather than trusted to stay equal.
if D11["abstention_correctness"].floor != abstention.CORRECTNESS_GATE:  # pragma: no cover
    raise RuntimeError(
        f"D11 pins abstention_correctness at {D11['abstention_correctness'].floor} and "
        f"vsir.eval.abstention.CORRECTNESS_GATE at {abstention.CORRECTNESS_GATE} — one gate, "
        f"one number (§12.6)"
    )


@dataclass(frozen=True)
class Rebaseline:
    """§12.6's one permitted re-baseline of a gate, with the record C10 requires attached."""

    #: The new floor. Always compared against D11's, never against another re-baseline.
    floor: float
    #: The corpus the new number was measured on — M2b, by §12.6's wording.
    measured_on: str
    #: The measurement itself, as it was observed. The evidence, not the conclusion.
    measurement: str
    #: Why the gate moves. Empty is a refusal: this is the whole of C10.
    rationale: str


#: The re-baselines in force. **Empty in this release**, and the report says so: §12.6 re-baselines
#: from the M2b measurement, M2b's re-bill is U013, and U013 is blocked on OQ-1. A number here is
#: a release, reviewed as code — never an environment variable and never a flag on this command.
REBASELINED: Mapping[str, Rebaseline] = MappingProxyType({})


@dataclass(frozen=True)
class Gate:
    """A metric's bound as it is actually in force, and the record of any move from D11's."""

    metric: str
    bound: Bound
    origin: Bound
    rebaseline: Rebaseline | None = None

    @property
    def moved(self) -> bool:
        return self.bound.floor != self.origin.floor

    def verdict(self, value: float | None) -> str:
        """This metric's outcome for ``value``. ``None`` means the set never ran."""
        if value is None:
            return SKIP
        if self.bound.block_below is not None and value < self.bound.block_below:
            return BLOCKED
        return PASS if value >= self.bound.floor else FAIL

    def describe(self) -> str:
        """The gate as a reviewer reads it in the report's column."""
        word = "=" if self.bound.floor >= 1.0 else "≥"
        block = ("" if self.bound.block_below is None
                 else f", block <{self.bound.block_below:.2f}")
        return f"{word} {self.bound.floor:.2f}{block}"


def gates(rebaselined: Mapping[str, Rebaseline] = REBASELINED) -> dict[str, Gate]:
    """D11's bounds with any re-baseline applied, or :class:`RebaselineRefused` naming the gap.

    Four refusals, and each one is a way C10 gets broken quietly rather than a hypothetical:

    * a metric §12.6 does not have — a gate nothing measures cannot be reviewed;
    * a record missing its rationale, its measurement or the corpus it was measured on — §12.6
      permits the re-baseline *"with a recorded rationale"* and this is what makes that binding;
    * a record that lands on D11's own number — it moves nothing and leaves a note claiming a
      decision was taken;
    * a **lowered safety floor**. §12.6 calls precision a safety property and recall a measured
      target, so the permission to re-baseline is the permission to move a target. No rationale
      buys a `code_precision` under 1.00; that is a spec change, not a report.
    """
    in_force: dict[str, Gate] = {}
    for metric, origin in D11.items():
        record = rebaselined.get(metric)
        if record is None:
            in_force[metric] = Gate(metric=metric, bound=origin, origin=origin)
            continue
        _check_rebaseline(metric, origin, record)
        block = origin.block_below
        if block is not None and record.floor < block:
            raise RebaselineRefused(
                f"{metric}: re-baselining the floor to {record.floor} puts it under the "
                f"{block} that D11 blocks below — a gate that fails nothing above the blocking "
                f"line is not a gate (§12.6)"
            )
        in_force[metric] = Gate(
            metric=metric,
            bound=Bound(floor=record.floor, p0=origin.p0, block_below=block),
            origin=origin,
            rebaseline=record,
        )
    for metric in rebaselined:
        if metric not in D11:
            raise RebaselineRefused(
                f"{metric} is not one of §12.6's metrics ({', '.join(D11)}): a gate nothing "
                f"measures cannot be re-baselined"
            )
    return in_force


def _check_rebaseline(metric: str, origin: Bound, record: Rebaseline) -> None:
    """The three refusals that are about the record itself rather than about the number."""
    for field_name in ("rationale", "measurement", "measured_on"):
        if not str(getattr(record, field_name) or "").strip():
            raise RebaselineRefused(
                f"{metric}: a re-baseline from {origin.floor} to {record.floor} with no "
                f"{field_name.replace('_', ' ')} is exactly the silent re-baseline C10 forbids — "
                f"§12.6 permits it once, from the M2b measurement, with a recorded rationale"
            )
    if record.floor == origin.floor:
        raise RebaselineRefused(
            f"{metric}: the re-baseline lands on D11's own {origin.floor} and moves nothing, "
            f"while recording that a decision was taken. Remove it or state the number it moves to"
        )
    if origin.safety and record.floor < origin.floor:
        raise RebaselineRefused(
            f"{metric}: {origin.floor} is a safety property, not a measured target — §12.6 is "
            f"explicit that precision must be perfect. Lowering it to {record.floor} is a change "
            f"to the spec, not a re-baseline of a measurement"
        )


# ── the ground truth, as checked in ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RegisterRow:
    """One printed component: the code as the register spells it, and the pages that carry it."""

    code: str
    page_ids: tuple[str, ...]
    as_printed: str = ""


@dataclass(frozen=True)
class AlarmRow:
    """One alarm record: the number, the label as printed, and the page holding the record."""

    number: str
    label: str
    page_ids: tuple[str, ...]


@dataclass(frozen=True)
class XrefRow:
    """One cross-reference token: the citation as printed, and the page it opens."""

    citation: str
    page_ids: tuple[str, ...]
    seen_on: str = ""
    as_printed: str = ""


@dataclass(frozen=True)
class Truth:
    """A corpus's §12.6 ground truth, exactly as the checked-in file states it."""

    doc_id: str
    revision: str
    source: Path
    held_out: bool = False
    caveat: str = ""
    register: tuple[RegisterRow, ...] = ()
    alarms: tuple[AlarmRow, ...] = ()
    xrefs: tuple[XrefRow, ...] = ()
    #: Per set, why it has no rows at all. A named skip, and the only thing that makes one legal.
    unavailable: Mapping[str, str] = field(default_factory=dict)
    #: Per set, the sentence the file uses to describe what its rows are.
    sources: Mapping[str, str] = field(default_factory=dict)


def truth_path(explicit: str | os.PathLike[str] | None = None, *, doc_id: str = "",
               fixture: str = "", beside: str | os.PathLike[str] | None = None) -> Path:
    """Where the ground-truth file is: an explicit path, ``VSIR_CORPUS_TRUTH``, then the corpus.

    An explicit path or the environment variable may name the file itself or the directory holding
    it, because both are how an operator actually has it to hand — a mounted fixture directory
    (exactly as ``VSIR_FIXTURE`` and ``VSIR_SYNTHETIC_PAGES`` are mounted) or one file copied
    somewhere. ``beside`` is the corpus's own directory as that corpus resolved it, so relocating
    the pages relocates their ground truth with them; the last resort is the repository's
    ``data/fixtures/<fixture or doc_id>/``, which is where a corpus's ground truth lives beside
    the corpus and is found without configuration at all.
    """
    candidate = Path(explicit) if explicit else None
    if candidate is None:
        from_env = (os.environ.get(TRUTH_ENV) or "").strip()
        candidate = Path(from_env) if from_env else None
    if candidate is None and beside is not None:
        candidate = Path(beside)
    if candidate is not None:
        return candidate if candidate.suffix == ".json" else candidate / TRUTH_FILE
    root = Path(__file__).resolve().parents[3] / "data" / "fixtures"
    direct = root / (fixture or doc_id) / TRUTH_FILE
    if direct.is_file() or not doc_id:
        return direct
    return _discover(root, doc_id, direct)


def _discover(root: Path, doc_id: str, direct: Path) -> Path:
    """Find the ground truth for ``doc_id`` among the checked-in fixtures, by what it declares.

    A fixture directory is named after the **corpus** — ``synthetic_pages`` holds ``SYN-M1``,
    ``legacy`` holds seven documents — so a path built from a `doc_id` finds nothing for most of
    them. What identifies a ground-truth file is the ``corpus.doc_id`` inside it, so that is what
    is matched on, and the directory-name path above stays as the fast case.

    Two files claiming one document is refused rather than resolved: whichever won would decide
    every number in the report, and picking by sort order is not a decision anybody made.
    """
    found = [path for path in sorted(root.glob(f"*/{TRUTH_FILE}")) if _declares(path, doc_id)]
    if len(found) > 1:
        raise TruthInvalid(
            f"{len(found)} ground-truth files claim {doc_id} — "
            f"{', '.join(str(path) for path in found)}. Name one with --truth: whichever won a "
            f"tie would silently decide every metric in the report"
        )
    return found[0] if found else direct


def _declares(path: Path, doc_id: str) -> bool:
    """Whether ``path`` is ground truth for ``doc_id``. An unreadable file is simply not a match —
    :func:`load` reports it properly once one has been chosen."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str((raw.get("corpus") or {}).get("doc_id") or "") == doc_id


def load(explicit: str | os.PathLike[str] | None = None, *, doc_id: str = "",
         fixture: str = "", beside: str | os.PathLike[str] | None = None) -> Truth:
    """Read and validate the ground truth. Every disagreement with itself is named, never averaged.

    Validation is about one thing: a page id in the file must be a page id **of the corpus the
    file claims to describe**. A row pointing at another document or another revision would score
    `lookup` against a page it was never asked about, and the metric would be measuring the
    fixture rather than the system.
    """
    path = truth_path(explicit, doc_id=doc_id, fixture=fixture, beside=beside)
    if not path.is_file():
        raise TruthMissing(
            f"no §12.6 ground truth at {path} — write one beside the corpus or set {TRUTH_ENV} "
            f"to where it is mounted. Without it there is no register, no alarm catalogue and no "
            f"cross-reference set to measure, and a corpus report over no ground truth is not a "
            f"pass"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as refusal:
        raise TruthInvalid(f"{path}: not readable as JSON — {refusal}") from None
    corpus = raw.get("corpus") or {}
    declared_doc = str(corpus.get("doc_id") or "")
    declared_revision = str(corpus.get("revision") or "")
    if not declared_doc or not declared_revision:
        raise TruthInvalid(f"{path}: corpus.doc_id and corpus.revision name what the sets are "
                           f"ground truth *for*, and one of them is missing")
    if doc_id and declared_doc != doc_id:
        raise TruthInvalid(f"{path}: ground truth for {declared_doc}, asked for {doc_id}")

    def pages(row: Mapping[str, Any], what: str) -> tuple[str, ...]:
        listed = [str(page_id) for page_id in (row.get("page_ids") or [])]
        if not listed:
            raise TruthInvalid(f"{path}: {what} names no page — a ground-truth row whose answer "
                               f"is unstated cannot be scored")
        for page_id in listed:
            try:
                page_doc, page_revision, _page_no = ids.parse_page_id(page_id)
            except ValueError as refusal:
                raise TruthInvalid(f"{path}: {what} — {page_id} is not a page id "
                                   f"({refusal})") from None
            if (page_doc, page_revision) != (declared_doc, declared_revision):
                raise TruthInvalid(
                    f"{path}: {what} points at {page_doc}@{page_revision} while the file is "
                    f"ground truth for {declared_doc}@{declared_revision}"
                )
        return tuple(listed)

    unavailable: dict[str, str] = {}
    sources: dict[str, str] = {}
    for set_name in SETS:
        if set_name == "near_miss":
            continue
        block = raw.get(set_name) or {}
        reason = str(block.get("unavailable") or "").strip()
        if reason:
            unavailable[set_name] = reason
        sources[set_name] = str(block.get("source") or "")

    register = tuple(
        RegisterRow(code=str(row["code"]), page_ids=pages(row, f'register row "{row.get("code")}"'),
                    as_printed=str(row.get("as_printed") or ""))
        for row in ((raw.get("component_register") or {}).get("rows") or [])
    )
    alarms = tuple(
        AlarmRow(number=str(row["number"]), label=str(row.get("label") or row["number"]),
                 page_ids=pages(row, f'alarm record {row.get("number")}'))
        for row in ((raw.get("alarm_catalogue") or {}).get("records") or [])
    )
    xrefs = tuple(
        XrefRow(citation=str(row["citation"]),
                page_ids=pages(row, f'cross-reference "{row.get("citation")}"'),
                seen_on=str(row.get("seen_on") or ""),
                as_printed=str(row.get("as_printed") or ""))
        for row in ((raw.get("cross_references") or {}).get("tokens") or [])
    )
    for set_name, rows in (("component_register", register), ("alarm_catalogue", alarms),
                           ("cross_references", xrefs)):
        if not rows and set_name not in unavailable:
            raise TruthInvalid(
                f"{path}: {set_name} has no rows and no `unavailable` reason. §12.6 allows a set "
                f"to be missing and does not allow it to be silent — state why, and the report "
                f"skips it by name"
            )
    return Truth(doc_id=declared_doc, revision=declared_revision, source=path,
                 held_out=bool(corpus.get("held_out", False)),
                 caveat=str(corpus.get("caveat") or ""),
                 register=register, alarms=alarms, xrefs=xrefs,
                 unavailable=MappingProxyType(unavailable), sources=MappingProxyType(sources))


# ── the measurement ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Finding:
    """One pair that went wrong, named. The first question a red row raises is *which one*."""

    subject: str
    page_id: str
    detail: str

    def __str__(self) -> str:
        return f"{self.subject} → {self.page_id or '—'}: {self.detail}"


@dataclass(frozen=True)
class Metric:
    """One §12.6 metric: the ratio, the gate, the verdict, and everything that went wrong."""

    name: str
    set_name: str
    gate: Gate
    numerator: int = 0
    denominator: int = 0
    #: Pairs the system returned that the ground truth does not contain. Precision's offenders.
    wrong: tuple[Finding, ...] = ()
    #: Pairs the ground truth contains that the system did not return. Recall's misses.
    missed: tuple[Finding, ...] = ()
    #: Why this metric was not measured at all. Named, never blank — see :class:`TruthMissing`.
    skip_reason: str = ""
    #: What the measurement does **not** evidence, printed beside it.
    caveat: str = ""

    @property
    def value(self) -> float | None:
        """The ratio, or ``None`` where nothing was measured.

        A zero denominator is ``None`` and never `1.00`: a set that scored no pair proved nothing,
        and the one arithmetic accident that could turn an absent corpus into a green gate is
        `0/0 = 1`.
        """
        if self.skip_reason or not self.denominator:
            return None
        return self.numerator / self.denominator

    @property
    def outcome(self) -> str:
        return SKIP if self.skip_reason else self.gate.verdict(self.value)

    @property
    def p0_stop(self) -> bool:
        """A shortfall on a safety metric. §12.6's *"any miss is a P0 stop"*."""
        return self.gate.bound.p0 and self.outcome in (FAIL, BLOCKED)

    @property
    def resolution(self) -> float | None:
        """``1/denominator`` — the smallest non-zero shortfall this set can register."""
        return 1 / self.denominator if self.denominator else None

    @property
    def underpowered(self) -> bool:
        """Whether the set is too small to evidence its own gate.

        Only ever true of a **target**: a floor under 1.00 leaves a tolerance, and a sample whose
        single miss costs more than that tolerance can fail the gate but can never demonstrate a
        value between the floor and 1.00. A `= 1.00` gate has no such gap — "no miss in n" is
        exactly what it asks — so a safety metric is never marked underpowered, only reported with
        its `n`.
        """
        resolution = self.resolution
        if resolution is None or self.gate.bound.floor >= 1.0:
            return False
        return resolution > 1 - self.gate.bound.floor


@dataclass(frozen=True)
class ThresholdCheck:
    """R4 — what the indexed corpus says about the `grounded_rate` publish bar (§11.1, C10)."""

    pin: float
    distribution: grounded_rate.Distribution | None = None
    recommendation: grounded_rate.Recommendation | None = None
    refusal: str = ""


@dataclass(frozen=True)
class Report:
    """The §12.6 report: every metric, the R4 re-validation, and what none of it covers."""

    doc_id: str
    revision: str
    collection: str
    pages: int = 0
    truth_source: str = ""
    held_out: bool = False
    caveat: str = ""
    metrics: tuple[Metric, ...] = ()
    #: Per set, the ground-truth file's own sentence about what its rows are. Printed above the
    #: set's first metric, because *"measured against what?"* is the first question an L5 report
    #: has to answer and a file path alone does not answer it.
    sources: Mapping[str, str] = field(default_factory=dict)
    threshold: ThresholdCheck | None = None
    #: R7 — the §7/§8 paths the ported baseline says nothing about (U012), printed beside the
    #: metrics so a green report is never read as coverage of them.
    no_coverage: tuple[str, ...] = ()
    #: Why the report could not be produced at all. A refusal is never a pass.
    refusals: tuple[str, ...] = ()

    @property
    def measured(self) -> tuple[Metric, ...]:
        return tuple(metric for metric in self.metrics if metric.outcome != SKIP)

    @property
    def skipped(self) -> tuple[Metric, ...]:
        return tuple(metric for metric in self.metrics if metric.outcome == SKIP)

    @property
    def failed(self) -> tuple[Metric, ...]:
        return tuple(metric for metric in self.metrics if metric.outcome in (FAIL, BLOCKED))

    @property
    def blocked(self) -> tuple[Metric, ...]:
        return tuple(metric for metric in self.metrics if metric.outcome == BLOCKED)

    @property
    def p0_stops(self) -> tuple[Metric, ...]:
        return tuple(metric for metric in self.metrics if metric.p0_stop)

    @property
    def rebaselines(self) -> tuple[Rebaseline, ...]:
        return tuple(metric.gate.rebaseline for metric in self.metrics
                     if metric.gate.rebaseline is not None)

    @property
    def ok(self) -> bool:
        """Green means: nothing refused, nothing failed, and **something was measured**.

        The last clause is the one that matters. Every set skipping by name is honest output and
        it is not a passing report — it is a report that measured nothing, which is the state
        §12.6 exists to make impossible to mistake for a result.
        """
        return not self.refusals and not self.failed and bool(self.measured)


def evaluate(client: Any, collection: str, truth: Truth, *, provenance: Provenance,
             in_force: Mapping[str, Gate] | None = None, sample: int = DEFAULT_SAMPLE,
             runs_collection: str = "") -> Report:
    """Measure §12.6's five metrics over one indexed corpus. Reads only.

    ``in_force`` is the gate table; it defaults to D11 with :data:`REBASELINED` applied and is a
    parameter so the L2 suite can drive the arithmetic across its own boundaries without moving a
    gate this release ships.
    """
    in_force = dict(in_force if in_force is not None else gates())
    payloads = current_payloads(client, collection, doc_id=truth.doc_id)
    if not payloads:
        return Report(
            doc_id=truth.doc_id, revision=truth.revision, collection=collection,
            truth_source=str(truth.source),
            refusals=(f"{truth.doc_id} has no current page in {collection}: §12.6 measures a "
                      f"published index and there is nothing published to measure",),
        )

    # The pages as the index holds them, by id. A recall miss is explained from the page's **own**
    # record — `text_trust`, `has_text` — not from the status of the document-wide query: an
    # unsearchable page inside a searchable document answers `not_found` (§5.7, and
    # `expected.json`'s `no_text` row), so the response alone would explain the miss wrongly.
    pages = {str((payload.get("provenance") or {}).get("page_id") or ""): payload
             for payload in payloads}

    metrics = [
        *_register_metrics(client, collection, truth, in_force, provenance=provenance,
                           runs_collection=runs_collection, pages=pages),
        _near_miss_metric(client, collection, truth, in_force, provenance=provenance,
                          sample=sample),
        _alarm_metric(client, collection, truth, in_force, provenance=provenance,
                      runs_collection=runs_collection, pages=pages),
        _xref_metric(client, collection, truth, in_force, provenance=provenance),
    ]
    return Report(
        doc_id=truth.doc_id, revision=truth.revision, collection=collection,
        pages=len(payloads), truth_source=str(truth.source), held_out=truth.held_out,
        caveat=truth.caveat, metrics=tuple(metrics), sources=truth.sources,
        threshold=_threshold_check(payloads),
        no_coverage=legacy.NO_LEGACY_COVERAGE,
    )


def _skip(metric: str, set_name: str, gate: Gate, reason: str) -> Metric:
    return Metric(name=metric, set_name=set_name, gate=gate, skip_reason=reason)


def _register_metrics(client: Any, collection: str, truth: Truth,
                      in_force: Mapping[str, Gate], *, provenance: Provenance,
                      runs_collection: str, pages: Mapping[str, Mapping[str, Any]]) -> list[Metric]:
    """`code_precision` and `code_recall` over the component register, per (code, page) pair."""
    precision_gate, recall_gate = in_force["code_precision"], in_force["code_recall"]
    unavailable = truth.unavailable.get("component_register", "")
    if unavailable or not truth.register:
        reason = unavailable or "the ground truth lists no register row"
        return [_skip("code_precision", "component_register", precision_gate, reason),
                _skip("code_recall", "component_register", recall_gate, reason)]

    returned = 0
    correct = 0
    expected = 0
    wrong: list[Finding] = []
    missed: list[Finding] = []
    for row in truth.register:
        response = _lookup(client, collection, row.code, truth.doc_id, provenance=provenance,
                           runs_collection=runs_collection)
        found = {hit.page_id for hit in response.hits}
        want = set(row.page_ids)
        returned += len(found)
        correct += len(found & want)
        expected += len(want)
        wrong += [Finding(row.code, page_id,
                          f"{row.code} is not printed on this page — the register places it on "
                          f"{', '.join(row.page_ids)}")
                  for page_id in sorted(found - want)]
        missed += [Finding(row.code, page_id,
                           _why_missed(response, pages.get(page_id),
                                       row.as_printed or row.code))
                   for page_id in sorted(want - found)]

    if not returned:
        # Precision over zero returned pairs is not 1.00 and it is not 0.00 — the surface
        # answered nothing at all, so there is no pair whose correctness could be scored. Naming
        # it is the only honest outcome; `code_recall` below is where a silent index shows up.
        precision = _skip(
            "code_precision", "component_register", precision_gate,
            f"`lookup` returned no page for any of the {len(truth.register)} register row(s): "
            f"precision is undefined over zero returned pairs, and reporting 0/0 as 1.00 is the "
            f"one arithmetic accident that turns an empty index into a perfect safety score. "
            f"Read code_recall below")
    else:
        precision = Metric(
            name="code_precision", set_name="component_register", gate=precision_gate,
            numerator=correct, denominator=returned, wrong=tuple(wrong),
            caveat="one register row is one (code, page) pair: a code returned on the right "
                   "page and a wrong one is a precision miss, not a found code")

    return [
        precision,
        Metric(name="code_recall", set_name="component_register", gate=recall_gate,
               numerator=correct, denominator=expected, missed=tuple(missed)),
    ]


def _why_missed(response: Any, page: Mapping[str, Any] | None, printed: str) -> str:
    """Why this printed code did not come back on **this** page.

    The page's own record answers first and the query's status second, because the two disagree
    in exactly the case that matters: an unsearchable page inside a searchable document makes the
    document-wide `lookup` answer `not_found`, and reporting that back as *"the page is
    searchable and does not contain the phrase"* would send a reader looking for a tokenisation
    bug that is not there (§5.7).
    """
    if page is None:
        return (f"{response.status.value} — and the index holds no current page with this id at "
                f"all, so the ground-truth row names a page that is not published")
    if not page.get("has_text", False):
        return ("the page has no text layer (§5.7), so `lookup` cannot search it and abstains "
                "rather than guessing. This code is reachable through `vlm_codes` (D3), which is "
                "opt-in and permanently verified:false, or by reading the image")
    if str(page.get("text_trust", "")) in UNSEARCHABLE_TRUST:
        return (f"the page's text layer is {page.get('text_trust')} (§5.7), so it is excluded "
                f"from the exact surface. A recall miss the corpus caused, not the index: the "
                f"code is reachable through `vlm_codes` (D3) or a `read`")
    if response.status == Status.FOUND_ONLY_IN_SUPERSEDED:
        return "found_only_in_superseded — the code is carried by a revision no longer current (F9)"
    if response.status == Status.ERROR:
        return "error — the store refused the query, so nothing was measured here"
    return (f"the page is searchable and its text does not contain the phrase {printed!r} "
            f"({response.status.value}). This is a recall miss to explain, not to tune away")


def _near_miss_metric(client: Any, collection: str, truth: Truth, in_force: Mapping[str, Gate], *,
                      provenance: Provenance, sample: int) -> Metric:
    """`abstention_correctness` — §12.4's eval, run through its own module rather than again."""
    gate = in_force["abstention_correctness"]
    report = abstention.evaluate(client, collection, provenance=provenance, doc_id=truth.doc_id,
                                 sample=sample)
    if report.refusal:
        return _skip("abstention_correctness", "near_miss", gate, report.refusal)
    wrong = tuple(Finding(leak.miss.fake, "", f"{leak.surface}: {leak.detail} "
                                              f"(one character off {leak.miss.source})")
                  for leak in report.leaks)
    missed = tuple(Finding(source, "", "the real code the fakes were mutated from stopped being "
                                       "findable — an eval of absences over a broken index would "
                                       "pass every row")
                   for source in report.unfindable_sources)
    return Metric(name="abstention_correctness", set_name="near_miss", gate=gate,
                  numerator=report.abstained, denominator=report.sample,
                  wrong=wrong, missed=missed,
                  caveat=f"derived from the observed-token inventory of {report.observed_tokens} "
                         f"token(s) (§6.8), so OQ-4's 8,414-pair list is not required")


def _alarm_metric(client: Any, collection: str, truth: Truth, in_force: Mapping[str, Gate], *,
                  provenance: Provenance, runs_collection: str,
                  pages: Mapping[str, Mapping[str, Any]]) -> Metric:
    """`alarm_label_hit` — each catalogued number lands the page holding its record."""
    gate = in_force["alarm_label_hit"]
    unavailable = truth.unavailable.get("alarm_catalogue", "")
    if unavailable or not truth.alarms:
        return _skip("alarm_label_hit", "alarm_catalogue", gate,
                     unavailable or "the ground truth lists no alarm record")

    landed = 0
    missed: list[Finding] = []
    for row in truth.alarms:
        response = _lookup(client, collection, row.label, truth.doc_id, provenance=provenance,
                           runs_collection=runs_collection)
        found = {hit.page_id for hit in response.hits}
        want = set(row.page_ids)
        if want <= found:
            landed += 1
            continue
        missed += [Finding(f"alarm {row.number}", page_id,
                           _why_missed(response, pages.get(page_id), row.label))
                   for page_id in sorted(want - found)]
    return Metric(name="alarm_label_hit", set_name="alarm_catalogue", gate=gate,
                  numerator=landed, denominator=len(truth.alarms), missed=tuple(missed))


def _xref_metric(client: Any, collection: str, truth: Truth, in_force: Mapping[str, Gate], *,
                 provenance: Provenance) -> Metric:
    """`xref_resolve` — the page a citation opens is among the candidates `resolve` returns.

    *Among*, not *equal to*, and that is F5 rather than a looser bar: ambiguity returns every
    candidate, and a metric that demanded a single hit would score the refusal to pick as a miss
    and reward the silent pick F5 exists to forbid. The candidate count is carried into the
    report so an answer that came back with twenty pages beside it is visible.
    """
    gate = in_force["xref_resolve"]
    unavailable = truth.unavailable.get("cross_references", "")
    if unavailable or not truth.xrefs:
        return _skip("xref_resolve", "cross_references", gate,
                     unavailable or "the ground truth lists no cross-reference token")

    resolved = 0
    missed: list[Finding] = []
    for row in truth.xrefs:
        try:
            response = resolve(client, collection, row.citation, doc_id=truth.doc_id,
                               provenance=provenance)
        except ToolError as refusal:
            missed += [Finding(row.citation, page_id, f"{refusal.code}: {refusal}")
                       for page_id in row.page_ids]
            continue
        found = {hit.page_id for hit in response.hits}
        want = set(row.page_ids)
        if want <= found:
            resolved += 1
            continue
        missed += [Finding(row.citation, page_id,
                           f"resolve returned {sorted(found) or 'nothing'} "
                           f"({response.status.value})")
                   for page_id in sorted(want - found)]
    return Metric(name="xref_resolve", set_name="cross_references", gate=gate,
                  numerator=resolved, denominator=len(truth.xrefs), missed=tuple(missed))


def _lookup(client: Any, collection: str, label: str, doc_id: str, *, provenance: Provenance,
            runs_collection: str) -> Any:
    """One register or alarm `lookup`, scoped to the document the ground truth is about.

    Scoped because the ground truth is one document's: a second binder printing the same code
    would otherwise register as a precision miss against a register that never claimed to cover
    it. ``include_unverified`` stays **false** — a `vlm_codes` hit is `verified: false` by
    construction (D3), and counting one as a found code would put model output into a recall
    number the whole of I2 keeps it out of.
    """
    return lookup(client, collection, label, scope={"doc_id": doc_id}, cap=CORPUS_CAP,
                  provenance=provenance, runs_collection=runs_collection)


def _threshold_check(payloads: Sequence[Mapping[str, Any]]) -> ThresholdCheck:
    """R4 — the `grounded_rate` distribution of what is indexed, against the shipped pin.

    §12.6's report is where the threshold set from 55 pages is re-validated at corpus scale, and
    the judgement itself is :func:`~vsir.eval.grounded_rate.recommend`'s — including its refusal
    to propose anything off a corpus the pinned extractor did not write. Nothing is decided here;
    the recommendation and its rationale are printed, and adopting one is a release.
    """
    try:
        records = [PageRecord.from_payload(dict(payload)) for payload in payloads]
        distribution = grounded_rate.from_records(records)
    except (grounded_rate.NoRecords, ValueError) as refusal:
        return ThresholdCheck(pin=health.TRUST_OK_MIN, refusal=str(refusal))
    return ThresholdCheck(pin=health.TRUST_OK_MIN, distribution=distribution,
                          recommendation=grounded_rate.recommend(distribution))


# ── the command ─────────────────────────────────────────────────────────────────────────────────

def run(client: Any, *, base: str, dim: int, release_id: str, corpus: str = "synthetic",
        collection: str = "", doc_id: str = "", sample: int = DEFAULT_SAMPLE,
        truth_dir: str | os.PathLike[str] | None = None,
        runs_collection: str = "",
        synthetic_dir: str | os.PathLike[str] | None = None) -> Report:
    """Load the ground truth, measure, and leave the index exactly as it was.

    ``--corpus indexed`` is the L5 shape: it reads the configured serving collection and creates,
    upserts and deletes nothing. ``--corpus synthetic`` seeds the §13 M1 pages into a collection
    of its own and drops it in a ``finally``, so the gates are runnable — and the arithmetic
    reviewable — on a machine with no ingested corpus at all.
    """
    try:
        in_force = gates()
    except RebaselineRefused as refusal:
        return Report(doc_id=doc_id, revision="", collection=collection,
                      refusals=(f"the gate table is refused: {refusal}",))

    if corpus == "indexed":
        target = collection or f"{base}_{dim}"
        provenance = Provenance(release_id=release_id)
        try:
            exists = client.collection_exists(target)
        except Exception as refusal:  # noqa: BLE001 - anything here is "no reachable store"
            return Report(doc_id=doc_id, revision="", collection=target,
                          refusals=(f"could not reach the store: {type(refusal).__name__}: "
                                    f"{refusal}",))
        if not exists:
            return Report(doc_id=doc_id, revision="", collection=target,
                          refusals=(f"{target} does not exist: nothing is indexed, so §12.6 has "
                                    f"no corpus to measure",))
        resolved = doc_id or _sole_document(client, target)
        if not resolved:
            return Report(doc_id="", revision="", collection=target,
                          refusals=(f"{target} holds no document, or more than one and none was "
                                    f"named: §12.6's sets are one document's ground truth, so "
                                    f"name it with --doc-id",))
        try:
            truth = load(truth_dir, doc_id=resolved)
        except (TruthMissing, TruthInvalid) as refusal:
            return Report(doc_id=resolved, revision="", collection=target,
                          refusals=(str(refusal),))
        return evaluate(client, target, truth, provenance=provenance, in_force=in_force,
                        sample=sample, runs_collection=runs_collection)

    try:
        pages = synthetic.load(synthetic_dir)
        truth = load(truth_dir, doc_id=pages.doc_id, fixture="synthetic_pages",
                     beside=pages.source)
    except (synthetic.FixtureMissing, TruthMissing, TruthInvalid) as refusal:
        return Report(doc_id="", revision="", collection="",
                      refusals=(f"corpus refused: {refusal}",))
    target = synthetic.synthetic_collection(f"{base}_{EPHEMERAL}", dim)
    provenance = Provenance(run_id=synthetic.SEED_RUN_ID, release_id=release_id)
    try:
        synthetic.seed(client, target, pages.records(release_id=release_id), dim=dim)
    except Exception as refusal:  # noqa: BLE001 - anything here is "no reachable store"
        return Report(doc_id=pages.doc_id, revision=pages.revision, collection=target,
                      refusals=(f"could not seed {target}: {type(refusal).__name__}: {refusal}",))
    try:
        return evaluate(client, target, truth, provenance=provenance, in_force=in_force,
                        sample=sample)
    finally:
        synthetic.drop(client, target)


def _sole_document(client: Any, collection: str) -> str:
    """The one **current** document in ``collection``, or empty where there is not exactly one.

    Faceted on the index rather than counted in this process, for register E9's reason: a count
    taken off a bounded scroll is a statement about the scroll. The filter comes from
    :func:`~vsir.serve.tools.lookup.effective_scope`, which is the one place `is_current` is
    injected (I7) — a retired document must not become the corpus this report is about.
    """
    try:
        hits = client.facet(collection, key="doc_id",
                            facet_filter=scope_filter(effective_scope(None)),
                            limit=2, exact=True).hits
    except Exception:  # noqa: BLE001 - an unreachable or unindexed store is "cannot tell"
        return ""
    return str(hits[0].value) if len(hits) == 1 else ""


#: Column widths. Public for the same reason `acceptance`'s are: the L2 suite has to be able to
#: read the metric, the measurement and the gate apart to assert they are three columns.
METRIC_WIDTH = 24
SET_WIDTH = 20
VALUE_WIDTH = 20
GATE_WIDTH = 20


def print_report(report: Report) -> None:
    """The reviewable output: one row per §12.6 metric, then everything that qualifies it."""
    if report.refusals:
        for refusal in report.refusals:
            print(f"\n   corpus report refused: {refusal}")
        print("\ncorpus: not measured — a report that produced no evidence is not a pass")
        return

    print(f"\nCORPUS — {report.doc_id}@{report.revision} in {report.collection}, "
          f"{report.pages} current page(s)")
    print(f"  ground truth: {report.truth_source}")
    print(f"  held out: {'yes' if report.held_out else 'NO'}"
          + ("" if report.held_out else " — §12.2 L5 asks for a document nobody tuned against"))
    if report.caveat:
        for line in _wrap(report.caveat, 96):
            print(f"  {line}")

    print(f"\n{'METRIC':<{METRIC_WIDTH}} {'SET':<{SET_WIDTH}} {'MEASURED':<{VALUE_WIDTH}} "
          f"{'D11 GATE':<{GATE_WIDTH}} VERDICT")
    described: set[str] = set()
    for metric in report.metrics:
        source = report.sources.get(metric.set_name, "")
        if source and metric.set_name not in described:
            described.add(metric.set_name)
            for line in _wrap(f"{metric.set_name} · {source}", 94):
                print(f"  {line}")
        value = metric.value
        measured = ("—" if value is None
                    else f"{value:.4f}  {metric.numerator}/{metric.denominator}")
        print(f"{metric.name:<{METRIC_WIDTH}} {metric.set_name:<{SET_WIDTH}} "
              f"{measured:<{VALUE_WIDTH}} {metric.gate.describe():<{GATE_WIDTH}} "
              f"{metric.outcome}")
        if metric.gate.rebaseline is not None:
            record = metric.gate.rebaseline
            print(f"  re-baselined {metric.gate.origin.floor:.2f} → {record.floor:.2f} on "
                  f"{record.measured_on} ({record.measurement})")
            for line in _wrap(f"rationale: {record.rationale}", 94):
                print(f"    {line}")
        if metric.skip_reason:
            for line in _wrap(f"SKIP · {metric.skip_reason}", 94):
                print(f"  {line}")
        if metric.underpowered:
            for line in _wrap(f"underpowered · one miss costs {metric.resolution:.4f} against a "
                              f"tolerance of {1 - metric.gate.bound.floor:.4f}: this set can "
                              f"FAIL the gate and cannot evidence it", 94):
                print(f"  {line}")
        if metric.caveat:
            for line in _wrap(metric.caveat, 94):
                print(f"  {line}")
        for finding in metric.wrong:
            _print_finding("! wrong ", finding)
        for finding in metric.missed:
            _print_finding("- missed", finding)

    if report.p0_stops:
        print("\nP0 STOP — §12.6: precision is a safety property and must be perfect")
        for metric in report.p0_stops:
            value = metric.value
            print(f"  {metric.name} is {'—' if value is None else f'{value:.4f}'}, not "
                  f"{metric.gate.bound.floor:.2f}. Every offending pair:")
            for finding in (metric.wrong or metric.missed):
                _print_finding("  !     ", finding)
        print("  Stop. This is the injury the whole design exists to prevent (§1.1, §12.4) — "
              "do not re-baseline it (§12.6, C10).")

    if report.blocked:
        print("\nBLOCKED — D11 blocks the run below these floors, which is worse than a failed "
              "target")
        for metric in report.blocked:
            print(f"  {metric.name} {metric.value:.4f} < {metric.gate.bound.block_below:.2f}")

    _print_threshold(report.threshold)

    if not report.rebaselines:
        print(f"\nRE-BASELINE — none in force. §12.6 permits one, from the M2b measurement, with "
              f"a recorded rationale; M2b's re-bill is U013 and is blocked on OQ-1, so every gate "
              f"above is D11's own number.")

    if report.no_coverage:
        print(f"\nNO LEGACY COVERAGE — {len(report.no_coverage)} area(s) the ported baseline says "
              f"nothing about (R7). A green report above is not sign-off on these")
        for line in report.no_coverage:
            print(f"  - {line}")

    print(f"\ncorpus: {len(report.measured)} measured, {len(report.failed)} failed, "
          f"{len(report.skipped)} skipped — {'PASS' if report.ok else 'FAIL'}")


def _print_finding(marker: str, finding: Finding) -> None:
    """One offending pair, wrapped: the subject and page on the first line, the reason under it.

    Two lines rather than one, because the reason is a sentence and the subject is the thing a
    reader scans for. A single overflowing line hides both.
    """
    print(f"  {marker} {finding.subject} → {finding.page_id or '—'}")
    for line in _wrap(finding.detail, 88):
        print(f"  {' ' * len(marker)}   {line}")


def _print_threshold(check: ThresholdCheck | None) -> None:
    """R4's re-validation block: the distribution, the pin, and what the corpus supports."""
    if check is None:
        return
    print(f"\nR4 — the grounded_rate publish bar, re-validated against this corpus "
          f"(pin: {check.pin})")
    if check.refusal:
        for line in _wrap(check.refusal, 94):
            print(f"  {line}")
        return
    distribution = check.distribution
    recommendation = check.recommendation
    if distribution is not None:
        median = distribution.median
        print(f"  {distribution.page_count} page(s), {distribution.pages_with_text} with text, "
              f"median {'—' if median is None else f'{median:.4f}'}, "
              f"searchable_ratio {distribution.searchable_ratio:.4f}")
    if recommendation is not None:
        for line in _wrap(recommendation.rationale, 94):
            print(f"  {line}")
        print(f"  recommendation: "
              + ("no change — the pin stays where the release ships it"
                 if not recommendation.changes_the_pin
                 else f"move TRUST_OK_MIN {recommendation.current} → {recommendation.threshold}, "
                      f"which is a release and a recorded rationale (C10)"))


def _wrap(text: str, width: int) -> list[str]:
    """Wrap on word boundaries. The report is read in a terminal, not piped into a parser."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
