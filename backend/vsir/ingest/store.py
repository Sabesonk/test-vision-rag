"""The document store — ``page_id`` → the bytes a raster is rendered from (§4.2, §15 Factor VI).

**Rasters are never persisted, and nothing kept the file to render them from.** That is the gap
this module closes, and the two halves of it are easy to conflate. §4.2's *"no blob store, no local
source of truth"* is a statement about **rasters**: they are re-rendered on demand into an
in-process LRU cache, a cold instance returns identical results and only more slowly, and no record
carries an ``image_path`` (§5.3, register **A5**). None of that says the **source document** may
vanish — and yet it did:

* a CLI ingest could render later only because the operator's copy was still on their filesystem —
  luck, not architecture, and not true of the instance serving the request;
* an upload spooled to ``/tmp/<run_id>.pdf`` and the reaper deleted it when the run exited;
* and nothing could even *name* the file. The page payload deliberately carries no path, and until
  this unit the run record carried no ``content_hash`` either, so given
  ``SICK-UE410-SD400@1.0#p002`` there was no route from page → document → bytes.

So this is a store of **sources**, not of derived artefacts, and the distinction is what keeps
§4.2 intact: re-rendering on demand stays true, and it now has something to re-render *from*.

**Identity-addressed, integrity-checked.** The file is ``<doc_id>@<revision>.pdf`` — derivable from
any ``page_id`` through :func:`vsir.core.ids.parse_page_id`, so **no path goes in a payload** and
A5's fix stands: the payload names the *document*, the store resolves the *file*. A pure
content-addressed layout (``<sha256>.pdf``) would have needed a hash in the payload or a second
index to find one, which is the same coupling by another name. The hash is not dropped, it moves:
``content_hash`` is recorded on the run record (§6.9), and :meth:`DocumentStore.locate` refuses to
serve bytes that disagree with the hash the caller expects. That matters most in the one case that
otherwise fails silently — a ``(doc_id, revision)`` re-ingested from corrected bytes, where the
index still holds the *previous* run's pages until publish retires them (§6.7). Rendering the new
file for an old page would answer with a page nobody indexed. A named refusal is the honest answer.

**A miss is a typed refusal naming the document.** Never a placeholder image, never a 500, never an
empty result — §11.3, and the same reason a backend failure is a 5xx rather than "no hits": a page
that exists in the index and cannot be shown is a different fact from a page that does not exist.

**It is a mounted volume, not the instance's disk.** ``VSIR_DOC_STORE`` names it and the deployment
supplies it (§15 Factor III); every process type of the release — ``web``, an ingest worker, a
one-off ``vsir`` admin command — reads and writes the same one. Nothing here is a source of truth
about *retrieval*: the index is, and a store with a missing entry costs an image, not an answer.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from vsir import logging as vsir_logging
from vsir.core import ids
from vsir.ingest import render as render_module

_log = vsir_logging.get_logger(__name__)

#: Where documents live. Not one of the twelve required variables (§15 Factor III's contract with
#: `doctor`) for the same reason ``VSIR_SPOOL_DIR`` is not: a release that never ingests and never
#: serves an image must not be made unstartable by it. Unset means a directory under the platform's
#: temporary directory, which is what a disposable instance has and is honest about being ephemeral
#: — a deployment that wants a document to outlive its container mounts a volume and names it here.
STORE_ENV = "VSIR_DOC_STORE"

#: The default directory name under the platform temporary directory.
DEFAULT_DIRNAME = "vsir-documents"

#: The corpus is PDFs (§2.1) and the renderer is PyMuPDF, so there is one extension and no
#: content sniffing anywhere in this module.
SUFFIX = ".pdf"

#: Where :meth:`DocumentStore.put` writes before it renames. Inside the root, so the rename is on
#: one filesystem and therefore atomic, and dot-prefixed so it is not a document.
STAGING = ".staging"

#: What may appear in the file name. ``doc_id`` is already a slug (`ids.slug`), but ``revision`` is
#: the operator's own string and ``page_id`` — which a caller may supply from a saved citation —
#: parses a revision as anything but ``@`` and ``#``. So a separator, a ``..`` or a leading dot
#: reaching :func:`Path` here would be a path traversal with a citation as its payload.
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class StoreRefused(RuntimeError):
    """A typed refusal from the document store, shaped like every other one (§7.3, §11.3)."""

    code = "store_refused"
    http_status = 503

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


class DocumentNotStored(StoreRefused):
    """No bytes for this ``doc_id@revision``. A 5xx: the page exists, the image cannot be made."""

    code = "document_not_stored"


class DocumentHashMismatch(StoreRefused):
    """The stored bytes are not the bytes the run indexed. Refused rather than served."""

    code = "document_hash_mismatch"


class DocumentIdUnsafe(StoreRefused):
    """A ``doc_id`` or ``revision`` that cannot be a file name. A 400: it is about the input."""

    code = "document_id_unsafe"
    http_status = 400


class StoreUnwritable(StoreRefused):
    """The volume is not there, or not writable. Named before a run spends, never after."""

    code = "document_store_unwritable"


@dataclass(frozen=True)
class StoredDocument:
    """One document in the store: what it is, where it is, and what it weighs."""

    doc_id: str
    revision: str
    path: Path

    @property
    def name(self) -> str:
        """``"TC1E-SF@1.3"`` — how a refusal names the document a page could not be rendered from."""
        return f"{self.doc_id}@{self.revision}"

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size

    @property
    def content_hash(self) -> str:
        """SHA-256 of the stored bytes — the same digest ``probe.content_hash`` computes.

        Through :func:`vsir.ingest.render.source_hash`, which memoises on ``(path, size, mtime_ns)``
        — so a `web` process serving a hundred page images of one document hashes the file once,
        and re-hashes exactly when the file underneath it changes.
        """
        stat = self.path.stat()
        return render_module.source_hash(str(self.path), stat.st_size, stat.st_mtime_ns)

    @property
    def stored_at(self) -> str:
        return datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc).isoformat()


@dataclass(frozen=True)
class PageSource:
    """A resolved ``page_id``: the document to open and the 1-based page to render."""

    document: StoredDocument
    page_no: int
    page_id: str

    @property
    def path(self) -> Path:
        return self.document.path


def safe_component(kind: str, value: str) -> str:
    """One half of the file name, or a typed refusal. Never a silently mangled name.

    Mangling is the tempting alternative and it is worse than refusing: two revisions that differ
    only in an unsafe character would collapse onto one file, so one document's bytes would be
    served for the other's pages. This refuses at ingest — step 02, before any spend past the
    probe — where the operator can still correct the value they typed.
    """
    if not SAFE_COMPONENT.match(value or ""):
        raise DocumentIdUnsafe(
            f"{kind} {value!r} cannot name a file in the document store: it must match "
            f"{SAFE_COMPONENT.pattern} — alphanumeric, then any of . _ + -. A separator or a "
            f"'..' here would be a path traversal carried by a citation, and mangling it instead "
            f"would let two revisions share one file",
            **{kind: value})
    return value


def file_name(doc_id: str, revision: str) -> str:
    """``("TC1E-SF", "1.3")`` → ``"TC1E-SF@1.3.pdf"``. Both halves validated (§5.1)."""
    return f"{safe_component('doc_id', doc_id)}@{safe_component('revision', revision)}{SUFFIX}"


def split_file_name(name: str) -> tuple[str, str]:
    """``"TC1E-SF@1.3.pdf"`` → ``("TC1E-SF", "1.3")``. The inverse, for listing the store.

    Split on the **last** ``@``: neither half may contain one — ``ids.slug`` folds it out of a
    ``doc_id`` and :data:`SAFE_COMPONENT` refuses it in a revision — so the split is unambiguous.
    """
    stem = name[: -len(SUFFIX)] if name.endswith(SUFFIX) else name
    doc_id, sep, revision = stem.rpartition("@")
    if not sep:
        raise DocumentIdUnsafe(f"{name!r} is not a <doc_id>@<revision>{SUFFIX} document",
                               file_name=name)
    return safe_component("doc_id", doc_id), safe_component("revision", revision)


def store_root(configured: str = "") -> Path:
    """The directory documents live in. Configuration only — never a path chosen in code."""
    if configured.strip():
        return Path(configured.strip()).expanduser()
    return Path(tempfile.gettempdir()) / DEFAULT_DIRNAME


@dataclass(frozen=True)
class DocumentStore:
    """The store, as one directory. Frozen and stateless: it holds a path, never a cache.

    Constructed per call site rather than held as a module singleton, which is the §15.2 ban on a
    module-level mutable store applied to something that looks harmless: a cached handle would be
    process state that two apps in one test process — or two configurations in one release — would
    silently share.
    """

    root: Path

    @classmethod
    def from_config(cls, cfg: Any) -> "DocumentStore":
        """The store this process's configuration names (§15 Factor III)."""
        return cls(store_root(getattr(cfg, "doc_store", "") or ""))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "DocumentStore":
        """For the one caller that has an environment and not a :class:`~vsir.config.Config`."""
        source = env if env is not None else os.environ
        return cls(store_root(source.get(STORE_ENV) or ""))

    # ── locating ────────────────────────────────────────────────────────────────────────────────

    def path_for(self, doc_id: str, revision: str) -> Path:
        """Where this document's bytes belong. Pure — it does not touch the filesystem."""
        return self.root / file_name(doc_id, revision)

    def holds(self, doc_id: str, revision: str) -> bool:
        return self.path_for(doc_id, revision).is_file()

    def locate(self, doc_id: str, revision: str, *, expect_hash: str = "") -> StoredDocument:
        """The stored document, or a typed refusal naming ``doc_id@revision``.

        ``expect_hash`` is the run record's ``content_hash``. Passing it is what turns *"a file is
        there"* into *"the bytes this document was indexed from are there"*, and the two differ
        exactly when someone re-ingested the same ``(doc_id, revision)`` from a corrected file.
        """
        document = StoredDocument(doc_id=doc_id, revision=revision,
                                  path=self.path_for(doc_id, revision))
        if not document.path.is_file():
            raise DocumentNotStored(
                f"no source document for {document.name} in the store at {self.root}. The page is "
                f"indexed and its image cannot be rendered: rasters are re-rendered on demand "
                f"(§4.2), so the source has to be here. Re-ingest the document, or mount the "
                f"volume {STORE_ENV} names",
                doc_id=doc_id, revision=revision, document=document.name, store=str(self.root))
        if expect_hash and document.content_hash != expect_hash:
            raise DocumentHashMismatch(
                f"the stored bytes for {document.name} hash to {document.content_hash[:12]} and "
                f"the run that indexed these pages recorded {expect_hash[:12]}. The file behind "
                f"this document was replaced; rendering it would answer with a page nobody "
                f"indexed. Re-ingest {document.name} so the index and the source agree",
                doc_id=doc_id, revision=revision, document=document.name,
                stored_hash=document.content_hash, expected_hash=expect_hash)
        return document

    def for_page(self, page_id: str, *, expect_hash: str = "") -> PageSource:
        """``page_id`` → the document to open and the page to render. The one job (§5.1).

        The parse is :func:`vsir.core.ids.parse_page_id`, so only the canonical spelling resolves
        and a malformed citation is a ``ValueError`` here rather than a guess at which page was
        meant (§7.2.3).
        """
        doc_id, revision, page_no = ids.parse_page_id(page_id)
        return PageSource(document=self.locate(doc_id, revision, expect_hash=expect_hash),
                          page_no=page_no, page_id=page_id)

    def entries(self) -> tuple[StoredDocument, ...]:
        """Every document in the store, in name order. What ``vsir documents`` prints."""
        if not self.root.is_dir():
            return ()
        found = []
        for path in sorted(self.root.glob(f"*{SUFFIX}")):
            try:
                doc_id, revision = split_file_name(path.name)
            except DocumentIdUnsafe:      # something else put a PDF here; it is not a document
                continue
            found.append(StoredDocument(doc_id=doc_id, revision=revision, path=path))
        return tuple(found)

    # ── writing ─────────────────────────────────────────────────────────────────────────────────

    def ensure_writable(self) -> Path:
        """Create the root and prove it can be written to. Called before a run spends anything.

        The check is a real write and not ``os.access``: a read-only bind mount, a full volume and
        a directory owned by another uid all answer differently to the two, and the one that
        matters is whether :meth:`put` will work in a minute's time.
        """
        probe = self.root / STAGING / f".writable-{uuid.uuid4().hex}"
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as failure:
            raise StoreUnwritable(
                f"the document store at {self.root} is not writable: "
                f"{type(failure).__name__}: {failure}. Ingesting into a release whose store "
                f"cannot be written would publish pages whose image can never be rendered — so "
                f"it is refused here, before anything is spent",
                # `os_error` and not `reason`: a refusal's details are splatted into the log line
                # beside the caller's own `reason=<code>`, and a collision is a TypeError that
                # replaces a clean named refusal with a traceback. Found by running the stack.
                store=str(self.root), os_error=type(failure).__name__) from failure
        return self.root

    def put(self, doc_id: str, revision: str, *, source: Path | None = None,
            body: bytes | None = None, content_hash: str = "") -> StoredDocument:
        """Deposit a document's bytes under ``<doc_id>@<revision>.pdf``. Idempotent.

        Written to :data:`STAGING` and renamed, so a reader never sees a half-written PDF and a
        killed writer leaves a temporary file rather than a truncated document (F17).

        Re-depositing **different** bytes under the same ``(doc_id, revision)`` is allowed — it is
        what a corrected re-ingest is — and it is logged rather than refused, because the run that
        deposited them is also the run that will retire the previous one's pages (§6.7). What makes
        that safe in the window between the two is ``expect_hash`` on :meth:`locate`: until publish
        retires them, the previous run's pages ask for a hash this file no longer has and get a
        named refusal instead of the wrong image.
        """
        if (source is None) == (body is None):
            raise ValueError("put takes exactly one of `source` or `body`")
        destination = self.path_for(doc_id, revision)
        if source is not None and source.resolve() == destination.resolve():
            # A resumed run re-ingesting straight out of the store. Nothing to copy, and copying a
            # file onto itself through a rename would empty it.
            return self.locate(doc_id, revision, expect_hash=content_hash)

        previous = ""
        if destination.is_file():
            previous = StoredDocument(doc_id=doc_id, revision=revision,
                                      path=destination).content_hash
        self.ensure_writable()
        staged = self.root / STAGING / f"{uuid.uuid4().hex}{SUFFIX}"
        try:
            if source is not None:
                # Streamed, not `read_bytes()`: the upload boundary already holds one copy of the
                # body in memory and the corpus's largest document is 310 MB, so a second full
                # copy here would be a memory spike proportional to the document.
                shutil.copyfile(source, staged)
            else:
                staged.write_bytes(body or b"")
            os.replace(staged, destination)
        except OSError as failure:
            staged.unlink(missing_ok=True)
            raise StoreUnwritable(
                f"could not deposit {doc_id}@{revision} in the document store at {self.root}: "
                f"{type(failure).__name__}: {failure}",
                store=str(self.root), doc_id=doc_id, revision=revision) from failure

        stored = StoredDocument(doc_id=doc_id, revision=revision, path=destination)
        if content_hash and stored.content_hash != content_hash:
            raise DocumentHashMismatch(
                f"{stored.name} was written to the store and hashes to {stored.content_hash[:12]}, "
                f"not the {content_hash[:12]} the run computed from the same file. The bytes "
                f"changed underneath the run; nothing downstream may assume otherwise",
                doc_id=doc_id, revision=revision, document=stored.name,
                stored_hash=stored.content_hash, expected_hash=content_hash)
        _log.info("document_stored", doc_id=doc_id, revision=revision,
                  document=stored.name, bytes=stored.size_bytes,
                  content_hash=stored.content_hash, replaced=bool(previous),
                  previous_hash=previous)
        if previous and previous != stored.content_hash:
            _log.warning(
                "document_replaced", doc_id=doc_id, revision=revision, document=stored.name,
                previous_hash=previous, content_hash=stored.content_hash,
                detail="the same (doc_id, revision) was re-ingested from different bytes. Pages "
                       "of the previous run are refused a raster until publish retires them "
                       "(§6.7), because their run recorded the previous hash")
        return stored
