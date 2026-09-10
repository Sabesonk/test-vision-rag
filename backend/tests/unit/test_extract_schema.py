"""L0/L1 — step 06's schema and its four bisection triggers (Spec §5.2, §6.1, §6.2, F13).

The S2 schema is the one place the model is allowed to shape the pipeline's data, so what it
*cannot* say matters more than what it can:

* **there is no field for extent.** `sections[]` reports presence on this page and nothing about
  where a section starts or stops, because a window fold can cut through a section and the model on
  one side cannot see the other. Any span it gave would be a confident guess, and F8 is what that
  costs: a search over a subset of a chapter, believing it searched the chapter.
* **there is no page text.** The text came from PyMuPDF at step 02 and `ingest/probe.py` is its one
  writer (I2). That is what makes step 07 able to *check* the model's codes against what is printed
  rather than take them on trust.
* **there is no classification.** No identifier grammar, no kind enum, no regex taxonomy, no
  per-corpus keyword list — §5.2 bans all four, and `impl` had all four (`STRICT_KINDS`,
  `Unit.kind`, `key_for_unit`, `_is_safety()`'s keyword list). Two of the AST scans below exist
  because that is the kind of code that grows back.

And a bad answer is **bisected, never kept**: a 30-page window quietly kept after a truncation
loses 30 pages of a manual and reports success (F13). All four of §6.2's triggers are exercised
here through the real replay backend, so the path under test is the path that ships.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vsir.config import DPI_ANSWER
from vsir.eval import synthetic_pdf as generator
from vsir.ingest import extract as x
from vsir.ingest import probe, render
from vsir.ingest import window as w
from vsir.vlm import (EXTRACT, FixtureMiss, FixtureStore, StubBackend, VlmSchemaInvalid,
                      extract_key, write)

MODEL = "gemini-3.8-flash-001"
PROMPT = "s2-v1"
PACKAGE = Path(x.__file__).resolve().parent.parent

#: §5.2's eight, verbatim. Written out rather than imported so the test fails when the constant
#: changes: this list is the schema's own value set, and a ninth kind is a spec change.
SPEC_PAGE_KINDS = ("prose", "table", "schematic", "exploded", "cover", "toc", "index", "blank")


def _form(**overrides) -> dict:
    """A minimal valid `PageOut` body, for the fields one test is about to change."""
    return {"page_index": 1, "summaries": [{"lang": "en", "text": "Specific to this page."}],
            **overrides}


def _probed(pdf):
    return probe.run(pdf)


def _key(pdf, window, probed) -> str:
    return extract_key(
        render.page_hashes(pdf, window.page_numbers, dpi=DPI_ANSWER,
                           content_hash=probed.content_hash),
        vlm_model=MODEL, prompt_version=PROMPT, dpi=DPI_ANSWER, schema_hash=x.S2_SCHEMA_HASH)


def _replay(tmp_path, entries: dict[str, tuple[str, dict | None]]) -> StubBackend:
    """A fixture directory holding exactly the frozen responses a test wants, and no others.

    Built per test rather than shared: replay's whole contract is that a key it does not hold is a
    typed miss, so a test about a bisection has to be able to say precisely which keys exist.
    """
    for key, (body, meta) in entries.items():
        write(tmp_path, EXTRACT, key, body, meta=meta)
    return StubBackend(FixtureStore(tmp_path))


def _extract_one(backend, window, pdf, probed):
    return x.extract_window(backend, window, source=pdf, content_hash=probed.content_hash,
                            page_count=probed.page_count, vlm_model=MODEL, prompt_version=PROMPT,
                            dpi=DPI_ANSWER)


# ── the schema is §5.2's, exactly ───────────────────────────────────────────────────────────────

def test_the_models_carry_exactly_the_fields_the_spec_lists():
    """AC — `WindowOut` validates against §5.2 exactly. Field-for-field, both ways: a missing
    field breaks a downstream step, and an extra one is a feature the spec did not authorise."""
    assert set(x.WindowOut.model_fields) == {"pages"}
    assert set(x.PageOut.model_fields) == {"page_index", "printed_page_no", "page_kind", "lang",
                                           "sections", "summaries", "codes", "topics"}
    assert set(x.SectionRef.model_fields) == {"title", "is_start"}
    assert set(x.Summary.model_fields) == {"lang", "text"}


def test_there_is_no_field_in_which_extent_could_be_claimed():
    """§5.2 — presence per page, never extent. This is the structural half of F8: stitching can
    survive a window fold only because the model was never able to say where a section ended."""
    for model in (x.SectionRef, x.PageOut, x.WindowOut):
        assert not set(model.model_fields) & {"span", "extent", "pages_covered", "page_range",
                                              "start_page", "end_page", "last_page", "page_count",
                                              "continues", "is_end"}


def test_the_model_is_never_asked_for_page_text(synthetic_fixture):
    """I2 — `text` has exactly one writer, `ingest/probe.py`. The schema cannot even carry it, so
    step 07 has something independent to check the model's codes against."""
    assert "text" not in x.PageOut.model_fields
    schema = json.dumps(x.WindowOut.model_json_schema())

    # The one `text` in the schema is a Summary's own prose, which is generated, goes to the
    # captions surface, and is never a lexical index of the page (D2, D3).
    assert "text" in x.Summary.model_fields
    assert schema.count('"text"') == 1


