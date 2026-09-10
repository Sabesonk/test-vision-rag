"""L2 — §12.3's negative row: *every raw in `withheld.jsonl` is NOT findable in* ``text`` (I2, F14).

This is the parity suite's other half and the more important one. `impl`'s own run emitted 96 codes
that its text layer did not back — real model output about real pages, on a real corpus — and the
one rule this whole system is built on says they must be unreachable through the exact surface:
*"`ingest/probe.py` is the only writer of the `text` payload field. Model output never reaches a
lexical index except through `vlm_codes`, which is opt-in and permanently `verified: false`"*
(§1.2, I2).

`impl` enforced that with a curated allowlist and a gate, and wrote the refusals to a file. Here
there is nothing to enforce: a code is findable because the page's text prints it, so an unbacked
code is not *withheld*, it is **unfindable**. This suite is what turns that sentence into 96
assertions against a live index.

Two scopes, and the difference is deliberate. The `not findable` half is asked at **page** scope,
because a code withheld from one page is often legitimately printed on another — ``Q16`` is a real
tag somewhere in this corpus, and asserting it is nowhere would be asserting something false. The
`include_unverified` half is asked at document scope, because §6.5's reattribution can move a
sighting one page (F6), and where it does, that move is disclosed rather than hidden.
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
    collection = legacy.legacy_collection("vsir_pages_withheld", EMBED_DIM)
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


def split(page_id: str) -> tuple[str, str, int]:
    doc_id, rest = page_id.split("@", 1)
    revision, page_no = rest.split("#p", 1)
    return doc_id, revision, int(page_no)


WITHHELD = legacy.load().withheld()


# ── the negative row ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("page_id,raw", [
    pytest.param(page_id, raw, id=f"{page_id}:{raw}") for page_id, raw in WITHHELD
])
def test_a_withheld_code_is_not_findable_in_the_text_of_the_page_it_came_from(page_id, raw, ask):
    """AC: ``hits == []`` for every raw in `withheld.jsonl` — one PASS row each.

    Scoped to the page it was withheld from, which is the edge case U012's test plan names: a
    withheld raw is often a legitimate token elsewhere in the corpus, and a corpus-wide assertion
    would be asserting that the *other* page does not print something it does print.
    """
    doc_id, revision, page_no = split(page_id)

    response = ask(raw, scope={"doc_id": doc_id, "revision": revision, "page_no": page_no})

    assert response.hits == []
    assert response.total == 0
    assert response.status in (Status.NOT_FOUND, Status.NOT_SEARCHABLE)


@pytest.mark.parametrize("page_id,raw", [
    pytest.param(page_id, raw, id=f"{page_id}:{raw}") for page_id, raw in WITHHELD
])
def test_the_unverified_surface_opens_only_when_the_caller_opts_in(page_id, raw, ask):
    """AC: a non-empty ``unverified_hits`` **only** with ``include_unverified=True`` (D3).

    The model did say it, so the sighting is not thrown away — it is on ``vlm_codes``, the opt-in
    surface, and every hit from there is permanently ``verified: false``. That is the whole of D3:
    on a page with no text layer it is the only recall there is, and it is never evidence. Without
    the flag the field comes back empty for all 96, whatever else the query found.

    Document scope rather than page scope, because §6.5 may have moved the sighting one page to the
    sheet that actually prints it (F6) — see the test below, which names both codes that moved.
    """
    doc_id, revision, _page_no = split(page_id)
    scope = {"doc_id": doc_id, "revision": revision}

    verified_only = ask(raw, scope=scope)
    with_unverified = ask(raw, scope=scope, include_unverified=True)

    assert verified_only.unverified_hits == []
    assert with_unverified.unverified_hits, f"{raw} reaches neither surface"
    assert all(hit.verified is False for hit in with_unverified.unverified_hits)
    assert with_unverified.hits == verified_only.hits


def test_opting_in_never_changes_the_verified_surface(ask, baseline):
    """The two lists are never merged, and ``total`` counts the verified surface alone (§7.1).

    Asserted as an *equality against the same query without the flag* rather than as
    ``hits == []``, because emptiness is not the property and on this corpus it is not even true:
    §6.5 moved two of the 96 onto the neighbouring page, which does print them, so a
    document-scoped `lookup` for those two legitimately returns a verified hit. What must hold for
    all 96 is that opting in adds a second list and touches nothing else — if `include_unverified`
    ever changed ``hits`` or ``total``, an agent's *"the page says so"* would start to mean *"the
    model said so"*, which is the injury the whole design exists to prevent.
    """
    for page_id, raw in baseline.withheld():
        doc_id, revision, page_no = split(page_id)
        scope = {"doc_id": doc_id, "revision": revision}

        opted_in = ask(raw, scope=scope, include_unverified=True)
        verified_only = ask(raw, scope=scope)

        assert opted_in.hits == verified_only.hits
        assert opted_in.total == verified_only.total
        assert opted_in.status is verified_only.status
        # …and on the page it was withheld from, there is nothing to cite either way.
        on_its_page = ask(raw, scope={**scope, "page_no": page_no}, include_unverified=True)
        assert on_its_page.hits == []
        assert on_its_page.total == 0


def test_a_reattributed_withheld_code_becomes_verified_on_the_page_that_prints_it(ask, baseline):
    """F6 where it meets the negative set — and the clearest gain in the corpus.

    ``F302`` and ``F313`` were withheld from `TC1E-PERIODIC` page 5: that sheet's text layer did
    not back them, so the old run recorded them as unbacked model output and stopped. Page 4's text
    prints both. §6.5 moves the sighting to the page whose text carries it and records
    ``moved_from`` naming page 5, so the same two codes that were evidence for nothing are now
    ``verified: true`` on the right sheet — found through ``text``, which only the probe writes, so
    the trust is structural and not a decision anybody made.

    `impl` had no such repair. The code stayed on page 5, unbacked, and a citation would have named
    the sheet next to the one that prints it — F6, exactly.
    """
    moved = {"F302", "F313"}
    records = {record.page_id: record for record in baseline.records("TC1E-PERIODIC")}
    receiving = records["TC1E-PERIODIC@1.1#p004"].content

    assert {code.code for code in receiving.moved_from} == moved
    assert {code.from_page_id for code in receiving.moved_from} == {"TC1E-PERIODIC@1.1#p005"}

    for raw in moved:
        on_page_five = ask(raw, scope={"doc_id": "TC1E-PERIODIC", "page_no": 5},
                           include_unverified=True)
        on_page_four = ask(raw, scope={"doc_id": "TC1E-PERIODIC", "page_no": 4})

        assert on_page_five.hits == []
        assert on_page_five.unverified_hits == []
        assert on_page_four.status is Status.OK
        assert [hit.page_no for hit in on_page_four.hits] == [4]
        assert all(hit.verified for hit in on_page_four.hits)


def test_the_negative_set_is_the_size_the_export_recorded(baseline):
    """96 codes, every one of them `source: "vlm"` — the denominator, stated (§12.1)."""
    assert len(WITHHELD) == 96
    assert {row["source"] for row in baseline.withheld_rows} == {"vlm"}
