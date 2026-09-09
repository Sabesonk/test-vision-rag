"""L0 — `verify_claims` (Spec §7.2.4, F2, and the mechanism I8 gates on at M6).

Two things are being tested, and the second is the one that matters most:

* the **matrix** — every `(claim, page)` pair is checked, so a draft citing two pages cannot let a
  code from the neighbour through (I8);
* the **fold** — `unverifiable` is never collapsed into `absent`. Collapsing them tells the agent
  *"that code is not on the page"* about a page nobody could read, which converts our blind spot
  into its confident denial. Every test below that names a trust level exists for that sentence.
"""
from __future__ import annotations

import pytest
from fake_store import FakeStore

from vsir.core.observed_tokens import from_texts
from vsir.core.record import PageRecord
from vsir.core.verify import (
    ABSENT,
    NOT_CURRENT,
    PRESENT,
    UNVERIFIABLE,
    PageNotFound,
    check,
    local_inventory,
    page_checks,
    page_payloads,
    verify_claims,
)
from vsir.eval import synthetic
from vsir.serve.envelope import Provenance, ToolEnvelope, VerifyResult

COLLECTION = "fake_pages"


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def store(corpus: synthetic.Corpus) -> FakeStore:
    return FakeStore(record.to_payload() for record in corpus.records(release_id="test-release"))


@pytest.fixture
def ask(store: FakeStore):
    def _ask(claims, page_ids, **kwargs):
        return verify_claims(store, COLLECTION, claims, page_ids, **kwargs)
    return _ask


def page(page_no: int, **overrides) -> dict:
    record = PageRecord(doc_id="D", revision="1", is_current=True, page_no=page_no,
                        has_text=True, text_trust="ok", text="",
                        provenance={"page_id": f"D@1#p{page_no:03d}"})
    return {**record.to_payload(), **overrides}


# ── the three states (§7.2.4) ───────────────────────────────────────────────────────────────────

def test_a_printed_code_is_present_on_the_page_that_prints_it(ask, corpus):
    verdict = ask(["SF 1.1A"], [corpus.page_id(1)]).claims["SF 1.1A"]

    assert verdict.status == PRESENT
    assert verdict.page_ids == [corpus.page_id(1)]
    assert verdict.present_instead == []


def test_verify_claims_sf_1_1a_absent_on_p008(ask, corpus):
    """§12.3's row, and F2 in one line: the tokens are on p008 and the phrase is not.

    `lookup` and `verify` share one `exact_filter`, so this verdict cannot disagree with the
    `lookup("SF 1.1A")` that returned p001 and not p008.
    """
    verdict = ask(["SF 1.1A"], [corpus.page_id(8)]).claims["SF 1.1A"]

    assert verdict.status == ABSENT
    assert verdict.page_ids == [corpus.page_id(8)]


def test_a_page_with_no_text_layer_is_unverifiable_and_never_absent(ask, corpus):
    verdict = ask(["SF 9.9"], [corpus.page_id(5)]).claims["SF 9.9"]

    assert verdict.status == UNVERIFIABLE
    assert verdict.reason == "no_text"
    assert verdict.page_ids == []


def test_an_untrusted_text_layer_is_unverifiable_even_though_the_phrase_is_there(ask, corpus):
    """§5.7 — `K404` really is in p010's text, and a garbled extraction is not evidence."""
    verdict = ask(["K404"], [corpus.page_id(10)]).claims["K404"]

    assert verdict.status == UNVERIFIABLE
    assert verdict.reason == "untrusted"


def test_a_page_that_is_not_current_is_unverifiable(ask, corpus):
    """I7 — and `unverifiable`, not `absent`: the code may well be printed on it.

    `SF 7.7A` *is* printed on the revision 0.9 page. Reporting `absent` would be false, and it
    would also leave the answer gate unable to tell a superseded citation from a scanned page.
    """
    verdict = ask(["SF 7.7A"], ["SYN-M1@0.9#p001"]).claims["SF 7.7A"]

    assert verdict.status == UNVERIFIABLE
    assert verdict.reason == NOT_CURRENT


def test_degraded_text_is_still_checkable():
    """§5.7 lists four trust levels and only two of them stop a check."""
    store = FakeStore([page(1, text_trust="degraded", text="contactor K158 on rail 2")])

    verdict = verify_claims(store, COLLECTION, ["K158"], ["D@1#p001"]).claims["K158"]

    assert verdict.status == PRESENT


