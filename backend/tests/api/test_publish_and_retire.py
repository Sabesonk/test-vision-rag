"""L2 — the publish flip and the three-clause retirement, against a real ``qdrant/qdrant:v1.19.0``.

Spec §6.7, §11.1 · invariants **I1**, **I4**, **I7** · failure rows **F4**, **F7**, **F12**.

Everything here needs a live store, because everything here is about what a *filter* does. Whether
`is_current=False` really makes a point unreachable, whether a filtered delete scoped to one
`(doc_id, revision)` leaves another revision's points untouched, and whether a filtered
`set_payload` is idempotent are all properties of Qdrant. A fake would only restate our belief
about them, and the belief is precisely what F12 and F9 disagree about:

    A blanket "delete every point whose `run_id` is not the current run" satisfies F12 by
    destroying F9's evidence.

So clause 2 and clause 3 each get their own test, and clause 3's is a payload-hash comparison of an
untouched second document taken **before and after** the publish (SA-10).

The collections are this module's own, created and dropped around the suite, so nothing it writes
is visible to another L2 suite.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Sequence

import pytest
from qdrant_client.http import models as qm

from vsir.core.ids import page_id as make_page_id
from vsir.core.ids import point_id
from vsir.core.record import PageContent, PageRecord, Provenance, StoredSection, Summary
from vsir.ingest import export as export_module
from vsir.ingest import gates, index as index_module
from vsir.ingest import run as run_module
from vsir.ingest.fingerprint import Fingerprint

EMBED_DIM = 8
COLLECTION = f"vsir_pages_publish_{EMBED_DIM}"
RUNS = "vsir_runs_publish"
PAGES = 12

FINGERPRINT = Fingerprint(embed_model="gemini-embedding-2", dim=EMBED_DIM)


def build_records(doc_id: str, revision: str, run_id: str, *, pages: int = PAGES,
                  rate: float | None = 1.0, labels: Sequence[str] | None = None,
                  doc_type: str = "manual") -> tuple[PageRecord, ...]:
    """``pages`` finished records for one ``(doc_id, revision, run_id)``.

    Built here rather than driven through the whole pipeline because this suite is about step 11
    alone: what varies between its cases is the health of a document and the ids on its points,
    and running extraction to produce those would test the fixture instead of the gates.
    """
    printed = list(labels) if labels is not None else [str(number)
                                                       for number in range(1, pages + 1)]
    return tuple(
        PageRecord(
            doc_id=doc_id, revision=revision, run_id=run_id, page_no=number, doc_type=doc_type,
            has_text=rate is not None, text_trust="ok" if rate is not None else "no_text",
            text=f"page {number} of {doc_id} carries K{100 + number} and SF 1.{number}A",
            section_id=[f"{doc_id}@{revision}#s001"], series_id=[f"{doc_id}#s:operation"],
            content=PageContent(
                printed_page_no=printed[number - 1], label_verified=rate is not None,
                grounded_rate=rate, topics=["operation"],
                codes_in_text=[f"k{100 + number}"] if rate is not None else [],
                summaries=[Summary(lang="en", text=f"page {number}")],
                sections=[StoredSection(section_id=f"{doc_id}@{revision}#s001", title="Operation",
                                        series_id=f"{doc_id}#s:operation", page_range=(1, pages))],
            ),
            provenance=Provenance(page_id=make_page_id(doc_id, revision, number), run_id=run_id,
                                  release_id="test-0", vlm_model="gemini-3.8-flash-001",
                                  prompt_version="s2-v1", dpi=220),
        )
        for number in range(1, pages + 1)
    )


def vectors_for(records: Sequence[PageRecord]) -> dict[str, list[float]]:
    return {record.page_id: [float((record.page_no + position) % 5) / 5.0 or 0.1
                             for position in range(EMBED_DIM)]
            for record in records}


def windows_of(pages: int = PAGES, *, offset_ok: bool = True) -> list[gates.WindowOutcome]:
    return [gates.WindowOutcome(start=1, end=pages, pages_returned=pages, offset_ok=offset_ok,
                                check="" if offset_ok else "independent_observation")]


def write(client: Any, records: Sequence[PageRecord]) -> None:
    """Step 10 — every point ``is_current=False``, which is the state step 11 acts on (I7)."""
    index_module.upsert(client, COLLECTION, list(records), vectors_for(records),
                        fingerprint=FINGERPRINT, runs_collection=RUNS)


def open_run(client: Any, records: Sequence[PageRecord], *, page_count: int = PAGES) -> Any:
    record = records[0]
    return run_module.start(client, RUNS, run_id=record.run_id, doc_id=record.doc_id,
                            revision=record.revision, release_id="test-0", collection=COLLECTION,
                            page_count=page_count, windows_total=1, owner="suite")


def publish(client: Any, records: Sequence[PageRecord], *,
            windows: list[gates.WindowOutcome] | None = None, overrides: tuple[str, ...] = (),
            reason: str = "", page_count: int = PAGES) -> Any:
    """Steps 10 and 11 for one document: write, evaluate, publish."""
    write(client, records)
    record = open_run(client, records, page_count=page_count)
    for gate in overrides:
        record = run_module.override(record, gate=gate, reason=reason, by="suite")
    report = gates.evaluate(records=list(records), page_count=page_count,
                            windows=windows if windows is not None else windows_of(len(records)))
    return run_module.publish(client, runs_collection=RUNS, collection=COLLECTION, record=record,
                              report=report, records=list(records), by="suite")


def queryable(client: Any, doc_id: str, revision: str | None = None) -> int:
    """What a tool would see: every tool injects ``is_current=True`` server-side (I7, §6.7)."""
    scope: dict[str, Any] = {"doc_id": doc_id, "is_current": True}
    if revision is not None:
        scope["revision"] = revision
    return index_module.count(client, COLLECTION, scope)


def payload_digest(client: Any, doc_id: str) -> str:
    """A hash over every payload of a document, order-independent. Clause 3's evidence."""
    found, offset = [], None
    while True:
        page, offset = client.scroll(COLLECTION, scroll_filter=qm.Filter(must=[
            qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]),
            limit=128, offset=offset, with_payload=True, with_vectors=False)
        found.extend(json.dumps(point.payload, sort_keys=True) for point in page)
        if offset is None:
            break
    return hashlib.sha256("\n".join(sorted(found)).encode("utf-8")).hexdigest()


