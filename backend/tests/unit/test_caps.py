"""L0 — the caps of Spec §7.3 (F18). Each one a typed 400 naming its bound, never a clamp."""
from __future__ import annotations

import pytest

from vsir.config import MAX_READ_PAGES
from vsir.core.exact import UnknownScopeKey
from vsir.serve.caps import (
    ALLOWED_DPI,
    MAX_FETCH_MEGAPIXELS,
    MAX_FETCH_PAGES,
    REGION_REQUIRED_ABOVE,
    ToolError,
    as_tool_error,
    validate_budget,
    validate_dpi,
    validate_fetch_megapixels,
    validate_fetch_pages,
    validate_read_pages,
    validate_region,
    validate_scope,
)


def test_read_takes_three_pages_and_refuses_four():
    """Tightened from `impl`'s four, deliberately (§2.4, §7.3)."""
    assert MAX_READ_PAGES == 3
    validate_read_pages(["a", "b", "c"])

    with pytest.raises(ToolError) as raised:
        validate_read_pages(["a", "b", "c", "d"])

    assert raised.value.code == "read_page_cap_exceeded"
    assert raised.value.details == {"limit": 3, "requested": 4}
    assert raised.value.http_status == 400


def test_fetch_takes_five_pages_and_refuses_six():
    assert MAX_FETCH_PAGES == 5
    validate_fetch_pages(["a"] * 5)

    with pytest.raises(ToolError) as raised:
        validate_fetch_pages(["a"] * 6)

    assert raised.value.code == "fetch_budget_exceeded"
    assert raised.value.details["limit"] == 5
    assert raised.value.details["requested"] == 6
    assert raised.value.http_status == 400


def test_the_megapixel_budget_is_a_separate_bound_under_the_same_code():
    """"A typed 400 naming its bound": both `fetch` bounds say which one was hit."""
    validate_fetch_megapixels(MAX_FETCH_MEGAPIXELS)

    with pytest.raises(ToolError) as raised:
        validate_fetch_megapixels(12.5)

    assert raised.value.code == "fetch_budget_exceeded"
    assert raised.value.details["bound"] == "megapixels"
    assert raised.value.details["limit"] == 12.0
    assert raised.value.http_status == 400


@pytest.mark.parametrize("dpi", ALLOWED_DPI)
def test_every_allowed_dpi_is_accepted(dpi):
    validate_dpi(dpi, region=[0.0, 0.0, 1.0, 1.0] if dpi > REGION_REQUIRED_ABOVE else None)


@pytest.mark.parametrize("dpi", [0, 1, 100, 219, 221, 401, 4000, -150])
def test_a_dpi_off_the_list_is_refused_rather_than_rounded(dpi):
    with pytest.raises(ToolError) as raised:
        validate_dpi(dpi)

    assert raised.value.code == "dpi_not_allowed"
    assert raised.value.details["allowed"] == list(ALLOWED_DPI)
    assert raised.value.http_status == 400


def test_the_allowed_dpi_tiers_are_the_documented_six():
    """36/72 are the triage thumbnails, 150 is `fetch`'s default, 220 is what `read` sees."""
    assert ALLOWED_DPI == (36, 72, 150, 220, 300, 400)
    assert REGION_REQUIRED_ABOVE == 220


@pytest.mark.parametrize("dpi", [300, 400])
def test_above_the_answer_dpi_a_region_is_required(dpi):
    """Detail that fine is about part of a page — and a full page at 400 dpi is money."""
    with pytest.raises(ToolError) as raised:
        validate_dpi(dpi, region=None)

    assert raised.value.code == "dpi_requires_region"
    assert raised.value.http_status == 400

    validate_dpi(dpi, region=[0.1, 0.1, 0.5, 0.5])


@pytest.mark.parametrize("dpi", [36, 72, 150, 220])
def test_at_or_below_the_answer_dpi_a_region_is_optional(dpi):
    validate_dpi(dpi, region=None)


@pytest.mark.parametrize(
    "region",
    [[0.0, 0.0, 1.0, 1.0], [0.1, 0.2, 0.3, 0.4], None],
)
def test_a_valid_region_passes(region):
    validate_region(region)


@pytest.mark.parametrize(
    "region",
    [[0, 0, 2, 2], [0.5, 0.5, 0.1, 0.9], [0.5, 0.5, 0.9, 0.1], [0, 0, 0, 1], [0, 0, 1], [-0.1, 0, 1, 1],
     [0, 0, 1, 1, 1]],
)
def test_a_malformed_region_is_refused_not_clamped(region):
    """Clamping `[0,0,2,2]` to the page returns a different crop and calls it success."""
    with pytest.raises(ToolError) as raised:
        validate_region(region)

    assert raised.value.code == "region_invalid"
    assert raised.value.http_status == 400


def test_unknown_scope_key_returns_typed_400():
    """F10 — the one failure that has no symptom until somebody trusts the smaller answer.

    Named as the plan's Test Plan names it, so §10's F10 row and this assertion are greppable from
    each other. The tool-boundary half is `tests/api/test_acceptance_synthetic.py`'s test of the
    same name, which proves `lookup` raises this and not the core's domain error.
    """
    validate_scope({"doc_id": "D", "page_no": 1})
    validate_scope(None)

    with pytest.raises(ToolError) as raised:
        validate_scope({"bogus": 1, "also_bogus": 2, "doc_id": "D"})

    assert raised.value.code == "filter_unknown_key"
    assert raised.value.details["keys"] == ["also_bogus", "bogus"]
    assert raised.value.http_status == 400


@pytest.mark.parametrize("key", ["text", "vlm_codes", "content.units", "entity_keys",
                                 "machine_models", "score"])
def test_the_scope_gate_rejects_the_keys_that_are_not_scope(key):
    with pytest.raises(ToolError):
        validate_scope({key: "x"})


def test_an_exhausted_read_budget_is_a_429_not_a_truncated_loop():
    validate_budget(1)

    with pytest.raises(ToolError) as raised:
        validate_budget(0)

    assert raised.value.code == "budget_exhausted"
    assert raised.value.http_status == 429


def test_the_core_scope_error_translates_to_the_surface_error_once():
    """`core/` knows nothing about HTTP and `serve/` does not re-implement the INDEXED gate."""
    translated = as_tool_error(UnknownScopeKey(["bogus"]))

    assert translated.code == "filter_unknown_key"
    assert translated.details["keys"] == ["bogus"]


def test_the_error_payload_is_machine_readable():
    """An agent switches on the code, not on prose."""
    payload = ToolError("dpi_not_allowed", "nope", requested=100).to_payload()

    assert payload["error"] == "dpi_not_allowed"
    assert payload["requested"] == 100
    assert "detail" in payload