def test_every_response_field_is_closed_to_extra_keys():
    """A response with a field the schema does not name answered a different question than the one
    the schema hash in `extract_key` describes — and `impl`'s old shape is exactly such a
    response, so accepting extras would let a stale fixture validate (§2.4, C1)."""
    for model in (x.WindowOut, x.PageOut, x.SectionRef, x.Summary):
        assert model.model_config["extra"] == "forbid"

    with pytest.raises(ValidationError):
        x.PageOut.model_validate(_form(units=[{"kind": "safety_function"}]))
    with pytest.raises(ValidationError):
        x.PageOut.model_validate(_form(identifiers=["K122"]))


def test_page_index_is_required_and_window_local():
    """§6.4 — `abs = window.start + page_index - 1`. A defaulted 0 would map to the page *before*
    the window and shift a citation silently, which is the injury I4 is asserted against."""
    assert x.PageOut.model_fields["page_index"].is_required()

    with pytest.raises(ValidationError):
        x.PageOut.model_validate({"summaries": []})

    window = w.Window(15, 28, 1)
    assert window.absolute(x.PageOut.model_validate(_form()).page_index) == 15


def test_summaries_are_required_even_when_empty():
    """A response that omits the field entirely answered a different question; an empty list is a
    (poor) answer to this one. The distinction is what makes D5's per-language check meaningful."""
    assert x.PageOut.model_fields["summaries"].is_required()
    assert x.PageOut.model_validate(_form(summaries=[])).summaries == []


def test_codes_and_topics_are_lists_of_strings():
    """AC — and they arrive as the model printed them: not sorted, not deduplicated, not
    classified. `codes` is where a one-character normalisation would rename a component (§5.2)."""
    page = x.PageOut.model_validate(_form(codes=["K122", "SI2", "K122"], topics=["wiring"]))

    assert page.codes == ["K122", "SI2", "K122"]
    assert page.topics == ["wiring"]
    with pytest.raises(ValidationError):
        x.PageOut.model_validate(_form(codes=[{"code": "K122", "kind": "relay"}]))


@pytest.mark.parametrize("kind", SPEC_PAGE_KINDS)
def test_every_page_kind_the_spec_lists_is_accepted(kind):
    assert x.PageOut.model_validate(_form(page_kind=kind)).kind == kind


def test_the_page_kinds_are_the_eight_of_the_spec_and_a_stray_one_normalises():
    """The eight describe a *sheet of paper* and would read the same for a cookbook. A value
    outside them is normalised to the default rather than re-billing thirty pages over a label —
    and normalising is safe precisely because nothing downstream branches on the kind."""
    assert x.PAGE_KINDS == SPEC_PAGE_KINDS
    assert x.DEFAULT_PAGE_KIND in x.PAGE_KINDS
    assert x.PageOut.model_validate(_form(page_kind="safety_function")).kind == "prose"
    assert x.page_kind("schematic") == "schematic"
    assert x.page_kind("wiring_diagram") == x.DEFAULT_PAGE_KIND


