"""The §12.4 adversarial abstention eval, as a command (Spec §12.4, §12.6 · plan U016).

§12.4 is one test and the spec states its stakes in one sentence: *"If one assertion here ever
fails, the system has produced the injury the whole design exists to prevent."* One hundred codes,
each one character from a code the indexed corpus really prints, put through the exact surface and
through the check that confirms it. None may return a page. None may be handed back as what is
there instead.

`tests/api/test_near_miss_codes_never_answer.py` has asserted exactly that since M1 and runs in CI
on every commit. This module is the same eval as an **operator-facing command** — `vsir eval
abstention` — for the two things a pytest file cannot do:

* **Point it at a corpus that is not a fixture.** ``--corpus indexed`` runs it against whatever the
  configured collection currently holds, which is §12.4's own wording: *"the observed-token
  inventory of **whatever corpus is indexed** — the synthetic seed at M1, the real fixture after
  M2b."* That is how the number gets measured on a real document after an ingest, and it is the
  M1-available half of the D11 gates §12.6 tabulates.
* **Report the metric rather than a dot.** ``abstention_correctness`` is a number D11 fixes at
  **1.00**, and a reviewer needs to see it, with the leaks named if it is not.

── What it does *not* do ────────────────────────────────────────────────────────────────────────

It never calls a model. `near_misses` is deterministic and has no RNG (see that module), `lookup`
and `verify_claims` are the shipped exact surface, and the whole eval is index reads: with
``--corpus synthetic`` it seeds a collection of its own from checked-in page text and drops it, and
with ``--corpus indexed`` it **only reads** — no upsert, no delete, no collection creation. A run
of this command leaves the index byte-identical, which the L2 suite asserts by comparing point
counts and payload digests either side of it.

── The control row, and why an eval of absences needs one ───────────────────────────────────────

A corpus that answered *nothing at all* would pass every assertion above. So the real codes the
fakes were mutated from are looked up too, and every one of them must come back. Without that row
a broken index is indistinguishable from a perfectly abstaining one — which is the one failure
mode a safety eval cannot afford.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

from vsir.core import ids
from vsir.core.nearmiss import DEFAULT_SAMPLE, NearMiss, near_misses
from vsir.core.observed_tokens import Inventory, from_records
from vsir.core.present_instead import present_instead
from vsir.core.tok import token_set
from vsir.core.verify import PRESENT, verify_claims
from vsir.eval import searchable_payloads, synthetic
from vsir.serve.envelope import Provenance, Status
from vsir.serve.tools.lookup import lookup

#: The corpora the command can be pointed at. ``synthetic`` seeds the checked-in §13 M1 pages into
#: a collection of its own; ``indexed`` reads the configured serving collection as it stands.
CORPORA = ("synthetic", "indexed")

#: The infix naming the collection ``--corpus synthetic`` creates and drops. Its own, so running
#: this command cannot disturb `vsir eval acceptance`'s corpus or either suite's.
EPHEMERAL = "eval_abstention"

#: The two absences a fabricated code may legitimately produce. ``ok`` is the failure this eval
#: exists to catch; ``out_of_scope`` would mean the corpus was never seeded.
HONEST_ABSENCES = (Status.NOT_FOUND, Status.NOT_SEARCHABLE)

#: D11's gate, and it is not negotiable: §12.6 fixes `abstention_correctness` at 1.00 and calls a
#: single miss a P0 stop. Held here as the pin the report is measured against, in code, so
#: relaxing it is a reviewable release rather than an env edit (the same rule as `TRUST_OK_MIN`).
CORRECTNESS_GATE = 1.00


@dataclass(frozen=True)
class Leak:
    """One fabricated code the system failed to abstain on, and how it failed.

    Named rather than counted, because the first question when this eval goes red is *"one
    character off what?"* — so the real code, the fake, and the surface that leaked are all here.
    """

    miss: NearMiss
    surface: str
    detail: str

    def __str__(self) -> str:
        return (f"{self.miss.source} → {self.miss.fake} (char {self.miss.position}): "
                f"{self.surface} {self.detail}")


@dataclass(frozen=True)
class Report:
    """The eval's result: the metric D11 gates, the leaks, and the control."""

    doc_id: str
    collection: str
    #: The inventory size the sample was drawn from — the corpus's own shape, stated.
    observed_tokens: int
    fakes: tuple[NearMiss, ...] = ()
    leaks: tuple[Leak, ...] = ()
    #: Real codes the fakes came from that stopped being findable. The control row.
    unfindable_sources: tuple[str, ...] = ()
    #: Why the eval could not run at all. An eval that produced no evidence is not a pass.
    refusal: str = ""

    @property
    def sample(self) -> int:
        return len(self.fakes)

    @property
    def abstained(self) -> int:
        """Fakes with no leak on any surface. The numerator §12.6 names."""
        leaked = {leak.miss.fake for leak in self.leaks}
        return sum(1 for miss in self.fakes if miss.fake not in leaked)

    @property
    def abstention_correctness(self) -> float:
        """`abstained / sample`. Zero-sample is 0.0, never 1.0: nothing was proved."""
        return self.abstained / self.sample if self.sample else 0.0

    @property
    def ok(self) -> bool:
        return (not self.refusal and self.sample > 0
                and self.abstention_correctness >= CORRECTNESS_GATE
                and not self.unfindable_sources)


