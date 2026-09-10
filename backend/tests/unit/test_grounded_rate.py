"""L0/L1 — `grounded_rate`, `text_trust` and the aggregates (Spec §5.7, §11.1, §11.3, F4).

One `0.0` where a `None` belongs quarantines every scanned document in the corpus. That is the
whole risk this suite exists for: §11.1 blocks publication under a median of 0.8, the median is
taken over pages, and a scanned page has nothing to be grounded *in* — so scoring it zero fails
exactly the documents F4 requires to be published-and-unsearchable.

The membership question is a **phrase**, not a set intersection (§5.7, §5.6). A `token_set`
intersection cannot see `SF 1.3A` or `EAO 84-5140.1003` at all, and on this corpus it would
ground six of a typical page's ten codes — a median of 0.6, under the gate, on a document with
nothing wrong with it.
"""
from __future__ import annotations

import pytest

from vsir.core import health


# ── the rate itself ─────────────────────────────────────────────────────────────────────────────

def test_a_page_with_no_text_layer_rates_none_not_zero():
    """§5.7, and the reason the whole module exists (F4)."""
    assert health.grounded_rate(seen=40, grounded=0, has_text=False) is None
    assert health.grounded_rate(seen=0, grounded=0, has_text=False) is None


def test_a_page_with_text_and_no_codes_rates_one():
    """AC: nothing was claimed, so nothing is unbacked. Not 0.0, and not `None`."""
    assert health.grounded_rate(seen=0, grounded=0, has_text=True) == 1.0


@pytest.mark.parametrize("seen,grounded,expected", [(10, 10, 1.0), (11, 10, 10 / 11),
                                                    (4, 1, 0.25), (40, 0, 0.0)])
def test_the_rate_is_the_share_of_codes_the_text_backs(seen, grounded, expected):
    assert health.grounded_rate(seen=seen, grounded=grounded, has_text=True) == expected


def test_more_grounded_than_seen_is_a_bug_and_raises():
    """A rate over 1.0 would read as "better than perfect" and mean the caller counted twice."""
    with pytest.raises(ValueError):
        health.grounded_rate(seen=2, grounded=3, has_text=True)


# ── membership is a phrase (§5.6, I3) ───────────────────────────────────────────────────────────

def test_a_multi_token_code_grounds_because_the_question_is_a_phrase():
    """The correction to §5.7's snippet, asserted: a set intersection could not see any of these."""
    text = "SF 1.3A) EMERGENCY STOP\nB213 --> K113 - SI2\nEAO 84-5140.1003  SCHNEIDER ZB4-BS844"
    codes = ["SF 1.3A", "EAO 84-5140.1003", "ZB4-BS844", "K113"]

    assert health.grounded_codes(codes, text) == tuple(codes)
    assert health.codes_in_text(codes) == ["eao 84-5140.1003", "k113", "sf 1.3a", "zb4-bs844"]


def test_a_code_the_page_does_not_print_does_not_ground():
    text = "B213 --> K113 - SI2"
    assert health.grounded_codes(["K114", "K113"], text) == ("K113",)


def test_a_re_spaced_spelling_still_grounds_and_a_changed_character_never_does():
    """`variants()` re-spaces and only re-spaces (I3, F3).

    The page prints the code closed up and the model reported it spaced; the whitespace-removed
    variant is what grounds it. The second assertion is the half that matters: one character
    different is a different component in this corpus, and no variant can ever produce it.
    """
    text = "the interlock SF1.3A is monitored"

    assert health.grounded_codes(["SF 1.3A"], text) == ("SF 1.3A",)
    assert health.grounded_codes(["SF 1.4A"], text) == ()


def test_codes_in_text_is_collapsed_lowercased_and_deduplicated():
    """§6.8's export shape: `["k158", "q25", "sf 1.2a"]`."""
    assert health.codes_in_text(["SF  1.2A", "sf 1.2a", "K158", " ", ""]) == ["k158", "sf 1.2a"]


# ── the trust ladder ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rate,expected", [(1.0, "ok"), (0.8, "ok"), (0.79, "degraded"),
                                           (0.2, "degraded"), (0.19, "untrusted"),
                                           (0.0, "untrusted")])
