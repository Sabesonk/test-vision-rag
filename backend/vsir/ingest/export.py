"""The Part A contract (Spec §6.8, D1, C8) — two artefacts, generated from the index and streamed.

`impl` wrote three files into ``data/exports/{run_id}/`` and handed the directory over. Two things
about that are kept and one is deleted.

**Kept:** the export is a *build-time* channel, distinct from the query-time API. The graph team
builds from what was found; questions are answered live. That separation is D1 and it survives.

**Deleted:** ``withheld.jsonl``. It listed every identifier the allowlist gate refused, and the
gate is struck (§2.4, §2.5 B) — there is no withholding left to report, because a code the text
layer does not back is not withheld from an index, it is simply absent from ``codes_in_text`` and
counted against the page's ``grounded_rate``. The file survives only as a frozen M2b parity
artefact (U012), never as an output of this pipeline.

**Changed:** the files are not files. Nothing is written to the instance's filesystem (§15 Factor
VI) — both artefacts are generated **from the index** and streamed over HTTP::

    GET /runs/{run_id}/export/labels.jsonl            one line per page
    GET /runs/{run_id}/export/observed_tokens.jsonl   one line per document

That is not a cosmetic move. `impl`'s directory was written by the CLI path and **never** by the
HTTP path (register **E1**), so a UI ingest gave the graph team nothing at all, and the artefacts
that were written sat on one instance's disk where a second replica could not serve them. Reading
from the index instead makes any instance able to serve any run's export, and makes the export a
projection of what is actually stored rather than of what one process remembered.

**Where `safety_flag` comes from now.** `impl`'s ``_is_safety()`` used two sources this CR
deletes: the unit grammar's ``kind == "safety_function"``, and a hardcoded keyword list. Dropping
both without a replacement would silently drop a *contract* item, so §6.8 replaces them with two
sources that already exist and add no grammar::

    safety_flag = (doc_type in SAFETY_DOC_TYPES              # manifest, set by the uploader
                   or any(t in page.topics for t in SAFETY_TOPICS))   # the model's own topics

Both sets are **configuration** (§15 Factor III) — corpora differ, and a list compiled into the
image would be a per-corpus taxonomy that no deployment could correct. There is no keyword list in
this module, and a test asserts it by AST scan. `safety_flag` is advisory metadata for Part A's
answer policy: never a gate, never a filter default, and never a reason to hide a page.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Iterator, Mapping, Sequence

from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.ingest import run as run_module

_log = vsir_logging.get_logger(__name__)

#: The two artefacts of §6.8, by the name they are served under.
LABELS = "labels"
OBSERVED_TOKENS = "observed_tokens"
EXPORTS: tuple[str, ...] = (LABELS, OBSERVED_TOKENS)

#: NDJSON, which is what a `.jsonl` is. One object per line, no wrapping array — so a consumer can
#: stream a 1,440-line export without holding it, which is the same reason this module yields.
MEDIA_TYPE = "application/x-ndjson"

#: Pages read back per round trip. The export streams, but Qdrant pages: the memory held at any
#: moment is one chunk, and the ordering is exact because the chunk is a `page_no` range rather
#: than an opaque scroll cursor.
PAGE_CHUNK = 512

#: How many page windows past the last accounted-for point the walk will tolerate before refusing.
#: A document whose pages are 1..N needs none of them; a gap wider than this is a numbering the
#: export cannot walk, and it says so instead of stopping early.
MAX_EMPTY_CHUNKS = 8

#: §6.8, verbatim — the field set of one `labels.jsonl` line. Asserted as an exact equality by the
#: shape test: an extra field is a contract change Part A did not agree to, and a missing one is a
#: consumer's `KeyError` in someone else's service.
LABEL_FIELDS: tuple[str, ...] = (
    "page_id", "doc_id", "revision", "page_no", "printed_page_no", "label_verified", "sections",
    "summaries", "codes_in_text", "grounded_rate", "safety_flag", "vlm_model", "prompt_version",
    "dpi",
)
SECTION_FIELDS: tuple[str, ...] = ("section_id", "title", "page_range", "series_id")
OBSERVED_TOKEN_FIELDS: tuple[str, ...] = ("doc_id", "revision", "run_id", "tokens", "token_count",
                                          "pages")


class ExportRefused(RuntimeError):
    """A typed refusal from the export path — an unknown artefact name, or an unknown run."""

    code = "export_refused"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


def safety_flag(doc_type: str, topics: Iterable[str], *,
                safety_doc_types: Iterable[str] = (),
                safety_topics: Iterable[str] = ()) -> bool:
    """§6.8's replacement for `impl`'s ``_is_safety()``. Two configured sets, no grammar.

    ``doc_type`` is the manifest facet the uploader declared — a document-level statement, never
    inferred from content (§6.1 step 01). ``topics`` is the model's own lowercase topic list, which
    is a *retrieval* label set, so a miss here costs a flag rather than a wrong answer. Comparison
    is on the lowercase forms of both sides because the model emits lowercase topics and an
    operator setting an environment variable should not have to know that.
    """
    declared = {value.strip().lower() for value in safety_doc_types if value.strip()}
    watched = {value.strip().lower() for value in safety_topics if value.strip()}
    if doc_type.strip().lower() in declared:
        return True
    return any(str(topic).strip().lower() in watched for topic in topics)


def label_row(payload: Mapping[str, Any], *, safety_doc_types: Iterable[str] = (),
              safety_topics: Iterable[str] = ()) -> dict[str, Any]:
    """One page's payload → one `labels.jsonl` row, in :data:`LABEL_FIELDS` order.

    ``codes_in_text`` **is** the old ``verified_identifiers[]`` (C8) — the same contract field,
    computed structurally from what the page prints instead of decided by a curated allowlist. It
    is read straight off the record rather than recomputed here, so the export cannot disagree
    with the index about which codes a page is evidence for.
    """
    content = payload.get("content") or {}
    provenance = payload.get("provenance") or {}
    return {
        "page_id": str(provenance.get("page_id", "")),
        "doc_id": str(payload.get("doc_id", "")),
        "revision": str(payload.get("revision", "")),
        "page_no": int(payload.get("page_no", 0)),
        "printed_page_no": str(content.get("printed_page_no", "")),
        "label_verified": bool(content.get("label_verified", False)),
        "sections": [
            {"section_id": str(section.get("section_id", "")),
             "title": str(section.get("title", "")),
             "page_range": list(section.get("page_range") or []) or None,
             "series_id": str(section.get("series_id", ""))}
            for section in (content.get("sections") or [])
        ],
        "summaries": [{"lang": str(summary.get("lang", "")), "text": str(summary.get("text", ""))}
                      for summary in (content.get("summaries") or [])],
        "codes_in_text": list(content.get("codes_in_text") or []),
        # `None` where the page has no text layer, never 0.0 — §5.7's rule, carried out of the
        # index and into the contract, so Part A can tell "nothing was claimed" from "nothing
        # checked out".
        "grounded_rate": content.get("grounded_rate"),
        "safety_flag": safety_flag(str(payload.get("doc_type", "")),
                                   content.get("topics") or [],
                                   safety_doc_types=safety_doc_types,
                                   safety_topics=safety_topics),
        "vlm_model": str(provenance.get("vlm_model", "")),
        "prompt_version": str(provenance.get("prompt_version", "")),
        "dpi": int(provenance.get("dpi", 0)),
    }


def _line(row: Mapping[str, Any]) -> str:
    """One NDJSON line. ``ensure_ascii=False`` because a summary is prose in the page's language."""
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"


