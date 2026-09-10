"""The §12.3 acceptance table, as something a reviewer runs (Spec §12.3, §13 M3 · plan U016).

§12.3 is nine lookup rows, a `verify` row, a scanned-document row and a two-line PARITY block, and
until this module existed they were only assertions inside three pytest files. That is enough to
keep the build honest and not enough to *review*: a reviewer who wants to know what the exact
surface currently does has to read `tests/api/test_acceptance_synthetic.py`, `test_parity_lookup.py`
and `test_withheld_negative_set.py` and reconstruct the table from their assertions. So the table
becomes a command, and the command prints one row per assertion with the expectation beside the
measurement — `vsir eval acceptance`.

**It is a second surface over the same numbers, never a second set of them.** That is C10: *"if
the first real ingest disagrees, record it as a blocking finding — do not re-baseline
`expected.json` silently"*, and a command carrying its own copy of a number would be a second
place to quietly fix one. So the rule here is about the **direction** a literal points:

* **no measurement is written down in this module.** Every number the corpus produces — page
  counts, totals, which page a label lands on, inventory sizes — is read out of a checked-in
  `expected.json` or out of the ported `labels.jsonl`. There is no line here that could be edited
  to make a red row green;
* **§12.3's and §12.1's own text is written down**, and asserted *against* the checked-in table:
  :data:`PARITY_ROWS`, the seven lookup labels in §12.3's order, "55 pages over 2 windows",
  `weak_abs == 20`, SA-7's `total: 10`. Those are the spec, and a table that had drifted from it
  would make every measurement below meaningless. Checking them is the point, not a shortcut.

One literal is neither: :data:`~vsir.eval.abstention.CORRECTNESS_GATE`, in the other module, which
is D11's gate and is pinned in code deliberately (see there).

── Three sections, and why they are separate ────────────────────────────────────────────────────

* **SYNTHETIC** — `data/fixtures/synthetic_pages/`, the §13 M1 corpus. Hand-written page text, no
  PDF, no VLM, no spend, and always available: this section runs on every machine and in CI, and
  it is the section §13 M3 means by *"the acceptance table passes **on the synthetic corpus**"*.
* **PARITY** — `data/fixtures/legacy/`, the baseline `impl` already paid for (§12.1). §12.3's
  PARITY block, plus its negative row, plus the **GAINS** report, which §12.3 is explicit is a
  report: *"a code the old grammar dropped but the phrase index finds is a gain: record it, do not
  treat it as a diff to reconcile."* So gains are printed and never failed.
* **REAL** — `data/fixtures/TC1E-SF/`, the pilot document. Its table is checked in *ahead of* the
  ingest (C10) and this section splits along the same seam `tests/api/test_acceptance_real.py`
  does: the rows that assert the **table's own faithfulness to §12.3** run today, and the rows
  that need real text **skip by name** until the M2b re-bill lands OQ-1/OQ-2. The skip count is
  printed in the summary, because a permanent skip nobody notices is the failure mode the plan's
  risk register names.

Every section seeds a collection of its own, queries it and drops it. Nothing here touches the
serving collection, nothing here writes to disk and nothing here can spend: the exact surface is
the only thing exercised and `lookup`/`verify_claims` reach no model (§15 Factor VI, D10).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vsir.core.observed_tokens import from_records, is_code_like
from vsir.core.tok import tok, token_set
from vsir.core.verify import verify_claims
from vsir.eval import legacy, searchable_payloads, synthetic
from vsir.serve.envelope import Provenance, Status
from vsir.serve.tools.lookup import UNSEARCHABLE_TRUST, lookup

#: The three verdicts a row can carry. `SKIP` is a first-class outcome rather than an absence: a
#: row that cannot run yet has to be visible, and it must not be counted as a pass (plan U016's
#: risk register) nor fail the command.
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

#: The sections, in the order they print. `--only` takes one of these or `all`.
SECTIONS = ("synthetic", "parity", "real")

#: Where the pilot document's frozen fixture lives when it is not at the repository path — the same
#: escape hatch `VSIR_SYNTHETIC_PAGES` and `VSIR_LEGACY_FIXTURE` are (§15 Factor III).
TC1E_DIR_ENV = "VSIR_TC1E_FIXTURE"

#: The three artefacts the one paid ingest buys (§12.1). `expected.json` is **not** among them: it
#: is the spec's, checked in first, and that ordering is the whole of C10.
BOUGHT = ("raw_window_1.json", "raw_window_2.json", "text.json")

#: §12.3's first two lookup rows, which are also the two the PARITY corpus can carry. This is the
#: spec's **text**, not a measurement: the pages each one lands on are read out of `labels.jsonl`.
PARITY_ROWS = ("SF 1.1A", "SF 5.5b")

#: The infix that names the collections this command creates, seeds, queries and drops. The base
#: is the deployment's own ``VSIR_COLLECTION`` (§15 Factor III), and `synthetic_collection` /
#: `legacy_collection` suffix it further — so an eval collection can never *equal* the serving
#: one, and the two suites that seed their own acceptance corpora cannot collide with this command
#: either. Every one of them is dropped in a ``finally``.
EPHEMERAL = "eval_acceptance"


@dataclass(frozen=True)
class Row:
    """One assertion: what was asked, what §12.3 expects, what the index answered, the verdict."""

    section: str
    assertion: str
    expected: str
    observed: str
    outcome: str
    #: Why a `SKIP` is skipped. Named, never blank — an unexplained skip is a silent hole.
    reason: str = ""

    @property
    def failed(self) -> bool:
        return self.outcome == FAIL


@dataclass(frozen=True)
class Report:
    """Every row of every section that ran, plus the two things §12.3 asks to be *recorded*."""

    rows: tuple[Row, ...] = ()
    #: §12.3's GAINS row: `(code, pages)` the old grammar dropped and the phrase index finds.
    gains: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: R7 — the §7/§8 paths parity says nothing about, printed so green is never read as sign-off.
    no_coverage: tuple[str, ...] = ()
    #: Sections that could not run at all, with the reason. Distinct from a skipped row.
    refusals: tuple[str, ...] = ()

    @property
    def passed(self) -> int:
        return sum(1 for row in self.rows if row.outcome == PASS)

    @property
    def failed(self) -> int:
        return sum(1 for row in self.rows if row.outcome == FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for row in self.rows if row.outcome == SKIP)

    @property
    def ok(self) -> bool:
        """A skipped row is not a failure and a refused section is: it produced no evidence."""
        return self.failed == 0 and not self.refusals

    def section(self, name: str) -> tuple[Row, ...]:
        return tuple(row for row in self.rows if row.section == name)


def _row(section: str, assertion: str, expected: Any, observed: Any, *, ok: bool) -> Row:
    return Row(section=section, assertion=assertion, expected=str(expected),
               observed=str(observed), outcome=PASS if ok else FAIL)


def _equal(section: str, assertion: str, expected: Any, observed: Any) -> Row:
    """The common shape: a row that passes exactly when the two sides agree."""
    return _row(section, assertion, expected, observed, ok=expected == observed)


def _skip(section: str, assertion: str, expected: Any, reason: str) -> Row:
    return Row(section=section, assertion=assertion, expected=str(expected), observed="—",
               outcome=SKIP, reason=reason)


def _pages(response: Any) -> str:
    """The pages a response named, short enough to read in a column."""
    return " ".join(hit.page_id.split("#")[-1] for hit in response.hits) or "—"


def page_scope(page_id: str) -> dict[str, Any]:
    """A scope naming exactly one page, through `INDEXED` keys only.

    ``page_id`` is not filterable — it is not in `INDEXED` (§5.4) — and asking for it would be a
    typed 400 rather than a narrower answer. The three keys that identify a page are.
    """
    doc_id, rest = page_id.split("@", 1)
    revision, page_no = rest.split("#p", 1)
    return {"doc_id": doc_id, "revision": revision, "page_no": int(page_no)}


# ── SYNTHETIC · §12.3 over the §13 M1 corpus ────────────────────────────────────────────────────

SYNTHETIC = "SYNTHETIC"


def synthetic_rows(client: Any, collection: str, corpus: synthetic.Corpus, *,
                   provenance: Provenance) -> list[Row]:
    """§12.3's table against the seeded synthetic corpus, one row per assertion.

    The order follows §12.3's own: the exact rows first, then the four absences, then the two
    surfaces §12.3's PARITY block is about — what a model claimed and what the text backs.
    """
    expected = corpus.expected
    rows: list[Row] = []

    def ask(label: str, **kwargs: Any) -> Any:
        return lookup(client, collection, label, provenance=provenance, **kwargs)

    # The corpus itself, because every row below is a statement about these numbers.
    facts = expected["corpus"]
    records = corpus.records()
    current = [record for record in records if record.is_current]
    stats = ask("K 158").scope_stats
    rows.append(_equal(SYNTHETIC, f'{facts["doc_id"]}@{facts["revision"]} current pages indexed',
                       facts["pages"], stats.pages))
    rows.append(_equal(SYNTHETIC, "pages with no text layer (§5.7)",
                       facts["pages_no_text"], stats.pages_no_text))
    rows.append(_equal(SYNTHETIC, "pages unsearchable for lookup (§5.7)",
                       facts["pages_unsearchable"],
                       sum(1 for record in current
                           if record.text_trust in UNSEARCHABLE_TRUST or not record.has_text)))
    rows.append(_equal(SYNTHETIC, f'searchable_ratio of {facts["doc_id"]}',
                       round(facts["searchable_ratio"], 4),
                       round(stats.docs[0].searchable_ratio, 4)))
    rows.append(_equal(SYNTHETIC,
                       f'superseded revision {facts["superseded_revision"]} kept, not deleted',
                       f'{facts["superseded_pages"]} page(s) is_current=False',
                       f"{len(records) - len(current)} page(s) is_current=False"))

    # ── §12.3 rows 1-5: an exact label finds exactly its page, and never the decoy (F1, F3) ──
    for label in expected["compact_labels"]:
        response = ask(label["label"])
        rows.append(_row(SYNTHETIC, f'lookup("{label["label"]}") → printed {label["printed"]}',
                         f'total=1 {label["page_id"].split("#")[-1]}',
                         f"total={response.total} {_pages(response)}",
                         ok=response.status is Status.OK and response.total == 1
                         and [hit.page_id for hit in response.hits] == [label["page_id"]]))

    decoy = expected["decoy"]
    response = ask(decoy["label"])
    rows.append(_row(SYNTHETIC, f'lookup("{decoy["label"]}") never returns the token decoy',
                     f'without {decoy["page_id"].split("#")[-1]}', _pages(response),
                     ok=decoy["page_id"] not in [hit.page_id for hit in response.hits]))

    for near in expected["one_character_apart"]:
        response = ask(near["label"])
        rows.append(_row(SYNTHETIC,
                         f'lookup("{near["label"]}") ≠ the page printing {near["printed_there"]}',
                         f'without {near["not_page_id"].split("#")[-1]}', _pages(response),
                         ok=near["not_page_id"] not in [hit.page_id for hit in response.hits]))

    prefix = expected["phrase_prefix"]
    response = ask(prefix["label"])
    rows.append(_row(SYNTHETIC, f'lookup("{prefix["label"]}") matches a contiguous run of tokens',
                     f'{prefix["status"]} {prefix["page_id"].split("#")[-1]}',
                     f"{response.status.value} {_pages(response)}",
                     ok=response.status.value == prefix["status"]
                     and [hit.page_id for hit in response.hits] == [prefix["page_id"]]))

    # ── §12.3 row 6: weak/needs_scope, at ANY cap, off a server constant (§7.1) ──
    weak = expected["weak"]
    for cap in weak["caps"]:
        response = ask(weak["label"], cap=cap)
        rows.append(_row(SYNTHETIC, f'lookup("{weak["label"]}", cap={cap}) is weak at any cap',
                         f'weak total={weak["total"]} '
                         f'capped={weak["total"] > cap}',
                         f"weak={response.weak} total={response.total} "
                         f"capped={response.capped}",
                         ok=response.weak is True and response.needs_scope is True
                         and response.total == weak["total"]
                         and response.capped is (weak["total"] > cap)
                         and len(response.hits) == min(cap, weak["total"])))

    # ── §12.3 row 7: an absence a different move could answer says so (F3, §7.1) ──
    suggest = expected["suggest"]
    response = ask(suggest["label"])
    observed_next = response.next
    rows.append(_row(SYNTHETIC, f'lookup("{suggest["label"]}") → {suggest["status"]} + next.suggest',
                     f'{suggest["status"]} {suggest["suggest"]}',
                     f"{response.status.value} "
                     f"{list(observed_next.suggest) if observed_next else None}",
                     ok=response.status.value == suggest["status"] and not response.hits
                     and observed_next is not None
                     and list(observed_next.suggest) == suggest["suggest"]))
    rows.append(_row(SYNTHETIC, "…and lists the tokens that did occur (§7.1)",
                     suggest["tokens_observed"],
                     list(observed_next.tokens_observed) if observed_next else None,
                     ok=observed_next is not None
                     and list(observed_next.tokens_observed) == suggest["tokens_observed"]))

    asymmetric = expected["asymmetric_variant"]
    response = ask(asymmetric["label"])
    rows.append(_row(SYNTHETIC,
                     f'lookup("{asymmetric["label"]}") abstains with a move, never a wrong page',
                     f'{asymmetric["status"]} {asymmetric["suggest"]}',
                     f"{response.status.value} "
                     f"{list(response.next.suggest) if response.next else None}",
                     ok=response.status.value == asymmetric["status"] and not response.hits
                     and response.next is not None
                     and list(response.next.suggest) == asymmetric["suggest"]))

    # ── §12.3 row 9: a scanned or garbled page is not_searchable, never not_found (F4) ──
    for kind in ("no_text", "untrusted"):
        row = expected[kind]
        scoped = ask(row["label"], scope=row["scope"])
        unscoped = ask(row["label"])
        rows.append(_row(SYNTHETIC, f'lookup("{row["label"]}") in {kind} scope → not_searchable',
                         row["scoped_status"], scoped.status.value,
                         ok=scoped.status.value == row["scoped_status"] and not scoped.hits))
        rows.append(_row(SYNTHETIC, f'lookup("{row["label"]}") unscoped → {row["unscoped_status"]}',
                         row["unscoped_status"], unscoped.status.value,
                         ok=unscoped.status.value == row["unscoped_status"]
                         and not unscoped.hits))
        disclosed = ask(row["label"], include_unverified=True)
        rows.append(_row(SYNTHETIC, "…and is disclosed only through unverified_hits (D3)",
                         f'{row["unverified_hits"]} unverified, verified=false',
                         f"{len(disclosed.unverified_hits)} unverified, "
                         f"{len(disclosed.hits)} verified",
                         ok=not disclosed.hits
                         and len(disclosed.unverified_hits) == row["unverified_hits"]
                         and all(hit.verified is False for hit in disclosed.unverified_hits)))

    # ── I2 / F14: a model-invented code is unfindable, and its page is not quarantined ──
    fake = expected["hallucinated"]
    silent = ask(fake["label"])
    disclosed = ask(fake["label"], include_unverified=True)
    rows.append(_row(SYNTHETIC, f'lookup("{fake["label"]}") — claimed by the model, absent from text',
                     f'{fake["status"]}, 0 hits', f"{silent.status.value}, {len(silent.hits)} hits",
                     ok=silent.status.value == fake["status"] and not silent.hits
                     and not silent.unverified_hits and silent.total == 0))
    rows.append(_row(SYNTHETIC, "…and no argument turns the claim into a hit (I2)",
                     f'0 hits, {fake["unverified_hits"]} unverified',
                     f"{len(disclosed.hits)} hits, {len(disclosed.unverified_hits)} unverified",
                     ok=not disclosed.hits
                     and [hit.page_id for hit in disclosed.unverified_hits] == [fake["page_id"]]))
    rows.append(_row(SYNTHETIC, "…and nothing could answer it, so nothing is suggested",
                     "next=None", f"next={silent.next}", ok=silent.next is None))

    # ── I7: only a current, published page can answer ──
    for row in expected["superseded"]:
        response = ask(row["label"])
        rows.append(_row(SYNTHETIC, f'lookup("{row["label"]}") — is_current injected server-side',
                         f'{row["hits"]} hit(s)', f"{len(response.hits)} hit(s) {_pages(response)}",
                         ok=len(response.hits) == row["hits"]
                         and (not row["hits"]
                              or [hit.page_id for hit in response.hits] == [row["page_id"]])))

    out_of_scope = expected["out_of_scope"]
    response = ask(out_of_scope["label"], scope=out_of_scope["scope"])
    rows.append(_row(SYNTHETIC, f'lookup in an empty scope → {out_of_scope["status"]}',
                     f'{out_of_scope["status"]}, 0 pages',
                     f"{response.status.value}, {response.scope_stats.pages} pages",
                     ok=response.status.value == out_of_scope["status"]
                     and response.scope_stats.pages == 0))

    # ── §12.3's verify row, and the three verdicts one vocabulary has (§7.2.4) ──
    for row in expected["verify"]:
        result = verify_claims(client, collection, [row["claim"]], row["page_ids"])
        verdict = result.claims[row["claim"]]
        detail = (f'reason={row["reason"]}' if row.get("reason")
                  else f'present_instead={row.get("present_instead", [])}'
                  if "present_instead" in row
                  else f'on={[page.split("#")[-1] for page in row.get("on", [])]}')
        observed_detail = (f"reason={verdict.reason}" if row.get("reason")
                           else f"present_instead={verdict.present_instead}"
                           if "present_instead" in row
                           else f"on={[page.split('#')[-1] for page in verdict.page_ids]}")
        agrees = verdict.status == row["status"]
        if row.get("reason"):
            agrees = agrees and verdict.reason == row["reason"]
        elif "present_instead" in row:
            agrees = agrees and verdict.present_instead == row["present_instead"]
        else:
            agrees = agrees and verdict.page_ids == row["on"]
        rows.append(_row(SYNTHETIC,
                         f'verify("{row["claim"]}", '
                         f'[{", ".join(page.split("#")[-1] for page in row["page_ids"])}])',
                         f'{row["status"]} {detail}', f"{verdict.status} {observed_detail}",
                         ok=agrees))

    # ── §6.8: the inventory that backs `present_instead`, built from what was indexed ──
    inventory_expected = expected["observed_tokens"]
    payloads = searchable_payloads(client, collection)
    inventory = from_records(payloads)[inventory_expected["doc_id"]]
    every_word = {word for payload in payloads for word in token_set(payload["text"])}
    rows.append(_equal(SYNTHETIC, "observed-token inventory size (§6.8)",
                       inventory_expected["count"], len(inventory)))
    rows.append(_row(SYNTHETIC, "…is exactly the code-like tokens of the searchable text",
                     "one token per code-like word", f"{len(every_word)} words scanned",
                     ok=set(inventory.tokens) == {word for word in every_word
                                                  if is_code_like(word)}))
    absent = [token for token in inventory_expected["includes"] if token not in inventory]
    present = [token for token in inventory_expected["excludes"] if token in inventory]
    rows.append(_row(SYNTHETIC, "…includes every token §6.8 says it must",
                     f'{len(inventory_expected["includes"])} tokens',
                     f'{len(inventory_expected["includes"]) - len(absent)} present'
                     + (f", missing {absent}" if absent else ""), ok=not absent))
    rows.append(_row(SYNTHETIC, "…and excludes every token §6.8 says it must not",
                     f'{len(inventory_expected["excludes"])} tokens excluded',
                     f"{len(present)} leaked" + (f": {present}" if present else ""),
                     ok=not present))
    return rows


# ── PARITY · §12.3's PARITY block, its negative row, and the GAINS report ───────────────────────

PARITY = "PARITY"


def parity_rows(client: Any, collection: str, baseline: legacy.Baseline, *,
                provenance: Provenance) -> list[Row]:
    """§12.3's two PARITY lines, measured, plus the acceptance rows the baseline can carry.

    Absolutely, not comparatively (C10): the rows below are *"405 of 405 findable"* and *"0 of 96
    findable"*, not a diff against a previous run. The GAINS set is returned separately by
    :func:`run` and never becomes a row, because §12.3 says record it.
    """
    rows: list[Row] = []

    def ask(label: str, **kwargs: Any) -> Any:
        return lookup(client, collection, label, provenance=provenance, **kwargs)

    accepted_pairs = baseline.accepted()
    raws = baseline.accepted_raws()
    rows.append(_equal(PARITY, f"the parity set {legacy.EXPORT_RUN} recorded",
                       f"{len(accepted_pairs)} pairs / {len(raws)} identifiers",
                       f"{len(accepted_pairs)} pairs / {len(raws)} identifiers"))

    unfindable: list[str] = []
    disagreed: list[str] = []
    uncapped = 0
    for raw in raws:
        response = ask(raw)
        if response.status is not Status.OK or response.total < 1:
            unfindable.append(f"{raw} → {response.status.value}")
            continue
        if response.capped:
            continue
        uncapped += 1
        recorded = {page_id for page_id, accepted in accepted_pairs if accepted == raw}
        if not recorded <= {hit.page_id for hit in response.hits}:
            disagreed.append(raw)
    rows.append(_row(PARITY, "every identifier the old gate accepted is findable by phrase",
                     f"{len(raws)} of {len(raws)}",
                     f"{len(raws) - len(unfindable)} of {len(raws)}"
                     + (f" — {unfindable[:3]}" if unfindable else ""), ok=not unfindable))
    rows.append(_row(PARITY, "…on the pages the old run recorded it on",
                     f"{uncapped} uncapped identifiers agree",
                     f"{uncapped - len(disagreed)} agree"
                     + (f" — {disagreed[:3]}" if disagreed else ""), ok=not disagreed))

    withheld = baseline.withheld()
    leaked: list[str] = []
    undisclosed: list[str] = []
    for page_id, raw in withheld:
        if ask(raw, scope=page_scope(page_id)).hits:
            leaked.append(f"{raw} on {page_id}")
    for page_id, raw in withheld:
        doc_id = page_id.split("@", 1)[0]
        disclosed = ask(raw, scope={"doc_id": doc_id}, include_unverified=True)
        if not disclosed.unverified_hits and not disclosed.hits:
            undisclosed.append(f"{raw} on {page_id}")
    rows.append(_row(PARITY, "every raw in withheld.jsonl is unfindable in `text` (I2, F14)",
                     f"0 of {len(withheld)} findable",
                     f"{len(leaked)} of {len(withheld)} findable"
                     + (f" — {leaked[:3]}" if leaked else ""), ok=not leaked))
    rows.append(_row(PARITY, "…and reachable only when the caller opts in (D3)",
                     f"{len(withheld)} under include_unverified",
                     f"{len(withheld) - len(undisclosed)} disclosed"
                     + (f" — {undisclosed[:3]}" if undisclosed else ""), ok=not undisclosed))

    # §12.3's own first two rows, on real printed shapes rather than hand-written ones. These are
    # the rows any-order matching gets wrong: three pages and two pages respectively (F1).
    #
    # The **pages** come from `labels.jsonl`, never from a literal here. A page id written into
    # this module would be a measurement of the corpus held in code, editable to make a row green
    # — the one thing C10 is about. The labels are §12.3's text; where they land is the old run's
    # own record, and the row's whole content is that the phrase index agrees with it.
    for label in PARITY_ROWS:
        expected_pages = sorted(page_id for page_id, accepted in accepted_pairs
                                if accepted == label)
        response = ask(label)
        rows.append(_row(PARITY, f'lookup("{label}") on the ported baseline',
                         f"total={len(expected_pages)} {' '.join(expected_pages) or '—'}",
                         f"total={response.total} "
                         f"{' '.join(hit.page_id for hit in response.hits) or '—'}",
                         ok=response.status is Status.OK
                         and response.total == len(expected_pages)
                         and [hit.page_id for hit in response.hits] == expected_pages))

    # §12.3's last row: a scanned document publishes and answers `not_searchable` (F4).
    #
    # Probed with a label the corpus demonstrably **does** print somewhere else, taken off the
    # baseline rather than written down here. That makes the row stronger than a made-up code
    # would: a code that is genuinely findable elsewhere is still `not_searchable` on a document
    # with no text layer, which is the distinction F4 exists for.
    scanned = [doc_id for doc_id in baseline.doc_ids if not baseline.has_text_layer(doc_id)]
    findable_elsewhere = next((raw for raw in raws if len(tok(raw)) == 1), "")
    control = ask(findable_elsewhere)
    for doc_id in scanned:
        response = ask(findable_elsewhere, scope={"doc_id": doc_id})
        rows.append(_row(PARITY,
                         f"the scanned document {doc_id} → not_searchable, not not_found",
                         f'not_searchable for "{findable_elsewhere}", '
                         f"which IS printed elsewhere",
                         f"{response.status.value}, found on "
                         f"{control.total} page(s) elsewhere",
                         # The second half is the control. Without it the row would pass on a
                         # label nothing prints at all, which says nothing about F4's distinction.
                         ok=response.status is Status.NOT_SEARCHABLE and not response.hits
                         and response.scope_stats.pages == response.scope_stats.pages_no_text
                         and control.status is Status.OK and control.total >= 1))

    # Every gain is checked before it is reported: a code that is not findable is not a gain.
    gains = baseline.gains()
    not_really: list[str] = []
    for page_id, code in gains:
        if ask(code, scope=page_scope(page_id)).status is not Status.OK:
            not_really.append(f"{code} on {page_id}")
    rows.append(_row(PARITY, "every code reported as a GAIN is genuinely findable",
                     f"{len(gains)} sighting(s)",
                     f"{len(gains) - len(not_really)} findable"
                     + (f" — {not_really[:3]}" if not_really else ""), ok=not not_really))
    return rows


# ── REAL · the pilot document's table, and what it is still waiting for ─────────────────────────

REAL = "REAL"


def tc1e_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The pilot fixture directory: an explicit path, then the env var, then the repo copy."""
    if explicit:
        return Path(explicit)
    from_env = (os.environ.get(TC1E_DIR_ENV) or "").strip()
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[3] / "data" / "fixtures" / "TC1E-SF"


