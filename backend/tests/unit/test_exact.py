"""L0 — `exact_filter()` (Spec §5.6, I3, F1, F10).

The filter is the system's single exact-match code path. These tests assert its *shape*, because
the shape is the guarantee: a phrase per variant, each ANDed with the scope, ORed together. A
`MatchText` anywhere in that structure would turn `"SF 1.1A"` into "any page mentioning safety
functions", which is not a slow path but a wrong answer.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from qdrant_client.http import models as qm

from vsir.core.exact import UnknownScopeKey, exact_filter, phrases_of, scope_conditions
from vsir.core.indexed import TEXT_FIELDS
from vsir.core.variants import variants

PACKAGE = Path(__file__).resolve().parents[2] / "vsir"


def test_the_filter_is_a_phrase_per_variant():
    query = exact_filter("SF 1.1A")

    assert len(query.should) == len(variants("SF 1.1A")) == 3
    assert phrases_of(query) == ["SF 1.1A", "SF1.1A", "SF 1.1 A"]
    for branch in query.should:
        condition = branch.must[0]
        assert isinstance(condition.match, qm.MatchPhrase)
        assert condition.key == "text"


def test_the_scope_is_anded_into_every_branch():
    """A scope that applied to only one branch would silently widen the other two."""
    query = exact_filter("K158", {"doc_id": "TC1E-SF", "is_current": True})

    for branch in query.should:
        assert len(branch.must) == 3
        keys = {condition.key for condition in branch.must}
        assert keys == {"text", "doc_id", "is_current"}


def test_a_list_scope_value_matches_any_element():
    """F8 — a page straddling two sections is in scope for either."""
    conditions = scope_conditions({"section_id": ["D@1#s001", "D@1#s002"]})

    assert len(conditions) == 1
    assert isinstance(conditions[0].match, qm.MatchAny)
    assert conditions[0].match.any == ["D@1#s001", "D@1#s002"]


def test_an_empty_scope_produces_a_bare_phrase_filter():
    query = exact_filter("K158")

    assert all(len(branch.must) == 1 for branch in query.should)


@pytest.mark.parametrize("field", TEXT_FIELDS)
def test_either_text_surface_can_be_asked_the_same_question(field):
    """Same code path, same phrase semantics, different trust — a parameter, not a second function."""
    query = exact_filter("K158", field=field)

    assert {branch.must[0].key for branch in query.should} == {field}


@pytest.mark.parametrize("field", ["content.text", "summary", "vlm_codes ", "TEXT"])
def test_no_other_field_can_be_phrase_matched(field):
    with pytest.raises(ValueError, match="not a text surface"):
        exact_filter("K158", field=field)


def test_an_unknown_scope_key_is_refused_by_name():
    """I6, F10 — never absorbed, never degraded to an unindexed scan."""
    with pytest.raises(UnknownScopeKey) as raised:
        exact_filter("K158", {"bogus": 1, "doc_id": "D"})

    assert raised.value.keys == ["bogus"]


@pytest.mark.parametrize("key", ["text", "vlm_codes"])
def test_a_text_surface_is_not_a_caller_supplied_filter(key):
    """§5.4 — those two are reachable only through `lookup` and `verify`."""
    with pytest.raises(UnknownScopeKey):
        exact_filter("K158", {key: "anything"})


def test_a_none_scope_value_is_dropped_rather_than_matched_against_null():
    conditions = scope_conditions({"doc_id": "D", "revision": None})

    assert [condition.key for condition in conditions] == ["doc_id"]


def test_an_empty_label_is_refused():
    with pytest.raises(ValueError, match="empty"):
        exact_filter("   ")


def test_exact_filter_is_the_only_call_site_of_match_phrase():
    """I3 — asserted by an AST scan over the package, not by a grep over strings.

    A second `MatchPhrase` call site is a second exact-match path, and two paths mean the tool that
    found a page and the check that confirms it can disagree.
    """
    call_sites: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (function.attr if isinstance(function, ast.Attribute)
                    else getattr(function, "id", None))
            if name == "MatchPhrase":
                call_sites.append(f"{path.relative_to(PACKAGE.parent)}:{node.lineno}")

    assert len(call_sites) == 1, f"MatchPhrase must have exactly one call site, found {call_sites}"
    assert call_sites[0].startswith("vsir/core/exact.py")


def test_no_fuzzy_matching_primitive_is_imported_anywhere_in_core():
    """§7.6 — no edit distance, no similarity library, not even from the standard library."""
    banned = {"difflib", "Levenshtein", "rapidfuzz", "fuzzywuzzy", "jellyfish"}
    for path in (PACKAGE / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & banned
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned
