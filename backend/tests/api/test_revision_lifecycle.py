"""Two revisions in one index — F9, F12's revision half, and F8's `series_id` half (M8, U025).

§6.7's retirement has three clauses and the whole design is in the difference between the first
two: clause 1 **deletes** earlier runs of the same `(doc_id, revision)` so totals cannot double
(F12), and clause 2 **demotes and keeps** the previously current *other* revision, because those
points are what `found_only_in_superseded` reads from (F9). *"A blanket delete every point whose
`run_id` is not the current run would satisfy F12 by destroying F9's evidence."*

So the two rows are proved against each other here, on one pair of revisions, rather than in two
files that could each pass while the system did the wrong thing.

**What makes a revision *superseded* rather than merely unpublished.** In the pages collection
those two are the same fact — `is_current: False` — and §5.4's `INDEXED` has sixteen keys with no
seventeenth to spare. The discriminator is the control plane (D9): a revision is superseded when
a run **published** it and a later one replaced it. `lookup` reads `vsir_runs` for exactly that,
and only on the absence path. The last test in this file is the one that matters most: a run that
never published must never be reachable through the status, because I7's whole promise is that a
half-ingested document cannot answer.

Records are built here rather than ingested. The pipeline's own two-revision behaviour is
`test_resume.py`'s; this file is about what the index does with two revisions once they are in
it, and seeding is how `test_publish_and_retire.py` asks that question already.
"""
from __future__ import annotations

import pytest
from qdrant_client.http import models as qm

from conftest import EMBED_DIM as CONFTEST_DIM
from conftest import seed_with_vectors
from test_publish_and_retire import (COLLECTION, EMBED_DIM, FINGERPRINT, RUNS, build_records,
                                     open_run, payload_digest, vectors_for, windows_of)
from vsir.core.status import Status
from vsir.ingest import gates
from vsir.ingest import index as index_module
from vsir.ingest import run as run_module
from vsir.serve.envelope import Provenance
from vsir.serve.tools.lookup import lookup
from vsir.serve.tools.skim import skim_pages

DOC = "REV-DOC"
OTHER = "REV-OTHER"
OLD, NEW = "1.3", "1.4"
PAGES = 6

#: A code only revision 1.3 prints. 1.4 replaced that sheet, so the code is nowhere current —
#: and it is the one `found_only_in_superseded` exists to answer about.
WITHDRAWN_CODE = "K913"
#: A code both revisions print. Only the current one may answer for it (I7).
SHARED_CODE = "K102"

PROVENANCE = Provenance(release_id="test")