@pytest.fixture
def store(qdrant):
    """A clean pair of collections per test: publish is stateful and every case owns its state."""
    for name in (COLLECTION, RUNS):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    index_module.ensure_collection(qdrant, name=COLLECTION, dim=EMBED_DIM,
                                   fingerprint=FINGERPRINT, runs_collection=RUNS)
    try:
        yield qdrant
    finally:
        for name in (COLLECTION, RUNS):
            if qdrant.collection_exists(name):
                qdrant.delete_collection(name)


# ── I7 — nothing is queryable until the gates pass ───────────────────────────────────────────────

def test_unpublished_run_zero_queryable_pages(store):
    """AC + I7 + F17: before the gates pass, a query for a page of that run returns **zero** —
    and the points exist, `is_current=False`. A crash at window 700 of 1,440 must look like this,
    or `searchable_ratio` lies and the loop abstains about a page that is in the document."""
    records = build_records("DOC-A", "1.0", "R1")
    write(store, records)

    assert index_module.count(store, COLLECTION, {"doc_id": "DOC-A"}) == PAGES
    assert queryable(store, "DOC-A") == 0


def test_publish_page_count_and_unique_point_id(store):
    """AC + I1: after publish, `count(doc, rev, is_current=True) == pdf.page_count`, and every
    `page_id` is unique — so `point_id = uuid5(page_id)` means a re-ingest overwrites."""
    records = build_records("DOC-A", "1.0", "R1")

    published = publish(store, records)

    assert published.state == run_module.PUBLISHED and published.published_at
    assert queryable(store, "DOC-A", "1.0") == PAGES == published.pages_indexed
    assert len({record.page_id for record in records}) == PAGES
    assert len({point_id(record.page_id) for record in records}) == PAGES