def test_a_bilingual_page_gets_one_summary_per_language(synthetic_fixture):
    """D5 — never a blended one. One IT/EN summary poisons the embedding for both languages, and
    these documents are routinely bilingual with both languages on one sheet."""
    page = x.PageOut.model_validate(_form(
        lang=["it", "en"],
        summaries=[{"lang": "it", "text": "Specifico di questa pagina."},
                   {"lang": "en", "text": "Specific to this page."}]))

    assert page.summary_langs == ("it", "en")
    assert page.missing_summary_langs() == ()


def test_a_missing_language_summary_is_reported_and_never_repaired():
    """Reported, because the repair would be to blend — and blending is what D5 forbids. U009's
    derivation is what acts on it; the schema's job is to make it visible."""
    page = x.PageOut.model_validate(_form(lang=["it", "en"],
                                          summaries=[{"lang": "it", "text": "Solo italiano."}]))

    assert page.missing_summary_langs() == ("en",)


def test_the_frozen_corpus_validates_against_the_schema(synthetic_fixture, expected):
    """The fixture is a transcript of an answer, so it has to be an answer this schema accepts.

    If it were not, every downstream test would be asserting against a body the pipeline could
    never receive — the most expensive kind of green there is (D10).
    """
    forms = 0
    for path in sorted((synthetic_fixture / EXTRACT).glob("*.json")):
        out = x.WindowOut.model_validate_json(path.read_text())
        forms += len(out.pages)
        assert [page.page_index for page in out.pages] == list(range(1, len(out.pages) + 1))
        for page in out.pages:
            assert page.page_kind in SPEC_PAGE_KINDS
            assert page.missing_summary_langs() == ()
            assert all(isinstance(code, str) for code in page.codes)
            assert all(isinstance(topic, str) for topic in page.topics)

    assert forms == expected["extraction"]["page_forms"]


# ── the offset proof's structural half (§6.4 check 1) ───────────────────────────────────────────

def test_a_sound_window_has_no_index_problem():
    out = x.WindowOut.model_validate(json.loads(generator.window_body(15, 28)))

    assert x.page_index_problem(out, w.Window(15, 28, 1)) == ""


@pytest.mark.parametrize(("label", "indices", "expect"), [
    ("a lost page", [1, 2, 4], "missing [3]"),
    ("a page described twice", [1, 2, 2], "duplicated [2]"),
    ("an index outside the window", [1, 2, 9], "outside the window [9]"),
    ("a short response", [1, 2], "2 form(s)"),
])
def test_every_way_a_window_can_be_misindexed_is_named(label, indices, expect):
    """F13 — "never accept a partial window", in code. A 4-page window that comes back with three
    forms has lost a page of a manual, and nothing else in the pipeline would notice."""
    out = x.WindowOut.model_validate({"pages": [_form(page_index=i) for i in indices]})

    problem = x.page_index_problem(out, w.Window(1, 4, 1))
    assert expect in problem, label


# ── the four bisection triggers, through the real backend (§6.2, F13) ──────────────────────────

@pytest.mark.parametrize(("label", "body", "meta", "reason"), [
    ("the output ceiling", generator.window_body(1, 4), {"finish_reason": "MAX_TOKENS"},
     x.CEILING),
    ("an unterminated body", '{"pages": [{"page_index": 1, "summ', None, x.UNTERMINATED),
    ("an answer of the wrong shape", '{"units": []}', None, x.MALFORMED),
    ("an answer about other pages", '{"pages": []}', None, x.MISINDEXED),
])
def test_each_trigger_bisects_and_re_bills(label, body, meta, reason, tmp_path, synthetic_pdf):
    """§6.2's four triggers, each through the replay backend rather than a monkeypatch.

    The halves come back with their **own** keys, which is the port's correction: `impl` merged
    them and cached the result under the *parent's* key, so the repair was invisible on the next
    run and the receipt described a call no model ever made.
    """
    probed = _probed(synthetic_pdf)
    parent = w.Window(1, 4, 1)
    left, right = w.bisect_window(parent, "max_tokens")
    backend = _replay(tmp_path, {
        _key(synthetic_pdf, parent, probed): (body, meta),
        _key(synthetic_pdf, left, probed): (generator.window_body(1, 2), None),
        _key(synthetic_pdf, right, probed): (generator.window_body(3, 4), None),
    })

    after = _extract_one(backend, parent, synthetic_pdf, probed)

    assert [(e.window.start, e.window.end) for e in after] == [(1, 2), (3, 4)], label
    assert {e.window.bisected_from for e in after} == {reason}
    assert len({e.key for e in after}) == 2
    assert _key(synthetic_pdf, parent, probed) not in {e.key for e in after}
    assert sum(e.page_forms for e in after) == parent.pages


