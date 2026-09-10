"""L2 — §12.3's PARITY row, against a real Qdrant: *every identifier the old gate accepted is
still findable by phrase* (Spec §12.1, §12.3 · plan U012).

R7 is the risk this suite answers: the port is a rewrite of 3,268 lines that had no tests. `impl`'s
exact surface was a curated keyword payload built from an identifier grammar and matched with
`MatchValue`; C1 struck the grammar and C2 replaced the mechanism with `MatchPhrase` over the
extracted text. Nothing about that is obviously safe. This suite makes it an assertion over 405
identifier shapes a real corpus actually printed — ``SF 1.1A``, ``EAO 84-5140.0020``,
``B&R X20SI4100``, ``K616-K626``, ``SAPP02D-06A0001``, ``10.2.3.1``, ``0.03`` — and it costs
nothing, because `impl` already paid for every one of them.

It runs against a collection of its own, seeded from `vsir.eval.legacy` and dropped on the way out.
The records are a projection (see that module's docstring): every string in the ``text`` of this
corpus was proved printed on that page by the old run's own gate, and nothing the model said is in
it. So a PASS is evidence and a FAIL is a defect — while the **GAINS** row is a report, never a
diff to reconcile (§12.3, verbatim).

What this cannot cover is :data:`~vsir.eval.legacy.NO_LEGACY_COVERAGE`, printed beside the results
by the last test in the file so that a green run is never mistaken for sign-off.
"""
from __future__ import annotations

from typing import Any

import pytest
from qdrant_client import QdrantClient

from vsir.eval import legacy
from vsir.serve.envelope import Provenance, Status
from vsir.serve.tools.lookup import lookup

EMBED_DIM = 1536
PROVENANCE = Provenance(run_id=legacy.SEED_RUN_ID, release_id="test")


@pytest.fixture(scope="module")
def baseline() -> legacy.Baseline:
    return legacy.load()


@pytest.fixture(scope="module")
def seeded(qdrant: QdrantClient, baseline: legacy.Baseline) -> str:
    """The ported baseline in a collection of its own, dropped at the end of the module.

    Created through `core.indexed.create_collection` and the same `eval.synthetic.seed` the M1
    corpus uses — one seeding path, so a green suite is evidence about the shipped creation code
    and not about a test's private setup. The collection name is ``…_legacy_…``: these points are a
    projection of a superseded run and must be impossible to confuse with a published page.
    """
    collection = legacy.legacy_collection("vsir_pages_parity", EMBED_DIM)
    legacy.seed(qdrant, collection, baseline.records(), dim=EMBED_DIM)
    try:
        yield collection
    finally:
        legacy.drop(qdrant, collection)


@pytest.fixture
def ask(qdrant: QdrantClient, seeded: str):
    def _ask(label: str, **kwargs: Any):
        return lookup(qdrant, seeded, label, provenance=PROVENANCE, **kwargs)
    return _ask


def page_scope(baseline: legacy.Baseline, page_id: str) -> dict[str, Any]:
    """A scope naming exactly one page, through `INDEXED` keys only.

    ``page_id`` is not filterable — it is not in `INDEXED` (§5.4) — and asking for it would be a
    typed 400 rather than a narrower answer. The three keys that identify a page are.
    """
    doc_id, rest = page_id.split("@", 1)
    revision, page_no = rest.split("#p", 1)
    return {"doc_id": doc_id, "revision": revision, "page_no": int(page_no)}


# ── the PARITY row ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    pytest.param(raw, id=raw) for raw in legacy.load().accepted_raws()
])
def test_an_identifier_the_old_gate_accepted_is_still_found_by_phrase(raw, ask, baseline):
    """AC: every identifier in `labels.jsonl` returns ``total >= 1`` — one PASS row each.

    And more than the AC asks: the pages the old run recorded it on are the pages that come back.
    ``total`` is the size of the set, so a capped result still proves the count; the page check
    runs where the whole set fits in the cap, which is 400 of the 405.
    """
    expected = sorted(page_id for page_id, accepted in baseline.accepted() if accepted == raw)

    response = ask(raw, scope=None)

    assert response.status is Status.OK, f"{raw} was accepted by the old gate and is not found"
    assert response.total >= 1
    if not response.capped:
        assert set(expected) <= {hit.page_id for hit in response.hits}
    assert all(hit.verified for hit in response.hits)


def test_the_whole_parity_set_is_the_size_the_export_recorded(baseline):
    """1,644 (page, identifier) pairs over 405 distinct identifiers — the denominator, stated."""
    assert len(baseline.accepted()) == 1644
    assert len(baseline.accepted_raws()) == 405


