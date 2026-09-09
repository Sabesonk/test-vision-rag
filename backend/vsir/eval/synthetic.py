"""The M1 synthetic corpus (Spec §13 M1) — hand-written page text, no PDF, no VLM, no spend.

§13 M1 asks for `lookup` proved *"against an ephemeral Qdrant seeded with hand-written page text
— no PDF"*, and that is exactly what this module seeds. The pages live beside the code as data, in
`data/fixtures/synthetic_pages/`: one file per page, each one a page as `ingest/probe.py` would
have extracted it plus the codes an extraction would have claimed, and `expected.json` beside them
holding the acceptance table (§12.3) so a number can never be quietly re-baselined to make a run
green (C10).

**Why the fixture is a page and not a record.** A hand-written §5.3 record could contradict itself
— `has_text: true` with empty text, a `codes_in_text` that is not a subset of `codes`, a
`grounded_rate` that does not follow from either. So the checked-in file carries the two things
only a human can supply, the page's **text** and the model's **claims**, and this module derives
the record from them. A fixture that cannot be internally inconsistent is worth the twenty lines.

**The points carry no vectors.** There is no embedder at M1 and this milestone spends nothing, so
each page is upserted with an empty vector map — legal in Qdrant, and honest: the dense and the two
sparse surfaces are *empty* here, so nothing in this corpus can exercise them. That is precisely
what M1 is: the exact surface, proved on its own, before a cent is spent (§0).

**Nothing here is state.** The collection is created, seeded, queried and dropped inside one
process (§15 Factor VI); the corpus directory is located from the environment because a fixture
directory is a deployment-varying path, not a constant (`VSIR_SYNTHETIC_PAGES`, §15 Factor III).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from qdrant_client.http import models as qm

from vsir.core import ids
from vsir.core.indexed import create_collection
from vsir.core.record import PageContent, PageRecord, Provenance, StoredSection, Summary
from vsir.core.tok import token_set

#: Where the corpus lives, when it is not where this package was installed from. The Docker build
#: context is `backend/`, so the checked-in fixture is **not** in the image: a container running
#: `vsir demo exact --synthetic` mounts it and points this variable at the mount, exactly as
#: `VSIR_FIXTURE` does for replay mode (D10).
PAGES_DIR_ENV = "VSIR_SYNTHETIC_PAGES"

#: A deterministic run id for the seed, so re-seeding overwrites rather than accumulating and two
#: runs of the demo produce byte-identical payloads (I1).
SEED_RUN_ID = ids.run_id(now_ms=0, randomness=b"synthetic!")

#: The probe that produced this text was a person with a keyboard. Saying so in the provenance is
#: the point: nothing downstream can mistake the synthetic corpus for a PyMuPDF extraction.
PROBE_VERSION = "hand-written-m1"


class FixtureMissing(FileNotFoundError):
    """The corpus directory or one of its files is not there.

    A typed, named refusal rather than an empty corpus: a `lookup` over zero seeded pages returns
    `out_of_scope` for every label, which would read as a green run of a suite that tested nothing
    (the same reason a fixture miss in replay mode is an error and never a live call, D10).
    """


def pages_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The corpus directory: an explicit path, then ``VSIR_SYNTHETIC_PAGES``, then the repo copy."""
    if explicit:
        return Path(explicit)
    from_env = (os.environ.get(PAGES_DIR_ENV) or "").strip()
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[3] / "data" / "fixtures" / "synthetic_pages"


def synthetic_collection(base: str, dim: int) -> str:
    """The ephemeral collection's name — never the one a real corpus is indexed into.

    ``{base}_synthetic_{dim}``: the demo recreates and drops it, so it must be impossible to
    confuse with ``{base}_{dim}``, which holds published pages (§15 Factor XII — an admin command
    does not do live surgery on the serving collection).
    """
    return f"{base}_synthetic_{dim}"