def test_a_clean_window_is_served_once_from_the_receipt(tmp_path, synthetic_pdf):
    """The happy path: one frozen response, one `WindowExtraction`, no bisection, origin `replay`
    — the same code path a live call takes, with a different attached service (§15 Factor IV)."""
    probed = _probed(synthetic_pdf)
    window = w.Window(1, 4, 1)
    backend = _replay(tmp_path, {
        _key(synthetic_pdf, window, probed): (generator.window_body(1, 4), None)})

    after = _extract_one(backend, window, synthetic_pdf, probed)

    assert len(after) == 1
    assert after[0].origin == "replay"
    assert after[0].page_forms == 4
    assert after[0].window.bisected_from == ""
    assert json.loads(after[0].entry.body) == json.loads(generator.window_body(1, 4))


def test_a_single_page_that_still_fails_is_unsplittable(tmp_path, synthetic_pdf):
    """F13's floor. §6.2 names the page, not a recursion limit, as the terminus: the run fails
    naming the page rather than publishing a window the model never described."""
    probed = _probed(synthetic_pdf)
    window = w.Window(7, 7, 1)
    backend = _replay(tmp_path, {_key(synthetic_pdf, window, probed): ('{"pages": []}', None)})

    with pytest.raises(w.WindowUnsplittable) as refusal:
        _extract_one(backend, window, synthetic_pdf, probed)

    assert refusal.value.details["page_no"] == 7


def test_a_partial_window_is_never_kept(tmp_path, synthetic_pdf):
    """The failure this whole section exists for: a window that describes fewer pages than it was
    sent must not become an `Extraction`. It bisects; and if the halves cannot answer either, the
    run fails rather than publishing the pages that did come back."""
    probed = _probed(synthetic_pdf)
    parent = w.Window(1, 4, 1)
    left, _ = w.bisect_window(parent, "offset")
    short = json.dumps({"pages": json.loads(generator.window_body(1, 4))["pages"][:3]})
    backend = _replay(tmp_path, {
        _key(synthetic_pdf, parent, probed): (short, None),
        _key(synthetic_pdf, left, probed): (generator.window_body(1, 2), None),
    })

    with pytest.raises(FixtureMiss) as refusal:
        _extract_one(backend, parent, synthetic_pdf, probed)

    assert refusal.value.code == "fixture_miss"


def test_the_parse_failures_are_told_apart(tmp_path):
    """Three different events, three reasons: only one of them means the prompt is wrong.

    An unterminated body is the provider's ceiling reached mid-JSON; a valid body of the wrong
    shape is an answer to a different question; a sound body with the wrong indices is an answer
    about pages that were not the ones sent. Merging them would make the run's log unusable for
    deciding whether to change the prompt or the window size.
    """
    window = w.Window(1, 2, 1)
    for body, reason in (('{"pages": [{"page_index": 1', x.UNTERMINATED),
                         ('{"units": []}', x.MALFORMED),
                         ('{"pages": []}', x.MISINDEXED)):
        entry = write(tmp_path, EXTRACT, "0" * 64, body)
        with pytest.raises(VlmSchemaInvalid) as refusal:
            x.parse(FixtureStore(tmp_path).get(EXTRACT, "0" * 64), window)
        assert refusal.value.details["reason"] == reason
        assert refusal.value.code == "vlm_schema_invalid"
        entry.unlink()


# ── the absolute page is resolved once (§6.4) ──────────────────────────────────────────────────

