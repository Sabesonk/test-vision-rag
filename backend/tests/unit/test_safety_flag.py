"""L0 — `safety_flag`, and the keyword list that must not come back (Spec §6.8).

`impl` computed it in ``_is_safety()`` from two things this CR deletes: the unit grammar's
``kind == "safety_function"`` and a hardcoded keyword list — ``"pl="``, ``"performance level"``,
``"safety"``, ``"sicurezza"``, ``"emergency"``, ``"category 3"``, ``"category 2"``. Both are
struck (C1, §2.5 B), and dropping them without a replacement would have silently deleted a
**contract** item: the POC document requires safety flagging to be exported to Part A.

So §6.8 replaces it with two sources that already exist and add no grammar — the manifest's
`doc_type`, declared by the uploader, and the model's own lowercase `topics[]`. Both are
configuration, because the vocabulary is the corpus's: a list compiled into the image is one no
deployment could correct, and it is exactly the thing this suite exists to keep out.

The flag is **advisory metadata**. It is never a gate, never a filter default and never a reason
to hide a page, so the cost of a miss is one missing hint in Part A's answer policy rather than a
wrong answer here. That is what lets the sources be this simple.

Run this unit's slice:
    bash scripts/test-unit.sh -k "gates or export_shape or safety_flag"
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vsir.config import load_config
from vsir.ingest import export
from vsir.ingest.export import safety_flag
from conftest import SYNTHETIC_ENV

MODULE = Path(export.__file__)

#: The list `impl` shipped. Named here, in a test, so it is documented and testable — and asserted
#: **absent** from the module below. It is the shape of the mistake, not a set anything uses.
IMPL_KEYWORDS = ("pl=", "performance level", "safety", "sicurezza", "emergency", "category 3",
                 "category 2")

DOC_TYPES = ("safety_function_list", "risk_assessment")
TOPICS = ("safety", "emergency stop")


# ── the two sources of §6.8 ──────────────────────────────────────────────────────────────────────

def test_a_declared_safety_doc_type_flags_every_page_of_the_document():
    """The document-level source: what the uploader declared in the manifest, never inferred."""
    assert safety_flag("safety_function_list", ["hydraulics"], safety_doc_types=DOC_TYPES,
                       safety_topics=TOPICS)


def test_a_model_emitted_safety_topic_flags_the_page_that_carries_it():
    """The page-level source: the model's own `topics[]`, which is a retrieval label set — so a
    miss costs a flag rather than a wrong answer."""
    assert safety_flag("manual", ["wiring", "emergency stop"], safety_doc_types=DOC_TYPES,
                       safety_topics=TOPICS)
    assert not safety_flag("manual", ["wiring", "lubrication"], safety_doc_types=DOC_TYPES,
                           safety_topics=TOPICS)


def test_neither_source_matching_is_simply_false():
    assert not safety_flag("manual", ["hydraulics"], safety_doc_types=DOC_TYPES,
                           safety_topics=TOPICS)


def test_the_comparison_is_case_insensitive_on_both_sides():
    """The model emits lowercase topics; an operator setting an environment variable should not
    have to know that, and a flag lost to a capital letter is a contract item lost silently."""
    assert safety_flag("Safety_Function_List", [], safety_doc_types=DOC_TYPES,
                       safety_topics=TOPICS)
    assert safety_flag("manual", ["EMERGENCY STOP"], safety_doc_types=DOC_TYPES,
                       safety_topics=TOPICS)


def test_with_nothing_configured_nothing_is_ever_flagged():
    """The honest default. A compiled-in fallback list would be the `impl` keyword list under
    another name — and it would flag differently in every corpus with nothing saying so."""
    for doc_type in ("safety_function_list", "manual", *IMPL_KEYWORDS):
        assert not safety_flag(doc_type, list(IMPL_KEYWORDS))


def test_a_topic_that_merely_contains_a_watched_word_is_not_a_match():
    """Membership, not substring. `"safety valve maintenance"` is not the topic `"safety"`, and a
    substring rule is how a keyword list grows back one `in` at a time."""
    assert not safety_flag("manual", ["safety valve maintenance"], safety_topics=("safety",))
    assert safety_flag("manual", ["safety"], safety_topics=("safety",))


# ── no keyword list in the module (AC: an AST scan finds none) ───────────────────────────────────

def test_no_safety_keyword_appears_as_a_string_literal_in_the_module():
    """AC: an AST scan finds no hardcoded safety keyword list.

    Over string **literals** in the AST rather than over the file's text, so the module can — and
    does — explain in prose which list was deleted and why, while being unable to contain one.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    literals = {node.value.lower() for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and len(node.value) < 200 and "\n" not in node.value}

    assert not literals & set(IMPL_KEYWORDS), f"a keyword list is back: {literals & set(IMPL_KEYWORDS)}"


def test_the_module_has_no_module_level_collection_of_words_at_all():
    """The stronger form: no module-level list/tuple/set of strings other than the field sets the
    §6.8 contract names. A taxonomy cannot hide as a constant nobody looked at."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    declared: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                name = getattr(targets[0], "id", "?")
                declared[name] = len(value.elts)

    assert set(declared) == {"EXPORTS", "LABEL_FIELDS", "SECTION_FIELDS", "OBSERVED_TOKEN_FIELDS",
                             "__all__"}


# ── the sets are configuration (§15 Factor III) ──────────────────────────────────────────────────

def test_both_sets_come_from_the_environment_and_default_to_empty():
    """A deployment-varying value is an env var in `.env.example`, never a literal in code."""
    plain = load_config(SYNTHETIC_ENV)
    configured = load_config({**SYNTHETIC_ENV,
                              "VSIR_SAFETY_DOC_TYPES": "safety_function_list, risk_assessment",
                              "VSIR_SAFETY_TOPICS": "safety,emergency stop"})

    assert plain.safety_doc_types == () and plain.safety_topics == ()
    assert configured.safety_doc_types == DOC_TYPES
    assert configured.safety_topics == TOPICS


def test_both_variables_are_documented_in_the_env_example():
    """§15 Factor III: a value a deployment sets is one an operator can find."""
    example = (Path(__file__).resolve().parents[3] / ".env.example").read_text()

    assert "VSIR_SAFETY_DOC_TYPES=" in example
    assert "VSIR_SAFETY_TOPICS=" in example


def test_neither_set_is_ever_a_reason_to_hide_a_page():
    """§6.8, verbatim: advisory metadata. It is not in `INDEXED`, so it cannot be a scope filter,
    and it is computed at export time rather than stored — there is nothing to filter on."""
    from vsir.core.indexed import INDEXED

    assert "safety_flag" not in INDEXED
    assert "safety_flag" not in export.SECTION_FIELDS
    assert "safety_flag" in export.LABEL_FIELDS


@pytest.mark.parametrize("value", ["", "   ", ",,"])
def test_an_empty_or_blank_configuration_value_flags_nothing(value):
    assert load_config({**SYNTHETIC_ENV, "VSIR_SAFETY_TOPICS": value}).safety_topics == ()