def test_the_publish_flip_is_idempotent(store):
    """§6.7 — the flip is a filter with a constant value, so running it again changes nothing.
    That is what lets it be retried after a `set_payload` that timed out mid-write."""
    records = build_records("DOC-A", "1.0", "R1")
    publish(store, records)

    again = run_module.flip_current(store, COLLECTION, doc_id="DOC-A", revision="1.0",
                                    run_id="R1")

    assert again == PAGES == queryable(store, "DOC-A", "1.0")


def test_a_failed_set_payload_is_retried_and_published_at_follows_it(store):
    """§6.7 — *"the filtered `set_payload` is idempotent and retried; `published_at` is recorded
    only after it returns"*. A publish time in front of a half-applied flip is F17 with a
    timestamp on it."""
    records = build_records("DOC-A", "1.0", "R1")
    write(store, records)
    record = open_run(store, records)
    report = gates.evaluate(records=list(records), page_count=PAGES, windows=windows_of())

    class Flaky:
        """The store, with the first two publish flips failing. Everything else is the real one."""

        def __init__(self, real: Any) -> None:
            self.real, self.failures = real, 0

        def __getattr__(self, name: str) -> Any:
            return getattr(self.real, name)

        def set_payload(self, *args: Any, **kwargs: Any) -> Any:
            if kwargs.get("payload") == {"is_current": True} and self.failures < 2:
                self.failures += 1
                raise ConnectionError("qdrant went away mid-flip")
            return self.real.set_payload(*args, **kwargs)

    flaky = Flaky(store)
    published = run_module.publish(flaky, runs_collection=RUNS, collection=COLLECTION,
                                   record=record, report=report, records=list(records))

    assert flaky.failures == 2
    assert published.published_at and queryable(store, "DOC-A", "1.0") == PAGES


