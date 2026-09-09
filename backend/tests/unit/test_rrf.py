"""L0 — reciprocal-rank fusion (D2, §7.6). Ranks in, an ordering out, no magnitude anywhere."""
from __future__ import annotations

import inspect

from vsir.config import RRF_K, SURFACE_WEIGHTS
from vsir.serve.tools import skim
from vsir.serve.tools.skim import FusedRow, rrf


def test_the_pinned_fusion_parameters():
    assert RRF_K == 60
    assert dict(SURFACE_WEIGHTS) == {"page": 1.0, "lexical": 1.0, "captions": 0.4}


def test_the_total_matches_the_hand_computed_sum():
    """`Σ w / (k + rank)` at k=60, computed by hand against the private ordering function."""
    weights = dict(SURFACE_WEIGHTS)

    assert skim._total({"page": 1}, weights, 60) == 1.0 / 61
    assert skim._total({"page": 1, "lexical": 2}, weights, 60) == 1.0 / 61 + 1.0 / 62
    assert skim._total({"captions": 1}, weights, 60) == 0.4 / 61
    assert skim._total({"page": 3, "captions": 1}, weights, 60) == 1.0 / 63 + 0.4 / 61


def test_the_order_is_the_hand_computed_order():
    """a and b tie exactly (1/61 + 1/62 both ways); c is lower. The tie breaks deterministically."""
    rows = rrf({"page": ["a", "b", "c"], "lexical": ["b", "a"], "captions": ["c"]})

    assert [row.point_id for row in rows] == ["a", "b", "c"]
    assert [row.rank for row in rows] == [1, 2, 3]


def test_ties_break_deterministically_and_reproducibly():
    """§16 — the same query returns the same rows in the same order, across processes.

    `impl` sorted on the total alone and left equal rows in dictionary insertion order.
    """
    branches = {"page": ["b", "a"], "lexical": ["a", "b"]}

    first = [row.point_id for row in rrf(branches)]
    again = [row.point_id for row in rrf(branches)]

    assert first == again == ["a", "b"]


def test_surface_ranks_are_kept_so_a_weight_change_is_explicable():
    rows = rrf({"page": ["a"], "lexical": ["a"]})

    assert rows[0].surface_ranks == {"page": 1, "lexical": 1}
    assert rows[0].surfaces == ("page", "lexical")
    assert rows[0].best_rank == 1


def test_a_surface_weighted_zero_is_switched_off_entirely():
    rows = rrf({"page": ["a"], "lexical": ["b"]}, weights={"page": 1.0, "lexical": 0.0})

    assert [row.point_id for row in rows] == ["a"]
    assert rows[0].surfaces == ("page",)


def test_a_point_found_by_more_surfaces_outranks_one_found_by_fewer():
    rows = rrf({"page": ["solo", "both"], "lexical": ["both"]})

    assert rows[0].point_id == "both"


def test_no_similarity_value_can_enter_the_arithmetic():
    """§7.6 — the inputs are ordered lists; there is nowhere to pass a distance."""
    parameters = inspect.signature(rrf).parameters

    assert list(parameters) == ["branches", "weights", "k"]
    assert not any(name in parameters for name in ("scores", "distances", "similarities"))


def test_no_fused_total_is_ever_returned():
    """`impl` carried it out to the API as `Hit.fused`. A fused float is a score by another name."""
    row = rrf({"page": ["a"]})[0]

    assert not hasattr(row, "score")
    assert not hasattr(row, "fused")
    assert set(FusedRow.__dataclass_fields__) == {"point_id", "surfaces", "surface_ranks", "rank"}


def test_an_object_with_an_id_attribute_is_keyed_by_that_id():
    class Point:
        def __init__(self, id_):
            self.id = id_

    rows = rrf({"page": [Point("p1"), Point("p2")]})

    assert [row.point_id for row in rows] == ["p1", "p2"]


def test_empty_branches_fuse_to_nothing():
    assert rrf({}) == []
    assert rrf({"page": [], "lexical": []}) == []


def test_ranks_are_a_dense_1_based_sequence():
    rows = rrf({"page": ["a", "b", "c", "d"]})

    assert [row.rank for row in rows] == [1, 2, 3, 4]