def evaluate(client: Any, collection: str, *, provenance: Provenance, doc_id: str = "",
             sample: int = DEFAULT_SAMPLE) -> Report:
    """Run §12.4 against one collection. Reads only — nothing here writes to the index.

    ``doc_id`` selects which document's inventory the sample is drawn from; empty means the one
    the collection holds, and a collection holding several without a choice is a refusal rather
    than an arbitrary pick — a safety metric measured over an unnamed corpus is not a measurement.
    """
    payloads = searchable_payloads(client, collection)
    if not payloads:
        return Report(doc_id=doc_id, collection=collection, observed_tokens=0,
                      refusal=f"{collection} holds no current, searchable page: there is no "
                              f"observed-token inventory to mutate, so §12.4 cannot be measured")

    inventories = from_records(payloads)
    if not doc_id:
        if len(inventories) != 1:
            return Report(doc_id="", collection=collection, observed_tokens=0,
                          refusal=f"{collection} holds {len(inventories)} documents "
                                  f"({', '.join(sorted(inventories))}): name one with --doc-id, "
                                  f"because §12.4's near misses are one document's codes mutated")
        doc_id = next(iter(inventories))
    if doc_id not in inventories:
        return Report(doc_id=doc_id, collection=collection, observed_tokens=0,
                      refusal=f"{doc_id} has no searchable page in {collection}; it holds "
                              f"{', '.join(sorted(inventories))}")

    inventory = inventories[doc_id]
    # The document's own pages, and only them: a near miss is one document's code mutated, and a
    # candidate excluded because a *different* document prints it would be excluded for a reason
    # that says nothing about this corpus.
    own = [payload for payload in payloads if payload.get("doc_id") == doc_id]
    fakes = near_misses(inventory, n=sample, texts=[payload["text"] for payload in own])
    if not fakes:
        return Report(doc_id=doc_id, collection=collection, observed_tokens=len(inventory),
                      refusal=f"{doc_id}'s inventory of {len(inventory)} token(s) cannot produce "
                              f"a single near miss: every mutation lands on something printed")

    pages = _busiest_pages(own, inventory)
    leaks = list(_leaks(client, collection, fakes, pages=pages, inventory=inventory,
                        provenance=provenance))
    unfindable = tuple(source for source in sorted({miss.source for miss in fakes})
                       if not lookup(client, collection, source, provenance=provenance).hits)
    return Report(doc_id=doc_id, collection=collection, observed_tokens=len(inventory),
                  fakes=fakes, leaks=tuple(leaks), unfindable_sources=unfindable)


def _busiest_pages(payloads: Sequence[dict], inventory: Inventory,
                   how_many: int = 3) -> tuple[str, ...]:
    """The pages carrying the most observed codes — the hardest pages to abstain on.

    `verify` is per `(claim, page)`, so which pages the claims are checked against decides how
    hard the assertion is. The pages with the most real codes are where a matcher that is even
    slightly fuzzy would confirm a near miss, so those are the ones the eval names. Deterministic:
    ties break on `page_id`.
    """
    scored = sorted((-len([word for word in token_set(payload["text"]) if word in inventory]),
                     ids.page_id(payload["doc_id"], payload["revision"], payload["page_no"]))
                    for payload in payloads)
    return tuple(page_id for _score, page_id in scored[:how_many])


