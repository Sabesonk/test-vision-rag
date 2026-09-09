"""L3 — the adversarial abstention eval (Spec §12.4). **A failure here is P0.**

§12.4 states the stakes plainly: *"If one assertion here ever fails, the system has produced the
injury the whole design exists to prevent."* One hundred codes, each one character from a code the
corpus really prints, put through the exact surface and the check that confirms it. None of them
may return a page, and none of them may be handed back as what is there instead.

It runs against **whatever corpus is indexed** — the synthetic seed here, the real fixture from
M2b — so it needs no list that does not exist yet (OQ-4, resolved by design) and it runs in CI
from M1 onward rather than from M2b.

**One deviation from §12.4's sketch, and it is a shape not a substance.** The snippet reads
`for n in r.present_instead.values()` off a `lookup` response; Family A has no `present_instead`
field (§7.1) — the disclosure belongs to a per-claim check (§7.2.4). So the same assertion is made
where the field actually lives: every fake is also run through `verify_claims`, and no verdict may
name it in `present_instead`. That is strictly stronger than the sketch, because it exercises the
code path that could actually leak a near miss.
"""
from __future__ import annotations

from typing import Any

import pytest
from qdrant_client import QdrantClient

from vsir.core.nearmiss import near_misses
from vsir.core.observed_tokens import from_records, is_searchable
from vsir.core.present_instead import present_instead
from vsir.core.verify import PRESENT, verify_claims
from vsir.eval import synthetic
from vsir.serve.envelope import Provenance, Status
from vsir.serve.tools.lookup import lookup

EMBED_DIM = 1536
PROVENANCE = Provenance(run_id=synthetic.SEED_RUN_ID, release_id="test")
SAMPLE = 100

#: The two absences a fabricated code may legitimately produce. `ok` is the failure this eval
#: exists to catch; `out_of_scope` would mean the corpus was never seeded.
HONEST_ABSENCES = (Status.NOT_FOUND, Status.NOT_SEARCHABLE)


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def seeded(qdrant: QdrantClient, corpus: synthetic.Corpus) -> str:
    collection = synthetic.synthetic_collection("vsir_pages_abstention", EMBED_DIM)
    synthetic.seed(qdrant, collection, corpus.records(release_id="test"), dim=EMBED_DIM)
    try:
        yield collection
    finally:
        synthetic.drop(qdrant, collection)


@pytest.fixture(scope="module")
def searchable_payloads(qdrant: QdrantClient, seeded: str) -> list[dict]:
    """What was **indexed** and is searchable — the source §6.8 and §5.7 between them specify.

    Read back out of Qdrant rather than off the records: if the payload and the record could
    disagree, the eval would be mutating codes the index does not contain and passing for the
    wrong reason. `is_searchable` then drops the pages `lookup` cannot search and `verify` cannot
    check, because a code observed only there is not one this eval can reason about.
    """
    return [point.payload for point in
            qdrant.scroll(collection_name=seeded, limit=1000, with_payload=True,
                          with_vectors=False)[0]
            if point.payload and point.payload.get("is_current")
            and is_searchable(point.payload)]


@pytest.fixture(scope="module")
def inventory(searchable_payloads: list[dict], corpus: synthetic.Corpus):
    return from_records(searchable_payloads)[corpus.doc_id]


@pytest.fixture(scope="module")
def fakes(inventory, searchable_payloads: list[dict]) -> tuple[Any, ...]:
    """The sample, and the reason ``texts`` is handed in.

    Without it a fake is only *"not a known token"*, and a mutation can land on a **phrase** the
    corpus prints: ``sf5`` mutates to ``sf1``, whose boundary-spaced variant ``sf 1`` really is
    printed inside ``SF 1.1A``. `lookup` returns that page and is right to — the phrase is there —
    so asserting on such a candidate would test the corpus rather than the system. That behaviour
    is asserted deliberately in `test_acceptance_synthetic.py` instead.
    """
    sample = near_misses(inventory, n=SAMPLE,
                         texts=[payload["text"] for payload in searchable_payloads])
    assert len(sample) == SAMPLE, "the corpus must be able to supply the whole sample"
    return sample