@dataclass(frozen=True)
class Corpus:
    """The corpus as checked in: the document facts, the page specs, and the acceptance table."""

    document: Mapping[str, Any]
    pages: tuple[Mapping[str, Any], ...]
    expected: Mapping[str, Any]
    source: Path

    @property
    def doc_id(self) -> str:
        return str(self.document["doc_id"])

    @property
    def revision(self) -> str:
        return str(self.document["revision"])

    def records(self, *, release_id: str = "") -> tuple[PageRecord, ...]:
        """The §5.3 page records, in ``(revision, page_no)`` order."""
        sections = _sections(self.document, self.pages)
        return tuple(
            _record(self.document, spec, sections, release_id=release_id)
            for spec in sorted(self.pages, key=lambda spec: (_revision(self.document, spec),
                                                             int(spec["page_no"])))
        )

    def current_records(self, *, release_id: str = "") -> tuple[PageRecord, ...]:
        """Only the records a tool can reach — the ones `is_current` lets answer (I7)."""
        return tuple(record for record in self.records(release_id=release_id)
                     if record.is_current)

    def page_id(self, page_no: int, revision: str | None = None) -> str:
        return ids.page_id(self.doc_id, revision or self.revision, page_no)


def load(directory: str | os.PathLike[str] | None = None) -> Corpus:
    """Read the corpus off disk. Every missing piece is a named :class:`FixtureMissing`."""
    root = pages_dir(directory)
    if not root.is_dir():
        raise FixtureMissing(
            f"synthetic corpus directory not found: {root} — set {PAGES_DIR_ENV} to where "
            f"data/fixtures/synthetic_pages/ is mounted"
        )
    document = _read_json(root / "document.json")
    expected = _read_json(root / "expected.json")
    pages = tuple(_read_json(path) for path in sorted(root.glob("page-*.json")))
    if not pages:
        raise FixtureMissing(f"no page-*.json files in {root}")
    declared = int(document.get("pages", 0))
    current = sum(1 for spec in pages if spec.get("is_current", True))
    if declared != current:
        raise FixtureMissing(
            f"{root / 'document.json'} declares {declared} pages and {current} current page files "
            f"are present — the corpus is the acceptance table's denominator, so a mismatch is a "
            f"finding, not a rounding"
        )
    return Corpus(document=document, pages=pages, expected=expected, source=root)


def seed(client: Any, collection: str, records: Iterable[PageRecord], *, dim: int,
         recreate: bool = True) -> int:
    """Create the collection from ``INDEXED`` and upsert the records. Returns the point count.

    ``point_id = uuid5(page_id)``, so seeding twice overwrites and never doubles (I1, F12) — the
    same property the real ingest relies on, exercised here for free.
    """
    create_collection(client, collection, dim, recreate=recreate)
    points = [
        qm.PointStruct(
            id=ids.point_id(record.page_id),
            # No vectors: M1 has no embedder and spends nothing. The three fused surfaces of D2
            # are empty in this corpus, which is why only the exact surface is asserted against it.
            vector={},
            payload=record.to_payload(),
        )
        for record in records
    ]
    if points:
        client.upsert(collection, points=points, wait=True)
    return len(points)


def drop(client: Any, collection: str) -> None:
    """Delete the ephemeral collection. The demo's corpus outlives neither the process nor a run."""
    if client.collection_exists(collection):
        client.delete_collection(collection)


# ── deriving a record from a hand-written page ──────────────────────────────────────────────────

def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FixtureMissing(f"missing fixture file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _revision(document: Mapping[str, Any], spec: Mapping[str, Any]) -> str:
    return str(spec.get("revision", document["revision"]))


def _sections(document: Mapping[str, Any],
              pages: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], StoredSection]:
    """``(revision, title) → StoredSection``, ordinals in page order, extents from the pages.

    Section **extent** is computed here rather than declared in the fixture for the same reason S2
    never reports it: a page reports the section it belongs to, and the range is whatever the pages
    that carry it turn out to span (§5.2). ``series_id`` carries no revision, which is what lets a
    scope survive a revision boundary (§5.1, F8).
    """
    ordered = sorted(pages, key=lambda spec: (_revision(document, spec), int(spec["page_no"])))
    extents: dict[tuple[str, str], list[int]] = {}
    for spec in ordered:
        key = (_revision(document, spec), str(spec["section"]))
        page_no = int(spec["page_no"])
        span = extents.setdefault(key, [page_no, page_no])
        span[0], span[1] = min(span[0], page_no), max(span[1], page_no)

    doc_id = str(document["doc_id"])
    sections: dict[tuple[str, str], StoredSection] = {}
    ordinals: dict[str, int] = {}
    for (revision, title), (first, last) in extents.items():
        ordinals[revision] = ordinals.get(revision, 0) + 1
        sections[(revision, title)] = StoredSection(
            section_id=ids.section_id(doc_id, revision, ordinals[revision]),
            title=title,
            series_id=ids.series_id(doc_id, title),
            page_range=(first, last),
        )
    return sections