def real_rows(directory: str | os.PathLike[str] | None = None) -> list[Row]:
    """The pilot document's §12.3 table: its integrity today, its corpus rows named as skips.

    The split is C10's. `expected.json` is written from the spec **before** the ingest, so the
    rows that check the table against §12.3 — that all seven lookup labels are present, that no
    row claims `capped` while its total fits the cap, that SA-7's reconciliation is recorded
    rather than applied silently — are assertions this command can make today, and everything
    measured later rests on them. The rows that need the real extraction cannot be faked, so each
    one is emitted as a `SKIP` naming the artefacts it waits on. Turning them into measurements is
    U013's remaining work (its Definition of Done is that these skips become passes); §12.3's
    PARITY rows cover the same ground on the ported baseline meanwhile.
    """
    fixture = tc1e_dir(directory)
    table = fixture / "expected.json"
    if not table.is_file():
        return [_skip(REAL, "the checked-in acceptance table", str(table),
                      f"{table} is absent: nothing states what the pilot document must answer")]

    expected = json.loads(table.read_text(encoding="utf-8"))
    corpus = expected["corpus"]
    lookups = list(expected["lookup"])
    rows: list[Row] = []

    rows.append(_equal(REAL, "the table names the pilot document at §12.1's page count",
                       f'{corpus["doc_id"]} 55 pages / 2 windows',
                       f'{corpus["doc_id"]} {corpus["pages"]} pages / {corpus["windows"]} windows'))
    rows.append(_equal(REAL, "…and its window ranges tile it exactly",
                       corpus["pages"],
                       sum(end - start + 1 for start, end in corpus["window_ranges"])))
    #: §12.3's lookup labels, in the order it states them. A row the table lost is a row nothing
    #: asserts, so the list is named here — the only literal in this module, and it is the spec's
    #: own text rather than a measurement (C10 is about numbers the corpus produces).
    in_order = ["SF 1.1A", "SF 5.5b", "SF 121.1", "EAO 84-5140.0020", "B&R X20SI4100", "3",
                "alarm 152"]
    observed_order = [row["label"] for row in lookups]
    rows.append(_row(REAL, "every lookup row of §12.3 is in the table, in its order",
                     f"{len(in_order)} rows: {in_order[0]} … {in_order[-1]}",
                     f"{len(observed_order)} rows"
                     + ("" if observed_order == in_order
                        else f", differs: {sorted(set(in_order) ^ set(observed_order))}"),
                     ok=observed_order == in_order))

    miscapped = [row["label"] for row in lookups if "capped" in row
                 and row["capped"] != (row["total"] > row.get("cap", 20))]
    rows.append(_row(REAL, "no row claims `capped` while its total fits the cap (§7.1)",
                     "0 rows", f"{len(miscapped)} rows"
                     + (f" — {miscapped}" if miscapped else ""), ok=not miscapped))

    reconciled = next((row for row in lookups if "reconciled" in row), None)
    rows.append(_row(REAL, "the SA-7 reconciliation is recorded, not silently applied (C10)",
                     "finding SA-7, total unchanged",
                     f'{reconciled["reconciled"]["finding"]}, '
                     f'{reconciled["reconciled"]["unchanged"]}' if reconciled else "absent",
                     ok=reconciled is not None
                     and reconciled["reconciled"]["finding"] == "SA-7"
                     and reconciled["reconciled"]["unchanged"] == "total: 10"
                     and reconciled["total"] == 10 and reconciled["capped"] is False))

    weak = next((row for row in lookups if row["label"] == "3"), {})
    rows.append(_row(REAL, "the weak row is a server constant and holds at every cap (§7.1)",
                     "weak_abs=20, no per-row cap",
                     f'weak_abs={weak.get("weak_abs")}, caps={weak.get("caps")}',
                     ok=weak.get("weak") is True and weak.get("needs_scope") is True
                     and weak.get("weak_abs") == 20 and "cap" not in weak))

    absent = next((row for row in lookups if row["label"] == "alarm 152"), {})
    rows.append(_row(REAL, "the absent row suggests a move rather than a wrong page (F3)",
                     'not_found + ["skim_pages"]',
                     f'{absent.get("status")} + {absent.get("suggest")}',
                     ok=absent.get("status") == "not_found" and absent.get("hits") == 0
                     and absent.get("suggest") == ["skim_pages"]))

    verify_rows = list(expected["verify"])
    rows.append(_row(REAL, "§12.3's verify row is `absent` where the tokens are present (F2)",
                     "SF 1.1A on p008 → absent",
                     " ".join(f'{row["claim"]} → {row["status"]}' for row in verify_rows),
                     ok=len(verify_rows) == 1 and verify_rows[0]["claim"] == "SF 1.1A"
                     and verify_rows[0]["status"] == "absent"))

    rows.append(_row(REAL, "the PARITY and negative sets point at the paid-for baseline (§12.1)",
                     "labels.jsonl + withheld.jsonl",
                     f'{Path(expected["parity"]["source"]).name} + '
                     f'{Path(expected["negative_set"]["source"]).name}',
                     ok=expected["parity"]["source"].endswith("labels.jsonl")
                     and expected["negative_set"]["source"].endswith("withheld.jsonl")
                     and "GAIN" in expected["parity"]["gains"].upper()))

    missing = [name for name in BOUGHT if not (fixture / name).is_file()]
    if not missing:
        rows.append(_skip(REAL, "the corpus rows, against the frozen extraction",
                          f"{len(lookups)} lookup + {len(verify_rows)} verify rows",
                          f"the M2b artefacts are present in {fixture} — running them against real "
                          f"text is U013's remaining step, and this command will not fabricate a "
                          f"measurement it has not made"))
        return rows

    reason = (f"{', '.join(missing)} absent from {fixture}: OQ-1 (the pilot PDF) and OQ-2 (a "
              f"Gemini key) are open, so the one M2b re-bill has not run. These rows assert real "
              f"text and cannot be faked; §12.3's PARITY rows run meanwhile on "
              f"data/fixtures/legacy/. U013's DoD is that this skip becomes a pass.")
    for row in lookups:
        # What the row *expects* is still printed, because a skip whose expectation is invisible
        # tells a reviewer nothing about what U013 will have to make true.
        if "total" in row:
            wanted = f'total={row["total"]} capped={row["capped"]}'
        elif row.get("weak"):
            wanted = f'weak, needs_scope, at caps {row["caps"]}'
        else:
            wanted = f'{row["status"]} + next.suggest {row.get("suggest", [])}'
        rows.append(_skip(REAL, f'lookup("{row["label"]}") on real text', wanted, reason))
    for row in verify_rows:
        rows.append(_skip(REAL, f'verify("{row["claim"]}") on real text', row["status"], reason))
    rows.append(_skip(REAL, "the parity set, on real text rather than the projection (R7)",
                      "every accepted identifier findable", reason))
    rows.append(_skip(REAL, "the negative set, on real text (I2, F14)",
                      "every withheld raw unfindable", reason))
    return rows


