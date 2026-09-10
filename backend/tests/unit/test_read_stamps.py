"""L0 — the stamp `read` puts on every code it returns (Spec §7.2.6 Loop 1, §7.2.4, F19).

`read` is the one tool that spends, and almost none of what makes it *safe* costs anything. This
suite is that part: the three-state stamp, the mandatory `sufficient`, the pinned dpi, the caps in
front of the money — and four structural assertions that are the real deliverable, because they
are the ones a well-meaning change would quietly break.

**The stamp is not a new idea and must never become one.** Every code goes through
:func:`~vsir.core.verify.verify_claims`, the same function `POST /tools/verify` calls, which asks
:func:`~vsir.core.exact.exact_filter` the question `lookup` asks. `impl` did the opposite — its
``read()`` stamped ``text_layer_backed`` from its own ``token_set()`` over its own tokeniser, with
no relationship to the index anything else searched — and a second matcher is free to disagree
with the index it is checking (F2). So one test proves the routing and one scans the module for a
matcher of its own.

Nothing here touches a store, a raster, a model or a network: the fixtures are the M1 corpus's
payloads in memory, which is also why every row below can be read as *"this is true of the
shipped code"* rather than *"this passed in an environment"*.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fake_store import FakeStore

from vsir.config import DPI_ANSWER, MAX_READ_PAGES
from vsir.core.verify import ABSENT, PRESENT, UNVERIFIABLE
from vsir.eval import synthetic
from vsir.serve.app import ReadRequest
from vsir.serve.caps import ToolError
from vsir.serve.envelope import ReadResult
from vsir.serve.tools import read as read_module
from vsir.serve.tools.read import (
    FLAG_NO_TEXT_LAYER,
    FLAG_UNTRUSTED_TEXT,
    FLAG_UNVERIFIED_CODES,
    READ_FLAGS,
    READ_SCHEMA_HASH,
    ReadOut,
    parse,
    precheck,
)
from vsir.vlm import Entry, VlmSchemaInvalid, prompt, read_key

COLLECTION = "fake_pages"
SOURCE = Path(read_module.__file__)

#: The M1 corpus rows this suite stands on, from `data/fixtures/synthetic_pages/expected.json`.
#: Named here so a failure reads as *"K73 stopped being absent on p006"* rather than as an index.
P001, P005, P006, P010 = (f"SYN-M1@1.0#p{n:03d}" for n in (1, 5, 6, 10))


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def store(corpus: synthetic.Corpus) -> FakeStore:
    return FakeStore(record.to_payload() for record in corpus.records(release_id="test-release"))


@pytest.fixture(scope="module")
def payloads(corpus: synthetic.Corpus) -> dict[str, dict]:
    return {record.provenance.page_id: record.to_payload()
            for record in corpus.records(release_id="test-release")}


def stamp(store: FakeStore, codes, page_ids):
    return read_module._stamp(store, COLLECTION, codes, page_ids)


def body(**fields) -> Entry:
    """A frozen response body, as the boundary hands it over: verbatim bytes under a key."""
    return Entry(key="k" * 8, namespace="read", body=json.dumps(fields))


def source_tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def called_names(tree: ast.Module) -> set[str]:
    """Every name this module *calls*, attribute calls included, as the caller spells them."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


# ── the three states, and they are `verify`'s (§7.2.6 Loop 1, §7.2.4) ───────────────────────────

def test_a_code_the_page_prints_is_stamped_present(store: FakeStore):
    """The ordinary case, and the only one that lets a code into an answer (I8, U022)."""
    stamped = stamp(store, ["K158"], [P001])

    assert [(code.raw, code.status) for code in stamped] == [("K158", PRESENT)]
    assert stamped[0].page_ids == [P001], "a `present` stamp names the pages that carry it"


def test_a_code_the_page_does_not_print_is_absent_with_present_instead(store: FakeStore):
    """§7.2.6's own example: the model misread a character, and the page says what it does hold.

    `K73` is not on p006 and `K78` is. That disclosure is a **prefix lookup over observed
    tokens** and never a nearest match (F16, §7.2.4) — it cannot be returned as the code, and the
    caller is told *"different part"*, not *"did you mean"*.
    """
    stamped = stamp(store, ["K73"], [P006])

    assert (stamped[0].status, stamped[0].present_instead) == (ABSENT, ["k78"])
    assert stamped[0].page_ids == [P006], "an `absent` names the pages the absence was asserted on"


