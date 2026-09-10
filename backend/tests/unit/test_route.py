"""L0 — §8.1a: `fetch` versus `read`, the deliberate choice, and the four inputs it is made from.

The route is where this system decides whether the *agent* looks at the page or a *sub-model*
does, and it is the last free decision before the only tool that spends. Three properties are
worth a suite of their own:

* **the default is `fetch`** — SA-4 settles the wording clash between §8.2's generic *"`relevant`
  → `read`"* and §8.1a's bolded *"Default: `fetch`"*, and a release that drifted back to
  read-by-default would bill the whole per-question budget for a page the caller could have
  looked at for nothing;
* **`read` is delegation** — chosen for a caller that cannot see or a context that cannot hold
  another raster, and for no other reason;
* **the decision itself costs nothing** — no model call, no raster, no store read.

Nothing here needs a store, a network or a fixture: every test is a value in and a value out.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vsir.config import MAX_READ_PAGES
from vsir.runner import route as route_module
from vsir.runner.route import (
    FETCH,
    READ,
    REASONS,
    ROUTES,
    Caller,
    decide,
    plan,
    routes,
)
from vsir.serve.app import tool_table
from vsir.serve.caps import MAX_FETCH_PAGES

SOURCE = Path(route_module.__file__)
PAGES = ("d@1.0#p001", "d@1.0#p002")


# ── the default (§8.1a) ─────────────────────────────────────────────────────────────────────────

def test_the_default_route_is_fetch():
    """A vision-capable caller with room and budget looks at the page itself, for free."""
    decision = decide(Caller(reads_remaining=3))
    assert (decision.route, decision.reason) == (FETCH, "default_fetch")
    assert not decision.spends


def test_the_default_holds_for_every_relevant_candidate():
    for one in routes(PAGES, Caller(reads_remaining=3)):
        assert (one.route, one.reason) == (FETCH, "default_fetch")


def test_the_default_does_not_depend_on_the_read_budget():
    """A caller that can see does not need the paid route, so an empty budget changes nothing."""
    assert decide(Caller(reads_remaining=0)).route == FETCH


# ── delegation, by both doors (§8.1a) ───────────────────────────────────────────────────────────

def test_a_caller_that_cannot_see_gets_read():
    decision = decide(Caller(reads_remaining=3, vision_capable=False))
    assert (decision.route, decision.reason) == (READ, "caller_not_vision_capable")
    assert decision.spends


def test_a_context_that_cannot_hold_another_raster_gets_read():
    """*"To keep the agent's context small on a long trace"* — the second door to delegation."""
    decision = decide(Caller(reads_remaining=3, image_slots=0))
    assert (decision.route, decision.reason) == (READ, "context_budget")


def test_the_context_budget_is_compared_against_the_pages_actually_being_looked_at():
    caller = Caller(reads_remaining=3, image_slots=2)
    assert decide(caller, pages=2).route == FETCH
    assert decide(caller, pages=3).route == READ


def test_delegation_with_no_read_budget_left_is_no_route_at_all():
    """§8.4 — never a silent extra call, and never a raster a caller cannot read."""
    decision = decide(Caller(reads_remaining=0, vision_capable=False))
    assert decision.route is None and decision.reason == "budget_exhausted"
    assert not decision.spends


# ── the zoom (§8.1a, §7.2.5) ────────────────────────────────────────────────────────────────────

def test_a_zoom_can_only_be_a_fetch():
    """`read` renders one pinned dpi and has no `region`, so a corner crop has one route."""
    assert decide(Caller(reads_remaining=3), zoom=True).route == FETCH
    assert decide(Caller(reads_remaining=0, image_slots=0), zoom=True).route == FETCH


def test_a_caller_that_cannot_see_cannot_zoom_and_is_told_so():
    decision = decide(Caller(reads_remaining=3, vision_capable=False), zoom=True)
    assert decision.route is None and decision.reason == "zoom_requires_vision"


# ── the caps (§7.3) ─────────────────────────────────────────────────────────────────────────────

def test_a_look_is_split_at_the_route_s_own_cap():
    many = tuple(f"d@1.0#p{n:03d}" for n in range(1, 8))
    looked = plan(many, Caller(reads_remaining=3, vision_capable=False))
    assert looked.route == READ
    assert looked.pages == many[:MAX_READ_PAGES]
    assert looked.deferred == many[MAX_READ_PAGES:]

    seen = plan(many, Caller(reads_remaining=3, image_slots=len(many)))
    assert seen.route == FETCH
    assert len(seen.pages) == MAX_FETCH_PAGES and seen.deferred == many[MAX_FETCH_PAGES:]


def test_a_deferred_page_carries_no_route_and_does_not_claim_the_set_s_reason():
    many = tuple(f"d@1.0#p{n:03d}" for n in range(1, 5))
    marks = {one.page_id: one for one in routes(many, Caller(reads_remaining=3,
                                                             vision_capable=False))}
    assert marks[many[MAX_READ_PAGES]].route is None
    assert marks[many[MAX_READ_PAGES]].reason == "deferred_over_cap"


def test_no_route_defers_everything_rather_than_silently_looking():
    looked = plan(PAGES, Caller(reads_remaining=0, vision_capable=False))
    assert looked.route is None and looked.pages == () and looked.deferred == PAGES


def test_one_route_for_the_whole_set_never_a_split_between_the_two():
    """§8.1a — `fetch`'s advantage is that both pages are in one context. Halving it loses that."""
    assert len({one.route for one in routes(PAGES, Caller(reads_remaining=3))}) == 1


def test_duplicate_page_ids_are_looked_at_once():
    looked = plan(("d@1.0#p001", "d@1.0#p001"), Caller(reads_remaining=3))
    assert looked.pages == ("d@1.0#p001",)


# ── the decision costs nothing ──────────────────────────────────────────────────────────────────

def test_the_routing_decision_makes_no_call_of_any_kind():
    """A call spy would need something to spy on. There is nothing: the module imports no client.

    Asserted structurally rather than by mocking, because that is the stronger statement — a
    module that cannot reach a backend cannot bill one under any input.
    """
    tree = ast.parse(SOURCE.read_text())
    imported = {node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    assert not [name for name in imported
                if any(part in name for part in ("vlm", "qdrant", "raster", "tools", "app"))]
    assert not [node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in
                {"dispatch", "query_points", "generate_content", "render"}]


def test_the_routes_are_the_two_tools_and_which_one_spends_is_the_release_s_own_answer():
    """`spends` must agree with the tool table the dispatcher charges the budget from (§7.3)."""
    table = tool_table()
    assert set(ROUTES) == {FETCH, READ} <= set(table)
    assert table[READ].spends and not table[FETCH].spends
    assert decide(Caller(reads_remaining=1, vision_capable=False)).spends is table[READ].spends
    assert decide(Caller(reads_remaining=1)).spends is table[FETCH].spends


@pytest.mark.parametrize("caller, zoom", [
    (Caller(reads_remaining=3), False),
    (Caller(reads_remaining=3, vision_capable=False), False),
    (Caller(reads_remaining=0, image_slots=0), False),
    (Caller(reads_remaining=3, vision_capable=False), True),
])
def test_every_decision_names_a_declared_reason(caller, zoom):
    decision = decide(caller, zoom=zoom)
    assert decision.reason in REASONS
    assert decision.route in (None, *ROUTES)