# ── per (claim, page), never collapsed (I8) ─────────────────────────────────────────────────────

def test_the_matrix_is_per_claim_and_page(store, corpus):
    """AC — `present` on the page whose text has it, `absent` on the other, both visible."""
    matrix = page_checks(store, COLLECTION, ["K158"],
                         [corpus.page_id(1), corpus.page_id(2)])

    assert matrix["K158"][corpus.page_id(1)] == (PRESENT, "")
    assert matrix["K158"][corpus.page_id(2)] == (ABSENT, "")


def test_the_folded_verdict_names_only_the_pages_that_carry_the_code(ask, corpus):
    """I8's mechanism: a draft citing p002 cannot borrow p001's evidence."""
    verdict = ask(["K158"], [corpus.page_id(1), corpus.page_id(2)]).claims["K158"]

    assert verdict.status == PRESENT
    assert verdict.page_ids == [corpus.page_id(1)]
    assert corpus.page_id(2) not in verdict.page_ids


def test_an_absent_verdict_names_the_pages_the_absence_is_about(ask, corpus):
    """With an unreadable page in the set, `absent` is asserted only over the readable ones."""
    verdict = ask(["K158"], [corpus.page_id(2), corpus.page_id(5)]).claims["K158"]

    assert verdict.status == ABSENT
    assert verdict.page_ids == [corpus.page_id(2)]


def test_every_named_page_is_checked_for_every_claim(store, corpus):
    pages = [corpus.page_id(1), corpus.page_id(6), corpus.page_id(8)]

    matrix = page_checks(store, COLLECTION, ["K158", "K78"], pages)

    assert set(matrix) == {"K158", "K78"}
    assert all(set(states) == set(pages) for states in matrix.values())


def test_a_duplicated_page_or_claim_is_checked_once(store, corpus):
    matrix = page_checks(store, COLLECTION, ["K158", "K158"],
                         [corpus.page_id(1), corpus.page_id(1)])

    assert list(matrix) == ["K158"]
    assert list(matrix["K158"]) == [corpus.page_id(1)]


# ── `present_instead` (F16) ─────────────────────────────────────────────────────────────────────

def test_k73_absent_with_present_instead_k78(ask, corpus):
    """F16 — a prefix lookup over the observed tokens of the page, never a distance.

    The disclosure is lowercase because the inventory is: the text index is built with
    `lowercase=True` (§5.5) and §6.8's own export writes `codes_in_text` lowercase. §7.2.4's
    `["K78"]` is prose casing, not a second normalisation.
    """
    verdict = ask(["K73"], [corpus.page_id(6)]).claims["K73"]

    assert verdict.status == ABSENT
    assert verdict.present_instead == ["k78"]
    assert len(verdict.present_instead) <= 5


def test_a_hallucinated_code_gets_an_absent_verdict_and_nothing_to_disclose(ask, corpus):
    """I2 — p004 claims `K999` in `content.codes`; its text does not carry it."""
    verdict = ask(["K999"], [corpus.page_id(4)]).claims["K999"]

    assert verdict.status == ABSENT
    assert verdict.present_instead == []


def test_present_instead_is_drawn_from_the_named_pages_only(ask, corpus):
    """The tighter, honest reading of *"instead"*: what is on the page the claim was checked on.

    `k78` is on p006 and nowhere else, so a `K73` claim checked against p002 discloses nothing —
    the code is not "instead" on a page that does not carry it. §6.8's document-level inventory can
    be passed in explicitly when the wider statement is the wanted one.
    """
    assert ask(["K73"], [corpus.page_id(2)]).claims["K73"].present_instead == []
    assert ask(["K73"], [corpus.page_id(6)]).claims["K73"].present_instead == ["k78"]


def test_an_explicit_inventory_overrides_the_local_one(ask, corpus):
    """§6.8 — the document-level inventory, once U011 writes it to the run's control point."""
    document_wide = from_texts(corpus.doc_id,
                               [record.text for record in corpus.current_records()])

    verdict = ask(["K73"], [corpus.page_id(2)], inventory=document_wide).claims["K73"]

    assert verdict.status == ABSENT
    assert verdict.present_instead == ["k78"]