@pytest.fixture
def store(qdrant):
    """The two collections, empty before and after. Nothing here shares state with a neighbour."""
    for name in (COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    index_module.ensure_collection(qdrant, name=COLLECTION, dim=EMBED_DIM,
                                   fingerprint=FINGERPRINT, runs_collection=RUNS)
    yield qdrant
    for name in (COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)


def records_for(revision: str, run_id: str, *, doc_id: str = DOC, extra: str = "",
                pages: int = PAGES):
    """One revision's pages. ``extra`` is a code this revision prints and the other may not."""
    built = build_records(doc_id, revision, run_id, pages=pages)
    if not extra:
        return built
    first = built[0]
    return (first.model_copy(update={"text": f"{first.text} and {extra}"}), *built[1:])


def publish(client, records, *, page_count: int = PAGES):
    """Steps 10 and 11 for one revision: write is_current=False, gate, flip, retire."""
    index_module.upsert(client, COLLECTION, list(records), vectors_for(records),
                        fingerprint=FINGERPRINT, runs_collection=RUNS)
    record = open_run(client, records, page_count=page_count)
    report = gates.evaluate(records=list(records), page_count=page_count,
                            windows=windows_of(len(records)))
    return run_module.publish(client, runs_collection=RUNS, collection=COLLECTION,
                              record=record, report=report, records=list(records))


def both_revisions(client):
    """1.3 published, then 1.4 published over it. The state every test below starts from."""
    publish(client, records_for(OLD, "R-OLD", extra=WITHDRAWN_CODE))
    publish(client, records_for(NEW, "R-NEW"))


def ask(client, label, **kwargs):
    return lookup(client, COLLECTION, label, provenance=PROVENANCE, runs_collection=RUNS,
                  **kwargs)


def count(client, **scope) -> int:
    return index_module.count(client, COLLECTION, scope)


# ── F12's revision half: publishing 1.4 keeps every one of 1.3's points ─────────────────────────

def test_publishing_new_revision_keeps_prior_points(store):
    """AC + F12: 1.3's point count is **unchanged** after 1.4 publishes, and all of it is demoted.

    Clause 2 is a `set_payload`, not a delete. If it were a delete this test and
    `test_lookup_only_in_superseded_returns_typed_status` could not both pass, which is the
    point of proving them in one file.
    """
    publish(store, records_for(OLD, "R-OLD", extra=WITHDRAWN_CODE))
    before = count(store, doc_id=DOC, revision=OLD)
    assert before == PAGES == count(store, doc_id=DOC, revision=OLD, is_current=True)

    published = publish(store, records_for(NEW, "R-NEW"))

    assert count(store, doc_id=DOC, revision=OLD) == before
    assert count(store, doc_id=DOC, revision=OLD, is_current=True) == 0
    assert count(store, doc_id=DOC, revision=NEW, is_current=True) == PAGES
    assert count(store, doc_id=DOC) == PAGES * 2
    assert published.retired["superseded_demoted"] == PAGES
    assert published.retired["other_revision_points_kept"] == PAGES
    assert published.retired["deleted_stale_points"] == 0


def test_a_second_run_of_the_same_revision_deletes_the_first_runs_points(store):
    """F12's other half, re-exercised beside the revision one: totals do not double.

    Clause 1 is scoped to the **same** `(doc_id, revision)`, so re-ingesting 1.4 removes 1.4's
    earlier run and leaves 1.3 exactly where clause 2 put it. A blanket delete-by-`run_id` would
    pass this assertion and fail the next one.
    """
    both_revisions(store)

    again = publish(store, records_for(NEW, "R-NEW-2"))

    assert count(store, doc_id=DOC, revision=NEW) == PAGES
    assert count(store, doc_id=DOC, run_id="R-NEW") == 0
    assert count(store, doc_id=DOC, revision=OLD) == PAGES, "F9's evidence must survive F12"
    assert again.pages_indexed == PAGES


def test_retirement_never_touches_another_document(store):
    """Clause 3, by payload hash: another document's pages are byte-identical before and after."""
    publish(store, records_for(OLD, "R-OTHER", doc_id=OTHER))
    untouched = payload_digest(store, OTHER)

    both_revisions(store)

    assert payload_digest(store, OTHER) == untouched
    assert count(store, doc_id=OTHER, is_current=True) == PAGES


# ── F9: the status, and what it is allowed to say ───────────────────────────────────────────────

def test_lookup_only_in_superseded_returns_typed_status(store):
    """AC + F9: a label only 1.3 satisfies is `found_only_in_superseded`, with the revision named.

    Not `not_found`, which would send the agent to abstain about a page somebody is holding, and
    not a silent 1.3 hit, which would cite a superseded revision as current. §7.1: *"surface the
    revision and let the caller decide."*
    """
    both_revisions(store)

    response = ask(store, WITHDRAWN_CODE)

    assert response.status == Status.FOUND_ONLY_IN_SUPERSEDED
    assert response.hits == [], "a superseded page is not current and is never returned as one"
    assert [(row.doc_id, row.revision, row.pages) for row in response.superseded] == [
        (DOC, OLD, 1)]
    assert response.effective_scope["is_current"] is True


def test_a_label_the_current_revision_carries_answers_from_it_alone(store):
    """AC: a `lookup` satisfied by 1.4 returns only 1.4's pages — `is_current` is injected (I7)."""
    both_revisions(store)

    response = ask(store, SHARED_CODE)

    assert response.status == Status.OK
    assert {hit.page_id.split("#")[0] for hit in response.hits} == {f"{DOC}@{NEW}"}
    assert response.superseded == [], "the status is `ok`; there is nothing to surface"


def test_a_label_no_revision_carries_is_still_not_found(store):
    """The guard on the whole feature: F9 must not turn every absence into a revision story."""
    both_revisions(store)

    response = ask(store, "K777")

    assert response.status == Status.NOT_FOUND
    assert response.superseded == []


def test_an_unpublished_revision_is_never_surfaced_as_superseded(store):
    """I7, and the reason `lookup` reads the control plane at all.

    A run that wrote its points and never passed its gates leaves them `is_current: False` —
    indistinguishable in the pages collection from a revision that was published and replaced.
    Answering `found_only_in_superseded` about it would disclose a half-ingested revision through
    the one status that is supposed to be about the past, and it would do so while the document
    is mid-ingest, which is when an operator is least able to tell the report is wrong.
    """
    publish(store, records_for(OLD, "R-OLD"))
    # Step 10 for a 1.5 that never reaches step 11: the points exist, nothing published them.
    inflight = records_for("1.5", "R-INFLIGHT", extra=WITHDRAWN_CODE)
    index_module.upsert(store, COLLECTION, list(inflight), vectors_for(inflight),
                        fingerprint=FINGERPRINT, runs_collection=RUNS)
    open_run(store, inflight)

    response = ask(store, WITHDRAWN_CODE)

    assert count(store, doc_id=DOC, revision="1.5") == PAGES
    assert response.status == Status.NOT_FOUND
    assert response.superseded == []


def test_a_gated_run_is_not_superseded_either(store):
    """The same rule where the run got further: gated is a judgement, not a publication."""
    publish(store, records_for(OLD, "R-OLD"))
    held = records_for("1.5", "R-GATED", extra=WITHDRAWN_CODE)
    index_module.upsert(store, COLLECTION, list(held), vectors_for(held),
                        fingerprint=FINGERPRINT, runs_collection=RUNS)
    record = open_run(store, held)
    blocked = gates.evaluate(records=list(held), page_count=PAGES,
                             windows=windows_of(PAGES, offset_ok=False))
    with pytest.raises(run_module.GateBlocked):
        run_module.publish(store, runs_collection=RUNS, collection=COLLECTION, record=record,
                           report=blocked, records=list(held))

    assert run_module.require(store, RUNS, "R-GATED").state == run_module.GATED
    assert ask(store, WITHDRAWN_CODE).status == Status.NOT_FOUND


def test_a_scope_holding_only_superseded_pages_is_not_out_of_scope(store):
    """F9 on the aggregate rungs: the filters *did* match a document — a retired revision of one.

    `out_of_scope` means *"no document matched the filters"*, and saying it here would be wrong
    rather than merely less specific. The probe fires only where the scope selects no current
    page at all, which is the one case a fused ranking can be certain about.
    """
    both_revisions(store)

    response = lookup(store, COLLECTION, SHARED_CODE, scope={"revision": OLD},
                      provenance=PROVENANCE, runs_collection=RUNS)

    assert response.status == Status.FOUND_ONLY_IN_SUPERSEDED
    assert response.scope_stats.pages == 0
    assert [row.revision for row in response.superseded] == [OLD]


#: The aggregate rungs read a **dense vector**, so they cannot run against
#: `test_publish_and_retire`'s 8-dimensional collection. Their own, at the release's dimension.
SKIM_COLLECTION = f"vsir_pages_rev_{CONFTEST_DIM}"
SKIM_RUNS = "vsir_runs_rev"


@pytest.fixture
def skim_store(qdrant, stub_embedder):
    """Both revisions with all three surfaces, plus the two published run records F9 reads."""
    for name in (SKIM_COLLECTION, SKIM_RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    run_module.ensure_control_plane(qdrant, SKIM_RUNS)
    seeded = [
        *(record.model_copy(update={"is_current": False})
          for record in records_for(OLD, "R-OLD", extra=WITHDRAWN_CODE)),
        *(record.model_copy(update={"is_current": True})
          for record in records_for(NEW, "R-NEW")),
    ]
    seed_with_vectors(qdrant, SKIM_COLLECTION, seeded, dim=CONFTEST_DIM, embedder=stub_embedder)
    # The control plane says both revisions were published — which is the fact that makes 1.3
    # *superseded* rather than merely not current (see this module's docstring).
    for revision, run_id in ((OLD, "R-OLD"), (NEW, "R-NEW")):
        record = run_module.start(qdrant, SKIM_RUNS, run_id=run_id, doc_id=DOC,
                                  revision=revision, release_id="test-0",
                                  collection=SKIM_COLLECTION, page_count=PAGES, owner="suite")
        run_module.save(qdrant, SKIM_RUNS,
                        record.model_copy(update={"state": run_module.PUBLISHED}))
    yield qdrant
    for name in (SKIM_COLLECTION, SKIM_RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)


def test_skim_pages_says_the_same_thing_about_the_same_scope(skim_store, stub_embedder):
    """The rungs share `absence`, so the vocabulary cannot drift between them (§7.1)."""
    response = skim_pages(skim_store, SKIM_COLLECTION, query="operation",
                          scope={"revision": OLD}, embedder=stub_embedder,
                          provenance=PROVENANCE, runs_collection=SKIM_RUNS)

    assert response.status == Status.FOUND_ONLY_IN_SUPERSEDED
    assert response.hits == []
    assert [row.revision for row in response.superseded] == [OLD]


def test_skim_pages_over_the_current_revision_is_untouched_by_the_probe(skim_store,
                                                                       stub_embedder):
    """The guard: the probe costs nothing and says nothing where the scope has current pages."""
    response = skim_pages(skim_store, SKIM_COLLECTION, query="operation",
                          scope={"revision": NEW}, embedder=stub_embedder,
                          provenance=PROVENANCE, runs_collection=SKIM_RUNS)

    assert response.status == Status.OK
    assert response.superseded == []
    assert {hit.page_id.split("#")[0] for hit in response.hits} == {f"{DOC}@{NEW}"}


def test_without_a_control_plane_the_answer_is_honestly_not_found(store):
    """A caller with no `vsir_runs` in hand cannot be told which revisions were published.

    So it is told what the *current corpus* says, which is what every tool said before U025 —
    not a guess dressed as a status. The served app always passes the control plane; this is the
    contract for the one that cannot.
    """
    both_revisions(store)

    response = lookup(store, COLLECTION, WITHDRAWN_CODE, provenance=PROVENANCE)

    assert response.status == Status.NOT_FOUND
    assert response.superseded == []


# ── F8's series_id half, in an index ────────────────────────────────────────────────────────────

def test_series_id_stable_across_revisions_in_the_index(store):
    """AC: a `series_id` scope returns pages from **both** revisions; a `section_id` scope does not.

    This is what F8 costs if it is missing. An agent that scoped to `TC1E-SF@1.3#s001` yesterday
    and runs the same scope today gets nothing back and concludes the chapter is empty; the
    `series_id` scope is the one that still means what it meant.
    """
    both_revisions(store)
    series = f"{DOC}#s:operation"

    # Scoped to the series, across the publish flip: both revisions' pages are there.
    assert count(store, doc_id=DOC, series_id=series) == PAGES * 2
    assert count(store, doc_id=DOC, series_id=series, is_current=True) == PAGES

    # Scoped to the old revision's `section_id`, nothing current answers — the id went stale
    # with the revision, which is exactly why `series_id` exists.
    assert count(store, section_id=f"{DOC}@{OLD}#s001", is_current=True) == 0
    assert count(store, section_id=f"{DOC}@{NEW}#s001", is_current=True) == PAGES


def test_a_series_id_scope_through_the_tool_is_the_current_revisions_pages(store):
    """And the tool injects `is_current` over it, so the stable scope still answers about today."""
    both_revisions(store)

    response = ask(store, SHARED_CODE, scope={"series_id": f"{DOC}#s:operation"})

    assert response.status == Status.OK
    assert {hit.page_id.split("#")[0] for hit in response.hits} == {f"{DOC}@{NEW}"}
    assert response.scope_stats.pages == PAGES


def test_the_series_id_index_is_a_keyword_array_and_matches_any_element(store):
    """§5.3: a straddling page is in scope for either section, on both revisions."""
    both_revisions(store)
    stored, _ = store.scroll(collection_name=COLLECTION, limit=1, with_payload=True,
                             scroll_filter=qm.Filter(must=[qm.FieldCondition(
                                 key="series_id",
                                 match=qm.MatchValue(value=f"{DOC}#s:operation"))]))

    assert isinstance((stored[0].payload or {})["series_id"], list)
