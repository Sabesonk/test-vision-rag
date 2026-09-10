"""The ported `impl` baseline: the artefacts already paid for, and the parity sets over them
(Spec §12.1, §12.3 PARITY · plan U012).

`impl` ran seven documents through a vision model and kept every receipt. Spec §12.1 is blunt
about what that is worth: *"Most of this fixture is already paid for."* This module brings those
receipts into the repository as a read-only fixture and turns §12.3's two PARITY rows into
something a test can assert, **before a cent is spent** — which is why U012 sits inside a paid
milestone and spends nothing.

What was ported, verbatim and byte-for-byte:

* ``raw/<doc_id>/<key>.json`` — the 19 S2 responses of §12.1, in the **old schema**, exactly as
  `impl` cached them. `TC1E-SF` as 2 windows, `LTC1AV81` as 12, and one window each for
  `CE-TC1AV8`, `DS-2611-SICK`, `DS-5549-EATON`, `TC1E-PERIODIC` and `TC1AV8M2-LIFTING`.
* ``labels.jsonl`` — the `lookup` parity baseline: every identifier the old gate accepted.
* ``withheld.jsonl`` — the negative set: model-emitted codes the text layer never backed.
* ``manifest.json`` — the run's own report, which is where the page counts, revisions and window
  counts below come from rather than from anything this module infers.
* ``recorded_text.json`` — the **one** page of verbatim text layer `impl` wrote down anywhere
  (`INGESTION_WALKTHROUGH.md` §1b, `texts[0]`), lifted mechanically out of that document.
* ``SOURCE.json`` — the ledger: every ported file with its sha256, so the integrity test can prove
  the fixture is the source even where the source tree is not mounted.

**Which export run, and why `r-poc-5`.** `impl` kept five. Only `r-poc-3`, `r-poc-4` and `r-poc-5`
published every document, and of those only `r-poc-5` is the run its checked-in code produces:
`r-poc-3`/`r-poc-4` withheld 114 `SF` labels that `r-poc-5` backs, so their negative set is
polluted by a defect the last run had already fixed — and §12.3's acceptance table says
``lookup("SF 1.1A") → exactly 1 page``, which only `r-poc-5`'s baseline agrees with. `r-poc-5`'s
withheld set is also the only one that matches §12.1's description of it word for word: every row
is ``source: "vlm"``, *model-emitted codes the text layer never backed*.

── The observable projection ────────────────────────────────────────────────────────────────────

There is no PDF. `impl`'s `data/uploads/` and `data/pages/` are empty and Spec §17 OQ-1 says the
pilot document arrives with U013, so the page text those runs indexed cannot be recovered. What
**can** be recovered is the part of it the artefacts prove: for each page, the identifier strings
the old gate found *in that page's text layer* — that is the whole meaning of
``text_layer_backed: true`` — plus, for `TC1E-SF` page 1, the verbatim extraction recorded in the
walkthrough.

That union is what :func:`Baseline.observable_text` returns, and the name is the promise: it is the
**observable projection** of a text layer, never the text layer. Three rules keep it honest:

1. **Nothing the model said is in it.** Not a unit title, not a summary, not a ``printed_page_no``,
   not a code the gate refused. Those are model output, and the negative set exists to prove model
   output cannot reach the exact surface — seeding any of it into ``text`` would refute the very
   thing under test (I2, F14).
2. **It is a floor, not a page.** Every string in it was printed on that page; the page printed
   more. So a parity PASS is evidence and a parity FAIL is a defect, while a *gain* the projection
   cannot show is simply invisible rather than absent.
3. **It is never the pipeline's output.** These records are built for an ephemeral collection that
   the suite creates and drops. No published document, no serving collection, no run of this
   system claims them.

What parity therefore proves: every identifier shape the old gate accepted — 405 distinct raws
across 1,644 (page, identifier) pairs, including the multi-token ones like ``SF 1.1A`` and the
punctuation-heavy ones like ``EAO 84-5140.0020``, ``K616-K626`` and ``SAPP02D-06A0001`` — is still
found by ``MatchPhrase`` over :func:`~vsir.core.variants.variants` through Qdrant's WORD tokenizer.
That is the one thing R7 asks for: turning *"does the new code still do what the old code did"*
into an assertion over real strings. What it does **not** prove is in :data:`NO_LEGACY_COVERAGE`,
which the L2 suite prints beside its results so a green run is never mistaken for sign-off.

── Two readings of one window ───────────────────────────────────────────────────────────────────

:func:`adapt` renames the old response shape into §5.2's: ``units[] → sections[]``,
``identifiers[] → codes[]``, ``refs[]`` dropped (§2.5 B — measured at zero reads), and
``summaries`` / ``topics`` empty because the old schema has no such field. §12.1 names exactly that
gap as the one thing the U013 re-bill buys.

The two consumers want different ``codes``, and the difference matters enough to be a parameter:

* ``codes_from="window"`` — the model's ``identifiers[]``, verbatim. This is the faithful reading
  and it is what the L1 suite derives from: real window structure, real page counts, so §6.4's
  offset proof, §6.5's reattribution and §6.1 step 08's stitching all run on real data for free.
* ``codes_from="export"`` — the claim set the run **recorded per page**: the identifiers it backed
  plus the ones it withheld. This is what the L2 corpus is built from, because ``grounded_rate``
  is a ratio and the denominator has to mean something. The window's list also carries the strings
  the old grammar dropped *before* the gate — 17 of them on page 1 alone, "counted nowhere" in the
  walkthrough's own words — so rating a page against them would measure the old grammar's drop
  rate rather than its text layer, and would sink two documents to `untrusted` for a reason that
  has nothing to do with their text.

── Where the windows sit ────────────────────────────────────────────────────────────────────────

An old response is a bare ``{"pages": [...]}`` with page indices 1..N and no record of which
absolute pages they were. :func:`Baseline.placements` recovers that rather than assuming it: the
windows must tile 1..``pages`` exactly once each (from ``manifest.json``), and where a document has
more than one window each placement must be **positively confirmed** by ``labels.jsonl``, whose
rows carry the absolute ``page_id`` beside the unit the run recorded there. A document whose
alignment is not unique raises rather than picking one — the same rule as §6.4, for the same
reason.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from vsir.core import ids
from vsir.core.exact import printed_in
from vsir.core.record import PageRecord
from vsir.core.tok import tok
from vsir.eval.synthetic import FixtureMissing, drop, seed
from vsir.ingest import derive as derive_module
from vsir.ingest import stitch as stitch_module
from vsir.ingest.extract import Extraction, PageOut, SectionRef, WindowExtraction, WindowOut
from vsir.ingest.manifest import Manifest
from vsir.ingest.probe import PageProbe, Probe
from vsir.ingest.window import Plan, Window
from vsir.vlm import EXTRACT, Entry

#: Where the ported baseline lives when it is not where this package was installed from. Same
#: reasoning as ``VSIR_SYNTHETIC_PAGES``: the Docker build context is `backend/`, so the fixture is
#: not in the image and a container running the parity suite mounts it (§15 Factor III).
LEGACY_DIR_ENV = "VSIR_LEGACY_FIXTURE"

#: The `impl` tree the fixture was ported from, for the integrity test's optional second half and
#: for ``--port``. Absent on any machine that only has this repository, which is the normal case.
IMPL_ROOT_ENV = "VSIR_IMPL_ROOT"

#: The export run the two jsonl files come from. Recorded here and in ``SOURCE.json`` because
#: "ported from `impl/data/exports/r-poc-*/`" is five different baselines (see the module docstring).
EXPORT_RUN = "r-poc-5"

#: A deterministic run id for the parity corpus, so seeding twice overwrites rather than
#: accumulating and two runs of the suite produce byte-identical payloads (I1).
SEED_RUN_ID = ids.run_id(now_ms=0, randomness=b"legacy-r5!")

#: The provenance stamp on every projected record. It says what produced the ``text`` field, and
#: it is deliberately not a version of `ingest/probe.py`: nothing here read a PDF.
PROBE_VERSION = f"legacy-projection-{EXPORT_RUN}"

#: What the old run was, as its own manifest reports it. Carried onto every record's provenance so
#: a point from this corpus can never be mistaken for one this pipeline produced.
LEGACY_PROMPT_VERSION = "s2-v1"

#: Which ``codes`` a window is read with — see the module docstring.
CodesFrom = Literal["window", "export"]

#: **R7, published as required.** Parity covers what `impl` exercised, and `impl` had no HTTP
#: surface for most of §7 and no runner at all. A green parity run says nothing about any of this;
#: U006's abstention eval, U016's acceptance eval and U026's D11 gates are the actual safety net.
NO_LEGACY_COVERAGE: tuple[str, ...] = (
    "§7.1 the six-value status enum — `impl` returned bare empty lists, so no absence is "
    "distinguished and `next.suggest` has no baseline at all",
    "§7.1 `weak` / `needs_scope` against the server constant, and `scope_stats` — neither exists "
    "in `impl`",
    "§7.1 the two envelope families: `impl` has one ad-hoc dict shape and no `ToolEnvelope`",
    "§7.2.1 / §7.2.5 `skim_documents`, `skim_sections`, `resolve` — no `impl` equivalent",
    "§7.2.3 `verify` and the `present | absent | unverifiable` vocabulary — `impl` had no "
    "per-claim check to be a baseline for",
    "§7.2.4 `present_instead` and the observed-token inventory of §6.8 — net new",
    "§7.3 every cap and its typed 400: `read` ≤ 3 pages at the pinned dpi, `fetch` ≤ 5 pages / "
    "12 MP, the dpi tiers and the `region` rule — `impl` clamped or had no bound",
    "§7.3 / §8.4 `reads_remaining` and `budget_exhausted` — no budget exists in `impl`",
    "§7.4 the audit line, and cost staying out of the response body",
    "§7.6 the four refusals — `impl` returned similarity values, which is what §7.6 forbids",
    "§8 the whole runner: triage, the six correction loops, the answer gate, `POST /ask`",
    "§5.7 `text_trust`, `grounded_rate` and `searchable_ratio` as contract fields — the old gate "
    "produced a backing rate for a report, never a per-page trust level a tool reads",
    "§6.7 scoped retirement and `is_current` — `impl` deleted by run and had no revision rule",
    "§15 the cloud-native properties: probes, structured logs, SIGTERM draining, replay mode",
)

#: The documents §12.1 names, in the order it names them. A document in this tuple with no ported
#: window is a broken port, which the integrity test says out loud rather than skipping.
EXPECTED_DOCUMENTS: tuple[str, ...] = (
    "TC1E-SF", "LTC1AV81", "CE-TC1AV8", "DS-2611-SICK", "DS-5549-EATON", "TC1E-PERIODIC",
    "TC1AV8M2-LIFTING",
)


def legacy_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The fixture directory: an explicit path, then ``VSIR_LEGACY_FIXTURE``, then the repo copy."""
    if explicit:
        return Path(explicit)
    from_env = (os.environ.get(LEGACY_DIR_ENV) or "").strip()
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[3] / "data" / "fixtures" / "legacy"


def legacy_collection(base: str, dim: int) -> str:
    """``{base}_legacy_{dim}`` — created, seeded, queried and dropped inside one suite.

    Never ``{base}_{dim}``: the parity corpus is a projection of a superseded run, and a point of
    it must be impossible to confuse with a published page (§15 Factor XII, and the unit's own
    rollback plan).
    """
    return f"{base}_legacy_{dim}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PortedFile:
    """One ported artefact and where it came from. The row the integrity test asserts."""

    path: str
    source: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class Placement:
    """One old window response, and the absolute pages it turned out to describe."""

    doc_id: str
    key: str
    path: Path
    window: Window
    body: str

    @property
    def out(self) -> WindowOut:
        """The response in §5.2's shape. Recomputed rather than stored: see :func:`adapt`."""
        return adapt(json.loads(self.body))


@dataclass(frozen=True)
class Baseline:
    """The ported baseline as checked in, plus the sets §12.3 asserts over it."""

    manifest: Mapping[str, Any]
    labels: tuple[Mapping[str, Any], ...]
    withheld_rows: tuple[Mapping[str, Any], ...]
    recorded_text: Mapping[str, str]
    ported: tuple[PortedFile, ...]
    source: Path

    # ── the documents ───────────────────────────────────────────────────────────────────────────

    @property
    def documents(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.manifest.get("documents") or ())

    @property
    def doc_ids(self) -> tuple[str, ...]:
        """The documents the ported export covers, in manifest order.

        `DS-2611-SICK` has a ported window and no row here: it never published in this run, so the
        export attributes nothing to it and there is nothing to be parity *against*. It is still
        ported — §12.1 counts seven documents — and the ledger records why it has no rows.
        """
        return tuple(str(document["doc_id"]) for document in self.documents)

    def document(self, doc_id: str) -> Mapping[str, Any]:
        for entry in self.documents:
            if str(entry["doc_id"]) == doc_id:
                return entry
        raise KeyError(f"{doc_id} is not in {self.source / 'manifest.json'}")

    def page_count(self, doc_id: str) -> int:
        return int(self.document(doc_id)["pages"])

    def revision(self, doc_id: str) -> str:
        return str(self.document(doc_id)["revision"])

    def has_text_layer(self, doc_id: str) -> bool:
        return bool(self.document(doc_id)["has_text_layer"])

    def page_id(self, doc_id: str, page_no: int) -> str:
        return ids.page_id(doc_id, self.revision(doc_id), page_no)

    def manifest_of(self, doc_id: str) -> Manifest:
        """The document's facets as a :class:`~vsir.ingest.manifest.Manifest`.

        Built from the ported manifest rather than from a file: ``source`` names a PDF nobody has,
        which is the honest value — step 01 never ran here, and nothing downstream of derivation
        reads it.
        """
        entry = self.document(doc_id)
        return Manifest(
            doc_id=doc_id,
            revision=str(entry["revision"]),
            doc_type=str(entry.get("doc_type") or "unknown"),
            subjects=(),
            tags=(),
            source=Path(str(entry.get("path") or f"{doc_id}.pdf")),
            size_bytes=0,
            uploader="",
            revision_declared=False,
            doc_type_declared=False,
        )

    # ── what the export recorded, per page ──────────────────────────────────────────────────────

    def accepted(self, doc_id: str | None = None) -> tuple[tuple[str, str], ...]:
        """``(page_id, raw)`` for every identifier the old gate accepted — the parity set.

        De-duplicated and in file order. The export writes one row per *unit*, so a page carrying
        four units repeats its backed identifiers four times; the pair is what §12.3 asserts over.
        """
        seen: dict[tuple[str, str], None] = {}
        for row in self.labels:
            if doc_id and str(row["doc_id"]) != doc_id:
                continue
            for identifier in row.get("identifiers") or ():
                seen.setdefault((str(row["page_id"]), str(identifier["raw"])), None)
        return tuple(seen)

    def accepted_raws(self, doc_id: str | None = None) -> tuple[str, ...]:
        """The distinct identifiers of the parity set, sorted — one PASS row each in the demo."""
        return tuple(sorted({raw for _page_id, raw in self.accepted(doc_id)}))

    def accepted_on(self, page_id: str) -> tuple[str, ...]:
        return tuple(raw for pid, raw in self.accepted() if pid == page_id)

    def withheld(self, doc_id: str | None = None) -> tuple[tuple[str, str], ...]:
        """``(page_id, raw)`` for every model-emitted code the text layer never backed."""
        seen: dict[tuple[str, str], None] = {}
        for row in self.withheld_rows:
            page_id = str(row["page_id"])
            if doc_id and not page_id.startswith(f"{doc_id}@"):
                continue
            seen.setdefault((page_id, str(row["raw"])), None)
        return tuple(seen)

    def withheld_on(self, page_id: str) -> tuple[str, ...]:
        return tuple(raw for pid, raw in self.withheld() if pid == page_id)

    def claims_on(self, page_id: str) -> tuple[str, ...]:
        """Everything the old run attributed to this page: what it backed, then what it withheld.

        This is ``codes`` under ``codes_from="export"`` — see the module docstring for why the
        window's own list is the wrong denominator for ``grounded_rate``.
        """
        claims = list(self.accepted_on(page_id))
        for raw in self.withheld_on(page_id):
            if raw not in claims:
                claims.append(raw)
        return tuple(claims)

    def observable_text(self, page_id: str) -> str:
        """The observable projection of one page's text layer. **Not** the text layer.

        The verbatim extraction first where one was recorded, then every identifier the old gate
        proved present. A page of a document the run reported as having no text layer projects to
        ``""``, however many units the model read off its raster — that is `CE-TC1AV8`, and it is
        the corpus's `not_searchable` case rather than an omission.
        """
        doc_id = page_id.split("@", 1)[0]
        if not self.has_text_layer(doc_id):
            return ""
        parts = [self.recorded_text[page_id]] if page_id in self.recorded_text else []
        parts.extend(self.accepted_on(page_id))
        return "\n".join(parts)

    # ── the windows, and where they sit ─────────────────────────────────────────────────────────

    def window_paths(self, doc_id: str) -> tuple[Path, ...]:
        directory = self.source / "raw" / doc_id
        if not directory.is_dir():
            raise FixtureMissing(f"no ported windows for {doc_id}: {directory} is not a directory")
        return tuple(sorted(directory.glob("*.json")))

    def placements(self, doc_id: str) -> tuple[Placement, ...]:
        """Every window of a document, placed on absolute pages. Raises rather than guessing.

        One window is placed by arithmetic — it must be the whole document, and a length that
        disagrees with ``manifest.json`` is a broken port, not a shorter document. More than one
        needs evidence, and ``labels.jsonl`` is it: a placement stands only if **every** page of
        it is confirmed by the row the export wrote for that absolute page. The search returns
        every tiling that survives, and anything other than exactly one is an
        :class:`~vsir.eval.synthetic.FixtureMissing` naming the ambiguity.
        """
        pages = self.page_count(doc_id)
        level = int(self.document(doc_id).get("level") or 0)
        loaded = [(path, json.loads(path.read_text(encoding="utf-8"))) for path
                  in self.window_paths(doc_id)]
        forms = [(path, sorted(body.get("pages") or (), key=lambda page: int(page["page_index"])))
                 for path, body in loaded]

        if len(forms) == 1:
            path, only = forms[0]
            if len(only) != pages:
                raise FixtureMissing(
                    f"{doc_id}: the single ported window has {len(only)} page form(s) and "
                    f"manifest.json says the document has {pages} page(s)"
                )
            tilings = [[(path, 1, pages)]]
        else:
            tilings = self._tilings(doc_id, forms, pages)

        if len(tilings) != 1:
            raise FixtureMissing(
                f"{doc_id}: {len(tilings)} window alignment(s) are consistent with "
                f"labels.jsonl — the offset of a ported window is proved or it is not used"
            )
        return tuple(
            Placement(doc_id=doc_id, key=path.stem, path=path,
                      window=Window(start, end, level),
                      body=path.read_text(encoding="utf-8"))
            for path, start, end in tilings[0]
        )

    def _tilings(self, doc_id: str, forms: Sequence[tuple[Path, Sequence[Mapping[str, Any]]]],
                 pages: int) -> list[list[tuple[Path, int, int]]]:
        """Every ordering of the windows that tiles 1..``pages`` and that the export confirms."""
        found: list[list[tuple[Path, int, int]]] = []

        def search(start: int, remaining: Sequence[tuple[Path, Sequence[Mapping[str, Any]]]],
                   placed: list[tuple[Path, int, int]]) -> None:
            if start > pages:
                if not remaining:
                    found.append(list(placed))
                return
            for index, (path, window_forms) in enumerate(remaining):
                width = len(window_forms)
                if start + width - 1 > pages:
                    continue
                if all(self._confirms(doc_id, form, start + offset)
                       for offset, form in enumerate(window_forms)):
                    placed.append((path, start, start + width - 1))
                    search(start + width, [*remaining[:index], *remaining[index + 1:]], placed)
                    placed.pop()

        search(1, list(forms), [])
        return found

    def _confirms(self, doc_id: str, form: Mapping[str, Any], page_no: int) -> bool:
        """Does the export's row for this absolute page confirm this window form sits on it?

        Two shapes of evidence, because the export writes two shapes of row. Where the run
        recorded a real unit for the page, the form must have reported a unit with the same label.
        Where it fell back to the synthetic page-scoped unit — whose label *is* the page's read
        label — the form's ``printed_page_no`` must be that label. A page the export never wrote a
        row for confirms nothing and constrains nothing.
        """
        page_id = self.page_id(doc_id, page_no)
        real = {_collapse(row["unit"]["label"]) for row in self.labels
                if row["page_id"] == page_id and row["unit"]["kind"] != "page"}
        synthetic_units = {_collapse(row["unit"]["label"]) for row in self.labels
                           if row["page_id"] == page_id and row["unit"]["kind"] == "page"}
        if real:
            return bool(real & {_collapse(unit.get("label", "")) for unit in form.get("units") or ()})
        if synthetic_units:
            return _collapse(str(form.get("printed_page_no") or "")) in synthetic_units
        return True

    # ── the two readings ────────────────────────────────────────────────────────────────────────

    def extraction(self, doc_id: str, *, codes_from: CodesFrom = "export") -> Extraction:
        """The document's ported windows as an :class:`~vsir.ingest.extract.Extraction`.

        ``plan.level`` is the **old** run's rung, carried for the record. Nothing in derivation
        reads it, and this system's own ladder stops at ``MAX_LADDER_LEVEL`` (§6.2) — a level 2
        here is a fact about `impl`, not a plan this repository would make.
        """
        placed = self.placements(doc_id)
        windows = []
        for placement in placed:
            out = placement.out
            if codes_from == "export":
                out = WindowOut(pages=[
                    page.model_copy(update={
                        "codes": list(self.claims_on(
                            self.page_id(doc_id, placement.window.absolute(page.page_index)))),
                        # The export records a page's claim set and **no page label** — no column
                        # of `labels.jsonl` carries one. So this reading has none either, and
                        # §6.4's second check has nothing to observe rather than something to
                        # observe against a projection that is not the page's text. The check is
                        # not weakened: `codes_from="window"` keeps the model's label and the L1
                        # suite runs both checks over every ported window with it.
                        "printed_page_no": "",
                    })
                    for page in out.pages
                ])
            windows.append(WindowExtraction(
                window=placement.window,
                # The **old** cache key, which is what the file is named. §6.3's `extract_key` is a
                # different function over different inputs, so no run of this repository could ever
                # mint this string — which is exactly why these responses are not a `VSIR_FIXTURE`
                # replay directory: they answer a different schema and would be a lie to serve.
                key=placement.key,
                out=out,
                entry=Entry(key=placement.key, namespace=EXTRACT, body=placement.body,
                            origin="replay", path=str(placement.path)),
            ))
        level = placed[0].window.level if placed else 0
        return Extraction(plan=Plan(level=level, windows=tuple(p.window for p in placed)),
                          windows=tuple(windows))

    def probe(self, doc_id: str) -> Probe:
        """A :class:`~vsir.ingest.probe.Probe` over the observable projection.

        ``label`` is empty on every page: the PDF's own ``/PageLabels`` table is a mechanical
        readout of a file nobody has, and inventing one would hand §6.5 a second reading it did
        not get. ``content_hash`` is likewise empty — this probe read nothing.
        """
        pages = tuple(
            PageProbe(page_no=page_no, text=self.observable_text(self.page_id(doc_id, page_no)),
                      label="")
            for page_no in range(1, self.page_count(doc_id) + 1)
        )
        return Probe(page_count=len(pages), size_bytes=0, content_hash="", pages=pages,
                     probe_version=PROBE_VERSION)

    def derived(self, doc_id: str, *, codes_from: CodesFrom = "export",
                extraction: Extraction | None = None) -> derive_module.Derivation:
        """Step 07 over one ported document. No ``reextract``: an offset failure is the answer.

        There is nothing to re-bill with here, so :class:`~vsir.ingest.derive.OffsetError` reaches
        the caller — which is what makes the shifted-window test of the L1 suite an assertion
        rather than a silent bisection.
        """
        return derive_module.derive(
            extraction if extraction is not None else self.extraction(doc_id,
                                                                      codes_from=codes_from),
            probed=self.probe(doc_id), doc=self.manifest_of(doc_id), run_id=SEED_RUN_ID,
            release_id=EXPORT_RUN, vlm_model=str(self.manifest.get("extract_model") or ""),
            prompt_version=str(self.manifest.get("prompt_version") or LEGACY_PROMPT_VERSION),
            dpi=0, doc_lang=(),
        )

    def stitched(self, doc_id: str, **kwargs: Any) -> stitch_module.Stitched:
        """Step 08 over one ported document — sections resolved across the real window folds."""
        return stitch_module.stitch(self.derived(doc_id, **kwargs).pages, doc_id=doc_id,
                                    revision=self.revision(doc_id))

    def records(self, doc_id: str | None = None) -> tuple[PageRecord, ...]:
        """The parity corpus: every page of every ported document, ready to seed.

        ``is_current`` is flipped here and **only** here. Step 10 writes it False and §6.7's
        publish gates are the only thing that flips it in the pipeline (I7); this corpus never goes
        near that pipeline, and a corpus of pages no tool can reach would assert nothing. The flip
        is one line, in the open, on records that live in a collection the suite drops.
        """
        wanted = (doc_id,) if doc_id else self.doc_ids
        return tuple(
            record.model_copy(update={"is_current": True})
            for one in wanted
            for record in self.stitched(one).pages
        )

    # ── §12.3's third row: the gains ────────────────────────────────────────────────────────────

    def emitted(self, doc_id: str) -> tuple[tuple[str, str], ...]:
        """``(page_id, code)`` for every code the **model** returned, placed on absolute pages."""
        seen: dict[tuple[str, str], None] = {}
        for placement in self.placements(doc_id):
            for page in placement.out.pages:
                page_id = self.page_id(doc_id, placement.window.absolute(page.page_index))
                for code in page.codes:
                    seen.setdefault((page_id, code), None)
        return tuple(seen)

    def dropped(self, doc_id: str) -> tuple[tuple[str, str], ...]:
        """What the old grammar discarded *before* the gate: emitted, backed by nothing, withheld
        by nothing.

        The walkthrough's own accounting of page 1 — 42 emitted, 25 through the grammar, 17
        dropped and "counted nowhere" — is this set, and it is where every gain comes from.
        """
        recorded = set(self.accepted(doc_id)) | set(self.withheld(doc_id))
        return tuple(pair for pair in self.emitted(doc_id) if pair not in recorded)

    def gains(self, doc_id: str | None = None) -> tuple[tuple[str, str], ...]:
        """§12.3's third row: codes the old grammar dropped that the phrase index **finds**.

        *"A code the old grammar dropped but the phrase index finds is a gain: record it, do not
        treat it as a diff to reconcile."* So this is computed and reported, never asserted as an
        equality — and it is computed without a grammar of its own, from two things only: what the
        model emitted, and whether the projection prints it.

        The projection is a floor (see the module docstring), so this is a floor too. On the one
        page whose verbatim text `impl` recorded it finds ``EAO 84-5140.0020`` and
        ``B&R X20SI4100`` — the two part numbers §12.3's acceptance table names and the old
        surface could not return.
        """
        found: list[tuple[str, str]] = []
        for one in ((doc_id,) if doc_id else self.doc_ids):
            tokens = {page_id: tok(self.observable_text(page_id))
                      for page_id in {pair[0] for pair in self.dropped(one)}}
            found.extend(pair for pair in self.dropped(one)
                         if printed_in(tokens[pair[0]], pair[1]))
        return tuple(found)


    def gains_by_code(self, doc_id: str | None = None) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """The gains grouped by code, the informative ones first — a display, not a filter.

        Ordered by token count descending, then alphabetically. A code the WORD tokenizer reduces
        to one token is found wherever that token occurs, so ``"1"`` is a gain in the literal sense
        and a part number is a gain worth reading; the ordering says which is which without
        dropping either, because §12.3 says *record it* and a filter here would be a grammar.
        """
        grouped: dict[str, list[str]] = {}
        for page_id, code in self.gains(doc_id):
            grouped.setdefault(code, []).append(page_id)
        return tuple(sorted(((code, tuple(pages)) for code, pages in grouped.items()),
                            key=lambda row: (-len(tok(row[0])), row[0])))