def test_a_flip_that_never_succeeds_leaves_the_run_unpublished(store):
    """The other side of the retry: three failures is an outage, and an outage must not produce a
    published run record. Nothing partial, and nothing claimed (§11.3)."""
    records = build_records("DOC-A", "1.0", "R1")
    write(store, records)
    record = open_run(store, records)
    report = gates.evaluate(records=list(records), page_count=PAGES, windows=windows_of())

    class Dead:
        def __init__(self, real: Any) -> None:
            self.real = real

        def __getattr__(self, name: str) -> Any:
            return getattr(self.real, name)

        def set_payload(self, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("qdrant is down")

    with pytest.raises(run_module.StoreUnavailable):
        run_module.publish(Dead(store), runs_collection=RUNS, collection=COLLECTION,
                           record=record, report=report, records=list(records))

    assert queryable(store, "DOC-A", "1.0") == 0
    assert run_module.require(store, RUNS, "R1").published_at is None


# ── the gates decide, and a blocked gate publishes nothing (§11.1) ───────────────────────────────

def test_offset_check_catches_shifted_pages(store):
    """AC + I4 + F7: a window failing either §6.4 check **blocks** the publish, the run record
    names the failing window, and zero pages are queryable."""
    records = build_records("DOC-A", "1.0", "R1")
    write(store, records)
    record = open_run(store, records)
    report = gates.evaluate(records=list(records), page_count=PAGES,
                            windows=windows_of(offset_ok=False))

    with pytest.raises(run_module.GateBlocked) as blocked:
        run_module.publish(store, runs_collection=RUNS, collection=COLLECTION, record=record,
                           report=report, records=list(records))

    assert blocked.value.details["blocked_by"] == [gates.OFFSET_CHECK]
    assert queryable(store, "DOC-A") == 0
    held = run_module.require(store, RUNS, "R1")
    assert held.state == run_module.GATED
    assert held.gate_results[gates.OFFSET_CHECK]["evidence"][0]["window"] == [1, PAGES]


def test_a_missing_page_blocks_the_publish_and_leaves_nothing_queryable(store):
    """AC: `window_coverage < 1.0` after retries **blocks** publish; the run record shows the gate
    name and zero pages are queryable. Half a manual in the index makes every later coverage
    measurement report the pipeline's own incompleteness as a property of the corpus."""
    records = build_records("DOC-A", "1.0", "R1")[:-2]
    write(store, records)
    record = open_run(store, records)
    report = gates.evaluate(records=list(records), page_count=PAGES, windows=windows_of())

    with pytest.raises(run_module.GateBlocked) as blocked:
        run_module.publish(store, runs_collection=RUNS, collection=COLLECTION, record=record,
                           report=report, records=list(records))

    assert blocked.value.details["blocked_by"] == [gates.WINDOW_COVERAGE]
    assert queryable(store, "DOC-A") == 0
    held = run_module.require(store, RUNS, "R1")
    assert held.state == run_module.GATED
    assert held.gate_results[gates.WINDOW_COVERAGE]["pass"] is False
    assert held.gate_results[gates.WINDOW_COVERAGE]["metric"] == pytest.approx(10 / 12)


def test_a_blocked_gate_cannot_be_overridden_unless_11_1_offers_one(store):
    """`window_coverage` and `offset_check` are not judgements about a threshold, so no reason an
    operator types releases them (§11.1)."""
    with pytest.raises(gates.OverrideRefused):
        gates.check_override(gates.OFFSET_CHECK, "the labels are fine, I checked by hand")


def test_grounded_rate_blocks_then_publishes_with_an_override_flagging_every_page(store):
    """AC: the median below the threshold blocks and lists the worst pages; `--override
    grounded_rate --reason "…"` then publishes with the reason in the run record and
    `published_with_override` on **every** page."""
    records = build_records("DOC-A", "1.0", "R1", rate=0.25)
    write(store, records)
    record = open_run(store, records)
    report = gates.evaluate(records=list(records), page_count=PAGES, windows=windows_of())

    with pytest.raises(run_module.GateBlocked):
        run_module.publish(store, runs_collection=RUNS, collection=COLLECTION, record=record,
                           report=report, records=list(records))
    assert queryable(store, "DOC-A") == 0
    held = run_module.require(store, RUNS, "R1")
    assert len(held.gate_results[gates.GROUNDED_RATE]["evidence"]) == min(PAGES, gates.WORST_PAGES)

    released = run_module.override(held, gate=gates.GROUNDED_RATE,
                                   reason="M2b baseline: 0.25 is this scanner's normal",
                                   by="operator")
    published = run_module.publish(store, runs_collection=RUNS, collection=COLLECTION,
                                   record=released, report=report, records=list(records))

    assert published.state == run_module.PUBLISHED
    assert queryable(store, "DOC-A", "1.0") == PAGES
    assert [(o.gate, o.by) for o in published.overrides] == [(gates.GROUNDED_RATE, "operator")]
    assert "0.25 is this scanner's normal" in published.overrides[0].reason

    stored = run_module.run_records(store, COLLECTION, doc_id="DOC-A", revision="1.0",
                                    run_id="R1")
    assert len(stored) == PAGES
    assert all(gates.FLAG_PUBLISHED_WITH_OVERRIDE in page.content.flags for page in stored)


def test_an_override_keeps_the_flags_derivation_put_on_a_page(store):
    """The stamp is additive. A single filtered write of one constant list would erase
    `ungrounded_codes`, `label_ambiguous` and every other per-page disclosure (§6.5)."""
    records = list(build_records("DOC-A", "1.0", "R1", rate=0.25))
    records[3] = records[3].model_copy(update={
        "content": records[3].content.model_copy(update={"flags": ["ungrounded_codes"]})})

    published = publish(store, records, overrides=(gates.GROUNDED_RATE,), reason="baseline")

    stored = {page.page_no: page.content.flags for page in run_module.run_records(
        store, COLLECTION, doc_id="DOC-A", revision="1.0", run_id="R1")}

    assert published.state == run_module.PUBLISHED
    assert stored[4] == ["ungrounded_codes", gates.FLAG_PUBLISHED_WITH_OVERRIDE]
    assert stored[5] == [gates.FLAG_PUBLISHED_WITH_OVERRIDE]


def test_fully_scanned_document_publishes(store):
    """AC + F4 + D3: `text_coverage == 0.0` publishes with `mostly_scanned` and **without the
    `grounded_rate` gate being evaluated at all**. Quarantining it is how an agent is told
    *"that part doesn't exist"* about a page that is in the manual."""
    records = build_records("SCANNED", "1.0", "R1", rate=None, labels=[""] * PAGES)

    published = publish(store, records)

    assert published.state == run_module.PUBLISHED
    assert queryable(store, "SCANNED", "1.0") == PAGES
    assert published.gate_results[gates.GROUNDED_RATE]["skipped"] is True
    assert published.gate_results[gates.GROUNDED_RATE]["metric"] is None
    assert published.flags == [gates.FLAG_MOSTLY_SCANNED]
    assert all(page.text_trust == "no_text" for page in run_module.run_records(
        store, COLLECTION, doc_id="SCANNED", revision="1.0", run_id="R1"))


def test_a_label_conflict_flags_the_run_and_publishes_it_anyway(store):
    """AC: a non-monotonic printed-label sequence publishes with `label_conflict`."""
    labels = [str(number) for number in range(1, PAGES + 1)]
    labels[7] = "2"

    published = publish(store, build_records("DOC-A", "1.0", "R1", labels=labels))

    assert published.state == run_module.PUBLISHED
    assert published.flags == [gates.FLAG_LABEL_CONFLICT]
    assert queryable(store, "DOC-A", "1.0") == PAGES


# ── retirement, all three clauses (§6.7 — F12 vs F9) ─────────────────────────────────────────────

def test_reingest_twice_same_point_count(store):
    """AC + F12: re-ingesting the same `(doc_id, revision)` twice yields the same point count, and
    the earlier run's points are deleted by filter."""
    publish(store, build_records("DOC-A", "1.0", "R1"))
    first = index_module.count(store, COLLECTION, {"doc_id": "DOC-A", "revision": "1.0"})

    second = publish(store, build_records("DOC-A", "1.0", "R2"))

    assert first == PAGES
    assert index_module.count(store, COLLECTION, {"doc_id": "DOC-A", "revision": "1.0"}) == PAGES
    assert queryable(store, "DOC-A", "1.0") == PAGES
    assert index_module.count(store, COLLECTION, {"run_id": "R1"}) == 0
    assert second.retired["deleted_stale_points"] == 0  # point_id is idempotent: R2 overwrote R1


def test_a_shrinking_reingest_deletes_the_pages_that_are_gone(store):
    """Register **E7**: *"re-ingest leaves orphan points — stale pages survive a shrinking
    re-run"*. Idempotent `point_id` handles the pages that are still there; clause 1's filtered
    delete is what removes the ones that are not."""
    publish(store, build_records("DOC-A", "1.0", "R1", pages=PAGES))

    shorter = build_records("DOC-A", "1.0", "R2", pages=PAGES - 4)
    published = publish(store, shorter, page_count=PAGES - 4)

    assert published.retired["deleted_stale_points"] == 4
    assert index_module.count(store, COLLECTION, {"doc_id": "DOC-A"}) == PAGES - 4
    assert queryable(store, "DOC-A", "1.0") == PAGES - 4


def test_publishing_new_revision_keeps_prior_points(store):
    """AC + F9, clause 2: after publishing revision 1.4, revision 1.3's points still **exist**
    with `is_current=False`. They are not deleted — they are what `found_only_in_superseded`
    reads from at M8, and a blanket delete-by-`run_id` would satisfy F12 by destroying them."""
    publish(store, build_records("DOC-A", "1.3", "R1"))
    assert queryable(store, "DOC-A", "1.3") == PAGES

    published = publish(store, build_records("DOC-A", "1.4", "R2"))

    assert published.retired["superseded_demoted"] == PAGES
    assert published.retired["other_revision_points_kept"] == PAGES
    assert index_module.count(store, COLLECTION, {"doc_id": "DOC-A", "revision": "1.3"}) == PAGES
    assert queryable(store, "DOC-A", "1.3") == 0
    assert queryable(store, "DOC-A", "1.4") == PAGES
    assert queryable(store, "DOC-A") == PAGES


def test_publishing_one_document_leaves_every_point_of_another_untouched(store):
    """AC + clause 3 (SA-10): a point-count and payload-hash comparison of document B taken
    before and after publishing document A. The isolation is structural — no filter this module
    builds can omit the document — and this is the regression test that keeps it that way."""
    publish(store, build_records("DOC-B", "2.0", "RB"))
    before_count = index_module.count(store, COLLECTION, {"doc_id": "DOC-B"})
    before_digest = payload_digest(store, "DOC-B")

    publish(store, build_records("DOC-A", "1.3", "R1"))
    publish(store, build_records("DOC-A", "1.4", "R2"))

    assert index_module.count(store, COLLECTION, {"doc_id": "DOC-B"}) == before_count == PAGES
    assert payload_digest(store, "DOC-B") == before_digest
    assert queryable(store, "DOC-B", "2.0") == PAGES


def test_retirement_is_idempotent(store):
    """Every clause is a filter with a constant outcome, so a retried retirement is a no-op."""
    publish(store, build_records("DOC-A", "1.3", "R1"))
    publish(store, build_records("DOC-A", "1.4", "R2"))

    again = run_module.retire(store, COLLECTION, doc_id="DOC-A", revision="1.4", run_id="R2")

    assert again["deleted_stale_points"] == 0
    assert again["other_revision_points_kept"] == PAGES
    assert queryable(store, "DOC-A", "1.4") == PAGES


# ── the advisory lease (D9) ──────────────────────────────────────────────────────────────────────

def test_a_second_worker_refuses_a_live_lease_and_takes_it_with_steal(store):
    """AC: two workers taking the same run — the second refuses without `--steal`; with `--steal`
    it proceeds, and the final point count is still `pdf.page_count`.

    The lease is **advisory**: Qdrant has no compare-and-swap, so what makes the duplicate safe is
    I1 (idempotent `point_id`) and I7 (nothing queryable until the gates pass), not this claim.
    """
    records = build_records("DOC-A", "1.0", "R1")
    write(store, records)
    open_run(store, records)

    with pytest.raises(run_module.LeaseHeld) as refusal:
        run_module.claim(store, RUNS, "R1", owner="worker-2")
    assert refusal.value.details["owner"] == "suite"

    stolen = run_module.claim(store, RUNS, "R1", owner="worker-2", steal=True)
    assert stolen.lease.owner == "worker-2" and stolen.lease.live()

    write(store, records)  # the duplicated worker re-bills and re-writes: a cost bug, not a data one
    report = gates.evaluate(records=list(records), page_count=PAGES, windows=windows_of())
    published = run_module.publish(store, runs_collection=RUNS, collection=COLLECTION,
                                   record=stolen, report=report, records=list(records))

    assert published.pages_indexed == PAGES == queryable(store, "DOC-A", "1.0")


def test_the_lease_is_released_when_the_run_ends(store):
    """A lease outliving the process that held it is what makes an operator reach for `--steal`
    when they should not have to."""
    published = publish(store, build_records("DOC-A", "1.0", "R1"))

    assert not published.lease.live() and published.lease.owner == ""


def test_a_stopped_run_releases_its_lease_and_publishes_nothing(store):
    """§15 Factor IX: `stopped` is what a SIGTERM leaves, and it is the only state `--resume`
    accepts without `--steal`."""
    records = build_records("DOC-A", "1.0", "R1")
    write(store, records)
    record = open_run(store, records)

    stopped = run_module.stop(store, RUNS, record, reason="sigterm", step="extract")

    assert stopped.state == run_module.STOPPED and not stopped.lease.live()
    assert stopped.failed is not None and stopped.failed.reason == "sigterm"
    assert queryable(store, "DOC-A") == 0
    assert run_module.claim(store, RUNS, "R1", owner="worker-2").state == run_module.RUNNING


# ── the control plane holds what §6.9 says it does ───────────────────────────────────────────────

def test_the_observed_token_inventory_is_written_from_the_text_layer_only(store):
    """§6.8, C7 — the inventory backing `present_instead`, stored on the document's control point.
    Built from `text` and nothing else, over the searchable pages only (I2, §5.7)."""
    publish(store, build_records("DOC-A", "1.0", "R1"))

    inventory = run_module.read_inventory(store, RUNS, "DOC-A")

    assert inventory is not None and len(inventory) > 0
    assert all(any(character.isdigit() for character in token) for token in inventory.tokens)
    assert inventory.starting_with("k10") and not inventory.starting_with("zzz")


def test_a_scanned_document_contributes_no_observed_tokens(store):
    """A page nobody may be shown a hit from must not be volunteering codes beside an `absent`
    verdict either (§5.7)."""
    publish(store, build_records("SCANNED", "1.0", "R1", rate=None, labels=[""] * PAGES))

    assert len(run_module.read_inventory(store, RUNS, "SCANNED") or ()) == 0


def test_the_export_reads_the_published_run_back_out_of_the_index(store):
    """§6.8 — both artefacts are generated from the index, so any instance can serve any run."""
    publish(store, build_records("DOC-A", "1.0", "R1", doc_type="safety_function_list"))

    lines = [json.loads(line) for line in export_module.labels(
        store, COLLECTION, run_id="R1", doc_id="DOC-A", revision="1.0",
        safety_doc_types=("safety_function_list",))]
    tokens = [json.loads(line) for line in export_module.observed_tokens(
        store, RUNS, run_id="R1", doc_ids=["DOC-A"])]

    assert [row["page_no"] for row in lines] == list(range(1, PAGES + 1))
    assert all(row["safety_flag"] for row in lines)
    assert len(tokens) == 1 and tokens[0]["doc_id"] == "DOC-A"


def test_the_two_gauges_of_11_4_come_from_the_control_plane(store):
    """§11.4 — computed from `vsir_runs` on every scrape, so any replica answers the same and a
    restart is not a hole in the series."""
    publish(store, build_records("DOC-A", "1.0", "R1"))
    blocked = build_records("DOC-C", "1.0", "R3")
    write(store, blocked)
    with pytest.raises(run_module.GateBlocked):
        run_module.publish(store, runs_collection=RUNS, collection=COLLECTION,
                           record=open_run(store, blocked),
                           report=gates.evaluate(records=list(blocked), page_count=PAGES,
                                                 windows=windows_of(offset_ok=False)),
                           records=list(blocked))

    snapshot = run_module.gauges(store, RUNS)

    assert snapshot["ingest_grounded_rate_median"] == {"DOC-A": 1.0}
    assert snapshot["ingest_gate_failures_total"][gates.OFFSET_CHECK] == 1
    assert snapshot["ingest_gate_failures_total"][gates.WINDOW_COVERAGE] == 0


def test_the_control_plane_carries_no_page_points_and_the_index_no_control_points(store):
    """§6.6's reason for putting the fingerprint in `vsir_runs`: the page collection's point count
    **is** I1's assertion, so a sentinel point in it would make the count mean something else."""
    publish(store, build_records("DOC-A", "1.0", "R1"))

    kinds = {(point.payload or {}).get("kind") for point in
             store.scroll(RUNS, limit=256, with_payload=True)[0]}

    # This suite publishes without running the windowing ladder, so there is no window point —
    # `test_run_record.py` covers those. Every point that is here says which kind it is.
    assert kinds == {"fingerprint", run_module.KIND_RUN, run_module.KIND_INVENTORY}
    assert index_module.count(store, COLLECTION, {"doc_id": "DOC-A"}) == PAGES
    assert all("kind" not in (point.payload or {}) for point in
               store.scroll(COLLECTION, limit=8, with_payload=True)[0])


def test_a_run_point_id_is_derived_so_writing_it_twice_is_one_point(store):
    """Like `point_id` for a page (I1): the control plane must not double either."""
    records = build_records("DOC-A", "1.0", "R1")
    write(store, records)
    open_run(store, records)
    open_run(store, records)

    assert run_module.run_point_id("R1") == str(uuid.uuid5(
        run_module.NAMESPACE, "vsir:run:R1"))
    assert len(run_module.runs(store, RUNS)) == 1
