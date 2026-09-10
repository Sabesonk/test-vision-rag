"""L2 — the same query returns the same rows in the same order (Spec §16, §7.2.1, U017).

This is a **non-functional requirement asserted as a functional one**, because everything above it
rests on it: the L2 acceptance table, the E2E assertions, and an agent that excludes a page it
rejected and expects the rest of the list to stay where it was. A ranking that reshuffles between
two identical calls is not a worse ranking, it is a different answer to the same question, and the
caller has no way to tell which one it got.

Three levels of the same claim:

* **within one process** — two calls, one client, identical bodies;
* **across two processes** — the `vsir skim pages --json` one-shot, run twice as a real
  subprocess, against the same collection. A fresh process has a fresh embedder, a fresh Qdrant
  connection and no memory of the first call, which is the only way to show the order is a
  property of the data rather than of a warm process (§15 Factor VI);
* **in the arithmetic itself** — `Σ w/(k + rank)` at `k=60` with weights `1.0 / 1.0 / 0.4`,
  computed by hand for a fixed set of branch rankings and compared with what :func:`rrf` returns.
  Ranks only: there is no similarity value anywhere in the input, so there is none in the output.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from vsir.config import RRF_K, SURFACE_WEIGHTS
from vsir.serve.tools.skim import rrf

from conftest import QDRANT_URL, SKIM_COLLECTION, SKIM_RUNS, serve_env

SKIM = "/tools/skim_pages"
QUERY = "emergency stop reset"
BODY = {"query": QUERY, "scope": {"doc_id": "SYN-M1"}, "limit": 5}


def page_ids(body: dict) -> list[str]:
    return [hit["page_id"] for hit in body["hits"]]


# ── the arithmetic (§7.2.1 rule 2) ──────────────────────────────────────────────────────────────

def test_the_weights_and_k_are_the_pins_the_spec_names():
    """D2: `page 1.0 · lexical 1.0 · captions 0.4`, `rrf_k = 60`. Pins, not defaults."""
    assert RRF_K == 60
    assert dict(SURFACE_WEIGHTS) == {"page": 1.0, "lexical": 1.0, "captions": 0.4}


def test_the_fused_order_matches_the_hand_computed_sum():
    """`Σ w/(k + rank)` — computed here in full, so the ordering rule is checkable by eye.

    Four points, three branches, every interesting case in one table: a point two branches found
    (``b``), a point only the 0.4-weighted branch found (``d``), and two points at different depths
    of the same branch.
    """
    branches = {"page": ["a", "b", "c"], "lexical": ["b", "a"], "captions": ["d", "b"]}

    by_hand = {
        "a": 1.0 / (60 + 1) + 1.0 / (60 + 2),                 # dense 1st, lexical 2nd
        "b": 1.0 / (60 + 2) + 1.0 / (60 + 1) + 0.4 / (60 + 2),  # all three
        "c": 1.0 / (60 + 3),                                   # dense only
        "d": 0.4 / (60 + 1),                                   # captions only
    }
    expected = sorted(by_hand, key=lambda point: -by_hand[point])
    fused = rrf(branches)

    assert [row.point_id for row in fused] == expected == ["b", "a", "c", "d"]
    assert [row.rank for row in fused] == [1, 2, 3, 4]
    assert fused[0].why == ["dense", "lexical", "captions"]
    assert fused[2].why == ["dense"]
    assert fused[3].why == ["captions"]
    assert fused[0].surface_ranks == {"page": 2, "lexical": 1, "captions": 2}


def test_a_tie_breaks_the_same_way_every_time():
    """`impl` left equal rows in dictionary insertion order; §16 needs a rule, so there is one.

    Two points each found at rank 1 by one branch of equal weight have identical sums. The tiebreak
    is the best per-surface rank, then the point id — so the order is a property of the values and
    not of which branch happened to be iterated first.
    """
    one = rrf({"page": ["z", "a"], "lexical": ["a", "z"]})
    other = rrf({"lexical": ["a", "z"], "page": ["z", "a"]})

    assert [row.point_id for row in one] == [row.point_id for row in other] == ["a", "z"]


def test_a_surface_weighted_zero_contributes_nothing_at_all():
    """Not even its presence in `why`: a switched-off branch must not explain a row."""
    fused = rrf({"page": ["a"], "captions": ["b"]}, weights={"page": 1.0, "captions": 0.0})

    assert [row.point_id for row in fused] == ["a"]
    assert fused[0].why == ["dense"]


# ── the same query, twice, in one process ───────────────────────────────────────────────────────

def test_two_identical_calls_return_the_identical_ordered_list(skimming, token_header):
    first = skimming.post(SKIM, json=BODY, headers=token_header)
    second = skimming.post(SKIM, json=BODY, headers=token_header)

    assert first.status_code == second.status_code == 200
    assert page_ids(first.json()) == page_ids(second.json())
    # Byte-identical, not merely equal: `rank`, `why` and the affordances are part of the answer.
    assert first.content == second.content


def test_a_second_app_over_the_same_collection_returns_the_same_order(skimming, token_header,
                                                                      skim_collection):
    """A different instance, a different client, a different embedder object — the same rows.

    The service holds no state, so a second replica behind a load balancer must answer identically
    to the first (C11, §15 Factor VI). This is that property at the smallest scale that can show
    it inside one test process.
    """
    from fastapi.testclient import TestClient

    from vsir.serve.app import create_app

    with TestClient(create_app(serve_env(VSIR_COLLECTION=SKIM_COLLECTION,
                                         VSIR_RUNS_COLLECTION=SKIM_RUNS))) as other:
        theirs = other.post(SKIM, json=BODY, headers=token_header)
    ours = skimming.post(SKIM, json=BODY, headers=token_header)

    assert theirs.status_code == 200
    assert page_ids(theirs.json()) == page_ids(ours.json())


# ── the same query, twice, in two processes ─────────────────────────────────────────────────────

def one_shot(*arguments: str) -> dict:
    """`vsir skim pages … --json` as a **real** subprocess, returning the parsed envelope.

    A subprocess rather than `cli.main` in this process, deliberately and unlike
    `test_one_shot_parity.py`: what is being asserted here is not which callable answered but that
    a cold process — nothing cached, nothing warm, no vector held from a previous call — produces
    the same order. That claim cannot be made from inside a process that has already run the query.
    """
    environment = {**os.environ,
                   **serve_env(VSIR_COLLECTION=SKIM_COLLECTION, VSIR_RUNS_COLLECTION=SKIM_RUNS),
                   "VSIR_QDRANT_URL": QDRANT_URL}
    executable = Path(sys.executable).with_name("vsir")
    finished = subprocess.run([str(executable), *arguments, "--json"], env=environment,
                              capture_output=True, text=True, timeout=120, check=False)
    assert finished.returncode == 0, finished.stderr[-2000:]
    return json.loads(finished.stdout)


def test_two_processes_return_the_identical_ordered_list(skim_collection, skimming, token_header):
    """The acceptance criterion, across process boundaries — and matching the HTTP surface."""
    first = one_shot("skim", "pages", QUERY, "--scope", "doc_id=SYN-M1", "--limit", "5")
    second = one_shot("skim", "pages", QUERY, "--scope", "doc_id=SYN-M1", "--limit", "5")
    over_http = skimming.post(SKIM, json=BODY, headers=token_header).json()

    assert page_ids(first) == page_ids(second) == page_ids(over_http)
    assert [hit["rank"] for hit in first["hits"]] == [1, 2, 3, 4, 5]
    assert [hit["why"] for hit in first["hits"]] == [hit["why"] for hit in over_http["hits"]]


def test_excluding_a_page_leaves_the_rest_of_the_order_alone_across_processes(skim_collection):
    """`exclude` removes a row; it does not re-rank the ones that remain (C11)."""
    before = one_shot("skim", "pages", QUERY, "--scope", "doc_id=SYN-M1", "--limit", "5")
    dropped = page_ids(before)[2]
    after = one_shot("skim", "pages", QUERY, "--scope", "doc_id=SYN-M1", "--limit", "5",
                     "--exclude", dropped)

    assert dropped not in page_ids(after)
    assert page_ids(after)[:2] == page_ids(before)[:2]