def impl_root() -> Path | None:
    """The `impl` tree, if this machine has one mounted at ``VSIR_IMPL_ROOT``.

    Never guessed from a relative path: where the previous implementation sits is a property of a
    workstation, and a test that silently found *some* directory would compare the fixture against
    whatever was there. Absent is the normal case — the ledger's digests are what make the
    integrity assertion work without it.
    """
    configured = (os.environ.get(IMPL_ROOT_ENV) or "").strip()
    if not configured:
        return None
    root = Path(configured)
    return root if (root / "data" / "raw").is_dir() else None


def _collapse(value: Any) -> str:
    """Whitespace-collapsed and lowercased — for comparing two recordings of one label.

    Used only to align a ported window with the export's rows. It never touches a page's ``text``
    and never reaches a filter: §5.6's normalisation rule is about matching, and this is
    bookkeeping over two artefacts that were written by the same run.
    """
    return " ".join(str(value or "").split()).strip(" ()[].,;:").lower()


def adapt(body: Mapping[str, Any]) -> WindowOut:
    """One old-schema response → §5.2's :class:`~vsir.ingest.extract.WindowOut`.

    The rename `ingest/extract.py` documents, applied: ``units[] → sections[]`` (title, and
    ``is_head`` becomes ``is_start``), ``identifiers[] → codes[]``. ``refs[]`` is dropped — §2.5 B
    struck it, having measured it at zero reads anywhere in `impl`. ``summaries`` and ``topics``
    come back empty because the old schema has no such field, and §12.1 names precisely that as
    what the U013 re-bill buys.

    Nothing is invented to fill the gap. An empty ``summaries`` list is the true statement *"this
    response does not contain summaries"*; a generated one would put model-shaped prose that no
    model produced into a fixture that exists to be a baseline.
    """
    pages = []
    for page in body.get("pages") or ():
        pages.append(PageOut(
            page_index=int(page["page_index"]),
            printed_page_no=str(page.get("printed_page_no") or ""),
            page_kind=str(page.get("page_kind") or "prose"),
            lang=[str(one) for one in page.get("lang") or ()],
            sections=[
                SectionRef(title=str(unit.get("title") or unit.get("label") or ""),
                           is_start=bool(unit.get("is_head")))
                for unit in page.get("units") or ()
                if str(unit.get("title") or unit.get("label") or "").strip()
            ],
            summaries=[],
            codes=[str(one) for one in page.get("identifiers") or ()],
            topics=[],
        ))
    return WindowOut(pages=pages)