def test_a_present_verdict_never_carries_a_disclosure(ask, corpus):
    verdict = ask(["K78"], [corpus.page_id(6)]).claims["K78"]

    assert verdict.status == PRESENT
    assert verdict.present_instead == []


def test_an_unverifiable_verdict_never_carries_a_disclosure(ask, corpus):
    """Nothing was read, so there is nothing to say is there instead."""
    verdict = ask(["K73"], [corpus.page_id(5)]).claims["K73"]

    assert verdict.status == UNVERIFIABLE
    assert verdict.present_instead == []


def test_pages_from_two_documents_share_no_inventory():
    """A code from one binder must never be disclosed as what is on a page of another."""
    payloads = {"A@1#p001": {"doc_id": "A", "text": "K158"},
                "B@1#p001": {"doc_id": "B", "text": "K162"}}

    assert local_inventory(payloads) is None


# ── the missing page is a 404, never a verdict (§7.1) ───────────────────────────────────────────

def test_a_page_that_is_not_in_the_collection_is_an_error(store):
    with pytest.raises(PageNotFound) as refusal:
        page_payloads(store, COLLECTION, ["SYN-M1@1.0#p999"])

    assert refusal.value.page_ids == ["SYN-M1@1.0#p999"]


def test_a_malformed_page_id_is_refused_before_anything_is_checked(store):
    with pytest.raises(ValueError, match="not a page_id"):
        page_payloads(store, COLLECTION, ["not-a-page-id"])


def test_no_pages_is_no_work(store):
    assert page_payloads(store, COLLECTION, []) == {}
    assert verify_claims(store, COLLECTION, ["K158"], []).claims["K158"].status == UNVERIFIABLE


def test_no_claims_is_an_empty_result(store, corpus):
    result = verify_claims(store, COLLECTION, [], [corpus.page_id(1)])

    assert result.claims == {}


# ── the Family B envelope (§7.1, I5) ────────────────────────────────────────────────────────────

def test_a_verify_where_every_claim_is_absent_is_still_ok(ask, corpus):
    """The whole reason Family B exists: the call ran, and the answer is no."""
    result = ask(["K999", "K73"], [corpus.page_id(4)])
    envelope = ToolEnvelope[VerifyResult](
        status="ok", result=result, provenance=Provenance(release_id="test"))

    assert [verdict.status for verdict in result.claims.values()] == [ABSENT, ABSENT]
    assert envelope.status == "ok"


def test_the_verdict_vocabulary_is_exactly_three_words(ask, corpus):
    result = ask(["SF 1.1A", "K999", "SF 9.9"],
                 [corpus.page_id(1), corpus.page_id(5)])

    assert {verdict.status for verdict in result.claims.values()} <= {PRESENT, ABSENT,
                                                                      UNVERIFIABLE}
    assert not [field for field in type(next(iter(result.claims.values()))).model_fields
                if field == "verified"], "`verified` is a boolean about a surface, not a check"


# ── one code path (I3, F2) ──────────────────────────────────────────────────────────────────────

def test_verify_asks_the_index_the_same_question_lookup_does(store, corpus):
    """The one `exact_filter`, so F1 and F2 cannot come apart.

    Same label, same variants, same phrase semantics — the only difference is the scope, which is
    one page here and the whole corpus there.
    """
    scattered, printed = corpus.page_id(8), corpus.page_id(1)

    states = page_checks(store, COLLECTION, ["SF 1.1A"], [printed, scattered])["SF 1.1A"]

    assert states[printed][0] == PRESENT
    assert states[scattered][0] == ABSENT


def test_check_reports_a_reason_only_when_it_could_not_look(store, corpus):
    payloads = page_payloads(store, COLLECTION, [corpus.page_id(1), corpus.page_id(5)])

    looked = check(store, COLLECTION, "SF 1.1A", corpus.page_id(1), payloads[corpus.page_id(1)])
    could_not = check(store, COLLECTION, "SF 1.1A", corpus.page_id(5), payloads[corpus.page_id(5)])

    assert looked == (PRESENT, "")
    assert could_not == (UNVERIFIABLE, "no_text")


def test_verify_costs_one_retrieve_and_one_count_per_checkable_pair(store, corpus):
    before = store.calls

    verify_claims(store, COLLECTION, ["K158", "K78"],
                  [corpus.page_id(1), corpus.page_id(5)])

    # one retrieve, then a count for each of the two claims on the one checkable page
    assert store.calls - before == 1 + 2