def test_every_code_on_a_page_with_no_text_layer_is_unverifiable(store: FakeStore):
    """§7.2.6, verbatim: *"On a page with no text layer **every** code is `unverifiable`"*.

    Including a code that is genuinely printed elsewhere in the same document. The check is per
    `(code, page)`, and a page nobody can read cannot support a code that lives next door — R2
    says this stays true forever, and that the badge is the deliverable rather than a gap.
    """
    stamped = stamp(store, ["SF 9.9", "K158"], [P005])

    assert {code.status for code in stamped} == {UNVERIFIABLE}
    assert {code.reason for code in stamped} == {"no_text"}
    assert all(not code.page_ids for code in stamped), (
        "an `unverifiable` names no page: nothing was checked, so there is nothing to name")


def test_an_untrusted_extraction_is_unverifiable_and_never_absent(store: FakeStore):
    """§5.7, §11.3 — a collapsed `grounded_rate` makes a page unsearchable, not empty.

    This is the fold the whole vocabulary exists for. Told `absent` about a garbled text layer,
    an agent concludes the code is not printed on the page; told `unverifiable`, it knows the
    page was never read.
    """
    stamped = stamp(store, ["K404"], [P010])

    assert (stamped[0].status, stamped[0].reason) == (UNVERIFIABLE, "untrusted")


def test_the_states_are_exactly_the_three_verify_uses():
    """One vocabulary, one meaning (§7.2.6). The model type is the enforcement, not a convention."""
    from vsir.serve.envelope import ClaimVerdict, ReadCode

    assert (ReadCode.model_fields["status"].annotation
            == ClaimVerdict.model_fields["status"].annotation)


# ── one matcher, and it is `core/verify.py`'s (F2) ──────────────────────────────────────────────