def load(directory: str | os.PathLike[str] | None = None) -> Baseline:
    """Read the ported baseline off disk. Every missing piece is a named :class:`FixtureMissing`."""
    root = legacy_dir(directory)
    if not root.is_dir():
        raise FixtureMissing(
            f"ported legacy baseline not found: {root} — set {LEGACY_DIR_ENV} to where "
            f"data/fixtures/legacy/ is mounted, or re-port it with "
            f"`python -m vsir.eval.legacy --port <impl root>`"
        )
    manifest = _read_json(root / "manifest.json")
    ledger = _read_json(root / "SOURCE.json")
    recorded = _read_json(root / "recorded_text.json")
    return Baseline(
        manifest=manifest,
        labels=tuple(_read_jsonl(root / "labels.jsonl")),
        withheld_rows=tuple(_read_jsonl(root / "withheld.jsonl")),
        recorded_text={str(key): str(value)
                       for key, value in (recorded.get("pages") or {}).items()},
        ported=tuple(PortedFile(path=str(row["path"]), source=str(row["source"]),
                                sha256=str(row["sha256"]), bytes=int(row["bytes"]))
                     for row in ledger.get("files") or ()),
        source=root,
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FixtureMissing(f"missing fixture file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FixtureMissing(f"missing fixture file: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── porting ─────────────────────────────────────────────────────────────────────────────────────
#
# `python -m vsir.eval.legacy --port <impl root>` rebuilds the fixture from the `impl` tree, the
# same way `python -m vsir.eval.synthetic_pdf` rebuilds the generated corpus. It is how the
# checked-in bytes came to exist, and running it again on the same tree is a no-op — which is what
# makes the ledger's digests re-derivable rather than a claim.

#: The walkthrough block that carries the one verbatim page of text layer `impl` wrote down.
_VERBATIM_MARKER = "`texts[0]`, verbatim:"
_VERBATIM_PAGE_ID = "TC1E-SF@1.3#p001"
_WALKTHROUGH = "INGESTION_WALKTHROUGH.md"


def recorded_page_text(walkthrough: str) -> str:
    """The fenced block after ```texts[0]`, verbatim:`` in `impl`'s walkthrough.

    Lifted mechanically rather than retyped: a hand-copied page of text layer is a page of text
    layer somebody could have adjusted, and this one is load-bearing — it is the only real text in
    the corpus, so it is where every gain and the whole of §6.4's second check come from.
    """
    marker = walkthrough.find(_VERBATIM_MARKER)
    if marker < 0:
        raise FixtureMissing(f"{_WALKTHROUGH}: no {_VERBATIM_MARKER!r} block")
    fence = re.compile(r"^```\s*$", re.MULTILINE)
    opening = fence.search(walkthrough, marker)
    if opening is None:
        raise FixtureMissing(f"{_WALKTHROUGH}: {_VERBATIM_MARKER!r} is not followed by a block")
    closing = fence.search(walkthrough, opening.end())
    if closing is None:
        raise FixtureMissing(f"{_WALKTHROUGH}: the verbatim block is not closed")
    return walkthrough[opening.end():closing.start()].lstrip("\n")


def port(impl_root: str | os.PathLike[str], fixture_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Copy the `impl` artefacts in verbatim and write the ledger beside them."""
    source = Path(impl_root)
    target = Path(fixture_dir)
    if not (source / "data" / "raw").is_dir():
        raise FixtureMissing(f"{source} does not look like the `impl` tree: no data/raw/")

    copied: list[tuple[str, str]] = []
    for window in sorted((source / "data" / "raw").rglob("*.json")):
        relative = window.relative_to(source / "data")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(window.read_bytes())
        copied.append((str(relative), str(window.relative_to(source))))

    export = source / "data" / "exports" / EXPORT_RUN
    for name in ("labels.jsonl", "withheld.jsonl", "manifest.json"):
        (target / name).write_bytes((export / name).read_bytes())
        copied.append((name, str((export / name).relative_to(source))))

    walkthrough = (source / _WALKTHROUGH).read_text(encoding="utf-8")
    (target / "recorded_text.json").write_text(json.dumps({
        "source": f"impl/{_WALKTHROUGH} §1b — `texts[0]`, verbatim",
        "note": (
            "The only page of text layer `impl` recorded anywhere. It is the OPENING of the page: "
            "the same section reports page 1 at 829-3,554 characters, so this block is a floor on "
            "what the page prints and never a complete extraction. Lifted mechanically by "
            "`python -m vsir.eval.legacy --port`, never retyped."
        ),
        "pages": {_VERBATIM_PAGE_ID: recorded_page_text(walkthrough)},
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    copied.append(("recorded_text.json", f"{_WALKTHROUGH} §1b"))

    ledger = {
        "source_root": "impl",
        "source_root_note": (
            "The previous implementation's tree, as Spec §2.4 names it. Its absolute path is a "
            f"property of a workstation, so it is not recorded here: set {IMPL_ROOT_ENV} to point "
            "the integrity test at it, and it asserts against the recorded digests without it."
        ),
        "export_run": EXPORT_RUN,
        "export_run_rationale": (
            "The last of impl's five runs and the only one whose withheld set is what Spec §12.1 "
            "describes: every row source=vlm, model-emitted codes the text layer never backed. "
            "r-poc-1/2 quarantined TC1E-SF and export nothing for it; r-poc-3/4 published it but "
            "withheld 114 SF labels that r-poc-5 backs, which would contradict §12.3's "
            'lookup("SF 1.1A") -> exactly 1 page.'
        ),
        "schema": "impl's old S2 schema, kept as-is. See vsir.eval.legacy.adapt for the rename.",
        "schema_version": int((_read_json(target / "manifest.json")).get("schema_version") or 0),
        "documents_without_export_rows": [
            {"doc_id": "DS-2611-SICK",
             "why": ("ported because §12.1 counts seven documents, but it never published in "
                     f"{EXPORT_RUN}, so labels.jsonl and withheld.jsonl attribute nothing to it "
                     "and it carries no parity rows.")},
        ],
        "files": [
            {"path": relative, "source": origin,
             "sha256": sha256_of(target / relative), "bytes": (target / relative).stat().st_size}
            for relative, origin in sorted(copied)
        ],
    }
    (target / "SOURCE.json").write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8")
    return {"fixture": str(target), "files": len(ledger["files"]), "export_run": EXPORT_RUN}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vsir.eval.legacy",
        description="Report the ported `impl` baseline, or re-port it from an `impl` tree.",
    )
    parser.add_argument("--port", metavar="IMPL_ROOT", default="",
                        help=f"re-port the fixture from this `impl` tree (or {IMPL_ROOT_ENV})")
    parser.add_argument("--fixture-dir", type=Path, default=None)
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    target = arguments.fixture_dir or legacy_dir()
    if arguments.port or os.environ.get(IMPL_ROOT_ENV):
        report = port(arguments.port or os.environ[IMPL_ROOT_ENV], target)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    baseline = load(target)
    print(json.dumps({
        "fixture": str(baseline.source),
        "export_run": EXPORT_RUN,
        "ported_files": len(baseline.ported),
        "documents": {
            doc_id: {
                "pages": baseline.page_count(doc_id),
                "windows": len(baseline.window_paths(doc_id)),
                "accepted": len(baseline.accepted(doc_id)),
                "withheld": len(baseline.withheld(doc_id)),
                "dropped_by_the_old_grammar": len(baseline.dropped(doc_id)),
                "gains": len(baseline.gains(doc_id)),
            }
            for doc_id in baseline.doc_ids
        },
        "no_legacy_coverage": list(NO_LEGACY_COVERAGE),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - the module is a process, and this is its entry
    sys.exit(main())
