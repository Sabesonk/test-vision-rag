"""Rebuild the two sparse surfaces in place when ``sparse_version`` moves (plan §4c **P10**).

`fixes/005` made the sparse recipe client-side and versioned: :data:`~vsir.config.SPARSE_VERSION`
is the fifth field of the §6.6 fingerprint, so bumping it refuses every collection built before it
at boot. That refusal is correct — a BM25 collection and a raw-term-frequency collection are
byte-identical in shape, declare the same ``Modifier.IDF``, pass every check in
:mod:`vsir.core.indexed`, and differ only in what the stored floats *mean*. What was missing is the
other half: **a supported way to say yes.**

Without one, the only path is delete-and-re-ingest, and that is the wrong price by an order of
magnitude. Deleting the collection deletes the embedding cache with it — the cache *is* the index
(:func:`vsir.ingest.index.cached_vectors`, register B5) — so a change that touches no embedding
becomes a full live re-embed of every page. Two documents and 58 pages is pennies; the 208-document
corpus is a bill and an outage for a migration whose entire content is arithmetic over text that is
already stored.

It is already stored, and that is the whole design here. Both sparse surfaces are a pure function
of the payload — ``text`` for `lexical`, ``summaries[] + topics`` deduped against ``text`` for
`captions` — so they can be re-derived by scrolling the collection and writing back only the two
sparse vectors. No model call, no raster, no S2 receipt, no spend, and the dense vector is never
read, let alone rewritten.

**The refusal this module exists to make.** A migration that rebuilt sparse vectors under *any*
fingerprint change would be far more dangerous than no migration at all: it would stamp the new
recipe onto a collection whose **dense** vectors were made by a different model, which is exactly
the in-place mix §6.6 forbids and whose only symptom is worse neighbours. So
:func:`rebuild_sparse` compares field by field and proceeds **only** when ``sparse_version`` is the
sole difference. Every other difference — a new embed model, a new dim, a new distance, a new
composition — is :class:`UnsupportedMigration`, and the message says why the cheap path cannot
apply.

**Ordering is the crash-safety argument.** The fingerprint point is rewritten **last**, after every
page has been updated. A kill halfway therefore leaves the *old* fingerprint over a partly-rebuilt
collection — so the boot check keeps refusing, nothing serves a mixed index, and re-running the
command is safe because deriving a sparse vector from a payload is idempotent. The other order
would publish a collection that claims to be migrated while half of it is not, which is the one
outcome worse than the refusal we started with.

§15 Factor XII is why this is a subcommand and not a notebook: ``vsir migrate sparse`` runs from
the same image and release as `web` and `ingest-worker`, so the repair for a bad release is
reachable from wherever the release is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.core.record import PageRecord
from vsir.ingest import fingerprint as fingerprint_module
from vsir.ingest.fingerprint import Fingerprint
from vsir.ingest.index import CAPTIONS, LEXICAL, sparse_vectors

_log = vsir_logging.get_logger(__name__)

#: The one field this migration can repair. Everything else in :data:`vsir.ingest.fingerprint.FIELDS`
#: describes how the **dense** vector was made, and no amount of stored payload can re-derive one.
REBUILDABLE = "sparse_version"

#: Points per scroll page and per write. Large enough that a 5,600-page corpus is ~22 round trips,
#: small enough that one batch of payload plus two sparse vectors is a bounded amount of memory —
#: the dense vector, which is the big one, is deliberately never fetched.
BATCH = 256


class MigrationRefused(RuntimeError):
    """A typed refusal from the migration. Nothing is ever written behind one."""

    code = "migration_refused"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


class UnsupportedMigration(MigrationRefused):
    """The fingerprint differs somewhere other than ``sparse_version`` (or nowhere useful)."""

    code = "migration_unsupported"


class CollectionMissing(MigrationRefused):
    """There is no collection, or no fingerprint recorded for it, to migrate."""

    code = "migration_no_collection"


class PayloadUnreadable(MigrationRefused):
    """A stored payload does not validate as a :class:`~vsir.core.record.PageRecord`.

    Raised rather than skipped. A page whose sparse vectors were not rebuilt is a page that answers
    under the old recipe inside a collection stamped with the new one — the silent mix again, one
    page wide. The migration stops, the fingerprint is not written, and the boot check goes on
    refusing until somebody looks.
    """

    code = "migration_payload_unreadable"


@dataclass
class Rebuilt:
    """What the migration did, or would do under ``dry_run``. Printed; nothing branches on it."""

    collection: str
    stored: Fingerprint
    configured: Fingerprint
    dry_run: bool = False
    scanned: int = 0
    updated: int = 0
    #: Points with no sparse terms on either surface — a fully scanned page with no text layer and
    #: no generated text has nothing to rebuild, and writing it an empty vector would be wrong
    #: (:func:`~vsir.ingest.index.sparse_vectors`: absent, never zeroed).
    untouched: int = 0
    lexical_written: int = 0
    captions_written: int = 0
    #: ``(point_id, surface)`` for a surface that had a vector and now has no terms at all.
    surfaces_dropped: list[tuple[str, str]] = field(default_factory=list)
    fingerprint_written: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection, "dry_run": self.dry_run, "scanned": self.scanned,
            "updated": self.updated, "untouched": self.untouched,
            "lexical_written": self.lexical_written, "captions_written": self.captions_written,
            "surfaces_dropped": len(self.surfaces_dropped),
            "fingerprint_written": self.fingerprint_written,
            "from_version": self.stored.sparse_version,
            "to_version": self.configured.sparse_version,
            "from_digest": self.stored.digest, "to_digest": self.configured.digest,
        }


def _scroll(client: Any, collection: str, batch: int) -> Iterator[Sequence[Any]]:
    """Every point, in batches, carrying payload and the two sparse vectors — never the dense one.

    ``with_vectors`` names the two sparse surfaces explicitly. Fetching them is not decoration: it
    is the only way to know a surface is *currently present*, which is what distinguishes "this page
    never had generated text" from "this page had some and the new recipe scores none of it". The
    first needs nothing; the second needs a delete, because :meth:`update_vectors` has no way to
    express removal and an omitted name means *leave it alone*.
    """
    offset: Any = None
    while True:
        points, offset = client.scroll(
            collection_name=collection, limit=batch, offset=offset,
            with_payload=True, with_vectors=[LEXICAL, CAPTIONS],
        )
        if points:
            yield points
        if offset is None:
            return


def _record_of(point: Any, collection: str) -> PageRecord:
    payload = point.payload or {}
    try:
        return PageRecord.from_payload(dict(payload))
    except Exception as invalid:            # pydantic ValidationError, or a payload that is not one
        raise PayloadUnreadable(
            f"point {point.id} of {collection} does not validate as a PageRecord ({invalid}). The "
            f"sparse surfaces are derived from the payload, so a payload this release cannot read "
            f"is a page whose vectors cannot be rebuilt — and leaving one page on the old recipe "
            f"inside a collection stamped with the new one is the silent mix §6.6 exists to "
            f"prevent. Nothing further was written and the fingerprint was left alone",
            collection=collection, point_id=str(point.id),
        ) from invalid


def plan_migration(stored: Fingerprint, configured: Fingerprint) -> dict[str, tuple[Any, Any]]:
    """The differences, or a typed refusal naming why the cheap path does not apply.

    Separated from the write so the decision can be tested without a store, and so `--dry-run` and
    the real run reach it by the same route rather than by two similar ones.
    """
    differences = configured.differences(stored)
    if not differences:
        raise UnsupportedMigration(
            f"the stored fingerprint already matches this release ({configured.digest}): there is "
            f"nothing to rebuild. A migration that ran anyway would rewrite every sparse vector to "
            f"the value it already holds, which costs a full pass over the collection to achieve "
            f"nothing and would make a real migration indistinguishable from a no-op in the logs",
            collection_digest=stored.digest, configured=configured.as_dict(),
        )
    other = sorted(field_name for field_name in differences if field_name != REBUILDABLE)
    if other:
        detail = ", ".join(f"{name}: stored {differences[name][0]!r} != configured "
                           f"{differences[name][1]!r}" for name in other)
        raise UnsupportedMigration(
            f"this migration rebuilds the sparse surfaces only, and the fingerprint also differs "
            f"in {other} ({detail}). Those fields describe how the **dense** vector was made, and "
            f"no stored payload can re-derive one — rebuilding sparse here would stamp this "
            f"release onto a collection whose dense vectors came from a different recipe, which "
            f"is the in-place mix §6.6 forbids and whose only symptom is worse neighbours. The "
            f"remedy for a dense change is unchanged: a NEW collection, a full re-embed, an alias "
            f"swap. Nothing was written",
            fields=other, differences={name: list(pair) for name, pair in differences.items()},
            stored=stored.as_dict(), configured=configured.as_dict(),
        )
    return differences


def rebuild_sparse(client: Any, *, pages_collection: str, runs_collection: str,
                   configured: Fingerprint, batch: int = BATCH,
                   dry_run: bool = False) -> Rebuilt:
    """Re-derive `lexical` and `captions` from payload for every point, then restamp the recipe.

    Costs nothing and calls no model. Idempotent: it is a pure function of each payload, so a
    killed run is repaired by running it again — and because the fingerprint is written last, a
    killed run leaves the collection refused rather than half-published.
    """
    if not client.collection_exists(pages_collection):
        raise CollectionMissing(
            f"{pages_collection} does not exist: there is nothing to migrate, and creating it here "
            f"would produce an empty collection stamped with this release rather than a migrated "
            f"one",
            collection=pages_collection,
        )
    stored = fingerprint_module.read(client, runs_collection, pages_collection)
    if stored is None:
        raise CollectionMissing(
            f"{pages_collection} exists but {runs_collection} records no fingerprint for it, so "
            f"there is no statement of how its vectors were made and nothing to migrate *from*. "
            f"Adopting this release's recipe on the strength of the collection merely existing is "
            f"the assumption §6.6 was written to stop being made silently",
            collection=pages_collection, runs_collection=runs_collection,
        )

    plan_migration(stored, configured)
    report = Rebuilt(collection=pages_collection, stored=stored, configured=configured,
                     dry_run=dry_run)
    _log.info("resparse_started", collection=pages_collection, dry_run=dry_run,
              from_version=stored.sparse_version, to_version=configured.sparse_version,
              from_digest=stored.digest, to_digest=configured.digest)

    for points in _scroll(client, pages_collection, batch):
        updates: list[qm.PointVectors] = []
        drops: dict[str, list[Any]] = {LEXICAL: [], CAPTIONS: []}
        for point in points:
            report.scanned += 1
            rebuilt = sparse_vectors(_record_of(point, pages_collection))
            held = point.vector if isinstance(point.vector, dict) else {}
            gone = [name for name in (LEXICAL, CAPTIONS) if name in held and name not in rebuilt]
            for name in gone:
                drops[name].append(point.id)
                report.surfaces_dropped.append((str(point.id), name))
            if not rebuilt and not gone:
                report.untouched += 1
                continue
            if rebuilt:
                updates.append(qm.PointVectors(id=point.id, vector=dict(rebuilt)))
                report.lexical_written += 1 if LEXICAL in rebuilt else 0
                report.captions_written += 1 if CAPTIONS in rebuilt else 0
            report.updated += 1
        if dry_run:
            continue
        if updates:
            client.update_vectors(collection_name=pages_collection, points=updates, wait=True)
        for name, ids in drops.items():
            if ids:
                client.delete_vectors(collection_name=pages_collection, vectors=[name],
                                      points=ids, wait=True)

    if not dry_run:
        # Last, and only once every page is on the new recipe: this is the line that makes the
        # collection servable again, so it must not be able to run over a partial rebuild.
        fingerprint_module.write(client, runs_collection, pages_collection, configured)
        report.fingerprint_written = True
    _log.info("resparse_finished", **report.as_dict())
    return report


__all__ = [
    "BATCH", "REBUILDABLE", "CollectionMissing", "MigrationRefused", "PayloadUnreadable",
    "Rebuilt", "UnsupportedMigration", "plan_migration", "rebuild_sparse",
]
