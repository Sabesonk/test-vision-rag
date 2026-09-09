"""Step 01 — identity. Adapted from ``impl/app/pipeline.py``'s entry, which had no module of its own.

Nothing is extracted here, nothing is embedded, nothing costs money — and it is still the step you
cannot fix later without re-billing the whole document, because it decides **identity**:

| decision | if it is wrong |
|---|---|
| ``doc_id`` | the knowledge graph attaches entities to the wrong node, or mints a duplicate |
| ``revision`` | revision 1.4's page 54 silently overwrites revision 1.3's page 54 |

So the rule of §6.1 step 01 is narrow and absolute: the facets come from the **filename, the file's
own metadata, and the uploader** — never from the content. There is no grammar in this module. No
regex, no taxonomy, no keyword list, no "if the title contains 'safety' then…". A classifier here
would be invisible, unversioned corpus knowledge sitting in front of every later step, and §5.2
bans exactly that everywhere else in the pipeline; there is no reason it should be allowed at the
door. What the *model* thinks the document is arrives at step 04 as :class:`DocumentFacts`, as a
cross-check, and the operator's declaration wins where there is one.

Two `impl` defects are closed by shape rather than by care:

* **register A4** — ``facts.doc_type = doc_type or facts.doc_type``, where the HTTP form and the UI
  dropdown both defaulted to the truthy literal ``"unknown"``, so S1's classification was thrown
  away by leaving a dropdown alone. Here a facet that was not declared is recorded as *not
  declared* (:attr:`Manifest.doc_type_declared`), so a later step can fill it without having to
  distinguish "the operator said unknown" from "nobody said anything".
* **the revision cross-check** — `impl` reported ``s1_said: "1.0"`` when S1 had actually returned an
  empty string, because ``1.0`` was the fallback constant. An unread field and a field genuinely
  read as ``1.0`` were indistinguishable in the one report whose disagreement mints a duplicate
  document. :attr:`Manifest.revision_declared` is what makes them distinguishable here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pymupdf

from vsir.core import ids

#: What a document is when nobody has said. Truthy, like `impl`'s — but paired with a declared-flag,
#: which is the part `impl` lacked (register A4).
DEFAULT_DOC_TYPE = "unknown"
#: The revision of a document whose operator declared none. Recorded as undeclared.
DEFAULT_REVISION = "1.0"
#: PDF ``/Subject`` and ``/Keywords`` are free text by convention written as a list. Splitting on
#: this is a separator convention, not a taxonomy: no value in the file is interpreted, only cut.
LIST_SEPARATOR = ","


def _clean(values: Iterable[Any]) -> tuple[str, ...]:
    """Trim, drop the empties, de-duplicate, keep the order the caller gave."""
    seen: dict[str, None] = {}
    for value in values:
        text = str(value).strip()
        if text:
            seen.setdefault(text, None)
    return tuple(seen)


def _split(value: str) -> tuple[str, ...]:
    return _clean(value.split(LIST_SEPARATOR))


@dataclass(frozen=True)
class Manifest:
    """A document's identity and its document-level facets (§5.3, §6.1 step 01)."""

    doc_id: str
    revision: str
    doc_type: str
    subjects: tuple[str, ...]
    tags: tuple[str, ...]
    source: Path
    size_bytes: int
    uploader: str
    revision_declared: bool
    doc_type_declared: bool

    def facets(self) -> dict[str, Any]:
        """The document-level facets of a page record, ready to stamp on every page."""
        return {
            "doc_id": self.doc_id,
            "revision": self.revision,
            "doc_type": self.doc_type,
            "subjects": list(self.subjects),
            "tags": list(self.tags),
        }

    def disagreement(self, facts: Any) -> dict[str, str]:
        """Where the model's reading differs from a facet the operator **declared**.

        Reported, never applied: the operator's inventory is authoritative, and a silent
        disagreement about the revision would mint a second document in the graph. Where nothing
        was declared there is nothing to disagree with, so an undeclared facet is absent here
        rather than reported as a mismatch against a fallback constant.
        """
        found: dict[str, str] = {}
        if self.revision_declared and getattr(facts, "revision", "") not in ("", self.revision):
            found["revision"] = str(facts.revision)
        if self.doc_type_declared and getattr(facts, "doc_type", "") not in ("", self.doc_type):
            found["doc_type"] = str(facts.doc_type)
        return found


def file_metadata(path: str | Path) -> dict[str, str]:
    """The PDF's own ``/Info`` dictionary, as strings. Metadata, never content."""
    with pymupdf.open(path) as doc:
        return {key: str(value) for key, value in (doc.metadata or {}).items() if value}


def filename_tags(stem: str) -> tuple[str, ...]:
    """The filename, cut into slug parts and lowercased. A readout, not an interpretation."""
    return _clean(ids.slug(stem).lower().split("-"))


def build(path: str | Path, *, doc_id: str | None = None, revision: str | None = None,
          doc_type: str | None = None, subjects: Iterable[str] = (),
          tags: Iterable[str] = (), uploader: str = "",
          metadata: Mapping[str, str] | None = None) -> Manifest:
    """Build the manifest from the file, its metadata and what the uploader declared.

    ``doc_id`` is **revision-stable** on purpose: the revision is a field, not part of the key. A
    graph node key that changes on every revision orphans every relationship pointing at the old
    one, which is why `impl`'s corpus declared ``TC1E-SF`` rather than letting the filename — which
    carries ``1.3`` — become the id.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"no such document: {source}")
    info = dict(metadata) if metadata is not None else file_metadata(source)

    declared_doc_type = (doc_type or "").strip()
    declared_revision = (revision or "").strip()
    declared_subjects = _clean(subjects)

    return Manifest(
        doc_id=ids.doc_id((doc_id or "").strip() or source.stem),
        revision=declared_revision or DEFAULT_REVISION,
        doc_type=declared_doc_type or DEFAULT_DOC_TYPE,
        # The file's ``/Subject`` is the machine or model the document is about when the operator
        # did not say. It is a declared field of the file, not something read off a page.
        subjects=declared_subjects or _split(info.get("subject", "")),
        tags=_clean((*_clean(tags), *_split(info.get("keywords", "")),
                     *filename_tags(source.stem))),
        source=source,
        size_bytes=source.stat().st_size,
        uploader=uploader.strip(),
        revision_declared=bool(declared_revision),
        doc_type_declared=bool(declared_doc_type),
    )