def _leaks(client: Any, collection: str, fakes: Sequence[NearMiss], *, pages: Sequence[str],
           inventory: Inventory, provenance: Provenance) -> Iterator[Leak]:
    """Every way a fabricated code could reach a caller, checked on both surfaces.

    Three assertions, and §12.4's sketch is one of them. The sketch reads
    ``r.present_instead`` off a `lookup` response; Family A has no such field (§7.1) — the
    disclosure belongs to a per-claim check (§7.2.4) — so the same assertion is made where the
    field actually lives. That is strictly stronger than the sketch, because it exercises the code
    path that could actually leak a near miss.
    """
    verdicts = verify_claims(client, collection, [miss.fake for miss in fakes], pages).claims
    for miss in fakes:
        response = lookup(client, collection, miss.fake, provenance=provenance)
        if response.hits:
            yield Leak(miss, "lookup",
                       f"returned {[hit.page_id for hit in response.hits]}")
        elif response.status not in HONEST_ABSENCES:
            yield Leak(miss, "lookup", f"status {response.status.value}")

        verdict = verdicts[miss.fake]
        if verdict.status == PRESENT:
            yield Leak(miss, "verify", f"present on {verdict.page_ids}")
        if miss.fake in verdict.present_instead:
            yield Leak(miss, "verify.present_instead", "returned the claim AS the disclosure")
        if miss.fake in present_instead(miss.fake, inventory):
            yield Leak(miss, "present_instead", "the prefix lookup returned the claim itself")


def run(client: Any, *, base: str, dim: int, release_id: str, corpus: str = "synthetic",
        collection: str = "", doc_id: str = "", sample: int = DEFAULT_SAMPLE,
        synthetic_dir: str | os.PathLike[str] | None = None) -> Report:
    """Seed (or not), evaluate, drop. ``--corpus indexed`` never creates or deletes anything."""
    if corpus == "indexed":
        target = collection or f"{base}_{dim}"
        provenance = Provenance(release_id=release_id)
        try:
            exists = client.collection_exists(target)
        except Exception as refusal:  # noqa: BLE001 - anything here is "no reachable store"
            return Report(doc_id=doc_id, collection=target, observed_tokens=0,
                          refusal=f"could not reach the store: {type(refusal).__name__}: "
                                  f"{refusal}")
        if not exists:
            return Report(doc_id=doc_id, collection=target, observed_tokens=0,
                          refusal=f"{target} does not exist: nothing is indexed, so §12.4 has no "
                                  f"corpus to mutate")
        return evaluate(client, target, provenance=provenance, doc_id=doc_id, sample=sample)

    try:
        pages = synthetic.load(synthetic_dir)
    except synthetic.FixtureMissing as refusal:
        return Report(doc_id="", collection="", observed_tokens=0,
                      refusal=f"corpus refused: {refusal}")
    target = synthetic.synthetic_collection(f"{base}_{EPHEMERAL}", dim)
    provenance = Provenance(run_id=synthetic.SEED_RUN_ID, release_id=release_id)
    try:
        synthetic.seed(client, target, pages.records(release_id=release_id), dim=dim)
    except Exception as refusal:  # noqa: BLE001 - anything here is "no reachable store"
        return Report(doc_id=pages.doc_id, collection=target, observed_tokens=0,
                      refusal=f"could not seed {target}: {type(refusal).__name__}: {refusal}")
    try:
        return evaluate(client, target, provenance=provenance, doc_id=pages.doc_id, sample=sample)
    finally:
        synthetic.drop(client, target)


def print_report(report: Report) -> None:
    """The reviewable output: the metric, the gate, the control, and every leak by name."""
    if report.refusal:
        print(f"\n   abstention refused: {report.refusal}")
        print("\nabstention_correctness: not measured")
        return

    print(f"\nCORPUS — {report.doc_id} in {report.collection}")
    print(f"  {report.observed_tokens} observed token(s) (§6.8), "
          f"{report.sample} fabricated code(s), each one character off a real one")
    print(f"  {len({miss.source for miss in report.fakes})} distinct source code(s): "
          + ", ".join(f"{miss.source}→{miss.fake}" for miss in report.fakes[:4]) + " …")

    print("\nLEAKS — a fabricated code that reached a caller on any surface (§12.4)")
    if report.leaks:
        for leak in report.leaks:
            print(f"  ! {leak}")
    else:
        print(f"  none: {report.abstained} of {report.sample} abstained on every surface")

    print("\nCONTROL — the real codes the fakes were mutated from are still findable")
    if report.unfindable_sources:
        for source in report.unfindable_sources:
            print(f"  ! {source} is no longer findable — an eval of absences over an empty index "
                  f"would pass every row above")
    else:
        print(f"  {len({miss.source for miss in report.fakes})} of "
              f"{len({miss.source for miss in report.fakes})} findable")

    print(f"\nabstention_correctness: {report.abstention_correctness:.2f} "
          f"(D11 gate: {CORRECTNESS_GATE:.2f}) — "
          f"{'PASS' if report.ok else 'FAIL'}")