def _record(document: Mapping[str, Any], spec: Mapping[str, Any],
            sections: Mapping[tuple[str, str], StoredSection], *, release_id: str) -> PageRecord:
    """One hand-written page → one §5.3 record."""
    doc_id = str(document["doc_id"])
    revision = _revision(document, spec)
    page_no = int(spec["page_no"])
    page_id = ids.page_id(doc_id, revision, page_no)

    text = str(spec.get("text", ""))
    has_text = bool(spec.get("has_text", True))
    codes = [str(code) for code in spec.get("codes", [])]
    section = sections[(revision, str(spec["section"]))]
    printed = str(document.get("printed_page_no_format", "{page_no}")).format(
        page_no=page_no, pages=document.get("pages", 0))

    # §5.7, verbatim. `have` is the page's token *set*, so a code spelled with a space —
    # `SF 1.1A` — cannot intersect it and does not count as grounded. That is the specified
    # formula and `impl`'s adjacent-token joins are explicitly not ported (§2.4); the phrase-aware
    # replacement belongs to `core/health.py` (U009), which owns this derivation.
    seen = {code.lower() for code in codes}
    have = token_set(text)
    grounded = (len(seen & have) / len(seen) if seen else 1.0) if has_text else None

    return PageRecord(
        doc_id=doc_id,
        revision=revision,
        # The seed stands in for a *published* document, so `is_current` is true for the current
        # revision — the one thing a fixture may assert about itself, because there is no publish
        # step at M1 to flip it (I7, U011). The superseded page declares false and stays findable
        # to nothing.
        is_current=bool(spec.get("is_current", True)),
        doc_type=str(document.get("doc_type", "unknown")),
        subjects=[str(subject) for subject in document.get("subjects", [])],
        tags=[str(tag) for tag in document.get("tags", [])],
        page_kind=str(spec.get("page_kind", "prose")),
        lang=[str(lang) for lang in spec.get("lang", ["en"])],
        page_no=page_no,
        section_id=[section.section_id],
        series_id=[section.series_id],
        has_text=has_text,
        text_trust=spec.get("text_trust", "ok" if has_text else "no_text"),
        run_id=SEED_RUN_ID,
        text=text,
        vlm_codes=" ".join(codes),
        content=PageContent(
            printed_page_no=printed,
            # A hand-written page's printed label is exactly as verified as its text layer; §6.5's
            # real label attribution and its `interpolated` disclosure are U009's.
            label_verified=has_text,
            interpolated=not has_text,
            summaries=([Summary(lang=str(spec.get("lang", ["en"])[0]), text=str(spec["summary"]))]
                       if spec.get("summary") else []),
            topics=[str(topic) for topic in spec.get("topics", [])],
            sections=[section.model_copy(update={"is_start": bool(spec.get("is_start", False))})],
            codes=codes,
            codes_in_text=sorted(seen & have),
            grounded_rate=grounded,
            flags=[str(flag) for flag in spec.get("flags", [])],
        ),
        provenance=Provenance(
            page_id=page_id,
            run_id=SEED_RUN_ID,
            release_id=release_id,
            probe_version=PROBE_VERSION,
            vlm_model="stub",
            prompt_version="synthetic",
            # Nothing was rendered: there is no PDF behind this corpus, so there is no dpi to
            # claim. A page-image URL on a hit from here dereferences to nothing, which is true of
            # any page whose source document is unavailable and is not a claim the hit makes.
            dpi=0,
        ),
    )
