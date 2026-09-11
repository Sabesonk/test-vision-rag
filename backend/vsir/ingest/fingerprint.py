"""The embedding fingerprint (Spec §6.6). Written net new — `impl` has no equivalent.

    The collection stores ``{embed_model, dim, distance, composition_version}``. On mismatch:
    **refuse to upsert.** A model change is a new collection + full re-embed + alias swap, never
    an in-place mix.

The failure this prevents is quiet, and `impl` demonstrates it. Its record of *how* a page was
embedded is the string ``f"{CFG.embed_model}|{CFG.seg_dim}"`` stored on the point — where
``embed_model`` was a floating alias (register B6) and nothing ever compared it to anything. So a
model change, a dim change or a change to the composition would put two incompatible families of
vector in one cosine space, and the only symptom is worse neighbours: no error, no log line, and
no way afterwards to tell which points belong to which family.

**Why a fourth field.** ``embed_model`` and ``dim`` are the obvious two, and ``distance`` is cheap.
``composition_version`` is the one that is easy to leave out and is the one this system needs most:
the vector is a *fused* image+text embedding whose meaning depends entirely on which parts were
sent and in what order (§5.3, D4). Reordering the parts or dropping the raster changes every vector
without changing the model id, so a fingerprint without it would agree with a collection whose
contents it no longer describes.

**Why a fifth field.** The same argument, one surface over. The two sparse vectors are scored by a
recipe that is now half client-side (:mod:`vsir.ingest.sparse` writes BM25's tf component; Qdrant
supplies the idf factor). A BM25 collection and a raw-term-frequency collection are byte-identical
in shape, declare the same ``Modifier.IDF``, pass every schema check in
:mod:`vsir.core.indexed` — and differ only in what the stored floats *mean*. A process configured
for one and serving the other returns worse neighbours and no error, which is precisely the silent
failure ``composition_version`` exists to prevent.

**Where it lives.** Qdrant has no collection-level metadata, and §4.2 allows exactly two
collections — so the fingerprint is a point in the **control plane**, ``vsir_runs`` (D9): one
point per pages collection, discriminated by ``kind``. That collection holds runs, windows and
the observed-token inventory (U011), and every one of them is a record *about* the index rather
than a page in it, which is what this is too. The alternative — a sentinel point inside
``vsir_pages`` — was rejected because it would put a non-page point in a collection whose point
count is I1's assertion.

Two halves of §6.6, checked in two places, and both are needed:

* ``dim`` and ``distance`` are observable from the live collection, and
  :func:`vsir.core.indexed.schema_problems` already reads them back at boot (§4.3);
* ``embed_model`` and ``composition_version`` are **not** observable from Qdrant, so they are
  recorded here and compared next to the write, where the money is (:mod:`vsir.ingest.index`).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from qdrant_client.http import models as qm

from vsir import logging as vsir_logging
from vsir.config import COMPOSITION_VERSION, DISTANCE, SPARSE_VERSION, Config
from vsir.core.ids import NAMESPACE

_log = vsir_logging.get_logger(__name__)

#: The payload discriminator on a control-plane point. ``vsir_runs`` holds several kinds of record
#: — this one, and U011's run, window and observed-token points — so every one says which it is
#: rather than being told apart by which fields it happens to carry.
KIND = "fingerprint"
KIND_KEY = "kind"

#: The §6.6 field set, in the order the spec names them. The fifth, ``sparse_version``, was added
#: as a release and did exactly what this comment used to warn a fifth field would do: it re-keyed
#: every collection and refused every existing one, which is the point. A *sixth* would do the same
#: again — that is the cost, and it is the correct cost for a change to how a vector is made.
FIELDS: tuple[str, ...] = ("embed_model", "dim", "distance", "composition_version",
                           "sparse_version")


class FingerprintMismatch(RuntimeError):
    """The live collection was embedded by a different recipe than this process is configured for.

    Deliberately **not** a warning and not a repair. The remedy is in the message because it is
    not obvious and it is not "fix the config": if the collection was right, the process is
    misconfigured; if the process is right, the collection needs rebuilding — and rebuilding means
    a *new* collection, a full re-embed and an alias swap, because there is no way to convert a
    vector from one recipe into the other.
    """

    code = "embed_fingerprint_mismatch"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


@dataclass(frozen=True)
class Fingerprint:
    """``{embed_model, dim, distance, composition_version, sparse_version}``: how it was made."""

    embed_model: str
    dim: int
    distance: str = DISTANCE
    composition_version: str = COMPOSITION_VERSION
    sparse_version: str = SPARSE_VERSION

    @classmethod
    def of(cls, cfg: Config) -> "Fingerprint":
        """What this process would write, from :attr:`vsir.config.Config.fingerprint`."""
        return cls.from_mapping(cfg.fingerprint)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "Fingerprint":
        missing = [field for field in FIELDS if field not in values]
        if missing:
            raise FingerprintMismatch(
                f"a stored fingerprint is missing {missing}: the recipe is "
                f"{list(FIELDS)}, "
                f"and a record that omits one cannot say whether it matches",
                missing=missing, stored=dict(values),
            )
        return cls(embed_model=str(values["embed_model"]), dim=int(values["dim"]),
                   distance=str(values["distance"]),
                   composition_version=str(values["composition_version"]),
                   sparse_version=str(values["sparse_version"]))

    def as_dict(self) -> dict[str, Any]:
        return {"embed_model": self.embed_model, "dim": self.dim, "distance": self.distance,
                "composition_version": self.composition_version,
                "sparse_version": self.sparse_version}

    @property
    def digest(self) -> str:
        """A short stable digest — what `vsir doctor` prints and a log line carries."""
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def differences(self, other: "Fingerprint") -> dict[str, tuple[Any, Any]]:
        """``{field: (stored, configured)}`` per differing field. Empty means it matches."""
        mine, theirs = other.as_dict(), self.as_dict()
        return {field: (mine[field], theirs[field])
                for field in FIELDS if mine[field] != theirs[field]}


def point_id(pages_collection: str) -> str:
    """The control point for one pages collection. Derived, so writing it twice is idempotent."""
    if not pages_collection:
        raise ValueError("a fingerprint belongs to a named collection")
    return str(uuid.uuid5(NAMESPACE, f"vsir:fingerprint:{pages_collection}"))


def ensure_control_collection(client: Any, runs_collection: str) -> bool:
    """Create ``vsir_runs`` if it is absent. Returns False if it already existed.

    **Payload only** — ``vectors_config={}``. Nothing in the control plane is searched by
    similarity: a run, a window and a fingerprint are all looked up by id or by an exact filter,
    and declaring a vector nobody writes would only invite one.
    """
    if client.collection_exists(runs_collection):
        return False
    client.create_collection(collection_name=runs_collection, vectors_config={})
    client.create_payload_index(runs_collection, field_name=KIND_KEY,
                                field_schema=qm.PayloadSchemaType.KEYWORD)
    client.create_payload_index(runs_collection, field_name="collection",
                                field_schema=qm.PayloadSchemaType.KEYWORD)
    _log.info("control_collection_created", collection=runs_collection)
    return True


def read(client: Any, runs_collection: str, pages_collection: str) -> Fingerprint | None:
    """The fingerprint recorded for ``pages_collection``, or None if there is none yet."""
    if not client.collection_exists(runs_collection):
        return None
    found = client.retrieve(runs_collection, ids=[point_id(pages_collection)], with_payload=True)
    if not found:
        return None
    payload = found[0].payload or {}
    if payload.get(KIND_KEY) != KIND:
        raise FingerprintMismatch(
            f"the control point for {pages_collection} is a {payload.get(KIND_KEY)!r} record, not "
            f"a {KIND!r} one",
            collection=pages_collection, kind=payload.get(KIND_KEY),
        )
    return Fingerprint.from_mapping(payload)


def write(client: Any, runs_collection: str, pages_collection: str,
          fingerprint: Fingerprint) -> Fingerprint:
    """Record the fingerprint for ``pages_collection``. The id is derived, so this is idempotent."""
    ensure_control_collection(client, runs_collection)
    client.upsert(
        collection_name=runs_collection,
        points=[qm.PointStruct(
            id=point_id(pages_collection),
            vector={},
            payload={KIND_KEY: KIND, "collection": pages_collection, "digest": fingerprint.digest,
                     **fingerprint.as_dict()},
        )],
        wait=True,
    )
    _log.info("fingerprint_written", collection=pages_collection, digest=fingerprint.digest,
              **fingerprint.as_dict())
    return fingerprint


def require(client: Any, *, runs_collection: str, pages_collection: str,
            fingerprint: Fingerprint) -> Fingerprint:
    """The §6.6 gate: agree with the stored fingerprint, or **refuse** — write nothing either way.

    A collection with no fingerprint yet takes this one, which is the first-ingest case and the
    only way a record is ever created. Every other outcome is the refusal: there is no path here
    that updates a stored fingerprint in place, because that is precisely the in-place mix §6.6
    rules out.
    """
    stored = read(client, runs_collection, pages_collection)
    if stored is None:
        return write(client, runs_collection, pages_collection, fingerprint)
    differences = fingerprint.differences(stored)
    if differences:
        detail = ", ".join(f"{field}: stored {was!r} != configured {now!r}"
                           for field, (was, now) in sorted(differences.items()))
        raise FingerprintMismatch(
            f"{pages_collection} was embedded under a different recipe ({detail}). Refusing to "
            f"upsert: a vector made one way cannot be compared with one made another, so the "
            f"remedy is a NEW collection, a full re-embed of every document into it, and an alias "
            f"swap — never an in-place mix (§6.6). Nothing was written",
            collection=pages_collection, differences={field: list(pair)
                                                      for field, pair in differences.items()},
            stored=stored.as_dict(), configured=fingerprint.as_dict(),
            stored_digest=stored.digest, configured_digest=fingerprint.digest,
        )
    return stored
