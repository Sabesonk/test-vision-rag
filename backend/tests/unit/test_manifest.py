"""L0/L1 — step 01, identity (Spec §6.1).

The load-bearing assertion in this file is a **negative** one: `ingest/manifest.py` contains no
grammar. A regex taxonomy or a keyword list at the door would be corpus knowledge sitting in front
of every later step, unversioned and invisible, which is precisely what §5.2 bans everywhere else
in the pipeline. So the test reads the module's AST and refuses one.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vsir.ingest import manifest
from vsir.ingest.window import DocumentFacts

MODULE = Path(manifest.__file__)


def test_the_facets_come_from_the_filename_the_metadata_and_the_uploader(synthetic_pdf):
    built = manifest.build(synthetic_pdf)

    assert built.doc_id == "synthetic-3window"          # the filename's slug
    assert built.subjects == ("C24",)                   # the file's own /Subject
    assert set(built.tags) >= {"synthetic", "3window"}  # the filename, cut into parts
    assert set(built.tags) >= {"m2a", "fixture"}        # the file's own /Keywords
    assert built.size_bytes == synthetic_pdf.stat().st_size
    assert built.source == synthetic_pdf


def test_the_document_id_is_revision_stable(synthetic_pdf):
    """A key that changes on every revision orphans every relationship pointing at the old one."""
    built = manifest.build(synthetic_pdf, revision="1.3")

    assert built.revision == "1.3"
    assert "1.3" not in built.doc_id
    assert manifest.build(synthetic_pdf, revision="2.0").doc_id == built.doc_id


def test_what_the_uploader_declares_wins_over_the_file(synthetic_pdf):
    built = manifest.build(synthetic_pdf, doc_id="TC1E-SF", revision="1.3",
                           doc_type="safety_function_list", subjects=["C24", "C24-M2"],
                           tags=["pilot"], uploader="ops@example")

    assert (built.doc_id, built.revision, built.doc_type) == (
        "TC1E-SF", "1.3", "safety_function_list")
    assert built.subjects == ("C24", "C24-M2")
    assert built.tags[0] == "pilot"
    assert built.uploader == "ops@example"


def test_an_undeclared_facet_is_recorded_as_undeclared(synthetic_pdf):
    """Register A4: `doc_type or facts.doc_type` threw S1's answer away, because the form's
    default was the truthy literal "unknown". A default and a declaration must be tellable apart.
    """
    silent = manifest.build(synthetic_pdf)
    assert (silent.doc_type, silent.doc_type_declared) == (manifest.DEFAULT_DOC_TYPE, False)
    assert (silent.revision, silent.revision_declared) == (manifest.DEFAULT_REVISION, False)

    declared = manifest.build(synthetic_pdf, doc_type=manifest.DEFAULT_DOC_TYPE,
                              revision=manifest.DEFAULT_REVISION)
    assert declared.doc_type_declared and declared.revision_declared


def test_a_disagreement_is_only_reported_against_a_declared_facet(synthetic_pdf):
    """`impl` reported `s1_said: "1.0"` when S1 had returned nothing at all — the fallback
    constant. An unread field and a field genuinely read as 1.0 were indistinguishable in the one
    report whose disagreement mints a duplicate document.
    """
    facts = DocumentFacts(revision="1.0", doc_type="wiring_diagram")

    assert manifest.build(synthetic_pdf).disagreement(facts) == {}
    assert manifest.build(synthetic_pdf, revision="1.3").disagreement(facts) == {"revision": "1.0"}
    assert manifest.build(synthetic_pdf, doc_type="safety_function_list").disagreement(facts) == {
        "doc_type": "wiring_diagram"}


def test_a_model_that_read_nothing_is_not_a_disagreement(synthetic_pdf):
    assert manifest.build(synthetic_pdf, revision="1.3").disagreement(DocumentFacts()) == {}


def test_a_missing_document_is_a_named_refusal(tmp_path):
    with pytest.raises(FileNotFoundError):
        manifest.build(tmp_path / "nope.pdf")


def test_metadata_can_be_supplied_without_opening_the_file(synthetic_pdf):
    """The uploader's door and the file's door reach the same builder (§6.1 step 01)."""
    built = manifest.build(synthetic_pdf, metadata={"subject": "C24, C25", "keywords": "a,b"})

    assert built.subjects == ("C24", "C25")
    assert set(built.tags) >= {"a", "b"}


# ── the negative assertion: no grammar in this module ───────────────────────────────────────────

def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def test_the_manifest_imports_no_regex_engine():
    """A regex here is a taxonomy in disguise: `if the title matches …` is content sniffing."""
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(_tree())
        for alias in (node.names if isinstance(node, (ast.Import, ast.ImportFrom)) else [])
    } | {
        node.module.split(".")[0]
        for node in ast.walk(_tree())
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "re" not in imported, "step 01 takes facets from metadata, never from a pattern"
    assert "regex" not in imported


def test_the_manifest_holds_no_keyword_list():
    """A collection of two or more string constants is a taxonomy, wherever it is written."""
    offenders = [
        ast.unparse(node)
        for node in ast.walk(_tree())
        if isinstance(node, (ast.List, ast.Tuple, ast.Set))
        and sum(1 for item in node.elts if isinstance(item, ast.Constant)
                and isinstance(item.value, str)) >= 2
    ]
    offenders += [
        ast.unparse(node)
        for node in ast.walk(_tree())
        if isinstance(node, ast.Dict)
        and sum(1 for key in node.keys if isinstance(key, ast.Constant)
                and isinstance(key.value, str)) >= 2
        and not any(isinstance(value, ast.Attribute) for value in node.values)
    ]

    assert not offenders, f"a keyword list in {MODULE.name}: {offenders}"


def test_the_ast_scan_would_catch_a_taxonomy(tmp_path):
    """The gate is real: the same scan over a module that does classify fails."""
    planted = tmp_path / "planted.py"
    planted.write_text('SAFETY_WORDS = ("safety", "sicurezza", "notaus")\n')
    tree = ast.parse(planted.read_text())

    assert [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Tuple)
        and sum(1 for item in node.elts if isinstance(item, ast.Constant)) >= 2
    ]