# ── the command ─────────────────────────────────────────────────────────────────────────────────

def run(client: Any, *, base: str, dim: int, release_id: str, only: str = "all",
        synthetic_dir: str | os.PathLike[str] | None = None,
        legacy_fixture: str | os.PathLike[str] | None = None,
        tc1e_fixture: str | os.PathLike[str] | None = None) -> Report:
    """Seed, assert, drop — per section, in one process, leaving nothing behind (§15 Factor VI).

    ``client`` may be ``None`` when ``only`` is a section that needs no index; today every corpus
    section needs one and only ``real`` does not. A section whose fixture is missing is a
    **refusal** rather than a skipped row: it produced no evidence at all, and calling that a pass
    would be the failure C10 is about.
    """
    wanted = SECTIONS if only in ("all", "") else (only,)
    rows: list[Row] = []
    refusals: list[str] = []
    gains: tuple[tuple[str, tuple[str, ...]], ...] = ()
    no_coverage: tuple[str, ...] = ()

    if "synthetic" in wanted:
        try:
            corpus = synthetic.load(synthetic_dir)
        except synthetic.FixtureMissing as refusal:
            refusals.append(f"SYNTHETIC: {refusal}")
        else:
            collection = synthetic.synthetic_collection(f"{base}_{EPHEMERAL}", dim)
            provenance = Provenance(run_id=synthetic.SEED_RUN_ID, release_id=release_id)
            try:
                synthetic.seed(client, collection, corpus.records(release_id=release_id), dim=dim)
            except Exception as refusal:  # noqa: BLE001 - anything here is "no reachable store"
                refusals.append(f"SYNTHETIC: could not seed {collection}: "
                                f"{type(refusal).__name__}: {refusal}")
            else:
                try:
                    rows.extend(synthetic_rows(client, collection, corpus, provenance=provenance))
                finally:
                    synthetic.drop(client, collection)

    if "parity" in wanted:
        try:
            baseline = legacy.load(legacy_fixture)
        except legacy.FixtureMissing as refusal:
            refusals.append(f"PARITY: {refusal}")
        else:
            collection = legacy.legacy_collection(f"{base}_{EPHEMERAL}", dim)
            provenance = Provenance(run_id=legacy.SEED_RUN_ID, release_id=release_id)
            try:
                legacy.seed(client, collection, baseline.records(), dim=dim)
            except Exception as refusal:  # noqa: BLE001 - anything here is "no reachable store"
                refusals.append(f"PARITY: could not seed {collection}: "
                                f"{type(refusal).__name__}: {refusal}")
            else:
                try:
                    rows.extend(parity_rows(client, collection, baseline, provenance=provenance))
                    gains = baseline.gains_by_code()
                    no_coverage = legacy.NO_LEGACY_COVERAGE
                finally:
                    legacy.drop(client, collection)

    if "real" in wanted:
        rows.extend(real_rows(tc1e_fixture))

    return Report(rows=tuple(rows), gains=gains, no_coverage=tuple(no_coverage),
                  refusals=tuple(refusals))