def test_the_stamp_routes_through_verify_claims_and_nothing_else(store: FakeStore, monkeypatch):
    """Break :func:`verify_claims` and stamping breaks. There is no second path to fall back to."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("verify_claims")

    monkeypatch.setattr(read_module, "verify_claims", refuse)
    with pytest.raises(AssertionError, match="verify_claims"):
        stamp(store, ["K158"], [P001])


@pytest.mark.parametrize("banned", ["exact_filter", "MatchPhrase", "MatchText", "variants", "tok"])
def test_read_builds_no_matcher_of_its_own(banned: str):
    """The import-graph assertion of U020's acceptance list, as a scan of the module itself.

    `read` may not phrase-match, tokenise or build a filter. Every one of those is a decision
    about what *counts* as the same code, and there is exactly one place in this system that
    makes it (I3, §5.6). A second one here would be free to drift from the index it is checking,
    which is the failure F2 names.
    """
    tree = source_tree()
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) for alias in node.names}

    assert banned not in imported | called_names(tree)


def test_read_imports_the_shared_check_explicitly():
    """The positive half: it is `core.verify` this module leans on, by name."""
    sources = {node.module for node in ast.walk(source_tree())
               if isinstance(node, ast.ImportFrom)}

    assert "vsir.core.verify" in sources


# ── no retrieval judgment happens here (§7.6, §7.2.6) ───────────────────────────────────────────

@pytest.mark.parametrize("decision", [
    "skim_pages", "skim_documents", "skim_sections", "lookup", "resolve", "query_points",
    "search", "rrf", "fuse", "NextMoves",
])
def test_read_never_chooses_or_ranks_a_page(decision: str):
    """*"Retrieval judgment never happens inside `read`"* — that would make the engine the answerer.

    The caller named the pages. This module renders them, asks one question about them and
    stamps what comes back; it does not search, rank, re-scope, or hand back a `next` move. On
    `sufficient: false` the **runner** decides what to do (U021, U022), which is the whole point
    of the field.
    """
    assert decision not in called_names(source_tree())


def test_the_result_carries_no_next_and_no_score():
    """§7.6 — no similarity value anywhere, and no affordance that would be a suggestion."""
    assert "score" not in ReadResult.model_fields
    assert "next" not in ReadResult.model_fields


# ── what the model may decide, and what it may not (§7.2.6, I2) ─────────────────────────────────

def test_the_model_is_asked_for_exactly_three_things():
    """No field in which it could stamp its own code, and none in which it could name a page.

    `impl` returned ``identifiers[]`` with a ``text_layer_backed`` flag **we** computed, and that
    was right; what is new here is that the response schema itself gives the model nowhere to
    make either claim. A field it cannot fill is a failure mode that cannot occur.
    """
    assert set(ReadOut.model_fields) == {"extract", "codes", "sufficient"}


def test_sufficient_is_mandatory_and_a_response_without_it_does_not_parse():
    """§7.2.6 — *"`sufficient` is mandatory"*, so there is no default to fall back to.

    A default would have to be one of the two answers the field exists to separate. `True` lets
    an agent compose from pages that never contained an answer; `False` sends it looking again
    for something it has already found. So a response that omits it is refused.
    """
    with pytest.raises(VlmSchemaInvalid):
        parse(body(extract="something", codes=["K158"]))


def test_a_paid_response_carrying_an_unexpected_field_is_refused():
    """``extra="forbid"``: a field this release did not ask for is a refusal, never a drop."""
    with pytest.raises(VlmSchemaInvalid):
        parse(body(extract="", codes=[], sufficient=True, confidence=0.9))


def test_an_honest_empty_extract_is_a_perfectly_good_response():
    """The abstention path, and it is a *parsed* response rather than an error (§7.2.6)."""
    out = parse(body(extract="", codes=[], sufficient=False))

    assert (out.extract, out.codes, out.sufficient) == ("", [], False)


# ── the codes list itself ───────────────────────────────────────────────────────────────────────

def test_codes_are_de_duplicated_in_emission_order(store: FakeStore):
    """One code named twice is one code read once — two stamps would double-count the evidence."""
    stamped = stamp(store, ["K158", "K73", "K158"], [P001, P006])

    assert [code.raw for code in stamped] == ["K158", "K73"]


def test_an_empty_code_list_asks_the_index_nothing(store: FakeStore):
    """A model that named no code costs no count. Nothing to check is not the same as nothing found."""
    before = store.calls

    assert stamp(store, ["", "   "], [P001]) == []
    assert store.calls == before


# ── the flags (§7.2.6) ──────────────────────────────────────────────────────────────────────────

def test_the_flags_are_a_closed_server_derived_list(store: FakeStore, payloads: dict[str, dict]):
    """Server-derived, every one: the model has no field in which to raise a flag."""
    scanned = read_module._flags(stamp(store, ["K158"], [P005]), {P005: payloads[P005]})
    clean = read_module._flags(stamp(store, ["K158"], [P001]), {P001: payloads[P001]})
    untrusted = read_module._flags(stamp(store, ["K404"], [P010]), {P010: payloads[P010]})

    assert scanned == [FLAG_NO_TEXT_LAYER, FLAG_UNVERIFIED_CODES]
    assert clean == []
    assert untrusted == [FLAG_UNTRUSTED_TEXT, FLAG_UNVERIFIED_CODES]
    assert set(scanned) | set(untrusted) <= set(READ_FLAGS)


# ── the dpi is pinned, and the caps are in front of the money (§7.2.6, §7.3, F18) ───────────────

def test_the_request_has_no_dpi_and_no_region():
    """A caller cannot change the dpi, because the dpi is an input to ``read_key`` (§6.3).

    Refused rather than ignored: ``extra="forbid"`` makes a hopeful ``dpi: 400`` an
    `invalid_request` naming the field. A parameter silently dropped would let a caller believe
    it had bought a 400-dpi read of a part number it cannot make out.
    """
    from pydantic import ValidationError

    assert set(ReadRequest.model_fields) == {"page_ids", "question"}
    with pytest.raises(ValidationError):
        ReadRequest.model_validate({"page_ids": ["a"], "question": "q", "dpi": 400})


def test_the_only_dpi_this_module_knows_is_the_pinned_one():
    """No dpi literal in the source: the render and the key both read `DPI_ANSWER` (§4.2, SA-12)."""
    literals = {node.value for node in ast.walk(source_tree())
                if isinstance(node, ast.Constant) and isinstance(node.value, int)}

    assert DPI_ANSWER == 220
    assert not literals & {36, 72, 150, 220, 300, 400}


@pytest.mark.parametrize("pages, question, code", [
    (["a", "b", "c", "d"], "why?", "read_page_cap_exceeded"),
    ([], "why?", "read_empty"),
    (["a"], "   ", "read_question_missing"),
])
def test_the_precheck_refuses_by_name_before_a_cent_is_committed(pages, question, code):
    """Each a typed 400 naming its bound (§7.3) — never a clamp and never a truncated page list.

    :func:`~vsir.serve.tools.read.precheck` is what the dispatcher runs **before** it charges the
    quota, so a caller that named four pages is told so with its budget untouched (F18).
    """
    with pytest.raises(ToolError) as raised:
        precheck(pages, question)

    assert raised.value.code == code
    assert raised.value.http_status == 400


def test_three_pages_are_fine_and_a_repeat_is_one_page():
    """§7.3 bounds *pages*: one page named twice is one page rendered once and asked once."""
    assert MAX_READ_PAGES == 3
    precheck(["a", "b", "c"], "why?")
    precheck(["a", "a", "b", "b"], "why?")


# ── the key: a new question is a miss (F19, §6.3) ───────────────────────────────────────────────

def key(question: str, hashes=("h1", "h2")) -> str:
    return read_key(list(hashes), vlm_model="gemini-3.8-flash", prompt_version="s2-v1",
                    dpi=DPI_ANSWER, schema_hash=READ_SCHEMA_HASH, question=question)


def test_a_new_question_about_the_same_pages_is_a_cache_miss():
    """F19, and it is the whole of F19: the question is on the key, so it cannot be answered
    from the last question's response."""
    assert key("what releases the interlock?") != key("which contactor is named?")