@pytest.mark.parametrize("label,page_id", [
    ("SF 1.1A", "TC1E-SF@1.3#p001"),
    ("SF 5.5b", "TC1E-SF@1.3#p031"),
])
def test_the_acceptance_tables_own_rows_hold_on_the_legacy_baseline(label, page_id, ask):
    """§12.3's first two rows, on real data: exactly one page each.

    These are the rows any-order matching would get wrong — ``SF 1.1A`` returns three pages and
    ``SF 5.5b`` two if the mechanism is `MatchText` rather than a phrase (F1). They also decided
    which of `impl`'s five exports could be the baseline at all: `r-poc-3` and `r-poc-4` withheld
    both of these labels, and a baseline that called ``SF 1.1A`` unbacked would contradict the
    acceptance table it is supposed to be measured against.
    """
    response = ask(label)

    assert response.status is Status.OK
    assert response.total == 1
    assert [hit.page_id for hit in response.hits] == [page_id]


def test_a_multi_token_identifier_is_matched_as_a_phrase_and_not_as_tokens(ask, baseline):
    """``EAO 84-5140.0020`` is four tokens to Qdrant — ``[eao, 84, 5140, 0020]``.

    `impl` kept it as one token by regex and could not find it at all, having dropped it before the
    gate. Here it is found, on the page whose text layer `impl` recorded, and it is found as a
    contiguous run: the page that prints ``84`` elsewhere is not a hit.
    """
    response = ask("EAO 84-5140.0020")

    assert response.status is Status.OK
    assert "TC1E-SF@1.3#p001" in {hit.page_id for hit in response.hits}
    assert response.total == 1


def test_the_scanned_document_answers_not_searchable_rather_than_not_found(ask):
    """F4 — `CE-TC1AV8` has no text layer, so nothing was searchable rather than nothing matched.

    The distinction is the whole reason the status enum has four absences. An agent told
    `not_found` stops; an agent told `not_searchable` knows a `read` of the page is the next move.
    """
    response = ask("C24", scope={"doc_id": "CE-TC1AV8"})

    assert response.status is Status.NOT_SEARCHABLE
    assert response.hits == []
    assert response.scope_stats.pages == 1
    assert response.scope_stats.pages_no_text == 1


def test_a_near_miss_of_a_real_identifier_is_never_returned(ask, baseline):
    """I3 on real shapes: a variant re-spaces, so one character apart can never match.

    ``K158`` is printed on `TC1E-SF` page 1 and ``K159`` is not. No amount of re-spacing turns one
    into the other, which is why there is no edit distance anywhere in the system (§7.6).
    """
    real = ask("K158")
    near = ask("K159")

    assert real.status is Status.OK
    assert near.hits == []
    assert near.status in (Status.NOT_FOUND, Status.NOT_SEARCHABLE)


# ── the GAINS row ───────────────────────────────────────────────────────────────────────────────

def test_the_gains_are_recorded_and_do_not_fail_the_suite(ask, baseline, capsys):
    """§12.3: *a code the old grammar dropped but the phrase index finds is a **gain***.

    So this test reports rather than reconciles. Every gain is checked against the index — it has
    to be genuinely findable to be one — and against `labels.jsonl`, which must not already contain
    it. The two the acceptance table names, ``EAO 84-5140.0020`` and ``B&R X20SI4100``, are the
    ones this baseline can prove: both are printed on the one page `impl` recorded verbatim, both
    were dropped before the old gate ever saw them, and a technician asking *"what part replaces
    the emergency-stop button"* could not have been answered by the old surface.
    """
    accepted = set(baseline.accepted())
    gains = baseline.gains()

    with capsys.disabled():
        print(f"\nGAINS — {len(gains)} sighting(s), {len(baseline.gains_by_code())} distinct "
              f"code(s) the old grammar dropped and the phrase index finds:")
        for code, pages in baseline.gains_by_code():
            print(f"  + {code:42s} {len(pages):3d} page(s)   e.g. {pages[0]}")

    for page_id, code in gains:
        assert (page_id, code) not in accepted, f"{code} is not a gain: the old gate accepted it"
        response = ask(code, scope=page_scope(baseline, page_id))
        assert response.status is Status.OK, f"{code} is reported as a gain and is not findable"

    named = {code for code, _pages in baseline.gains_by_code()}
    assert {"EAO 84-5140.0020", "B&R X20SI4100"} <= named


def test_the_paths_parity_cannot_cover_are_published_beside_the_result(capsys):
    """R7, in the suite's own output: a green parity run is not sign-off for §7 or §8.

    U012's risk register requires this list to exist and to be visible. It is printed here rather
    than only asserted, because the failure mode is a reviewer reading 405 green rows as coverage.
    """
    with capsys.disabled():
        print(f"\nNO LEGACY COVERAGE — {len(legacy.NO_LEGACY_COVERAGE)} area(s) parity says "
              f"nothing about:")
        for line in legacy.NO_LEGACY_COVERAGE:
            print(f"  - {line}")

    assert legacy.NO_LEGACY_COVERAGE