#: What a green section does **not** prove, printed above its rows. The PARITY corpus is a
#: *projection* — `Baseline.observable_text` is the one page of verbatim text `impl` wrote down
#: plus the identifier strings its own gate accepted (see `eval/legacy.py`). So the accepted half
#: genuinely exercises `variants()`, `MatchPhrase` and the WORD tokenizer over 405 real identifier
#: shapes, and the withheld half is a floor: those strings were never seeded, so "unfindable" is
#: weaker there than it will be on real text. Saying so beside the result is the only thing that
#: stops a green 405-row report being read as the M2b row it is standing in for (R7).
SECTION_CAVEATS = {
    PARITY: "on the ported projection of §12.1's baseline, not on real page prose — the accepted "
            "half exercises the phrase mechanism over 405 real identifier shapes; the withheld "
            "half is a floor until M2b (R7, and NO LEGACY COVERAGE below)",
}

#: Column widths: the assertion is the sentence, the two middles are the numbers being compared.
#: Public, because a row that rendered its two sides into one column would still print something
#: and the L2 suite has to be able to read the columns apart to assert that it did not.
ASSERTION_WIDTH = 62
VALUE_WIDTH = 34


def print_report(report: Report) -> None:
    """The reviewable output: one line per assertion, the two records §12.3 asks for, a summary.

    A human-readable report rather than the JSON event stream, for the same reason
    `vsir demo exact` prints one: this is a one-off command whose **output is the deliverable**
    (§4.4, §15 Factor XII).
    """
    for name in (SYNTHETIC, PARITY, REAL):
        section = report.section(name)
        if not section:
            continue
        print(f"\n{name} — {len(section)} assertion(s)")
        if name in SECTION_CAVEATS:
            print(f"  {SECTION_CAVEATS[name]}")
        for row in section:
            print(f"  {row.assertion[:ASSERTION_WIDTH]:<{ASSERTION_WIDTH}} "
                  f"{row.expected[:VALUE_WIDTH]:<{VALUE_WIDTH}} "
                  f"{row.observed[:VALUE_WIDTH]:<{VALUE_WIDTH}} {row.outcome}")
        reasons = {row.reason for row in section if row.outcome == SKIP}
        for reason in sorted(reasons):
            print(f"  SKIP · {reason}")

    if report.gains:
        print(f"\nGAINS — {len(report.gains)} code(s) the old grammar dropped and the phrase index "
              f"finds (§12.3: record it, do not reconcile it)")
        for code, pages in report.gains:
            print(f"  + {code:<42} {len(pages):>3} page(s)   e.g. {pages[0]}")

    if report.no_coverage:
        print(f"\nNO LEGACY COVERAGE — {len(report.no_coverage)} area(s) parity says nothing "
              f"about (R7)")
        for line in report.no_coverage:
            print(f"  - {line}")

    for refusal in report.refusals:
        print(f"\n   section refused: {refusal}")

    print(f"\nacceptance: {report.passed} passed, {report.failed} failed, "
          f"{report.skipped} skipped")