def test_the_trust_ladder_follows_the_rate(rate, expected):
    assert health.page_trust(rate, has_text=True) == expected


def test_no_text_is_final_and_nothing_promotes_it():
    """§5.7 — `has_text == false` ⇒ `text_trust == "no_text"`, whatever the model read."""
    assert health.page_trust(1.0, has_text=False) == "no_text"
    assert health.page_trust(None, has_text=False) == "no_text"


def test_a_collapsed_document_demotes_its_pages_but_never_a_scanned_one():
    """§11.3 — the document-level signal has to reach the pages, or it changes nothing.

    `no_text` survives the demotion: that page is already unsearchable and *why* it is
    unsearchable is a fact about the page, which `verify` reports back by name (§7.2.4).
    """
    assert health.demote("ok", "untrusted") == "untrusted"
    assert health.demote("degraded", "untrusted") == "untrusted"
    assert health.demote("no_text", "untrusted") == "no_text"
    assert health.demote("ok", "ok") == "ok"


# ── the aggregates ignore the pages with no rate ────────────────────────────────────────────────

def test_the_median_ignores_the_pages_with_no_rate():
    """AC: the document median ignores `has_text == false` pages — it does not read them as 0."""
    assert health.median([None, None, 1.0, 1.0, 0.9]) == 1.0
    # The same pages scored 0.0 instead would put this document under §11.1's 0.8 gate.
    assert health.median([0.0, 0.0, 1.0, 1.0, 0.9]) == 0.9


def test_a_fully_scanned_document_has_no_median_at_all():
    """§11.1 — at 0.0 text coverage the gate is **skipped**, not failed (F4, D3)."""
    document = health.document_health([None, None], [False, False])

    assert document.grounded_median is None
    assert document.fully_scanned is True
    assert document.text_trust == "no_text"
    assert document.searchable_ratio == 0.0


def test_document_health_is_page_parallel_or_it_raises():
    """Zipping short here would take the median over a prefix of the document."""
    with pytest.raises(ValueError):
        health.document_health([1.0, 1.0], [True])


def test_searchable_ratio_counts_pages_not_characters():
    assert health.searchable_ratio([True, True, False, False]) == 0.5
    assert health.searchable_ratio([]) == 0.0


# ── on the corpus ───────────────────────────────────────────────────────────────────────────────

def test_the_corpus_rates_none_on_exactly_its_scanned_pages(derived, expected):
    """AC: `grounded_rate` is `None` on every `has_text == False` page, and only those."""
    rated_none = sorted(page.page_no for page in derived.pages
                        if page.record.content.grounded_rate is None)
    no_text = sorted(page.page_no for page in derived.pages if not page.record.has_text)

    assert rated_none == expected["pages_without_text"] == no_text
    assert all(page.record.text_trust == "no_text" for page in derived.pages
               if not page.record.has_text)


def test_the_corpus_median_clears_the_publish_gate(derived):
    """§11.1 — the whole point of the phrase correction: a healthy document publishes."""
    assert derived.health.grounded_median == 1.0
    assert derived.health.grounded_median >= health.TRUST_OK_MIN
    assert derived.health.text_trust == "ok"
    assert derived.health.searchable_ratio == pytest.approx(40 / 42)


def test_only_the_page_carrying_the_ungrounded_code_is_marked_down(derived, expected):
    """AC: a page whose codes are all printed on it rates 1.0; the one misread costs its page."""
    loose = expected["extraction"]["ungrounded"]
    rates = {page.page_no: page.record.content.grounded_rate for page in derived.pages}

    assert rates[loose["page"]] < 1.0
    assert [page_no for page_no, rate in rates.items()
            if rate is not None and rate < 1.0] == [loose["page"]]
    # Still `ok`: one misread code in eleven is not a broken text layer (§5.7).
    assert derived.page(loose["page"]).record.text_trust == "ok"


def test_a_page_with_codes_and_no_text_layer_still_rates_none(derived):
    """The §5.7 case in prose: codes read off a raster, and nothing to check them against."""
    for page in derived.pages:
        if not page.record.has_text:
            assert page.record.content.grounded_rate is None
            assert page.record.content.codes_in_text == []