# ── the eval ────────────────────────────────────────────────────────────────────────────────────

def test_near_miss_codes_never_answer(qdrant, seeded, fakes):
    """One hundred fabricated codes, and not one of them returns a page.

    Reported in one assertion rather than a hundred parametrised ones on purpose: the number that
    matters is `abstention_correctness`, and §12.6/D11 fix it at **1.00** — a single leak is a stop,
    so the failure message has to name every leak, not the first.
    """
    leaked: list[str] = []
    for miss in fakes:
        response = lookup(qdrant, seeded, miss.fake, provenance=PROVENANCE)
        if response.hits or response.status not in HONEST_ABSENCES:
            leaked.append(f"{miss.source} → {miss.fake}: {response.status.value} "
                          f"{[hit.page_id for hit in response.hits]}")

    assert not leaked, f"{len(leaked)} of {len(fakes)} fabricated codes answered: {leaked}"


def test_a_near_miss_is_never_verified_as_present(qdrant, seeded, corpus, fakes):
    """The other half of the surface: `verify` must not confirm one either (F2, F16).

    Checked against the two pages that carry the most real codes, in one call, so the assertion is
    about the fold as well as the filter.
    """
    pages = [corpus.page_id(1), corpus.page_id(6)]

    result = verify_claims(qdrant, seeded, [miss.fake for miss in fakes], pages)

    confirmed = [claim for claim, verdict in result.claims.items() if verdict.status == PRESENT]
    assert not confirmed, f"verify confirmed a fabricated code: {confirmed}"


def test_no_fabricated_code_is_ever_returned_as_what_is_there_instead(qdrant, seeded, corpus,
                                                                      fakes, inventory):
    """§12.4's `assert n != fake` — F16, at the one place a code the caller did not ask for
    appears.

    Both readings are asserted: the disclosure a `verify` actually returns, and the raw prefix
    lookup over the document-wide inventory. Neither may contain the claim itself.
    """
    pages = [corpus.page_id(1), corpus.page_id(6)]
    result = verify_claims(qdrant, seeded, [miss.fake for miss in fakes], pages)

    for miss in fakes:
        verdict = result.claims[miss.fake]
        assert miss.fake not in verdict.present_instead
        assert miss.fake not in present_instead(miss.fake, inventory)
        assert len(verdict.present_instead) <= 5


def test_the_real_codes_the_fakes_came_from_are_all_findable(qdrant, seeded, fakes):
    """The control. Without it, a corpus that answered nothing at all would pass this file.

    An eval that only asserts absences is green on a broken index, which is the failure mode a
    safety test cannot afford. Every source is on a searchable page — that is what
    `searchable_payloads` guarantees — so every one of them must come back.
    """
    unfindable: list[str] = []
    for source in sorted({miss.source for miss in fakes}):
        response = lookup(qdrant, seeded, source, provenance=PROVENANCE)
        if not response.hits:
            unfindable.append(f"{source}: {response.status.value}")

    assert not unfindable, f"real codes that stopped being findable: {unfindable}"


def test_abstention_correctness_is_one(qdrant, seeded, corpus, fakes):
    """D11's gate, computed rather than asserted piecemeal: 100 of 100, or it is a stop.

    `code_precision = 1.00` and `abstention_correctness = 1.00` are the two numbers §12.6 refuses
    to negotiate, and this is the M1-available half of them.
    """
    pages = [corpus.page_id(1), corpus.page_id(6), corpus.page_id(8)]
    result = verify_claims(qdrant, seeded, [miss.fake for miss in fakes], pages)

    abstained = sum(
        1 for miss in fakes
        if not lookup(qdrant, seeded, miss.fake, provenance=PROVENANCE).hits
        and result.claims[miss.fake].status != PRESENT
    )

    assert abstained / len(fakes) == 1.00