def _page_payloads(client: Any, collection: str, *, run_id: str, doc_id: str, revision: str,
                   chunk: int) -> Iterator[dict[str, Any]]:
    """The run's page payloads, in `page_no` order, one bounded chunk at a time.

    The chunking is a ``page_no`` range rather than an opaque scroll cursor, so the order is total
    and stable between runs: a consumer diffing two exports of the same document sees the changes
    rather than a re-shuffle. Nothing beyond one chunk is ever held.

    The **count comes first**, and it is what terminates the walk. A generator that stopped at the
    first empty chunk would silently truncate a document whose page numbering has a hole in it —
    and a truncated export of an index that is missing pages is precisely the failure `labels.jsonl`
    is meant to make visible. If the walk cannot account for every point, it raises.
    """
    must: list[qm.Condition] = [qm.FieldCondition(key="run_id", match=qm.MatchValue(value=run_id))]
    if doc_id:
        must.append(qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id)))
    if revision:
        must.append(qm.FieldCondition(key="revision", match=qm.MatchValue(value=revision)))
    base = qm.Filter(must=must)

    total = client.count(collection, count_filter=base, exact=True).count
    seen, start, chunks = 0, 1, 0
    limit = (total // max(chunk, 1)) + MAX_EMPTY_CHUNKS + 1
    while seen < total:
        if chunks > limit:
            raise ExportRefused(
                f"the export walked {chunks} page window(s) of {chunk} and accounted for {seen} "
                f"of {total} point(s) in run {run_id}: the page numbering is not 1..N, so a "
                f"complete export cannot be produced. That is a `window_coverage` failure the "
                f"gates should have caught (§11.1), and truncating the file here would hide it",
                run_id=run_id, doc_id=doc_id, expected=total, produced=seen)
        window = qm.Filter(must=[*must, qm.FieldCondition(
            key="page_no", range=qm.Range(gte=start, lt=start + chunk))])
        found: list[dict[str, Any]] = []
        offset: Any = None
        while True:
            page, offset = client.scroll(collection, scroll_filter=window,
                                         limit=run_module.SCROLL_BATCH, offset=offset,
                                         with_payload=True, with_vectors=False)
            found.extend((point.payload or {}) for point in page)
            if offset is None:
                break
        for payload in sorted(found, key=lambda item: int(item.get("page_no", 0))):
            seen += 1
            yield payload
        start += chunk
        chunks += 1


def labels(client: Any, collection: str, *, run_id: str, doc_id: str = "", revision: str = "",
           safety_doc_types: Iterable[str] = (), safety_topics: Iterable[str] = (),
           chunk: int = PAGE_CHUNK) -> Iterator[str]:
    """``labels.jsonl`` — one line per page, streamed. **Nothing is written to disk** (§15 VI).

    A generator, not a string and not a file: the response is produced as Qdrant answers, so a
    1,440-page manual's export costs one chunk of memory in the serving process and no bytes
    anywhere. There is no ``open()`` in this module and a test asserts that by AST scan.
    """
    lines = 0
    for payload in _page_payloads(client, collection, run_id=run_id, doc_id=doc_id,
                                  revision=revision, chunk=chunk):
        lines += 1
        yield _line(label_row(payload, safety_doc_types=safety_doc_types,
                              safety_topics=safety_topics))
    _log.info("export_streamed", artefact=LABELS, run_id=run_id, doc_id=doc_id, lines=lines,
              bytes_written_to_disk=0)


def observed_tokens(client: Any, runs_collection: str, *, run_id: str = "",
                    doc_ids: Sequence[str] = ()) -> Iterator[str]:
    """``observed_tokens.jsonl`` — one line per **document**, from the control plane (§6.8, D9).

    The inventory backs `present_instead`, the disclosure beside an `absent` verdict. It is
    exported because Part A's answer policy needs to know which code-like tokens a document's text
    layer actually carries — and because the same structure is the only thing in this system that
    can say *"K73 is not there; K78 is"* without a distance, a score or a near-miss match (F16).
    """
    lines = 0
    for payload in run_module.inventories(client, runs_collection, doc_ids):
        lines += 1
        yield _line({field: payload.get(field, [] if field == "tokens" else "")
                     for field in OBSERVED_TOKEN_FIELDS})
    _log.info("export_streamed", artefact=OBSERVED_TOKENS, run_id=run_id, lines=lines,
              bytes_written_to_disk=0)


def stream(client: Any, *, artefact: str, collection: str, runs_collection: str,
           record: run_module.RunRecord, safety_doc_types: Iterable[str] = (),
           safety_topics: Iterable[str] = ()) -> Iterator[str]:
    """Dispatch to one of the two exports for a run. An unknown name is a typed refusal."""
    if artefact == LABELS:
        return labels(client, collection, run_id=record.run_id, doc_id=record.doc_id,
                      revision=record.revision, safety_doc_types=safety_doc_types,
                      safety_topics=safety_topics)
    if artefact == OBSERVED_TOKENS:
        return observed_tokens(client, runs_collection, run_id=record.run_id,
                               doc_ids=[record.doc_id])
    raise ExportRefused(
        f"{artefact!r} is not an export. §6.8 defines exactly {list(EXPORTS)}; `withheld.jsonl` "
        f"was the third file `impl` wrote and it is dropped — the allowlist gate that produced it "
        f"is struck, so there is no withholding left to report",
        artefact=artefact, exports=list(EXPORTS))


__all__ = [
    "EXPORTS", "LABELS", "LABEL_FIELDS", "MEDIA_TYPE", "OBSERVED_TOKENS",
    "OBSERVED_TOKEN_FIELDS", "PAGE_CHUNK", "SECTION_FIELDS", "ExportRefused", "label_row",
    "labels", "observed_tokens", "safety_flag", "stream",
]