def test_the_same_question_about_the_same_pages_is_the_same_key():
    """The other half. A cache that missed on a repeat would make `read` bill twice for one answer."""
    assert key("what releases the interlock?") == key("what releases the interlock?")


def test_the_pages_and_their_order_are_on_the_key():
    """A model shown the same pages in a different order is being asked a different question."""
    assert key("q", ("h1", "h2")) != key("q", ("h2", "h1"))
    assert key("q", ("h1", "h2")) != key("q", ("h1", "h3"))


def test_the_dpi_is_on_the_key_which_is_why_it_cannot_be_a_parameter():
    """SA-12's consequence, stated as a test: vary the dpi and the receipt is a different one."""
    pinned = key("q")
    at_400 = read_key(["h1", "h2"], vlm_model="gemini-3.8-flash", prompt_version="s2-v1",
                      dpi=400, schema_hash=READ_SCHEMA_HASH, question="q")

    assert pinned != at_400


def test_a_read_without_a_question_cannot_even_be_keyed():
    """The refusal below the typed 400: `read` without a question is `fetch` (§7.2.5)."""
    with pytest.raises(ValueError, match="question"):
        key("   ")


# ── the prompt is part of the release (§15 Factor III, F11) ─────────────────────────────────────

def test_the_read_prompt_is_the_text_released_under_the_configured_version():
    """An edit to `prompts/read.md` without a new ``VSIR_PROMPT_VERSION`` fails **here**.

    The version is a label, and a label only describes the text while the two move together. Left
    unchecked, an edited prompt would serve every cached and frozen response under the old
    version as though the new instructions had produced it (F11).
    """
    released = prompt("read", "s2-v1")

    assert released.stage == "read"
    assert "sufficient" in released.text
    # `prompt()` itself compares the digest to PROMPT_DIGESTS and refuses a mismatch; this asserts
    # the comparison actually happened against a published entry rather than a missing one.
    assert released.digest


def test_the_schema_hash_is_computed_from_the_schema_and_not_written_down():
    """`impl`'s hand-bumped ``SCHEMA_VERSION`` is correct only while somebody remembers (B1)."""
    from vsir.ingest.extract import schema_hash

    assert READ_SCHEMA_HASH == schema_hash(ReadOut)
    assert READ_SCHEMA_HASH != schema_hash(ReadResult)