def test_an_extraction_resolves_each_form_to_one_absolute_page(tmp_path, synthetic_pdf):
    """`page_form(page_no)` applies the offset in one place, so no caller writes it again."""
    probed = _probed(synthetic_pdf)
    window = w.Window(3, 6, 1)
    backend = _replay(tmp_path, {
        _key(synthetic_pdf, window, probed): (generator.window_body(3, 6), None)})
    extraction = x.Extraction(plan=w.Plan(1, (window,)),
                              windows=_extract_one(backend, window, synthetic_pdf, probed))

    assert extraction.page_form(3).page_index == 1
    assert extraction.page_form(6).page_index == 4
    assert extraction.page_form(3).printed_page_no == generator.printed_label(3)
    with pytest.raises(KeyError):
        extraction.page_form(7)


# ── §5.2's prohibitions, as an AST scan ────────────────────────────────────────────────────────

def _sources() -> dict[str, ast.Module]:
    """`ingest/extract.py` and every module of `vlm/` — the two places §5.2's ban applies."""
    paths = [PACKAGE / "ingest" / "extract.py"] + sorted((PACKAGE / "vlm").rglob("*.py"))
    return {str(path.relative_to(PACKAGE)): ast.parse(path.read_text(encoding="utf-8"))
            for path in paths}


def _string_collections(tree: ast.Module) -> list[tuple[int, list[str]]]:
    """Every list/tuple/set literal of string constants, with the line it is on."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [e.value for e in node.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if values and len(values) == len(node.elts):
                found.append((node.lineno, values))
    return found


def test_no_regex_taxonomy_in_extraction_or_at_the_boundary():
    """§5.2 — a taxonomy needs a pattern to match with, and `impl` had one (`TOKEN_RE`, the
    identifier grammar). The only permitted normalisation lives in `core/variants.py`, is
    whitespace-and-spacing only, and is proved character-preserving by the I3 property test."""
    for name, tree in _sources().items():
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                     and node.module}
        assert "re" not in imported, f"{name} imports re"
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                    and n.attr in {"compile", "fullmatch"}
                    and isinstance(n.value, ast.Name) and n.value.id == "re"], name


def test_no_classification_enum_in_extraction_or_at_the_boundary():
    """§5.2 — `impl`'s `Unit.kind` was a ten-way enum of what a page *contains*, and every value
    encoded a fact about this corpus. §5.2's eight `page_kind` values are a plain value list of
    what a sheet of paper is, deliberately not an enum: a stray value normalises."""
    for name, tree in _sources().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = {ast.unparse(base) for base in node.bases}
                assert not bases & {"Enum", "StrEnum", "IntEnum", "enum.Enum", "enum.StrEnum"}, (
                    f"{name}: {node.name} is an enum")


def test_no_per_corpus_keyword_list_in_extraction_or_at_the_boundary():
    """§5.2's hardest prohibition to keep, because it grows back as a helpful special case.

    `impl`'s `_is_safety()` was a hardcoded list of safety words; a document that phrased a stop
    function differently was silently not a safety function. The scan is over string collections
    because that is the shape such a list takes when somebody adds it back.
    """
    corpus_words = ("safety", "emergency", "estop", "e-stop", "relay", "curtain", "muting",
                    "contactor", "interlock", "guard", "valve", "sensor", "machine", "hazard")
    for name, tree in _sources().items():
        for lineno, values in _string_collections(tree):
            blob = " ".join(values).lower()
            assert not [word for word in corpus_words if word in blob], (
                f"{name}:{lineno}: {values} reads like a per-corpus keyword list")


def test_the_struck_names_of_the_old_shape_are_gone():
    """§2.4/§5.2 — what went with the old shape. Named individually because each one is a place
    the previous implementation encoded corpus knowledge that this build proves instead."""
    struck = ("STRICT_KINDS", "UNIT_KINDS", "key_for_unit", "_is_safety", "classify", "Unit",
              "attrs", "refs", "identifiers", "units")
    for name, tree in _sources().items():
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        assigned = {t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                    for t in node.targets if isinstance(t, ast.Name)}
        assigned |= {node.target.id for node in ast.walk(tree)
                     if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
        assert not (defined | assigned) & set(struck), name
