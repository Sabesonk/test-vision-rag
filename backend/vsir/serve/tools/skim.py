"""Deterministic fusion (D2). Ported from ``impl/app/retrieve.py::rrf`` — **ranks only**.

At this milestone this module is the fusion function alone; the three `skim_*` rungs arrive at M4
and M5. The original's docstring states the property that makes it acceptable at all:

    Reciprocal-rank fusion. RANKS ONLY — no similarity score enters the arithmetic.

That is what satisfies §7.6's refusal by construction rather than by policy. The inputs are
per-surface *positions*; a cosine distance never enters, so there is nothing to leak into a
response, and no caller can mistake a fused number for a confidence. The one thing this module
returns about ordering is an **ordinal** `rank`: a position is not a confidence.

Two changes from `impl`:

* the accumulator is not called ``score`` and the total is **never returned**. `impl` carried it out
  to the API as ``Hit.fused``; a fused float is a similarity score under another name, and the
  §12.5 conformance grep now fails the build on the field name;
* ties break deterministically. `impl` sorted on the total alone, leaving equal rows in dictionary
  insertion order. The NFR is that the same query returns the same rows **in the same order**
  (§16), so the tiebreak is explicit: best per-surface rank, then the point id.

Per-surface ranks are kept, not just which surfaces hit: they are what the fusion actually
consumed, so they are what makes a weight change explicable — and they are what `PageHit.why`
reports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from vsir.config import RRF_K, SURFACE_WEIGHTS


@dataclass(frozen=True)
class FusedRow:
    """One fused result. Carries positions and provenance of positions — never a magnitude."""

    point_id: Any
    #: The surfaces that found this point, in the order they were fused — `PageHit.why`.
    surfaces: tuple[str, ...]
    surface_ranks: dict[str, int]
    #: The ordinal position after fusion, 1-based.
    rank: int

    @property
    def best_rank(self) -> int:
        """The best position any single surface gave this point — `DocHit.best_rank`'s input."""
        return min(self.surface_ranks.values())


def _total(surface_ranks: Mapping[str, int], weights: Mapping[str, float], k: int) -> float:
    """``Σ w / (k + rank)`` — private, and the only place the arithmetic lives.

    Kept off :class:`FusedRow` deliberately: it is an ordering device, not a property of a result,
    and a number that escapes into a response is a score somebody eventually displays.
    """
    return sum(weights.get(surface, 1.0) / (k + rank)
               for surface, rank in surface_ranks.items())


def rrf(branches: Mapping[str, Sequence[Any]],
        weights: Mapping[str, float] | None = None,
        k: int = RRF_K) -> list[FusedRow]:
    """Fuse per-surface result lists into one ordered list.

    ``branches`` maps a surface name to that surface's results **in rank order** — the position in
    the list is the rank, which is the whole input. A surface weighted ``0`` is switched off and
    contributes nothing, not even its presence in ``surfaces``.
    """
    weights = dict(SURFACE_WEIGHTS if weights is None else weights)

    ranks: dict[Any, dict[str, int]] = {}
    order: list[Any] = []
    for surface, results in branches.items():
        if weights.get(surface, 1.0) == 0:
            continue                       # weight 0 = the surface is switched off
        for rank, result in enumerate(results, start=1):
            point_id = getattr(result, "id", result)
            if point_id not in ranks:
                ranks[point_id] = {}
                order.append(point_id)
            ranks[point_id].setdefault(surface, rank)

    ordered = sorted(
        order,
        key=lambda point_id: (-_total(ranks[point_id], weights, k),
                              min(ranks[point_id].values()),
                              str(point_id)),
    )
    return [
        FusedRow(point_id=point_id,
                 surfaces=tuple(ranks[point_id]),
                 surface_ranks=dict(ranks[point_id]),
                 rank=position)
        for position, point_id in enumerate(ordered, start=1)
    ]
