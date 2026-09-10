"""L1 — I2's structural half: `ingest/probe.py` is the only writer of `text` (Spec §12.5, §1.2).

§12.5 says this in as many words, and says why it cannot be a grep: *"I2 — that `ingest/probe.py`
is the only writer of the `text` payload field — cannot be a string grep, because
`ingest/index.py` legitimately upserts a payload containing that key. The real check is the
`get_text(` rule paired with an L1 assertion that `record.text == probe_text[page_no]` for every
page of the fixture, which U009 owns."*

This is that assertion. Derivation is the step where model output and page text meet, so it is
the step where the two could be blended — a summary appended, a code list joined on, a "helpful"
normalisation. If `text` survives this step byte for byte, the exact surface is exactly what
PyMuPDF read off the sheet, and no code the model invented can ever be found by `lookup` (F14).

The suite also asserts the two mechanical halves of the rule so a future edit trips something:
only `probe.py` calls `get_text(`, and derivation's own module imports nothing that could write
one.

§12.1 requires the same L1 suite to run against the ported `impl` responses (U012) and the real
`TC1E-SF` fixture (U013). Everything here reads the `derived` fixture, so it will.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vsir.ingest import derive as derive_module

PACKAGE = Path(derive_module.__file__).resolve().parents[1]


def test_i2_text_provenance(derived, extracted):
    """AC: for **every** page of the fixture, `record.text == probe_text[page_no]`."""
    _doc, probed, _facts, _plan, _extraction = extracted
    texts = derive_module.probe_texts(probed)

    assert len(derived.pages) == probed.page_count
    for page in derived.pages:
        assert page.record.text == texts[page.page_no], (
            f"page {page.page_no}: derivation changed the text layer")


def test_the_scanned_pages_text_is_empty_and_stays_empty(derived, expected):
    """A page with no text layer must not acquire one from the model's reading of the raster."""
    for page_no in expected["pages_without_text"]:
        record = derived.page(page_no).record

        assert record.text == ""
        assert record.has_text is False
        # …even though the model returned a summary, a page kind and topics for it.
        assert record.content.summaries and record.content.topics


def test_no_model_prose_appears_in_the_text_of_any_page(derived):
    """The join is one-way: a summary goes to `content`, never appended to the page's text.

    Only the summaries are checked, and deliberately so. A topic is a *label for* the page, so
    `machine layout and access points` is both a topic the model emitted and a heading the sheet
    genuinely prints — asserting its absence would test the corpus, not the provenance.
    """
    for page in derived.pages:
        for summary in page.record.content.summaries:
            assert summary.text
            assert summary.text not in page.record.text


def test_a_code_the_model_invented_is_in_vlm_codes_and_never_in_text(derived, expected):
    """D3's separation, on the corpus's own hallucination: `vlm_codes` yes, `text` no."""
    loose = expected["extraction"]["ungrounded"]
    record = derived.page(loose["page"]).record

    assert loose["code"] in record.vlm_codes
    assert not any(loose["code"] in page.record.text for page in derived.pages)


def test_stitching_does_not_touch_the_text_either(stitched, derived):
    """Step 08 is the other place the record is rewritten, and it rewrites only the section ids."""
    before = {page.page_no: page.record.text for page in derived.pages}

    for record in stitched.pages:
        assert record.text == before[record.page_no]


# ── the mechanical halves of the same rule ──────────────────────────────────────────────────────

def test_only_the_probe_derives_text_from_the_pdf():
    """The `get_text(` rule of §12.5, asserted here beside the behaviour it protects.

    `test_conformance.py` owns the grep; this restates it at the one call site that matters, so
    a reader of *this* file can see both halves of I2 in one place.
    """
    callers = sorted(
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*.py")
        if "get_text(" in path.read_text(encoding="utf-8")
    )

    assert callers == ["ingest/probe.py"]


def test_derivation_assigns_text_from_the_probe_and_from_nothing_else():
    """An AST walk over `derive.py`: every value assigned to a `text=` keyword is a probe read.

    A string literal, an f-string or a concatenation there would be model output reaching the
    exact surface, and it would not fail any other test in this repository until a hallucinated
    code became findable.
    """
    tree = ast.parse(Path(derive_module.__file__).read_text(encoding="utf-8"))
    assigned = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "text"
    ]

    assert assigned, "no `text=` assignment found in derive.py — has the record shape moved?"
    for value in assigned:
        assert isinstance(value, ast.Attribute), ast.dump(value)
        # `page.text`, where `page` is the working page built from `probed.page(page_no)`.
        assert value.attr == "text"


@pytest.mark.parametrize("banned", ["classify(", "entity_keys", "class_totality",
                                    "identifiers_from_text", "withheld", "allowlist"])
def test_the_deleted_gate_did_not_come_back_with_the_derivation(banned):
    """§2.4, §2.5 B — the AST-scan acceptance criterion, as a source check over `derive.py`.

    Guide `06-derivation-and-gate.md` documents the gate in detail, so a builder reading it for
    the offset and the join is one paste away from re-implementing what I2 replaced.
    """
    source = Path(derive_module.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith(("#", "*")))
    body = code.split('"""', 2)[-1]        # skip the module docstring, which names what it deleted

    assert banned not in body


def test_derivation_holds_no_keyword_list_and_no_regex():
    """The other half of the same criterion: no per-corpus grammar of any kind (§5.2).

    A tuple of corpus words or an `re` import in this module would be unversioned corpus
    knowledge sitting between the model and the index.
    """
    source = Path(derive_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names} | {
        node.module.split(".")[0] for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module}

    assert "re" not in imported
    # Every module-level string constant is a field name, a flag or a trigger — never corpus
    # vocabulary. The list is short enough to enumerate, which is the point.
    assert set(derive_module.DERIVE_FLAGS) == {
        "no_text", "ungrounded_codes", "codes_reattributed", "ambiguous_reattribution",
        "label_ambiguous", "label_interpolated"}
